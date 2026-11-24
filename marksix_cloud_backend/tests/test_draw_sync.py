import os
import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from marksix_cloud_backend.database import connect_database, DrawRepository, store_draw
from marksix_cloud_backend.draw_sync import freshness, HONG_KONG, LOCK, synchronize
from marksix_cloud_backend.main import app


@unittest.skipUnless(os.environ.get("MARKSIX_SYNC_TEST_DSN"), "requires disposable local PostgreSQL")
class DrawSyncDatabaseTest(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "DATABASE_URL": os.environ["MARKSIX_SYNC_TEST_DSN"],
            "MARKSIX_CATCH_UP_TOKEN": "local-test-only",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        with connect_database() as connection:
            connection.execute("TRUNCATE marksix.draws")
            connection.execute("DELETE FROM marksix.draw_sync_state")
            connection.execute("INSERT INTO marksix.draw_sync_state DEFAULT VALUES")
        today = datetime.now(HONG_KONG).date()
        self.first = {"draw": f"{today.year % 100:02d}/001", "date": today.isoformat(),
                      "numbers": [1, 2, 3, 4, 5, 6], "special_number": 7}
        self.second = {**self.first, "draw": f"{today.year % 100:02d}/002"}

    def official(self, *draws):
        return lambda start, end: [
            draw for draw in draws if start.isoformat() <= draw["date"] <= end.isoformat()
        ]

    def release_cooldown(self):
        with connect_database() as connection:
            connection.execute("UPDATE marksix.draw_sync_state SET retry_at=NULL")

    def test_lock_atomic_retry_and_fingerprint(self):
        with connect_database() as connection:
            connection.execute("SELECT pg_advisory_lock(%s)", (LOCK,))
            self.assertEqual(freshness()["status"], "catching_up")
            self.assertEqual(synchronize(fetch=lambda *_: self.fail("unexpected fetch"))[0],
                             "in_progress")
        self.assertEqual(freshness()["status"], "unknown")
        with connect_database() as connection:
            store_draw(connection, self.second)
        conflict = {**self.second, "special_number": 8}
        self.assertEqual(synchronize(fetch=self.official(self.first, conflict))[0], "retry_later")
        self.assertEqual(DrawRepository().recent(10), [self.second])
        self.assertEqual(freshness()["status"], "failed")
        self.assertEqual(synchronize(fetch=lambda *_: self.fail("cooldown bypass"))[0], "cooldown")
        self.release_cooldown()
        self.assertEqual(synchronize(fetch=self.official(self.first, self.second))[0], "completed")
        confirmed = freshness()
        self.assertEqual(confirmed["status"], "up_to_date")
        self.assertEqual(confirmed["sync_revision"], 1)
        self.release_cooldown()
        self.assertEqual(synchronize(fetch=self.official(self.first, self.second))[0], "completed")
        self.assertEqual(DrawRepository().recent(10), [self.second, self.first])
        self.assertEqual(freshness()["source_revision"], confirmed["source_revision"])
        self.assertEqual(freshness()["sync_revision"], 1)

    def test_api_authentication_and_same_snapshot_header(self):
        with TestClient(app) as client, patch(
            "marksix_cloud_backend.main.synchronize",
            side_effect=lambda: synchronize(fetch=self.official(self.first, self.second)),
        ) as update:
            route = "/api/v1/marksix/admin/catch-up"
            self.assertEqual(client.post(route).status_code, 401)
            self.assertEqual(client.post(route, headers={"Authorization": "Bearer wrong"}).status_code, 401)
            update.assert_not_called()
            self.assertEqual(client.post(route, headers={
                "Authorization": "Bearer local-test-only",
            }).status_code, 200)
            fresh = client.get("/api/v1/marksix/freshness")
            self.assertEqual(fresh.headers["cache-control"], "no-store")
            self.assertEqual(fresh.json()["status"], "up_to_date")
            for endpoint in ("latest", "recent-draws"):
                reply = client.get(f"/api/v1/marksix/{endpoint}", params={"consistent": "true"})
                self.assertEqual(reply.status_code, 200)
                self.assertEqual(reply.headers["x-marksix-source-revision"],
                                 fresh.json()["source_revision"])
            missing = client.get("/api/v1/marksix/missing-numbers")
            self.assertEqual(missing.headers["x-marksix-source-revision"],
                             fresh.json()["source_revision"])
