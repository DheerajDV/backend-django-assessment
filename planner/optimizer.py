"""Minimum purchase cost for a vehicle following a fixed, one-dimensional route.

Distances and fuel amounts are converted from their decimal string representations
to Decimal before arithmetic. A tolerance of one millionth of a mile accommodates
route projection noise at a reachability boundary. Returned fuel quantities are
floats; prices and monetary amounts are Decimals. Initial fuel is already paid
for, so the objective counts only fuel bought during this journey.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Optional

DISTANCE_TOLERANCE_MILES = Decimal("0.000001")
_CENT = Decimal("0.01")
_ZERO = Decimal("0")


class OptimizationError(ValueError):
    """The route or vehicle inputs are invalid, or the route cannot be driven."""


@dataclass(frozen=True)
class FuelCandidate:
    station_id: int
    mile: float
    price: Decimal


@dataclass(frozen=True)
class _Point:
    station_id: Optional[int]
    mile: Decimal
    price: Decimal


def _number(value, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise OptimizationError(f"{label} must be a finite number.")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise OptimizationError(f"{label} must be a finite number.") from None
    if not result.is_finite():
        raise OptimizationError(f"{label} must be a finite number.")
    return result


def _money(value: Decimal) -> Decimal:
    # Preserve cents even when a valid amount exceeds the usual Decimal precision.
    with localcontext() as context:
        context.prec = max(context.prec, value.adjusted() + 3)
        return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def optimize_fuel(
    total_miles: float,
    candidates: list[FuelCandidate],
    initial_fuel_gallons: float = 50,
    tank_gallons: float = 50,
    mpg: float = 10,
) -> dict:
    """Return a minimum-cost fueling plan for the supplied station order.

    At each station, buy enough to reach the first strictly cheaper reachable
    station. If none exists, fill the tank or buy enough to finish, whichever is
    less. The destination is a virtual zero-price station. A monotonic stack
    finds the next cheaper station in linear time after sorting the candidates.
    Collocated stations use the cheapest price, with station ID breaking ties.

    Each stop's cost is rounded to cents for display. The total is calculated
    from the unrounded purchase costs and rounded once, rather than summing the
    displayed stop costs. All rounding uses ROUND_HALF_UP.

    Raises OptimizationError for invalid input or an unreachable route segment.
    Stations must lie on the route, within the documented distance tolerance.
    """
    with localcontext() as context:
        context.prec = 40
        return _optimize(total_miles, candidates, initial_fuel_gallons, tank_gallons, mpg)


def _optimize(total_miles, candidates, initial_fuel_gallons, tank_gallons, mpg):
    total = _number(total_miles, "total_miles")
    tank = _number(tank_gallons, "tank_gallons")
    efficiency = _number(mpg, "mpg")
    initial = _number(initial_fuel_gallons, "initial_fuel_gallons")
    if total < 0:
        raise OptimizationError("total_miles must be nonnegative.")
    if tank <= 0:
        raise OptimizationError("tank_gallons must be greater than zero.")
    if efficiency <= 0:
        raise OptimizationError("mpg must be greater than zero.")
    if not 0 <= initial <= tank:
        raise OptimizationError("initial_fuel_gallons must be between zero and tank_gallons.")
    if not isinstance(candidates, (list, tuple)):
        raise OptimizationError("candidates must be a list of FuelCandidate values.")

    stations = []
    for candidate in candidates:
        if not isinstance(candidate, FuelCandidate):
            raise OptimizationError("Each candidate must be a FuelCandidate.")
        if isinstance(candidate.station_id, bool) or not isinstance(candidate.station_id, int):
            raise OptimizationError("Every station_id must be an integer.")
        mile = _number(candidate.mile, f"Station {candidate.station_id} mile")
        price = _number(candidate.price, f"Station {candidate.station_id} price")
        if price < 0:
            raise OptimizationError(f"Station {candidate.station_id} price must be nonnegative.")
        if mile < -DISTANCE_TOLERANCE_MILES or mile > total + DISTANCE_TOLERANCE_MILES:
            raise OptimizationError(
                f"Station {candidate.station_id} lies outside the route (mile {mile})."
            )
        mile = min(total, max(_ZERO, mile))
        # Buying at the destination cannot improve the journey's cost.
        if mile < total:
            stations.append(_Point(candidate.station_id, mile, price))

    stations.sort(key=lambda point: (point.mile, point.price, point.station_id))
    points = []
    for station in stations:
        if not points or station.mile != points[-1].mile:
            points.append(station)
    points.append(_Point(None, total, _ZERO))

    next_cheaper = [None] * len(points)
    stack = []
    for index in range(len(points) - 1, -1, -1):
        while stack and points[stack[-1]].price >= points[index].price:
            stack.pop()
        if stack:
            next_cheaper[index] = stack[-1]
        stack.append(index)

    fuel = initial
    position = _ZERO
    previous_id = None
    capacity_miles = tank * efficiency
    fuel_tolerance = DISTANCE_TOLERANCE_MILES / efficiency
    total_cost = _ZERO
    purchased = _ZERO
    stops = []

    for index, point in enumerate(points):
        distance = point.mile - position
        needed = distance / efficiency
        if needed > fuel + fuel_tolerance:
            origin = "the start" if previous_id is None else f"station {previous_id}"
            target = (
                "the destination" if point.station_id is None else f"station {point.station_id}"
            )
            raise OptimizationError(
                f"Cannot reach {target} from {origin}: the next available location "
                f"is {float(distance):.2f} miles away, but the remaining fuel covers "
                f"{float(fuel * efficiency):.2f} miles. Add a reachable station or "
                "increase the available initial fuel/range."
            )
        fuel = max(_ZERO, fuel - needed)
        position = point.mile
        previous_id = point.station_id
        if point.station_id is None:
            break

        desired = min(tank, (total - point.mile) / efficiency)
        cheaper_index = next_cheaper[index]
        if cheaper_index is not None:
            cheaper_distance = points[cheaper_index].mile - point.mile
            if cheaper_distance <= capacity_miles + DISTANCE_TOLERANCE_MILES:
                desired = min(tank, cheaper_distance / efficiency)

        gallons = max(_ZERO, desired - fuel)
        if gallons:
            cost = gallons * point.price
            stops.append(
                {
                    "station_id": point.station_id,
                    "mile": float(point.mile),
                    "gallons": float(gallons),
                    "price_per_gallon": point.price,
                    "cost": _money(cost),
                    "arrival_fuel_gallons": float(fuel),
                    "departure_fuel_gallons": float(fuel + gallons),
                }
            )
            purchased += gallons
            total_cost += cost
            fuel += gallons

    return {
        "stops": stops,
        "total_fuel_cost": _money(total_cost),
        "fuel_purchased_gallons": float(purchased),
        "fuel_consumed_gallons": float(total / efficiency),
        "initial_fuel_gallons": float(initial),
        "remaining_fuel_gallons": float(fuel),
    }
