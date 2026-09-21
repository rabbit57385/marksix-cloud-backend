"""Test doubles verify application transactions, NOT PostgreSQL constraint execution."""

import copy
import io
import json
import unittest
from contextlib import contextmanager, redirect_stdout
from datetime import date
from unittest.mock import MagicMock, patch

import psycopg

from marksix_cloud_backend import database, update_marksix
from marksix_cloud_backend.hkjc_client import HkjcError
from marksix_cloud_backend.tests.test_models import sample_draw


def db_row(value):
    return {"draw": value["draw"], "draw_date": date.fromisoformat(value["date"]),
            **{f"number{i}": number for i, number in enumerate(value["numbers"], 1)},
            "special_number": value["special_number"]}


class ConnectionDouble:
    """Offline transaction/cursor fake only; never used by the application."""
    autocommit = True

    def __init__(self):
        self.rows = {}
        self.commands = []
        self.fail_draws = set()
        self.fail_commit = False
        self.commits = 0
        self.rollbacks = 0
        self.info = MagicMock(transaction_status=psycopg.pq.TransactionStatus.IDLE)

    @contextmanager
    def transaction(self):
        before = copy.deepcopy(self.rows)
        self.info.transaction_status = psycopg.pq.TransactionStatus.INTRANS
        try:
            yield
            if self.fail_commit:
                self.fail_commit = False
                raise psycopg.OperationalError("simulated commit failure")
        except Exception:
            self.rows = before
            self.rollbacks += 1
            raise
        else:
            self.commits += 1
        finally:
            self.info.transaction_status = psycopg.pq.TransactionStatus.IDLE

    @contextmanager
    def cursor(self):
        yield CursorDouble(self)


class CursorDouble:
    def __init__(self, connection):
        self.connection = connection
        self.result = None

    def execute(self, query, params):
        self.connection.commands.append((query, params))
        if query.lstrip().startswith("INSERT"):
            draw, draw_date, *balls = params
            if draw in self.connection.fail_draws:
                raise psycopg.IntegrityError("simulated database rejection")
            if draw in self.connection.rows:
                self.result = None
            else:
                value = {"draw": draw, "date": draw_date, "numbers": balls[:6], "special_number": balls[6]}
                self.connection.rows[draw] = db_row(value)
                self.result = {"id": len(self.connection.rows)}
        elif query.startswith("SELECT"):
            self.result = self.connection.rows.get(params[0])
        else:
            raise AssertionError("Unexpected SQL in test double")

    def fetchone(self):
        return self.result


class DatabaseUpdaterTests(unittest.TestCase):
    def test_repeated_draw_inserts_once_and_then_reports_existing(self):
        connection = ConnectionDouble()
        stats = update_marksix.import_draws(connection, [sample_draw(), sample_draw()])
        self.assertEqual(stats, {"inserted": 1, "existing": 1, "conflict": 0, "failed": 0})
        self.assertEqual(len(connection.rows), 1)
        self.assertEqual(connection.commits, 2)
        insert = connection.commands[0][0]
        self.assertIn("ON CONFLICT (draw) DO NOTHING", insert)
        self.assertNotIn("DO UPDATE", insert)

    def test_conflict_reports_all_changed_fields_without_overwriting(self):
        connection = ConnectionDouble()
        database.store_draw(connection, sample_draw())
        before = copy.deepcopy(connection.rows)
        changed = sample_draw(date="2026-09-18", numbers=[1, 2, 3, 4, 5, 6], special_number=7)
        with self.assertLogs(update_marksix.logger, level="WARNING") as logs:
            stats = update_marksix.import_draws(connection, [changed])
        self.assertEqual(stats["conflict"], 1)
        self.assertEqual(connection.rows, before)
        for word in ("26/102", '"date"', '"numbers"', '"special_number"', '"database"', '"hkjc"'):
            self.assertIn(word, "\n".join(logs.output))

    def test_main_number_reordering_is_reported_not_silently_rewritten(self):
        connection = ConnectionDouble()
        database.store_draw(connection, sample_draw())
        status, changes = database.store_draw(connection, sample_draw(numbers=[31, 19, 14, 11, 8, 5]))
        self.assertEqual(status, "conflict")
        self.assertEqual(set(changes), {"numbers"})

    def test_one_db_failure_rolls_back_and_other_draws_commit(self):
        connection = ConnectionDouble()
        connection.fail_draws.add("26/101")
        draws = [sample_draw(), sample_draw(draw="26/101"), sample_draw(draw="26/100")]
        with self.assertLogs(update_marksix.logger, level="ERROR"):
            stats = update_marksix.import_draws(connection, draws)
        self.assertEqual(stats, {"inserted": 2, "existing": 0, "conflict": 0, "failed": 1})
        self.assertEqual(set(connection.rows), {"26/102", "26/100"})
        self.assertEqual((connection.commits, connection.rollbacks), (2, 1))

    def test_commit_failure_not_counted_as_inserted(self):
        connection = ConnectionDouble()
        connection.fail_commit = True
        with self.assertLogs(update_marksix.logger, level="ERROR"):
            stats = update_marksix.import_draws(connection, [sample_draw(), sample_draw(draw="26/101")])
        self.assertEqual(stats["inserted"], 1)
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(set(connection.rows), {"26/101"})

    def test_invalid_python_row_never_reaches_sql_and_does_not_abort_batch(self):
        connection = ConnectionDouble()
        with self.assertLogs(update_marksix.logger, level="ERROR"):
            stats = update_marksix.import_draws(
                connection, [sample_draw(special_number=5), sample_draw()])
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["inserted"], 1)
        self.assertEqual(len(connection.commands), 1)

    def test_refuses_ambient_transaction(self):
        connection = ConnectionDouble()
        for autocommit, status in ((False, psycopg.pq.TransactionStatus.IDLE),
                                   (True, psycopg.pq.TransactionStatus.INTRANS)):
            connection.autocommit = autocommit
            connection.info.transaction_status = status
            with self.subTest(autocommit=autocommit), self.assertRaises(ValueError):
                database.store_draw(connection, sample_draw())
        self.assertEqual(connection.commands, [])

    def test_row_mapping(self):
        self.assertEqual(database.row_to_draw(db_row(sample_draw())), sample_draw())

    def test_repository_uses_qualified_schema_parameterized_limit_and_date_order(self):
        with patch.object(database, "connect_database") as connect:
            cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
            cursor.fetchall.return_value = [db_row(sample_draw())]
            self.assertEqual(database.DrawRepository().recent(20), [sample_draw()])
            query, params = cursor.execute.call_args.args
            self.assertIn("FROM marksix.draws", query)
            self.assertIn("ORDER BY draw_date DESC, draw DESC LIMIT %s", query)
            self.assertEqual(params, (20,))

    def test_latest_empty_and_uses_limit_one(self):
        repository = database.DrawRepository()
        with patch.object(repository, "recent", return_value=[]) as recent:
            self.assertIsNone(repository.latest())
            recent.assert_called_once_with(1)

    def test_missing_database_url_never_connects_or_fetches_upstream(self):
        with patch.dict("os.environ", {}, clear=True), \
             patch.object(database.psycopg, "connect") as connect, \
             patch.object(update_marksix, "fetch_recent_draws") as fetch, \
             redirect_stdout(io.StringIO()) as output, \
             self.assertLogs(update_marksix.logger, level="ERROR"):
            self.assertEqual(update_marksix.main([]), 1)
        connect.assert_not_called()
        fetch.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["batch_error"], "database_not_configured")

    def test_cli_hkjc_error_has_statistics_and_no_db_write(self):
        with patch.object(update_marksix, "database_url", return_value="configured"), \
             patch.object(update_marksix, "fetch_recent_draws", side_effect=HkjcError("graphql", {})), \
             patch.object(update_marksix, "connect_database") as connect, \
             redirect_stdout(io.StringIO()) as output, \
             self.assertLogs(update_marksix.logger, level="ERROR"):
            self.assertEqual(update_marksix.main([]), 1)
        connect.assert_not_called()
        summary = json.loads(output.getvalue())
        self.assertEqual(summary["batch_error"], "graphql")
        for key in ("inserted", "existing", "conflict", "failed"):
            self.assertEqual(summary[key], 0)

    def test_cli_conflicts_produce_nonzero_exit_and_summary(self):
        with patch.object(update_marksix, "database_url", return_value="configured"), \
             patch.object(update_marksix, "fetch_recent_draws", return_value=[sample_draw()]), \
             patch.object(update_marksix, "connect_database"), \
             patch.object(update_marksix, "import_draws", return_value={
                 "inserted": 0, "existing": 0, "conflict": 1, "failed": 0}), \
             redirect_stdout(io.StringIO()) as output:
            self.assertEqual(update_marksix.main(["--last-n", "5"]), 1)
        self.assertEqual(json.loads(output.getvalue())["conflict"], 1)
