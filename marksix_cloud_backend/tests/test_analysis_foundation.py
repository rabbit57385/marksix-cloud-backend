"""Offline production rules and snapshot tests; no research/Flutter/live IO."""
import ast
import copy
import json
import math
import unittest
from dataclasses import FrozenInstanceError
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from marksix_cloud_backend import analysis_repository as repository
from marksix_cloud_backend import analysis_rules as rules
from marksix_cloud_backend.analysis_engine import build_analysis_foundation
from marksix_cloud_backend.statistics_core import InsufficientHistory
from marksix_cloud_backend.tests.test_database_updater import db_row

FIXTURES = json.loads((Path(__file__).parent / "fixtures/analysis_parity.json").read_text(encoding="utf-8"))


def history(size=103):
    return [{"draw": f"20/{i * 2 + 1:03}",
             "date": (date(2020, 1, 1) + timedelta(days=i)).isoformat(),
             "numbers": [((i * 7 + j) % 49) + 1 for j in range(6)],
             "special_number": ((i * 7 + 6) % 49) + 1} for i in range(size)]


class RuleParityTests(unittest.TestCase):
    def test_static_boundary_fixtures(self):
        types, reasons, warnings = set(), set(), set()
        for case in FIXTURES["cases"]:
            with self.subTest(case=case["name"]):
                r = case["ratios"]
                score, sr, sw = rules.score_number(*r)
                er, ew = rules.build_reasons(*r)
                self.assertEqual(score, case["score"])
                self.assertEqual(rules.classify_grade(score), case["grade"])
                self.assertEqual(rules.frozen_long_hot_score(r[2], r[3]), case["frozen_score"])
                self.assertEqual(rules.classify_momentum_type(*r), case["momentum_type"])
                self.assertEqual(sr, case["score_reasons"])
                self.assertEqual(sw, case["score_warnings"])
                self.assertEqual(er, case["extra_reasons"])
                self.assertEqual(ew, case["extra_warnings"])
                self.assertEqual(list(dict.fromkeys(sr + er)), case["reasons"])
                self.assertEqual(list(dict.fromkeys(sw + ew)), case["warnings"])
                types.add(case["momentum_type"])
                reasons.update(sr + er)
                warnings.update(sw + ew)
        self.assertEqual(len(types), 7)
        self.assertEqual(len(warnings), 4)
        # Ensure no reachable wording silently disappears from fixture coverage.
        self.assertEqual(reasons, {
            "50期穩定偏熱", "50期強勢", "50期略強", "長期偏熱", "長期強勢",
            "短中共振", "三週期共振", "中長期一致", "回補訊號", "動能加速",
            "50期偏強", "長冷短熱回補", "短期高於長期",
        })

    def test_grade_boundaries(self):
        for case in FIXTURES["grades"]:
            self.assertEqual(rules.classify_grade(case["score"]), case["grade"])

    def test_independent_duplicate_penalties_and_trends(self):
        self.assertEqual(rules.score_number(1, 1, 1, 1)[0], 59)
        self.assertEqual(rules.score_number(2.2, 1.6, 1.1, 1.1)[0], 82)
        self.assertEqual(rules.score_number(1.3, 1.1, .95, .95)[0], 62)
        self.assertEqual(rules.score_number(0, 0, 1.3, 1.25)[0], 57)

    def test_integer_arithmetic_rounding_and_clamp_contract(self):
        # All reachable scores are integral: Python ties-to-even vs Dart ties-away
        # cannot differ here. Do not invent impossible raw scores to hit clamp.
        tree = ast.parse(Path(rules.__file__).read_text(encoding="utf-8"))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "score_number")
        increments = [n for n in ast.walk(fn) if isinstance(n, ast.AugAssign)]
        self.assertTrue(increments)
        self.assertTrue(all(isinstance(n.value, ast.Constant) and isinstance(n.value.value, int)
                            for n in increments))
        for case in FIXTURES["cases"]:
            score = rules.score_number(*case["ratios"])[0]
            self.assertEqual(score, int(score))
            self.assertEqual(score, max(0, min(100, round(score, 1))))
            self.assertGreaterEqual(score, 0)
            self.assertLessEqual(score, 100)
        self.assertIn("max(0, min(100, round(score, 1)))", ast.unparse(fn))

    def test_no_display_rounding_before_rules(self):
        self.assertEqual(rules.score_number(0, 0, math.nextafter(1.1, 0), 1)[0], 58)
        self.assertEqual(rules.score_number(0, 0, 1.1, 1)[0], 68)
        r50, r100 = 1.123456789, 1.098765432
        self.assertEqual(rules.frozen_long_hot_score(r50, r100), r50 * .5 + r100 * .5)


class FoundationSnapshotTests(unittest.TestCase):
    def assert_snapshot(self, actual, draws):
        self.assertEqual(actual.cutoff_draw, draws[-1].draw)
        self.assertEqual(actual.cutoff_date, draws[-1].date)
        self.assertEqual(actual.available_draw_count, len(draws))
        self.assertFalse(actual.include_special)
        self.assertEqual(actual.theoretical_probability, 6 / 49)
        self.assertEqual([r.number for r in actual.numbers], list(range(1, 50)))
        for row in actual.numbers:
            for w in (10, 30, 50, 100):
                # Independent six-main count: never include special_number.
                count = sum(row.number in d.numbers for d in draws[-w:])
                self.assertEqual(getattr(row, f"r{w}"), count / (w * (6 / 49)))
            score, sr, sw = rules.score_number(row.r10, row.r30, row.r50, row.r100)
            er, ew = rules.build_reasons(row.r10, row.r30, row.r50, row.r100)
            self.assertEqual(row.score, score)
            self.assertEqual(row.reasons, tuple(dict.fromkeys(sr + er)))
            self.assertEqual(row.warnings, tuple(dict.fromkeys(sw + ew)))

    def test_101_complete_current_previous_windows_nonconsecutive_draws(self):
        h = repository.AnalysisSnapshot.from_records(history(101))
        result = build_analysis_foundation(h)
        self.assert_snapshot(result.current, h.draws)
        self.assert_snapshot(result.previous, h.draws[:-1])
        self.assertEqual(result.current.formula_version, result.previous.formula_version)
        self.assertNotEqual(result.current.numbers, result.previous.numbers)

    def test_insufficient_history_fails_before_any_calculation(self):
        for size in (0, 1, 99, 100):
            with self.subTest(size=size), self.assertRaises(InsufficientHistory) as exc:
                build_analysis_foundation(repository.AnalysisSnapshot.from_records(history(size)))
            self.assertEqual((exc.exception.required, exc.exception.available), (101, size))

    def test_immutable_outputs_and_input_unchanged(self):
        records = history()
        original = copy.deepcopy(records)
        h = repository.AnalysisSnapshot.from_records(records)
        result = build_analysis_foundation(h)
        self.assertEqual(records, original)
        self.assertEqual(h, repository.AnalysisSnapshot.from_records(original))
        self.assertIsNot(result.current.numbers, result.previous.numbers)
        self.assertIsNot(result.current.numbers[0], result.previous.numbers[0])
        with self.assertRaises(FrozenInstanceError):
            result.current.numbers[0].score = 0
        with self.assertRaises(TypeError):
            result.previous.numbers[0] = result.current.numbers[0]
        with self.assertRaises(FrozenInstanceError):
            result.current.numbers[0].reasons += ("changed",)

    def test_boundary_cutoff_and_future_exclusion(self):
        records = history(103)
        old = {**records[0], "date": "1993-01-01", "draw": "93/001"}
        h = repository.AnalysisSnapshot.from_records([old, *records], cutoff_draw=records[101]["draw"],
                                                     include_cutoff_draw=False)
        result = build_analysis_foundation(h)
        self.assertEqual(len(h.draws), 101)
        self.assert_snapshot(result.current, h.draws)
        self.assert_snapshot(result.previous, h.draws[:-1])
        records[-1]["numbers"] = [40, 41, 42, 43, 44, 45]
        again = repository.AnalysisSnapshot.from_records([old, *records], cutoff_date=h.draws[-1].date)
        self.assertEqual(build_analysis_foundation(again), result)

    def test_one_repository_load_connection_select_no_engine_io(self):
        with patch.object(repository, "connect_database") as connect:
            cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
            cursor.fetchall.return_value = [db_row(d) for d in history(101)]
            h = repository.AnalysisRepository().load_analysis_draws()
            result = build_analysis_foundation(h)
            connect.assert_called_once_with()
            cursor.execute.assert_called_once()
        self.assert_snapshot(result.previous, h.draws[:-1])

    def test_last_draw_changes_only_current(self):
        records = history(101)
        before = build_analysis_foundation(repository.AnalysisSnapshot.from_records(records))
        records[-1]["numbers"] = [40, 41, 42, 43, 44, 45]
        records[-1]["special_number"] = 49
        after = build_analysis_foundation(repository.AnalysisSnapshot.from_records(records))
        self.assertEqual(before.previous, after.previous)
        self.assertNotEqual(before.current, after.current)
