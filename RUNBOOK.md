# Runbook

## Live Render service

Open [Game Discovery](https://game-discovery-ml.onrender.com). It runs as one Free image-backed web service in Singapore; feedback is disabled. Idle suspension is expected and waking may take about a minute. There are no keep-alive pings, persistent disks or databases.

Service dashboard: `https://dashboard.render.com/web/srv-dbeij13ncjis73ec72n0`. The deployed registry digest and source identity are in [deploy/render/release.json](deploy/render/release.json). To check readiness, GET `/readyz`; liveness is `/healthz`. The bounded verification command is:

```powershell
python scripts/smoke_http.py --base-url https://game-discovery-ml.onrender.com --catalog-version 2ce5fc7db7f31ffcea7c06a827b46493aa7f9f738cf409c15ffdc70008eed841 --output artifacts/deployment/render_cloud_smoke.json
```

To update, publish a reviewed serving image to the same Docker Hub repository, retain its immutable digest and prior images, edit this service's image reference, and deploy manually. Render's Deploys page provides rollback after a previous successful deployment exists. The initial launch, an owner-approved same-image replacement and rollback to the first successful deployment were verified on 2026-10-25; every stage passed 45 HTTPS checks. This exercises deployment revisions using the same saved model, not switching trained models. A rollback may briefly interrupt access; check readiness and identity after it completes.

To shut down, open **Settings > Suspend Web Service** for exactly `game-discovery-ml` (`srv-dbeij13ncjis73ec72n0`). To remove hosting permanently, use **Delete Web Service** only after checking that same name and service ID and obtaining deletion authorization. Keep the source repository and registry image unless separately instructed to remove them. Do not modify unrelated workspace services.

## Start the app

Requires Docker Desktop, ignored local release artifacts from the M4 export, and Docker build access.

```powershell
docker build -t game-discovery:local .
docker run --rm --name game-discovery-local -p 127.0.0.1:8000:8000 game-discovery:local
```

Open `http://127.0.0.1:8000`. Readiness is `/readyz`; liveness is `/healthz`. Stop with Ctrl+C or `docker stop game-discovery-local`. Feedback remains disabled unless a separately reviewed durable store and stable signing secret are explicitly configured.

## Validate local changes

Linux training/CI environments need the OpenMP runtime used by `implicit`: on Debian/Ubuntu install `libgomp1` before running the training extra. The inference-only image does not import `implicit` and does not need that training library. GitHub CI installs this prerequisite explicitly.

```powershell
uv sync --extra train --extra dev
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
docker run --rm -v "${PWD}/web:/web" -w /web node:22 npm ci
```

Frontend typecheck/build/audit are run in the Docker build image. See the CI workflow for the maintained checks.

## Lifecycle and data protection

- Keep raw source files, user-level evaluation, private mappings and private events in ignored local paths. Only the owner-authorized item-only serving assets and aggregate evaluation enter the published image; source-term uncertainty remains documented.
- Never enable API feedback on an ephemeral container filesystem.
- Monitor real service data only after cloud deployment and privacy review. Synthetic replay reports are not real traffic.
- Use the provider-specific steps in [DEPLOYMENT.md](DEPLOYMENT.md). Preserve the Render Free plan and no-card configuration; make no paid upgrade. Suspend or delete only the named project service with the applicable authorization.
- If model readiness fails, keep the app unavailable rather than changing the model label or silently falling back to an unverified bundle. Verify bundle hashes and rebuild the reviewed image.

## Known limitations

The HTTPS inference service, bounded functional smoke and same-image deployment revision recovery are verified. No durable store, real feedback or capacity benchmark is verified. Local model promotion/rollback evidence uses synthetic or validation-only inputs; cloud recovery used the same image. The frozen final test must not be rerun or used to change the selected model.
