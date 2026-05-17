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

    def test_install_command_runs_as_non_login_shell(self) -> None:
        # Regression: `bash -lc` on macOS triggers /etc/profile →
        # /usr/libexec/path_helper, which rebuilds PATH from
        # /etc/paths{,.d/*} and clobbers the venv-prepended PATH that
        # _run_install_command just constructed. Symptom in the field:
        # `pip` resolves to /usr/local/bin/pip (often a broken
        # Python-2.7-shebanged shim on developer Macs) instead of the
        # venv's own pip, and install_command exits 126.
        #
        # The fix is to invoke `bash -c` (non-login). This test asserts
        # the shell is non-login regardless of what any login profile
        # might do on this host — it's the lever, not a downstream
        # observable.
        from benchmark_runner.isolation import install_dependencies

        with tempfile.TemporaryDirectory() as td:
            wt = provision_worktree(
                IsolationConfig(tier=ISOLATION_WORKTREE_VENV, python="python3"),
                Path(td),
            )
            trace = wt / "shell-mode.txt"
            # `$-` contains the flags the shell was invoked with;
            # `l` is present for login shells. Always exits 0, so
            # install_dependencies doesn't raise on shopt's quirky
            # rc=1-when-unset behaviour.
            install_dependencies(
                IsolationConfig(
                    tier=ISOLATION_WORKTREE_VENV,
                    python="python3",
                    install_command=(
                        f'case "$-" in *l*) echo login > {trace};; '
                        f'*) echo non-login > {trace};; esac'
                    ),
                ),
                wt,
            )
            content = trace.read_text(encoding="utf-8").strip()
            self.assertEqual(
                content, "non-login",
                "install_command must run as non-login shell to keep "
                "explicit PATH precedence (see _run_install_command's "
                "IMPORTANT note in isolation.py).",
            )

    def test_install_command_resolves_venv_binaries_first(self) -> None:
        # Regression: the venv's bin/ must be the FIRST entry in PATH
        # as seen by install_command, so `pip`, `pytest`, etc. resolve
        # to the venv's copies instead of any host-side equivalents.
        # If a future change re-introduces a login-shell PATH rebuild
        # or otherwise reorders PATH, this test catches it.
        from benchmark_runner.isolation import install_dependencies

        with tempfile.TemporaryDirectory() as td:
            wt = provision_worktree(
                IsolationConfig(tier=ISOLATION_WORKTREE_VENV, python="python3"),
                Path(td),
            )
            path_trace = wt / "path-trace.txt"
            install_dependencies(
                IsolationConfig(
                    tier=ISOLATION_WORKTREE_VENV,
                    python="python3",
                    install_command=f'printf "%s" "$PATH" > {path_trace}',
                ),
                wt,
            )
            path_seen = path_trace.read_text(encoding="utf-8")
            first_entry = path_seen.split(":", 1)[0]
            self.assertEqual(
                Path(first_entry).resolve(),
                (wt / ".venv" / "bin").resolve(),
                f"venv bin/ must be first on PATH inside install_command. "
                f"Got first={first_entry!r}; full PATH={path_seen!r}",
            )

    def test_verify_imports_raises_when_module_absent(self) -> None:
        # Regression: pip can exit 0 without actually installing the
        # requested packages (transient network failure + `-q` masks
        # the warning, pip's internal retry-then-give-up silently
        # returns success). Discovered on 2026-05-15 — 5 of 6 Polyglot
        # attempts produced venvs with only `pip` in site-packages.
        # The fix is verify_imports: declare modules that MUST be
        # importable post-install; harness fails loud when they're not.
        from benchmark_runner.isolation import install_dependencies

        with tempfile.TemporaryDirectory() as td:
            wt = provision_worktree(
                IsolationConfig(tier=ISOLATION_WORKTREE_VENV, python="python3"),
                Path(td),
            )
            # install_command exits 0 (literally /bin/true) but installs
            # nothing. verify_imports must catch the mismatch.
            with self.assertRaises(Exception) as ctx:
                install_dependencies(
                    IsolationConfig(
                        tier=ISOLATION_WORKTREE_VENV,
                        python="python3",
                        install_command="true",  # no-op shell builtin
                        verify_imports=("pytest",),
                    ),
                    wt,
                )
            msg = str(ctx.exception)
            self.assertIn("pytest", msg)
            self.assertIn("not importable", msg)

    def test_verify_imports_passes_when_module_present(self) -> None:
        # Positive case: a module that ships with the stdlib is always
        # importable, so verify_imports=("json",) plus a no-op
        # install_command should succeed.
        from benchmark_runner.isolation import install_dependencies

        with tempfile.TemporaryDirectory() as td:
            wt = provision_worktree(
                IsolationConfig(tier=ISOLATION_WORKTREE_VENV, python="python3"),
                Path(td),
            )
            install_dependencies(
                IsolationConfig(
                    tier=ISOLATION_WORKTREE_VENV,
                    python="python3",
                    install_command="true",
                    verify_imports=("json",),  # stdlib, always present
                ),
                wt,
            )
            # No exception = pass.

    def test_verify_imports_rejects_invalid_module_name(self) -> None:
        # Defence-in-depth regression: verify_imports entries are
        # user-supplied (via the adapter), so even though they're
        # passed to subprocess as argv (not interpolated into source),
        # we validate them as dotted-identifier strings before
        # invoking python. An adapter that returned a derived value
        # (config-driven, dataset-driven, malicious) MUST NOT be
        # able to smuggle code through this surface.
        from benchmark_runner.isolation import (
            IsolationProvisionError,
            install_dependencies,
        )

        with tempfile.TemporaryDirectory() as td:
            wt = provision_worktree(
                IsolationConfig(tier=ISOLATION_WORKTREE_VENV, python="python3"),
                Path(td),
            )
            # Classic injection shape: would have been concatenated
            # into `import <X>` source before the data-not-code fix.
            with self.assertRaises(IsolationProvisionError) as ctx:
                install_dependencies(
                    IsolationConfig(
                        tier=ISOLATION_WORKTREE_VENV,
                        python="python3",
                        install_command="true",
                        verify_imports=("os'); __import__('os').system('echo PWNED",),
                    ),
                    wt,
                )
            self.assertIn("not a valid Python module name", str(ctx.exception))
            self.assertIn("Refusing to invoke subprocess", str(ctx.exception))

        # Other invalid shapes that must also be rejected.
        for bad_name in ("", "1abc", "abc-def", "abc def", "abc;def", "..pytest"):
            with tempfile.TemporaryDirectory() as td2:
                wt2 = provision_worktree(
                    IsolationConfig(tier=ISOLATION_WORKTREE_VENV, python="python3"),
                    Path(td2),
                )
                with self.assertRaises(IsolationProvisionError) as ctx:
                    install_dependencies(
                        IsolationConfig(
                            tier=ISOLATION_WORKTREE_VENV,
                            python="python3",
                            install_command="true",
                            verify_imports=(bad_name,),
                        ),
                        wt2,
                    )
                self.assertIn(
                    "not a valid Python module name", str(ctx.exception),
                    f"expected rejection for {bad_name!r}",
                )

    def test_verify_imports_accepts_dotted_submodule(self) -> None:
        # Positive case for the valid-name allowlist: dotted submodule
        # paths (e.g. ``numpy.linalg``) must be accepted, since real
        # adapters may want to verify a submodule rather than just the
        # top-level package.
        from benchmark_runner.isolation import install_dependencies

        with tempfile.TemporaryDirectory() as td:
            wt = provision_worktree(
                IsolationConfig(tier=ISOLATION_WORKTREE_VENV, python="python3"),
                Path(td),
            )
            install_dependencies(
                IsolationConfig(
                    tier=ISOLATION_WORKTREE_VENV,
                    python="python3",
                    install_command="true",
                    verify_imports=("json.decoder",),  # stdlib dotted name
                ),
                wt,
            )

    def test_verify_imports_empty_is_no_op(self) -> None:
        # Default verify_imports=() must not run the import check —
        # adapters that don't declare it should see exactly the
        # pre-fix behaviour.
        from benchmark_runner.isolation import install_dependencies

        with tempfile.TemporaryDirectory() as td:
            wt = provision_worktree(
                IsolationConfig(tier=ISOLATION_WORKTREE_VENV, python="python3"),
                Path(td),
            )
            install_dependencies(
                IsolationConfig(
                    tier=ISOLATION_WORKTREE_VENV,
                    python="python3",
                    install_command="true",
                    # No verify_imports → no import check.
                ),
                wt,
            )

    def test_install_command_uses_venv_pip_under_relative_worktree(self) -> None:
        # Reviewer-flagged regression (Bug #5, 2026-05-16): the
        # orchestration layer passes worktree as a relative path
        # (runs_root defaults to Path("runs")), and subprocess.run
        # with cwd=worktree re-relativizes the PATH entries we
        # prepended — so bash's `pip` lookup fails on the venv entry
        # and falls through to the system pip (which on this user's
        # Mac found pytest "already satisfied" in
        # ~/Library/Python/3.11/site-packages, exited 0, leaving the
        # venv with only pip+pip.dist-info). Symptom: `verify_imports`
        # raises "exited 0 but X is not importable" after a smoke run
        # that should have installed pytest.
        #
        # Fix: absolutize the venv bin path before injecting into
        # PATH. This test exercises that fix by cd'ing into a tempdir
        # and passing a relative attempt_dir to provision_worktree
        # (mirroring how run.py constructs paths).
        from benchmark_runner.isolation import install_dependencies

        with tempfile.TemporaryDirectory() as td:
            original_cwd = os.getcwd()
            try:
                os.chdir(td)
                # Build a relative attempt_dir, same shape as run.py
                # produces with the default runs_root=Path("runs").
                rel_attempt = Path("runs-rel/attempt-01")
                rel_attempt.mkdir(parents=True)
                wt = provision_worktree(
                    IsolationConfig(tier=ISOLATION_WORKTREE_VENV, python="python3"),
                    rel_attempt,
                )
                self.assertFalse(
                    Path(wt).is_absolute(),
                    "test precondition: worktree must be relative to exercise the bug",
                )
                # `install_command` records which `pip` actually got
                # picked up by bash's PATH lookup inside the harness's
                # subprocess. We capture it before pip would have a
                # chance to silently no-op.
                install_dependencies(
                    IsolationConfig(
                        tier=ISOLATION_WORKTREE_VENV,
                        python="python3",
                        install_command="command -v pip > pip-resolution.txt",
                    ),
                    wt,
                )
                resolved_pip = (wt / "pip-resolution.txt").read_text(encoding="utf-8").strip()
                expected_venv_bin = (wt / ".venv" / "bin").absolute()
                self.assertEqual(
                    str(Path(resolved_pip).parent.resolve()),
                    str(expected_venv_bin.resolve()),
                    f"install_command's `pip` must resolve to the venv's "
                    f"bin ({expected_venv_bin}); got {resolved_pip!r}. "
                    f"If this fails, subprocess re-relativization is back "
                    f"and pip installs would silently no-op into the "
                    f"system Python.",
                )
            finally:
                os.chdir(original_cwd)

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
