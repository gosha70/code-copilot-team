# Tests for #285 T1 — embedding contract, registry, config, envelope
# validation. No composer, no runner, no wire code: those are T2–T4.
#
# The FR-9 validation tests are DISCRIMINATORS, one per refusal reason:
# each asserts on the reason text, so a validator collapsed into a
# single "shape is wrong" check fails here rather than passing by
# accident of a neighbouring rule.

from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from session_analytics import config as cfgmod
from session_analytics.embedding import _register, ollama_embed
from session_analytics.embedding.contracts import (
    ENVELOPE_SCHEMA_VERSION,
    EmbeddingBackend,
    EmbeddingResult,
    build_envelope,
    validate_envelope,
)
from session_analytics.embedding.registry import (
    UnknownEmbeddingError,
    _reset_for_tests,
    get_embedding,
    list_embedding_ids,
    register_embedding,
)


def _valid_envelope(**overrides):
    env = build_envelope(
        EmbeddingResult(vector=(0.1, -0.2, 0.3), resolved_model="nomic-embed-text"),
        provider="ollama",
        embedded_at="2026-09-02T18:00:00+00:00",
    )
    env.update(overrides)
    return env


class TestEnvelopeValidation(unittest.TestCase):
    def test_valid_nonzero_vector_accepted(self) -> None:
        self.assertIsNone(validate_envelope(_valid_envelope()))

    def test_build_envelope_is_valid_by_construction(self) -> None:
        env = _valid_envelope()
        self.assertEqual(env["schema_version"], ENVELOPE_SCHEMA_VERSION)
        self.assertEqual(env["dim"], 3)

    # ── each FR-9 refusal, for its OWN reason ────────────────────────
    def test_empty_vector_refused(self) -> None:
        err = validate_envelope(_valid_envelope(vector=[], dim=3))
        self.assertIn("empty vector", err)

    def test_zero_vector_refused(self) -> None:
        err = validate_envelope(_valid_envelope(vector=[0.0, 0.0, 0.0]))
        self.assertIn("zero vector", err)

    def test_nan_refused(self) -> None:
        err = validate_envelope(_valid_envelope(vector=[0.1, math.nan, 0.3]))
        self.assertIn("not finite", err)

    def test_inf_refused(self) -> None:
        err = validate_envelope(_valid_envelope(vector=[0.1, math.inf, 0.3]))
        self.assertIn("not finite", err)

    def test_boolean_element_refused(self) -> None:
        # bool is an int subclass — must be refused BEFORE the numeric
        # checks accept it.
        err = validate_envelope(_valid_envelope(vector=[0.1, True, 0.3]))
        self.assertIn("boolean", err)

    def test_dim_mismatch_refused(self) -> None:
        err = validate_envelope(_valid_envelope(dim=7))
        self.assertIn("does not match vector length", err)

    def test_nonpositive_dim_refused(self) -> None:
        err = validate_envelope(_valid_envelope(dim=0, vector=[0.1]))
        self.assertIn("not a positive integer", err)

    def test_boolean_dim_refused(self) -> None:
        err = validate_envelope(_valid_envelope(dim=True, vector=[0.1]))
        self.assertIn("not a positive integer", err)

    def test_empty_model_refused(self) -> None:
        err = validate_envelope(_valid_envelope(model=""))
        self.assertIn("model is empty", err)
        self.assertIn("unattributed", err)  # the reason names the rule

    def test_empty_provider_refused(self) -> None:
        err = validate_envelope(_valid_envelope(provider=""))
        self.assertIn("provider is empty", err)

    def test_wrong_schema_version_refused(self) -> None:
        err = validate_envelope(_valid_envelope(schema_version=2))
        self.assertIn("schema_version", err)
        self.assertIn("refused", err)  # unknown version never best-effort

    def test_missing_schema_version_refused(self) -> None:
        env = _valid_envelope()
        del env["schema_version"]
        self.assertIn("missing fields", validate_envelope(env))

    def test_bad_timestamp_refused(self) -> None:
        err = validate_envelope(_valid_envelope(embedded_at="yesterday-ish"))
        self.assertIn("ISO-8601", err)

    def test_refusal_reasons_are_pairwise_distinct(self) -> None:
        # Four different lies, four different reasons — a collapsed
        # validator cannot satisfy this.
        reasons = {
            validate_envelope(_valid_envelope(vector=[], dim=3)),
            validate_envelope(_valid_envelope(vector=[0.0, 0.0, 0.0])),
            validate_envelope(_valid_envelope(model="")),
            validate_envelope(_valid_envelope(dim=7)),
        }
        self.assertEqual(len(reasons), 4)


class TestRegistry(unittest.TestCase):
    def setUp(self) -> None:
        _reset_for_tests()
        self.addCleanup(_reset_for_tests)

    def test_register_all_resolves_ollama(self) -> None:
        _register.register_all_embeddings()
        self.assertEqual(list_embedding_ids(), ["ollama"])
        backend = get_embedding("ollama", "some-model")
        self.assertIsInstance(backend, EmbeddingBackend)

    def test_duplicate_registration_refused(self) -> None:
        _register.register_all_embeddings()
        with self.assertRaises(RuntimeError):
            register_embedding("ollama", ollama_embed.factory)

    def test_unknown_family_names_the_known_set(self) -> None:
        _register.register_all_embeddings()
        with self.assertRaises(UnknownEmbeddingError) as ctx:
            get_embedding("no-such-backend")
        self.assertIn("ollama", str(ctx.exception))

    def test_t1_stub_refuses_with_the_t3_contract_named(self) -> None:
        # T1 ships NO wire code: both methods refuse, and the refusal
        # names the recorded-capture contract rather than looking like
        # an outage. This test is DELETED by T3, which replaces it with
        # capture-derived behaviour.
        _register.register_all_embeddings()
        backend = get_embedding("ollama")
        for call in (backend.probe, lambda: backend.embed("x")):
            with self.assertRaises(NotImplementedError) as ctx:
                call()
            self.assertIn("verification-ollama-embed", str(ctx.exception))


class TestEmbeddingConfig(unittest.TestCase):
    """FR-8: the loader's FULL precedence, hermetically.

    The real ~/.cct/session-analytics.json and repo .env are patched
    out so the developer's machine cannot leak into assertions.
    """

    def _load(self, *, user_json=None, environ=None):
        tmp = Path(tempfile.mkdtemp())
        user_path = tmp / "session-analytics.json"
        if user_json is not None:
            user_path.write_text(json.dumps(user_json), encoding="utf-8")
        with mock.patch.object(cfgmod, "_USER_CONFIG", user_path), \
             mock.patch.object(cfgmod, "parse_env_file", lambda *a, **k: {}), \
             mock.patch.dict("os.environ", environ or {}, clear=False):
            return cfgmod.load_config()

    def test_defaults_layer(self) -> None:
        e = self._load().embedding
        self.assertEqual(
            (e.backend, e.model, e.input_cap_chars, e.workers),
            ("ollama", "", 8000, 1),
        )
        self.assertEqual(e.ollama_url, "http://localhost:11434")

    def test_user_json_layer_overrides_defaults(self) -> None:
        # The layer the first SDD draft dropped — pinned on its own.
        e = self._load(
            user_json={"embedding": {"model": "from-user-json", "input_cap_chars": 1234}}
        ).embedding
        self.assertEqual(e.model, "from-user-json")
        self.assertEqual(e.input_cap_chars, 1234)
        self.assertEqual(e.backend, "ollama")  # unset keys keep defaults

    def test_real_env_overrides_user_json(self) -> None:
        e = self._load(
            user_json={"embedding": {"model": "from-user-json"}},
            environ={cfgmod.ENV_EMBED_MODEL: "from-env"},
        ).embedding
        self.assertEqual(e.model, "from-env")

    def test_env_backend_and_cap_override(self) -> None:
        e = self._load(
            environ={
                cfgmod.ENV_EMBED_BACKEND: "other",
                cfgmod.ENV_EMBED_INPUT_CAP: "4321",
            }
        ).embedding
        self.assertEqual(e.backend, "other")
        self.assertEqual(e.input_cap_chars, 4321)

    def test_no_hardcoded_default_in_new_source(self) -> None:
        # The embedding modules define no literal fallback values of
        # their own — config carries them. (config.py's resolution-line
        # fallbacks mirror the judge's existing idiom and are the
        # loader's job, not the modules'.)
        pkg = Path(cfgmod.__file__).parent / "embedding"
        for py in pkg.glob("*.py"):
            text = py.read_text(encoding="utf-8")
            self.assertNotIn("11434", text, f"hardcoded port in {py.name}")
            self.assertNotIn("8000", text, f"hardcoded cap in {py.name}")


if __name__ == "__main__":
    unittest.main()
