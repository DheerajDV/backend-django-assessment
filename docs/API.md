# Interactive API explorer

Open `/api/docs/` on the running deployment to use Swagger UI. It loads the local OpenAPI definition from `/static/planner/openapi.json` and sends real requests to the same host. The definition can also be imported into Postman. No authentication is required; hosted route requests are rate limited.

1. Expand `GET /api/health/`, click **Try it out**, then **Execute**. Inspect the reported Django version and the imported versus located station counts.
2. Execute `POST /api/routes/` with the **Long trip** request example to plan Chicago → Dallas. Open the returned `map_url`. Inspect `fuel_plan.stops`, `total_fuel_cost`, `metadata.routing_api_calls`, `geocoding_api_calls`, `elapsed_ms`, and warnings.
3. Execute the same body again to inspect caching. Counts report actual upstream HTTP attempts for that request. A warm cache may reduce both routing and geocoding calls to zero. Swagger's displayed request duration also includes HTTP transport and response serialization, whereas `metadata.elapsed_ms` measures plan construction before saving the record.
4. Paste the returned `id` into `GET /api/routes/{id}/` to retrieve the persisted response. Its metadata describes the original planning request, not the retrieval request.
5. Change `initial_fuel_gallons` to `51` and execute the POST to demonstrate input validation. Reset it to `50` afterward.

The request examples are editable input examples, not captured test results. Response schemas default to the **Model** view; actual results appear under **Server response** only after execution.

## Model boundaries

The vehicle uses 10 US miles per gallon, carries 50 gallons, and starts with 50 gallons unless specified otherwise. Starting fuel is prepaid, so `total_fuel_cost` counts additional purchases only. A short trip can consume fuel while requiring no purchases. USD prices and monetary amounts are decimal strings; distances and fuel quantities are JSON numbers.

The planner considers sourced station coordinates near the initial road route and verifies selected stops by routing through their coordinates. Fuel purchasing is minimum-cost for the final ordered itinerary; candidate and road selection do not guarantee a global minimum over all roads or stations. Missing station coordinates, historical price data, car routing, and road snapping are disclosed in each response's assumptions and warnings. A route can fail with a structured coverage error when the available stations do not support it.

Swagger UI's official `swagger-ui-dist` package is pinned to **5.33.0** (npm registry checked on 28 September 2026), loaded through jsDelivr with SHA-384 integrity checks. The external schema validator is disabled, cookie credentials are omitted, and interactive requests are restricted to this deployment's origin. The explorer does not execute requests on page load.

References: [official Swagger UI package](https://www.npmjs.com/package/swagger-ui-dist), [Swagger UI configuration](https://swagger.io/docs/open-source-tools/swagger-ui/usage/configuration/).
