from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase

from planner.geography import route_candidates


class GeographyTests(SimpleTestCase):
    @patch("planner.geography.station_catalog")
    def test_projects_close_station_and_excludes_far_station(self, catalog):
        catalog.return_value = [
            {"opis_id": 1, "longitude": -97.5, "latitude": 35, "price": Decimal("3")},
            {"opis_id": 2, "longitude": -97.5, "latitude": 36, "price": Decimal("2")},
        ]
        route = {
            "distance_miles": 100,
            "geometry": {"type": "LineString", "coordinates": [[-98, 35], [-97.5, 35], [-97, 35]]},
        }
        candidates, details = route_candidates(route)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].station_id, 1)
        self.assertAlmostEqual(candidates[0].mile, 50, places=3)
        self.assertLess(details[1]["offset_miles"], 0.01)

    @patch("planner.geography.station_catalog", return_value=[])
    def test_no_coordinates_is_an_empty_candidate_set(self, catalog):
        self.assertEqual(route_candidates({"distance_miles": 100}), ([], {}))
