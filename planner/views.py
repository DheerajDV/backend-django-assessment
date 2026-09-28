import json
import math

from django.core.exceptions import RequestDataTooBig
from django.core.serializers.json import DjangoJSONEncoder
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_GET

from planner.errors import PlanningError
from planner.models import RoutePlan, Station
from planner.service import build_plan


@require_GET
@ensure_csrf_cookie
def index(request):
    return render(request, "planner/index.html")


@require_GET
def api_docs(request):
    return render(request, "planner/api_docs.html")


@require_GET
def health(request):
    total = Station.objects.count()
    located = Station.objects.filter(latitude__isnull=False, longitude__isnull=False).count()
    return JsonResponse(
        {
            "status": "ok" if total else "needs_data",
            "django_version": __import__("django").get_version(),
            "total_stations": total,
            "located_stations": located,
        }
    )


def error(message, code, status=400, details=None):
    value = {"code": code, "message": message}
    if details is not None:
        value["details"] = details
    return JsonResponse({"error": value}, status=status)


@csrf_exempt
def plan_route(request):
    # Public stateless demo API: no cookie-based identity, JSON-only bodies,
    # no cross-origin access, and shared request limits when hosted.
    if request.method != "POST":
        response = error("Use POST with a JSON body.", "method_not_allowed", 405)
        response["Allow"] = "POST"
        return response
    if request.content_type != "application/json":
        return error("Content-Type must be application/json.", "unsupported_media_type", 415)
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return error("Request body is not valid JSON.", "invalid_json")
    except RequestDataTooBig:
        return error("Request body is too large.", "request_too_large", 413)
    if not isinstance(payload, dict):
        return error("Request body must be a JSON object.", "invalid_request")
    unknown = set(payload) - {"start", "finish", "initial_fuel_gallons"}
    if unknown:
        return error("Unknown fields: " + ", ".join(sorted(unknown)), "invalid_request")
    for name in ("start", "finish"):
        value = payload.get(name)
        if not isinstance(value, str) or not 2 <= len(value.strip()) <= 200:
            return error(
                f"'{name}' must be a location string between 2 and 200 characters.",
                "invalid_request",
            )
    initial = payload.get("initial_fuel_gallons", 50)
    if (
        isinstance(initial, bool)
        or not isinstance(initial, (float, int))
        or not 0 <= initial <= 50
        or not math.isfinite(initial)
    ):
        return error("initial_fuel_gallons must be a number from 0 to 50.", "invalid_request")
    if not Station.objects.exists():
        return error(
            "Import the supplied station CSV before planning routes.", "station_data_missing", 503
        )
    try:
        result = build_plan(payload["start"].strip(), payload["finish"].strip(), initial)
    except PlanningError as exc:
        return error(str(exc), exc.code, exc.status, exc.details)
    # Normalize Decimal values to JSON strings for exact monetary representation.
    result = json.loads(json.dumps(result, cls=DjangoJSONEncoder, allow_nan=False))
    record = RoutePlan.objects.create(result=result)
    result["id"] = str(record.id)
    result["map_url"] = request.build_absolute_uri(reverse("route-map", args=[record.id]))
    record.result = result
    record.save(update_fields=["result"])
    return JsonResponse(result)


@require_GET
def route_detail(request, plan_id):
    record = RoutePlan.objects.filter(pk=plan_id).first()
    if record is None:
        return error("Route not found.", "not_found", 404)
    return JsonResponse(record.result)


@require_GET
def route_map(request, plan_id):
    record = get_object_or_404(RoutePlan, pk=plan_id)
    return render(request, "planner/map.html", {"plan": record.result})
