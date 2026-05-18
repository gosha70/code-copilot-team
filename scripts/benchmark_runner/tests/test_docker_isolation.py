# tests/test_docker_isolation.py — #33 docker isolation tier.
#
# Offline-by-default: the logic paths (image-required, missing-daemon,
# local routing, no-op release) need no Docker. The real
# provision→exec→teardown path is gated behind an available Docker
# daemon (skipped otherwise) — that real run is also exercised
# out-of-band per infra-verification and recorded in the PR.

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from benchmark_runner import isolation
from benchmark_runner.contracts import IsolationConfig
from benchmark_runner.isolation import (
    ISOLATION_DOCKER,
    ISOLATION_WORKTREE,
    IsolationProvisionError,
    provision_worktree,
    release_worktree,
    run_in_worktree,
)


class TestDockerTierLogic(unittest.TestCase):
    def test_docker_tier_requires_image_fast(self) -> None:
        # No image -> immediate IsolationProvisionError, NOT a slow/hung
        # `docker run`. (Regression guard for the #32→#33 transition.)
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(IsolationProvisionError) as ctx:
                provision_worktree(
                    IsolationConfig(tier=ISOLATION_DOCKER), Path(td)
                )
        self.assertIn("image", str(ctx.exception).lower())

    def test_missing_docker_is_environment_error(self) -> None:
        with mock.patch.object(isolation.shutil, "which", return_value=None):
            with tempfile.TemporaryDirectory() as td:
                with self.assertRaises(IsolationProvisionError) as ctx:
                    provision_worktree(
                        IsolationConfig(
                            tier=ISOLATION_DOCKER, image="alpine:3"
                        ),
                        Path(td),
                    )
        self.assertIn("ENVIRONMENT PREREQUISITE", str(ctx.exception))

    def test_run_in_worktree_local_when_not_registered(self) -> None:
        # An unregistered (non-docker) worktree routes to a local
        # subprocess.
        with tempfile.TemporaryDirectory() as td:
            wt = Path(td)
            proc = run_in_worktree(
                wt, ["python3", "-c", "print('hi-local')"], timeout=30
            )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("hi-local", proc.stdout)

    def test_release_worktree_noop_and_idempotent_for_non_docker(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            wt = Path(td)
            # Must not raise, and a double-call is safe.
            release_worktree(IsolationConfig(tier=ISOLATION_WORKTREE), wt)
            release_worktree(ISOLATION_WORKTREE, wt)  # legacy str form
            release_worktree(IsolationConfig(tier=ISOLATION_WORKTREE), wt)


@unittest.skipUnless(
    shutil.which("docker") is not None,
    "docker not on PATH; real docker-tier path is local-only "
    "(also exercised out-of-band per infra-verification)",
)
class TestDockerTierReal(unittest.TestCase):
    def test_provision_exec_release_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = IsolationConfig(tier=ISOLATION_DOCKER, image="alpine:3")
            try:
                wt = provision_worktree(cfg, Path(td))
            except IsolationProvisionError as exc:
                # Daemon down / image pull blocked = environment, not a
                # bug: skip rather than fail.
                self.skipTest(f"docker environment unavailable: {exc}")
            try:
                proc = run_in_worktree(
                    wt, ["sh", "-c", "echo in-container-ok"], timeout=60
                )
                self.assertEqual(proc.returncode, 0)
                self.assertIn("in-container-ok", proc.stdout)
            finally:
                release_worktree(cfg, wt)
            # Idempotent + deregistered.
            release_worktree(cfg, wt)


if __name__ == "__main__":
    unittest.main()
