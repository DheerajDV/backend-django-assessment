#!/usr/bin/env python3
"""Build a reviewable station-coordinate CSV from exact, conservative POI matches.

This is an offline preparation tool, never part of a route request. Network calls
are opt-in. Unmatched records remain unmatched; no city-centre substitution occurs.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
US_STATES = set(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split()
)
PILOT_URL = "https://locations.pilotflyingj.com/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "DjangoFuelAssessment/1.0 (one-time station data preparation)"


def normalize(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def city_key(value: str) -> str:
    value = re.sub(r"\bFT\.?\s+", "FORT ", value.upper())
    value = re.sub(r"\bST\.?\s+", "SAINT ", value)
    return normalize(value)


def store_number(value: str) -> str | None:
    match = re.search(r"#\s*0*(\d+)", value)
    return str(int(match.group(1))) if match else None


def brand_key(value: str) -> str:
    name = normalize(value)
    if name.startswith("PETROCANADA"):
        return ""
    # Known aliases only: this is not fuzzy matching across unrelated brands.
    for text, key in (
        ("LOVES", "LOVES"),
        ("PILOT", "PILOT"),
        ("FLYINGJ", "FLYINGJ"),
        ("TRAVELCENTERSOFAMERICA", "TA"),
        ("TATRAVEL", "TA"),
        ("PETRO", "PETRO"),
        ("KWIKTRIP", "KWIKTRIP"),
        ("KWIKSTAR", "KWIKSTAR"),
        ("CASEYS", "CASEYS"),
        ("ROADRANGER", "ROADRANGER"),
        ("CIRCLEK", "CIRCLEK"),
        ("SPEEDWAY", "SPEEDWAY"),
        ("7ELEVEN", "7ELEVEN"),
        ("QUIKTRIP", "QUIKTRIP"),
    ):
        if name.startswith(text):
            return key
    if re.match(r"^TA(?:\s|#|$)", value.upper()):
        return "TA"
    return ""


def website_store_number(brand: str, website: str) -> str | None:
    """Read store references only from known official URL structures."""
    parsed = urllib.parse.urlparse(website)
    host = (parsed.hostname or "").removeprefix("www.")
    match = None
    if brand == "LOVES" and host == "loves.com":
        match = re.fullmatch(r"/locations/(\d+)/?", parsed.path)
    elif (
        brand in {"KWIKTRIP", "KWIKSTAR"}
        and host == "kwiktrip.com"
        and parsed.path.rstrip("/") == "/locator/store"
    ):
        number = urllib.parse.parse_qs(parsed.query).get("id", [""])[0]
        return str(int(number)) if number.isdigit() else None
    elif brand == "CASEYS" and host == "caseys.com":
        match = re.fullmatch(r"/general-store/[^/]+/[^/]+/(\d+)/?", parsed.path)
    elif brand in {"PILOT", "FLYINGJ"} and host == "pilotflyingj.com":
        match = re.fullmatch(r"/stores/(\d+)/?", parsed.path)
    return str(int(match.group(1))) if match else None


def get_json(url: str, timeout: int = 45):
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def download_pilot(path: Path) -> list[dict]:
    """Use the public locator's own 50-result pagination, caching compact facts."""
    stations = []
    offset, count = 0, 1
    while offset < count:
        url = (
            PILOT_URL + "?" + urllib.parse.urlencode({"country": "US", "per": 50, "offset": offset})
        )
        data = get_json(url)["response"]
        count = data["count"]
        entities = data["entities"]
        if not entities:
            raise RuntimeError(f"Pilot locator returned no records at offset {offset} of {count}")
        for entity in entities:
            profile = entity["profile"]
            address = profile["address"]
            # These refer to the actual site. Explicitly never use cityCoordinate.
            coordinate = (
                profile.get("routableCoordinate")
                or profile.get("geocodedCoordinate")
                or profile.get("displayCoordinate")
            )
            number = profile.get("c_externalStoreNumber") or profile.get("c_siteID")
            if coordinate and number:
                stations.append(
                    {
                        "store_number": str(number),
                        "name": profile.get("c_pagesName", profile["name"]),
                        "city": address["city"],
                        "state": address["region"],
                        "latitude": coordinate["lat"],
                        "longitude": coordinate["long"],
                        "source": profile.get("landingPageUrl") or profile["websiteUrl"],
                    }
                )
        offset += len(entities)
        print(f"Pilot locator: {offset}/{count}", flush=True)
        if offset < count:
            time.sleep(0.4)
    path.write_text(json.dumps({"source": PILOT_URL, "stations": stations}, indent=2) + "\n")
    return stations


def compact_osm(data: dict) -> dict:
    keep_tags = {
        "amenity",
        "brand",
        "name",
        "alt_name",
        "ref",
        "addr:city",
        "addr:state",
        "website",
    }
    elements = []
    for item in data.get("elements", []):
        compact = {key: item[key] for key in ("type", "id", "lat", "lon", "center") if key in item}
        compact["tags"] = {
            key: value for key, value in item.get("tags", {}).items() if key in keep_tags
        }
        elements.append(compact)
    return {"osm3s": data.get("osm3s", {}), "elements": elements}


def download_osm(path: Path) -> dict:
    # A small, bounded chain extract; full nationwide amenity=fuel queries can
    # exceed the public service's timeout. Larger local extracts may be supplied.
    query = '[out:json][timeout:90];nwr["amenity"="fuel"]["brand"~"Love|Pilot|Flying J|TravelCenters|Petro|Casey|Kwik|Road Ranger|QuikTrip",i](24,-125,50,-66);out center tags;'
    data = get_json(OVERPASS_URL + "?" + urllib.parse.urlencode({"data": query}), timeout=110)
    if data.get("remark"):
        raise RuntimeError("Overpass returned an incomplete extract: " + data["remark"])
    data = compact_osm(data)
    path.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    return data


def distance_miles(a, b):
    lat1, lon1, lat2, lon2 = map(
        math.radians, (a["latitude"], a["longitude"], b["latitude"], b["longitude"])
    )
    hav = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 3958.7613 * 2 * math.asin(min(1, math.sqrt(hav)))


def one_site(candidates: list[dict]) -> dict | None:
    """Accept duplicate pump/canopy POIs only when all lie on the same small site."""
    if not candidates:
        return None
    if any(distance_miles(a, b) > 0.15 for a in candidates for b in candidates):
        return None
    return candidates[0]


def load_stations(path: Path):
    by_id = defaultdict(list)
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row["State"] in US_STATES:
                by_id[row["OPIS Truckstop ID"]].append(row)
    return by_id


def build_coordinates(rows_by_id, pilot_stations, osm):
    results, methods = {}, Counter()
    by_pilot = defaultdict(list)
    for item in pilot_stations:
        if str(item["store_number"]).isdigit():
            by_pilot[
                (str(int(item["store_number"])), item["state"], city_key(item["city"]))
            ].append(item)

    # Refuse same-brand city matching when the assessment has multiple stores.
    assessment_groups = defaultdict(set)
    assessment_names = defaultdict(set)
    for opis_id, rows in rows_by_id.items():
        for row in rows:
            brand = brand_key(row["Truckstop Name"])
            key = (city_key(row["City"]), row["State"])
            if brand:
                assessment_groups[(brand,) + key].add(opis_id)
            assessment_names[(normalize(row["Truckstop Name"]),) + key].add(opis_id)

    by_ref, by_brand_city, by_name_city = defaultdict(list), defaultdict(list), defaultdict(list)
    for item in osm.get("elements", []):
        tags = item.get("tags", {})
        point = item if "lat" in item else item.get("center", {})
        if not point or tags.get("amenity") != "fuel":
            continue
        candidate = {
            "latitude": point["lat"],
            "longitude": point["lon"],
            "source": f"https://www.openstreetmap.org/{item['type']}/{item['id']}",
            "state": tags.get("addr:state", ""),
            "city": city_key(tags.get("addr:city", "")),
        }
        brand = brand_key(tags.get("brand", "")) or brand_key(tags.get("name", ""))
        ref = tags.get("ref", "")
        references = {
            value
            for value in (
                str(int(ref)) if ref.isdigit() else None,
                store_number(tags.get("name", "")),
                website_store_number(brand, tags.get("website", "")),
            )
            if value is not None
        }
        # Conflicting source references require manual review.
        if len(references) > 1:
            continue
        number = next(iter(references), None)
        candidate["store_number"] = number
        if brand and number:
            by_ref[(brand, number)].append(candidate)
        if candidate["city"] and candidate["state"]:
            key = (candidate["city"], candidate["state"])
            if brand:
                by_brand_city[(brand,) + key].append(candidate)
            for name in (tags.get("name", ""), tags.get("alt_name", "")):
                if name:
                    by_name_city[(normalize(name),) + key].append(candidate)

    for opis_id, rows in rows_by_id.items():
        for row in rows:
            name, state, city = row["Truckstop Name"], row["State"], city_key(row["City"])
            number, brand = store_number(name), brand_key(name)
            match, method = None, None
            if number and brand in {"PILOT", "FLYINGJ"}:
                match = one_site(by_pilot[(number, state, city)])
                if match:
                    method = "official_pilot_store_number_city_state"
            if match is None and brand and number:
                candidates = [
                    p
                    for p in by_ref[(brand, number)]
                    if (not p["state"] or p["state"] == state)
                    and (not p["city"] or p["city"] == city)
                ]
                match = one_site(candidates)
                if match:
                    method = "osm_brand_store_reference"
            name_key = (normalize(name), city, state)
            if match is None and len(assessment_names[name_key]) == 1:
                match = one_site(by_name_city[name_key])
                if match:
                    method = "osm_exact_name_city_state"
            brand_city_key = (brand, city, state)
            if match is None and brand and len(assessment_groups[brand_city_key]) == 1:
                candidates = by_brand_city[brand_city_key]
                # A city match must not override explicit evidence of another store.
                if not any(
                    number and p["store_number"] and number != p["store_number"] for p in candidates
                ):
                    match = one_site(candidates)
                if match:
                    method = "osm_unique_brand_city_state"
            if match:
                results[opis_id] = {
                    "opis_id": opis_id,
                    "latitude": match["latitude"],
                    "longitude": match["longitude"],
                    "source": match["source"],
                }
                methods[method] += 1
                break
    return results, methods


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=ROOT / "data/fuel-prices.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "data/station_coordinates.csv")
    parser.add_argument("--pilot", type=Path, default=ROOT / "data/pilot-stations.json")
    parser.add_argument("--osm", type=Path, default=ROOT / "data/coordinate-pois.json")
    parser.add_argument(
        "--download-pilot",
        action="store_true",
        help="Refresh official Pilot locator snapshot (17 sequential calls for current US network)",
    )
    parser.add_argument(
        "--download-osm", action="store_true", help="Refresh bounded OSM chain snapshot (one query)"
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pilot = (
        download_pilot(args.pilot)
        if args.download_pilot
        else json.loads(args.pilot.read_text()).get("stations", [])
        if args.pilot.exists()
        else []
    )
    osm = (
        download_osm(args.osm)
        if args.download_osm
        else json.loads(args.osm.read_text())
        if args.osm.exists()
        else {}
    )
    if not pilot and not osm:
        parser.error(
            "No source snapshots available. Supply --pilot/--osm or enable a download flag."
        )
    if osm.get("remark"):
        parser.error("Refusing an incomplete OSM extract with a runtime error.")
    rows_by_id = load_stations(args.csv)
    results, methods = build_coordinates(rows_by_id, pilot, osm)
    with args.output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["opis_id", "latitude", "longitude", "source"])
        writer.writeheader()
        for opis_id in sorted(results, key=int):
            writer.writerow(results[opis_id])
    print(
        json.dumps(
            {
                "us_unique_stations": len(rows_by_id),
                "matched": len(results),
                "unresolved": len(rows_by_id) - len(results),
                "methods": methods,
                "output": str(args.output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
