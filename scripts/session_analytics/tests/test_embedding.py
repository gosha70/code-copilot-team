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
import os
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
    """FR-8: the loader's FULL five-layer precedence, hermetically.

    Hermeticity: the real ~/.cct/session-analytics.json is patched to a
    temp path, the repo .env is replaced by an explicit dict, and every
    real CCT_SA_* variable is REMOVED from the environment before each
    test injects only what it intends — so the developer's machine
    cannot leak into any assertion.
    """

    def _load(self, *, user_json=None, dotenv=None, environ=None, cli=None):
        tmp = Path(tempfile.mkdtemp())
        user_path = tmp / "session-analytics.json"
        if user_json is not None:
            user_path.write_text(json.dumps(user_json), encoding="utf-8")
        base = {k: v for k, v in os.environ.items() if not k.startswith("CCT_SA_")}
        base.update(environ or {})
        with mock.patch.object(cfgmod, "_USER_CONFIG", user_path), \
             mock.patch.object(cfgmod, "parse_env_file",
                               lambda *a, **k: dict(dotenv or {})), \
             mock.patch.dict("os.environ", base, clear=True):
            return cfgmod.load_config(
                extra_overrides={"embedding": cli} if cli is not None else None
            )

    def test_defaults_layer(self) -> None:
        e = self._load().embedding
        self.assertEqual(
            (e.backend, e.model, e.input_cap_chars, e.workers),
            ("ollama", "", 8000, 1),
        )
        self.assertEqual(e.ollama_url, "http://localhost:11434")

    # ── the full five-layer ladder, per the review's discriminators ──
    def test_all_five_layers_cli_wins(self) -> None:
        e = self._load(
            user_json={"embedding": {"model": "B"}},
            dotenv={cfgmod.ENV_EMBED_MODEL: "C"},
            environ={cfgmod.ENV_EMBED_MODEL: "D"},
            cli={"model": "E"},
        ).embedding
        self.assertEqual(e.model, "E")

    def test_without_cli_real_env_wins(self) -> None:
        e = self._load(
            user_json={"embedding": {"model": "B"}},
            dotenv={cfgmod.ENV_EMBED_MODEL: "C"},
            environ={cfgmod.ENV_EMBED_MODEL: "D"},
        ).embedding
        self.assertEqual(e.model, "D")

    def test_without_env_dotenv_wins(self) -> None:
        e = self._load(
            user_json={"embedding": {"model": "B"}},
            dotenv={cfgmod.ENV_EMBED_MODEL: "C"},
        ).embedding
        self.assertEqual(e.model, "C")

    def test_without_dotenv_user_json_wins(self) -> None:
        e = self._load(user_json={"embedding": {"model": "B"}}).embedding
        self.assertEqual(e.model, "B")

    def test_cli_empty_model_is_a_value_not_an_absence(self) -> None:
        # "" means 'the backend default model' — presence, not
        # truthiness, decides whether a layer spoke.
        e = self._load(
            environ={cfgmod.ENV_EMBED_MODEL: "D"},
            cli={"model": ""},
        ).embedding
        self.assertEqual(e.model, "")

    def test_unset_keys_keep_lower_layers(self) -> None:
        e = self._load(
            user_json={"embedding": {"input_cap_chars": 1234}},
            cli={"model": "E"},
        ).embedding
        self.assertEqual(e.model, "E")
        self.assertEqual(e.input_cap_chars, 1234)
        self.assertEqual(e.backend, "ollama")

    # ── defaults.json is the ONLY source of defaults (behavioral) ────
    def test_missing_embedding_block_is_refused_not_reconstructed(self) -> None:
        base_defaults = cfgmod._read_defaults()
        stripped = {k: v for k, v in base_defaults.items() if k != "embedding"}
        with mock.patch.object(cfgmod, "_read_defaults", lambda: stripped):
            with self.assertRaises(ValueError) as ctx:
                self._load()
        self.assertIn("single source of embedding defaults", str(ctx.exception))

    def test_missing_key_is_refused_and_named(self) -> None:
        base_defaults = cfgmod._read_defaults()
        crippled = json.loads(json.dumps(base_defaults))
        del crippled["embedding"]["input_cap_chars"]
        with mock.patch.object(cfgmod, "_read_defaults", lambda: crippled):
            with self.assertRaises(ValueError) as ctx:
                self._load()
        self.assertIn("input_cap_chars", str(ctx.exception))

    def test_packaged_default_flows_from_the_data_file(self) -> None:
        # Replace a packaged default with a sentinel: the loader must
        # surface the sentinel, proving no Python literal recreates
        # "ollama"/8000/1 behind the data file's back.
        base_defaults = cfgmod._read_defaults()
        sentinel = json.loads(json.dumps(base_defaults))
        sentinel["embedding"]["backend"] = "sentinel-backend"
        sentinel["embedding"]["input_cap_chars"] = 4242
        with mock.patch.object(cfgmod, "_read_defaults", lambda: sentinel):
            e = self._load().embedding
        self.assertEqual(e.backend, "sentinel-backend")
        self.assertEqual(e.input_cap_chars, 4242)

    def test_no_literal_defaults_in_the_embedding_package(self) -> None:
        # The behavioral pins above are the real guard; this grep keeps
        # the embedding modules themselves clean too.
        pkg = Path(cfgmod.__file__).parent / "embedding"
        for py in pkg.glob("*.py"):
            text = py.read_text(encoding="utf-8")
            self.assertNotIn("11434", text, f"hardcoded port in {py.name}")
            self.assertNotIn("8000", text, f"hardcoded cap in {py.name}")


if __name__ == "__main__":
    unittest.main()


class TestComposer(unittest.TestCase):
    """T2 — FR-1 (allowlist) and FR-7 (determinism, truncation).

    The fixture DB plants a sensitive marker in EVERY text-bearing
    column outside the allowlist that shares a row or session with the
    composed turns — session metadata, tool I/O, raw-differing
    preview-adjacent fields — so the assertions prove the allowlist,
    not the absence of one lucky string.
    """

    RAW_MARKER = "RAW_TRANSCRIPT_MARKER_9f3"
    PATH_MARKER = "SECRET_PROJECT_PATH_MARKER_a71"
    BENCH_MARKER = "BENCH_RUN_DIR_MARKER_c44"

    def setUp(self) -> None:
        from session_analytics.relational.db import Database, apply_ddl

        tmp = Path(tempfile.mkdtemp(prefix="cct-sa-embed-"))
        self.db = Database.connect(f"sqlite:///{tmp / 'sa.db'}")
        apply_ddl(self.db)
        self.sid = self.db.insert_returning_id(
            "INSERT INTO copilot_session (copilot, session_id, project_path, "
            "benchmark_run_dir, turn_count) VALUES (?, ?, ?, ?, ?) RETURNING id",
            ("claude-code", "sess-1", f"/home/x/{self.PATH_MARKER}",
             f"/runs/{self.BENCH_MARKER}", 3),
        )
        # Turn previews are the ONLY text allowed through. slash_command
        # and uuid carry the raw marker to prove other copilot_turn
        # columns are excluded too.
        for seq, role, preview in (
            (0, "user", "please fix the login bug"),
            (1, "assistant", "reading auth.py and the failing test"),
            (2, "user", ""),          # empty preview: contributes nothing
            (3, "assistant", None),   # NULL preview: contributes nothing
            (4, "assistant", "done - added a null check"),
        ):
            self.db.execute(
                "INSERT INTO copilot_turn (session_id, sequence_num, role, "
                "content_preview, content_length, slash_command, uuid) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (self.sid, seq, role, preview, len(preview or ""),
                 f"/cmd-{self.RAW_MARKER}", f"uuid-{self.RAW_MARKER}"),
            )
        self.db.commit()
        self.addCleanup(self.db.close)

    def _compose(self, cap=8000):
        from session_analytics.embedding.composer import compose_input

        return compose_input(self.db, self.sid, cap_chars=cap)

    # ── FR-1: the allowlist, proven on planted markers ───────────────
    def test_no_marker_reaches_the_composed_text(self) -> None:
        text = self._compose().text
        for marker in (self.RAW_MARKER, self.PATH_MARKER, self.BENCH_MARKER):
            self.assertNotIn(marker, text)

    def test_preview_text_is_present_and_role_tagged(self) -> None:
        text = self._compose().text
        self.assertIn("user: please fix the login bug", text)
        self.assertIn("assistant: reading auth.py and the failing test", text)

    def test_the_query_names_exactly_the_allowlist(self) -> None:
        # The SQL is generated from COMPOSER_COLUMNS; pin both halves so
        # the constant and the query cannot drift, and no session join
        # sneaks in.
        from session_analytics.embedding import composer

        self.assertEqual(
            composer.COMPOSER_COLUMNS,
            ("sequence_num", "role", "content_preview"),
        )
        sql = composer._SELECT.lower()
        self.assertIn("from copilot_turn", sql)
        self.assertNotIn("join", sql)
        self.assertNotIn("copilot_session", sql)
        for forbidden in ("project_path", "benchmark_run_dir", "slash_command",
                          "uuid", "has_tool_use", "model"):
            self.assertNotIn(forbidden, sql)

    def test_module_source_references_no_forbidden_column(self) -> None:
        from session_analytics.embedding import composer

        src = Path(composer.__file__).read_text(encoding="utf-8")
        # Behaviour is pinned above; this keeps even a second, unused
        # query from appearing without review: exactly one FROM over
        # exactly one table, and it is copilot_turn.
        self.assertEqual(src.lower().count("from copilot_"), 1)
        self.assertIn("from copilot_turn", src.lower())

    # ── FR-7: determinism, ordering, truncation, emptiness ───────────
    def test_byte_identical_on_repeat(self) -> None:
        a, b = self._compose(), self._compose()
        self.assertEqual(a.text, b.text)
        self.assertEqual(a, b)

    def test_ordered_by_sequence_num(self) -> None:
        text = self._compose().text
        self.assertLess(
            text.index("please fix"), text.index("reading auth.py"))
        self.assertLess(
            text.index("reading auth.py"), text.index("null check"))

    def test_empty_and_null_previews_contribute_nothing(self) -> None:
        c = self._compose()
        self.assertEqual(c.turns_used, 3)  # 5 rows, 2 without preview

    def test_truncation_keeps_the_head_and_is_reported(self) -> None:
        full = self._compose().text
        c = self._compose(cap=20)
        self.assertTrue(c.truncated)
        self.assertEqual(c.text, full[:20])
        self.assertFalse(self._compose().truncated)

    def test_cap_boundary_is_not_a_truncation(self) -> None:
        full = self._compose().text
        c = self._compose(cap=len(full))
        self.assertFalse(c.truncated)
        self.assertEqual(c.text, full)

    def test_nonpositive_cap_refused(self) -> None:
        with self.assertRaises(ValueError):
            self._compose(cap=0)

    def test_empty_session_is_unembeddable_not_empty_string(self) -> None:
        sid2 = self.db.insert_returning_id(
            "INSERT INTO copilot_session (copilot, session_id, turn_count) "
            "VALUES (?, ?, ?) RETURNING id",
            ("claude-code", "sess-empty", 0),
        )
        self.db.commit()
        from session_analytics.embedding.composer import compose_input

        c = compose_input(self.db, sid2, cap_chars=8000)
        self.assertTrue(c.unembeddable)
        self.assertEqual(c.text, "")
        self.assertEqual(c.turns_used, 0)

    def test_all_blank_previews_are_unembeddable_too(self) -> None:
        sid3 = self.db.insert_returning_id(
            "INSERT INTO copilot_session (copilot, session_id, turn_count) "
            "VALUES (?, ?, ?) RETURNING id",
            ("claude-code", "sess-blank", 1),
        )
        self.db.execute(
            "INSERT INTO copilot_turn (session_id, sequence_num, role, "
            "content_preview, content_length) VALUES (?, ?, ?, ?, ?)",
            (sid3, 0, "user", "", 0),
        )
        self.db.commit()
        from session_analytics.embedding.composer import compose_input

        self.assertTrue(compose_input(self.db, sid3, cap_chars=100).unembeddable)
