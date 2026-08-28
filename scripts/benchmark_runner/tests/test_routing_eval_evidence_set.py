# tests/test_routing_eval_evidence_set.py — routing-shadow T1.
#
# The E1 evidence-set orchestration, proven LIVE: publish_evidence_set
# drives the hybrid scenario (router arm), the fixed-profile matrix
# sweep through the UNMODIFIED production supervisor under
# stage-specific one-profile derived registries, the control
# selections, and the report — then publishes SET-atomically. The
# owner's three load-bearing discriminators are pinned here:
# a reconciler holding bounded-build cannot steal the pinned builder
# leg; manifest-only fingerprint tampering fails with genuine artifact
# bytes; and (in the quality suite) provisional process damage
# survives a clean reconciliation.

from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

from benchmark_runner.routing_eval.evidence_set import (
    ARTIFACT_MANIFEST,
    ARTIFACT_MATRIX,
    ARTIFACT_REPORT,
    ARTIFACT_RUNS,
    EvidenceSetError,
    EvidenceSetInvalid,
    PublishedEvidenceSet,
    _publish,
    derive_single_profile_registry,
    discover_evidence_sets,
    publish_evidence_set,
    run_profile_cell,
    set_id_of,
    validate_evidence_set,
    _profile_declarations,
)
from benchmark_runner.routing_eval.scenario_config import (
    validate_scenario_config,
)
from benchmark_runner.tests.test_routing_eval_supervisor import (
    _ARC_REGISTRY,
    _DMOCK,
    _register_fixture_adapter,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _git(*args: str) -> None:
    subprocess.run(list(args), check=True, capture_output=True)


class _EvidenceFixture(unittest.TestCase):
    """The T4 arc fixture, one-trial shape, plus sweep mock specs."""

    def setUp(self) -> None:
        import tempfile

        self.base = Path(tempfile.mkdtemp(prefix="cct-e2-evidence."))
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.wt = self.base / "wt"
        self.wt.mkdir(parents=True)
        (self.wt / "README.md").write_text("baseline\n", encoding="utf-8")
        _git("git", "init", "-q", str(self.wt))
        _git("git", "-C", str(self.wt), "config", "user.email", "t@t")
        _git("git", "-C", str(self.wt), "config", "user.name", "t")
        _git("git", "-C", str(self.wt), "add", "-A")
        _git("git", "-C", str(self.wt), "commit", "-qm", "fixture")

        self.registry = self.base / "registry.toml"
        self.registry.write_text(_ARC_REGISTRY, encoding="utf-8")
        os.environ.setdefault("HYBRID_KEY", "hybrid-fixture-secret")
        os.environ.setdefault("HYBRID_URL", "https://hybrid-fixture.invalid")

        dmock = self.base / "dmock.sh"
        dmock.write_text(_DMOCK, encoding="utf-8")
        dmock.chmod(0o755)
        self.solve = self.base / "solve.sh"
        self.solve.write_text(
            "sed 's/status: UNSOLVED/status: SOLVED/' solution.txt > solution.txt.tmp\n"
            "mv solution.txt.tmp solution.txt\n"
            "for f in specs/*/tasks.md; do\n"
            "  sed 's/- \\[ \\]/- [x]/' \"$f\" > \"$f.tmp\" && mv \"$f.tmp\" \"$f\"\n"
            "done\n",
            encoding="utf-8",
        )
        self.solve_packet = self.base / "solve-packet.sh"
        self.solve_packet.write_text(
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
        self.verdict = self.base / "verdict-accepted.txt"
        self.verdict.write_text(
            'RECONCILE_VERDICT: accepted\n'
            '{"type":"result","total_cost_usd":0.005}\n',
            encoding="utf-8",
        )
        # real backends end their transcript with a result record
        # carrying total_cost_usd; the durable transcript-N.log copies
        # are where harvest measures cost from
        self.cost = self.base / "cost.txt"
        self.cost.write_text('{"type":"result","total_cost_usd":0.01}\n',
                             encoding="utf-8")

        # router-arc mock (per-profile ordered specs, ONE trial)
        self.mock = self.base / "mock"
        self.mock.mkdir()
        (self.mock / "preferred.spec").write_text(
            f"{self.solve}|{self.cost}|0\n-|{quota}|1\n"
            f"{self.solve}|{self.cost}|0\n-|{self.verdict}|0\n",
            encoding="utf-8",
        )
        (self.mock / "fallback.spec").write_text(
            f"{self.solve}|{self.cost}|0\n" * 4, encoding="utf-8"
        )
        (self.mock / "t2loc.spec").write_text(
            f"{self.solve_packet}|{self.cost}|0\n" * 2, encoding="utf-8"
        )
        self.arc_cmd = f"MOCK_DIR='{self.mock}' bash '{dmock}'"

        # sweep mocks: every ordinary invocation solves; the sweep
        # reconcile leg gets its own mock dir answering the verdict
        self.sweep_mock = self.base / "sweep-mock"
        self.sweep_mock.mkdir()
        for profile in ("preferred", "fallback"):
            (self.sweep_mock / f"{profile}.spec").write_text(
                f"{self.solve}|{self.cost}|0\n", encoding="utf-8"
            )
        (self.sweep_mock / "t2loc.spec").write_text(
            f"{self.solve_packet}|{self.cost}|0\n", encoding="utf-8"
        )
        self.sweep_cmd = f"MOCK_DIR='{self.sweep_mock}' bash '{dmock}'"
        self.sweep_recon_mock = self.base / "sweep-recon-mock"
        self.sweep_recon_mock.mkdir()
        (self.sweep_recon_mock / "preferred.spec").write_text(
            f"-|{self.verdict}|0\n", encoding="utf-8"
        )
        self.sweep_recon_cmd = (
            f"MOCK_DIR='{self.sweep_recon_mock}' bash '{dmock}'"
        )
        self.dmock = dmock

        self.bench_id = _register_fixture_adapter(self.base)
        self.addCleanup(os.environ.pop, "CCT_EXTRA_ADAPTER_MODULE", None)
        self.addCleanup(os.environ.pop, "CCT_EXTRA_ADAPTER_PATH", None)
        self.config = validate_scenario_config({
            "benchmark": self.bench_id,
            "scenario": "hybrid-routing",
            "cost_basis": "measured",
            "trials": 1,
            "trial_seeds": [1701],
            "task": ["t0", "t1", "t2", "bounded-fix", "t4"],
            "tier1_only_tasks": ["t0"],
            "delegate_tasks": ["bounded-fix"],
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


class TestPublishEvidenceSetLive(_EvidenceFixture):
    def test_the_complete_set_publishes_validates_and_binds(self) -> None:
        output_root = self.base / "evidence"
        published = publish_evidence_set(
            self.config,
            self.registry,
            output_root,
            repo_root=REPO_ROOT,
            baseline_worktree=self.wt,
            benchmark_id=self.bench_id,
            preferred_profile="preferred",
            tier2_profiles=frozenset({"t2loc"}),
            task_set_revision="rev-e2e",
            toolchain_digest="sha256:tc",
            workdir=self.base / "work",
            reconciler_id="preferred",
            ordinary_harness_cmd=self.arc_cmd,
            delegate_harness_cmd=self.arc_cmd,
            reconcile_harness_cmd=self.arc_cmd,
            sweep_harness_cmd=self.sweep_cmd,
            sweep_delegate_harness_cmd=self.sweep_cmd,
            sweep_reconcile_harness_cmd=self.sweep_recon_cmd,
        )
        self.assertIsInstance(published, PublishedEvidenceSet)
        self.assertFalse(published.existed)
        root = published.path
        for name in (ARTIFACT_RUNS, ARTIFACT_MATRIX, ARTIFACT_REPORT,
                     ARTIFACT_MANIFEST):
            self.assertTrue((root / name).is_file(), name)

        # the loader's own validation passes and the recomputed id IS
        # the directory name (the name is a convenience, the bytes are
        # the identity)
        validated = validate_evidence_set(root)
        self.assertEqual(validated["set_id"], root.name)
        self.assertEqual(published.set_id, root.name)

        # matrix coverage: 5 tasks x 3 profiles x 1 trial = 15 cells;
        # ordinary tasks execute build-role profiles (preferred,
        # fallback), the delegate task executes only the bounded-build
        # profile (t2loc) — 4*2 + 1 = 9 executed, 6 ineligible
        matrix = validated["matrix"]
        cells = matrix["cells"]
        self.assertEqual(len(cells), 15)
        executed = [c for c in cells if c["eligible"]]
        self.assertEqual(len(executed), 9)
        delegate_cells = [c for c in executed
                          if c["task_id"] == "bounded-fix"]
        self.assertEqual([c["profile_id"] for c in delegate_cells],
                         ["t2loc"])
        # the delegated sweep cell folded its two lifecycle legs to
        # ONE cell that PASSES via the reconciled outcome
        self.assertEqual(delegate_cells[0]["result"], "pass")

        # the report is the persisted v1 contract, arms complete
        report = validated["report"]
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(
            set(report["arms"]),
            {"always_best", "always_cheapest", "oracle", "cct_router"},
        )
        # the router's bounded-fix lifecycle folded to one per-trial row
        router_tasks = report["arms"]["cct_router"]["tasks"]
        self.assertEqual(len(router_tasks["bounded-fix"]["per_trial"]), 1)

        # every routing-run evidence reference resolves INSIDE the set
        for record in validated["records"]:
            for verifier in record.get("verifiers") or []:
                ref = verifier["evidence_ref"]
                self.assertFalse(Path(ref).is_absolute())
                self.assertTrue((root / ref).is_file(), ref)

        # discovery lists the set and structurally excludes hidden
        # (staging-shaped) siblings
        (output_root / ".staging-leftover").mkdir()
        self.assertEqual(discover_evidence_sets(output_root), [root])

        # ── idempotent duplicate vs differing-content refusal ──
        report_doc = dict(report)
        report_doc.pop("source_artifacts")
        from benchmark_runner.routing_eval.outcome_matrix import (
            Fingerprint,
            matrix_from_record,
        )

        matrix_obj = matrix_from_record(json.loads(
            (root / ARTIFACT_MATRIX).read_text(encoding="utf-8")))

        fp = Fingerprint(
            registry_digest=validated["manifest"]["fingerprint"]["registry_digest"],
            preset_digest=validated["manifest"]["fingerprint"]["preset_digest"],
            execution_identity=tuple(
                validated["manifest"]["fingerprint"]["execution_identity"]
            ),
            task_set_revision=validated["manifest"]["fingerprint"]["task_set_revision"],
            toolchain_digest=validated["manifest"]["fingerprint"]["toolchain_digest"],
        )
        again = _publish(
            output_root,
            runs_path=root / ARTIFACT_RUNS,
            evidence_root=root,
            records=validated["records"],
            matrix=matrix_obj,
            report=report_doc,
            fingerprint=fp,
        )
        self.assertTrue(again.existed, "byte-identical republication is an "
                                       "idempotent no-op")
        self.assertEqual(again.set_id, published.set_id)

        # ── the owner's manifest-tamper mutation: fingerprint-only
        # tampering over GENUINE artifact bytes must fail ──
        tampered = self.base / "tampered-set"
        shutil.copytree(root, tampered)
        manifest = json.loads(
            (tampered / ARTIFACT_MANIFEST).read_text(encoding="utf-8")
        )
        manifest["fingerprint"]["task_set_revision"] = "fabricated"
        (tampered / ARTIFACT_MANIFEST).write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        with self.assertRaises(EvidenceSetInvalid) as caught:
            validate_evidence_set(tampered)
        self.assertEqual(caught.exception.code, "fingerprint_mismatch")

        # an edited report (schema-valid content change) breaks its hash
        tampered2 = self.base / "tampered-report"
        shutil.copytree(root, tampered2)
        doc = json.loads(
            (tampered2 / ARTIFACT_REPORT).read_text(encoding="utf-8")
        )
        doc["arms"]["always_best"]["quality"] = 0.123
        (tampered2 / ARTIFACT_REPORT).write_text(
            json.dumps(doc, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        with self.assertRaises(EvidenceSetInvalid) as caught2:
            validate_evidence_set(tampered2)
        self.assertEqual(caught2.exception.code, "hash_mismatch")

        # sanitized diagnostics: no failure detail carries a path
        for exc in (caught.exception, caught2.exception):
            self.assertNotIn(str(self.base), str(exc))
            self.assertNotIn("/", exc.detail.replace("<path>", ""))

        # ── fault injection: a failure at ANY publication step leaves
        # no discoverable partial set, and the retry succeeds ──
        from unittest import mock as _mock

        import benchmark_runner.routing_eval.evidence_set as es

        def _retry() -> PublishedEvidenceSet:
            return _publish(
                output_root,
                runs_path=root / ARTIFACT_RUNS,
                evidence_root=root,
                records=validated["records"],
                matrix=matrix_obj,
                report=dict(report_doc),
                fingerprint=fp,
            )

        faults = (
            ("matrix write", _mock.patch.object(
                es, "matrix_dumps",
                side_effect=RuntimeError("injected: matrix"))),
            ("report write", _mock.patch.object(
                es, "write_report",
                side_effect=RuntimeError("injected: report"))),
            ("staging validation", _mock.patch.object(
                es, "validate_evidence_set",
                side_effect=RuntimeError("injected: validate"))),
        )
        for step, patch in faults:
            with self.subTest(fault=step):
                with patch:
                    with self.assertRaises(RuntimeError):
                        _retry()
                self.assertEqual(discover_evidence_sets(output_root), [root],
                                 f"partial set discoverable after {step}")
                self.assertEqual(
                    [p.name for p in output_root.iterdir()
                     if p.name.startswith(".staging-")
                     and p.name != ".staging-leftover"],
                    [], f"staging left behind after {step}",
                )
        # after every injected failure, the clean retry still succeeds
        retried = _retry()
        self.assertTrue(retried.existed)
        self.assertEqual(retried.set_id, published.set_id)


class TestPinnedBuilderLeg(_EvidenceFixture):
    def test_a_bounded_build_reconciler_cannot_steal_the_builder_leg(self) -> None:
        # The owner's round-4 counterexample: builder and reconciler
        # both tier1 with bounded-build, reconciler at BETTER selector
        # priority. Under a shared derived registry the production
        # selector would pick the reconciler as builder; under
        # stage-specific one-profile registries the pinned builder is
        # mechanically the only candidate — and the per-leg identity
        # assertion proves who executed.
        registry = self.base / "steal-registry.toml"
        registry.write_text(_ARC_REGISTRY + """
[[profiles]]
id = "t1build"
backend = "claude-code"
provider = "prov-build"
model = "m-build"
capability_tier = "tier1"
priority = 20
quota_pool = "poolB1"
roles = ["bounded-build"]
tool_profile = "local-builder-minimal"
data_policy = "approved-cloud"
credential_env = "HYBRID_KEY"
base_url_env = "HYBRID_URL"
[[profiles]]
id = "t1rev"
backend = "claude-code"
provider = "prov-rev"
model = "m-rev"
capability_tier = "tier1"
priority = 1
quota_pool = "poolR1"
roles = ["bounded-build", "reconcile"]
tool_profile = "full-cct"
data_policy = "approved-cloud"
credential_env = "HYBRID_KEY"
base_url_env = "HYBRID_URL"
""", encoding="utf-8")
        (self.sweep_mock / "t1build.spec").write_text(
            f"{self.solve_packet}|{self.cost}|0\n", encoding="utf-8"
        )
        (self.sweep_recon_mock / "t1rev.spec").write_text(
            f"-|{self.verdict}|0\n", encoding="utf-8"
        )
        declarations = _profile_declarations(registry)
        workdir = self.base / "steal-work"
        cell = run_profile_cell(
            repo_root=REPO_ROOT,
            registry_path=registry,
            declarations=declarations,
            task="bounded-fix",
            profile_id="t1build",
            trial=0,
            seed=1701,
            events=[],
            workdir=workdir,
            baseline_worktree=self.wt,
            preset_digest_value="sha256:" + "ab" * 32,
            task_set_revision="rev",
            toolchain_digest="sha256:tc",
            benchmark_id=self.bench_id,
            delegate_tasks=frozenset({"bounded-fix"}),
            reconciler_id="t1rev",
            delegate_harness_cmd=self.sweep_cmd,
            reconcile_harness_cmd=self.sweep_recon_cmd,
        )
        self.assertEqual(cell.profile_id, "t1build")
        self.assertEqual(cell.result, "pass")
        # the durable proof: the builder leg's started record names the
        # PINNED profile, not the better-priority reconciler
        started = sorted(workdir.rglob("started-1.json"))
        self.assertTrue(started)
        builder_profile = json.loads(
            started[0].read_text(encoding="utf-8"))["profile"]
        self.assertEqual(builder_profile["id"], "t1build")


class TestDerivedRegistryUnits(unittest.TestCase):
    def test_derivation_is_byte_faithful_and_validated(self) -> None:
        import tempfile

        template = (REPO_ROOT / "shared" / "templates" / "routing"
                    / "routing.toml.example")
        with tempfile.TemporaryDirectory() as tmp:
            out = derive_single_profile_registry(
                template, "local-qwen", Path(tmp) / "one.toml", tier="tier2"
            )
            text = out.read_text(encoding="utf-8")
            self.assertIn('id = "local-qwen"', text)
            self.assertNotIn("anthropic-sonnet", text)
            # the pinned block is byte-identical to the declaration
            original = template.read_text(encoding="utf-8")
            block_lines = [
                l for l in text.split("\n")
                if l and not l.startswith("[")
                and not l.startswith("schema_version")
                and l != "enabled = true"
                and not l.startswith("tier_order")
            ]
            for line in block_lines:
                self.assertIn(line, original.split("\n"), line)

    def test_an_undeclared_profile_refuses(self) -> None:
        import tempfile

        template = (REPO_ROOT / "shared" / "templates" / "routing"
                    / "routing.toml.example")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(EvidenceSetError, "not declared"):
                derive_single_profile_registry(
                    template, "ghost", Path(tmp) / "x.toml", tier="tier1"
                )


if __name__ == "__main__":
    unittest.main()
