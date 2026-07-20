# Tests for the connection-probe error hardening (#100).
#
# The binding assertion (maintainer guardrail, 2026-07-19): raw exception
# text must be absent from the FULL SERIALIZED response — not merely from
# the `error` field — so a leak through `error_code` or any future field is
# caught too.

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from session_analytics import constants as C
from session_analytics.api.db_test import (
    PHASE_CONNECT,
    PHASE_SCHEMA,
    classify_probe_error,
    probe,
    validate_probe_dsn,
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
            # #101 admission-policy rejections — curated like every other code.
            C.PROBE_ERR_SCHEME_NOT_ALLOWED, C.PROBE_ERR_HOST_NOT_ALLOWED,
            C.PROBE_ERR_SQLITE_FILE_MISSING,
        }
        self.assertEqual(set(C.PROBE_ERROR_MESSAGES), codes)
        self.assertTrue(all(C.PROBE_ERROR_MESSAGES[c] for c in codes))


class TestDsnConstraints(unittest.TestCase):
    """#101: what the probe will ATTEMPT, decided before any connection."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="cct-dsn-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.existing = os.path.join(self.tmp, "store.db")
        open(self.existing, "wb").close()

    def test_scheme_allowlist(self) -> None:
        for dsn in (
            f"sqlite:///{self.existing}",
            "postgresql://user@localhost/db",
            "postgres://user@localhost/db",
        ):
            self.assertIsNone(validate_probe_dsn(dsn), msg=dsn)
        for dsn in (
            "mysql://user@localhost/db",
            "http://localhost/db",
            "file:///etc/passwd",
            "redis://localhost",
            "notadsn",
            # Scheme says sqlite but this is not the `sqlite://` form we can
            # resolve — refused rather than falling through to the host
            # branch (where a hostless URL would have been admitted).
            "sqlite:/relative-ish.db",
        ):
            self.assertEqual(
                validate_probe_dsn(dsn), C.PROBE_ERR_SCHEME_NOT_ALLOWED, msg=dsn
            )
        # The empty DSN is classified ONCE, by the admission function, as a
        # malformed DSN — not as an unsupported scheme.
        self.assertEqual(validate_probe_dsn(""), C.PROBE_ERR_BAD_DSN)
        self.assertEqual(probe("")["error_code"], C.PROBE_ERR_BAD_DSN)

    def test_uppercase_sqlite_still_hits_sqlite_policy(self) -> None:
        # REGRESSION: the scheme gate lowercased but sqlite routing used a
        # case-sensitive prefix test, so `SQLITE://` skipped the
        # existing-file rule and was admitted through the hostless branch.
        missing = os.path.join(self.tmp, "nope.db")
        for prefix in ("SQLITE", "SqLiTe", "sqlite"):
            self.assertEqual(
                validate_probe_dsn(f"{prefix}:///{missing}"),
                C.PROBE_ERR_SQLITE_FILE_MISSING,
                msg=prefix,
            )
            # …and an existing file is admitted whatever the case.
            self.assertIsNone(
                validate_probe_dsn(f"{prefix}:///{self.existing}"), msg=prefix
            )

    def test_unparseable_host_fails_closed(self) -> None:
        # REGRESSION: urlsplit raises on an unterminated IPv6 literal; that
        # exception used to be swallowed into None, which reads as "no
        # host" — i.e. local — and the DSN was ADMITTED. Failure to
        # determine the host must refuse, not assume.
        for dsn in (
            "postgresql://user@[::1bad/db",
            "postgresql://user@[not-an-ipv6/db",
        ):
            self.assertEqual(
                validate_probe_dsn(dsn), C.PROBE_ERR_HOST_NOT_ALLOWED, msg=dsn
            )
            self.assertEqual(
                probe(dsn)["error_code"], C.PROBE_ERR_HOST_NOT_ALLOWED, msg=dsn
            )
        # An unparseable CONFIGURED dsn must not crash admission either; it
        # simply contributes no extra allowed host.
        self.assertEqual(
            validate_probe_dsn(
                "postgresql://user@evil.example/db", ["postgresql://u@[::1bad/x"]
            ),
            C.PROBE_ERR_HOST_NOT_ALLOWED,
        )

    def test_host_allowlist(self) -> None:
        configured = "postgresql://user@db.internal:5432/analytics"
        for host in C.PROBE_LOOPBACK_HOSTS:
            # ::1 must be bracketed in a URL to parse as a host.
            netloc = f"[{host}]" if ":" in host else host
            self.assertIsNone(
                validate_probe_dsn(f"postgresql://user@{netloc}/db"), msg=host
            )
        # The configured host is allowed (test-before-save keeps working).
        self.assertIsNone(
            validate_probe_dsn("postgresql://user@db.internal/other", [configured])
        )
        # Anything else is refused BEFORE a connection is attempted.
        self.assertEqual(
            validate_probe_dsn("postgresql://user@evil.example/db", [configured]),
            C.PROBE_ERR_HOST_NOT_ALLOWED,
        )
        # A host that merely LOOKS like the configured one is not allowed.
        self.assertEqual(
            validate_probe_dsn("postgresql://user@db.internal.evil/db", [configured]),
            C.PROBE_ERR_HOST_NOT_ALLOWED,
        )
        # With no configured DSN, only loopback remains.
        self.assertEqual(
            validate_probe_dsn("postgresql://user@db.internal/db"),
            C.PROBE_ERR_HOST_NOT_ALLOWED,
        )

    def test_every_configured_dsn_contributes_its_host(self) -> None:
        # REGRESSION: only ONE configured DSN used to be consulted (the one
        # the server booted with), so after saving a new database host the
        # operator could not test it without restarting. The saved config
        # and the startup DSN are both "configured".
        saved = "postgresql://user@new-db.internal/analytics"
        startup = "postgresql://user@old-db.internal/analytics"
        for host in ("new-db.internal", "old-db.internal"):
            self.assertIsNone(
                validate_probe_dsn(
                    f"postgresql://user@{host}/db", (saved, startup)
                ),
                msg=host,
            )
        # A third-party host is still refused, and empty entries (no DSN
        # configured yet) neither crash nor widen the allowlist.
        self.assertEqual(
            validate_probe_dsn("postgresql://user@evil.example/db", ("", startup)),
            C.PROBE_ERR_HOST_NOT_ALLOWED,
        )
        self.assertIsNone(validate_probe_dsn("postgresql://user@localhost/db", ("", "")))

    def test_sqlite_existing_file_only(self) -> None:
        missing = os.path.join(self.tmp, "nope.db")
        self.assertIsNone(validate_probe_dsn(f"sqlite:///{self.existing}"))
        self.assertEqual(
            validate_probe_dsn(f"sqlite:///{missing}"),
            C.PROBE_ERR_SQLITE_FILE_MISSING,
        )
        # A directory is not a database file either.
        self.assertEqual(
            validate_probe_dsn(f"sqlite:///{self.tmp}"),
            C.PROBE_ERR_SQLITE_FILE_MISSING,
        )

    def test_sqlite_in_memory_allowed(self) -> None:
        for dsn in ("sqlite://", "sqlite:///"):
            self.assertIsNone(validate_probe_dsn(dsn), msg=dsn)

    def test_sqlite_paths_resolve_via_the_shared_helper(self) -> None:
        # The validator must agree with Database.connect about what a DSN
        # points at — same helper, so relative and absolute forms match.
        from session_analytics.relational.db import sqlite_target

        self.assertEqual(sqlite_target(f"sqlite:///{self.existing}"), self.existing)
        self.assertIsNone(validate_probe_dsn(f"sqlite:///{self.existing}"))


class TestProbeDoesNotCreateFiles(unittest.TestCase):
    """MANDATORY regression (#101): probing a missing sqlite path must NOT
    bring a database into being. Before this slice it created a ~172 KB
    schema file at any path the server could write."""

    def test_missing_path_remains_nonexistent(self) -> None:
        tmp = tempfile.mkdtemp(prefix="cct-nocreate-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        target = os.path.join(tmp, "must-not-appear.db")
        self.assertFalse(os.path.exists(target))

        result = probe(f"sqlite:///{target}")

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], C.PROBE_ERR_SQLITE_FILE_MISSING)
        # The whole point: nothing was created.
        self.assertFalse(
            os.path.exists(target),
            "probe created a database file at a caller-chosen path",
        )
        self.assertEqual(os.listdir(tmp), [])

    def test_connect_rw_mode_refuses_to_create_but_default_still_does(self) -> None:
        # The guarantee is enforced at the OPEN, not only by the pre-check,
        # so there is no TOCTOU window. The DEFAULT must keep auto-creating
        # — ingest, setup and the test suite rely on it to bring a fresh
        # store into being.
        from session_analytics.relational.db import (
            SQLITE_MODE_RW,
            Database,
        )

        tmp = tempfile.mkdtemp(prefix="cct-connmode-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        guarded = os.path.join(tmp, "guarded.db")
        created = os.path.join(tmp, "created.db")

        with self.assertRaises(sqlite3.OperationalError):
            Database.connect(f"sqlite:///{guarded}", sqlite_mode=SQLITE_MODE_RW)
        self.assertFalse(os.path.exists(guarded), "rw mode created the file")

        # Default behaviour is untouched.
        db = Database.connect(f"sqlite:///{created}")
        db.close()
        self.assertTrue(os.path.exists(created), "default mode stopped creating")

        # In-memory is unaffected by the mode (there is no file to guard).
        Database.connect("sqlite://", sqlite_mode=SQLITE_MODE_RW).close()

    def test_rw_mode_opens_every_path_form_the_default_mode_opens(self) -> None:
        # The rw path builds a file: URI, so it can diverge from the plain
        # open in ways the plain open never had: URI metacharacters in the
        # filename, and a leading "//" being read as a URI AUTHORITY.
        # Anything the default mode opens, rw must open too.
        from session_analytics.relational.db import SQLITE_MODE_RW, Database

        tmp = tempfile.mkdtemp(prefix="cct-uriform-")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)

        names = ["plain.db", "has?query.db", "has#frag.db", "has%pct.db",
                 "has space.db"]
        for name in names:
            target = os.path.join(tmp, name)
            open(target, "wb").close()
            Database.connect(
                f"sqlite:///{target}", sqlite_mode=SQLITE_MODE_RW
            ).close()

        # Doubled leading slash: "sqlite://///abs" resolves to "//abs",
        # whose first segment would become a URI authority without the
        # explicit empty-authority form.
        plain = os.path.join(tmp, "plain.db")
        Database.connect(
            f"sqlite:////{plain}", sqlite_mode=SQLITE_MODE_RW
        ).close()

        # Relative paths take no authority marker at all.
        cwd = os.getcwd()
        self.addCleanup(os.chdir, cwd)
        os.chdir(tmp)
        Database.connect("sqlite:///plain.db", sqlite_mode=SQLITE_MODE_RW).close()

    def test_foreign_host_probe_is_refused_without_connecting(self) -> None:
        # If a connection were attempted, this would hang or raise a driver
        # error; the pre-connection check makes it immediate and specific.
        result = probe(
            "postgresql://user:pw@evil.example:5432/db",
            configured_dsns=["postgresql://user@localhost/analytics"],
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], C.PROBE_ERR_HOST_NOT_ALLOWED)
        # Still no DSN content in the payload (the #100 convention).
        self.assertNotIn("evil.example", json.dumps(result))
        self.assertNotIn("pw", json.dumps(result))


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
        # mkdtemp (0700, created atomically) rather than mktemp, which only
        # RESERVES a name — another process can win the path between the
        # call and the open (TOCTOU). It also leaves the db file behind;
        # this cleans up after itself.
        tmpdir = tempfile.mkdtemp(prefix="cct-probe-")
        self.addCleanup(shutil.rmtree, tmpdir, ignore_errors=True)

        # Since #101 the probe only opens a sqlite file that ALREADY exists,
        # so the operator's real database has to be standing in for it here.
        target = os.path.join(tmpdir, "store.db")
        open(target, "wb").close()

        result = probe(f"sqlite:///{target}")
        self.assertTrue(result["ok"])
        self.assertEqual(result["dialect"], "sqlite")
        self.assertEqual(result["sessions"], 0)
        self.assertNotIn("error", result)       # success path untouched
        self.assertNotIn("error_code", result)


if __name__ == "__main__":
    unittest.main()
