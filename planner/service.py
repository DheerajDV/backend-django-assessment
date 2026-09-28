import time

from planner.errors import PlanningError
from planner.geography import route_candidates, station_catalog
from planner.models import Station
from planner.optimizer import FuelCandidate, OptimizationError, optimize_fuel
from planner.providers import Providers


def build_plan(start_text, finish_text, initial_fuel):
    began = time.perf_counter()
    provider = Providers()
    try:
        start, finish = provider.geocode(start_text), provider.geocode(finish_text)
        base = provider.route([start, finish])
        candidates, details = route_candidates(base)
        try:
            plan = optimize_fuel(
                base["distance_miles"], candidates, initial_fuel_gallons=initial_fuel
            )
        except OptimizationError as exc:
            raise PlanningError(
                "The located stations cannot support this journey within the 500-mile range.",
                code="insufficient_station_coverage",
                details={
                    "reason": str(exc),
                    "candidate_stations": len(candidates),
                    "located_stations": len(station_catalog()),
                    "total_stations": Station.objects.count(),
                },
            ) from exc
        selected = [details[stop["station_id"]] for stop in plan["stops"]]
        actual = base
        if selected:
            if len(selected) > 90:
                raise PlanningError(
                    "This route needs too many waypoints for the demo routing service.",
                    code="too_many_stops",
                )
            actual = provider.route([start, *selected, finish])
            mile = 0.0
            verified = []
            for station, leg in zip(selected, actual["leg_miles"]):
                mile += leg
                verified.append(FuelCandidate(station["opis_id"], mile, station["price"]))
            try:
                plan = optimize_fuel(
                    actual["distance_miles"], verified, initial_fuel_gallons=initial_fuel
                )
            except OptimizationError as exc:
                raise PlanningError(
                    "Station access roads make the selected itinerary exceed the available fuel range. More station coverage is needed for this route.",
                    code="unreachable_fuel_stop",
                    details={"reason": str(exc)},
                ) from exc
        for stop in plan["stops"]:
            station = details[stop["station_id"]]
            stop.update(
                {
                    k: station[k]
                    for k in (
                        "name",
                        "address",
                        "city",
                        "state",
                        "latitude",
                        "longitude",
                        "coordinate_source",
                        "offset_miles",
                    )
                }
            )
        total, located = Station.objects.count(), len(station_catalog())
        warnings = []
        if located < total:
            warnings.append(
                f"Only {located} of {total} US stations have sourced coordinates. Unlocated stations are excluded, so a cheaper station may be missing."
            )
        warnings.append(
            "This estimates fuel purchases on the selected driving itinerary; it does not guarantee the cheapest route across all roads or stations."
        )
        return {
            "start": start,
            "finish": finish,
            "route": {k: actual[k] for k in ("distance_miles", "duration_hours", "geometry")},
            "fuel_plan": plan,
            "metadata": {
                "routing_api_calls": provider.routing_calls,
                "geocoding_api_calls": provider.geocoding_calls,
                "elapsed_ms": round((time.perf_counter() - began) * 1000, 1),
                "candidate_stations": len(candidates),
                "located_stations": located,
                "total_stations": total,
                "routed_station_waypoints": len(selected),
                "assumptions": [
                    "Vehicle efficiency is 10 US miles per US gallon; tank capacity is 50 gallons (500-mile maximum range).",
                    f"Starting fuel is {initial_fuel:g} gallons, already paid for. total_fuel_cost is additional purchases during the journey and excludes the starting fuel.",
                    "Prices are USD per US gallon from the supplied snapshot; duplicate OPIS IDs use the lowest supplied quote, not live prices.",
                    "Candidates are sourced station coordinates within one mile of the initial route; all selected stops are routed as waypoints and fuel is recalculated using those road distances.",
                    "Fuel purchasing is minimum-cost for the final ordered station itinerary. Candidate selection uses projected base-route distance and does not exhaustively optimize detours.",
                    "Map pins use sourced station coordinates. Routing snaps waypoints to roads within 1 km; forecourt access and truck-specific road restrictions are not verified.",
                    "OSRM uses a car driving profile. Route endpoints are in the USA; intervening border crossings are not prohibited.",
                ],
                "warnings": warnings,
                "attribution": "Routing: OSRM / FOSSGIS. Map data: OpenStreetMap contributors (ODbL). Geocoding: Photon.",
            },
        }
    finally:
        provider.session.close()
