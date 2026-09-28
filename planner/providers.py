"""Cached, bounded calls to public demo services; no automatic request retries."""

import hashlib
import json
import math
import threading
import time
from contextlib import contextmanager

import requests
from django.conf import settings
from django.core.cache import cache

from planner.errors import PlanningError

_thread_lock = threading.Lock()


@contextmanager
def provider_slot(provider):
    """Keep public-service calls <= 1/second, including separate local workers."""
    import fcntl

    folder = settings.CACHE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    with _thread_lock, (folder / f"{provider}.rate-limit").open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        previous = float(handle.read() or 0)
        time.sleep(max(0, 1.05 - (time.time() - previous)))
        handle.seek(0)
        handle.truncate()
        handle.write(str(time.time()))
        handle.flush()
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def cache_key(prefix, value):
    return prefix + hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class Providers:
    def __init__(self):
        self.routing_calls = 0
        self.geocoding_calls = 0
        self.session = requests.Session()
        self.session.headers["User-Agent"] = settings.UPSTREAM_USER_AGENT

    def _get(self, url, params, provider):
        try:
            with provider_slot(provider):
                if provider == "osrm":
                    self.routing_calls += 1
                else:
                    self.geocoding_calls += 1
                response = self.session.get(url, params=params, timeout=settings.UPSTREAM_TIMEOUT)
            value = response.json()
            if (
                provider == "osrm"
                and response.status_code == 400
                and isinstance(value, dict)
                and value.get("code") in ("NoRoute", "NoSegment")
            ):
                return value
            response.raise_for_status()
            if not isinstance(value, dict):
                raise ValueError("Unexpected response")
            return value
        except (requests.RequestException, ValueError) as exc:
            raise PlanningError(
                f"The {provider} service is temporarily unavailable. Please retry later.",
                code="upstream_unavailable",
                status=502,
            ) from exc

    def geocode(self, query):
        key = cache_key("geocode-v1:", [settings.PHOTON_BASE_URL, query.casefold().strip()])
        if (cached := cache.get(key)) is not None:
            return cached
        result = self._get(
            settings.PHOTON_BASE_URL + "/api/", {"q": query, "limit": 1, "lang": "en"}, "photon"
        )
        try:
            features = result["features"]
            if not features:
                raise PlanningError(
                    f"Could not find '{query}'. Use a city and state, such as Chicago, IL.",
                    code="location_not_found",
                    status=400,
                )
            feature = features[0]
            props = feature["properties"]
            if not isinstance(props, dict) or not isinstance(props.get("countrycode"), str):
                raise ValueError
            if props["countrycode"].upper() != "US":
                raise PlanningError(
                    "Start and finish must both be within the USA.", code="outside_usa", status=400
                )
            lon, lat = feature["geometry"]["coordinates"]
            if not (
                -90 <= lat <= 90
                and -180 <= lon <= 180
                and math.isfinite(lat)
                and math.isfinite(lon)
            ):
                raise ValueError
            location = {
                "name": ", ".join(
                    dict.fromkeys(
                        str(props[k]) for k in ("name", "city", "state", "country") if props.get(k)
                    )
                ),
                "latitude": lat,
                "longitude": lon,
            }
        except (KeyError, TypeError, IndexError, ValueError, OverflowError) as exc:
            raise PlanningError(
                "Geocoder returned an invalid location.",
                code="invalid_upstream_response",
                status=502,
            ) from exc
        cache.set(key, location, settings.GEOCODE_CACHE_SECONDS)
        return location

    def route(self, locations):
        coordinates = [[round(p["longitude"], 6), round(p["latitude"], 6)] for p in locations]
        key = cache_key("route-v2:", [settings.OSRM_BASE_URL, coordinates])
        if (cached := cache.get(key)) is not None:
            return cached
        path = ";".join(f"{lon},{lat}" for lon, lat in coordinates)
        result = self._get(
            settings.OSRM_BASE_URL + "/route/v1/driving/" + path,
            {
                "overview": "full",
                "geometries": "geojson",
                "steps": "false",
                "alternatives": "false",
                "radiuses": ";".join("1000" for _ in locations),
            },
            "osrm",
        )
        if result.get("code") in ("NoRoute", "NoSegment"):
            raise PlanningError("No drivable route was found for these locations.", code="no_route")
        try:
            route = result["routes"][0]
            if result["code"] != "Ok" or route["geometry"]["type"] != "LineString":
                raise ValueError
            points = route["geometry"]["coordinates"]
            valid_points = len(points) >= 2 and all(
                len(p) == 2
                and all(isinstance(v, (int, float)) and math.isfinite(v) for v in p)
                and -180 <= p[0] <= 180
                and -90 <= p[1] <= 90
                for p in points
            )
            valid_metrics = (
                math.isfinite(route["distance"])
                and route["distance"] >= 0
                and math.isfinite(route["duration"])
                and route["duration"] >= 0
            )
            valid_legs = (
                len(route["legs"]) == len(locations) - 1
                and all(
                    math.isfinite(leg["distance"]) and leg["distance"] >= 0 for leg in route["legs"]
                )
                and abs(sum(leg["distance"] for leg in route["legs"]) - route["distance"])
                < max(5, len(locations))
            )
            if not (valid_points and valid_metrics and valid_legs):
                raise ValueError
        except (KeyError, IndexError, TypeError, ValueError, OverflowError) as exc:
            raise PlanningError(
                "Routing provider returned an invalid route.",
                code="invalid_upstream_response",
                status=502,
            ) from exc
        value = {
            "distance_miles": route["distance"] / 1609.344,
            "duration_hours": route["duration"] / 3600,
            "geometry": route["geometry"],
            "leg_miles": [leg["distance"] / 1609.344 for leg in route["legs"]],
        }
        cache.set(key, value, settings.ROUTE_CACHE_SECONDS)
        return value
