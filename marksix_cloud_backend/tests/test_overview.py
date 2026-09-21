"""Offline production homepage integration through the real repository path."""

import unittest
from datetime import date
from unittest.mock import patch

import psycopg
from fastapi.testclient import TestClient

from marksix_cloud_backend import analysis_repository as repository, main
from marksix_cloud_backend.database import DatabaseConfigurationError
from marksix_cloud_backend.tests.test_database_updater import db_row
from marksix_cloud_backend.tests.test_statistics import history


class OverviewTests(unittest.TestCase):
    def setUp(self):
        main.app.dependency_overrides.clear()
        self.addCleanup(main.app.dependency_overrides.clear)
        patcher = patch.object(repository, "connect_database")
        self.connect = patcher.start()
        self.addCleanup(patcher.stop)
        self.cursor = self.connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        self.records = history(101)
        self.cursor.fetchall.return_value = [db_row(d) for d in self.records]
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)

    def test_contract_one_connection_one_query_same_snapshot_and_cutoff(self):
        with patch.object(main, "draw_counts_response", wraps=main.draw_counts_response) as counts, \
             patch.object(main, "missing_numbers_response", wraps=main.missing_numbers_response) as missing:
            response = self.client.get("/api/v1/marksix/overview")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(set(data), {"latest", "recent_draws", "momentum", "missing", "analysis"})
        self.assertEqual(data["latest"], self.records[-1])
        self.assertEqual(data["recent_draws"], self.records[-20:][::-1])
        self.assertEqual(set(data["momentum"]), {"10", "30", "50", "100"})
        source = missing.call_args.args[0]
        self.assertEqual(counts.call_count, 4)
        self.assertTrue(all(call.args[0] is source for call in counts.call_args_list))
        for section in [data["analysis"], data["missing"], *data["momentum"].values()]:
            self.assertEqual(section["cutoff_draw"], data["latest"]["draw"])
            self.assertEqual(section["cutoff_date"], data["latest"]["date"])
            self.assertEqual(section["analysis_start_date"], "2020-01-01")
            self.assertIs(section["include_special"], False)
            self.assertAlmostEqual(section["theoretical_probability"], 6 / 49)
        for window, section in data["momentum"].items():
            self.assertEqual(section["window"], int(window))
            self.assertEqual(section["actual_draw_count"], int(window))
            self.assertEqual([n["number"] for n in section["numbers"]], list(range(1, 50)))
            self.assertEqual(sum(n["count"] for n in section["numbers"]), int(window) * 6)
            for n in section["numbers"]:
                self.assertAlmostEqual(n["momentum_ratio"], n["count"] / (int(window) * 6 / 49))
            self.assertEqual(section["numbers"][6]["count"], 0)  # special remains separate
        self.assertEqual(len(data["missing"]["numbers"]), 49)
        self.assertEqual(data["missing"]["numbers"][0]["missing_periods"], 0)
        self.assertEqual(data["missing"]["numbers"][0]["last_draw"], data["latest"]["draw"])
        self.assertEqual(data["missing"]["numbers"][0]["last_date"], data["latest"]["date"])
        self.assertTrue(data["missing"]["numbers"][48]["is_lower_bound"])
        self.connect.assert_called_once_with()
        self.cursor.execute.assert_called_once()
        sql, params = self.cursor.execute.call_args.args
        self.assertIn("FROM marksix.draws WHERE draw_date >= %s", sql)
        self.assertEqual(params, (date(2020, 1, 1),))
        for forbidden in ("recommend", "prediction", "winning_probability", "grade", "v8", "biglotto", "p5", "p6", "s0", "s1"):
            self.assertNotIn(forbidden, response.text.lower())

    def test_1993_defense_in_depth_and_no_fallback(self):
        old = {"draw": "93/001", "date": "1993-01-05", "numbers": [44, 45, 46, 47, 48, 49], "special_number": 43}
        self.cursor.fetchall.return_value = [db_row(old), *[db_row(d) for d in self.records]]
        data = self.client.get("/api/v1/marksix/overview").json()
        self.assertEqual(data["analysis"]["available_draw_count"], 101)
        self.assertNotIn("1993", str(data))
        self.assertIsNone(data["missing"]["numbers"][48]["last_draw"])
        self.cursor.fetchall.return_value = [db_row(old)]
        self.assertEqual(self.client.get("/api/v1/marksix/overview").status_code, 404)

    def test_insufficient_history_reports_required_100(self):
        for size in (1, 9, 50, 99):
            with self.subTest(size=size):
                self.cursor.fetchall.return_value = [db_row(d) for d in history(size)]
                response = self.client.get("/api/v1/marksix/overview")
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()["detail"]["required_draw_count"], 100)
                self.assertEqual(response.json()["detail"]["actual_draw_count"], size)

    def test_empty_history(self):
        self.cursor.fetchall.return_value = []
        self.assertEqual(self.client.get("/api/v1/marksix/overview").status_code, 404)

    def test_database_failures_503_without_secret_leak(self):
        for error in (DatabaseConfigurationError("secret"), psycopg.OperationalError("secret")):
            self.connect.side_effect = error
            response = self.client.get("/api/v1/marksix/overview")
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("secret", response.text)

    def test_exact_100_succeeds_and_next_request_refreshes(self):
        self.cursor.fetchall.side_effect = [[db_row(d) for d in history(size)] for size in (100, 101)]
        for size in (100, 101):
            data = self.client.get("/api/v1/marksix/overview").json()
            self.assertEqual(data["analysis"]["available_draw_count"], size)
            self.assertEqual(data["latest"]["draw"], f"20/{size:03}")
        self.assertEqual(self.connect.call_count, 2)

    def test_cutoff_snapshot_shared_by_all_sections(self):
        source = repository.AnalysisSnapshot.from_records(
            history(110), cutoff_draw="20/105", include_cutoff_draw=False)
        main.app.dependency_overrides[main.get_analysis_snapshot] = lambda: source
        data = self.client.get("/api/v1/marksix/overview").json()
        self.assertEqual(data["latest"]["draw"], "20/104")
        for section in [data["analysis"], data["missing"], *data["momentum"].values()]:
            self.assertEqual(section["cutoff_draw"], "20/104")
        self.connect.assert_not_called()
