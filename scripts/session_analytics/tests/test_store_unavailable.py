from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from session_analytics import constants as C
from session_analytics.cli import main
from session_analytics.relational.db import Database, StoreUnavailable, _dsn_without_secret

BAD = "sqlite:////nonexistent/dir/x.db"


class AStoreThatCannotBeOpened(unittest.TestCase):
    """An unusable store is the person's environment, not a crash to read.

    Measured before this guard: `team status` and `runs` printed a sqlite3.OperationalError
    traceback and exited 1, with no line saying what was wrong or where.
    """

    def run_main(self, argv):
        err = io.StringIO()
        with redirect_stderr(err):
            code = main(argv)
        return code, err.getvalue()

    def test_connect_raises_store_unavailable_with_the_path(self):
        with self.assertRaises(StoreUnavailable) as caught:
            Database.connect(BAD)
        self.assertIn("/nonexistent/dir/x.db", str(caught.exception))
        self.assertIn("unable to open database file", str(caught.exception))

    def test_the_commands_that_had_no_catch_all_report_one_line(self):
        for argv in (["team", "status"], ["runs"]):
            with self.subTest(command=argv[0]):
                code, err = self.run_main(argv + ["--db", BAD])
                self.assertEqual(code, C.EXIT_RUNTIME)
                self.assertIn("error: cannot open the store:", err)
                self.assertNotIn("Traceback", err)
                self.assertEqual(err.count("\n"), 1)

    def test_the_commands_with_a_catch_all_do_not_log_a_traceback_first(self):
        for command in ("kpis", "gaps", "ingest"):
            argv = [command, "--db", BAD]
            if command == "ingest":
                argv += ["--copilot", "claude-code"]
            with self.subTest(command=command):
                code, err = self.run_main(argv)
                self.assertEqual(code, C.EXIT_RUNTIME)
                self.assertIn("error: cannot open the store:", err)
                self.assertNotIn("Traceback", err)

    def test_a_password_in_the_dsn_never_reaches_the_message(self):
        self.assertEqual(
            _dsn_without_secret("postgresql://someone:hunter2@db.internal:5432/sessions"),
            "postgresql://someone:***@db.internal:5432/sessions",
        )

    def test_a_working_store_is_still_a_working_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            dsn = "sqlite:///" + (Path(tmp) / "ok.db").as_posix()
            db = Database.connect(dsn)
            db.close()
            code, err = self.run_main(["team", "status", "--db", dsn])
        self.assertEqual(code, C.EXIT_OK)
        self.assertNotIn("cannot open the store", err)


if __name__ == "__main__":
    unittest.main()
