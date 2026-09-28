"use strict";

(() => {
  const container = document.getElementById("swagger-ui");
  const status = document.getElementById("api-load-status");

  if (!container || !status) return;
  if (typeof window.SwaggerUIBundle !== "function") {
    status.textContent = "The API explorer could not load. Refresh, or import the OpenAPI JSON into Postman.";
    return;
  }

  window.ui = window.SwaggerUIBundle({
    url: container.dataset.specUrl,
    dom_id: "#swagger-ui",
    deepLinking: true,
    docExpansion: "list",
    defaultModelRendering: "model",
    defaultModelExpandDepth: 1,
    defaultModelsExpandDepth: -1,
    displayRequestDuration: true,
    supportedSubmitMethods: ["get", "post"],
    tryItOutEnabled: false,
    validatorUrl: null,
    withCredentials: false,
    persistAuthorization: false,
    queryConfigEnabled: false,
    presets: [window.SwaggerUIBundle.presets.apis],
    layout: "BaseLayout",
    requestInterceptor: (request) => {
      const target = new URL(request.url, window.location.href);
      if (target.origin !== window.location.origin) {
        throw new Error("This explorer only sends API requests to this deployment.");
      }
      request.credentials = "omit";
      return request;
    },
    onComplete: () => {
      status.hidden = true;
      // Use Swagger's rendered control so its expansion state stays consistent.
      // Honor a supplied deep link; otherwise begin with the health operation.
      if (!window.location.hash) {
        const healthToggle = document.querySelector("#operations-Health-getHealth .opblock-summary-control");
        if (healthToggle && healthToggle.getAttribute("aria-expanded") !== "true") {
          healthToggle.click();
        }
      }
    },
  });
})();
