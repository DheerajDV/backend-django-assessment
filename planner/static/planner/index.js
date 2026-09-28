"use strict";

(() => {
  const form = document.getElementById("route-form");
  const submit = document.getElementById("submit-button");
  const status = document.getElementById("request-status");
  const error = document.getElementById("request-error");
  const result = document.getElementById("route-result");
  const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
  const decimal = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });

  document.querySelectorAll("[data-start]").forEach((button) => {
    button.addEventListener("click", () => {
      form.elements.start.value = button.dataset.start;
      form.elements.finish.value = button.dataset.finish;
      form.elements.start.focus();
    });
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    submit.disabled = true;
    submit.firstElementChild.textContent = "Planning your route…";
    error.hidden = true;
    result.hidden = true;
    status.textContent = "Finding the road route and checking fuel stops. A first request may take longer while locations are resolved.";
    status.hidden = false;

    try {
      const headers = { "Content-Type": "application/json", Accept: "application/json" };
      const csrf = form.querySelector("[name=csrfmiddlewaretoken]");
      if (csrf) headers["X-CSRFToken"] = csrf.value;
      const response = await fetch("/api/routes/", {
        method: "POST",
        headers,
        credentials: "same-origin",
        body: JSON.stringify({
          start: form.elements.start.value.trim(),
          finish: form.elements.finish.value.trim(),
          initial_fuel_gallons: Number(form.elements.initial_fuel_gallons.value),
        }),
      });
      let plan;
      try {
        plan = await response.json();
      } catch {
        throw new Error(`The server returned an unreadable response (${response.status}). Check that the API is running and try again.`);
      }
      if (!response.ok) throw new Error(plan.error?.message || `The route could not be planned (${response.status}).`);
      if (!plan.route || !plan.fuel_plan || !plan.map_url) throw new Error("The API response is missing route information.");

      const destination = new URL(plan.map_url, window.location.origin);
      if (destination.origin !== window.location.origin) throw new Error("The API returned an unexpected map address.");
      document.getElementById("result-title").textContent = `${form.elements.start.value.trim()} → ${form.elements.finish.value.trim()}`;
      const stops = plan.fuel_plan.stops.length;
      document.getElementById("result-summary").textContent = `${decimal.format(Number(plan.route.distance_miles))} miles · ${stops} fuel ${stops === 1 ? "stop" : "stops"} · ${money.format(Number(plan.fuel_plan.total_fuel_cost))} in additional fuel purchases`;
      document.getElementById("result-link").href = destination.href;
      document.getElementById("response-json").textContent = JSON.stringify(plan, null, 2);
      const warnings = plan.metadata?.warnings || [];
      const notice = document.getElementById("result-warning");
      notice.hidden = warnings.length === 0;
      notice.textContent = warnings.join(" ");
      result.hidden = false;
      status.textContent = "Route ready. Open the map to review your fuel plan and its assumptions.";
      result.scrollIntoView({ behavior: "smooth", block: "nearest" });
      document.getElementById("result-link").focus({ preventScroll: true });
    } catch (problem) {
      error.textContent = problem instanceof TypeError
        ? "The API could not be reached. Check your connection and that the local server is running, then try again."
        : problem.message;
      error.hidden = false;
      status.hidden = true;
    } finally {
      submit.disabled = false;
      submit.firstElementChild.textContent = "Plan my route";
    }
  });
})();
