import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from planner.middleware import RouteRateLimitMiddleware


class DemoRateLimitTests(SimpleTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.settings_override = override_settings(
            CACHE_DIR=Path(folder.name),
            API_RATE_LIMIT_ENABLED=True,
            API_RATE_LIMIT=2,
            API_GLOBAL_RATE_LIMIT=3,
            API_RATE_WINDOW=60,
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.factory = RequestFactory()
        self.middleware = RouteRateLimitMiddleware(lambda request: HttpResponse("ok"))

    def post(self, client="127.0.0.1", **headers):
        return self.middleware(self.factory.post("/api/routes/", REMOTE_ADDR=client, **headers))

    @patch("planner.middleware.time.time", return_value=100)
    def test_client_limit_is_shared_across_middleware_instances(self, clock):
        self.assertEqual(self.post().status_code, 200)
        other_worker = RouteRateLimitMiddleware(lambda request: HttpResponse("ok"))
        self.assertEqual(other_worker(self.factory.post("/api/routes/")).status_code, 200)
        limited = self.post()
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited["Retry-After"], "60")
        self.assertEqual(json.loads(limited.content)["error"]["code"], "rate_limited")

    @patch("planner.middleware.time.time", return_value=100)
    def test_forwarded_headers_cannot_change_the_limiter_identity(self, clock):
        self.post(HTTP_X_FORWARDED_FOR="1.1.1.1")
        self.post(HTTP_X_FORWARDED_FOR="2.2.2.2")
        self.assertEqual(self.post(HTTP_X_FORWARDED_FOR="3.3.3.3").status_code, 429)

    @patch("planner.middleware.time.time", return_value=100)
    def test_global_budget_applies_to_distinct_clients(self, clock):
        for address in ("1", "2", "3"):
            self.assertEqual(self.post(address).status_code, 200)
        self.assertEqual(self.post("4").status_code, 429)

    @patch("planner.middleware.time.time")
    def test_expired_requests_release_capacity(self, clock):
        clock.return_value = 100
        self.post()
        self.post()
        clock.return_value = 160
        self.assertEqual(self.post().status_code, 200)

    @override_settings(API_RATE_LIMIT_ENABLED=False)
    def test_local_disabled_mode_does_not_limit(self):
        for _ in range(4):
            self.assertEqual(self.post().status_code, 200)

    def test_read_only_routes_and_health_remain_available(self):
        for _ in range(5):
            self.assertEqual(self.middleware(self.factory.get("/api/health/")).status_code, 200)
