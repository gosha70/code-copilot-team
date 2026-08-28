# tests/test_routing_eval_redaction.py — routing-eval (E1 of #109) T6.
#
# plan.md decision 8 proven adversarially: redaction is a property of
# the WRITER. The decisive regression seeds a real-shaped credential,
# persists evidence both ways, and shows that the read-time design
# fails structurally — the secret already reached durable storage —
# while the write-time gate never lets it land. The other half of the
# contract is proven too: redaction can never alter measurement
# semantics or fingerprints (the writer refuses, loudly), scrubbed
# records stay schema-valid, evidence references stay resolvable, the
# changed-file measure excludes environment/cache churn, and identical
# immutable inputs reproduce byte-identical artifacts.

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from benchmark_runner.routing_eval import redaction
from benchmark_runner.routing_eval.record_check import load_schema, validate
from benchmark_runner.routing_eval.redaction import (
    REDACTED,
    RedactionError,
    is_measured_path,
    measured_diff_lines,
    measurement_view,
    scrub,
    scrub_text,
    secret_values_from_registry,
    write_run_records,
)
from benchmark_runner.routing_eval.supervisor_runner import SupervisorRunner

_SECRET = "sk-live-EXAMPLE0000000000000000000000"
_PRESET = "sha256:" + "ab" * 32


def _runner(tmp: Path, **overrides) -> SupervisorRunner:
    fields = dict(
        repo_root=tmp / "repo",
        registry_path=tmp / "registry.toml",
        worktree=tmp / "wt",
        state_path=tmp / "state.json",
        ledger_root=tmp / "ledger",
        preset_digest=_PRESET,
        task_set_revision="rev",
        toolchain_digest="sha256:tc",
    )
    fields.update(overrides)
    return SupervisorRunner(**fields)


def _valid_record(tmp: Path, *, reason="healthy — selected") -> dict:
    """One fully schema-valid routing-run record in harvest's shape,
    with an addressable verifier evidence file under the ledger."""
    evidence = tmp / "ledger" / "feat" / "verify.txt"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text("ok\n", encoding="utf-8")
    return {
        "schema_version": 1,
        "registry_digest": "sha256:" + "cd" * 32,
        "preset_digest": _PRESET,
        "task_set_revision": "rev",
        "toolchain_digest": "sha256:tc",
        "task_id": "go/bowling",
        "trial": 0,
        "trial_seed": 11,
        "mode": "cct_router",
        "profile_id": None,
        "injected_events": [],
        "routing_decisions": [
            {
                "considered": [
                    {"id": "alpha", "verdict": "selected",
                     "reason": reason, "state": "healthy"}
                ],
                "selected": "alpha",
                "reason": reason,
                "requested_model": None,
                "effective_model": None,
                "endpoint": None,
                "failure_classification": None,
                "provisional_outcome": None,
                "route_class": "tier1_only",
            }
        ],
        "tokens": {"input": None, "output": None,
                   "cache_read": None, "cache_write": None},
        "cost": {"value": None, "provenance": "unavailable",
                 "estimator": None, "inputs": None},
        "baseline": {"lint_passed": None, "typecheck_passed": None},
        "quality_gates": {
            "coverage": {"before": None, "after": None},
            "security": {"findings_by_severity": {"before": None, "after": None}},
        },
        "scope_violations": [],
        "verifiers": [
            {"command": "bash checks/run.sh", "exit_status": 0,
             "evidence_ref": str(evidence)}
        ],
        "repair_cycles": [],
        "interventions": [],
        "tier2": {"delegated": False, "packet_id": None, "packet_digest": None,
                  "builder_id": None, "builder_tier": None,
                  "builder_provider": None, "builder_model": None,
                  "delegated_lines": None, "reconciliation_diff_lines": None},
        "rollbacks": [],
        "reconciliation": None,
        "insufficient_evidence": {
            "cost": {"reason": "supervisor transcripts are transient; "
                     "no measured cost harvested"}
        },
    }


class TestSecretPatterns(unittest.TestCase):
    def test_the_closed_pattern_classes_each_scrub(self) -> None:
        cases = {
            "authorization header": "Authorization: Bearer abcd1234efgh5678",
            "bare bearer": "curl -H 'x' Bearer abcdefgh12345678 done",
            "api key assignment": f"OPENAI_API_KEY={_SECRET}",
            "lowercase assignment": "api_key: super-secret-value",
            "password": "password=hunter2hunter2",
            "cct config carrier": "CCT_CONFIG__GATEWAY=https://u:p@host",
            "cct cli sets carrier": "CCT_CLI_SETS=claude:sk-abc,pi:tok",
            "openai shape": f"saw {_SECRET} in env",
            "aws shape": "AKIAIOSFODNN7EXAMPLE key",
            "github shape": "ghp_abcdefghijklmnopqrstuvwxyz123456",
            "slack shape": "xoxb-1234567890-abcdefghijk",
            "jwt shape": ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
                          "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
                          "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9P"),
            "private key block": ("-----BEGIN RSA PRIVATE KEY-----\n"
                                  "MIIEow\n-----END RSA PRIVATE KEY-----"),
        }
        for name, text in cases.items():
            with self.subTest(pattern=name):
                out = scrub_text(text, home="/nonexistent-home")
                self.assertIn(REDACTED, out, f"{name} not scrubbed: {out!r}")
                for fragment in (_SECRET, "hunter2", "super-secret-value",
                                 "sk-abc", "u:p@host", "MIIEow"):
                    self.assertNotIn(fragment, out)

    def test_scrub_is_idempotent_and_leaves_benign_text_alone(self) -> None:
        benign = ("verifier 'bash checks/run.sh' exited 0; "
                  "state healthy; digest sha256:" + "ab" * 32)
        self.assertEqual(scrub_text(benign, home="/nonexistent-home"), benign)
        once = scrub_text(f"OPENAI_API_KEY={_SECRET}", home="/nonexistent-home")
        self.assertEqual(scrub_text(once, home="/nonexistent-home"), once)

    def test_home_paths_collapse_to_tilde(self) -> None:
        out = scrub_text("wrote /home/gosha/dev/wt/file.py",
                         home="/home/gosha")
        self.assertEqual(out, "wrote ~/dev/wt/file.py")

    def test_deep_scrub_touches_string_values_only(self) -> None:
        payload = {"a": [1, True, None, f"key={_SECRET}"],
                   "b": {"n": 0.5, "s": "clean"}}
        out = scrub(payload, home="/nonexistent-home")
        self.assertEqual(out["a"][:3], [1, True, None])
        self.assertNotIn(_SECRET, out["a"][3])
        self.assertEqual(out["b"], {"n": 0.5, "s": "clean"})


class TestDynamicLiteralSecrets(unittest.TestCase):
    """The actual-value guarantee: a credential deliberately chosen to
    match NO static pattern — no label, no header, no known shape —
    still never reaches durable bytes, because the writer removes it
    by literal value. The static regex layer alone provably leaks it."""

    _BORING = "correct-horse-X7"

    def test_unlabeled_boring_credential_never_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = _valid_record(
                root,
                reason=f"provider echoed {self._BORING} while failing",
            )
            # sanity: the static pattern layer does NOT catch it — the
            # value survives a pattern-only scrub, which is exactly the
            # gap the dynamic pass closes
            self.assertIn(self._BORING,
                          scrub_text(record["routing_decisions"][0]["reason"],
                                     home="/nonexistent-home"))
            out = write_run_records(
                [record], root / "ledger" / "runs.jsonl",
                evidence_root=root / "ledger", home="/nonexistent-home",
                secret_values=[self._BORING],
            )
            data = out.read_bytes().decode("utf-8")
            self.assertNotIn(self._BORING, data)
            self.assertIn(REDACTED, data)

    def test_disabling_the_dynamic_pass_leaks(self) -> None:
        # The owner's discriminator: all static patterns fully enabled,
        # dynamic pass off -> the boring credential reaches durable
        # bytes. This proves the dynamic pass — not the regex layer —
        # carries the actual-value guarantee.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = _valid_record(
                root,
                reason=f"provider echoed {self._BORING} while failing",
            )
            out = write_run_records(
                [record], root / "ledger" / "runs.jsonl",
                evidence_root=root / "ledger", home="/nonexistent-home",
                secret_values=(),
            )
            self.assertIn(self._BORING, out.read_bytes().decode("utf-8"),
                          "without the dynamic pass the value leaks — the "
                          "static patterns alone are not the guarantee")

    def test_literal_replacement_properties(self) -> None:
        # empty values are ignored
        self.assertEqual(
            scrub_text("clean", home="/nh", secret_values=[""]), "clean"
        )
        # regex metacharacters are inert — the value is a literal
        gnarly = "a+b(c)*[d]?|^$."
        out = scrub_text(f"saw {gnarly} in output", home="/nh",
                         secret_values=[gnarly])
        self.assertNotIn(gnarly, out)
        self.assertIn(REDACTED, out)
        # overlapping secrets replace deterministically longest-first:
        # the longer value is removed whole, no fragment survives
        out = scrub_text("xxabcdefyy", home="/nh",
                         secret_values=["abc", "abcdef"])
        self.assertEqual(out, f"xx{REDACTED}yy")
        # idempotent
        self.assertEqual(
            scrub_text(out, home="/nh", secret_values=["abc", "abcdef"]), out
        )

    def test_registry_resolver_reads_only_declared_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = Path(tmp) / "routing.toml"
            registry.write_text(
                "schema_version = 1\n"
                "[[profiles]]\n"
                'id = "alpha"\n'
                'credential_env = "CCT_EVAL_TOKEN_A"\n'
                "[[profiles]]\n"
                'id = "beta"\n'
                "credential_env = CCT_EVAL_TOKEN_B  # unquoted form\n"
                "[[profiles]]\n"
                'id = "gamma"\n'
                'credential_env = "CCT_EVAL_UNSET"\n',
                encoding="utf-8",
            )
            environ = {
                "CCT_EVAL_TOKEN_A": self._BORING,
                "CCT_EVAL_TOKEN_B": "another-plain-value",
                # deliberately present and secret-looking, but NOT
                # referenced by the registry: never resolved
                "UNRELATED_SECRET": "sk-should-not-be-read-000000000000",
            }
            values = secret_values_from_registry(registry, environ)
            self.assertEqual(
                values, (self._BORING, "another-plain-value")
            )
        # a missing registry resolves to nothing, never an error
        self.assertEqual(
            secret_values_from_registry(Path(tmp) / "gone.toml", environ), ()
        )

    def test_adapter_evidence_scrubs_the_registry_credential(self) -> None:
        # End to end at the runner's write site: the executed
        # registry declares the credential reference; the adapter's
        # output echoes the boring VALUE; the durable evidence is clean.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / "registry.toml"
            registry.write_text(
                'schema_version = 1\n[[profiles]]\nid = "p"\n'
                'credential_env = "CCT_EVAL_BORING"\n',
                encoding="utf-8",
            )
            runner = _runner(root, registry_path=registry,
                             benchmark_id="fixture")
            adapter = SimpleNamespace(
                verify=lambda spec, wt: SimpleNamespace(
                    tests_passed=False,
                    tests_output=(f"authentication failed for "
                                  f"{self._BORING}\n"),
                )
            )
            with mock.patch.dict("os.environ",
                                 {"CCT_EVAL_BORING": self._BORING}):
                with mock.patch.object(SupervisorRunner, "_adapter",
                                       return_value=adapter):
                    verifier = runner._adapter_verify(
                        SimpleNamespace(task_id="t"), root / "wt", "feat"
                    )
            durable = Path(verifier["evidence_ref"]).read_bytes().decode("utf-8")
            self.assertNotIn(self._BORING, durable)
            self.assertIn("authentication failed", durable)


class TestWriteTimeIsTheOnlySafeTime(unittest.TestCase):
    """The owner's decisive regression: emit a secret, persist evidence
    both ways, and prove read-time scrubbing is structurally too late."""

    def test_read_time_scrubbing_leaves_the_secret_durable(self) -> None:
        output = (f"export OPENAI_API_KEY={_SECRET}\n"
                  f"Authorization: Bearer {_SECRET}\ntests passed\n")
        with tempfile.TemporaryDirectory() as tmp:
            # The REJECTED design: persist raw, scrub when read. The
            # reader's view is clean — and the durable bytes are not.
            raw = Path(tmp) / "evidence-raw.txt"
            raw.write_text(output, encoding="utf-8")
            reader_view = scrub_text(raw.read_text(encoding="utf-8"),
                                     home="/nonexistent-home")
            self.assertNotIn(_SECRET, reader_view)
            self.assertIn(_SECRET, raw.read_bytes().decode("utf-8"),
                          "the counterfactual: read-time scrubbing cannot "
                          "un-persist what already reached durable storage")
            # Decision 8's design: the scrub happens BEFORE the write,
            # so no raw-then-scrub window exists at all.
            safe = Path(tmp) / "evidence-scrubbed.txt"
            safe.write_text(scrub_text(output, home="/nonexistent-home"),
                            encoding="utf-8")
            self.assertNotIn(_SECRET, safe.read_bytes().decode("utf-8"))
            self.assertIn("tests passed", safe.read_text(encoding="utf-8"))

    def test_adapter_verify_scrubs_at_its_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = _runner(Path(tmp), benchmark_id="fixture")
            adapter = SimpleNamespace(
                verify=lambda spec, wt: SimpleNamespace(
                    tests_passed=True,
                    tests_output=(f"env: OPENAI_API_KEY={_SECRET}\n"
                                  f"1 passed\n"),
                )
            )
            with mock.patch.object(SupervisorRunner, "_adapter",
                                   return_value=adapter):
                verifier = runner._adapter_verify(
                    SimpleNamespace(task_id="t"), Path(tmp) / "wt", "feat"
                )
            evidence = Path(verifier["evidence_ref"])
            self.assertEqual(verifier["exit_status"], 0)
            self.assertNotIn(_SECRET, evidence.read_bytes().decode("utf-8"),
                             "the secret reached durable adapter evidence")
            self.assertIn("1 passed", evidence.read_text(encoding="utf-8"))


class TestWriteRunRecords(unittest.TestCase):
    def test_secrets_in_prose_never_reach_the_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = _valid_record(
                root, reason=f"rejected — probe saw OPENAI_API_KEY={_SECRET}"
            )
            out = write_run_records(
                [record], root / "ledger" / "routing-runs.jsonl",
                evidence_root=root / "ledger", home="/nonexistent-home",
                secret_values=(),
            )
            data = out.read_bytes().decode("utf-8")
            self.assertNotIn(_SECRET, data)
            self.assertIn(REDACTED, data)

    def test_evidence_refs_relativize_and_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = write_run_records(
                [_valid_record(root)], root / "ledger" / "runs.jsonl",
                evidence_root=root / "ledger", home="/nonexistent-home",
                secret_values=(),
            )
            (persisted,) = [json.loads(line) for line in
                            out.read_text(encoding="utf-8").splitlines()]
            ref = persisted["verifiers"][0]["evidence_ref"]
            self.assertFalse(Path(ref).is_absolute())
            resolved = root / "ledger" / ref
            self.assertTrue(resolved.is_file())
            self.assertEqual(resolved.read_text(encoding="utf-8"), "ok\n")

    def test_evidence_outside_the_artifact_root_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = _valid_record(root)
            stray = root / "elsewhere" / "evidence.txt"
            stray.parent.mkdir()
            stray.write_text("x", encoding="utf-8")
            record["verifiers"][0]["evidence_ref"] = str(stray)
            with self.assertRaisesRegex(RedactionError, "outside the artifact"):
                write_run_records(
                    [record], root / "ledger" / "runs.jsonl",
                    evidence_root=root / "ledger", home="/nonexistent-home",
                    secret_values=(),
                )

    def test_a_pre_existing_artifact_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "ledger" / "runs.jsonl"
            target.parent.mkdir(parents=True)
            target.write_text("", encoding="utf-8")
            with self.assertRaisesRegex(RedactionError, "already exists"):
                write_run_records([_valid_record(root)], target,
                                  evidence_root=root / "ledger",
                                  secret_values=(),
                                  home="/nonexistent-home")

    def test_scrubbed_records_stay_schema_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = _valid_record(
                root, reason=f"Authorization: Bearer {_SECRET}"
            )
            self.assertEqual(validate(record, load_schema("routing-run")), [])
            out = write_run_records(
                [record], root / "ledger" / "runs.jsonl",
                evidence_root=root / "ledger", home="/nonexistent-home",
                secret_values=(),
            )
            schema = load_schema("routing-run")
            for line in out.read_text(encoding="utf-8").splitlines():
                self.assertEqual(validate(json.loads(line), schema), [])

    def test_redaction_that_would_alter_measurement_refuses(self) -> None:
        # The mutation the invariant exists for: a hostile pattern that
        # would eat digests. The writer must refuse the whole artifact,
        # never persist a record whose fingerprint was rewritten.
        hostile = redaction._SECRET_PATTERNS + (
            (re.compile(r"sha256:[0-9a-f]+"), REDACTED),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.object(redaction, "_SECRET_PATTERNS", hostile):
                with self.assertRaisesRegex(RedactionError,
                                            "measurement view"):
                    write_run_records(
                        [_valid_record(root)], root / "ledger" / "runs.jsonl",
                        evidence_root=root / "ledger",
                        home="/nonexistent-home",
                        secret_values=(),
                    )
            self.assertFalse((root / "ledger" / "runs.jsonl").exists(),
                             "a refused artifact must not partially exist")

    def test_identical_inputs_reproduce_identical_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = _valid_record(root)
            a = write_run_records([record], root / "ledger" / "a.jsonl",
                                  evidence_root=root / "ledger",
                                  secret_values=(),
                                  home="/nonexistent-home")
            b = write_run_records([record], root / "ledger" / "b.jsonl",
                                  evidence_root=root / "ledger",
                                  secret_values=(),
                                  home="/nonexistent-home")
            self.assertEqual(a.read_bytes(), b.read_bytes(),
                             "same immutable inputs, same artifact bytes")

    def test_measurement_view_preserves_counts_not_prose(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record = _valid_record(Path(tmp))
            record["scope_violations"] = ["a", "b"]
            view = measurement_view(record)
            self.assertEqual(view["scope_violations"], 2)
            self.assertEqual(view["insufficient_evidence"], ["cost"])
            self.assertNotIn("reason", json.dumps(view["routing_decisions"]))
            self.assertEqual(
                view["routing_decisions"][0]["considered"][0]["state"],
                "healthy",
            )


class TestChangedFileMeasure(unittest.TestCase):
    def test_environment_and_cache_churn_is_excluded(self) -> None:
        excluded = [
            ".venv/lib/python3.12/site-packages/x.py",
            "venv/bin/activate",
            "node_modules/pkg/index.js",
            "src/__pycache__/mod.cpython-312.pyc",
            "src/mod.pyc",
            ".pytest_cache/v/cache/lastfailed",
            ".mypy_cache/3.12/mod.json",
            ".cct/auto-build/feat/routing/started-1.json",
            ".git/index",
            "pkg.egg-info/PKG-INFO",
        ]
        for path in excluded:
            with self.subTest(path=path):
                self.assertFalse(is_measured_path(path))
        for path in ("src/app.py", "go/bowling/bowling.go",
                     "tests/test_app.py", "cache_policy.py"):
            with self.subTest(path=path):
                self.assertTrue(is_measured_path(path))

    def test_measured_diff_lines_sums_measured_paths_only(self) -> None:
        numstat = ("3\t1\tsrc/app.py\n"
                   "500\t0\t.venv/lib/site.py\n"
                   "2\t2\tsrc/__pycache__/app.pyc\n"
                   "1\t0\ttests/test_app.py\n")
        self.assertEqual(measured_diff_lines(numstat), 5)

    def test_binary_churn_in_a_measured_path_is_none_never_zero(self) -> None:
        self.assertIsNone(measured_diff_lines("-\t-\tassets/logo.png\n"))
        # binary churn OUTSIDE the measure does not poison the count
        self.assertEqual(
            measured_diff_lines("-\t-\t.venv/bin/python\n1\t1\tsrc/a.py\n"), 2
        )


class TestReconcilerDiffLines(unittest.TestCase):
    def _git(self, cwd: Path, *args: str) -> str:
        proc = subprocess.run(["git", "-C", str(cwd), *args],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def test_measures_the_reconciler_edit_excluding_noise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wt = root / "wt"
            wt.mkdir()
            src = wt / "src"
            src.mkdir()
            (src / "app.py").write_text(
                "\n".join(f"line {i}" for i in range(6)) + "\n",
                encoding="utf-8")
            self._git(wt, "init", "-q")
            self._git(wt, "config", "user.email", "t@t")
            self._git(wt, "config", "user.name", "t")
            self._git(wt, "add", "-A")
            self._git(wt, "commit", "-qm", "base")

            feature = "feat"
            runner = _runner(root, worktree=wt)
            rt_dir = runner._rt_dir(feature, wt)
            rt_dir.mkdir(parents=True)

            # provisional: the builder changes line 2
            (src / "app.py").write_text(
                "line 0\nline 1\nbuilder edit\nline 3\nline 4\nline 5\n",
                encoding="utf-8")
            self._git(wt, "add", "-A")
            (rt_dir / "prestate.patch").write_text(
                self._git(wt, "diff", "--cached", "HEAD"), encoding="utf-8")

            # accepted: provisional + a reconciler edit on line 4 + pure
            # cache noise that must not count
            (src / "app.py").write_text(
                "line 0\nline 1\nbuilder edit\nline 3\nreconciler edit\nline 5\n",
                encoding="utf-8")
            noise = src / "__pycache__"
            noise.mkdir()
            (noise / "app.cpython-312.txt").write_text("junk\n" * 40,
                                                       encoding="utf-8")
            self._git(wt, "add", "-A", "-f")
            (rt_dir / "accepted-1.patch").write_text(
                self._git(wt, "diff", "--cached", "HEAD"), encoding="utf-8")
            self._git(wt, "reset", "-q", "HEAD")

            # reconciler-vs-provisional: 1 add + 1 del on app.py; the
            # 40-line cache file is churn, not product
            self.assertEqual(
                runner._reconciler_diff_lines(wt, feature), 2
            )

    def test_missing_durable_patches_yield_none_never_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wt = root / "wt"
            (wt / ".cct").mkdir(parents=True)
            runner = _runner(root, worktree=wt)
            self.assertIsNone(runner._reconciler_diff_lines(wt, "feat"))


class TestScopeViolationHarvest(unittest.TestCase):
    def test_packet_scope_events_harvest_scrubbed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events = root / "events.jsonl"
            lines = [
                json.dumps({"event": "routing_candidate", "detail": "x"}),
                json.dumps({"event": "packet_scope",
                            "detail": ("round 1: '/home/gosha/wt/tests/x.py' "
                                       "is protected")}),
                json.dumps({"event": "attempt", "detail": "y"}),
            ]
            events.write_text("\n".join(lines) + "\n", encoding="utf-8")
            runner = _runner(root)
            with mock.patch.object(redaction.Path, "home",
                                   return_value=Path("/home/gosha")):
                violations = runner._scope_violations_from(events)
            self.assertEqual(len(violations), 1)
            self.assertIn("protected", violations[0])
            self.assertNotIn("/home/gosha", violations[0],
                             "the harvested detail is scrubbed at the boundary")

    def test_offset_and_missing_journal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner = _runner(root)
            self.assertEqual(
                runner._scope_violations_from(root / "missing.jsonl"), []
            )
            events = root / "events.jsonl"
            events.write_text(
                json.dumps({"event": "packet_scope", "detail": "early"})
                + "\n"
                + json.dumps({"event": "packet_scope", "detail": "late"})
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                runner._scope_violations_from(events, events_offset=1),
                ["late"],
            )


if __name__ == "__main__":
    unittest.main()
