"""Isolated MarkSix historical-grade contract and look-ahead checks."""
import copy
import unittest
from unittest.mock import Mock
from fastapi.testclient import TestClient

from marksix_cloud_backend import main
from marksix_cloud_backend.analysis_repository import AnalysisSnapshot, AnalysisRepository
from marksix_cloud_backend.analysis_rules import score_number, classify_grade
from marksix_cloud_backend.draw_sync import source_revision
from marksix_cloud_backend.grade_history import grade_history_response, GRADES
from marksix_cloud_backend.tests.test_analysis_foundation import history


class GradeHistoryTests(unittest.TestCase):
    def test_windows_modes_and_no_future_leakage(self):
        rows = history(203)
        snapshot = AnalysisSnapshot.from_records(rows)
        for mode in (False, True):
            probability = (7 if mode else 6) / 49
            for window in (10, 30, 50, 100):
                result = grade_history_response(snapshot, window, mode)
                data = result["data"]
                self.assertEqual(result["source_revision"], source_revision(snapshot))
                self.assertEqual(data["data_snapshot_id"], source_revision(snapshot).split(":")[1])
                self.assertEqual(data["count"], window)
                self.assertTrue(data["complete_window"])
                self.assertEqual(data["theoretical_probability"], probability)
                for index, draw in enumerate(data["draws"]):
                    target = len(rows) - 1 - index
                    self.assertEqual(draw["draw_no"], rows[target]["draw"])
                    self.assertEqual(draw["grade_cutoff"]["draw_no"], rows[target-1]["draw"])
                    self.assertEqual(len(draw["number_grades"]), 49)
                    for entry in draw["number_grades"]:
                        n = entry["number"]
                        ratios = [
                            sum(n in (d["numbers"] + ([d["special_number"]] if mode else []))
                                for d in rows[target-w:target]) / (w * probability)
                            for w in (10, 30,50,100)
                        ]
                        self.assertEqual(entry["grade"], classify_grade(score_number(*ratios)[0]))
                    self.assertEqual(sum(draw["hit_counts"].values()), 7 if mode else 6)
                    self.assertEqual(sum(draw["main_hit_counts"].values()), 6)
                    self.assertEqual(sum(draw["special_hit_counts"].values()), 1)
                self.assertEqual(sum(data["summary"]["hit_counts"].values()), window * (7 if mode else 6))
            changed = copy.deepcopy(rows)
            target = 130
            for row in changed[target:]:
                row["numbers"] = list(range(30, 36))
                row["special_number"] = 36
            new = grade_history_response(AnalysisSnapshot.from_records(changed), 100, mode)
            old = grade_history_response(snapshot, 100, mode)
            key = rows[target]["draw"]
            prior = next(row for row in old["data"]["draws"] if row["draw_no"] == key)
            after = next(row for row in new["data"]["draws"] if row["draw_no"] == key)
            self.assertEqual(prior["number_grades"], after["number_grades"])
            self.assertNotEqual(old["source_revision"], new["source_revision"])

    def test_incomplete_and_empty_never_manufacture_grades(self):
        for size, count in ((0, 0), (99, 0), (100, 0), (101, 1), (105, 5)):
            for mode in (False, True):
                snapshot = AnalysisSnapshot.from_records(history(size))
                data = grade_history_response(snapshot, 100, mode)["data"]
                self.assertEqual(data["count"], count)
                self.assertFalse(data["complete_window"])
                self.assertEqual(data["incomplete_reason"], "insufficient_pre_draw_history")
                self.assertEqual(len(data["draws"]), count)
                self.assertEqual(sum(data["summary"]["hit_counts"].values()), count * (7 if mode else 6))
                self.assertEqual(data["latest_draw"] is None, size == 0)

    def test_endpoint_snapshot_and_validation(self):
        snapshot = AnalysisSnapshot.from_records(history(203))
        repo = Mock(spec=AnalysisRepository)
        repo.load_analysis_draws.return_value = snapshot
        main.app.dependency_overrides[main.get_analysis_repository] = lambda: repo
        self.addCleanup(main.app.dependency_overrides.clear)
        with TestClient(main.app) as client:
            path = "/api/v1/marksix/grade-history"
            for mode in (False, True):
                for window in (10, 30, 50, 100):
                    repo.reset_mock()
                    reply = client.get(path, params={"window": window, "include_special": mode})
                    self.assertEqual(reply.status_code, 200)
                    repo.load_analysis_draws.assert_called_once_with()
                    self.assertEqual(reply.headers["x-marksix-source-revision"], source_revision(snapshot))
                    self.assertEqual(reply.json(), grade_history_response(snapshot, window, mode))
            for params in ({"window": 1}, {"window": 101}, {"include_special": "invalid"}):
                self.assertEqual(client.get(path, params=params).status_code, 422)
