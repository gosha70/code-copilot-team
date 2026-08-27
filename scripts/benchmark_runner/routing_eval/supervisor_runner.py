"""The production execution path: real supervisor, harvested records.

This is T4's ``run_task`` implementation. It shells to the REAL
``cooldown-supervisor.sh`` — no fork, no patch — feeding provider
behaviour exclusively through the documented T2 replay seam
(``CCT_SUPERVISOR_HARNESS_CMD``), then HARVESTS routing-run records
from the supervisor's durable outputs:

- ``RT_DIR/started-N.json`` — the persisted attempt records (selected
  profile identity, written BEFORE launch);
- ``events.jsonl`` — the journal, including one ``routing_candidate``
  line per considered profile in the selector's explain vocabulary.

The harvester owns the ONE prose-to-structure translation in E1: the
selector's reason strings carry the closed circuit state in known
producer formats ("cooling until <ts> (cooldown)", "recovery state
'probe_due' ...", "(state: healthy ...)"), and ``_state_for_reason``
maps them to the schema's closed ``state`` vocabulary at this boundary.
Verifiers downstream compare STATES; they never read prose.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from .injection import materialize_replay
from .redaction import (
    measured_diff_lines,
    scrub_text,
    secret_values_from_registry,
)
from .scenario_config import InjectedEvent


def registry_digest_of(registry_path: Path) -> str:
    """The canonical digest of the registry AS SHIPPED to the run.

    Computed from the file the subprocess actually reads — a caller can
    never label one registry with another registry's digest, which is
    the whole point of the fingerprint component.
    """
    return "sha256:" + hashlib.sha256(Path(registry_path).read_bytes()).hexdigest()


class RunnerError(RuntimeError):
    """The supervisor invocation cannot yield trustworthy fresh evidence."""


#: Explicit opt-in for launching the profile's REAL backend CLI as the
#: child (no harness override). The default is the deterministic T2
#: replay; live provider runs must be asked for by name, never fallen
#: into.
USE_REAL_BACKEND = "__real_backend__"

#: The producer's closed reason formats -> the schema's closed states.
_STATE_PATTERNS = (
    re.compile(r"\((pool:cooldown|cooldown)\)"),
    re.compile(r"recovery state '((?:pool:)?(?:degraded|probe_due|probing))'"),
    re.compile(r"\(state: ((?:pool:)?(?:unknown|cooldown|disabled|degraded|probe_due|probing|healthy))"),
)
_DISABLED_RE = re.compile(r"^disabled \(auth\)")


def _state_for_reason(reason: str) -> Optional[str]:
    """Translate the selector's reason prose to the closed state, ONCE.

    Unknown formats yield None rather than a guess — a verifier that
    needs the state will then fail the leg, which is the honest result
    for untranslatable evidence.
    """
    if _DISABLED_RE.search(reason):
        return "disabled"
    for pattern in _STATE_PATTERNS:
        m = pattern.search(reason)
        if m:
            return m.group(1)
    return None


_CANDIDATE_RE = re.compile(r"^(?P<id>[^:]+): (?P<verdict>selected|eligible|rejected) — (?P<reason>.*)$")


@dataclass(frozen=True)
class SupervisorRunner:
    """Runs one real supervisor invocation per (task, trial) and
    harvests its durable evidence into schema-valid routing-run records.
    """

    repo_root: Path
    registry_path: Path
    worktree: Path
    state_path: Path
    ledger_root: Path
    preset_digest: str
    task_set_revision: str
    toolchain_digest: str
    #: The DECLARED benchmark adapter id (config.benchmark). When set,
    #: every ordinary task runs the existing adapter lifecycle around
    #: the supervisor: the adapter prepares the task's starter files
    #: before the run and its verification executes after, recorded as
    #: a driver-owned verifier with addressable evidence. None means a
    #: CCT-native fixture run (no adapter contract to honor).
    benchmark_id: "str | None" = None
    #: Extra literal credential values for the write-time scrub, ON TOP
    #: of the values resolved from the executed registry's own
    #: credential_env references (which happens on every write,
    #: unconditionally — the persistence boundary is independently
    #: safe without callers remembering to pass anything).
    secret_values: tuple[str, ...] = ()
    supervisor_args: tuple[str, ...] = (
        "--profile", "advisory", "--max-attempts", "3",
        "--max-cooldowns", "2", "--cooldown-sec", "0", "--max-wall-sec", "120",
    )

    def for_trial(self, trial: int) -> "SupervisorRunner":
        """A CLEAN execution context for one trial.

        Trials must see the same starting conditions: trial 0's healthy
        circuit state, probe accounting, and accepted reconciliation
        edits must never become trial 1's baseline. The trial context
        gets its own routing state, ledger root (and thus probe
        ledger), and a fresh worktree cloned from the baseline's
        committed state.
        """
        import dataclasses

        base = self.worktree
        trial_wt = self.ledger_root / "trial-worktrees" / f"trial-{trial}"
        trial_state = self.ledger_root / f"state-trial-{trial}.json"
        trial_ledger = self.ledger_root / f"trial-{trial}"
        # A pre-existing trial context is REFUSED, never trusted: a
        # crash between clone and ledger publication would otherwise
        # hand the next run a contaminated worktree that still looks
        # like a clean context.
        for stale in (trial_wt, trial_state, trial_ledger):
            if stale.exists():
                raise RunnerError(
                    f"trial context {stale} already exists — refusing a "
                    f"possibly contaminated trial context"
                )
        trial_wt.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            ["git", "clone", "-q", "--no-hardlinks", str(base), str(trial_wt)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise RunnerError(
                f"could not clone the baseline worktree for trial {trial}: "
                f"{proc.stderr[-300:]!r}"
            )
        return dataclasses.replace(
            self,
            worktree=trial_wt,
            state_path=trial_state,
            ledger_root=trial_ledger,
        )

    def run_task(
        self,
        task: str,
        trial: int,
        seed: int,
        events: Sequence[InjectedEvent],
        harness_cmd: "str | None" = None,
    ) -> list[Mapping[str, Any]]:
        feature = self._feature_id(task, trial)

        # FRESHNESS BOUNDARY: this invocation's evidence directories
        # must not pre-exist. A repeated invocation would otherwise
        # harvest CUMULATIVE decisions, and a failed one could publish
        # a prior run's evidence as its own. Refusing a reused
        # directory is the same fail-closed rule the replay bundle and
        # the outcome matrix already follow.
        ledger_dir = self.ledger_root / feature
        rt_dir_default = self._rt_dir(feature)
        for stale in (ledger_dir, rt_dir_default):
            if stale.exists():
                raise RunnerError(
                    f"evidence directory {stale} already exists — refusing a "
                    f"harvest that could mix this invocation's evidence with "
                    f"a prior run's"
                )

        # The routed session executes IN the benchmark task's worktree:
        # adapter-prepared files at the root, the generated feature
        # spec embedding the adapter prompt. CCT-native mode
        # (benchmark_id None) keeps the runner's own worktree.
        if self.benchmark_id is not None:
            task_spec, exec_wt = self._prepare_task_worktree(
                task, feature, delegate=False
            )
        else:
            task_spec, exec_wt = None, self.worktree

        harness_cmd = self._ordinary_harness(feature, list(events), harness_cmd)

        env = dict(os.environ)
        env.update(
            CCT_ROUTING_REGISTRY=str(self.registry_path),
            CCT_ROUTING_STATE=str(self.state_path),
            CCT_SUPERVISOR_DIR=str(self.ledger_root),
            CCT_SUPERVISOR_SLEEP="true",  # cooldowns elapse without wall-clock
        )
        if harness_cmd is not None:
            env["CCT_SUPERVISOR_HARNESS_CMD"] = harness_cmd
        proc = subprocess.run(
            ["bash", str(self.repo_root / "scripts" / "cooldown-supervisor.sh"),
             feature, "--routing", "--worktree", str(exec_wt),
             *self.supervisor_args],
            env=env, capture_output=True, text=True, cwd=self.repo_root,
        )
        if proc.returncode != 0:
            raise RunnerError(
                f"supervisor exited {proc.returncode} for {feature} — a failed "
                f"invocation publishes no evidence "
                f"(stderr tail: {proc.stderr[-400:]!r})"
            )
        record = dict(
            self.harvest(task, trial, seed, events, feature, exec_worktree=exec_wt)
        )
        if task_spec is not None:
            record["verifiers"] = list(record["verifiers"]) + [
                self._adapter_verify(task_spec, exec_wt, feature)
            ]
        return [record]

    def _adapter(self):
        from benchmark_runner import _register
        from benchmark_runner.registry import get_adapter

        # register_all() is EXPLICIT and idempotent — importing
        # _register has no side effect, so a fresh production process
        # could not resolve any adapter without this call.
        _register.register_all()
        try:
            return get_adapter(self.benchmark_id)
        except Exception as exc:
            raise RunnerError(
                f"declared benchmark {self.benchmark_id!r} has no registered "
                f"adapter: {exc}"
            ) from exc

    def _task_spec(self, adapter, task: str):
        spec = next((t for t in adapter.list_tasks() if t.task_id == task), None)
        if spec is None:
            raise RunnerError(
                f"task {task!r} is not exposed by benchmark "
                f"{self.benchmark_id!r} — the preset's tasks must be the "
                f"adapter's tasks"
            )
        return spec

    def _prepare_task_worktree(self, task: str, feature: str, *, delegate: bool):
        """A DEDICATED task worktree carrying the adapter's lifecycle.

        This is where the routed session actually executes the
        benchmark task: adapter.prepare_task at the ROOT the backend
        will work in; adapter.isolation_for -> install_dependencies
        (the same post-prepare call run.py makes); and the CCT feature
        spec GENERATED from the adapter task —

        - ordinary: specs/<feature>/tasks.md embeds adapter.prompt_for,
          so the supervisor's prompt carries the benchmark task and
          completion means the backend did the work and checked it off;
        - delegate: routing-tasks.yaml with allowed_files derived from
          the prepared file set, and verification.yaml whose FR
          verifier is the adapter_verify bridge — packet verification
          IS the adapter's own verify, run in the packet worktree.

        A pre-existing worktree refuses (same freshness rule as every
        other evidence directory).
        """
        adapter = self._adapter()
        spec = self._task_spec(adapter, task)
        ctx_dir = self.ledger_root / "task-worktrees" / feature
        if ctx_dir.exists():
            raise RunnerError(
                f"task worktree context {ctx_dir} already exists — refusing a "
                f"run over a possibly contaminated context"
            )
        ctx_dir.mkdir(parents=True)
        # The EXISTING lifecycle, in its documented order: provisioning
        # owns venv/docker creation (skipping it broke every Python
        # aider task before launch), then prepare, then the
        # project-aware install.
        from benchmark_runner.isolation import (
            install_dependencies,
            provision_worktree,
        )

        isolation = adapter.isolation_for(spec)
        wt = provision_worktree(isolation, ctx_dir)
        adapter.prepare_task(spec, wt)
        install_dependencies(isolation, wt)
        prompt = adapter.prompt_for(spec, 1, None)
        spec_dir = wt / "specs" / feature
        spec_dir.mkdir(parents=True)
        # The task's instructions, DURABLE and CONVEYED: the packet
        # outcome and the ordinary feature task both point at this
        # committed file, so the child (real model or mock) receives
        # the adapter's actual benchmark instructions.
        (spec_dir / "benchmark-prompt.md").write_text(prompt + "\n", encoding="utf-8")
        if delegate:
            # Write authority is the ADAPTER'S solution boundary, never
            # "every prepared file": enumerating starters grants the
            # Tier-2 builder the test files and dependency manifests —
            # the verifier's own inputs. No declared boundary, no
            # delegation.
            writable = list((spec.metadata or {}).get("solution_files") or [])
            if not writable:
                raise RunnerError(
                    f"benchmark {self.benchmark_id!r} declares no "
                    f"solution_files boundary for task {task!r} — refusing to "
                    f"delegate write authority over verifier inputs"
                )
            safe_task = re.sub(r"[^A-Za-z0-9_-]", "-", task)
            allowed = "\n".join(f"      - {f}" for f in writable)
            (spec_dir / "routing-tasks.yaml").write_text(
                "schema_version: 1\n"
                "tasks:\n"
                f"  {safe_task}:\n"
                "    route_class: tier2_preferred\n"
                f"    outcome: \"Complete the benchmark task exactly as "
                f"specified in specs/{feature}/benchmark-prompt.md\"\n"
                "    reorderable: true\n"
                "    allowed_files:\n"
                f"{allowed}\n"
                "    fr_refs:\n"
                "      - FR-1\n",
                encoding="utf-8",
            )
            import hashlib as _hashlib
            import sys as _sys

            prompt_sha = _hashlib.sha256(prompt.encode("utf-8")).hexdigest()
            # The packet builder refuses wrapper-prefixed verifier
            # commands (the executable must be in a protectable
            # position), so the adapter bridge is a generated checks
            # script invoked directly — the same shape the packet
            # suite's own fixtures use.
            checks_dir = wt / "checks"
            checks_dir.mkdir(exist_ok=True)
            bridge_script = checks_dir / "adapter-verify.sh"
            bridge_script.write_text(
                "#!/usr/bin/env bash\n"
                "# Generated: packet verification IS the declared adapter's\n"
                "# own verify, run in this worktree by the bridge CLI.\n"
                f"export PYTHONPATH={self.repo_root / 'scripts'}:{self.repo_root}"
                "${CCT_EXTRA_ADAPTER_PATH:+:${CCT_EXTRA_ADAPTER_PATH}}\n"
                f"exec {_sys.executable} -m "
                f"benchmark_runner.routing_eval.adapter_verify "
                f"{self.benchmark_id} {task}\n",
                encoding="utf-8",
            )
            bridge_script.chmod(0o755)
            bridge = "bash checks/adapter-verify.sh"
            (spec_dir / "verification.yaml").write_text(
                "status: finalized\n"
                "FR-1:\n"
                f"  statement_sha: \"sha256:{prompt_sha}\"\n"
                "  verifiers:\n"
                "    - kind: test\n"
                f"      test: \"{bridge}\"\n",
                encoding="utf-8",
            )
        else:
            (spec_dir / "tasks.md").write_text(
                f"- [ ] {task}: complete the benchmark task in "
                f"specs/{feature}/benchmark-prompt.md, then change this "
                f"checkbox to [x]\n\n"
                f"## Benchmark task\n\n{prompt}\n",
                encoding="utf-8",
            )
        (wt / ".gitignore").write_text(".venv/\n", encoding="utf-8")
        for cmd in (["git", "init", "-q", str(wt)],
                    ["git", "-C", str(wt), "config", "user.email", "bench@cct"],
                    ["git", "-C", str(wt), "config", "user.name", "bench"],
                    ["git", "-C", str(wt), "add", "-A"],
                    ["git", "-C", str(wt), "commit", "-qm", f"prepared {task}"]):
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                raise RunnerError(
                    f"could not initialize the task worktree: {proc.stderr[-200:]!r}"
                )
        return spec, wt

    def _adapter_verify(self, task_spec, worktree: Path, feature: str) -> dict:
        """The adapter's own verification, ON THE EXECUTED WORKTREE,
        recorded as a driver-owned verifier with addressable evidence."""
        result = self._adapter().verify(task_spec, worktree)
        evidence = self.ledger_root / feature / "adapter-verify.txt"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        # Decision 8: scrubbed AT THE WRITE. Verifier output is
        # arbitrary tool output — env dumps, auth headers, key
        # material can all appear in it — and once raw bytes reach
        # durable storage, no later read-time scrub can un-persist
        # them. The literal credential values of the executed registry
        # are removed by VALUE, not by shape.
        evidence.write_text(
            scrub_text(result.tests_output or "",
                       secret_values=self._secret_values()),
            encoding="utf-8",
        )
        return {
            "command": f"adapter:{self.benchmark_id}:verify:{task_spec.task_id}",
            "exit_status": 0 if result.tests_passed else 1,
            "evidence_ref": str(evidence),
        }

    def _ordinary_harness(
        self,
        feature: str,
        events: list,
        harness_cmd: "str | None",
    ) -> "str | None":
        """Resolve the harness seam for one ordinary run.

        - explicit command: used as-is (tests, custom backends);
        - USE_REAL_BACKEND with events: the COMPOSITE — declared events
          replay deterministically, then every further attempt execs
          the supervisor's real default child (the auto-build driver),
          so injected failures and live task-quality evidence coexist;
        - USE_REAL_BACKEND without events: no override at all;
        - default: the deterministic T2 replay.
        """
        replay_dir = self.ledger_root / "replays" / feature
        if harness_cmd == USE_REAL_BACKEND:
            if not events:
                return None
            real_child = (
                f"bash {shlex.quote(str(self.repo_root / 'scripts' / 'auto-build-loop.sh'))} "
                f"{shlex.quote(feature)} --resume"
            )
            return materialize_replay(events, replay_dir, passthrough_cmd=real_child)
        if harness_cmd is not None:
            return harness_cmd
        return materialize_replay(events, replay_dir)

    def _rt_dir(self, feature: str, exec_worktree: "Path | None" = None) -> Path:
        base = exec_worktree if exec_worktree is not None else self.worktree
        return base / ".cct" / "auto-build" / feature / "routing"

    def _feature_id(self, task: str, trial: int) -> str:
        safe = re.sub(r"[^A-Za-z0-9_-]", "-", task)
        return f"hybrid-{safe}-trial{trial}"

    # ── harvest: durable outputs -> one routing-run record ────────────

    def harvest(
        self,
        task: str,
        trial: int,
        seed: int,
        events: Sequence[InjectedEvent],
        feature: str,
        events_offset: int = 0,
        exec_worktree: "Path | None" = None,
    ) -> Mapping[str, Any]:
        rt_dir = self._rt_dir(feature, exec_worktree)
        events_file = self.ledger_root / feature / "events.jsonl"

        decisions = self._decisions_from(events_file, rt_dir, events_offset)
        tier2, reconciliation = self._tier2_from(self.ledger_root / feature)
        scope_violations = self._scope_violations_from(events_file, events_offset)

        return {
            "schema_version": 1,
            # Computed from the registry file this run executed under —
            # never a caller-supplied label.
            "registry_digest": registry_digest_of(self.registry_path),
            "preset_digest": self.preset_digest,
            "task_set_revision": self.task_set_revision,
            "toolchain_digest": self.toolchain_digest,
            "task_id": task,
            "trial": trial,
            "trial_seed": seed,
            "mode": "cct_router",
            "profile_id": None,
            # Event provenance, recorded EXACTLY as scheduled: which
            # task received which events must be reconstructable from
            # the record, per T2's contract.
            "injected_events": [
                {"at_task_index": e.at_task_index, "outcome": e.outcome,
                 "reset_at": e.reset_at, "retry_after_sec": e.retry_after_sec}
                for e in events
            ],
            "routing_decisions": decisions,
            "tokens": {"input": None, "output": None,
                       "cache_read": None, "cache_write": None},
            "cost": {"value": None, "provenance": "unavailable",
                     "estimator": None, "inputs": None},
            "baseline": {"lint_passed": None, "typecheck_passed": None},
            "quality_gates": {
                "coverage": {"before": None, "after": None},
                "security": {"findings_by_severity": {"before": None, "after": None}},
            },
            # Row 6, MEASURED: increment C's own scope-enforcement
            # journal events, scanned — an empty list means the journal
            # was read and carried none, never "not looked".
            "scope_violations": scope_violations,
            "verifiers": [],
            "repair_cycles": [],
            "interventions": [],
            "tier2": tier2,
            "rollbacks": [],
            "reconciliation": reconciliation,
            "insufficient_evidence": {
                "cost": {"reason": "supervisor transcripts are transient; no measured cost harvested"}
            },
        }

    def _scope_violations_from(self, events_file: Path,
                               events_offset: int = 0) -> list[str]:
        """Row 6's evidence, harvested from increment C's OWN
        enforcement: every ``packet_scope`` journal event this
        invocation produced. No new detector is invented — the
        producer's refusal machinery is the single scope authority,
        and this reads what it durably journaled. Details are scrubbed
        at this boundary (they quote changed paths verbatim)."""
        violations: list[str] = []
        if not events_file.exists():
            return violations
        for line in events_file.read_text(encoding="utf-8").splitlines()[events_offset:]:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") == "packet_scope":
                violations.append(
                    scrub_text(event.get("detail") or "packet scope violation",
                               secret_values=self._secret_values())
                )
        return violations

    def _secret_values(self) -> tuple[str, ...]:
        """The dynamic literal-secret set for every write this runner
        performs: the caller's extra values plus the values resolved
        from the EXECUTED registry's credential_env references."""
        return tuple(self.secret_values) + secret_values_from_registry(
            self.registry_path
        )

    def _decisions_from(self, events_file: Path, rt_dir: Path,
                        events_offset: int = 0) -> list[dict]:
        """Group consecutive routing_candidate journal lines into
        decisions; the Nth group pairs with started-(N+1).json's
        persisted profile identity when that attempt launched."""
        groups: list[list[dict]] = []
        current: list[dict] = []
        if events_file.exists():
            for line in events_file.read_text(encoding="utf-8").splitlines()[events_offset:]:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("event") == "routing_candidate":
                    m = _CANDIDATE_RE.match(event.get("detail") or "")
                    if m:
                        current.append(
                            {
                                "id": m.group("id"),
                                "verdict": m.group("verdict"),
                                "reason": m.group("reason"),
                                "state": _state_for_reason(m.group("reason")),
                            }
                        )
                elif current:
                    groups.append(current)
                    current = []
            if current:
                groups.append(current)

        started: dict[int, str] = {}
        if rt_dir.exists():
            for f in sorted(rt_dir.glob("started-*.json")):
                try:
                    doc = json.loads(f.read_text(encoding="utf-8"))
                    started[int(f.stem.split("-")[1])] = doc["profile"]["id"]
                except (json.JSONDecodeError, KeyError, ValueError, IndexError):
                    continue

        decisions = []
        for i, considered in enumerate(groups):
            selected = started.get(i + 1)
            decisions.append(
                {
                    "considered": considered,
                    "selected": selected,
                    "reason": "harvested from the supervisor journal and the "
                    "persisted attempt record",
                    "requested_model": None,
                    "effective_model": None,
                    "endpoint": None,
                    "failure_classification": None,
                    "provisional_outcome": None,
                    # Increment B's FROZEN contract: an ordinary build
                    # run routes tier1-only — the selector itself
                    # journals tier2 candidates as "increment B routes
                    # tier1 only". Recording that closed class here is
                    # a definitional translation of the producer's
                    # behavior, not an inference.
                    "route_class": "tier1_only",
                }
            )
        return decisions

    def delegate_task(
        self,
        task: str,
        trial: int,
        seed: int,
        delegate_harness_cmd: Optional[str],
    ) -> Mapping[str, Any]:
        """Run the REAL --delegate flow for a bounded packet task and
        harvest the provisional evidence (increment C's packet identity
        + verified_provisional verdict) into a routing-run record.

        ``delegate_harness_cmd`` is the packet child (it must apply the
        packet's edits in its worktree); everything else — packet
        creation, selection, verification, the provisional ledger — is
        the unmodified supervisor.
        """
        feature = self._feature_id(task, trial)
        ledger_dir = self.ledger_root / feature
        if ledger_dir.exists():
            raise RunnerError(
                f"evidence directory {ledger_dir} already exists — refusing"
            )
        # The delegated BENCHMARK task goes through the adapter too:
        # the packet's worktree, route metadata, allowed_files, and FR
        # verifier are GENERATED from the adapter task, and packet
        # verification is the adapter's own verify via the bridge.
        if self.benchmark_id is not None:
            _spec, exec_wt = self._prepare_task_worktree(
                task, feature, delegate=True
            )
            delegate_key = re.sub(r"[^A-Za-z0-9_-]", "-", task)
        else:
            exec_wt = self.worktree
            delegate_key = task
        proc = self._invoke(feature, delegate_harness_cmd,
                            ["--profile", "unattended", "--delegate", delegate_key],
                            exec_worktree=exec_wt)
        if proc.returncode != 0:
            raise RunnerError(
                f"delegate supervisor exited {proc.returncode} for {feature} "
                f"(stdout tail: {proc.stdout[-600:]!r}; "
                f"stderr tail: {proc.stderr[-200:]!r})"
            )
        entry = self._provisional_entry(ledger_dir, delegate_key)
        if entry.get("verdict") != "verified_provisional":
            raise RunnerError(
                f"delegate run left verdict {entry.get('verdict')!r}, not "
                f"verified_provisional — no provisional evidence to record"
            )
        route_class = self._route_class_from(ledger_dir)
        record = self.harvest(task, trial, seed, [], feature,
                              exec_worktree=exec_wt)
        decisions = list(record["routing_decisions"])
        if not decisions:
            raise RunnerError("delegate run journaled no selection decision")
        builder = entry.get("builder") or {}
        chosen = dict(decisions[-1])
        chosen["provisional_outcome"] = "verified_provisional"
        chosen["route_class"] = route_class
        chosen["selected"] = builder.get("id") or chosen.get("selected")
        decisions[-1] = chosen
        return {
            **record,
            "routing_decisions": decisions,
            "tier2": {
                "delegated": True,
                "packet_id": entry["packet_id"],
                "packet_digest": entry["packet_digest"],
                # The ledger's builder identity — who actually executed
                # the packet, at which tier. Discarding these let a
                # provisional record prove delegation to nobody.
                "builder_id": builder.get("id"),
                "builder_tier": builder.get("tier"),
                "builder_provider": builder.get("provider"),
                "builder_model": builder.get("model"),
                # Row 10's denominator is increment C's OWN measure:
                # the ledger's changed_lines, computed by the packet
                # evaluator against the packet base (already
                # environment-clean — only tracked, staged product
                # counts there).
                "delegated_lines": entry.get("changed_lines"),
                "reconciliation_diff_lines": None,
            },
        }

    def reconcile_task(
        self,
        task: str,
        trial: int,
        seed: int,
        reconcile_harness_cmd: Optional[str],
    ) -> Mapping[str, Any]:
        """Run the REAL --reconcile flow for the task's provisional
        packet; the durable outcome is the ledger verdict flipping to
        accepted/accepted_with_changes with the reconciler identity."""
        feature = self._feature_id(task, trial)
        ledger_dir = self.ledger_root / feature
        events_file = ledger_dir / "events.jsonl"
        if not ledger_dir.exists():
            raise RunnerError(
                f"reconcile requires the delegate ledger at {ledger_dir}"
            )
        if self.benchmark_id is not None:
            exec_wt = self.ledger_root / "task-worktrees" / feature / "worktree"
            if not exec_wt.exists():
                raise RunnerError(
                    f"reconcile requires the delegate task worktree at {exec_wt}"
                )
            reconcile_key = re.sub(r"[^A-Za-z0-9_-]", "-", task)
        else:
            exec_wt = self.worktree
            reconcile_key = task
        before = self._provisional_entry(ledger_dir, reconcile_key)
        offset = len(events_file.read_text(encoding="utf-8").splitlines()) if events_file.exists() else 0
        proc = self._invoke(feature, reconcile_harness_cmd,
                            ["--profile", "unattended", "--reconcile", reconcile_key],
                            exec_worktree=exec_wt)
        if proc.returncode != 0:
            raise RunnerError(
                f"reconcile supervisor exited {proc.returncode} for {feature} "
                f"(stdout tail: {proc.stdout[-600:]!r}; "
                f"stderr tail: {proc.stderr[-300:]!r})"
            )
        entry = self._provisional_entry(ledger_dir, reconcile_key)
        verdict = entry.get("verdict")
        if verdict not in ("accepted", "accepted_with_changes"):
            raise RunnerError(
                f"reconcile left verdict {verdict!r} — not a reconciled outcome"
            )
        if (entry["packet_id"], entry["packet_digest"]) != (
            before.get("packet_id"), before.get("packet_digest")
        ):
            raise RunnerError("reconcile changed the packet identity — refusing")
        reconciler = entry.get("reconciler") or {}
        record = self.harvest(task, trial, seed, [], feature,
                              events_offset=offset, exec_worktree=exec_wt)
        decisions = list(record["routing_decisions"]) or [{
            "considered": [],
            "selected": reconciler.get("id"),
            "reason": "reconciler identity from the provisional ledger",
            "requested_model": None, "effective_model": None,
            "endpoint": None, "failure_classification": None,
            "provisional_outcome": None, "route_class": "tier1_only",
        }]
        chosen = dict(decisions[-1])
        chosen["selected"] = reconciler.get("id") or chosen.get("selected")
        decisions[-1] = chosen
        # Rows 9-10's numerator: how much the RECONCILER changed
        # relative to the provisional. "accepted" is increment C's own
        # digest-derived verdict that the diffs are identical — exactly
        # zero; "accepted_with_changes" is measured from the durable
        # patches, or None (insufficiency downstream), never a guess.
        builder = entry.get("builder") or {}
        recon_lines = (
            0 if verdict == "accepted"
            else self._reconciler_diff_lines(exec_wt, feature)
        )
        return {
            **record,
            "routing_decisions": decisions,
            "tier2": {
                "delegated": True,
                "packet_id": entry["packet_id"],
                "packet_digest": entry["packet_digest"],
                "builder_id": builder.get("id"),
                "builder_tier": builder.get("tier"),
                "builder_provider": builder.get("provider"),
                "builder_model": builder.get("model"),
                "delegated_lines": entry.get("changed_lines"),
                "reconciliation_diff_lines": recon_lines,
            },
            "reconciliation": {
                "packet_id": entry["packet_id"],
                "packet_digest": entry["packet_digest"],
                "outcome": "reconciled",
                "reconciler_id": reconciler.get("id"),
                "reconciler_tier": reconciler.get("tier"),
                "reconciler_provider": reconciler.get("provider"),
                "reconciler_model": reconciler.get("model"),
            },
        }

    def tick_probe(self, probe_events: Sequence[InjectedEvent] = ()) -> str:
        """One REAL `cct routing tick --due --once` with the probe seam
        answered by the T2 replay; returns the tick's stdout so the
        caller can loop until the due probe was claimed."""
        replay_dir = self.ledger_root / "replays" / "probe"
        probe_cmd = materialize_replay(list(probe_events), replay_dir, seam="probe")
        env = dict(os.environ)
        env.update(
            CCT_ROUTING_REGISTRY=str(self.registry_path),
            CCT_ROUTING_STATE=str(self.state_path),
            CCT_ROUTING_PROBE_CMD=probe_cmd,
            CCT_ROUTING_PROBE_LEDGER=str(self.ledger_root / "probe-ledger.json"),
        )
        proc = subprocess.run(
            ["bash", str(self.repo_root / "scripts" / "routing-cli.sh"),
             "tick", "--due", "--once"],
            env=env, capture_output=True, text=True, cwd=self.repo_root,
        )
        return proc.stdout + proc.stderr

    def _invoke(self, feature: str, harness_cmd: Optional[str], extra: list[str],
                exec_worktree: "Path | None" = None):
        env = dict(os.environ)
        env.update(
            CCT_ROUTING_REGISTRY=str(self.registry_path),
            CCT_ROUTING_STATE=str(self.state_path),
            CCT_SUPERVISOR_DIR=str(self.ledger_root),
            CCT_SUPERVISOR_SLEEP="true",
        )
        if harness_cmd is not None:
            # None means the REAL backend: the supervisor launches the
            # profile's actual CLI instead of a replay/mock child.
            env["CCT_SUPERVISOR_HARNESS_CMD"] = harness_cmd
        target = exec_worktree if exec_worktree is not None else self.worktree
        return subprocess.run(
            ["bash", str(self.repo_root / "scripts" / "cooldown-supervisor.sh"),
             feature, "--routing", "--worktree", str(target), *extra],
            env=env, capture_output=True, text=True, cwd=self.repo_root,
        )

    def _provisional_entry(self, ledger_dir: Path, task: str) -> Mapping[str, Any]:
        run_file = ledger_dir / "run.json"
        if not run_file.exists():
            raise RunnerError(f"no run ledger at {run_file}")
        run = json.loads(run_file.read_text(encoding="utf-8"))
        entry = (run.get("provisional") or {}).get(task)
        if not entry:
            raise RunnerError(f"no provisional entry for task {task!r}")
        return entry

    def _route_class_from(self, ledger_dir: Path) -> Optional[str]:
        events_file = ledger_dir / "events.jsonl"
        if not events_file.exists():
            return None
        for line in events_file.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") == "delegate_packet":
                m = re.search(r"route_class=(\S+)", event.get("detail") or "")
                if m:
                    return m.group(1)
        return None

    def _tier2_from(self, ledger_dir: Path) -> tuple[dict, Optional[dict]]:
        """Read increment C's provisional identity from the run ledger."""
        tier2 = {"delegated": False, "packet_id": None, "packet_digest": None,
                 "builder_id": None, "builder_tier": None,
                 "builder_provider": None, "builder_model": None,
                 "delegated_lines": None, "reconciliation_diff_lines": None}
        run_file = ledger_dir / "run.json"
        if run_file.exists():
            try:
                run = json.loads(run_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return tier2, None
            provisional = run.get("provisional") or {}
            for entry in provisional.values():
                if entry.get("verdict") == "verified_provisional":
                    builder = entry.get("builder") or {}
                    tier2 = {
                        "delegated": True,
                        "packet_id": entry.get("packet_id"),
                        "packet_digest": entry.get("packet_digest"),
                        "builder_id": builder.get("id"),
                        "builder_tier": builder.get("tier"),
                        "builder_provider": builder.get("provider"),
                        "builder_model": builder.get("model"),
                        "delegated_lines": entry.get("changed_lines"),
                        "reconciliation_diff_lines": None,
                    }
                    break
        return tier2, None

    def _reconciler_diff_lines(self, exec_wt: Path, feature: str) -> Optional[int]:
        """The reconciler-vs-provisional semantic diff, reconstructed
        from increment C's durable patches — ``prestate.patch`` (the
        provisional vs the packet base) and the latest
        ``accepted-N.patch`` (the accepted judgment vs the same base) —
        in a scratch clone, counted over MEASURED paths only
        (environment/cache churn never counts). Any gap in the
        reconstruction yields None — insufficiency downstream, never a
        zero that would claim the reconciler changed nothing."""
        rt_dir = self._rt_dir(feature, exec_wt)
        prestate = rt_dir / "prestate.patch"
        accepted = sorted(
            rt_dir.glob("accepted-*.patch"),
            key=lambda p: int(re.sub(r"[^0-9]", "", p.stem) or 0),
        )
        if not prestate.exists() or not accepted:
            return None
        scratch = self.ledger_root / feature / "recon-measure"
        if scratch.exists():
            return None
        import shutil

        def _git(*args: str) -> "subprocess.CompletedProcess[str]":
            return subprocess.run(
                ["git", "-C", str(scratch), *args],
                capture_output=True, text=True,
            )

        try:
            clone = subprocess.run(
                ["git", "clone", "-q", "--no-hardlinks", str(exec_wt), str(scratch)],
                capture_output=True, text=True,
            )
            if clone.returncode != 0:
                return None
            _git("config", "user.email", "bench@cct")
            _git("config", "user.name", "bench")
            base = _git("rev-parse", "HEAD").stdout.strip()
            shas = []
            for patch in (prestate, accepted[-1]):
                if _git("reset", "--hard", "-q", base).returncode != 0:
                    return None
                _git("clean", "-fdq")
                if patch.stat().st_size > 0:
                    if _git("apply", str(patch)).returncode != 0:
                        return None
                _git("add", "-A")
                if _git("commit", "-qm", "measure", "--allow-empty").returncode != 0:
                    return None
                shas.append(_git("rev-parse", "HEAD").stdout.strip())
            numstat = _git("diff", "--numstat", shas[0], shas[1])
            if numstat.returncode != 0:
                return None
            return measured_diff_lines(numstat.stdout)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
