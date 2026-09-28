from unittest import TestCase

from scripts.enrich_stations import build_coordinates, website_store_number


class EnrichmentTests(TestCase):
    def row(self, name="LOVES #123", city="Example", state="TX"):
        return {"Truckstop Name": name, "City": city, "State": state}

    def osm(self, *extras):
        points = []
        for i, extra in enumerate(extras):
            tags = {
                "amenity": "fuel",
                "brand": "Love's",
                "name": "Love's",
                "addr:city": "Example",
                "addr:state": "TX",
            }
            tags.update(extra.get("tags", {}))
            points.append(
                {"type": "node", "id": i + 1, "lat": extra.get("lat", 30), "lon": -98, "tags": tags}
            )
        return {"elements": points}

    def test_multiple_assessment_stores_are_ambiguous(self):
        rows = {"1": [self.row()], "2": [self.row("LOVES #124")]}
        self.assertEqual(build_coordinates(rows, [], self.osm({}))[0], {})

    def test_multiple_distinct_osm_sites_are_ambiguous(self):
        self.assertEqual(
            build_coordinates({"1": [self.row()]}, [], self.osm({}, {"lat": 30.1}))[0], {}
        )

    def test_same_site_duplicate_canopies_can_match(self):
        result, _ = build_coordinates({"1": [self.row()]}, [], self.osm({}, {"lat": 30.0001}))
        self.assertEqual(result["1"]["latitude"], 30)

    def test_city_match_cannot_override_different_store_number(self):
        self.assertEqual(
            build_coordinates({"1": [self.row()]}, [], self.osm({"tags": {"ref": "999"}}))[0], {}
        )

    def test_conflicting_osm_references_require_manual_review(self):
        osm = self.osm({"tags": {"ref": "123", "website": "https://www.loves.com/locations/999"}})
        self.assertEqual(build_coordinates({"1": [self.row()]}, [], osm)[0], {})

    def test_official_matches_require_store_city_and_state(self):
        pilot = [
            {
                "store_number": "123",
                "city": "Example",
                "state": "TX",
                "latitude": 30,
                "longitude": -98,
                "source": "https://locations.pilotflyingj.com/example",
            }
        ]
        result, _ = build_coordinates({"1": [self.row("PILOT #123")]}, pilot, {})
        self.assertEqual(result["1"]["latitude"], 30)
        self.assertEqual(
            build_coordinates({"1": [self.row("PILOT #123", state="OK")]}, pilot, {})[0], {}
        )

    def test_missing_poi_is_never_replaced_with_a_city_coordinate(self):
        self.assertEqual(build_coordinates({"1": [self.row()]}, [], {})[0], {})

    def test_website_reference_requires_known_host_and_path(self):
        self.assertEqual(
            website_store_number("LOVES", "https://www.loves.com/locations/0123"), "123"
        )
        self.assertEqual(
            website_store_number("KWIKTRIP", "https://www.kwiktrip.com/locator/store?id=00796"),
            "796",
        )
        self.assertIsNone(website_store_number("LOVES", "https://example.com/locations/123"))
        self.assertIsNone(website_store_number("LOVES", "https://www.loves.com/123-main-street"))
