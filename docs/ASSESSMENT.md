# Assessment requirements

The assignment received on 25 September 2026 asks for:

- An API accepting US start and finish locations.
- A map of the route and cost-effective places to refuel, using the attached price CSV.
- A maximum vehicle range of 500 miles, with multiple stops as needed.
- The money spent on fuel, assuming 10 miles per gallon.
- A free map/routing API selected by the implementer.
- The latest stable Django release and fast API responses.
- Ideally one routing call per request, with two or three acceptable.
- A Postman (or similar API client) demonstration and brief code overview in a Loom video of at most five minutes.
- A GitHub code link and Loom link submitted through the questionnaire, within three days of receipt.

The email was received at 14:56 IST on Friday 25 September; three days later is 14:56 IST on Monday 28 September 2026. No precise timezone/cutoff clarification was provided by the employer.

## Choices requiring explanation in the walkthrough

- Starting fuel is prepaid and defaults to a full tank; returned cost is additional fuel purchased. The original brief does not define the initial tank or origin price.
- Minimum-cost purchasing is exact for the selected itinerary; global route and detour optimization is outside the implemented heuristic.
- Station coordinate enrichment is incomplete and reported in each response. Unlocated records are excluded, never mapped to invented locations.
- A cold request uses one or two routing calls plus up to two geocoding calls. Cached repeats use no upstream calls.
