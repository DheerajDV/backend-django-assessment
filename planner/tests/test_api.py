import json
import uuid
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from planner.errors import PlanningError
from planner.models import RoutePlan, Station


class RouteAPITests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Station.objects.create(
            opis_id=1,
            name="Test Fuel",
            address="1 Main Street",
            city="Chicago",
            state="IL",
            price=Decimal("3.125"),
            latitude=41.88,
            longitude=-87.63,
        )

    def setUp(self):
        self.url = reverse("plan-route")
        self.payload = {"start": "Chicago, IL", "finish": "Dallas, TX"}

    def post_json(self, payload):
        return self.client.post(self.url, json.dumps(payload), content_type="application/json")

    @patch("planner.views.build_plan")
    def test_plan_is_persisted_and_retrievable_with_exact_money(self, build):
        build.return_value = {
            "start": {"name": "Chicago, IL"},
            "finish": {"name": "Dallas, TX"},
            "route": {"distance_miles": 400},
            "fuel_plan": {"total_fuel_cost": Decimal("12.34"), "stops": []},
            "metadata": {"routing_api_calls": 1},
        }
        response = self.post_json({"start": "  Chicago, IL ", "finish": " Dallas, TX  "})
        self.assertEqual(response.status_code, 200)
        build.assert_called_once_with("Chicago, IL", "Dallas, TX", 50)
        result = response.json()
        self.assertEqual(result["fuel_plan"]["total_fuel_cost"], "12.34")
        self.assertEqual(result["map_url"], f"http://testserver/routes/{result['id']}/map/")
        saved = RoutePlan.objects.get(id=result["id"])
        self.assertEqual(saved.result, result)
        retrieved = self.client.get(reverse("route-detail", args=[saved.id]))
        self.assertEqual(retrieved.status_code, 200)
        self.assertEqual(retrieved.json(), result)

    @patch("planner.views.build_plan")
    def test_explicit_initial_fuel_is_passed_through(self, build):
        build.return_value = {"fuel_plan": {"total_fuel_cost": Decimal(0)}}
        response = self.post_json({**self.payload, "initial_fuel_gallons": 12.5})
        self.assertEqual(response.status_code, 200)
        build.assert_called_once_with("Chicago, IL", "Dallas, TX", 12.5)

    @patch("planner.views.build_plan")
    def test_invalid_requests_do_not_call_external_planning(self, build):
        values = [
            None,
            [],
            "hello",
            {},
            {"start": "Chicago, IL"},
            {**self.payload, "start": " "},
            {**self.payload, "start": "x" * 201},
            {**self.payload, "finish": 123},
            {**self.payload, "unexpected": "field"},
            *(
                {**self.payload, "initial_fuel_gallons": fuel}
                for fuel in (-1, 50.1, True, None, "25", float("nan"), float("inf"), 10**400)
            ),
        ]
        for payload in values:
            with self.subTest(payload=payload):
                response = self.post_json(payload)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"]["code"], "invalid_request")
        build.assert_not_called()
        self.assertFalse(RoutePlan.objects.exists())

    def test_malformed_json_and_invalid_utf8_are_rejected(self):
        for body in (b"{not-json", b"\xff"):
            with self.subTest(body=body):
                response = self.client.post(self.url, body, content_type="application/json")
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"]["code"], "invalid_json")

    def test_request_size_is_bounded(self):
        response = self.client.post(
            self.url, json.dumps({"start": "x" * 17000}), content_type="application/json"
        )
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"]["code"], "request_too_large")

    def test_http_method_and_content_type_are_checked(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response["Allow"], "POST")
        self.assertEqual(response.json()["error"]["code"], "method_not_allowed")
        response = self.client.post(self.url, self.payload)
        self.assertEqual(response.status_code, 415)
        self.assertEqual(response.json()["error"]["code"], "unsupported_media_type")

    @patch("planner.views.build_plan")
    def test_missing_station_data_is_actionable(self, build):
        Station.objects.all().delete()
        response = self.post_json(self.payload)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "station_data_missing")
        build.assert_not_called()

    @patch("planner.views.build_plan")
    def test_planning_errors_keep_status_code_and_details(self, build):
        build.side_effect = PlanningError(
            "A station cannot be reached.",
            code="unreachable_fuel_stop",
            status=422,
            details={"reason": "510 miles exceeds the 500-mile range"},
        )
        response = self.post_json(self.payload)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "unreachable_fuel_stop")
        self.assertIn("510", response.json()["error"]["details"]["reason"])
        self.assertFalse(RoutePlan.objects.exists())

    def test_unknown_saved_plan_returns_json_404(self):
        response = self.client.get(reverse("route-detail", args=[uuid.uuid4()]))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "not_found")

    def test_health_reports_data_readiness(self):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(response.json()["total_stations"], 1)
        self.assertEqual(response.json()["located_stations"], 1)

    def test_health_is_unavailable_without_a_station_catalog(self):
        Station.objects.all().delete()
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "needs_data")
        self.assertEqual(response.json()["total_stations"], 0)

    def test_health_is_unavailable_without_usable_station_coordinates(self):
        Station.objects.update(latitude=None)
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "needs_data")
        self.assertEqual(response.json()["total_stations"], 1)
        self.assertEqual(response.json()["located_stations"], 0)
