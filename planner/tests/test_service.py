from contextlib import nullcontext
from decimal import Decimal
from unittest.mock import MagicMock, patch

import requests
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from planner.errors import PlanningError
from planner.geography import route_candidates
from planner.models import Station
from planner.optimizer import FuelCandidate
from planner.providers import Providers
from planner.service import build_plan

MEMORY_CACHE = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}


def location(name="City", latitude=35, longitude=-100):
    return {"name": name, "latitude": latitude, "longitude": longitude}


def route(distance, legs=None):
    return {
        "distance_miles": distance,
        "duration_hours": distance / 60,
        "geometry": {"type": "LineString", "coordinates": [[-100, 35], [-90, 35]]},
        "leg_miles": legs or [distance],
    }


def station_detail(sid, price="3", longitude=-95, latitude=35):
    return {
        "opis_id": sid,
        "name": f"Station {sid}",
        "address": f"{sid} Test Street",
        "city": "City",
        "state": "TX",
        "price": Decimal(price),
        "longitude": longitude,
        "latitude": latitude,
        "coordinate_source": "test fixture",
        "offset_miles": 0.1,
    }


@override_settings(CACHES=MEMORY_CACHE)
class PlanningServiceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.details = {1: station_detail(1, "4"), 2: station_detail(2, "2")}
        for detail in self.details.values():
            Station.objects.create(**{k: v for k, v in detail.items() if k != "offset_miles"})
        self.start, self.finish = location("Start"), location("Finish", longitude=-90)
        self.provider = MagicMock()
        self.provider.geocode.side_effect = [self.start, self.finish]
        self.provider.routing_calls = 2
        self.provider.geocoding_calls = 2
        self.provider_patch = patch("planner.service.Providers", return_value=self.provider)
        self.provider_patch.start()
        self.addCleanup(self.provider_patch.stop)

    def test_recomputes_purchases_using_actual_road_legs_in_two_route_calls(self):
        self.provider.route.side_effect = [route(1000), route(1010, [405, 205, 400])]
        candidates = [FuelCandidate(1, 400, Decimal(4)), FuelCandidate(2, 600, Decimal(2))]
        with patch("planner.service.route_candidates", return_value=(candidates, self.details)):
            result = build_plan("Start", "Finish", 50)
        self.assertEqual(self.provider.route.call_count, 2)
        self.assertEqual(self.provider.route.call_args_list[0].args[0], [self.start, self.finish])
        self.assertEqual(
            self.provider.route.call_args_list[1].args[0],
            [self.start, self.details[1], self.details[2], self.finish],
        )
        self.assertEqual(result["route"]["distance_miles"], 1010)
        plan = result["fuel_plan"]
        self.assertEqual(plan["total_fuel_cost"], Decimal("124.00"))
        self.assertEqual(plan["fuel_purchased_gallons"], 51)
        self.assertEqual(plan["fuel_consumed_gallons"], 101)
        self.assertEqual(plan["remaining_fuel_gallons"], 0)
        self.assertEqual([stop["mile"] for stop in plan["stops"]], [405, 610])
        for stop in plan["stops"]:
            self.assertGreaterEqual(stop["arrival_fuel_gallons"], 0)
            self.assertLessEqual(stop["departure_fuel_gallons"], 50)
            self.assertIn("coordinate_source", stop)
        self.assertEqual(result["metadata"]["routing_api_calls"], 2)
        self.assertEqual(result["metadata"]["routed_station_waypoints"], 2)
        self.provider.session.close.assert_called_once()

    def test_short_trip_requires_only_one_route_call(self):
        self.provider.route.return_value = route(400)
        self.provider.routing_calls = 1
        with patch("planner.service.route_candidates", return_value=([], {})):
            result = build_plan("Start", "Finish", 50)
        self.assertEqual(self.provider.route.call_count, 1)
        self.assertEqual(result["fuel_plan"]["stops"], [])
        self.assertEqual(result["fuel_plan"]["total_fuel_cost"], Decimal("0.00"))
        self.assertEqual(result["fuel_plan"]["remaining_fuel_gallons"], 10)
        self.assertEqual(result["metadata"]["routing_api_calls"], 1)

    def test_detour_that_breaks_initial_range_returns_error_not_unsafe_plan(self):
        self.provider.route.side_effect = [route(1000), route(1110, [510, 200, 400])]
        candidates = [FuelCandidate(1, 400, Decimal(4)), FuelCandidate(2, 600, Decimal(2))]
        with patch("planner.service.route_candidates", return_value=(candidates, self.details)):
            with self.assertRaises(PlanningError) as caught:
                build_plan("Start", "Finish", 50)
        self.assertEqual(caught.exception.code, "unreachable_fuel_stop")
        self.assertIn("510.00 miles", caught.exception.details["reason"])
        self.assertEqual(self.provider.route.call_count, 2)
        self.provider.session.close.assert_called_once()

    def test_missing_station_coverage_stops_before_second_route_call(self):
        self.provider.route.return_value = route(800)
        with patch("planner.service.route_candidates", return_value=([], {})):
            with self.assertRaises(PlanningError) as caught:
                build_plan("Start", "Finish", 50)
        self.assertEqual(caught.exception.code, "insufficient_station_coverage")
        self.assertEqual(caught.exception.details["candidate_stations"], 0)
        self.assertEqual(caught.exception.details["located_stations"], 2)
        self.assertEqual(self.provider.route.call_count, 1)
        self.provider.session.close.assert_called_once()

    def test_waypoint_count_is_bounded_before_upstream_request(self):
        self.provider.route.return_value = route(10000)
        details = {sid: station_detail(sid) for sid in range(1, 92)}
        selected_plan = {"stops": [{"station_id": sid} for sid in details]}
        with (
            patch("planner.service.route_candidates", return_value=([], details)),
            patch("planner.service.optimize_fuel", return_value=selected_plan),
            self.assertRaises(PlanningError) as caught,
        ):
            build_plan("Start", "Finish", 50)
        self.assertEqual(caught.exception.code, "too_many_stops")
        self.assertEqual(self.provider.route.call_count, 1)

    def test_provider_failure_closes_session_and_keeps_actionable_error(self):
        self.provider.geocode.side_effect = PlanningError(
            "Provider unavailable", code="upstream_unavailable", status=502
        )
        with self.assertRaises(PlanningError) as caught:
            build_plan("Start", "Finish", 50)
        self.assertEqual(caught.exception.status, 502)
        self.provider.route.assert_not_called()
        self.provider.session.close.assert_called_once()


@override_settings(CACHES=MEMORY_CACHE)
class ProviderTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.provider = Providers()
        self.addCleanup(self.provider.session.close)
        self.slot = patch("planner.providers.provider_slot", side_effect=lambda _: nullcontext())
        self.slot.start()
        self.addCleanup(self.slot.stop)
        self.get = patch.object(self.provider.session, "get")
        self.mock_get = self.get.start()
        self.addCleanup(self.get.stop)

    def response(self, payload, status=200):
        response = MagicMock()
        response.status_code = status
        response.json.return_value = payload
        if status >= 400:
            response.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status}")
        self.mock_get.return_value = response

    def geocode_response(self, props=None):
        return {
            "features": [
                {
                    "properties": props
                    if props is not None
                    else {
                        "countrycode": "US",
                        "name": "Chicago",
                        "state": "Illinois",
                        "country": "USA",
                    },
                    "geometry": {"coordinates": [-87.63, 41.88]},
                }
            ]
        }

    def route_response(self):
        return {
            "code": "Ok",
            "routes": [
                {
                    "distance": 160934.4,
                    "duration": 7200,
                    "geometry": {"type": "LineString", "coordinates": [[-100, 35], [-90, 35]]},
                    "legs": [{"distance": 160934.4}],
                }
            ],
        }

    def test_geocoding_cache_avoids_repeated_calls(self):
        self.response(self.geocode_response())
        first = self.provider.geocode("Chicago, IL")
        second = self.provider.geocode(" chicago, il ")
        self.assertEqual(first, second)
        self.assertEqual(first["latitude"], 41.88)
        self.mock_get.assert_called_once()
        self.assertEqual(self.provider.geocoding_calls, 1)
        self.assertEqual(self.provider.routing_calls, 0)

    def test_route_cache_avoids_repeated_calls_and_uses_bounded_request(self):
        self.response(self.route_response())
        locations = [location(), location(longitude=-90)]
        first = self.provider.route(locations)
        second = self.provider.route(locations)
        self.assertEqual(first, second)
        self.assertAlmostEqual(first["distance_miles"], 100)
        self.assertEqual(first["duration_hours"], 2)
        self.mock_get.assert_called_once()
        self.assertEqual(self.provider.routing_calls, 1)
        self.assertEqual(self.mock_get.call_args.kwargs["params"]["alternatives"], "false")
        self.assertEqual(self.mock_get.call_args.kwargs["params"]["radiuses"], "1000;1000")
        self.assertIn("timeout", self.mock_get.call_args.kwargs)

    def test_timeout_is_reported_without_automatic_retry(self):
        self.mock_get.side_effect = requests.Timeout("timed out")
        with self.assertRaises(PlanningError) as caught:
            self.provider.geocode("Chicago, IL")
        self.assertEqual(caught.exception.code, "upstream_unavailable")
        self.assertEqual(caught.exception.status, 502)
        self.mock_get.assert_called_once()

    def test_non_us_location_is_rejected(self):
        self.response(self.geocode_response({"countrycode": "CA", "name": "Toronto"}))
        with self.assertRaises(PlanningError) as caught:
            self.provider.geocode("Toronto")
        self.assertEqual(caught.exception.code, "outside_usa")
        self.assertEqual(caught.exception.status, 400)

    def test_unknown_location_is_reported(self):
        self.response({"features": []})
        with self.assertRaises(PlanningError) as caught:
            self.provider.geocode("Missing Place")
        self.assertEqual(caught.exception.code, "location_not_found")

    def test_malformed_geocoder_properties_are_reported_as_upstream_errors(self):
        for properties in (None, {"countrycode": 123}):
            with self.subTest(properties=properties):
                payload = self.geocode_response()
                payload["features"][0]["properties"] = properties
                self.response(payload)
                with self.assertRaises(PlanningError) as caught:
                    self.provider.geocode("Bad Location")
                self.assertEqual(caught.exception.code, "invalid_upstream_response")
                self.assertEqual(caught.exception.status, 502)

    def test_missing_driving_route_is_reported(self):
        self.response({"code": "NoRoute"})
        with self.assertRaises(PlanningError) as caught:
            self.provider.route([location(), location(longitude=-90)])
        self.assertEqual(caught.exception.code, "no_route")

    def test_http_400_no_route_or_segment_is_a_route_error(self):
        for code in ("NoRoute", "NoSegment"):
            with self.subTest(code=code):
                self.response({"code": code}, status=400)
                with self.assertRaises(PlanningError) as caught:
                    self.provider.route([location(), location(longitude=-90)])
                self.assertEqual(caught.exception.code, "no_route")
                self.assertEqual(caught.exception.status, 422)

    def test_http_503_remains_an_upstream_failure(self):
        self.response({"code": "ServiceUnavailable"}, status=503)
        with self.assertRaises(PlanningError) as caught:
            self.provider.route([location(), location(longitude=-90)])
        self.assertEqual(caught.exception.code, "upstream_unavailable")
        self.assertEqual(caught.exception.status, 502)
        self.mock_get.assert_called_once()

    def test_invalid_road_distance_and_leg_totals_are_rejected(self):
        for invalid_distance in (float("nan"), -1, 1):
            with self.subTest(distance=invalid_distance):
                payload = self.route_response()
                payload["routes"][0]["distance"] = invalid_distance
                self.response(payload)
                with self.assertRaises(PlanningError) as caught:
                    self.provider.route([location(), location(longitude=-90)])
                self.assertEqual(caught.exception.code, "invalid_upstream_response")
                self.assertEqual(caught.exception.status, 502)


class GeographicMatchingTests(SimpleTestCase):
    def test_projects_nearby_stations_and_excludes_distant_stations(self):
        catalog = [
            station_detail(1, longitude=-97.5),
            station_detail(2, longitude=-95, latitude=36),
        ]
        geometries = {
            "sparse": [[-100, 35], [-90, 35]],
            "sampled": [[-100 + i * 0.5, 35] for i in range(21)],
        }
        for name, coordinates in geometries.items():
            with self.subTest(geometry=name):
                driving_route = route(500)
                driving_route["geometry"]["coordinates"] = coordinates
                with patch("planner.geography.station_catalog", return_value=catalog):
                    candidates, details = route_candidates(driving_route)
                self.assertEqual([candidate.station_id for candidate in candidates], [1])
                self.assertAlmostEqual(candidates[0].mile, 125, delta=1)
                self.assertLessEqual(details[1]["offset_miles"], 1)
                self.assertEqual(candidates[0].price, Decimal(3))

    def test_zero_length_route_has_no_candidates(self):
        with patch("planner.geography.station_catalog", return_value=[station_detail(1)]):
            self.assertEqual(route_candidates(route(0)), ([], {}))
