# Local runbook

## Start the app

Requires Docker Desktop, ignored local release artifacts from the M4 export, and Docker build access.

```powershell
docker build -t game-discovery:local .
docker run --rm --name game-discovery-local -p 127.0.0.1:8000:8000 game-discovery:local
```

Open `http://127.0.0.1:8000`. Readiness is `/health/ready`; liveness is `/health/live`. Stop with Ctrl+C or `docker stop game-discovery-local`. Feedback remains disabled unless a separately reviewed durable store and stable signing secret are explicitly configured.

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

- Keep raw source files, user-level evaluation, private mappings, model artifacts and deployment evidence in ignored local paths until redistribution rights are resolved.
- Never enable API feedback on an ephemeral container filesystem.
- Monitor real service data only after cloud deployment and privacy review. Synthetic replay reports are not real traffic.
- If cloud access becomes available, use the exact steps in [DEPLOYMENT.md](DEPLOYMENT.md). Keep the subscription spending limit enabled, record the shutdown date, and destroy only resources whose project ownership tags were verified.
- If model readiness fails, keep the app unavailable rather than changing the model label or silently falling back to an unverified bundle. Verify bundle hashes and rebuild the reviewed image.

## Known limitations

No cloud service, persistent store, real feedback, load test, or deployment rollback has been verified. The local promotion ledger and rollback evidence are synthetic/validation-only. The local container is the current supported runtime.
