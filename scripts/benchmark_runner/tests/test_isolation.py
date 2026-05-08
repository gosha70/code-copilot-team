# tests/test_isolation.py — isolation tier provisioning.

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from benchmark_runner.contracts import (
    ISOLATION_DOCKER,
    ISOLATION_WORKTREE,
    ISOLATION_WORKTREE_VENV,
    IsolationConfig,
)
from benchmark_runner.isolation import (
    IsolationProvisionError,
    is_known_tier,
    known_tiers,
    provision_worktree,
)


_REAL_VENV = os.environ.get("CCT_BENCHMARK_INTEGRATION") == "1"


class TestKnownTiers(unittest.TestCase):
    def test_three_tiers_advertised(self) -> None:
        self.assertEqual(
            sorted(known_tiers()),
            sorted([ISOLATION_WORKTREE, ISOLATION_WORKTREE_VENV, ISOLATION_DOCKER]),
        )

    def test_is_known_tier(self) -> None:
        self.assertTrue(is_known_tier(ISOLATION_WORKTREE))
        self.assertFalse(is_known_tier("nonsense"))


class TestProvisionWorktree(unittest.TestCase):
    def test_plain_worktree_creates_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            wt = provision_worktree(IsolationConfig(tier=ISOLATION_WORKTREE), Path(td))
            self.assertTrue(wt.is_dir())
            self.assertEqual(wt.name, "worktree")

    def test_unknown_tier_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                provision_worktree(IsolationConfig(tier="nope"), Path(td))  # type: ignore[arg-type]

    def test_docker_not_implemented(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(NotImplementedError):
                provision_worktree(IsolationConfig(tier=ISOLATION_DOCKER), Path(td))

    def test_legacy_string_tier_accepted(self) -> None:
        # Backwards-compat: callers that pass a bare tier string get
        # the same behavior as IsolationConfig(tier=...).
        with tempfile.TemporaryDirectory() as td:
            wt = provision_worktree(ISOLATION_WORKTREE, Path(td))  # type: ignore[arg-type]
            self.assertTrue(wt.is_dir())


class TestVenvTier(unittest.TestCase):
    def test_venv_created_inside_worktree(self) -> None:
        # provision_worktree creates the dir and the venv but does NOT
        # execute install_command (regressed by test_provision_does_not_
        # run_install_command below).
        with tempfile.TemporaryDirectory() as td:
            config = IsolationConfig(
                tier=ISOLATION_WORKTREE_VENV,
                python="python3",
            )
            wt = provision_worktree(config, Path(td))
            self.assertTrue(wt.is_dir())
            self.assertTrue((wt / ".venv" / "bin" / "python").exists())

    def test_install_command_failure_raises(self) -> None:
        # The failure surfaces from install_dependencies (the new step
        # called by run.py after prepare_task), not provision_worktree.
        from benchmark_runner.isolation import install_dependencies

        with tempfile.TemporaryDirectory() as td:
            config = IsolationConfig(
                tier=ISOLATION_WORKTREE_VENV,
                python="python3",
                install_command="exit 7",
            )
            wt = provision_worktree(config, Path(td))
            with self.assertRaises(IsolationProvisionError):
                install_dependencies(config, wt)

    def test_missing_python_executable_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            config = IsolationConfig(
                tier=ISOLATION_WORKTREE_VENV,
                python="python-that-does-not-exist-9999",
            )
            with self.assertRaises(IsolationProvisionError):
                provision_worktree(config, Path(td))

    def test_provision_does_not_run_install_command(self) -> None:
        # Regression: provision_worktree must NOT execute the install
        # command — that step lives in install_dependencies, called
        # AFTER adapter.prepare_task so project-aware installs (e.g.
        # ``pip install -e .[dev]``) can see the task's pyproject.toml.
        with tempfile.TemporaryDirectory() as td:
            sentinel = Path(td) / "install-ran"
            config = IsolationConfig(
                tier=ISOLATION_WORKTREE_VENV,
                python="python3",
                # If provision_worktree runs install_command, this file
                # gets created — the assertion below catches the bug.
                install_command=f"touch {sentinel}",
            )
            provision_worktree(config, Path(td))
            self.assertFalse(
                sentinel.exists(),
                "provision_worktree must not run install_command "
                "(should land in install_dependencies after prepare_task)",
            )

    def test_install_dependencies_runs_after_task_files_present(self) -> None:
        # Regression: install_command must run AFTER prepare_task so
        # commands like 'pip install -e .[dev]' or 'pip install -r
        # requirements.txt' can find their input files.
        from benchmark_runner.isolation import install_dependencies

        with tempfile.TemporaryDirectory() as td:
            config = IsolationConfig(
                tier=ISOLATION_WORKTREE_VENV,
                python="python3",
            )
            wt = provision_worktree(config, Path(td))

            # Simulate adapter.prepare_task placing a task-local file:
            (wt / "marker.txt").write_text("task-supplied", encoding="utf-8")

            # install_command can now reference the prepared file:
            config_with_install = IsolationConfig(
                tier=ISOLATION_WORKTREE_VENV,
                python="python3",
                install_command="test -f marker.txt && touch install-ran",
            )
            install_dependencies(config_with_install, wt)
            self.assertTrue(
                (wt / "install-ran").exists(),
                "install_command should have seen marker.txt placed by prepare_task",
            )

    def test_install_dependencies_noop_for_plain_worktree(self) -> None:
        from benchmark_runner.isolation import install_dependencies

        with tempfile.TemporaryDirectory() as td:
            wt = provision_worktree(IsolationConfig(tier=ISOLATION_WORKTREE), Path(td))
            # No-op — should not raise even with an install_command
            # set on a plain worktree (which is illegal config but must
            # fail closed at the config-construction layer, not here).
            install_dependencies(
                IsolationConfig(
                    tier=ISOLATION_WORKTREE, install_command="exit 1"
                ),
                wt,
            )

    @unittest.skipUnless(
        _REAL_VENV,
        "set CCT_BENCHMARK_INTEGRATION=1 to run the real-pip install path",
    )
    def test_real_pip_install_pytest(self) -> None:
        # Integration: actually creates a venv and installs pytest.
        # Skipped by default to keep the suite hermetic.
        from benchmark_runner.isolation import install_dependencies

        with tempfile.TemporaryDirectory() as td:
            config = IsolationConfig(
                tier=ISOLATION_WORKTREE_VENV,
                python="python3",
                install_command="pip install -q pytest",
            )
            wt = provision_worktree(config, Path(td))
            install_dependencies(config, wt)
            pytest_exe = wt / ".venv" / "bin" / "pytest"
            self.assertTrue(
                pytest_exe.exists(),
                f"pytest should be installed in the venv at {pytest_exe}",
            )


if __name__ == "__main__":
    unittest.main()
