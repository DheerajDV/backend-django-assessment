"""Local spatial matching: no geocoding or routing calls for station candidates."""

import numpy as np
from django.conf import settings
from django.core.cache import cache
from pyproj import Geod, Transformer
from shapely import LineString, Point, STRtree

from planner.models import Station
from planner.optimizer import FuelCandidate

GEOD = Geod(ellps="WGS84")


def station_catalog():
    result = cache.get("station_catalog_v1")
    if result is None:
        result = list(
            Station.objects.filter(latitude__isnull=False, longitude__isnull=False).values()
        )
        cache.set("station_catalog_v1", result, 3600)
    return result


def route_candidates(route):
    """Project points onto nearby route segments and interpolate road chainage.

    This initial screening estimates position along the base route. Selected stops
    are subsequently routed as real waypoints before any fuel plan is returned.
    """
    catalog = station_catalog()
    if not catalog or route["distance_miles"] <= 0:
        return [], {}
    coords = np.asarray(route["geometry"]["coordinates"], dtype=float)
    # A long GeoJSON segment is linear in longitude/latitude, but a straight
    # chord in a projected CRS may be miles away from that line. Densify sparse
    # geometry before projection. OSRM full geometry usually needs few inserts.
    _, _, raw_lengths = GEOD.inv(coords[:-1, 0], coords[:-1, 1], coords[1:, 0], coords[1:, 1])
    pieces = np.maximum(1, np.ceil(raw_lengths / 1609.344).astype(int))
    if np.any(pieces > 1):
        coords = np.vstack(
            [
                np.linspace(a, b, int(count), endpoint=False)
                for a, b, count in zip(coords[:-1], coords[1:], pieces)
            ]
            + [coords[-1:]]
        )
    center = coords.mean(axis=0)
    projection = Transformer.from_crs(
        "EPSG:4326",
        f"+proj=aeqd +lat_0={center[1]} +lon_0={center[0]} +datum=WGS84 +units=m",
        always_xy=True,
    )
    x, y = projection.transform(coords[:, 0], coords[:, 1])
    xy = np.column_stack((x, y))
    vectors = np.diff(xy, axis=0)
    lengths_squared = np.sum(vectors * vectors, axis=1)
    _, _, geodesic_lengths = GEOD.inv(coords[:-1, 0], coords[:-1, 1], coords[1:, 0], coords[1:, 1])
    cumulative = np.concatenate(([0.0], np.cumsum(geodesic_lengths)))
    if cumulative[-1] == 0:
        return [], {}
    segments = [LineString([a, b]) for a, b in zip(xy[:-1], xy[1:])]
    tree = STRtree(segments)
    station_xy = np.column_stack(
        projection.transform([s["longitude"] for s in catalog], [s["latitude"] for s in catalog])
    )
    points = [Point(p) for p in station_xy]
    # Wider planar search protects against projection distortion; exact geodesic
    # offset below enforces the configured one-mile corridor.
    indices = tree.query_nearest(
        points, max_distance=settings.STATION_CORRIDOR_MILES * 1609.344 * 2, all_matches=False
    )
    candidates, details = [], {}
    for station_index, segment_index in indices.T:
        station = catalog[station_index]
        start = xy[segment_index]
        vector = vectors[segment_index]
        fraction = float(
            np.clip(
                np.dot(station_xy[station_index] - start, vector)
                / max(lengths_squared[segment_index], 1e-12),
                0,
                1,
            )
        )
        foot = coords[segment_index] + fraction * (
            coords[segment_index + 1] - coords[segment_index]
        )
        _, _, offset = GEOD.inv(station["longitude"], station["latitude"], foot[0], foot[1])
        offset_miles = offset / 1609.344
        if offset_miles > settings.STATION_CORRIDOR_MILES:
            continue
        mile = float(
            (cumulative[segment_index] + fraction * geodesic_lengths[segment_index])
            / cumulative[-1]
            * route["distance_miles"]
        )
        sid = station["opis_id"]
        candidates.append(FuelCandidate(sid, mile, station["price"]))
        details[sid] = {**station, "offset_miles": round(offset_miles, 3)}
    return candidates, details
