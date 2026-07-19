# Tests for the connection-probe error hardening (#100).
#
# The binding assertion (maintainer guardrail, 2026-07-19): raw exception
# text must be absent from the FULL SERIALIZED response — not merely from
# the `error` field — so a leak through `error_code` or any future field is
# caught too.

from __future__ import annotations

import json
import sqlite3
import unittest

from session_analytics import constants as C
from session_analytics.api.db_test import (
    PHASE_CONNECT,
    PHASE_SCHEMA,
    classify_probe_error,
    probe,
)

# A realistic psycopg-style failure: multi-line, and carrying every piece of
# infrastructure detail we must never hand back — host, IP, port, database
# and username.
_PG_AUTH_ERROR = (
    'connection to server at "db.internal" (10.0.0.5), port 5432 failed:\n'
    'FATAL:  password authentication failed for user "admin"\n'
    'FATAL:  database "analytics_prod" does not exist'
)
_LEAKY_FRAGMENTS = (
    "db.internal", "10.0.0.5", "5432", "admin", "analytics_prod",
    "FATAL", "password authentication failed",
)


def _classify(text: str, phase: str = PHASE_CONNECT) -> str:
    return classify_probe_error(sqlite3.OperationalError(text), phase=phase)


class TestClassification(unittest.TestCase):
    def test_type_signals_apply_in_connect_phase(self) -> None:
        # ImportError/ValueError are unambiguous WHILE CONNECTING and must
        # not fall through to signature matching there.
        self.assertEqual(
            classify_probe_error(
                ImportError("no module named psycopg"), phase=PHASE_CONNECT
            ),
            C.PROBE_ERR_DRIVER_MISSING,
        )
        self.assertEqual(
            classify_probe_error(
                ValueError("no DSN configured; set --dsn"), phase=PHASE_CONNECT
            ),
            C.PROBE_ERR_BAD_DSN,
        )

    def test_type_signals_do_not_apply_in_schema_phase(self) -> None:
        # Regression: the connection already SUCCEEDED, so a ValueError from
        # int(row[0]) must not report "DSN is empty or not a supported
        # format", and an unrelated ImportError must not tell the operator
        # to install psycopg.
        self.assertEqual(
            classify_probe_error(
                ValueError("invalid literal for int() with base 10: 'x'"),
                phase=PHASE_SCHEMA,
            ),
            C.PROBE_ERR_UNKNOWN,
        )
        self.assertEqual(
            classify_probe_error(
                ImportError("cannot import name X"), phase=PHASE_SCHEMA
            ),
            C.PROBE_ERR_UNKNOWN,
        )
        # Signature matching still works in the schema phase.
        self.assertEqual(
            _classify("permission denied for table copilot_session", PHASE_SCHEMA),
            C.PROBE_ERR_PERMISSION_DENIED,
        )

    def test_signature_truth_table(self) -> None:
        cases = [
            (_PG_AUTH_ERROR, C.PROBE_ERR_AUTH_FAILED),
            # Postgres interpolates the identifier, so "role does not exist"
            # never appears contiguously — the AND-tuple signature is what
            # keeps this out of the database_missing bucket.
            ('FATAL: role "nobody" does not exist', C.PROBE_ERR_AUTH_FAILED),
            ("could not connect to server: Connection refused",
             C.PROBE_ERR_UNREACHABLE),
            ("could not translate host name to address", C.PROBE_ERR_UNREACHABLE),
            ("timeout expired", C.PROBE_ERR_UNREACHABLE),
            ('FATAL: database "nope" does not exist', C.PROBE_ERR_DATABASE_MISSING),
            ("unable to open database file", C.PROBE_ERR_DATABASE_MISSING),
            ("permission denied for table copilot_session",
             C.PROBE_ERR_PERMISSION_DENIED),
            ("attempt to write a readonly database",
             C.PROBE_ERR_PERMISSION_DENIED),
            ("something nobody has ever seen", C.PROBE_ERR_UNKNOWN),
        ]
        for text, expected in cases:
            self.assertEqual(_classify(text), expected, msg=text[:60])

    def test_word_boundary_prevents_substring_hijack(self) -> None:
        # Regression: bare `in` matching put a missing DATABASE whose name
        # merely CONTAINS "role" into the auth bucket, sending the operator
        # to check credentials for what is really a missing database.
        for name in ("role_store", "payroles", "controller_db"):
            self.assertEqual(
                _classify(f'FATAL: database "{name}" does not exist'),
                C.PROBE_ERR_DATABASE_MISSING,
                msg=name,
            )
        # A genuine role error still classifies as auth.
        self.assertEqual(
            _classify('FATAL: role "reader" does not exist'),
            C.PROBE_ERR_AUTH_FAILED,
        )
        # …and a permission error mentioning a role is NOT an auth failure
        # (the AND-tuple requires "does not exist" too).
        self.assertEqual(
            _classify('permission denied for role "reader"'),
            C.PROBE_ERR_PERMISSION_DENIED,
        )

    def test_auth_beats_database_missing_when_both_present(self) -> None:
        # The realistic Postgres message contains BOTH "password
        # authentication failed" and "does not exist"; auth must win (it is
        # the actionable cause), which is why signature order matters.
        self.assertEqual(_classify(_PG_AUTH_ERROR), C.PROBE_ERR_AUTH_FAILED)

    def test_curated_message_never_contains_exception_text(self) -> None:
        message = C.PROBE_ERROR_MESSAGES[_classify(_PG_AUTH_ERROR)]
        for fragment in _LEAKY_FRAGMENTS:
            self.assertNotIn(fragment.lower(), message.lower(), msg=fragment)

    def test_every_code_has_a_message(self) -> None:
        codes = {
            C.PROBE_ERR_DRIVER_MISSING, C.PROBE_ERR_BAD_DSN,
            C.PROBE_ERR_AUTH_FAILED, C.PROBE_ERR_UNREACHABLE,
            C.PROBE_ERR_DATABASE_MISSING, C.PROBE_ERR_PERMISSION_DENIED,
            C.PROBE_ERR_UNKNOWN,
        }
        self.assertEqual(set(C.PROBE_ERROR_MESSAGES), codes)
        self.assertTrue(all(C.PROBE_ERROR_MESSAGES[c] for c in codes))


class TestProbePayload(unittest.TestCase):
    """FR-1/FR-6: nothing exception-derived reaches the serialized payload."""

    def test_empty_dsn_is_bad_dsn(self) -> None:
        result = probe("")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], C.PROBE_ERR_BAD_DSN)
        self.assertEqual(result["error"], C.PROBE_ERROR_MESSAGES[C.PROBE_ERR_BAD_DSN])

    def test_unsupported_dsn_payload_carries_no_exception_text(self) -> None:
        # Database.connect routes any non-sqlite DSN to psycopg, so the exact
        # failure here depends on whether psycopg is installed (ImportError
        # vs a driver error). The security invariant is what we assert — it
        # must hold either way: nothing from the DSN reaches the payload.
        marker = "s3cret-host.example.internal"
        result = probe(f"mysql://user:pw@{marker}:3306/db")
        serialized = json.dumps(result)
        self.assertFalse(result["ok"])
        self.assertNotIn(marker, serialized)
        self.assertIn(result["error"], C.PROBE_ERROR_MESSAGES.values())
        self.assertIn(result["error_code"], C.PROBE_ERROR_MESSAGES)

    def test_unreachable_sqlite_path_payload_is_curated_only(self) -> None:
        # A path that cannot be opened: the payload must name neither the
        # path nor the driver's wording — the WHOLE serialized response is
        # checked, not just `error` (the guardrail).
        marker = "definitely-not-a-directory-xyz"
        result = probe(f"sqlite:////{marker}/nested/store.db")
        serialized = json.dumps(result)
        self.assertFalse(result["ok"])
        self.assertNotIn(marker, serialized)
        self.assertIn(result["error"], C.PROBE_ERROR_MESSAGES.values())
        self.assertIn(result["error_code"], C.PROBE_ERROR_MESSAGES)

    def test_success_payload_shape_unchanged(self) -> None:
        import tempfile

        result = probe(f"sqlite:///{tempfile.mktemp(suffix='.db')}")
        self.assertTrue(result["ok"])
        self.assertEqual(result["dialect"], "sqlite")
        self.assertEqual(result["sessions"], 0)
        self.assertNotIn("error", result)       # success path untouched
        self.assertNotIn("error_code", result)


if __name__ == "__main__":
    unittest.main()
