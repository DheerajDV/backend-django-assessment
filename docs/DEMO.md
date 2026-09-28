# API demonstration

The hosted demonstration is at `https://spotter-fuel-planner-dheeraj.onrender.com/`; a local copy can also run at `http://127.0.0.1:8000/` following the repository README. The page submits the same JSON endpoint used by Postman. It does not generate sample results in the browser.

## Postman

1. Import `docs/postman_collection.json` into Postman.
2. The collection variable `baseUrl` defaults to `https://spotter-fuel-planner-dheeraj.onrender.com`. Set it to `http://127.0.0.1:8000` for a local run. Do not add a trailing slash.
3. Run **01 — Health and dataset coverage** first. Confirm that the station dataset is loaded. The response reports imported and located station counts separately.
4. Run the requests in order. Successful route requests store `routeId` and `mapUrl` as collection variables. Open the returned `map_url` in a browser to review the road geometry and numbered fuel stops.
5. The repeat request exercises the same route inputs. Read the response's `metadata.routing_api_calls`, `metadata.geocoding_api_calls`, and `metadata.elapsed_ms` to compare a first request with a warmed cache. A saved plan has its own ID even when upstream results are reused.

The collection includes a short trip, a trip longer than one full tank, a repeat trip, retrieval of a saved plan, an out-of-U.S. location, and an invalid tank quantity. Tests check response structure, the fuel balance, capacity constraints at stops, itemized purchase totals, and validation behavior. Any network-dependent request can fail if an upstream routing or geocoding service is unavailable; do not present such a failure as a passing demo.

Fuel efficiency is 10 miles per gallon and tank capacity is 50 gallons, giving a 500-mile maximum range. The default initial tank is full. **`total_fuel_cost` is the cost of additional fuel purchases, excluding the fuel already in the tank.** A short trip can therefore legitimately have no fuel stops and a purchase cost of $0. Price and cost fields are decimal strings in JSON; the collection converts them to numbers only for test comparisons.

## Coverage and limitations to explain

- Prices come from the provided CSV, not a live feed.
- A station can only be considered once the API has usable coordinates for it. Compare `located_stations` with `total_stations`; importing every CSV row does not mean every station has been located.
- Any remaining offline location enrichment must be completed and rechecked before claiming full coverage. The current implementation uses sourced station coordinates, not city centroids. Road snapping and forecourt access still have limitations; review the service's assumptions and warnings.
- The optimizer works with the candidate stations selected near the route. Its result does not establish the cheapest trip across every possible road route or stations that are missing coordinates.
- Explain exactly how station offsets and detours are handled by the implementation's returned assumptions. A straight-line offset shown on the map is not a verified driving detour.
- Driving duration is the road-service estimate. It excludes fuel stops, breaks, traffic changes, and any detours not included by the model.
- The demonstration uses public upstream services. Routing requests, map tiles, and geocoding are distinct uses; the metadata reports routing and geocoding request counts separately.

## Loom outline — target 4 minutes 30 seconds

**0:00–0:30 — What the API does.** Show the running homepage. State the 500-mile range, 10 mpg, and the default full prepaid tank. Explain that the cost is additional fuel purchased during the trip.

**0:30–1:00 — Data and health.** In Postman, send the health request. Show actual imported and located counts. Briefly explain that the source CSV supplies station prices and location enrichment is separate.

**1:00–2:15 — Main trip.** Send the Chicago-to-Dallas request. Show the distance, fuel stops, each stop's purchase amount, total purchase cost, and upstream request counts. Open its `map_url`; trace the route, select a numbered stop, and show the fuel accounting.

**2:15–2:50 — Short trip and validation.** Send Chicago-to-Milwaukee to demonstrate that a full initial tank can require no purchase. Send the non-U.S. or invalid-tank example and show its structured error response.

**2:50–3:25 — Cache and efficiency.** Repeat the main trip. Show the observed response time and metadata; describe only the caching behavior the actual response demonstrates.

**3:25–4:15 — Implementation.** Show the separation between request validation, routing/geocoding, station selection, and fuel optimization. Explain the decision rule or algorithm actually implemented. Show the automated test result and mention important edge cases covered.

**4:15–4:30 — Limits and deliverables.** Show the response assumptions, note any incomplete station enrichment and detour approximation, then identify the repository and Postman collection. Stop recording before five minutes.

Record only after live requests succeed. Avoid exposing private inbox content, credentials, or unrelated browser tabs in the recording. The repository and app are published separately from the video; no assessment submission is sent automatically.
