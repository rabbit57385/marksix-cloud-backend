"""Offline contracts and boundary tests; no HKJC or PostgreSQL connections."""

import unittest
from dataclasses import FrozenInstanceError
from datetime import date, timedelta
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from marksix_cloud_backend import analysis_repository as repository
from marksix_cloud_backend import main, statistics_core as stats
from marksix_cloud_backend.tests.test_database_updater import db_row


def history(size=101):
    return [{"draw": f"20/{i + 1:03}", "date": (date(2020, 1, 1) + timedelta(days=i)).isoformat(),
             "numbers": [1, 2, 3, 4, 5, 6], "special_number": 7} for i in range(size)]


def snapshot(size=101):
    return repository.AnalysisSnapshot.from_records(history(size))


class SnapshotTests(unittest.TestCase):
    def test_1993_excluded_and_2020_first_day_included(self):
        old = {**history(1)[0], "draw": "93/001", "date": "1993-01-05"}
        result = repository.AnalysisSnapshot.from_records([old, *history(101)])
        self.assertEqual(len(result.draws), 101)
        self.assertEqual(result.draws[0].date, repository.ANALYSIS_START_DATE)

    def test_engine_oldest_first_display_newest_first(self):
        result = repository.AnalysisSnapshot.from_records(history(101)[::-1])
        self.assertEqual(result.draws[0].draw, "20/001")
        self.assertEqual(result.newest_first()[0].draw, "20/101")
        self.assertEqual(result.draws[0].draw, "20/001")

    def test_cutoff_date_is_inclusive(self):
        result = repository.AnalysisSnapshot.from_records(history(), cutoff_date=date(2020, 1, 10))
        self.assertEqual(len(result.draws), 10)
        self.assertEqual(result.draws[-1].date, date(2020, 1, 10))

    def test_cutoff_draw_inclusive_and_before_target(self):
        records = history()
        for inclusive, count in ((True, 50), (False, 49)):
            result = repository.AnalysisSnapshot.from_records(records, cutoff_draw="20/050",
                                                              include_cutoff_draw=inclusive)
            self.assertEqual(len(result.draws), count)
            self.assertEqual(result.draws[-1].draw, f"20/{count:03}")
        # Changing target and future outcomes cannot affect pre-target snapshot.
        before = repository.AnalysisSnapshot.from_records(records, cutoff_draw="20/050", include_cutoff_draw=False)
        for item in records[49:]:
            item["numbers"], item["special_number"] = [10, 11, 12, 13, 14, 15], 16
        after = repository.AnalysisSnapshot.from_records(records, cutoff_draw="20/050", include_cutoff_draw=False)
        self.assertEqual(before, after)

    def test_same_date_uses_draw_tie_breaker(self):
        rows = history(3)
        for row in rows:
            row["date"] = "2020-01-01"
        result = repository.AnalysisSnapshot.from_records(rows[::-1], cutoff_draw="20/002")
        self.assertEqual([d.draw for d in result.draws], ["20/001", "20/002"])

    def test_missing_anchor_and_incompatible_bounds_fail_closed(self):
        for kwargs in ({"cutoff_draw": "20/999"},
                       {"cutoff_draw": "20/050", "cutoff_date": date(2020, 1, 1)},
                       {"cutoff_draw": "93/001"}, {"cutoff_date": date(1993, 1, 1)},
                       {"cutoff_draw": "20/000"}, {"cutoff_date": "2020-01-01"},
                       {"include_cutoff_draw": False}):
            with self.subTest(kwargs=kwargs), self.assertRaises(repository.InvalidCutoff):
                repository.AnalysisSnapshot.from_records(history(), **kwargs)

    def test_snapshot_and_nested_numbers_immutable(self):
        rows = history()
        result = repository.AnalysisSnapshot.from_records(rows)
        rows[-1]["numbers"][0] = 49
        self.assertEqual(result.draws[-1].numbers[0], 1)
        with self.assertRaises(FrozenInstanceError):
            result.draws = ()
        with self.assertRaises(TypeError):
            result.draws[-1].numbers[0] = 49
        payload = result.draws[-1].as_dict()
        payload["numbers"].append(7)
        self.assertEqual(len(result.draws[-1].numbers), 6)

    def test_duplicate_draw_rejected(self):
        with self.assertRaises(repository.AnalysisDataError):
            repository.AnalysisSnapshot.from_records(history(1) * 2)

    def test_repository_sql_boundary_unlimited_order_and_one_read(self):
        with patch.object(repository, "connect_database") as connect:
            cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
            cursor.fetchall.return_value = [db_row(d) for d in history(301)]
            result = repository.AnalysisRepository().load_analysis_draws()
        self.assertEqual(len(result.draws), 301)
        cursor.execute.assert_called_once()
        query, params = cursor.execute.call_args.args
        self.assertIn("FROM marksix.draws WHERE draw_date >= %s", query)
        self.assertIn("ORDER BY draw_date ASC, draw ASC", query)
        self.assertNotIn("LIMIT", query)
        self.assertEqual(params, (date(2020, 1, 1),))

    def test_repository_cutoffs_parameterized_same_sql_statement(self):
        with patch.object(repository, "connect_database") as connect:
            cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
            cursor.fetchall.return_value = [db_row(d) for d in history(50)]
            result = repository.AnalysisRepository().load_analysis_draws(
                cutoff_date=date(2020, 3, 1), cutoff_draw="20/050", include_cutoff_draw=False)
        query, params = cursor.execute.call_args.args
        self.assertIn("draw_date <= %s", query)
        self.assertIn("(draw_date, draw) <= (SELECT draw_date, draw", query)
        self.assertNotIn("20/050", query)
        self.assertEqual(params, (date(2020, 1, 1), date(2020, 3, 1), "20/050", date(2020, 1, 1)))
        self.assertEqual(len(result.draws), 49)
        cursor.execute.assert_called_once()

    def test_invalid_cutoff_never_connects(self):
        with patch.object(repository, "connect_database") as connect, self.assertRaises(repository.InvalidCutoff):
            repository.AnalysisRepository().load_analysis_draws(cutoff_draw="invalid")
        connect.assert_not_called()


class StatisticsTests(unittest.TestCase):
    def test_six_and_seven_number_statistics_keep_special_independent(self):
        item = snapshot().draws[0]
        self.assertEqual(stats.numbers_from_draw(item), (1, 2, 3, 4, 5, 6))
        self.assertEqual(stats.numbers_from_draw(item, True), (1, 2, 3, 4, 5, 6, 7))
        self.assertEqual(item.special_number, 7)
        self.assertEqual(len(item.numbers), 6)
        self.assertNotIn("number7", item.as_dict())

    def test_ratios_both_modes(self):
        self.assertAlmostEqual(stats.momentum_ratio(2, 10), 2 / (10 * 6 / 49))
        self.assertAlmostEqual(stats.momentum_ratio(2, 10, True), 2 / (10 * 7 / 49))
        self.assertEqual(stats.momentum_ratio(0, 100), 0)

    def test_all_complete_windows_counts_ratios_and_total(self):
        source = snapshot()
        for window in stats.WINDOWS:
            for mode in (False, True):
                with self.subTest(window=window, mode=mode):
                    counts = stats.count_by_window(source, window, mode)
                    self.assertEqual(len(counts), 49)
                    self.assertEqual(counts[1], window)
                    self.assertEqual(counts[7], window if mode else 0)
                    self.assertEqual(sum(counts.values()), window * (7 if mode else 6))
                    result = stats.draw_counts_response(source, window, mode)
                    self.assertEqual(result["actual_draw_count"], window)
                    self.assertAlmostEqual(result["numbers"][0]["momentum_ratio"], 49 / (7 if mode else 6))

    def test_counts_use_latest_window_not_oldest(self):
        rows = history(20)
        for row in rows[10:]:
            row["numbers"], row["special_number"] = [10, 11, 12, 13, 14, 15], 16
        counts = stats.count_by_window(repository.AnalysisSnapshot.from_records(rows), 10)
        self.assertEqual((counts[1], counts[10]), (0, 10))

    def test_incomplete_windows_rejected_not_rescaled(self):
        for window in stats.WINDOWS:
            with self.subTest(window=window), self.assertRaises(stats.InsufficientHistory) as caught:
                stats.count_by_window(snapshot(window - 1), window)
            self.assertEqual(caught.exception.available, window - 1)
        self.assertEqual(stats.draw_counts_response(snapshot(99), 50)["actual_draw_count"], 50)

    def test_missing_zero_increment_special_and_unseen_lower_bound(self):
        rows = history(3)
        rows[1]["numbers"], rows[1]["special_number"] = [8, 9, 10, 11, 12, 13], 1
        rows[2]["numbers"], rows[2]["special_number"] = [14, 15, 16, 17, 18, 19], 2
        source = repository.AnalysisSnapshot.from_records(rows)
        self.assertEqual(stats.missing_count(source, 14)["missing_periods"], 0)
        self.assertEqual(stats.missing_count(source, 8)["missing_periods"], 1)
        self.assertEqual(stats.missing_count(source, 1)["missing_periods"], 2)
        self.assertEqual(stats.missing_count(source, 1, True)["missing_periods"], 1)
        self.assertEqual(stats.missing_count(source, 2, True)["missing_periods"], 0)
        self.assertEqual(stats.missing_count(source, 49), {
            "number": 49, "missing_periods": 3, "is_lower_bound": True,
            "last_draw": None, "last_date": None})
        self.assertFalse(stats.missing_count(source, 1)["is_lower_bound"])

    def test_old_1993_occurrence_cannot_be_last_seen(self):
        old = {"draw": "93/001", "date": "1993-01-05", "numbers": [44, 45, 46, 47, 48, 49], "special_number": 43}
        source = repository.AnalysisSnapshot.from_records([old, *history(10)])
        self.assertEqual(stats.missing_count(source, 49)["missing_periods"], 10)
        self.assertTrue(stats.missing_count(source, 49)["is_lower_bound"])

    def test_empty_missing_rejected(self):
        with self.assertRaises(stats.InsufficientHistory):
            stats.missing_numbers_response(snapshot(0))

    def test_invalid_modes_windows_and_counts(self):
        for mode in ("false", 1, None):
            with self.assertRaises(ValueError):
                stats.theoretical_probability(mode)
        for window in (0, 20, True, 10.0):
            with self.assertRaises(ValueError):
                stats.count_by_window(snapshot(), window)
        for count, size in ((1, 0), (11, 10), (-1, 10), (True, 10)):
            with self.assertRaises(ValueError):
                stats.momentum_ratio(count, size)


class StatisticsApiTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(repository, "connect_database", side_effect=AssertionError("no live DB"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.repo = Mock(spec=repository.AnalysisRepository)
        self.source = snapshot()
        self.repo.load_analysis_draws.return_value = self.source
        main.app.dependency_overrides[main.get_analysis_repository] = lambda: self.repo
        self.addCleanup(main.app.dependency_overrides.clear)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)

    def test_draw_counts_contract_both_modes_all_windows(self):
        for mode in (False, True):
            for window in stats.WINDOWS:
                self.repo.reset_mock()
                response = self.client.get(f"/api/v1/marksix/draw-counts?window={window}&include_special={str(mode).lower()}")
                self.assertEqual(response.status_code, 200, response.text)
                data = response.json()
                self.assertEqual((data["window"], data["actual_draw_count"]), (window, window))
                self.assertEqual(data["include_special"], mode)
                self.assertAlmostEqual(data["theoretical_probability"], (7 if mode else 6) / 49)
                self.assertEqual(data["available_draw_count"], 101)
                self.assertEqual(len(data["numbers"]), 49)
                self.assertEqual(data["latest_draw"]["numbers"], [1, 2, 3, 4, 5, 6])
                self.assertEqual(data["latest_draw"]["special_number"], 7)
                self.assertNotIn("grade", response.text)
                self.assertNotIn("v7", response.text)
                self.repo.load_analysis_draws.assert_called_once_with()

    def test_default_window_and_invalid_parameters(self):
        self.assertEqual(self.client.get("/api/v1/marksix/draw-counts").json()["window"], 30)
        for query in ("window=20", "window=0", "window=oops", "include_special=oops"):
            self.assertEqual(self.client.get("/api/v1/marksix/draw-counts?" + query).status_code, 422)

    def test_insufficient_100_window_contract(self):
        self.repo.load_analysis_draws.return_value = snapshot(99)
        response = self.client.get("/api/v1/marksix/draw-counts?window=100")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], {"code": "insufficient_analysis_history",
                         "analysis_start_date": "2020-01-01", "required_draw_count": 100, "actual_draw_count": 99})

    def test_missing_contract_uses_one_identical_snapshot_for_all_numbers(self):
        with patch.object(stats, "missing_count", wraps=stats.missing_count) as missing:
            response = self.client.get("/api/v1/marksix/missing-numbers?include_special=true")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertIsNone(data["window"])
        self.assertEqual(data["analysis_start_date"], "2020-01-01")
        self.assertEqual(data["actual_draw_count"], 101)
        self.assertEqual(data["cutoff_draw"], self.source.draws[-1].draw)
        self.assertTrue(data["include_special"])
        self.assertAlmostEqual(data["theoretical_probability"], 7 / 49)
        self.assertEqual(data["numbers"][6]["missing_periods"], 0)
        self.assertEqual(data["numbers"][48]["missing_periods"], 101)
        self.assertTrue(data["numbers"][48]["is_lower_bound"])
        self.assertEqual(missing.call_count, 49)
        self.assertTrue(all(call.args[0] is self.source for call in missing.call_args_list))
        self.repo.load_analysis_draws.assert_called_once_with()

    def test_independent_requests_refresh_snapshot(self):
        self.repo.load_analysis_draws.side_effect = [snapshot(101), snapshot(102)]
        first = self.client.get("/api/v1/marksix/missing-numbers").json()
        second = self.client.get("/api/v1/marksix/missing-numbers").json()
        self.assertEqual((first["cutoff_draw"], second["cutoff_draw"]), ("20/101", "20/102"))
        self.assertEqual(self.repo.load_analysis_draws.call_count, 2)

    def test_missing_empty_returns_insufficient(self):
        self.repo.load_analysis_draws.return_value = snapshot(0)
        self.assertEqual(self.client.get("/api/v1/marksix/missing-numbers").status_code, 409)


if __name__ == "__main__":
    unittest.main()
