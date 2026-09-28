"""Small, single-instance deployment with a shared SQLite database."""

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
workers = 1
worker_class = "gthread"
threads = 2
timeout = 120
graceful_timeout = 30
keepalive = 5
accesslog = "-"
errorlog = "-"
capture_output = True
preload_app = False
# Match Django's explicit proxy-trust policy; do not trust client-supplied headers
# when the server is used directly. Render's private edge is the trusted proxy.
trust_proxy = os.environ.get("DJANGO_TRUST_PROXY_HEADERS", os.environ.get("RENDER", "0"))
trust_proxy = trust_proxy.lower() in {"1", "true", "yes", "on"}
forwarded_allow_ips = "*" if trust_proxy else ""
secure_scheme_headers = {"X-FORWARDED-PROTO": "https"} if trust_proxy else {}
limit_request_line = 4094
limit_request_fields = 50
limit_request_field_size = 4094
