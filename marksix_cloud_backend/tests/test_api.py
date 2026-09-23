import unittest
from unittest.mock import Mock, patch

import psycopg
from fastapi.testclient import TestClient

from marksix_cloud_backend import main
from marksix_cloud_backend.database import DatabaseConfigurationError, DrawRepository
from marksix_cloud_backend.tests.test_models import sample_draw


class ApiTests(unittest.TestCase):
    def setUp(self):
        # A missed override must fail loudly, never connect to a real database.
        patcher = patch("marksix_cloud_backend.database.connect_database",
                        side_effect=AssertionError("offline tests cannot connect to PostgreSQL"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.repository = Mock(spec=DrawRepository)
        main.app.dependency_overrides[main.get_repository] = lambda: self.repository
        self.addCleanup(main.app.dependency_overrides.clear)
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)

    def test_health_does_not_need_database(self):
        main.app.dependency_overrides.clear()
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "service": "marksix"})

    def test_recent_response_schema_and_default_limit(self):
        draws = [sample_draw(), sample_draw(draw="26/101", date="2026-09-17")]
        self.repository.recent.return_value = draws
        response = self.client.get("/api/v1/marksix/recent-draws")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"draws": draws})
        self.repository.recent.assert_called_once_with(20)

    def test_limit_bounds_and_requested_limit(self):
        self.repository.recent.return_value = []
        for limit in (1, 200):
            response = self.client.get(f"/api/v1/marksix/recent-draws?limit={limit}")
            self.assertEqual(response.status_code, 200)
            self.repository.recent.assert_called_with(limit)
        self.repository.recent.reset_mock()
        for limit in (0, -1, 201, "invalid"):
            with self.subTest(limit=limit):
                self.assertEqual(self.client.get(f"/api/v1/marksix/recent-draws?limit={limit}").status_code, 422)
        self.repository.recent.assert_not_called()

    def test_recent_empty_returns_empty_list(self):
        self.repository.recent.return_value = []
        self.assertEqual(self.client.get("/api/v1/marksix/recent-draws").json(), {"draws": []})

    def test_latest_response_schema(self):
        self.repository.latest.return_value = sample_draw()
        response = self.client.get("/api/v1/marksix/latest")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), sample_draw())

    def test_latest_empty_is_404(self):
        self.repository.latest.return_value = None
        self.assertEqual(self.client.get("/api/v1/marksix/latest").status_code, 404)

    def test_unconfigured_database_is_503(self):
        self.repository.recent.side_effect = DatabaseConfigurationError("not configured")
        self.assertEqual(self.client.get("/api/v1/marksix/recent-draws").status_code, 503)

    def test_database_error_does_not_leak_credentials(self):
        self.repository.latest.side_effect = psycopg.OperationalError("password=private postgres://secret")
        with self.assertLogs(main.logger, level="ERROR") as logs:
            response = self.client.get("/api/v1/marksix/latest")
        self.assertEqual(response.status_code, 503)
        for secret in ("private", "postgres://secret"):
            self.assertNotIn(secret, response.text + "\n".join(logs.output))

    def test_only_raw_draw_and_pure_statistics_endpoints(self):
        paths = set(self.client.get("/openapi.json").json()["paths"])
        self.assertEqual(paths, {"/health", "/api/v1/marksix/recent-draws", "/api/v1/marksix/latest",
                                 "/api/v1/marksix/draw-counts", "/api/v1/marksix/missing-numbers",
                                 "/api/v1/marksix/overview", "/api/v1/marksix/analysis"})

    def test_response_schema_rejects_invalid_repository_data(self):
        self.repository.latest.return_value = sample_draw(numbers=[1, 2, 3, 4, 5])
        with TestClient(main.app, raise_server_exceptions=False) as client:
            response = client.get("/api/v1/marksix/latest")
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('"numbers"', response.text)
