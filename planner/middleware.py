"""Small, shared limit for an unauthenticated assessment demo on one instance."""

import fcntl
import hashlib
import json
import math
import time

from django.conf import settings
from django.http import JsonResponse


class RouteRateLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.method != "POST"
            or request.path != "/api/routes/"
            or not settings.API_RATE_LIMIT_ENABLED
        ):
            return self.get_response(request)

        # Do not trust caller-supplied forwarding headers. On a reverse proxy,
        # callers sharing the same upstream address share this conservative cap.
        address = request.META.get("REMOTE_ADDR", "unknown")
        client = hashlib.sha256(address.encode()).hexdigest()
        now = time.time()
        window = settings.API_RATE_WINDOW
        cutoff = now - window
        settings.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        retry_after = 0
        with (settings.CACHE_DIR / "route-rate-limit.json").open("a+") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.seek(0)
            try:
                events = json.loads(handle.read() or "[]")
            except json.JSONDecodeError:
                events = []
            events = [event for event in events if cutoff < event[0] <= now]
            client_events = [event for event in events if event[1] == client]
            if len(events) >= settings.API_GLOBAL_RATE_LIMIT:
                retry_after = max(1, math.ceil(events[0][0] + window - now))
            elif len(client_events) >= settings.API_RATE_LIMIT:
                retry_after = max(1, math.ceil(client_events[0][0] + window - now))
            else:
                events.append([now, client])
            handle.seek(0)
            handle.truncate()
            json.dump(events, handle)
            handle.flush()
            fcntl.flock(handle, fcntl.LOCK_UN)

        if retry_after:
            response = JsonResponse(
                {
                    "error": {
                        "code": "rate_limited",
                        "message": "The demo is receiving too many route requests. Please retry shortly.",
                    }
                },
                status=429,
            )
            response["Retry-After"] = str(retry_after)
            response["Cache-Control"] = "no-store"
            return response
        return self.get_response(request)
