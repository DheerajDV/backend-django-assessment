import csv
import math
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from planner.models import Station

US_STATES = set(
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split()
)
HEADERS = {"OPIS Truckstop ID", "Truckstop Name", "Address", "City", "State", "Retail Price"}


class Command(BaseCommand):
    help = (
        "Import the assessment price snapshot; merge duplicate OPIS IDs and optional coordinates."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_path", nargs="?", default=str(settings.BASE_DIR / "data/fuel-prices.csv")
        )
        parser.add_argument(
            "--coordinates", default=str(settings.BASE_DIR / "data/station_coordinates.csv")
        )

    def handle(self, *args, **options):
        groups = defaultdict(list)
        skipped = 0
        try:
            with open(options["csv_path"], newline="", encoding="utf-8-sig") as handle:
                reader = csv.DictReader(handle)
                if not HEADERS <= set(reader.fieldnames or []):
                    raise CommandError("CSV is missing required assessment columns.")
                for number, row in enumerate(reader, 2):
                    if row["State"].strip().upper() not in US_STATES:
                        skipped += 1
                        continue
                    try:
                        price = Decimal(row["Retail Price"])
                        station_id = int(row["OPIS Truckstop ID"])
                        if not price.is_finite() or not 0 < price < 1000 or station_id <= 0:
                            raise ValueError
                    except (ValueError, InvalidOperation):
                        raise CommandError(
                            f"Invalid station ID or price on row {number}."
                        ) from None
                    groups[station_id].append((price, row))
            coords = {}
            coord_path = Path(options["coordinates"])
            if coord_path.exists():
                with coord_path.open(newline="", encoding="utf-8-sig") as handle:
                    reader = csv.DictReader(handle)
                    if not {"opis_id", "latitude", "longitude", "source"} <= set(
                        reader.fieldnames or []
                    ):
                        raise CommandError(
                            "Coordinate CSV needs opis_id,latitude,longitude,source."
                        )
                    for row in reader:
                        sid = int(row["opis_id"])
                        lat, lon = float(row["latitude"]), float(row["longitude"])
                        if not (
                            math.isfinite(lat)
                            and math.isfinite(lon)
                            and -90 <= lat <= 90
                            and -180 <= lon <= 180
                            and row["source"].strip()
                        ):
                            raise CommandError(f"Invalid coordinate/source for station {sid}.")
                        if sid in coords:
                            raise CommandError(f"Duplicate coordinate for station {sid}.")
                        coords[sid] = (lat, lon, row["source"].strip())
        except (OSError, ValueError, KeyError) as exc:
            raise CommandError(str(exc)) from exc
        if not groups:
            raise CommandError("CSV contains no valid US stations; database left unchanged.")
        objects = []
        for sid, entries in groups.items():
            price, row = min(entries, key=lambda entry: entry[0])
            lat, lon, source = coords.get(sid, (None, None, ""))
            objects.append(
                Station(
                    opis_id=sid,
                    name=row["Truckstop Name"].strip(),
                    address=row["Address"].strip(),
                    city=row["City"].strip(),
                    state=row["State"].strip().upper(),
                    price=price,
                    latitude=lat,
                    longitude=lon,
                    coordinate_source=source,
                    source_rows=len(entries),
                )
            )
        with transaction.atomic():
            Station.objects.all().delete()
            Station.objects.bulk_create(objects, batch_size=500)
        cache.delete("station_catalog_v1")
        located = sum(x.latitude is not None for x in objects)
        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {len(objects)} US stations; {located} located; {skipped} non-US rows excluded. Duplicate prices use the lowest supplied quote."
            )
        )
