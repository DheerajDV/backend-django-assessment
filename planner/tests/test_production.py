"""Exercise production startup settings in isolated interpreters, without providers."""

import json
import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]


class ProductionTests(SimpleTestCase):
    def run_python(self, code, **overrides):
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("DJANGO_", "RENDER", "GUNICORN_"))
            and key not in {"RUNTIME_DIR", "PORT"}
        }
        env.update(DJANGO_SETTINGS_MODULE="config.settings", **overrides)
        return subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )

    def production_env(self):
        return {
            "DJANGO_DEBUG": "0",
            "DJANGO_SECRET_KEY": secrets.token_urlsafe(64),
            "DJANGO_ALLOWED_HOSTS": "fuel.example.com",
        }

    def test_production_rejects_missing_weak_secrets_and_wildcard_hosts(self):
        cases = [
            {"DJANGO_SECRET_KEY": ""},
            {"DJANGO_SECRET_KEY": "a" * 64},
            {"DJANGO_ALLOWED_HOSTS": ""},
            {"DJANGO_ALLOWED_HOSTS": "*"},
            {"DJANGO_ALLOWED_HOSTS": ".example.com"},
        ]
        for overrides in cases:
            with self.subTest(overrides=list(overrides)):
                result = self.run_python(
                    "import config.settings", **(self.production_env() | overrides)
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ImproperlyConfigured", result.stderr)

    def test_render_defaults_to_production_with_an_exact_external_host(self):
        result = self.run_python(
            """
import json
from config import settings as s
print(json.dumps({
    "debug": s.DEBUG, "hosts": s.ALLOWED_HOSTS,
    "proxy": s.SECURE_PROXY_SSL_HEADER, "redirect": s.SECURE_SSL_REDIRECT,
    "database": str(s.DATABASES["default"]["NAME"]),
    "cache": str(s.CACHES["default"]["LOCATION"]),
    "secure_cookies": s.CSRF_COOKIE_SECURE and s.SESSION_COOKIE_SECURE,
}))
""",
            RENDER="true",
            RENDER_EXTERNAL_HOSTNAME="fuel-demo.onrender.com",
            DJANGO_SECRET_KEY=secrets.token_urlsafe(64),
            RUNTIME_DIR="/var/data",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertFalse(value["debug"])
        self.assertEqual(value["hosts"], ["fuel-demo.onrender.com"])
        self.assertEqual(value["proxy"], ["HTTP_X_FORWARDED_PROTO", "https"])
        self.assertTrue(value["redirect"])
        self.assertTrue(value["secure_cookies"])
        self.assertEqual(value["database"], "/var/data/db.sqlite3")
        self.assertEqual(value["cache"], "/var/data/.cache")

    def test_direct_server_does_not_trust_a_forged_https_header(self):
        result = self.run_python(
            """
import django
django.setup()
from django.test import Client
response = Client().get(
    "/", HTTP_HOST="fuel.example.com", HTTP_X_FORWARDED_PROTO="https"
)
print(response.status_code)
print(response.headers.get("Location"))
""",
            **self.production_env(),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip().splitlines(), ["301", "https://fuel.example.com/"])

    def test_production_serves_collected_static_and_rejects_unknown_hosts(self):
        with tempfile.TemporaryDirectory(prefix="fuel-production-") as folder:
            result = self.run_python(
                """
import json
from pathlib import Path
import django
django.setup()
from django.conf import settings
from django.contrib.staticfiles.storage import staticfiles_storage
from django.core.management import call_command
from django.test import Client
settings.STATIC_ROOT = Path(settings.RUNTIME_DIR) / "static"
call_command("collectstatic", interactive=False, verbosity=0)
client = Client(HTTP_HOST="fuel.example.com", HTTP_X_FORWARDED_PROTO="https")
page = client.get("/")
asset_url = staticfiles_storage.url("planner/style.css")
asset = client.get(asset_url)
asset_body = b"".join(asset.streaming_content)
unknown_host = client.get("/", HTTP_HOST="evil.example.com")
print(json.dumps({
    "page": page.status_code, "asset": asset.status_code,
    "has_styles": len(asset_body) > 100, "asset_url": asset_url,
    "cache_control": asset.headers.get("Cache-Control", ""),
    "hsts": page.headers.get("Strict-Transport-Security", ""),
    "unknown_host": unknown_host.status_code,
}))
""",
                **self.production_env(),
                RUNTIME_DIR=folder,
                DJANGO_TRUST_PROXY_HEADERS="1",
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["page"], 200)
        self.assertEqual(value["asset"], 200)
        self.assertTrue(value["has_styles"])
        self.assertRegex(value["asset_url"], r"/static/planner/style\.[a-f0-9]+\.css")
        self.assertIn("immutable", value["cache_control"])
        self.assertEqual(value["hsts"], "max-age=3600")
        self.assertEqual(value["unknown_host"], 400)

    def test_development_keeps_existing_local_database_and_no_proxy_trust(self):
        result = self.run_python(
            """
import json
from config import settings as s
print(json.dumps({
    "debug": s.DEBUG,
    "database": str(s.DATABASES["default"]["NAME"]),
    "trust_proxy": s.TRUST_PROXY_HEADERS,
    "redirect": s.SECURE_SSL_REDIRECT,
}))
"""
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertTrue(value["debug"])
        self.assertEqual(value["database"], str(ROOT / "db.sqlite3"))
        self.assertFalse(value["trust_proxy"])
        self.assertFalse(value["redirect"])
