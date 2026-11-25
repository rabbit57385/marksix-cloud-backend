"""Isolated fixture tests of both modes and the single-snapshot signal contract."""
import unittest
from fastapi.testclient import TestClient
from marksix_cloud_backend import main, momentum_signals as signals
from marksix_cloud_backend.analysis_repository import AnalysisSnapshot
from marksix_cloud_backend.analysis_engine import build_analysis_foundation
from marksix_cloud_backend.draw_sync import source_revision
from marksix_cloud_backend.tests.test_analysis_foundation import history

ENDPOINTS = ("momentum-changes", "explosion-momentum", "recovery-momentum",
             "reversal-momentum", "overheat-warning", "focus-observation")


class MomentumSignalTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = AnalysisSnapshot.from_records(history())
        self.client = TestClient(main.app)
        main.app.dependency_overrides[main.get_analysis_snapshot] = lambda: self.snapshot
        self.addCleanup(main.app.dependency_overrides.clear)
        self.addCleanup(self.client.close)

    def get(self, endpoint, mode):
        result = self.client.get(f"/api/v1/marksix/{endpoint}", params={"include_special": mode})
        self.assertEqual(result.status_code, 200, result.text)
        body = result.json()
        self.assertEqual(body["source_revision"], source_revision(self.snapshot))
        self.assertEqual(result.headers["X-MarkSix-Source-Revision"], body["source_revision"])
        self.assertIs(body["data"]["include_special"], mode)
        return body["data"]

    def test_all_read_only_endpoints_and_mode_isolation(self):
        all_modes = []
        for mode in (False, True):
            data = {endpoint: self.get(endpoint, mode) for endpoint in ENDPOINTS}
            for endpoint in ENDPOINTS[1:5]:
                rows = data[endpoint]["numbers"]
                self.assertEqual(len(rows), data[endpoint]["count"])
                self.assertEqual(data[endpoint]["expected_probability"], f"{6 + int(mode)}/49")
                self.assertEqual(len(set(row["number"] for row in rows)), len(rows))
                self.assertEqual(data[endpoint]["latest_draw"], data["focus-observation"]["latest_draw"])
            self.assertEqual(len(data["momentum-changes"]["all_changes"]), 49)
            self.assertEqual(len(data["focus-observation"]["numbers"]), 49)
            self.assertEqual(data["focus-observation"]["metadata"]["qualified_count"],
                             sum(row["positive_signal_count"] >= 2 for row in data["focus-observation"]["numbers"]))
            all_modes.append(data)
        self.assertNotEqual(all_modes[0]["focus-observation"]["snapshot_id"], all_modes[1]["focus-observation"]["snapshot_id"])
        self.assertEqual(all_modes[0]["recovery-momentum"]["numbers"], [])
        self.assertEqual(all_modes[1]["overheat-warning"]["numbers"], [])

    def test_cutoff_and_special_number_are_recomputed(self):
        for mode in (False, True):
            f = build_analysis_foundation(self.snapshot, mode)
            result = self.get("momentum-changes", mode)
            self.assertEqual(result["comparison"]["previous_draw"]["draw_no"], self.snapshot.draws[-2].draw)
            self.assertEqual(result["comparison"]["current_draw"]["draw_no"], self.snapshot.draws[-1].draw)
            for item, current, previous in zip(result["all_changes"], f.current.numbers, f.previous.numbers):
                self.assertEqual(item["score_delta"], round(current.score - previous.score, 4))
                for window in (10, 30, 50, 100):
                    self.assertAlmostEqual(item["momentum_delta"][str(window)],
                                           getattr(current, f"r{window}") - getattr(previous, f"r{window}"), places=3)
            n = self.snapshot.draws[-1].special_number
            count = sum(n in draw.numbers or (mode and n == draw.special_number)
                        for draw in self.snapshot.draws[-10:])
            self.assertAlmostEqual(f.current.numbers[n-1].r10, count / (10 * (6 + int(mode)) / 49))

    def test_insufficient_history(self):
        self.snapshot = AnalysisSnapshot.from_records(history(99))
        for mode in (False, True):
            for endpoint in ENDPOINTS:
                self.assertEqual(self.client.get(f"/api/v1/marksix/{endpoint}",
                                                params={"include_special": mode}).status_code, 409)

    def test_revision_changes_for_historical_special_correction(self):
        first = self.get("focus-observation", True)
        rows = history()
        rows[0]["special_number"] = next(n for n in range(1, 50)
                                        if n not in rows[0]["numbers"] and n != rows[0]["special_number"])
        self.snapshot = AnalysisSnapshot.from_records(rows)
        second = self.get("focus-observation", True)
        self.assertEqual(first["latest_draw"], second["latest_draw"])
        self.assertNotEqual(first["snapshot_id"], second["snapshot_id"])
