# Render Free deployment

Status: limited inference deployment authorized and in progress; no verified live Render service yet. The owner selected Render on 2026-10-25. The signed-in dashboard shows a Hobby workspace, no card on file, and $0 accrued charges. The owner explicitly authorized publishing the item model, historical catalog and aggregate statistics while retaining raw data and user records privately. `DATA_CARD.md` records this decision and source-terms uncertainty; no publisher permission or permissive license is claimed.

## Resource plan

- One **Web Service**, Free compute plan, one instance, Linux amd64.
- Existing FastAPI app and TypeScript interface run together in the existing Dockerfile.
- Port `10000`; readiness `/readyz`; one Uvicorn worker and one BLAS thread.
- Suggested region: Singapore, subject to availability in the account.
- No database, disk, worker, registry created by Render, or paid workspace upgrade.
- Feedback is disabled. Do not set the event-signing secret or attach the local test store.
- Render may stop the app after 15 minutes of inactivity; the next request can take about a minute to wake it. Local writes do not survive replacement or idle suspension. No keep-alive pings.
- Workspace free hours, bandwidth and build allowance are shared with existing apps. Preserve the no-card configuration; account verification and service-plan selection must be rechecked at launch.

Official references checked 2026-10-25: [Free services](https://render.com/docs/free), [compute plans](https://render.com/docs/compute-plans), [prebuilt images](https://render.com/docs/deploying-an-image), [Blueprint fields](https://render.com/docs/blueprint-spec).

## Stage and verify locally

```powershell
uv run python deploy/render/prepare.py
docker build --platform linux/amd64 -t game-discovery:render .
docker run --rm --name game-discovery-render-check --memory 512000000 --memory-swap 512000000 --cpus 0.1 -e PORT=10000 -p 127.0.0.1:18081:10000 game-discovery:render
```

`prepare.py` verifies the champion and ALS hashes/privacy flags, checks the saved test report's split identity, and creates an allowlisted archive and hash manifest in ignored `artifacts/deployment`. It never uploads anything and does not rerun evaluation. Staging itself does not establish a dataset license; the owner decision and attribution are documented separately.

With the container running, use `scripts/smoke_http.py` against the local service. It checks readiness/model identity, static assets, popular/tail/cold/unknown profiles, 20-seed requests, all three model modes, duplicate/seed exclusions, and truthful rejection of disabled feedback. It makes 45 requests within a shared 60-second deadline, with maximum concurrency 5, using synthetic visitor inputs against the real bundle. This is a bounded functional smoke, not a cloud latency benchmark.

## Publish and launch the authorized serving bundle

1. Build/recheck the exact runtime image, then publish it to a user-controlled registry. Keep raw data, private events and training artifacts out of the image. This repo's code-only GitHub checkout cannot build the real-data image: release assets are deliberately ignored. Use the local verified build context rather than silently replacing the model with fixtures.
2. Record the **registry manifest digest** returned by the push. A Docker local image ID is not a substitute for a pushed registry digest. Retain the previous image digest for rollback.
3. Generate a concrete Blueprint using the actual registry reference:

   ```powershell
   uv run python deploy/render/prepare.py --image-reference <registry>/<owner>/<image>@sha256:<registry-digest>
   ```

   The generated `artifacts/deployment/render.yaml` contains exactly one Free web service, its environment settings, image reference, and readiness path. It is valid YAML encoded as JSON. It contains no credentials and does not create a service by itself.

4. In Render, choose **New > Web Service > Existing Image**. Enter the digest-pinned reference. For a private registry, configure its read-only pull credential directly in Render; keep it out of Git and chat. Render supports private GitHub Container Registry and Docker Hub images.
5. Name the service `game-discovery-ml`, select **Free**, choose the region, set `PORT=10000`, `OMP_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1`, and `MKL_NUM_THREADS=1`, and set health check path `/readyz`. Review the resource plan before selecting Deploy. Do not select a paid plan, disk, database or workspace upgrade.
6. After the deploy is live, verify its actual HTTPS URL from outside Docker. Check model/catalog identity, UI comparisons, disabled feedback, logs, memory and errors. Save the deployed image digest, code commit and a bounded smoke report locally. Do not call the deployment cloud verified before this succeeds.

## Update, rollback and shutdown

Image-backed services do not automatically redeploy when a tag changes. Keep immutable registry digests and trigger reviewed manual deploys. Render Free supports rollback to the two most recent previous deploys; images must remain pullable from their registry. After rollback, recheck `/readyz` and model identity before returning to the chosen image.

To stop hosting, open this service's settings and delete **only** `game-discovery-ml` after verifying its service ID and image. Confirm Render no longer lists it. Review whether the separately published registry images or private source repository should be retained. Do not delete unrelated services in the shared workspace.
