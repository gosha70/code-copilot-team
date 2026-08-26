# tests/test_routing_eval_injection.py — routing-eval (E1 of #109) T2.
#
# Two load-bearing suites here. TestClassificationParity shells out to
# the REAL, unmodified rr_classify (scripts/lib/routing-result.sh) and
# asserts an injected transcript classifies exactly like the equivalent
# real provider response — the injected usage-limit shape is the same
# envelope the recovery suite's own capture fixtures use. And
# TestNoProductionRoutingFileTouched is the diff guard plan.md decision
# 2 promises: passing suites alone does not prove runtime behaviour was
# untouched; this test fails the moment the increment's diff reaches a
# production routing file.

from __future__ import annotations

import json
import subprocess
import time
import unittest
from pathlib import Path

from benchmark_runner.routing_eval.cost_reader import measured_cost
from benchmark_runner.routing_eval.injection import (
    TIMEOUT_EXIT_CODE,
    events_for_task,
    materialize_replay,
    preset_digest,
    reset_replay,
    transcript_for_event,
)
from benchmark_runner.routing_eval.scenario_config import InjectedEvent, validate_scenario_config

REPO_ROOT = Path(__file__).resolve().parents[3]
RESULT_LIB = REPO_ROOT / "scripts" / "lib" / "routing-result.sh"
PROBE_LIB = REPO_ROOT / "scripts" / "lib" / "routing-probe.sh"

# The same profile shapes the recovery suite's own rb_probe tests use.
_PJ_CHAT = (
    '{"id":"beta","backend":"pi","model":"qwen","tool_profile":"chat-only",'
    '"credential_ref":"none","endpoint_ref":"none"}'
)
_PJ_TOOL = (
    '{"id":"alpha","backend":"claude-code","model":"sonnet",'
    '"tool_profile":"full-cct","credential_ref":"none","endpoint_ref":"none"}'
)


def _rb_probe(cmd: str, profile_json: str, tmpdir: Path) -> str:
    """Drive the REAL rb_probe with our replay as the probe command."""
    ledger = tmpdir / "probe-ledger.json"
    proc = subprocess.run(
        [
            "bash", "-c",
            f'set +e; export CCT_ROUTING_PROBE_LEDGER="{ledger}" '
            f"CCT_ROUTING_PROBE_CMD={json.dumps(cmd)}; "
            f'source "{PROBE_LIB}"; '
            f"rb_probe '{profile_json}' 1",
        ],
        capture_output=True, text=True,
    )
    # rb_probe echoes "outcome<TAB>detail<TAB>evidence"
    return proc.stdout.strip().split("\t")[0] if proc.stdout.strip() else proc.stderr

_FULL_ARMS = [
    {"kind": "always_best"},
    {"kind": "always_cheapest"},
    {"kind": "oracle"},
    {"kind": "cct_router", "registry": "routing.toml"},
]


def _config(**overrides):
    payload = {
        "benchmark": "stub",
        "scenario": "hybrid-routing",
        "cost_basis": "measured",
        "arms": _FULL_ARMS,
        "trials": 2,
        "trial_seeds": [1701, 1702],
        "event_stream": [
            {"at_task_index": 0, "outcome": "usage_limit",
             "reset_at": "2099-07-01T00:00:00Z", "retry_after_sec": 900},
            {"at_task_index": 1, "outcome": "success"},
        ],
    }
    payload.update(overrides)
    return validate_scenario_config(payload)


def _classify(rc: int, text: str, tmpdir: Path) -> dict:
    """Run the REAL rr_classify on a transcript; return its JSON."""
    out = tmpdir / "capture.out"
    out.write_text(text, encoding="utf-8")
    proc = subprocess.run(
        ["bash", "-c", f'source "{RESULT_LIB}" && rr_classify {rc} "{out}"'],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


class TestPresetDigest(unittest.TestCase):
    def test_same_config_same_digest(self) -> None:
        self.assertEqual(preset_digest(_config()), preset_digest(_config()))
        self.assertTrue(preset_digest(_config()).startswith("sha256:"))

    def test_every_shaping_field_moves_the_digest(self) -> None:
        base = preset_digest(_config())
        variants = {
            "seed": _config(trial_seeds=[1701, 9999]),
            "trials": _config(trials=3, trial_seeds=[1, 2, 3]),
            "event outcome": _config(event_stream=[
                {"at_task_index": 0, "outcome": "server_error"},
                {"at_task_index": 1, "outcome": "success"},
            ]),
            "event order": _config(event_stream=[
                {"at_task_index": 1, "outcome": "success"},
                {"at_task_index": 0, "outcome": "usage_limit",
                 "reset_at": "2099-07-01T00:00:00Z", "retry_after_sec": 900},
            ]),
            "event timing": _config(event_stream=[
                {"at_task_index": 0, "outcome": "usage_limit",
                 "reset_at": "2099-08-01T00:00:00Z", "retry_after_sec": 900},
                {"at_task_index": 1, "outcome": "success"},
            ]),
            "arm set": _config(
                arms=_FULL_ARMS + [{"kind": "oracle_budget"}],
                budget_ceiling_usd=1.0,
            ),
            "cost basis": _config(cost_basis="estimated@price-table-v1"),
        }
        for label, cfg in variants.items():
            with self.subTest(changed=label):
                self.assertNotEqual(base, preset_digest(cfg))


class TestDeterministicTranscripts(unittest.TestCase):
    def test_same_event_same_bytes(self) -> None:
        event = InjectedEvent(0, "usage_limit", "2099-07-01T00:00:00Z", 900)
        self.assertEqual(transcript_for_event(event), transcript_for_event(event))

    def test_timeout_has_no_output_and_the_bounded_exit_code(self) -> None:
        text, code = transcript_for_event(InjectedEvent(0, "timeout"))
        self.assertEqual(text, "")
        self.assertEqual(code, TIMEOUT_EXIT_CODE)

    def test_unknown_outcome_refuses(self) -> None:
        with self.assertRaises(ValueError):
            transcript_for_event(InjectedEvent(0, "gremlins"))


class TestTaskScheduling(unittest.TestCase):
    """at_task_index addresses a TASK; the filter is the boundary."""

    def test_event_declared_for_task_5_never_reaches_task_0(self) -> None:
        events = [
            InjectedEvent(5, "usage_limit", "2099-07-01T00:00:00Z", None),
            InjectedEvent(0, "server_error"),
            InjectedEvent(0, "success"),
        ]
        self.assertEqual(
            [e.outcome for e in events_for_task(events, 0)],
            ["server_error", "success"],
        )
        self.assertEqual(
            [e.outcome for e in events_for_task(events, 5)], ["usage_limit"]
        )
        self.assertEqual(events_for_task(events, 3), [])

    def test_within_task_order_is_declaration_order(self) -> None:
        events = [
            InjectedEvent(1, "server_error"),
            InjectedEvent(1, "usage_limit"),
        ]
        self.assertEqual(
            [e.outcome for e in events_for_task(events, 1)],
            ["server_error", "usage_limit"],
        )


class TestReplayScript(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self.dir = Path(tempfile.mkdtemp(prefix="cct-inject-test."))
        self.events = [
            InjectedEvent(0, "usage_limit", "2099-07-01T00:00:00Z", 900),
            InjectedEvent(1, "server_error"),
            InjectedEvent(2, "success"),
        ]

    def _invoke(self, cmd: str, stdin: str = "") -> tuple[str, int]:
        proc = subprocess.run(
            ["bash", "-c", cmd], input=stdin, capture_output=True, text=True
        )
        return proc.stdout, proc.returncode

    def test_replays_the_stream_in_order_then_defaults(self) -> None:
        cmd = materialize_replay(self.events, self.dir)
        seen = [self._invoke(cmd) for _ in range(4)]
        expected = [transcript_for_event(e) for e in self.events]
        for i, (want_text, want_code) in enumerate(expected):
            self.assertEqual(seen[i], (want_text, want_code), f"event {i}")
        # Past the stream: the declared success default, not a repeat.
        text, code = seen[3]
        self.assertEqual(code, 0)
        self.assertIn('"type":"result"', text)

    def test_two_runs_of_one_preset_see_the_same_events(self) -> None:
        cmd = materialize_replay(self.events, self.dir)
        first = [self._invoke(cmd) for _ in range(3)]
        reset_replay(self.dir)
        second = [self._invoke(cmd) for _ in range(3)]
        self.assertEqual(first, second)

    def test_two_materializations_are_byte_identical(self) -> None:
        import tempfile

        other = Path(tempfile.mkdtemp(prefix="cct-inject-test2."))
        materialize_replay(self.events, self.dir)
        materialize_replay(self.events, other)
        for f in sorted(self.dir.glob("event-*")):
            with self.subTest(file=f.name):
                self.assertEqual(
                    f.read_bytes(), (other / f.name).read_bytes()
                )

    def test_injected_timeout_consumes_no_wall_clock(self) -> None:
        cmd = materialize_replay([InjectedEvent(0, "timeout")], self.dir)
        started = time.monotonic()
        text, code = self._invoke(cmd)
        elapsed = time.monotonic() - started
        self.assertEqual(code, TIMEOUT_EXIT_CODE)
        self.assertEqual(text, "")
        # The shape of a timeout without the wait. Seconds of slack for
        # slow CI hosts; a real bound would be minutes.
        self.assertLess(elapsed, 5.0)

    def test_probe_seam_echoes_the_prompts_nonce(self) -> None:
        # A canned reply can never pass the probe: routing-probe.sh
        # derives a per-launch nonce. The probe replay's pass is a
        # FUNCTION of the prompt, like a live backend's.
        cmd = materialize_replay([], self.dir, seam="probe")
        prompt = "Health canary. Reply with exactly this single line: CCT_PROBE_OK:deadbeef1234\n"
        text, code = self._invoke(cmd, stdin=prompt)
        self.assertEqual(code, 0)
        record = json.loads(text)
        self.assertEqual(record["result"], "CCT_PROBE_OK:deadbeef1234")
        # And the emitted spend reads as a measured cost.
        self.assertEqual(measured_cost(text), 0.0001)

    def test_probe_seam_replays_failures_before_passing(self) -> None:
        cmd = materialize_replay([InjectedEvent(0, "auth_failure")], self.dir, seam="probe")
        text, code = self._invoke(cmd, stdin="prompt\n")
        self.assertEqual(code, 1)
        self.assertIn("authentication_error", text)
        text2, code2 = self._invoke(
            cmd, stdin="Reply with exactly this single line: CCT_PROBE_OK:x\n"
        )
        self.assertEqual(code2, 0)
        self.assertEqual(json.loads(text2)["result"], "CCT_PROBE_OK:x")


class TestReplayRobustness(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self.base = Path(tempfile.mkdtemp(prefix="cct-inject-rb."))

    def test_overlapping_invocations_lose_no_events(self) -> None:
        # 30 distinguishable events + 10 past-stream defaults, all
        # launched concurrently: the atomic index claim must deliver
        # every event exactly once.
        events = [
            InjectedEvent(0, "usage_limit", f"2099-01-{d:02d}T00:00:00Z", None)
            for d in range(1, 31)
        ]
        cmd = materialize_replay(events, self.base)
        procs = [
            subprocess.Popen(
                ["bash", "-c", cmd],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            )
            for _ in range(40)
        ]
        outputs = [p.communicate()[0] for p in procs]
        expected = {transcript_for_event(e)[0] for e in events}
        seen = [o for o in outputs if o in expected]
        self.assertEqual(len(seen), 30, "an event was lost or duplicated")
        self.assertEqual(set(seen), expected)
        defaults = [o for o in outputs if '"type":"result"' in o]
        self.assertEqual(len(defaults), 10)

    def test_missing_declared_evidence_fails_closed(self) -> None:
        # The owner's reproduction: deleting an injected auth-failure
        # transcript turned it into a nonce pass. A declared index with
        # missing or corrupt evidence must be neither success nor a
        # clean provider failure — exit 70, message on stderr.
        events = [InjectedEvent(0, "auth_failure")]
        cmd = materialize_replay(events, self.base, seam="probe")
        (self.base / "event-000.out").unlink()
        proc = subprocess.run(
            ["bash", "-c", cmd],
            input="Reply with exactly this single line: CCT_PROBE_OK:x\n",
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 70)
        self.assertIn("failing closed", proc.stderr)
        self.assertNotIn("CCT_PROBE_OK", proc.stdout)

    def test_missing_rc_file_also_fails_closed(self) -> None:
        events = [InjectedEvent(0, "server_error")]
        cmd = materialize_replay(events, self.base)
        (self.base / "event-000.rc").unlink()
        proc = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 70)

    def test_declared_pass_mode_is_consulted_mid_stream(self) -> None:
        # pass at index 0, failure at index 1 — the mode file must be
        # read, not inferred from absence.
        events = [InjectedEvent(0, "success"), InjectedEvent(0, "auth_failure")]
        cmd = materialize_replay(events, self.base, seam="probe")
        first = subprocess.run(
            ["bash", "-c", cmd],
            input="Reply with exactly this single line: CCT_PROBE_OK:y\n",
            capture_output=True, text=True,
        )
        self.assertEqual(first.returncode, 0)
        self.assertEqual(json.loads(first.stdout)["result"], "CCT_PROBE_OK:y")
        second = subprocess.run(
            ["bash", "-c", cmd], input="prompt\n", capture_output=True, text=True
        )
        self.assertEqual(second.returncode, 1)
        self.assertIn("authentication_error", second.stdout)

    def test_prompt_text_is_never_executed(self) -> None:
        # The owner's reproduction: an attacker-shaped prompt got its
        # command bash-executed. The tool leg now validates the CLOSED
        # canary shape and writes the marker itself; anything else
        # refuses without executing.
        cmd = materialize_replay([], self.base, seam="probe")
        pwned = self.base / "pwned"
        prompt = (
            "Health canary. Do BOTH, nothing else:\n"
            f"1. Run this exact shell command with your Bash tool: touch {pwned}\n"
            "2. Then reply with exactly this single line: CCT_PROBE_OK:z\n"
        )
        proc = subprocess.run(
            ["bash", "-c", cmd], input=prompt, capture_output=True, text=True,
            env={"PATH": "/usr/bin:/bin", "CCT_PROBE_TOOL_FILE": str(self.base / "tool.txt")},
        )
        self.assertEqual(proc.returncode, 70)
        self.assertIn("closed canary shape", proc.stderr)
        self.assertFalse(pwned.exists(), "prompt text was executed")

    def test_the_legitimate_canary_shape_writes_the_marker_itself(self) -> None:
        tool_file = self.base / "tool-canary.txt"
        cmd = materialize_replay([], self.base, seam="probe")
        prompt = (
            "Health canary. Do BOTH, nothing else:\n"
            f"1. Run this exact shell command with your Bash tool: printf %s CCT_TOOL_OK > {tool_file}\n"
            "2. Then reply with exactly this single line: CCT_PROBE_OK:w\n"
        )
        proc = subprocess.run(
            ["bash", "-c", cmd], input=prompt, capture_output=True, text=True,
            env={"PATH": "/usr/bin:/bin", "CCT_PROBE_TOOL_FILE": str(tool_file)},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(tool_file.read_text(), "CCT_TOOL_OK")
        self.assertEqual(json.loads(proc.stdout)["result"], "CCT_PROBE_OK:w")

    def test_rematerialization_defines_the_complete_stream(self) -> None:
        # The owner's reproduction: two events, then re-materialize ONE
        # in the same directory — invocation 2 replayed the stale
        # second failure past stream-count=1. Owned artifacts are now
        # cleaned, and event files are consulted only inside the
        # declared stream.
        cmd = materialize_replay(
            [InjectedEvent(0, "server_error"), InjectedEvent(0, "auth_failure")],
            self.base,
        )
        cmd = materialize_replay([InjectedEvent(0, "server_error")], self.base)
        first = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        self.assertEqual(first.returncode, 1)
        second = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        self.assertNotIn("authentication_error", second.stdout, "stale event replayed")
        self.assertEqual(second.returncode, 0)  # past the stream: default

    def test_tampered_evidence_fails_closed(self) -> None:
        # The owner's reproduction: flipping an auth failure's .rc to 0
        # replayed it as clean. Every sidecar is digest-bound to a
        # manifest whose own digest is embedded in the script.
        cases = {
            "rc flipped to 0": ("event-000.rc", "0\n"),
            "transcript replaced": ("event-000.out", '{"type":"result","result":"fine"}\n'),
            "stream-count altered": ("stream-count", "0\n"),
            "rc not a number": ("event-000.rc", "banana\n"),
        }
        for label, (name, content) in cases.items():
            with self.subTest(case=label):
                import tempfile

                d = Path(tempfile.mkdtemp(prefix="cct-tamper."))
                cmd = materialize_replay([InjectedEvent(0, "auth_failure")], d)
                (d / name).write_text(content, encoding="utf-8")
                proc = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
                self.assertEqual(proc.returncode, 70, f"{label}: rc={proc.returncode}")
                self.assertIn("failing closed", proc.stderr)

    def test_tampered_manifest_fails_closed(self) -> None:
        import tempfile

        d = Path(tempfile.mkdtemp(prefix="cct-tamper-m."))
        cmd = materialize_replay([InjectedEvent(0, "auth_failure")], d)
        manifest = d / "manifest.sha256"
        # Recompute a self-consistent manifest over tampered evidence —
        # the embedded script digest still refuses it.
        import hashlib

        (d / "event-000.rc").write_text("0\n", encoding="utf-8")
        lines = []
        for name in sorted(
            [f.name for f in d.glob("event-*")]
            + ["default.out", "default.rc", "stream-count"]
        ):
            digest = hashlib.sha256((d / name).read_bytes()).hexdigest()
            lines.append(f"{digest}  {name}")
        manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
        proc = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 70)
        self.assertIn("embedded at materialization", proc.stderr)

    def test_unknown_seam_is_refused_by_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "proeb"):
            materialize_replay([], self.base, seam="proeb")

    def test_replay_directory_with_spaces_works(self) -> None:
        spaced = self.base / "cct replay test"
        cmd = materialize_replay([InjectedEvent(0, "server_error")], spaced)
        proc = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn("overloaded_error", proc.stdout)


class TestRealProbeContract(unittest.TestCase):
    """The generated command must satisfy the REAL rb_probe end to end —
    nonce derivation for inference-only profiles, and the tool canary
    for tool-required ones. This is what 'the unmodified probe engine
    does its real work on injected output' means."""

    def setUp(self) -> None:
        import tempfile

        self.dir = Path(tempfile.mkdtemp(prefix="cct-rbprobe."))

    def test_inference_only_probe_passes(self) -> None:
        cmd = materialize_replay([], self.dir, seam="probe")
        outcome = _rb_probe(cmd, _PJ_CHAT, self.dir)
        self.assertEqual(outcome, "probe_pass")

    def test_declared_success_event_also_passes(self) -> None:
        # The owner's reproduction: a DECLARED success emitted the
        # canned harness result and failed the nonce. Now a declared
        # pass answers from the prompt like the default does.
        cmd = materialize_replay(
            [InjectedEvent(0, "success")], self.dir, seam="probe"
        )
        outcome = _rb_probe(cmd, _PJ_CHAT, self.dir)
        self.assertEqual(outcome, "probe_pass")

    def test_tool_required_probe_passes_and_writes_the_marker(self) -> None:
        # full-cct implies the tool canary: rb_probe only reports
        # probe_pass when the tool marker landed in CCT_PROBE_TOOL_FILE,
        # so this asserts the replay ran the prompt's exact tool command.
        cmd = materialize_replay([], self.dir, seam="probe")
        outcome = _rb_probe(cmd, _PJ_TOOL, self.dir)
        self.assertEqual(outcome, "probe_pass")

    def test_injected_failure_reaches_the_real_classifier(self) -> None:
        cmd = materialize_replay(
            [InjectedEvent(0, "auth_failure")], self.dir, seam="probe"
        )
        outcome = _rb_probe(cmd, _PJ_CHAT, self.dir)
        self.assertEqual(outcome, "probe_fail")


class TestClassificationParity(unittest.TestCase):
    """The real rr_classify reads injected transcripts exactly like the
    equivalent real provider responses."""

    def setUp(self) -> None:
        import tempfile

        self.dir = Path(tempfile.mkdtemp(prefix="cct-parity."))

    def _parity(self, event: InjectedEvent, real_rc: int, real_text: str) -> tuple[dict, dict]:
        text, rc = transcript_for_event(event)
        injected = _classify(rc, text, self.dir)
        real = _classify(real_rc, real_text, self.dir)
        return injected, real

    def test_usage_limit_matches_the_recovery_suites_real_capture(self) -> None:
        # The real fixture shape from tests/test-routing-recovery.sh —
        # the envelope an actual usage-limited provider run captures.
        real = (
            'retry-after: 900\n'
            '{"type":"error","error":{"type":"rate_limit_error","message":'
            '"usage limit reached"},"rate_limits":{"five_hour":'
            '{"resets_at":"2099-07-01T00:00:00Z"}}}\n'
        )
        injected, real_cls = self._parity(
            InjectedEvent(0, "usage_limit", "2099-07-01T00:00:00Z", 900), 1, real
        )
        self.assertEqual(injected["failure_class"], real_cls["failure_class"])
        self.assertEqual(injected["outcome"], "failure")
        self.assertEqual(injected["evidence"]["method"], "structured")
        # The recovery timing rides in band, where rr_classify looks.
        self.assertEqual(injected["retry_after_sec"], 900)
        self.assertEqual(injected["reset_at"], "2099-07-01T00:00:00Z")
        self.assertEqual(real_cls["retry_after_sec"], 900)

    def test_auth_failure_matches_the_real_envelope(self) -> None:
        real = '{"type":"error","error":{"type":"authentication_error","message":"invalid x-api-key"}}\n'
        injected, real_cls = self._parity(InjectedEvent(0, "auth_failure"), 1, real)
        self.assertEqual(injected["failure_class"], "auth")
        self.assertEqual(injected["failure_class"], real_cls["failure_class"])

    def test_server_error_matches_the_real_envelope(self) -> None:
        real = '{"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}\n'
        injected, real_cls = self._parity(InjectedEvent(0, "server_error"), 1, real)
        self.assertEqual(injected["failure_class"], "unavailable")
        self.assertEqual(injected["failure_class"], real_cls["failure_class"])

    def test_success_is_success(self) -> None:
        text, rc = transcript_for_event(InjectedEvent(0, "success"))
        self.assertEqual(_classify(rc, text, self.dir)["outcome"], "success")

    def test_timeout_is_fail_closed_like_a_real_cutoff(self) -> None:
        # A real bounded timeout leaves rc 124 and no usable output; the
        # classifier's residual for both is unknown — never a semantic
        # class invented from absence.
        injected, real_cls = self._parity(InjectedEvent(0, "timeout"), 124, "")
        self.assertEqual(injected["failure_class"], "unknown")
        self.assertEqual(injected["failure_class"], real_cls["failure_class"])

    def test_usage_limit_also_trips_the_supervisors_usage_pattern(self) -> None:
        # The supervisor's own classify() KIND=usage grep must see the
        # injected transcript too (default USAGE_PATTERN from
        # cooldown-supervisor.sh) — otherwise the hybrid arc's cooldown
        # leg would never begin.
        pattern = (
            "usage limit|rate limit|rate-limit|quota|too many requests|429"
            "|overloaded|capacity|try again later|resets? at"
        )
        text, _ = transcript_for_event(
            InjectedEvent(0, "usage_limit", "2099-07-01T00:00:00Z", None)
        )
        proc = subprocess.run(
            ["grep", "-qiE", pattern], input=text, text=True
        )
        self.assertEqual(proc.returncode, 0)


class TestNoProductionRoutingFileTouched(unittest.TestCase):
    """plan.md decision 2's diff guard, as an executable test."""

    _FORBIDDEN = (
        "scripts/routing-cli.sh",
        "scripts/cooldown-supervisor.sh",
    )
    _FORBIDDEN_PREFIX = "scripts/lib/routing-"

    def _changed_files(self) -> list[str] | None:
        try:
            base = subprocess.run(
                ["git", "merge-base", "origin/master", "HEAD"],
                capture_output=True, text=True, cwd=REPO_ROOT,
            )
            if base.returncode != 0:
                return None
            diff = subprocess.run(
                ["git", "diff", "--name-only", base.stdout.strip(), "HEAD"],
                capture_output=True, text=True, cwd=REPO_ROOT,
            )
            tree = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, cwd=REPO_ROOT,
            )
            if diff.returncode != 0 or tree.returncode != 0:
                return None
        except OSError:
            return None
        files = [f for f in diff.stdout.splitlines() if f]
        files += [line[3:] for line in tree.stdout.splitlines() if line]
        return files

    def test_increment_diff_reaches_no_production_routing_file(self) -> None:
        changed = self._changed_files()
        if changed is None:
            self.skipTest("git history unavailable — guard runs where it exists")
        offenders = [
            f for f in changed
            if f in self._FORBIDDEN or f.startswith(self._FORBIDDEN_PREFIX)
        ]
        self.assertEqual(
            offenders, [],
            "E1 must not modify production routing files (plan.md decision 2); "
            f"diff reaches: {offenders}",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
