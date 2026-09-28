import csv
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from planner.models import Station


class ImportTests(TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "prices.csv"
        self.coords = Path(self.folder.name) / "coordinates.csv"

    def write_prices(self, rows):
        with self.path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                ["OPIS Truckstop ID", "Truckstop Name", "Address", "City", "State", "Retail Price"]
            )
            writer.writerows(rows)

    def run_import(self):
        call_command("import_stations", str(self.path), coordinates=str(self.coords), verbosity=0)

    def test_deduplication_us_filter_and_idempotence(self):
        self.write_prices(
            [
                [7, "A", "I-1", "Town", "TX", "3.12345678"],
                [7, "A alias", "I-1", "Town", "TX", "3.01"],
                [8, "Canadian", "Road", "Toronto", "ON", "2.99"],
            ]
        )
        self.coords.write_text(
            "opis_id,latitude,longitude,source\n7,32,-96,https://example.com/station/7\n"
        )
        self.run_import()
        self.run_import()
        self.assertEqual(Station.objects.count(), 1)
        station = Station.objects.get()
        self.assertEqual(str(station.price), "3.01000000")
        self.assertEqual(station.source_rows, 2)
        self.assertEqual(station.latitude, 32)

    def test_bad_input_leaves_existing_catalog_untouched(self):
        self.write_prices([[7, "A", "I-1", "Town", "TX", "3.01"]])
        self.run_import()
        self.write_prices([[9, "Bad", "Road", "Town", "TX", "NaN"]])
        with self.assertRaises(CommandError):
            self.run_import()
        self.assertEqual(list(Station.objects.values_list("opis_id", flat=True)), [7])

    def test_unlocated_station_is_not_assigned_a_city_center(self):
        self.write_prices([[7, "A", "I-1", "Town", "TX", "3.01"]])
        self.run_import()
        self.assertIsNone(Station.objects.get().latitude)
