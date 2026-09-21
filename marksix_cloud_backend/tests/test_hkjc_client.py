import ast
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from marksix_cloud_backend import hkjc_client as client
from marksix_cloud_backend.tests.test_models import sample_draw


def official_row(**changes):
    # Public fields captured by the successful official probe; fixture, not a live assertion.
    value = {"year": "2026", "no": 102, "drawDate": "2026-09-19+08:00", "status": "Result",
             "drawResult": {"drawnNo": [5, 8, 11, 14, 19, 31], "xDrawnNo": 21}}
    value.update(changes)
    return value


class HkjcTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(client.requests, "Session")
        self.factory = patcher.start()
        self.addCleanup(patcher.stop)
        self.session = self.factory.return_value.__enter__.return_value
        self.response = self.session.post.return_value.__enter__.return_value
        self.response.status_code = 200
        self.response.headers = {"Content-Type": "application/json; charset=utf-8"}
        self.response.json.return_value = {"data": {"lotteryDraws": [official_row()]}}

    def test_normalization_of_observed_official_response(self):
        self.assertEqual(client.normalize_draw(official_row()), sample_draw())
        self.assertEqual(client.normalize_draw(official_row(no=99))["draw"], "26/099")

    def test_original_query_fragment_and_headers_unchanged(self):
        source = Path(__file__).resolve().parents[2] / "tests" / "marksix_hkjc_test.py"
        if not source.exists():
            self.skipTest("Original probe is outside a standalone backend checkout")
        assignments = {}
        for node in ast.parse(source.read_text(encoding="utf-8-sig")).body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name in ("PAGE_URL", "ENDPOINT", "TIMEOUT", "QUERY"):
                    assignments[name] = ast.literal_eval(node.value)
                elif name == "HEADERS":
                    # Resolve the one public constant reference, without executing the probe.
                    for value in ast.walk(node.value):
                        if isinstance(value, ast.Name):
                            self.assertEqual(value.id, "PAGE_URL")
                    assignments[name] = eval(compile(ast.Expression(node.value), "<headers>", "eval"),
                                             {"__builtins__": {}, **assignments})
        for name, value in assignments.items():
            self.assertEqual(getattr(client, name), value, name)

    def test_fetch_uses_verified_query_ssl_timeouts_and_no_ambient_auth(self):
        self.assertEqual(client.fetch_recent_draws(5), [sample_draw()])
        self.assertFalse(self.session.trust_env)
        args, kwargs = self.session.post.call_args
        self.assertEqual(args, (client.ENDPOINT,))
        self.assertTrue(kwargs["verify"])
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual(kwargs["timeout"], (10, 30))
        self.assertEqual(kwargs["json"], {
            "operationName": "marksixResult", "query": client.QUERY,
            "variables": {"lastNDraw": 5, "startDate": None, "endDate": None, "drawType": "All"}})
        self.assertFalse({"cookie", "authorization"} & {key.lower() for key in kwargs["headers"]})

    def test_sorts_newest_first(self):
        self.response.json.return_value["data"]["lotteryDraws"].insert(
            0, official_row(no=101, drawDate="2026-09-17+08:00"))
        self.assertEqual([draw["draw"] for draw in client.fetch_recent_draws(2)], ["26/102", "26/101"])

    def test_rejects_bad_limit_before_network(self):
        for value in (0, 201, True, "5", 5.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                client.fetch_recent_draws(value)
        self.factory.assert_not_called()

    def test_whitelist_error_even_with_http_200_and_partial_data(self):
        self.response.json.return_value["errors"] = [{"message": "Internal server error - WHITELIST_ERROR"}]
        with self.assertRaises(client.HkjcError) as caught:
            client.fetch_recent_draws(5)
        self.assertEqual(caught.exception.kind, "graphql")
        self.assertIn("hint", caught.exception.diagnostics)
        self.assertEqual(caught.exception.diagnostics["http_status"], 200)

    def test_graphql_extensions_can_be_nonobject(self):
        self.response.json.return_value = {"errors": [{"message": "bad query", "extensions": "unexpected"}]}
        with self.assertRaises(client.HkjcError) as caught:
            client.fetch_recent_draws(5)
        self.assertEqual(caught.exception.kind, "graphql")

    def test_http_429_reports_status_content_type_and_retry_after(self):
        self.response.status_code = 429
        self.response.headers["Retry-After"] = "60"
        self.response.raise_for_status.side_effect = requests.HTTPError("too many requests")
        self.response.json.return_value = {}
        with self.assertRaises(client.HkjcError) as caught:
            client.fetch_recent_draws(5)
        self.assertEqual(caught.exception.kind, "http")
        self.assertEqual(caught.exception.diagnostics["retry_after"], "60")
        self.assertEqual(caught.exception.diagnostics["http_status"], 429)
        self.session.post.assert_called_once()

    def test_html_error_reports_http_and_json_failure(self):
        self.response.status_code = 503
        self.response.headers["Content-Type"] = "text/html"
        self.response.raise_for_status.side_effect = requests.HTTPError("unavailable")
        self.response.json.side_effect = ValueError("invalid JSON")
        with self.assertRaises(client.HkjcError) as caught:
            client.fetch_recent_draws(5)
        self.assertEqual(caught.exception.kind, "json")
        self.assertEqual(caught.exception.diagnostics["http_status"], 503)
        self.assertEqual(caught.exception.diagnostics["content_type"], "text/html")

    def test_redirect_is_not_success(self):
        self.response.status_code = 302
        with self.assertRaises(client.HkjcError) as caught:
            client.fetch_recent_draws(5)
        self.assertEqual(caught.exception.kind, "http")

    def test_timeout_ssl_and_network_failures_are_distinct(self):
        for error, kind in ((requests.Timeout("timed out"), "timeout"),
                            (requests.exceptions.SSLError("bad certificate"), "ssl"),
                            (requests.ConnectionError("offline"), "network")):
            self.session.post.side_effect = error
            with self.subTest(kind=kind), self.assertRaises(client.HkjcError) as caught:
                client.fetch_recent_draws(5)
            self.assertEqual(caught.exception.kind, kind)

    def test_rejects_unexpected_payloads(self):
        for payload in ([], {}, {"data": None}, {"data": {"lotteryDraws": []}},
                        {"data": {"lotteryDraws": {}}}):
            self.response.json.return_value = payload
            with self.subTest(payload=payload), self.assertRaises(client.HkjcError) as caught:
                client.fetch_recent_draws(5)
            self.assertEqual(caught.exception.kind, "schema")

    def test_invalid_result_and_duplicate_draw_reject_entire_batch(self):
        for rows in ([official_row(), official_row()],
                     [official_row(status="PreResult")],
                     [official_row(drawResult={"drawnNo": [1, 2, 3, 4, 5], "xDrawnNo": 6})]):
            self.response.json.return_value = {"data": {"lotteryDraws": rows}}
            with self.subTest(rows=rows), self.assertRaises(client.HkjcError) as caught:
                client.fetch_recent_draws(5)
            self.assertEqual(caught.exception.kind, "validation")

    def test_bad_source_dates_and_years(self):
        for value in (official_row(year=True), official_row(year="26"),
                      official_row(no=1000), official_row(drawDate="2026-02-30+08:00"),
                      official_row(drawDate="2025-09-19+08:00"),
                      official_row(drawDate="2026-09-19+14:30"),
                      official_row(drawDate="2026-09-19T00:00:00+08:00")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                client.normalize_draw(value)

    def test_diagnostics_redact_secrets(self):
        self.response.json.return_value = {"errors": [{"message": "token=abc password=def Bearer secret"}]}
        with self.assertRaises(client.HkjcError) as caught:
            client.fetch_recent_draws(5)
        message = caught.exception.diagnostics["errors"][0]["message"]
        for secret in ("abc", "def", "Bearer secret"):
            self.assertNotIn(secret, message)
