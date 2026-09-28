from django.urls import path

from planner import views

urlpatterns = [
    path("", views.index, name="index"),
    path("api/health/", views.health, name="health"),
    path("api/docs/", views.api_docs, name="api-docs"),
    path("api/routes/", views.plan_route, name="plan-route"),
    path("api/routes/<uuid:plan_id>/", views.route_detail, name="route-detail"),
    path("routes/<uuid:plan_id>/map/", views.route_map, name="route-map"),
]
