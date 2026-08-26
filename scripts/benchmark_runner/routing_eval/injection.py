"""Deterministic provider-event injection (E1 T2).

Plan decision 2: the benchmark supplies the CHILD'S OUTPUT through the
two documented test-only seams — ``CCT_SUPERVISOR_HARNESS_CMD``
(cooldown-supervisor.sh, "override the child command (a mock harness)")
and ``CCT_ROUTING_PROBE_CMD`` (routing-probe.sh, "Test seam") — and the
real, unmodified classifiers do their real work on it. Nothing here
injects at, patches, or bypasses the classification boundary; this
module only *writes files*: per-event reply transcripts and a replay
script suitable for those seams.

Determinism is the contract:

- The event stream is preset-owned and ordered; replay follows a
  counter file, so two runs of one preset see the same events in the
  same order.
- No leg depends on wall-clock timing. Even the injected ``timeout``
  consumes no time — it reproduces the *observable shape* of a bounded
  timeout (exit 124, no usable output) rather than waiting for one.
- ``preset_digest`` covers everything that shapes the run (scenario,
  arms, trials, seeds, events, cost basis, ceiling, task filter), so a
  changed seed or event can never silently reuse stored outcome cells.

The injected transcripts are shaped like what real providers emit, so
the parity regression (test_routing_eval_injection.py) can assert
``rr_classify`` reads an injected transcript exactly as it reads the
equivalent real provider response.
"""

from __future__ import annotations

import hashlib
import json
import shlex
from dataclasses import asdict
from pathlib import Path

from .scenario_config import InjectedEvent, ScenarioConfig


def _compact(doc) -> str:
    """Real providers and CLIs emit compact JSON, and rr_classify's
    structured-envelope grep matches that exact shape ('{"type":"error"'
    with no space). Pretty-printed injection would silently fall through
    to the text ladder and classify differently than the real capture —
    the parity test caught precisely this.
    """
    return json.dumps(doc, separators=(",", ":"))

#: Exit code ca_run_bounded reports when the bound expires — the
#: injected timeout reproduces the shape without consuming the time.
TIMEOUT_EXIT_CODE = 124

#: Default reply once the declared event stream is exhausted: ordinary
#: success. Declared as a constant so the replay script's tail behavior
#: is part of the contract, not an accident.
_DEFAULT_OUTCOME = "success"


def preset_digest(config: ScenarioConfig) -> str:
    """The digest that makes the preset part of the reuse fingerprint.

    Canonical JSON (sorted keys, no whitespace variance) over every
    field that shapes execution. Anything absent is serialized
    explicitly as null/None so an omitted field and a differently
    ordered file digest identically.
    """
    doc = {
        "scenario": config.scenario,
        "benchmark": config.benchmark,
        "arms": [asdict(a) for a in config.arms],
        "cost_basis": config.cost_basis,
        "trials": config.trials,
        "trial_seeds": config.trial_seeds,
        "event_stream": [asdict(e) for e in config.event_stream],
        "budget_ceiling_usd": config.budget_ceiling_usd,
        "task": config.task_filter,
    }
    canonical = json.dumps(doc, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def transcript_for_event(event: InjectedEvent) -> tuple[str, int]:
    """The child output (transcript text, exit code) one event injects.

    Shapes mirror real providers so the unmodified classifiers read
    them exactly as they read the real thing:

    - ``success``: a Claude-Code-shaped ``type:"result"`` record,
      exit 0. rc 0 is all rr_classify needs for outcome success.
    - ``usage_limit``: the compact rate_limit_error envelope carrying
      the provider's own usage-limit wording — the same shape the
      recovery suite's real capture fixtures use, so rr_classify reads
      it structurally (rate_limited/high), the supervisor's
      USAGE_PATTERN still sees KIND=usage, and the recovery timing
      rides in band exactly where rr_classify looks: a
      ``retry-after: N`` line and/or an ISO reset instant.
    - ``auth_failure``: the structured Anthropic error envelope
      (``error.type: authentication_error``) — the classifier's
      highest-precedence source.
    - ``server_error``: the ``overloaded_error`` envelope ->
      unavailable.
    - ``timeout``: NO output and exit 124 — the observable shape of
      ca_run_bounded's expiry, with zero wall-clock consumed.
    """
    outcome = event.outcome
    if outcome == "success":
        record = {
            "type": "result",
            "result": "Task complete. All verifier commands passed.",
            "total_cost_usd": 0.0123,
        }
        return _compact(record) + "\n", 0
    if outcome == "usage_limit":
        lines = []
        if event.retry_after_sec is not None:
            lines.append(f"retry-after: {event.retry_after_sec}")
        message = "You have hit your 5-hour limit."
        if event.reset_at is not None:
            message += f" Your limit will reset at {event.reset_at}."
        lines.append(
            _compact(
                {
                    "type": "error",
                    "error": {"type": "rate_limit_error", "message": message},
                }
            )
        )
        return "\n".join(lines) + "\n", 1
    if outcome == "auth_failure":
        envelope = {
            "type": "error",
            "error": {
                "type": "authentication_error",
                "message": "invalid x-api-key",
            },
        }
        return _compact(envelope) + "\n", 1
    if outcome == "server_error":
        envelope = {
            "type": "error",
            "error": {"type": "overloaded_error", "message": "Overloaded"},
        }
        return _compact(envelope) + "\n", 1
    if outcome == "timeout":
        return "", TIMEOUT_EXIT_CODE
    raise ValueError(f"unknown injected outcome {outcome!r}")


# NOTE on usage_limit vs the structured ladder: rate_limit_error maps to
# rate_limited via the envelope, but a usage-limit message ALSO matches
# RR_PAT_QUOTA... rr_classify checks the envelope FIRST, so the injected
# usage_limit classifies as rate_limited/structured exactly like the
# real capture fixtures in tests/test-routing-recovery.sh (which use the
# same envelope for usage-limit events). The parity test asserts against
# the REAL fixture's class, not against a wished-for one.


def events_for_task(
    events: list[InjectedEvent], task_index: int
) -> list[InjectedEvent]:
    """The scheduling boundary: the events one task's replay sees.

    ``at_task_index`` addresses a TASK, not an invocation.
    ``materialize_replay`` deliberately knows nothing about tasks — it
    replays an already-scheduled, invocation-ordered stream — so the
    driver materializes one replay per task from THIS filter. Order
    within a task is the preset's declaration order.
    """
    return [e for e in events if e.at_task_index == task_index]


#: The closed seam vocabulary. Anything else is refused by name: a
#: typo'd seam silently falling into harness semantics would recreate
#: the canned-reply nonce failure the probe seam exists to avoid.
REPLAY_SEAMS = ("harness", "probe")


def materialize_replay(
    events: list[InjectedEvent],
    directory: Path,
    seam: str = "harness",
) -> str:
    """Write per-event replies + a replay script; return the command.

    The returned string is suitable verbatim as
    ``CCT_SUPERVISOR_HARNESS_CMD`` (or ``CCT_ROUTING_PROBE_CMD`` with
    ``seam="probe"``). Invocation N emits event N's transcript on
    stdout and exits with its code; past the end of the stream it
    replays the default success reply. State is one counter file in the
    private directory — no time, no randomness, no environment reads.

    For the probe seam the success reply cannot be canned: a probe pass
    must echo the run-specific nonce the canary prompt carries
    (routing-probe.sh derives it per launch precisely so canned output
    can never pass). The probe script therefore extracts the expected
    line from the prompt on stdin and emits it inside a ``type:"result"``
    record — which is an honest pass: the output is a function of the
    prompt, exactly like a live backend's.
    """
    if seam not in REPLAY_SEAMS:
        raise ValueError(
            f"unknown replay seam {seam!r} — the closed set is {REPLAY_SEAMS}"
        )
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    # Clean OWNED artifacts first: a re-materialization must define the
    # complete stream. Stale event files from a longer prior stream
    # were replayable past the new stream-count — a preset/event
    # identity break.
    for stale in directory.glob("event-*"):
        stale.unlink()
    for stale in ("default.out", "default.rc", "stream-count", "manifest.sha256"):
        target = directory / stale
        if target.exists():
            target.unlink()
    reset_replay(directory)

    for i, event in enumerate(events):
        if seam == "probe" and event.outcome == "success":
            # A canned reply can never pass the probe (per-launch
            # nonce), so a DECLARED success is marked pass-mode and
            # answered from the prompt, like the post-stream default.
            (directory / f"event-{i:03d}.mode").write_text("pass\n", encoding="utf-8")
            continue
        text, code = transcript_for_event(event)
        (directory / f"event-{i:03d}.out").write_text(text, encoding="utf-8")
        (directory / f"event-{i:03d}.rc").write_text(f"{code}\n", encoding="utf-8")

    default_text, default_code = transcript_for_event(
        InjectedEvent(at_task_index=0, outcome=_DEFAULT_OUTCOME)
    )
    (directory / "default.out").write_text(default_text, encoding="utf-8")
    (directory / "default.rc").write_text(f"{default_code}\n", encoding="utf-8")
    # The declared stream length: what lets the script distinguish
    # "past the stream" (default) from "declared event whose evidence
    # is missing or corrupt" (fail closed, exit 70). Without it, a
    # deleted auth-failure transcript silently became a pass.
    (directory / "stream-count").write_text(f"{len(events)}\n", encoding="utf-8")

    # Bind every generated sidecar into a manifest, and bind the
    # manifest into the SCRIPT: replay evidence lives in mutable files,
    # and a flipped .rc (auth failure -> 0) or edited transcript would
    # otherwise replay as clean while preset_digest never noticed. The
    # script refuses (exit 70) any file whose digest disagrees.
    manifest_lines = []
    for name in sorted(
        [f.name for f in directory.glob("event-*")]
        + ["default.out", "default.rc", "stream-count"]
    ):
        digest = hashlib.sha256((directory / name).read_bytes()).hexdigest()
        manifest_lines.append(f"{digest}  {name}")
    manifest_text = "\n".join(manifest_lines) + "\n"
    (directory / "manifest.sha256").write_text(manifest_text, encoding="utf-8")
    manifest_digest = hashlib.sha256(manifest_text.encode("utf-8")).hexdigest()

    if seam == "probe":
        # The pass body answers FROM THE PROMPT, exactly like a healthy
        # backend: it extracts the expected line (both rb_prompt forms —
        # "Reply with exactly this single line:" for inference-only and
        # "Then reply with exactly this single line:" for tool-required).
        #
        # The tool leg NEVER executes prompt text. rb_prompt's canary is
        # a closed shape — `printf %s CCT_TOOL_OK > $CCT_PROBE_TOOL_FILE`
        # — so the replay validates the request against exactly that
        # shape (marker constant, path equal to the exported
        # CCT_PROBE_TOOL_FILE) and then writes the marker itself. Any
        # other tool request fails closed: stdin is untrusted text, and
        # a mock that bash-runs it is a shell-execution boundary no test
        # harness should own.
        default_body = (
            'prompt="$(cat)"\n'
            "expected=\"$(printf '%s\\n' \"$prompt\" | sed -n 's/.*[Rr]eply with exactly this single line: //p' | tail -1)\"\n"
            "toolreq=\"$(printf '%s\\n' \"$prompt\" | sed -n 's/.*Run this exact shell command with your Bash tool: //p' | tail -1)\"\n"
            'if [[ -n "$toolreq" ]]; then\n'
            '  if [[ -n "${CCT_PROBE_TOOL_FILE:-}" && "$toolreq" == "printf %s CCT_TOOL_OK > ${CCT_PROBE_TOOL_FILE}" ]]; then\n'
            '    printf %s CCT_TOOL_OK > "${CCT_PROBE_TOOL_FILE}"\n'
            "  else\n"
            '    echo "replay: tool request does not match the closed canary shape — refusing to execute prompt text" >&2\n'
            "    exit 70\n"
            "  fi\n"
            "fi\n"
            'printf \'{"type":"result","result":"%s","total_cost_usd":0.0001}\\n\' "$expected"\n'
            "exit 0\n"
        )
    else:
        default_body = (
            "verify default.out; verify default.rc\n"
            'cat "$dir/default.out"\n'
            'exit "$(cat "$dir/default.rc")"\n'
        )

    script = directory / f"replay-{seam}.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        "# Generated by routing_eval.injection — deterministic event replay.\n"
        "# The event index is claimed ATOMICALLY (mkdir); every evidence\n"
        "# file is digest-verified against a manifest whose own digest is\n"
        "# embedded below, so tampered sidecars fail closed (exit 70).\n"
        "set -euo pipefail\n"
        f'MANIFEST_SHA="{manifest_digest}"\n'
        'dir="$(cd "$(dirname "$0")" && pwd)"\n'
        "fail() { echo \"replay: $1 — failing closed\" >&2; exit 70; }\n"
        "sha() { if command -v shasum >/dev/null 2>&1; then shasum -a 256 \"$1\"; else sha256sum \"$1\"; fi | awk '{print $1}'; }\n"
        'verify() { # verify <relname> — digest must match the manifest\n'
        '  local want got\n'
        '  want="$(awk -v f="$1" \'$2 == f {print $1}\' "$dir/manifest.sha256" | head -1)"\n'
        '  [[ -n "$want" ]] || fail "$1 is not in the manifest"\n'
        '  got="$(sha "$dir/$1")"\n'
        '  [[ "$want" == "$got" ]] || fail "$1 does not match its recorded digest"\n'
        "}\n"
        '[[ -r "$dir/manifest.sha256" ]] || fail "manifest missing"\n'
        '[[ "$(sha "$dir/manifest.sha256")" == "$MANIFEST_SHA" ]] || fail "manifest does not match the digest embedded at materialization"\n'
        "n=0\n"
        'while ! mkdir "$dir/claim-$n" 2>/dev/null; do n=$((n + 1)); done\n'
        'idx="$(printf "event-%03d" "$n")"\n'
        'verify stream-count\n'
        'count="$(cat "$dir/stream-count")"\n'
        '[[ "$count" =~ ^[0-9]+$ ]] || fail "stream-count is not a number"\n'
        "# Event files are consulted ONLY inside the declared stream: a\n"
        "# stale artifact beyond stream-count must never replay.\n"
        'if (( n < count )); then\n'
        '  if [[ -e "$dir/$idx.mode" ]]; then\n'
        '    verify "$idx.mode"\n'
        '    [[ "$(cat "$dir/$idx.mode")" == "pass" ]] || fail "$idx.mode is not a declared pass"\n'
        "    # declared pass: fall through to the default body\n"
        '  elif [[ -e "$dir/$idx.out" && -e "$dir/$idx.rc" ]]; then\n'
        '    verify "$idx.out"; verify "$idx.rc"\n'
        '    rc="$(cat "$dir/$idx.rc")"\n'
        '    [[ "$rc" =~ ^[0-9]+$ ]] || fail "$idx.rc is not a number"\n'
        '    cat "$dir/$idx.out"\n'
        '    exit "$rc"\n'
        "  else\n"
        '    fail "declared event $n has missing evidence"\n'
        "  fi\n"
        "fi\n"
        "# Declared pass, or stream exhausted: the default reply.\n"
        + default_body,
        encoding="utf-8",
    )
    script.chmod(0o755)
    return f"bash {shlex.quote(str(script))}"


def reset_replay(directory: Path) -> None:
    """Rewind the replay to event 0 (a fresh run over the same stream)."""
    for claim in Path(directory).glob("claim-*"):
        claim.rmdir()
