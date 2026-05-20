# tests/test_judge_registry.py — judge registry contract tests.
#
# Mirrors test_contracts.py / test_cli_skeleton.py style: small,
# behaviour-focused, no live LLM. The registry itself is a small
# in-memory dispatch table; these tests cover the public contract
# (register / list / get / unknown) plus the canonical-vs-alias
# pattern that lets ``claude-code`` and ``claude-code-judge``
# share the same factory.

from __future__ import annotations

import unittest

from benchmark_runner._register import register_all, unregister_all_for_tests
from benchmark_runner.judge.claude_code_judge import (
    ClaudeCodeJudge,
    JUDGE_FAMILY as CLAUDE_CODE_JUDGE_FAMILY,
)
from benchmark_runner.judge.contracts import Judge
from benchmark_runner.judge.registry import (
    UnknownJudgeError,
    _reset_for_tests,
    get_judge,
    list_judge_ids,
    register_judge,
)


# ── Pure registry behaviour ───────────────────────────────────────────


class TestRegisterListGet(unittest.TestCase):
    def setUp(self) -> None:
        _reset_for_tests()

    def tearDown(self) -> None:
        _reset_for_tests()

    def test_empty_registry_lists_nothing(self) -> None:
        self.assertEqual(list_judge_ids(), [])

    def test_register_makes_family_resolvable(self) -> None:
        register_judge("family-x", lambda m: _StubJudge("family-x", m))
        self.assertIn("family-x", list_judge_ids())
        j = get_judge("family-x", "model-1")
        self.assertIsInstance(j, _StubJudge)
        self.assertEqual(j.model, "model-1")

    def test_get_with_default_model_passes_empty_string(self) -> None:
        # Mirrors the backend registry contract: stub-shaped factories
        # take ``model=""`` by default.
        register_judge("family-x", lambda m: _StubJudge("family-x", m))
        j = get_judge("family-x")
        self.assertEqual(j.model, "")

    def test_unknown_family_raises_with_known_listed(self) -> None:
        register_judge("a", lambda m: _StubJudge("a", m))
        register_judge("b", lambda m: _StubJudge("b", m))
        with self.assertRaises(UnknownJudgeError) as ctx:
            get_judge("not-registered", "")
        msg = str(ctx.exception)
        self.assertIn("not-registered", msg)
        # Every registered family appears in the error message so the
        # user sees what they could have typed.
        self.assertIn("a", msg)
        self.assertIn("b", msg)

    def test_unknown_family_when_empty_registry(self) -> None:
        with self.assertRaisesRegex(UnknownJudgeError, "\\(none\\)"):
            get_judge("any", "")


class TestRegistryDeterminism(unittest.TestCase):
    """list_judge_ids() must be deterministic (sorted) so callers
    like ``benchmark list`` produce identical output across machines."""

    def setUp(self) -> None:
        _reset_for_tests()

    def tearDown(self) -> None:
        _reset_for_tests()

    def test_list_judge_ids_is_sorted(self) -> None:
        # Register in non-alphabetical order; expect sorted output.
        for name in ("zebra", "alpha", "mid"):
            register_judge(name, lambda m, _n=name: _StubJudge(_n, m))
        self.assertEqual(list_judge_ids(), ["alpha", "mid", "zebra"])

    def test_list_judge_ids_stable_across_calls(self) -> None:
        for name in ("c", "a", "b"):
            register_judge(name, lambda m, _n=name: _StubJudge(_n, m))
        self.assertEqual(list_judge_ids(), list_judge_ids())


class TestAliasPattern(unittest.TestCase):
    """The canonical-vs-alias contract: ``claude-code`` and
    ``claude-code-judge`` share one factory and behave identically."""

    def setUp(self) -> None:
        _reset_for_tests()

    def tearDown(self) -> None:
        _reset_for_tests()

    def test_shared_factory_under_two_tokens_allowed(self) -> None:
        factory = lambda m: _StubJudge("shared", m)
        register_judge("canonical", factory)
        register_judge("alias", factory)  # same factory object — OK
        self.assertEqual(list_judge_ids(), ["alias", "canonical"])
        a = get_judge("canonical", "m")
        b = get_judge("alias", "m")
        # Both resolve via the same factory, so they produce
        # instances with the same internal state shape.
        self.assertEqual(a.family, b.family)

    def test_different_factories_under_same_token_raises(self) -> None:
        f1 = lambda m: _StubJudge("f1", m)
        f2 = lambda m: _StubJudge("f2", m)
        register_judge("canonical", f1)
        with self.assertRaisesRegex(RuntimeError, "already registered"):
            register_judge("canonical", f2)

    def test_idempotent_re_register_same_factory(self) -> None:
        # Calling register_all() twice (the test harness commonly
        # does this between cases) MUST be a no-op for the registry
        # rather than a duplicate-registration error.
        factory = lambda m: _StubJudge("idempotent", m)
        register_judge("canonical", factory)
        register_judge("canonical", factory)  # exact same factory object — no-op
        self.assertEqual(list_judge_ids(), ["canonical"])


# ── Integration with _register.register_all ───────────────────────────


class TestShippedJudgeRegistration(unittest.TestCase):
    """Verifies that ``register_all()`` registers the shipped judges
    under the documented family tokens. This is the contract the
    CLI's ``benchmark list`` and ``benchmark judge`` depend on."""

    def setUp(self) -> None:
        unregister_all_for_tests()

    def tearDown(self) -> None:
        unregister_all_for_tests()

    def test_register_all_registers_both_claude_code_tokens(self) -> None:
        register_all()
        ids = list_judge_ids()
        self.assertIn("claude-code", ids)
        self.assertIn("claude-code-judge", ids)

    def test_expected_ids_match_documented_set(self) -> None:
        # The full set of shipped judge tokens — pin it so a future
        # contributor who adds/removes a judge has to update this
        # test deliberately.
        register_all()
        self.assertEqual(
            list_judge_ids(),
            ["claude-code", "claude-code-judge"],
        )

    def test_both_tokens_resolve_to_a_claude_code_judge(self) -> None:
        register_all()
        a = get_judge("claude-code", "sonnet")
        b = get_judge("claude-code-judge", "sonnet")
        self.assertIsInstance(a, ClaudeCodeJudge)
        self.assertIsInstance(b, ClaudeCodeJudge)
        # The internal judge_id is the SDD-canonical value (not the
        # token the user typed) — that's the value recorded in
        # judge.json.
        self.assertEqual(a.judge_id, CLAUDE_CODE_JUDGE_FAMILY)
        self.assertEqual(b.judge_id, CLAUDE_CODE_JUDGE_FAMILY)

    def test_resolved_judge_satisfies_judge_protocol(self) -> None:
        register_all()
        self.assertIsInstance(get_judge("claude-code", "sonnet"), Judge)

    def test_register_all_is_idempotent(self) -> None:
        # The test harness sometimes calls register_all() more than
        # once per process (e.g. across unrelated CLI invocations).
        # MUST NOT raise on the second call.
        register_all()
        register_all()
        self.assertEqual(
            list_judge_ids(),
            ["claude-code", "claude-code-judge"],
        )


# ── Stub Judge for the unit tests ────────────────────────────────────


class _StubJudge:
    def __init__(self, family: str, model: str) -> None:
        self.family = family
        self.model = model

    @property
    def judge_id(self) -> str:
        return f"stub-{self.family}"

    def rate(self, attempt):  # type: ignore[no-untyped-def]
        raise NotImplementedError("stub — not exercised in registry tests")


if __name__ == "__main__":
    unittest.main()
