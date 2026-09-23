"""Offline endpoint, serialization parity and baseline overview regression."""
import copy
import hashlib
import json
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

import psycopg
from fastapi.testclient import TestClient
from pydantic import ValidationError

from marksix_cloud_backend import main, analysis_repository as repo
from marksix_cloud_backend.analysis_engine import build_analysis_foundation, AnalysisNumber
from marksix_cloud_backend.analysis_models import AnalysisResponse
from marksix_cloud_backend.database import DatabaseConfigurationError
from marksix_cloud_backend.tests.test_analysis_foundation import history, FIXTURES
from marksix_cloud_backend.tests.test_database_updater import db_row

PATH = "/api/v1/marksix/analysis"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class AnalysisApiTests(unittest.TestCase):
    def setUp(self):
        self.h = repo.AnalysisSnapshot.from_records(history(103))
        self.repository = Mock(spec=repo.AnalysisRepository)
        self.repository.load_analysis_draws.side_effect = lambda **kw: repo.AnalysisSnapshot.from_records(history(103), **kw)
        main.app.dependency_overrides[main.get_analysis_repository] = lambda: self.repository
        self.client = TestClient(main.app)
        self.addCleanup(main.app.dependency_overrides.clear)
        self.addCleanup(self.client.close)

    def test_complete_contract_and_one_loaded_history(self):
        with patch.object(main, "build_analysis_foundation", wraps=build_analysis_foundation) as build:
            response = self.client.get(PATH)
        self.assertEqual(response.status_code, 200)
        self.repository.load_analysis_draws.assert_called_once_with(
            cutoff_date=None, cutoff_draw=None, include_cutoff_draw=True)
        build.assert_called_once()
        self.assertIsInstance(build.call_args.args[0], repo.AnalysisSnapshot)
        data = response.json()
        self.assertEqual(set(data), {"metadata", "numbers"})
        meta = data["metadata"]
        self.assertEqual(meta, {
            "schema_version": "1.0.0", "engine_version": "1.0.0",
            "formula_version": "marksix-v7-foundation-1", "game": "marksix",
            "include_special": False, "theoretical_probability": 6/49,
            "analysis_start_date": "2020-01-01", "available_draw_count": 103,
            "cutoff_draw": self.h.draws[-1].draw, "cutoff_date": self.h.draws[-1].date.isoformat(),
            "previous_cutoff_draw": self.h.draws[-2].draw,
            "previous_cutoff_date": self.h.draws[-2].date.isoformat(),
        })
        expected = build_analysis_foundation(self.h)
        self.assertEqual([r["number"] for r in data["numbers"]], list(range(1, 50)))
        for actual, row in zip(data["numbers"], expected.current.numbers):
            self.assertEqual(actual, {
                "number": row.number,
                "momentum": {str(w): getattr(row, f"r{w}") for w in (10,30,50,100)},
                "score": row.score, "grade": row.grade, "frozen_score": row.frozen_score,
                "momentum_type": row.momentum_type, "reasons": list(row.reasons), "warnings": list(row.warnings),
            })
        self.assertNotEqual(expected.current.cutoff_draw, expected.previous.cutoff_draw)

    def test_one_connection_one_select_real_repository_path(self):
        main.app.dependency_overrides.clear()
        with patch.object(repo, "connect_database") as connect:
            cursor = connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
            cursor.fetchall.return_value = [db_row(d) for d in history(101)]
            response = self.client.get(PATH)
            self.assertEqual(response.status_code, 200)
            connect.assert_called_once_with()
            cursor.execute.assert_called_once()
            self.assertIn("draw_date >= %s", cursor.execute.call_args.args[0])
            self.assertEqual(cursor.execute.call_args.args[1], (date(2020,1,1),))

    def test_requested_cutoffs_inclusive_exclusive_and_date(self):
        target = history(103)[101]
        for inclusive, count, end in ((True,102,101), (False,101,100)):
            response = self.client.get(PATH, params={"cutoff_draw":target["draw"], "include_cutoff_draw":str(inclusive).lower()})
            self.assertEqual(response.status_code,200)
            meta=response.json()["metadata"]
            self.assertEqual(meta["available_draw_count"],count)
            self.assertEqual(meta["cutoff_draw"],history(103)[end]["draw"])
            self.assertEqual(meta["previous_cutoff_draw"],history(103)[end-1]["draw"])
        response=self.client.get(PATH,params={"cutoff_date":target["date"]})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()["metadata"]["cutoff_date"],target["date"])

    def test_invalid_cutoffs_rejected_without_db(self):
        for params in ({"cutoff_draw":"bad"},{"cutoff_draw":"20/000"},
                       {"cutoff_date":"1993-01-01"},{"cutoff_date":"2020-02-30"},
                       {"include_cutoff_draw":"false"},{"include_cutoff_draw":"invalid"}):
            with self.subTest(params=params):
                self.repository.reset_mock()
                self.assertEqual(self.client.get(PATH,params=params).status_code,422)
                self.repository.load_analysis_draws.assert_not_called()

    def test_missing_cutoff_rejected_and_no_eligible_data(self):
        self.assertEqual(self.client.get(PATH,params={"cutoff_draw":"20/999"}).status_code,422)
        self.repository.load_analysis_draws.side_effect=None
        self.repository.load_analysis_draws.return_value=repo.AnalysisSnapshot(())
        self.assertEqual(self.client.get(PATH).status_code,404)

    def test_insufficient_history_and_101_success(self):
        self.repository.load_analysis_draws.side_effect=None
        for size in (1,99,100,101):
            self.repository.load_analysis_draws.return_value=repo.AnalysisSnapshot.from_records(history(size))
            response=self.client.get(PATH)
            if size==101:
                self.assertEqual(response.status_code,200)
            else:
                self.assertEqual(response.status_code,409)
                self.assertEqual(response.json(),{"detail":{
                    "code":"insufficient_analysis_history","analysis_start_date":"2020-01-01",
                    "required_draw_count":101,"actual_draw_count":size}})

    def test_database_and_malformed_history_errors_sanitized(self):
        for exc in (psycopg.OperationalError("PRIVATE DB DETAILS"),
                    DatabaseConfigurationError("PRIVATE DB DETAILS"),
                    repo.AnalysisDataError("PRIVATE DB DETAILS")):
            self.repository.load_analysis_draws.side_effect=exc
            response=self.client.get(PATH)
            self.assertEqual(response.status_code,503)
            self.assertNotIn("PRIVATE",response.text)
        self.repository.load_analysis_draws.side_effect=None
        self.repository.load_analysis_draws.return_value={"malformed":"PRIVATE"}
        response=self.client.get(PATH)
        self.assertEqual(response.status_code,503)
        self.assertNotIn("PRIVATE",response.text)

    def test_real_history_endpoint_matches_static_fixture_without_engine_mock(self):
        # Deterministic history keeps multiples of seven out of the six mains.
        # Number seven can be special, but PRIMARY must still yield zero ratios.
        case = next(c for c in FIXTURES["cases"] if c["ratios"] == [0, 0, 0, 0])
        response = self.client.get(PATH)
        self.assertEqual(response.status_code, 200)
        row = response.json()["numbers"][6]
        self.assertEqual(row["number"], 7)
        self.assertEqual(list(row["momentum"].values()), case["ratios"])
        for key in ("score", "grade", "frozen_score", "momentum_type", "reasons", "warnings"):
            self.assertEqual(row[key], case[key])

    def test_endpoint_serialization_static_cross_language_parity(self):
        # Boundary ratios need not be achievable integer-count windows. Inject a
        # typed foundation to independently exercise wire serialization of them.
        foundation=build_analysis_foundation(self.h)
        for case in FIXTURES["cases"]:
            with self.subTest(case=case["name"]):
                row=AnalysisNumber(1,*case["ratios"],case["score"],case["grade"],
                    case["frozen_score"],case["momentum_type"],tuple(case["reasons"]),tuple(case["warnings"]))
                value=replace(foundation,current=replace(foundation.current,
                    numbers=(row,*foundation.current.numbers[1:])))
                with patch.object(main,"build_analysis_foundation",return_value=value):
                    response=self.client.get(PATH)
                self.assertEqual(response.status_code,200)
                actual=response.json()["numbers"][0]
                for key in ("score","grade","frozen_score","momentum_type","reasons","warnings"):
                    self.assertEqual(actual[key],case[key])
                self.assertEqual(list(actual["momentum"].values()),case["ratios"])

    def test_typed_contract_rejects_invalid_values(self):
        valid=self.client.get(PATH).json()
        mutations=[
            lambda d:d["numbers"].pop(),
            lambda d:d["numbers"].append(d["numbers"][0]),
            lambda d:d["numbers"][0].update(number=2),
            lambda d:d["numbers"].reverse(),
            lambda d:d["numbers"][0]["momentum"].pop("30"),
            lambda d:d["numbers"][0]["momentum"].update({"20":1.0}),
            lambda d:d["numbers"][0].update(score=101),
            lambda d:d["numbers"][0].update(score=-1),
            lambda d:d["numbers"][0].update(grade="Z"),
            lambda d:d["numbers"][0].update(frozen_score=float("inf")),
            lambda d:d["numbers"][0]["momentum"].update({"10":float("nan")}),
            lambda d:d["numbers"][0].update(reasons=[1]),
            lambda d:d["numbers"][0].update(warnings="none"),
            lambda d:d["metadata"].update(include_special=True),
            lambda d:d["metadata"].update(include_special=0),
            lambda d:d["metadata"].update(theoretical_probability=7/49),
            lambda d:d["metadata"].update(cutoff_date="2020-02-30"),
            lambda d:d["metadata"].update(cutoff_draw="21/205"),
            lambda d:d["metadata"].update(previous_cutoff_draw=d["metadata"]["cutoff_draw"],previous_cutoff_date=d["metadata"]["cutoff_date"]),
            lambda d:d["metadata"].update(formula_version="unknown"),
            lambda d:d.update(explosion=[]),
        ]
        for i, mutate in enumerate(mutations):
            with self.subTest(mutation=i):
                value=copy.deepcopy(valid);mutate(value)
                with self.assertRaises(ValidationError):AnalysisResponse.model_validate(value)

    def test_overview_baseline_json_openapi_unchanged(self):
        baseline=json.loads((Path(__file__).parent/"fixtures/overview_contract_baseline.json").read_text())
        response=self.client.get("/api/v1/marksix/overview")
        self.assertEqual(response.status_code,200)
        self.repository.load_analysis_draws.assert_called_once_with()
        self.assertEqual(digest(response.json()),baseline["payload_sha256"])
        spec=self.client.get("/openapi.json").json()
        self.assertEqual(digest(spec["paths"]["/api/v1/marksix/overview"]),baseline["overview_path_sha256"])
        for name, sha in baseline["schemas"].items():
            self.assertEqual(digest(spec["components"]["schemas"][name]),sha,name)
        response_schema=spec["paths"][PATH]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        self.assertEqual(response_schema,{"$ref":"#/components/schemas/AnalysisResponse"})
        self.assertEqual({p["name"] for p in spec["paths"][PATH]["get"]["parameters"]},
                         {"cutoff_date","cutoff_draw","include_cutoff_draw"})
