"use strict";

(() => {
  const plan = JSON.parse(document.getElementById("route-plan-data").textContent);
  const fuel = plan.fuel_plan;
  const metadata = plan.metadata || {};
  const stops = fuel.stops || [];
  const number = (value, digits = 1) => new Intl.NumberFormat("en-US", { maximumFractionDigits: digits }).format(Number(value));
  const money = (value) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(Number(value));
  const set = (id, value) => { document.getElementById(id).textContent = value; };
  const node = (tag, text, className) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  };
  const shortName = (place) => place.name.split(",").slice(0, 2).join(",");
  set("route-title", `${shortName(plan.start)} → ${shortName(plan.finish)}`);
  set("route-subtitle", "A driving route with fuel purchases planned around the available station prices.");
  document.title = `${shortName(plan.start)} to ${shortName(plan.finish)} — Fuelwise`;
  document.getElementById("json-link").href = `/api/routes/${encodeURIComponent(plan.id)}/`;
  set("distance-value", `${number(plan.route.distance_miles)} mi`);
  const minutes = Math.round(Number(plan.route.duration_hours) * 60);
  set("duration-value", `${Math.floor(minutes / 60)}h ${minutes % 60}m`);
  set("cost-value", money(fuel.total_fuel_cost));
  set("cost-note", `Excludes ${number(fuel.initial_fuel_gallons)} gal already in the tank.`);
  set("stops-value", String(stops.length).padStart(2, "0"));
  for (const [id, value] of [["initial-value", fuel.initial_fuel_gallons], ["purchased-value", fuel.fuel_purchased_gallons], ["consumed-value", fuel.fuel_consumed_gallons], ["remaining-value", fuel.remaining_fuel_gallons]]) set(id, `${number(value, 2)} gal`);

  if (metadata.total_stations !== undefined && metadata.located_stations !== undefined) {
    set("coverage-text", `${number(metadata.located_stations, 0)} of ${number(metadata.total_stations, 0)} imported stations have usable coordinates. ${number(metadata.candidate_stations || 0, 0)} stations were considered near this route. Coverage and coordinate accuracy limit this estimate.`);
  } else {
    set("coverage-text", "This plan uses the stations available to the API. Review its assumptions before relying on station locations or fuel costs.");
  }
  (metadata.assumptions || []).forEach((text) => document.getElementById("assumptions-list").append(node("li", text)));
  if ((metadata.warnings || []).length) {
    document.getElementById("warnings-panel").hidden = false;
    metadata.warnings.forEach((text) => document.getElementById("warnings-list").append(node("li", text)));
  }
  const requestDetails = [];
  if (metadata.routing_api_calls !== undefined) requestDetails.push(`${metadata.routing_api_calls} routing API call(s)`);
  if (metadata.geocoding_api_calls !== undefined) requestDetails.push(`${metadata.geocoding_api_calls} geocoding call(s)`);
  if (metadata.elapsed_ms !== undefined) requestDetails.push(`${number(Number(metadata.elapsed_ms) / 1000, 2)}s response time`);
  set("request-meta", requestDetails.join(" · "));

  const stopButtons = [];
  stops.forEach((stop, index) => {
    const item = node("li", undefined, "stop-card");
    const heading = node("div", undefined, "stop-title-row");
    heading.append(node("span", String(index + 1), "stop-badge"));
    const title = node("div");
    title.append(node("h3", stop.name), node("p", [stop.city, stop.state].filter(Boolean).join(", "), "muted"));
    heading.append(title);
    item.append(heading);
    if (stop.address) item.append(node("p", stop.address, "stop-address"));
    const detail = node("div", undefined, "stop-purchase");
    detail.append(node("strong", money(stop.cost)), node("span", `${number(stop.gallons, 2)} gal × $${number(stop.price_per_gallon, 3)}/gal`));
    item.append(detail);
    item.append(node("p", `Mile ${number(stop.mile)} · ${number(stop.arrival_fuel_gallons, 2)} gal on arrival → ${number(stop.departure_fuel_gallons, 2)} gal on departure`, "stop-detail"));
    if (stop.offset_miles !== undefined) item.append(node("p", `${number(stop.offset_miles, 2)} mi from the initial route (straight-line offset)`, "stop-detail"));
    const button = node("button", "Show on map ↗", "text-button");
    button.type = "button";
    button.disabled = true;
    item.append(button);
    stopButtons.push(button);
    document.getElementById("stops-list").append(item);
  });
  document.getElementById("no-stops").hidden = stops.length > 0;

  const mapError = (message) => {
    set("map-error", message);
    document.getElementById("map-error").hidden = false;
  };
  if (typeof window.L === "undefined") {
    mapError("The map library could not load. Check your internet connection. Your fuel plan and the JSON response are still available.");
    return;
  }

  try {
    const map = L.map("map", { scrollWheelZoom: false });
    const tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      // OSM requires an origin Referer, including when Django defaults to same-origin.
      referrerPolicy: "strict-origin-when-cross-origin",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a> · Routing: <a href="https://project-osrm.org/">OSRM</a>',
    }).addTo(map);
    let tileErrors = 0;
    tiles.on("tileerror", () => {
      tileErrors += 1;
      if (tileErrors === 3) mapError("Some map tiles could not load. The route line and station markers are still shown; check your internet connection for the basemap.");
    });
    const route = L.geoJSON(plan.route.geometry, { style: { color: "#176f65", weight: 5, opacity: 0.9 } }).addTo(map);
    const bounds = route.getBounds();
    const endpoint = (place, letter, className) => {
      const icon = L.divIcon({ className: "marker-shell", html: `<span class="endpoint-marker ${className}">${letter}</span>`, iconSize: [30, 30], iconAnchor: [15, 15] });
      const latlng = [Number(place.latitude), Number(place.longitude)];
      L.marker(latlng, { icon, title: place.name }).addTo(map).bindPopup(node("strong", `${letter === "A" ? "Start" : "Finish"}: ${place.name}`));
      bounds.extend(latlng);
    };
    endpoint(plan.start, "A", "start-marker");
    endpoint(plan.finish, "B", "finish-marker");
    stops.forEach((stop, index) => {
      const latlng = [Number(stop.latitude), Number(stop.longitude)];
      const popup = node("div", undefined, "station-popup");
      popup.append(node("strong", `${index + 1}. ${stop.name}`));
      popup.append(node("p", [stop.address, stop.city, stop.state].filter(Boolean).join(", ")));
      popup.append(node("p", `Buy ${number(stop.gallons, 2)} gal at $${number(stop.price_per_gallon, 3)}/gal`));
      popup.append(node("strong", `Purchase: ${money(stop.cost)}`));
      const icon = L.divIcon({ className: "marker-shell", html: `<span class="fuel-marker">${index + 1}</span>`, iconSize: [32, 32], iconAnchor: [16, 16] });
      const marker = L.marker(latlng, { icon, title: `Fuel stop ${index + 1}: ${stop.name}` }).addTo(map).bindPopup(popup);
      bounds.extend(latlng);
      stopButtons[index].disabled = false;
      stopButtons[index].addEventListener("click", () => {
        map.setView(latlng, Math.max(map.getZoom(), 11));
        marker.openPopup();
        document.getElementById("map").scrollIntoView({ behavior: "smooth", block: "center" });
      });
    });
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [40, 40], maxZoom: 13 });
    else map.setView([39.5, -98.35], 4);
  } catch {
    mapError("This route could not be displayed on the map. The fuel plan is available below, and you can inspect the saved JSON response.");
  }
})();
