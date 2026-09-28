"""Fuel-planning invariants and an independent discrete dynamic-programming oracle."""

import random
import unittest
from decimal import Decimal

from planner.optimizer import FuelCandidate, OptimizationError, optimize_fuel


def station(station_id, mile, price):
    return FuelCandidate(station_id, mile, Decimal(str(price)))


def discrete_optimum(length, stations, capacity, initial):
    """Enumerate every integer purchase, then drive one mile, using one gallon.

    Integer distances/capacities have an integer optimal solution for this linear
    purchase-cost problem. This oracle does not use the next-cheaper greedy rule.
    """
    prices = {}
    for candidate in stations:
        prices[candidate.mile] = min(prices.get(candidate.mile, candidate.price), candidate.price)
    states = {initial: Decimal(0)}
    for mile in range(length):
        next_states = {}
        for fuel, cost in states.items():
            purchases = range(capacity - fuel + 1) if mile in prices else (0,)
            for purchase in purchases:
                departure = fuel + purchase
                if departure == 0:
                    continue
                resulting = departure - 1
                expense = cost + purchase * prices.get(mile, Decimal(0))
                next_states[resulting] = min(next_states.get(resulting, expense), expense)
        states = next_states
    return min(states.values()) if states else None


class FuelOptimizerTests(unittest.TestCase):
    def assert_physical_plan(self, result, total, initial, capacity, mpg):
        fuel = initial
        position = 0
        for stop in result["stops"]:
            fuel -= (stop["mile"] - position) / mpg
            self.assertGreaterEqual(fuel, -1e-7)
            self.assertAlmostEqual(stop["arrival_fuel_gallons"], fuel)
            self.assertGreater(stop["gallons"], 0)
            fuel += stop["gallons"]
            self.assertLessEqual(fuel, capacity + 1e-7)
            self.assertAlmostEqual(stop["departure_fuel_gallons"], fuel)
            position = stop["mile"]
        fuel -= (total - position) / mpg
        self.assertGreaterEqual(fuel, -1e-7)
        self.assertAlmostEqual(result["remaining_fuel_gallons"], fuel)
        self.assertAlmostEqual(
            initial + result["fuel_purchased_gallons"],
            result["fuel_consumed_gallons"] + result["remaining_fuel_gallons"],
        )

    def test_default_full_tank_is_prepaid(self):
        result = optimize_fuel(300, [station(1, 100, "0.01")])
        self.assertEqual(result["stops"], [])
        self.assertEqual(result["total_fuel_cost"], Decimal("0.00"))
        self.assertEqual(result["initial_fuel_gallons"], 50)
        self.assertEqual(result["fuel_consumed_gallons"], 30)
        self.assertEqual(result["remaining_fuel_gallons"], 20)

    def test_buys_only_enough_to_reach_a_cheaper_station(self):
        result = optimize_fuel(1000, [station(3, 900, 5), station(1, 400, 4), station(2, 600, 2)])
        self.assertEqual([stop["station_id"] for stop in result["stops"]], [1, 2])
        self.assertEqual([stop["gallons"] for stop in result["stops"]], [10, 40])
        self.assertEqual(result["total_fuel_cost"], Decimal("120.00"))
        self.assert_physical_plan(result, 1000, 50, 50, 10)

    def test_fills_at_cheap_station_before_more_expensive_stations(self):
        result = optimize_fuel(1000, [station(1, 100, 1), station(2, 400, 5), station(3, 600, 2)])
        self.assertEqual([stop["station_id"] for stop in result["stops"]], [1, 3])
        self.assertEqual(result["total_fuel_cost"], Decimal("90.00"))
        self.assert_physical_plan(result, 1000, 50, 50, 10)

    def test_collocated_stations_use_cheapest_then_lowest_id(self):
        result = optimize_fuel(
            50,
            [station(9, 0, 5), station(3, 0, 2), station(2, 0, 2)],
            initial_fuel_gallons=0,
        )
        self.assertEqual(len(result["stops"]), 1)
        self.assertEqual(result["stops"][0]["station_id"], 2)
        self.assertEqual(result["total_fuel_cost"], Decimal("10.00"))

    def test_destination_station_does_not_trigger_a_purchase(self):
        result = optimize_fuel(500, [station(1, 500, 1)])
        self.assertEqual(result["stops"], [])
        self.assertEqual(result["remaining_fuel_gallons"], 0)

    def test_zero_distance_and_empty_station_list(self):
        result = optimize_fuel(0, [], initial_fuel_gallons=17)
        self.assertEqual(result["stops"], [])
        self.assertEqual(result["remaining_fuel_gallons"], 17)
        self.assertEqual(result["fuel_consumed_gallons"], 0)
        self.assertEqual(result["total_fuel_cost"], Decimal("0.00"))

    def test_zero_price_is_valid(self):
        result = optimize_fuel(1000, [station(1, 0, 0), station(2, 500, 0)], initial_fuel_gallons=0)
        self.assertEqual(result["total_fuel_cost"], Decimal("0.00"))
        self.assertEqual(result["fuel_purchased_gallons"], 100)
        self.assert_physical_plan(result, 1000, 0, 50, 10)

    def test_starting_empty_can_refuel_at_origin(self):
        result = optimize_fuel(600, [station(1, 0, 3), station(2, 200, 2)], initial_fuel_gallons=0)
        self.assertEqual(result["total_fuel_cost"], Decimal("140.00"))
        self.assert_physical_plan(result, 600, 0, 50, 10)

    def test_insufficient_initial_fuel_is_reported(self):
        with self.assertRaisesRegex(OptimizationError, "Cannot reach station 1 from the start"):
            optimize_fuel(700, [station(1, 400, 3)], initial_fuel_gallons=20)

    def test_gap_exceeding_vehicle_range_is_reported(self):
        with self.assertRaisesRegex(OptimizationError, "Cannot reach station 2 from station 1"):
            optimize_fuel(1000, [station(1, 100, 2), station(2, 700, 3)])

    def test_unreachable_destination_without_stations(self):
        with self.assertRaisesRegex(OptimizationError, "Cannot reach the destination"):
            optimize_fuel(501, [])

    def test_float_noise_at_range_boundary_does_not_make_route_infeasible(self):
        result = optimize_fuel(500.00000000001, [])
        self.assertEqual(result["remaining_fuel_gallons"], 0)
        self.assertEqual(result["stops"], [])

    def test_total_rounds_unrounded_costs_once(self):
        result = optimize_fuel(
            3,
            [station(1, 0, ".004"), station(2, 1, ".004"), station(3, 2, ".004")],
            initial_fuel_gallons=0,
            tank_gallons=1,
            mpg=1,
        )
        self.assertEqual([stop["cost"] for stop in result["stops"]], [Decimal("0.00")] * 3)
        self.assertEqual(result["total_fuel_cost"], Decimal("0.01"))

    def test_money_rounds_half_up(self):
        result = optimize_fuel(10, [station(1, 0, "1.005")], initial_fuel_gallons=0)
        self.assertEqual(result["total_fuel_cost"], Decimal("1.01"))

    def test_invalid_vehicle_values(self):
        invalid = [
            {"total_miles": -1},
            {"total_miles": float("nan")},
            {"total_miles": float("inf")},
            {"tank_gallons": 0},
            {"tank_gallons": -1},
            {"mpg": 0},
            {"mpg": float("nan")},
            {"initial_fuel_gallons": -1},
            {"initial_fuel_gallons": 51},
            {"initial_fuel_gallons": float("inf")},
            {"total_miles": True},
            {"mpg": "10"},
        ]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(OptimizationError):
                arguments = {"total_miles": 10, "candidates": []}
                arguments.update(changes)
                optimize_fuel(**arguments)

    def test_invalid_station_values(self):
        invalid = [
            station(1, -1, 3),
            station(1, 101, 3),
            station(1, 0, -1),
            station(1, float("inf"), 3),
            station(1, 0, "NaN"),
            station(1, 0, "Infinity"),
            station(True, 0, 3),
            {"station_id": 1, "mile": 0, "price": 3},
        ]
        for candidate in invalid:
            with self.subTest(candidate=candidate), self.assertRaises(OptimizationError):
                optimize_fuel(100, [candidate])
        with self.assertRaises(OptimizationError):
            optimize_fuel(100, None)

    def test_matches_independent_oracle_for_500_seeded_small_routes(self):
        rng = random.Random(20260928)
        for case in range(500):
            total = rng.randint(1, 12)
            capacity = rng.randint(1, 6)
            initial = rng.randint(0, capacity)
            candidates = [
                station(mile + 1, mile, rng.randint(0, 7))
                for mile in range(total)
                if rng.random() < 0.65
            ]
            if candidates and rng.random() < 0.3:
                point = rng.choice(candidates)
                candidates.append(station(100, point.mile, rng.randint(0, 7)))
            rng.shuffle(candidates)
            expected = discrete_optimum(total, candidates, capacity, initial)
            with self.subTest(case=case, total=total, capacity=capacity, initial=initial):
                if expected is None:
                    with self.assertRaises(OptimizationError):
                        optimize_fuel(total, candidates, initial, capacity, 1)
                else:
                    result = optimize_fuel(total, candidates, initial, capacity, 1)
                    self.assertEqual(result["total_fuel_cost"], expected)
                    self.assert_physical_plan(result, total, initial, capacity, 1)


if __name__ == "__main__":
    unittest.main()
