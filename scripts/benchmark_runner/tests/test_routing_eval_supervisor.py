# tests/test_routing_eval_supervisor.py — routing-eval (E1 of #109) T4
# part 2: the PRODUCTION execution path.
#
# This drives the real cooldown-supervisor.sh (no fork, no patch) with
# provider behaviour supplied only through the T2 replay seam, then
# asserts the HARVESTED routing-run records carry the durable evidence
# the arc verifier consumes: an initial preferred selection, and after
# an injected usage-limit, a failover decision whose considered[] shows
# the preferred profile rejected in the closed cooldown STATE with the
# fallback selected. Live coverage here is the ordinary-run legs
# (initial + failover); the delegation/recovery/reconciliation legs are
# covered by the verifier suite over schema-valid records and by the
# routing bash suites that own those flows.

from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path

from benchmark_runner.routing_eval.scenario_config import (
    InjectedEvent,
    validate_scenario_config,
)
from benchmark_runner.routing_eval.supervisor_runner import (
    SupervisorRunner,
    _state_for_reason,
    registry_digest_of,
)
from benchmark_runner.tests.test_routing_eval_schemas import _load_json, validate

REPO_ROOT = Path(__file__).resolve().parents[3]

_REGISTRY = """\
schema_version = 1
[policy]
enabled = true
[[profiles]]
id = "preferred"
backend = "claude-code"
provider = "anthropic-subscription"
model = "sonnet"
capability_tier = "tier1"
priority = 10
quota_pool = "poolA"
roles = ["build"]
tool_profile = "full-cct"
data_policy = "approved-cloud"
credential_env = "HYBRID_KEY"
base_url_env = "HYBRID_URL"
[[profiles]]
id = "fallback"
backend = "claude-code"
provider = "deepseek-api"
model = "deepseek"
capability_tier = "tier1"
priority = 20
quota_pool = "poolB"
roles = ["build"]
tool_profile = "full-cct"
data_policy = "approved-cloud"
credential_env = "HYBRID_KEY"
base_url_env = "HYBRID_URL"
"""


class TestStateTranslation(unittest.TestCase):
    """The one prose->structure boundary, against the producer's formats."""

    def test_producer_formats_translate(self) -> None:
        cases = {
            "cooling until 2099-07-01T00:00:00Z (cooldown)": "cooldown",
            "cooling until 2099-07-01T00:00:00Z (pool:cooldown)": "pool:cooldown",
            "recovery state 'probe_due' is not selectable until a canary passes": "probe_due",
            "eligible in tier1 at priority 10 (state: unknown — never treated as healthy)": "unknown",
            "eligible in tier1 at priority 10 (state: healthy)": "healthy",
            "disabled (auth) — no automatic re-eligibility": "disabled",
        }
        for reason, state in cases.items():
            with self.subTest(reason=reason[:30]):
                self.assertEqual(_state_for_reason(reason), state)

    def test_unknown_prose_translates_to_none_never_a_guess(self) -> None:
        for trap in ("rejected because this model is accurate but ineligible",
                     "tier2 rejected because tier1 is cheaper",
                     "cooldown lifted"):
            with self.subTest(trap=trap):
                self.assertIsNone(_state_for_reason(trap))


class TestLiveSupervisorHarvest(unittest.TestCase):
    """The real supervisor produces the evidence; the harvester reads it."""

    def setUp(self) -> None:
        import tempfile

        self.base = Path(tempfile.mkdtemp(prefix="cct-t4-live."))
        self.wt = self.base / "wt"
        (self.wt / "specs" / "hybrid-task-a-trial0").mkdir(parents=True)
        (self.wt / "specs" / "hybrid-task-a-trial0" / "tasks.md").write_text(
            "- [x] done\n", encoding="utf-8"
        )
        subprocess.run(["git", "init", "-q", str(self.wt)], check=True)
        subprocess.run(["git", "-C", str(self.wt), "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", str(self.wt), "config", "user.name", "t"], check=True)
        subprocess.run(["git", "-C", str(self.wt), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.wt), "commit", "-qm", "fixture"], check=True)

        self.registry = self.base / "registry.toml"
        self.registry.write_text(_REGISTRY, encoding="utf-8")
        os.environ.setdefault("HYBRID_KEY", "hybrid-fixture-secret")
        os.environ.setdefault("HYBRID_URL", "https://hybrid-fixture.invalid")

        self.runner = SupervisorRunner(
            repo_root=REPO_ROOT,
            registry_path=self.registry,
            worktree=self.wt,
            state_path=self.base / "state.json",
            ledger_root=self.base / "ledger",
            preset_digest="sha256:" + "ab" * 32,
            task_set_revision="fixture@0",
            toolchain_digest="sha256:" + "ef" * 32,
        )

    def test_records_carry_the_computed_registry_digest(self) -> None:
        # The digest is derived from the registry FILE the run executed
        # under — a caller can no longer label one registry with
        # another's digest (there is no field to supply).
        records = self.runner.run_task("task-a", 0, 1701, [])
        self.assertEqual(
            records[0]["registry_digest"], registry_digest_of(self.registry)
        )
        self.assertNotIn("registry_digest", SupervisorRunner.__dataclass_fields__)

    def test_quota_exhaustion_produces_initial_then_failover_evidence(self) -> None:
        # quota_exhausted (text-form pool exhaustion) cools the profile
        # and drives failover; the enveloped usage_limit draws ONE
        # same-profile retry by increment B's action table — the live
        # run proved that distinction. The arc's shape across tasks,
        # also proven live: WITHIN the exhausted unit, reselection
        # excludes the attempted profile; the closed cooldown STATE
        # appears in the NEXT task's decision, read from the persisted
        # circuit store. Failover evidence therefore lives at the task
        # boundary, exactly where the verifier looks.
        # setUp created the fixture spec dir for task-a; task-b needs its own.
        feature_b = self.runner._feature_id("task-b", 0)
        spec_b = self.wt / "specs" / feature_b
        spec_b.mkdir(parents=True)
        (spec_b / "tasks.md").write_text("- [x] done\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.wt), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.wt), "commit", "-qm", "b"], check=True)

        records = self.runner.run_task(
            "task-a", 0, 1701,
            [InjectedEvent(0, "quota_exhausted", "2099-07-01T00:00:00Z", None)],
        ) + self.runner.run_task("task-b", 0, 1701, [])
        self.assertEqual(len(records), 2)

        # Both harvested records are SCHEMA-VALID — the production
        # harvester constructs what the contract requires.
        schema = _load_json(
            REPO_ROOT / "benchmarks" / "schema" / "routing-run.schema.json"
        )
        for i, record in enumerate(records):
            with self.subTest(record=i):
                self.assertEqual(validate(record, schema), [], validate(record, schema))

        # task-a decision 1: the preferred profile initially selected.
        first = records[0]["routing_decisions"]
        self.assertGreaterEqual(len(first), 2, json.dumps(first, indent=2))
        self.assertEqual(first[0]["selected"], "preferred")
        self.assertTrue(any(
            c["id"] == "preferred" and c["verdict"] == "selected"
            for c in first[0]["considered"]
        ))
        # task-a decision 2: within-unit reselection moved off the
        # exhausted profile to the fallback.
        self.assertEqual(first[1]["selected"], "fallback")

        # task-b decision 1 — THE failover evidence: the REAL selector,
        # reading the persisted circuit store, rejects the preferred
        # profile in the closed (pool:)cooldown state and selects the
        # fallback at the task boundary.
        second = records[1]["routing_decisions"]
        self.assertTrue(second, records[1])
        self.assertEqual(second[0]["selected"], "fallback")
        preferred = [c for c in second[0]["considered"] if c["id"] == "preferred"]
        self.assertTrue(preferred, second[0])
        self.assertEqual(preferred[0]["verdict"], "rejected")
        self.assertIn(preferred[0]["state"], ("cooldown", "pool:cooldown"))

    def test_success_only_run_selects_preferred_and_stops(self) -> None:
        feature = self.runner._feature_id("task-b", 0)
        spec = self.wt / "specs" / feature
        spec.mkdir(parents=True)
        (spec / "tasks.md").write_text("- [x] done\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.wt), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.wt), "commit", "-qm", "b"], check=True)
        records = self.runner.run_task("task-b", 0, 1701, [])
        decisions = records[0]["routing_decisions"]
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["selected"], "preferred")


_FIXTURE_PLUGIN = """\
'''A REAL (if tiny) out-of-tree adapter, registered through the same
extension seam a third-party benchmark uses. prepare writes the starter
the backend must edit, prompt_for describes the edit, isolation_for
returns a live directive, and verify judges the ACTUAL work.'''

from pathlib import Path

from benchmark_runner import registry
from benchmark_runner.contracts import (
    ISOLATION_WORKTREE,
    IsolationConfig,
    TaskSpec,
    VerifyResult,
)

BENCH_ID = "cct-hybrid-fixture"
ISOLATION_CALLS = []


class FixtureAdapter:
    benchmark_id = BENCH_ID
    isolation_default = ISOLATION_WORKTREE

    def list_tasks(self):
        return [TaskSpec(task_id=t, language="text",
                         metadata={"solution_files": ["solution.txt"]})
                for t in ("t0", "t1", "t2", "t4", "bounded-fix")]

    def isolation_for(self, task):
        ISOLATION_CALLS.append(task.task_id)
        return IsolationConfig(tier=ISOLATION_WORKTREE)

    def prepare_task(self, task, worktree):
        # A realistically shaped starter: the solution edits ONE of six
        # lines, so the packet rewrite-fraction guard (a real
        # increment-C thrash control) sees an edit, not a rewrite.
        Path(worktree).mkdir(parents=True, exist_ok=True)
        (Path(worktree) / "solution.txt").write_text(
            f"# task {task.task_id}\\n"
            "# edit only the status line\\n"
            "config: fixed\\n"
            "status: UNSOLVED\\n"
            "notes: none\\n"
            "end: true\\n",
            encoding="utf-8",
        )

    def prompt_for(self, task, attempt, prior):
        return (
            f"Benchmark task {task.task_id}: replace the word UNSOLVED "
            f"with SOLVED on the status line of solution.txt."
        )

    def verify(self, task, worktree):
        solution = Path(worktree) / "solution.txt"
        text = solution.read_text(encoding="utf-8") if solution.exists() else ""
        solved = "status: SOLVED" in text and "UNSOLVED" not in text
        return VerifyResult(
            tests_passed=solved,
            tests_output=(
                f"fixture verify for {task.task_id}: "
                + ("SOLVED" if solved else "UNSOLVED")
            ),
        )

    def golden_patch(self, task):  # pragma: no cover - unused here
        raise NotImplementedError


if BENCH_ID not in registry.list_adapter_ids():
    registry.register_adapter(BENCH_ID, FixtureAdapter)
"""


def _register_fixture_adapter(plugin_dir: Path) -> str:
    """Write the fixture adapter as an OUT-OF-TREE plugin module and
    register it through the same seam the bridge subprocess uses —
    one definition, both processes."""
    import importlib
    import sys as _sys

    plugin = plugin_dir / "cct_hybrid_fixture_adapter.py"
    plugin.write_text(_FIXTURE_PLUGIN, encoding="utf-8")
    if str(plugin_dir) not in _sys.path:
        _sys.path.insert(0, str(plugin_dir))
    importlib.import_module("cct_hybrid_fixture_adapter")
    os.environ["CCT_EXTRA_ADAPTER_MODULE"] = "cct_hybrid_fixture_adapter"
    os.environ["CCT_EXTRA_ADAPTER_PATH"] = str(plugin_dir)
    return "cct-hybrid-fixture"


_ARC_REGISTRY = """\
schema_version = 1
[policy]
enabled = true
[route_classes.tier2_preferred]
tier_order = ["tier2", "tier1"]
[[profiles]]
id = "preferred"
backend = "claude-code"
provider = "anthropic-subscription"
model = "sonnet"
capability_tier = "tier1"
priority = 10
quota_pool = "poolA"
roles = ["build", "reconcile"]
tool_profile = "full-cct"
data_policy = "approved-cloud"
credential_env = "HYBRID_KEY"
base_url_env = "HYBRID_URL"
[[profiles]]
id = "fallback"
backend = "claude-code"
provider = "deepseek-api"
model = "deepseek"
capability_tier = "tier1"
priority = 20
quota_pool = "poolB"
roles = ["build"]
tool_profile = "full-cct"
data_policy = "approved-cloud"
credential_env = "HYBRID_KEY"
base_url_env = "HYBRID_URL"
[[profiles]]
id = "t2loc"
backend = "claude-code"
provider = "local-ollama"
model = "qwen-coder"
capability_tier = "tier2"
priority = 5
quota_pool = "poolLocal"
roles = ["bounded-build"]
tool_profile = "local-builder-minimal"
data_policy = "local-only"
credential_env = "HYBRID_KEY"
base_url_env = "HYBRID_URL"
"""



_DMOCK = """\
#!/usr/bin/env bash
p="${CCT_ROUTING_PROFILE:-none}"
cnt="$MOCK_DIR/count-$p"
n=$(( $(cat "$cnt" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$cnt"
cat > "$MOCK_DIR/prompt-$p-$n.txt"
spec="$MOCK_DIR/$p.spec"
[[ -f "$spec" ]] || { echo "dmock: no spec for $p"; exit 97; }
line=$(sed -n "${n}p" "$spec"); [[ -z "$line" ]] && line=$(tail -1 "$spec")
edit=$(cut -d'|' -f1 <<< "$line")
fixture=$(cut -d'|' -f2 <<< "$line")
code=$(cut -d'|' -f3 <<< "$line")
[[ "$edit" != "-" ]] && bash "$edit"
[[ "$fixture" != "-" ]] && cat "$fixture"
exit "$code"
"""


class TestFullArcThroughTheRealSupervisor(unittest.TestCase):
    """T4's closing proof: the production runner drives the UNMODIFIED
    supervisor + tick CLI through the entire #109 §12 arc — initial
    preferred build, quota exhaustion, task-boundary failover, bounded
    Tier-2 delegation to verified_provisional, probe-verified recovery,
    preferred re-selection, and Tier-1 reconciliation of the SAME
    packet — and verify_arc proves it from the harvested records alone.
    The cooldown window is real seconds (retry-after), so this test
    waits briefly for the probe to fall due; every other transition is
    event-driven."""

    def setUp(self) -> None:
        import tempfile

        self.base = Path(tempfile.mkdtemp(prefix="cct-t4-arc."))
        self.wt = self.base / "wt"
        self.mock = self.base / "mock"
        self.mock.mkdir(parents=True)
        # The baseline is MINIMAL: no hand-built hybrid-* specs and no
        # hand-built packet metadata — every task worktree, feature
        # spec, routing-tasks.yaml, and verification.yaml is GENERATED
        # from the adapter by the production runner.
        self.wt.mkdir()
        (self.wt / "README.md").write_text("baseline\n", encoding="utf-8")
        for cmd in (["git", "init", "-q", str(self.wt)],
                    ["git", "-C", str(self.wt), "config", "user.email", "t@t"],
                    ["git", "-C", str(self.wt), "config", "user.name", "t"],
                    ["git", "-C", str(self.wt), "add", "-A"],
                    ["git", "-C", str(self.wt), "commit", "-qm", "fixture"]):
            subprocess.run(cmd, check=True)

        self.registry = self.base / "registry.toml"
        self.registry.write_text(_ARC_REGISTRY, encoding="utf-8")
        os.environ.setdefault("HYBRID_KEY", "hybrid-fixture-secret")
        os.environ.setdefault("HYBRID_URL", "https://hybrid-fixture.invalid")

        dmock = self.base / "dmock.sh"
        dmock.write_text(_DMOCK, encoding="utf-8")
        dmock.chmod(0o755)
        # The ordinary child SOLVES the benchmark task (the adapter's
        # verify judges this) and checks off the generated feature
        # task; the delegate child solves within its packet scope.
        solve = self.base / "solve.sh"
        solve.write_text(
            "sed 's/status: UNSOLVED/status: SOLVED/' solution.txt > solution.txt.tmp\n"
            "mv solution.txt.tmp solution.txt\n"
            "for f in specs/*/tasks.md; do\n"
            "  sed 's/- \\[ \\]/- [x]/' \"$f\" > \"$f.tmp\" && mv \"$f.tmp\" \"$f\"\n"
            "done\n",
            encoding="utf-8",
        )
        solve_packet = self.base / "solve-packet.sh"
        solve_packet.write_text(
            "sed 's/status: UNSOLVED/status: SOLVED/' solution.txt > solution.txt.tmp\n"
            "mv solution.txt.tmp solution.txt\n",
            encoding="utf-8",
        )
        quota = self.base / "quota.txt"
        quota.write_text(
            "You have hit your 5-hour limit. Your limit will reset at "
            "2000-01-01T00:00:00Z.\n",
            encoding="utf-8",
        )
        verdict = self.base / "verdict-accepted.txt"
        verdict.write_text("RECONCILE_VERDICT: accepted\n", encoding="utf-8")
        # Per-profile invocation scripts, BOTH trials, in order:
        #   preferred: t0 solve; t1 quota; t4 solve; reconcile verdict
        #   fallback:  t1 retry solve; t2 solve
        #   t2loc:     delegate packet solve
        (self.mock / "preferred.spec").write_text(
            "".join([f"{solve}|-|0\n", f"-|{quota}|1\n",
                     f"{solve}|-|0\n", f"-|{verdict}|0\n"] * 2),
            encoding="utf-8",
        )
        (self.mock / "fallback.spec").write_text(
            f"{solve}|-|0\n" * 4, encoding="utf-8"
        )
        (self.mock / "t2loc.spec").write_text(
            f"{solve_packet}|-|0\n" * 2, encoding="utf-8"
        )
        self.dmock_cmd = f"MOCK_DIR='{self.mock}' bash '{dmock}'"

        bench_id = _register_fixture_adapter(self.base)
        self.addCleanup(os.environ.pop, "CCT_EXTRA_ADAPTER_MODULE", None)
        self.addCleanup(os.environ.pop, "CCT_EXTRA_ADAPTER_PATH", None)
        self.config = validate_scenario_config({
            "benchmark": bench_id,
            "scenario": "hybrid-routing",
            "cost_basis": "measured",
            "trials": 2,
            "trial_seeds": [1701, 1702],
            "task": ["t0", "t1", "t2", "bounded-fix", "t4"],
            "tier1_only_tasks": ["t0"],
            "delegate_tasks": ["bounded-fix"],
            # The provider reset is in the PAST: the pool cools and the
            # probe is due IMMEDIATELY, so nothing in this arc waits on
            # wall-clock time — due-ness is event-driven, per FR-E1-1.
            "event_stream": [
                {"at_task_index": 1, "outcome": "quota_exhausted",
                 "reset_at": "2000-01-01T00:00:00Z"},
            ],
            "arms": [
                {"kind": "always_best"},
                {"kind": "always_cheapest"},
                {"kind": "oracle"},
                {"kind": "cct_router", "registry": str(self.registry)},
            ],
        })
        from benchmark_runner.routing_eval.injection import preset_digest

        self.runner = SupervisorRunner(
            repo_root=REPO_ROOT,
            registry_path=self.registry,
            worktree=self.wt,
            state_path=self.base / "state.json",
            ledger_root=self.base / "ledger",
            preset_digest=preset_digest(self.config),
            task_set_revision="fixture@0",
            toolchain_digest="sha256:" + "ef" * 32,
            benchmark_id=bench_id,
        )

    def test_the_complete_arc_from_harvested_evidence_only(self) -> None:
        """The PRODUCTION entrypoint drives the preset-shaped config
        through the unmodified supervisor + tick CLI; the artifact's
        proof is verify_arc over the harvested records alone."""
        from benchmark_runner.routing_eval.scenario import run_hybrid_scenario

        artifact = run_hybrid_scenario(
            self.config,
            self.runner,
            preferred_profile="preferred",
            tier2_profiles={"t2loc"},
            delegate_harness_cmd=self.dmock_cmd,
            reconcile_harness_cmd=self.dmock_cmd,
            ordinary_harness_cmd=self.dmock_cmd,
        )
        self.assertTrue(artifact.arc.complete)
        # BOTH trials proved the complete arc independently — trial 1
        # started from the pristine baseline, not from trial 0's
        # healthy circuit state or accepted reconciliation edits.
        self.assertEqual(len(artifact.arc.trials), 2)
        for trial_report in artifact.arc.trials:
            self.assertTrue(trial_report.complete, trial_report.missing())
        legs = {l.leg: l for l in artifact.arc.trials[0].legs}
        # The Tier-2 leg is proven by the LEDGER's builder identity...
        provisional = artifact.records[legs["tier2_provisional"].evidence[0]]
        self.assertEqual(provisional["tier2"]["builder_id"], "t2loc")
        self.assertEqual(provisional["tier2"]["builder_tier"], "tier2")
        self.assertEqual(
            provisional["routing_decisions"][-1]["selected"], "t2loc"
        )
        # ...and reconciliation by the TIER-1 reconciler of the SAME packet.
        recon = artifact.records[legs["reconciliation"].evidence[1]]
        self.assertEqual(recon["reconciliation"]["reconciler_id"], "preferred")
        self.assertEqual(recon["reconciliation"]["reconciler_tier"], "tier1")
        self.assertEqual(
            recon["reconciliation"]["packet_digest"],
            provisional["tier2"]["packet_digest"],
        )
        # Registry identity was COMPUTED from the executed registry.
        for record in artifact.records:
            self.assertEqual(
                record["registry_digest"], registry_digest_of(self.registry)
            )
        # The DECLARED benchmark executed through the FULL adapter
        # lifecycle. For every ordinary record: the adapter's verify
        # PASSED against the executed worktree (the routed child
        # actually solved the task — starter existence proves nothing),
        # with addressable evidence.
        for record in artifact.records:
            if record["tier2"]["delegated"] or record["reconciliation"]:
                continue
            adapter_verifiers = [
                v for v in record["verifiers"]
                if v["command"].startswith("adapter:cct-hybrid-fixture:verify:")
            ]
            self.assertEqual(len(adapter_verifiers), 1, record["task_id"])
            self.assertEqual(adapter_verifiers[0]["exit_status"], 0, record["task_id"])
            evidence = Path(adapter_verifiers[0]["evidence_ref"])
            self.assertIn("SOLVED", evidence.read_text(encoding="utf-8"))
        # The generated feature spec EMBEDS the adapter's prompt, and
        # the executed worktree holds the solved task: prompt_for and
        # prepare_task shaped what the routed session actually did.
        trial0 = self.base / "ledger" / "trial-0"
        t0_wt = trial0 / "task-worktrees" / "hybrid-t0-trial0" / "worktree"
        tasks_md = (t0_wt / "specs" / "hybrid-t0-trial0" / "tasks.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("replace the word UNSOLVED", tasks_md)
        self.assertIn(
            "status: SOLVED",
            (t0_wt / "solution.txt").read_text(encoding="utf-8"),
        )
        # isolation_for was consulted for every prepared task.
        import cct_hybrid_fixture_adapter as _plugin

        self.assertIn("t0", _plugin.ISOLATION_CALLS)
        # The DELEGATED benchmark task went through the adapter too:
        # its packet metadata was GENERATED (no hand-built specs exist
        # in this fixture), its allowed_files came from the prepared
        # file set, and packet verification ran the adapter bridge.
        del_wt = trial0 / "task-worktrees" / "hybrid-bounded-fix-trial0" / "worktree"
        routing_yaml = (del_wt / "specs" / "hybrid-bounded-fix-trial0"
                        / "routing-tasks.yaml").read_text(encoding="utf-8")
        self.assertIn("solution.txt", routing_yaml)
        # The packet's write authority is EXACTLY the adapter's
        # solution boundary, and its outcome points at the durable
        # benchmark prompt the child actually received.
        self.assertNotIn("specs/", routing_yaml.split("allowed_files")[1].split("fr_refs")[0])
        self.assertIn("benchmark-prompt.md", routing_yaml)
        prompt_file = (del_wt / "specs" / "hybrid-bounded-fix-trial0"
                       / "benchmark-prompt.md").read_text(encoding="utf-8")
        self.assertIn("replace the word UNSOLVED", prompt_file)
        packet_prompt = (self.mock / "prompt-t2loc-1.txt").read_text(encoding="utf-8")
        self.assertIn("benchmark-prompt.md", packet_prompt)
        verification_yaml = (del_wt / "specs" / "hybrid-bounded-fix-trial0"
                             / "verification.yaml").read_text(encoding="utf-8")
        self.assertIn("bash checks/adapter-verify.sh", verification_yaml)
        bridge_script = (del_wt / "checks" / "adapter-verify.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("adapter_verify cct-hybrid-fixture bounded-fix",
                      bridge_script)
        ddirs = list((del_wt / ".cct" / "auto-build" / "hybrid-bounded-fix-trial0"
                      / "routing").glob("delegate-*"))
        self.assertTrue(ddirs, "no packet namespace generated")
        import json as _json

        outcome = _json.loads((ddirs[0] / "packet-outcome.json").read_text(
            encoding="utf-8"
        ))
        self.assertEqual(outcome["outcome"], "packet_verified")
        # PER-TRIAL ISOLATION, load-bearing three ways. (a) Distinct
        # contexts exist per trial, with distinct task worktrees.
        self.assertTrue((self.base / "ledger" / "trial-0").is_dir())
        self.assertTrue((self.base / "ledger" / "trial-1").is_dir())
        t0_wt_trial1 = (self.base / "ledger" / "trial-1"
                        / "task-worktrees" / "hybrid-t0-trial1" / "worktree")
        self.assertTrue(t0_wt_trial1.is_dir())
        self.assertNotEqual(t0_wt, t0_wt_trial1)
        # (b) The baseline worktree is pristine.
        status = subprocess.run(
            ["git", "-C", str(self.wt), "status", "--porcelain"],
            capture_output=True, text=True, check=True,
        )
        self.assertEqual(status.stdout.strip(), "", "baseline worktree dirty")
        # (c) THE CIRCUIT STORE IS FRESH PER TRIAL: trial 1's initial
        # decision sees the preferred profile in state 'unknown' —
        # under any shared state (worktree-sharing mutations included,
        # since state rides the trial context) it would arrive
        # 'healthy' from trial 0's successes.
        trial1_initial = next(
            r for r in artifact.records
            if r["trial"] == 1 and r["task_id"] == "t0"
        )
        preferred_candidates = [
            c
            for d in trial1_initial["routing_decisions"]
            for c in d["considered"]
            if c["id"] == "preferred"
        ]
        self.assertTrue(preferred_candidates)
        self.assertEqual(preferred_candidates[0]["state"], "unknown")

    def test_a_preexisting_trial_context_is_refused(self) -> None:
        from benchmark_runner.routing_eval.supervisor_runner import RunnerError

        first = self.runner.for_trial(0)
        self.assertTrue(first.worktree.is_dir())
        with self.assertRaisesRegex(RunnerError, "contaminated trial context"):
            self.runner.for_trial(0)

    def test_use_real_backend_with_events_builds_the_composite(self) -> None:
        # USE_REAL_BACKEND must not discard the declared failure: the
        # resolved harness is the composite replay whose passthrough
        # execs the supervisor's real default child.
        from benchmark_runner.routing_eval.supervisor_runner import (
            USE_REAL_BACKEND,
        )

        trial_runner = self.runner.for_trial(5)
        events = [InjectedEvent(0, "quota_exhausted", "2000-01-01T00:00:00Z", None)]
        cmd = trial_runner._ordinary_harness("feat-x", events, USE_REAL_BACKEND)
        self.assertIsNotNone(cmd)
        script = Path(cmd.split("bash ", 1)[1].strip("'\""))
        body = script.read_text(encoding="utf-8")
        self.assertIn("auto-build-loop.sh", body)
        self.assertIn("exec bash -c", body)
        # ...while USE_REAL_BACKEND with no events keeps NO override.
        self.assertIsNone(
            trial_runner._ordinary_harness("feat-y", [], USE_REAL_BACKEND)
        )

    def test_delegation_without_a_solution_boundary_is_refused(self) -> None:
        # Write authority over verifier inputs is never granted by
        # enumeration: no declared solution_files, no delegation.
        import cct_hybrid_fixture_adapter as _plugin

        original = _plugin.FixtureAdapter.list_tasks

        def stripped(adapter_self):
            from benchmark_runner.contracts import TaskSpec

            return [TaskSpec(task_id="bounded-fix", language="text")]

        _plugin.FixtureAdapter.list_tasks = stripped
        self.addCleanup(
            setattr, _plugin.FixtureAdapter, "list_tasks", original
        )
        from benchmark_runner.routing_eval.supervisor_runner import RunnerError

        trial_runner = self.runner.for_trial(6)
        with self.assertRaisesRegex(RunnerError, "solution_files boundary"):
            trial_runner.delegate_task("bounded-fix", 0, 1701, self.dmock_cmd)

    def test_a_fresh_process_resolves_the_shipped_adapters(self) -> None:
        # The owner's reproduction: importing _register has no side
        # effect, so without an explicit register_all() a fresh
        # production process cannot resolve aider-polyglot.
        proc = subprocess.run(
            ["python3", "-c",
             "from benchmark_runner import _register, registry;"
             "_register.register_all();"
             "ids = registry.list_adapter_ids();"
             "assert 'aider-polyglot' in ids, ids;"
             "print('ok')"],
            capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "scripts")},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("ok", proc.stdout)

    def test_a_runner_declaring_the_wrong_benchmark_is_refused(self) -> None:
        from benchmark_runner.routing_eval.scenario import (
            RecordInvalid,
            run_hybrid_scenario,
        )
        import dataclasses

        wrong = dataclasses.replace(self.runner, benchmark_id="stub")
        with self.assertRaisesRegex(RecordInvalid, "declared workload"):
            run_hybrid_scenario(
                self.config, wrong,
                preferred_profile="preferred", tier2_profiles={"t2loc"},
                delegate_harness_cmd=self.dmock_cmd,
                reconcile_harness_cmd=self.dmock_cmd,
            )

    def test_an_unknown_task_for_the_declared_benchmark_is_refused(self) -> None:
        from benchmark_runner.routing_eval.supervisor_runner import RunnerError

        with self.assertRaisesRegex(RunnerError, "not exposed by benchmark"):
            self.runner.run_task("no-such-task", 0, 1701, [])

    def test_an_unregistered_benchmark_is_refused(self) -> None:
        import dataclasses

        from benchmark_runner.routing_eval.supervisor_runner import RunnerError

        bogus = dataclasses.replace(self.runner, benchmark_id="no-such-bench")
        with self.assertRaisesRegex(RunnerError, "no registered adapter"):
            bogus.run_task("t0", 0, 1701, [])

    def test_a_runner_on_a_different_registry_is_refused(self) -> None:
        # The cct_router arm names the policy under measurement; a
        # runner executing a different registry must never proceed.
        from benchmark_runner.routing_eval.scenario import (
            RecordInvalid,
            run_hybrid_scenario,
        )

        other = self.base / "other-registry.toml"
        other.write_text(_ARC_REGISTRY, encoding="utf-8")
        import dataclasses

        wrong = dataclasses.replace(self.runner, registry_path=other)
        with self.assertRaisesRegex(RecordInvalid, "configured policy"):
            run_hybrid_scenario(
                self.config, wrong,
                preferred_profile="preferred", tier2_profiles={"t2loc"},
                delegate_harness_cmd=self.dmock_cmd,
                reconcile_harness_cmd=self.dmock_cmd,
            )


class TestAiderPresetTasks(unittest.TestCase):
    """The checked preset's REAL tasks, gated on the pinned polyglot
    cache (skipped where it is absent, e.g. CI smoke)."""

    @classmethod
    def setUpClass(cls) -> None:
        import tempfile

        cache = REPO_ROOT / "benchmarks" / ".cache" / "polyglot"
        if not cache.exists():
            raise unittest.SkipTest("polyglot cache not fetched on this host")
        cls.base = Path(tempfile.mkdtemp(prefix="cct-aider-prep."))
        cls.runner = SupervisorRunner(
            repo_root=REPO_ROOT,
            registry_path=cls.base / "unused-registry.toml",
            worktree=cls.base / "unused-wt",
            state_path=cls.base / "state.json",
            ledger_root=cls.base / "ledger",
            preset_digest="sha256:" + "ab" * 32,
            task_set_revision="fixture@0",
            toolchain_digest="sha256:" + "ef" * 32,
            benchmark_id="aider-polyglot",
        )

    def test_python_task_provisions_its_venv(self) -> None:
        # The owner's reproduction: skipping provision_worktree broke
        # python/book-store before launch. The provisioned lifecycle
        # must create the venv the install step requires.
        _spec, wt = self.runner._prepare_task_worktree(
            "python/book-store", "aider-py-prep", delegate=False
        )
        self.assertTrue((wt / ".venv").exists(), "venv was not provisioned")
        self.assertTrue((wt / "book_store.py").exists())
        prompt = (wt / "specs" / "aider-py-prep" / "benchmark-prompt.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("book_store.py", prompt)

    def test_go_delegation_scope_is_the_solution_boundary(self) -> None:
        # The owner's reproduction: enumeration granted bowling_test.go,
        # cases_test.go, and go.mod. The generated packet must carry
        # ONLY the adapter's solution files.
        _spec, wt = self.runner._prepare_task_worktree(
            "go/bowling", "aider-go-del", delegate=True
        )
        routing_yaml = (wt / "specs" / "aider-go-del" / "routing-tasks.yaml").read_text(
            encoding="utf-8"
        )
        allowed = routing_yaml.split("allowed_files:")[1].split("fr_refs:")[0]
        self.assertIn("bowling.go", allowed)
        for forbidden in ("bowling_test.go", "cases_test.go", "go.mod", ".venv"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, allowed)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
