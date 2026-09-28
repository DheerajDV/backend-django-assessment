# Spotter fuel-route planner

A Django 6.1.1 API that finds a driving route between US locations, chooses fuel stops from the supplied price snapshot, and returns fuel purchases plus an interactive route map. The vehicle has a 50-US-gallon tank, a 500-mile range and an efficiency of 10 mpg.

Includes live routing, sourced station coordinates, automated tests, a Postman collection, an interactive Swagger API explorer and a production deployment configuration. Coordinate coverage is incomplete: unlocated stations are excluded, and the API reports coverage on every response. This is not a guarantee of the cheapest journey among every road or every station in the original CSV.

## Prerequisites

- Python 3.12 or newer (developed and tested with Python 3.13).
- Internet access for uncached routing/geocoding and browser map tiles. No API key is required.
- Postman or another API client for the assessment demonstration.
- A GitHub account and Loom for the final submission.

SQLite is included with Python. Docker, PostgreSQL and a paid maps account are not required.

## Run locally

```sh
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py import_stations
python manage.py runserver 127.0.0.1:8000
```

If using uv, `uv sync --frozen` installs the locked environment instead of the first three commands. Run the remaining commands with `uv run`.

Open <http://127.0.0.1:8000/>. The homepage provides a small API demo; each successful response includes a saved `map_url` that opens the route and stops. Import `docs/postman_collection.json` into Postman to demonstrate the API directly.

## API

```sh
curl -X POST http://127.0.0.1:8000/api/routes/ \
  -H 'Content-Type: application/json' \
  -d '{"start":"Chicago, IL","finish":"Dallas, TX","initial_fuel_gallons":50}'
```

`start` and `finish` are location strings, preferably city and state. The first geocoder result must be in the United States. `initial_fuel_gallons` is optional, defaults to 50, and must be between 0 and 50. All quantities use US miles, US gallons and USD.

| Endpoint | Purpose |
| --- | --- |
| `GET /api/health/` | Django version and station coordinate coverage |
| `GET /api/docs/` | Interactive Swagger API explorer with real requests |
| `POST /api/routes/` | Validate input, calculate route and fuel purchases, save a map |
| `GET /api/routes/<id>/` | Retrieve a saved result without upstream calls |
| `GET /routes/<id>/map/` | Display the route, stations, costs and assumptions |

The response includes `route` (GeoJSON geometry, mileage and driving time), `fuel_plan` (ordered stops and quantities), `map_url`, and `metadata` (coverage, actual upstream call counts, elapsed time, assumptions and warnings). Currency is encoded as decimal strings to avoid binary floating-point money errors.

### What the fuel cost means

**The starting fuel is assumed to have been paid for before the trip.** `total_fuel_cost` is the additional money spent at selected stops; it excludes that starting fuel. Consequently, a journey under 500 miles with the default full tank can cost `$0.00` in additional purchases while still consuming fuel. `fuel_consumed_gallons`, `fuel_purchased_gallons`, `initial_fuel_gallons` and `remaining_fuel_gallons` make this distinction explicit.

The email does not specify starting fuel or its historical purchase price. This implementation makes the assumption visible rather than inventing an origin price. Set the starting fuel to the actual amount when planning. An empty tank can only travel if a sourced station is reachable at the origin.

Displayed stop costs are rounded to cents. The total is summed at full precision and then rounded once, so it can differ by a cent from summing individually rounded displays.

### Errors

Errors use `{ "error": { "code": "...", "message": "...", "details": {} } }`.

- `400`: invalid request, unknown location, or an endpoint outside the USA.
- `405` / `415`: unsupported method / content type.
- `422`: no route, insufficient sourced station coverage, or a road-verified fuel gap beyond the available range.
- `429`: the public demo's request limit has been reached; retry after the indicated delay.
- `502`: unavailable or malformed upstream service response.
- `503`: station data has not been imported.

## How it works

1. Resolve the two endpoints with Photon and cache them for 30 days.
2. Request an OSRM driving route and cache it for 24 hours.
3. Use a local spatial index to locate sourced fuel stations within one mile of that route. Geodesic segment lengths interpolate their positions along the route.
4. On this fixed ordered route, buy only enough to reach the next cheaper reachable station; otherwise fill up or buy enough to finish. A monotonic stack finds the next cheaper station after sorting, giving O(n log n) total optimizer complexity.
5. Request a second OSRM route through the selected station waypoints. Recalculate purchases using its actual road-leg distances and reject any infeasible fuel gap.
6. Save JSON and render a Leaflet map with the route, start/end and numbered fuel stops.

One routing call is used when no fuel stops are needed; at most two routing calls are used when stops are selected. An entirely uncached request also needs up to two Photon geocoding calls, so the cold long-route total is four external API calls. Repeat routes make zero external calls while caches are valid. Browser map tiles and JavaScript assets are separate from backend route/geocoder calls. Public-service calls are limited to one per second per provider across local processes, have bounded timeouts, and are not automatically retried.

**Optimality scope:** the fuel-buying algorithm is exact for a fixed ordered itinerary. Choosing stations based on the original route corridor and then verifying those stops is a heuristic for the wider road network; detours can change which subset would be globally cheapest. The returned map includes all selected routing waypoints even if recalculation no longer needs a purchase at one of them.

## Data and location accuracy

The input has 8,151 rows and 6,738 distinct OPIS IDs. Filtering by US state leaves 6,626 stations; 620 non-US rows are excluded. Duplicate station IDs are merged with the lowest quoted retail price from the snapshot. There are no price timestamps or fuel-grade fields, so this policy is documented rather than inferred as a current/live price.

The source addresses are mostly highway exits and do not contain latitude/longitude. The checked-in `data/station_coordinates.csv` adds coordinates with source URLs. See `data/COORDINATES.md` for sources, matching rules and coverage. City centers are never substituted for station coordinates. All US price records remain in SQLite, but only sourced coordinates are eligible for route selection.

`python manage.py import_stations` validates all inputs before replacing the station catalog, is transactional and repeatable, and invalidates the cached catalog. To use another reviewed coordinate file:

```sh
python manage.py import_stations data/fuel-prices.csv --coordinates path/to/station_coordinates.csv
```

The coordinate CSV fields are `opis_id,latitude,longitude,source`.

## Verification

```sh
python manage.py check
python manage.py test planner.tests
uv run ruff check .
```

Tests include input validation, atomic imports, spatial screening, purchase/range conservation, API errors, saved maps, caching and road-distance recalculation. The optimizer is also compared with an independent exhaustive dynamic-programming solution on 500 reproducible small routes.

Live verification with the checked-in 1,094-station coordinate snapshot: Chicago to Dallas produced a roughly 969-mile road-verified itinerary with three fuel purchases; New York to Los Angeles produced a roughly 2,801-mile itinerary with eight purchases. The cross-country test took about 11.3 seconds while fetching uncached provider responses. Cached repeats took 68 ms for Chicago–Dallas and 220 ms for New York–Los Angeles, with zero upstream calls. These measurements depend on provider availability and cache state; they are not latency guarantees.

## Configuration and limits

See [the hosting guide](docs/HOSTING.md) and `.env.example` for production configuration. The Render setup uses Gunicorn, WhiteNoise, HTTPS, a generated secret, explicit allowed hosts, and a rolling limit on route calculations. Saved routes and provider caches use `RUNTIME_DIR`; production persistence requires the configured disk. The public assessment demo deliberately has no login and should not receive private travel details.

- Public OSRM and Photon endpoints are free demo services without an availability guarantee. Use your own services for heavy use.
- OSRM uses a car profile, not truck-specific restrictions. The endpoints are checked as US locations, but intervening border crossings are not prohibited.
- Station waypoints can snap to nearby roads within 1 km. The final route verifies road distances, not driveway access or the side of a divided highway.
- Incomplete coordinates can miss cheaper stops or leave a route without a feasible fuel plan.
- Fuel prices are static assessment data. Fuel efficiency, tank capacity, vehicle load and traffic are not modeled dynamically.
- Local route records are retained in SQLite; external lookup caches expire separately. Rebuild a route to use updated station prices.

## Assessment handoff

See `docs/DEMO.md` for a walkthrough under five minutes and [API.md](docs/API.md) for the interactive client. Review the assumptions and station coverage before submitting the GitHub and Loom links through the employer's questionnaire. No submission is sent automatically.

Sources: [Django release](https://www.djangoproject.com/download/), [OSRM API](https://project-osrm.org/docs/v5.24.0/api/), [routing service policy](https://routing.openstreetmap.de/about.html), [Photon](https://github.com/komoot/photon), [OpenStreetMap attribution](https://www.openstreetmap.org/copyright).
