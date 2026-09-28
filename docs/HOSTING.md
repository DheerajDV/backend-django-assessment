# Hosted assessment demo

The repository includes a Render Blueprint for one always-on Python web service with a
1 GB persistent disk. It runs Django 6.1.1 through Gunicorn, with WhiteNoise serving
compressed, versioned CSS and JavaScript. This is a paid **0.5 CPU / 512 MB** configuration
(the tier previously called Starter);
review the price shown by Render before creating the service.

## Current deployment

The published app is [spotter-fuel-planner-dheeraj.onrender.com](https://spotter-fuel-planner-dheeraj.onrender.com/). Its 1 GB disk is mounted at `/var/data/fuel-planner-data`, and `RUNTIME_DIR` points to that exact directory. Both the mount and environment variable must match; mounting a subdirectory does not persist files stored in its parent.

## Deploy

1. Push this repository to GitHub and connect that repository in Render.
2. Create a **Blueprint** using the checked-in `render.yaml`.
3. Review the 0.5 CPU / 512 MB service and 1 GB disk, then create the service.
4. Wait for the build and `/api/health/` readiness check to succeed.
5. Open the supplied `https://…onrender.com` address. Set the Postman collection's
   `baseUrl` variable to that address.

The Blueprint generates a secret key and sets `DJANGO_DEBUG=0`. Render supplies the
exact allowed hostname automatically. For a custom domain, add that domain to
`DJANGO_ALLOWED_HOSTS` as a comma-separated value, without a scheme or path. Keep the
automatically supplied Render hostname enabled for the built-in URL and health checks.

The build installs the pinned dependencies from `requirements.txt` and collects static
files. Each startup applies migrations and imports the two checked-in CSV files, then
starts Gunicorn. The import does not call a geocoder or routing service and does not
delete saved route plans. Dataset enrichment is a separate, offline workflow.

## Temporary deployment without a disk

The initial connector-based deployment can use `RUNTIME_DIR=.runtime` until the
approved disk is attached in the Render Dashboard. **This temporary storage is
ephemeral, even on a paid service.** Saved route IDs and caches disappear on a
restart or redeploy. The startup import restores the station catalog, so the API
can still run, but persistence is not complete until both steps below are done:

1. Open the service's **Disks** page, add a **1 GB** disk mounted at **`/var/data`**,
   and wait for the triggered deployment to complete.
2. On its **Environment** page, change `RUNTIME_DIR` to **`/var/data`**, save and
   redeploy. Verify `/api/health/` returns HTTP 200 with nonzero station and
   coordinate counts, then generate fresh demo routes.

Attaching a disk does not copy the earlier `.runtime` database. If any initial
route history must be retained, take a consistent SQLite backup before the first
redeploy and restore it to the disk; otherwise those temporary route IDs expire.
The checked-in Blueprint already defines the finished disk-backed configuration.

## Updating the published app

The current service was created from the public repository URL. In this mode, Render does not create Git-provider webhooks, so a GitHub push alone does not deploy it. After checks pass, use **Manual Deploy → Deploy latest commit** on the Render service. Connecting the GitHub repository through Render's Git-provider credentials enables automatic deployments. See [Render's deployment documentation](https://render.com/docs/deploys).

## Storage and performance

`RUNTIME_DIR=/var/data/fuel-planner-data` places SQLite, route/geocoding caches, and request/provider
throttle state on the persistent disk. Saved route IDs survive service restarts and
deploys. The single Gunicorn worker has two threads to keep memory use modest and
reduce SQLite contention. This setup is suitable for a low-traffic assessment demo;
move to PostgreSQL and a shared cache before adding replicas or serving substantial
concurrent traffic.

The paid service remains running instead of sleeping after inactivity. The public routing and
geocoding providers still have network latency and availability limits. A repeated
route can reuse cached provider responses; a first request needs live upstream calls.
There is no background traffic used to keep providers or hosting awake.

Render disks attach to one instance, so deploys with a disk have a short interruption.
Use a consistent SQLite backup for any route history that must be retained; do not
rely on a live filesystem snapshot for database recovery. This demo database is not
a replacement for a managed production datastore.
The station catalog can always be recreated from the committed CSVs.

## Security settings

Production startup rejects missing/weak secret keys and empty or wildcard allowed
hosts. It requires HTTPS (except the public readiness probe), sets secure cookies and
security headers, and trusts
`X-Forwarded-Proto` only in Render's environment or when
`DJANGO_TRUST_PROXY_HEADERS=1` is explicitly set behind a trusted proxy. Do not enable
that flag for a server directly exposed to clients. Gunicorn uses the same policy.

HSTS starts at one hour on this demo's exact hostname. `includeSubDomains` and browser
preloading are intentionally disabled until domain ownership and long-term HTTPS
availability are confirmed. Consequently `python manage.py check --deploy` reports
the advisory warnings `security.W005` and `security.W021`; all other deployment
warnings should be investigated. No Django administration or login is exposed.

Run `python manage.py test` for the automated suite. The production tests separately
start Django with `DEBUG=0`, reject unsafe host/secret configuration, check forwarded
header handling, collect static files, and verify hashed CSS is actually served.

## Manual host settings

If creating a Render Web Service manually, use:

| Setting | Value |
| --- | --- |
| Runtime | Python |
| Python version | `3.13.15` |
| Build command | `bash scripts/build.sh` |
| Start command | `bash scripts/start.sh` |
| Health check | `/api/health/` |
| Instance | `0.5c-512mb` (0.5 CPU / 512 MB) |
| Disk | 1 GB at `/var/data` |
| `DJANGO_DEBUG` | `0` |
| `DJANGO_SECRET_KEY` | Fresh random value of at least 50 characters |
| `DJANGO_TRUST_PROXY_HEADERS` | `1` on Render |
| `RUNTIME_DIR` | `/var/data` |
| `GUNICORN_CMD_ARGS` | Empty, so the repository's configuration applies |

The app accepts Render's `PORT` automatically. On another hosting platform, also set
`DJANGO_ALLOWED_HOSTS` to the exact hostname. Environment values must be configured
through the host; `.env.example` is documentation and is not automatically loaded.

For a local production smoke run, set a fresh secret, `DJANGO_DEBUG=0`,
`DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost`, `RUNTIME_DIR=.runtime`, and
`DJANGO_SECURE_SSL_REDIRECT=0` for the HTTP-only loopback test. Leave proxy trust off,
collect static files, and run `bash scripts/start.sh` with the virtual environment
activated. Never disable HTTPS redirects on the public service.

## If switching to free hosting

Change the plan to `free`, remove the disk block, and use `RUNTIME_DIR=.runtime`.
Render's free service sleeps after 15 minutes of inactivity and may take about one
minute to wake. Its filesystem is discarded on restarts, redeploys, and spin-downs,
so saved route IDs and caches disappear; startup rebuilds only the station catalog.
Those limitations make the always-on persistent configuration preferable for review.

## References

- [Render Django deployment](https://render.com/docs/deploy-django)
- [Render environment variables](https://render.com/docs/environment-variables)
- [Render persistent disks](https://render.com/docs/disks)
- [Render free instance limitations](https://render.com/docs/free)
- [WhiteNoise Django integration](https://whitenoise.readthedocs.io/en/stable/django.html)
