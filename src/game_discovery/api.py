from __future__ import annotations

import json
import os
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from game_discovery.events.base import EventStore
from game_discovery.events.local import LocalEventStore
from game_discovery.events.tokens import (
    InvalidImpressionToken,
    create_impression_token,
    verify_impression_token,
)
from game_discovery.serving.bundle import RecommendationBundle


class RecommendationRequest(BaseModel):
    seed_item_ids: list[StrictStr] = Field(default_factory=list, max_length=20)
    exclude_item_ids: list[StrictStr] = Field(default_factory=list, max_length=100)
    genres: list[StrictStr] = Field(default_factory=list, max_length=20)
    k: StrictInt = Field(default=10, ge=1, le=20)
    model: Literal["champion", "recent_popularity", "als"] = "champion"


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    event_type: Literal["click", "save", "dismiss"]
    item_id: StrictStr = Field(min_length=1, max_length=64)
    impression_token: StrictStr = Field(min_length=1, max_length=2048)


def _load_public_evaluation(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    report = json.loads(path.read_text(encoding="utf-8"))
    candidate = report.get("candidate", {})
    baseline = report.get("recent_30d_popularity_baseline", {})
    return {
        "evaluation_split": report.get("evaluation_split"),
        "split_manifest_sha256": report.get("split_manifest_sha256"),
        "candidate": {
            "name": candidate.get("name"),
            "warm_catalog_ranking": candidate.get("warm_catalog_ranking"),
            "mean_all_target_recall_by_user": candidate.get("mean_all_target_recall_by_user"),
            "catalog_coverage_at_10": candidate.get("catalog_coverage_at_10"),
            "tail_exposure_share_at_10": candidate.get("tail_exposure_share_at_10"),
        },
        "recent_30d_popularity_baseline": {
            "warm_catalog_ranking": baseline.get("warm_catalog_ranking"),
            "mean_all_target_recall_by_user": baseline.get("mean_all_target_recall_by_user"),
            "catalog_coverage_at_10": baseline.get("catalog_coverage_at_10"),
            "tail_exposure_share_at_10": baseline.get("tail_exposure_share_at_10"),
        },
        "paired_ndcg_at_10_candidate_minus_recent30": report.get(
            "paired_ndcg_at_10_candidate_minus_recent30"
        ),
        "warm_catalog_users": report.get("warm_catalog_users"),
        "future_target_users": report.get("future_target_users"),
    }


def create_app(
    bundle_dir: Path | None = None,
    *,
    als_model_dir: Path | None = None,
    evaluation_path: Path | None = None,
    web_dir: Path | None = None,
    event_store: EventStore | None = None,
    event_signing_secret: bytes | str | None = None,
    event_stream: Literal["real_demo", "replay", "synthetic_test"] = "real_demo",
) -> FastAPI:
    if event_stream not in ("real_demo", "replay", "synthetic_test"):
        raise ValueError("event_stream must be real_demo, replay or synthetic_test")
    if isinstance(event_store, LocalEventStore) and event_stream != "synthetic_test":
        raise ValueError("LocalEventStore is restricted to the synthetic_test stream")
    selected_bundle_dir = bundle_dir or Path(
        os.environ.get("GAME_DISCOVERY_BUNDLE", "models/release/selected_candidate")
    )
    selected_als_dir = als_model_dir or Path(
        os.environ.get("GAME_DISCOVERY_ALS_COMPARISON", "models/release/alternates/als")
    )
    selected_evaluation_path = evaluation_path or Path(
        os.environ.get("GAME_DISCOVERY_EVALUATION", "artifacts/reports/final_test.json")
    )
    selected_web_dir = web_dir or Path(__file__).parent / "web"
    configured_secret = event_signing_secret
    if configured_secret is None:
        configured_secret = os.environ.get("GAME_DISCOVERY_EVENT_SIGNING_SECRET")
    if isinstance(configured_secret, str):
        configured_secret = configured_secret.encode("utf-8")
    app = FastAPI(
        title="Game Discovery",
        version="0.1.0",
        description="Historical game-interest discovery using transparent, CPU-friendly rankings.",
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.bundle = None
    app.state.als_model = None
    app.state.artifact_error = None
    app.state.public_evaluation = _load_public_evaluation(selected_evaluation_path)
    app.state.event_store = event_store
    app.state.event_stream = event_stream
    app.state.event_signing_secret = configured_secret
    app.state.feedback_enabled = event_store is not None and configured_secret is not None
    app.state.feedback_mode = (
        "disabled"
        if not app.state.feedback_enabled
        else "local_test_only"
        if isinstance(event_store, LocalEventStore)
        else "configured_store"
    )
    app.state.event_rate_limit: dict[str, tuple[int, int]] = {}
    app.state.request_counts = Counter()
    app.state.request_duration_sum = defaultdict(float)
    app.state.fallback_count = 0
    app.state.ready = False
    try:
        app.state.bundle = RecommendationBundle(selected_bundle_dir)
        if selected_als_dir.is_dir():
            from game_discovery.serving.als import ALSComparisonModel

            app.state.als_model = ALSComparisonModel(selected_als_dir)
        app.state.catalog_by_id = {item["item_id"]: item for item in app.state.bundle.catalog}
        app.state.ready = True
    except (OSError, ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        app.state.artifact_error = type(exc).__name__

    @app.middleware("http")
    async def measure_request(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - started
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        status = str(response.status_code)
        app.state.request_counts[(path, status)] += 1
        app.state.request_duration_sum[path] += elapsed
        response.headers["X-Processing-Time-Ms"] = f"{elapsed * 1000:.2f}"
        return response

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(selected_web_dir / "index.html")

    app.mount("/static", StaticFiles(directory=selected_web_dir), name="static")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "healthy"}

    @app.get("/readyz")
    def readyz():
        if not app.state.ready:
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "reason": "model_artifact_unavailable"},
            )
        return {
            "status": "ready",
            "model_version": app.state.bundle.manifest["model_version"],
            "catalog_version": app.state.bundle.manifest["split_manifest_sha256"],
            "als_comparison_available": app.state.als_model is not None,
        }

    def require_bundle() -> RecommendationBundle:
        if not app.state.ready:
            raise HTTPException(status_code=503, detail="Recommendation artifact is not ready")
        return app.state.bundle

    @app.get("/v1/catalog")
    def catalog(
        q: str = Query(default="", max_length=100),
        limit: int = Query(default=20, ge=1, le=50),
        sort: Literal["recent_popularity", "tail"] = "recent_popularity",
    ) -> dict[str, Any]:
        bundle = require_bundle()
        query = q.strip().casefold()
        items = bundle.catalog
        if query:
            items = [
                item
                for item in items
                if query in item["title"].casefold()
                or any(query in value.casefold() for value in item["genres"])
                or any(query in value.casefold() for value in item["tags"])
            ]
        if sort == "tail":
            items = sorted(
                items, key=lambda item: (item["recent_30d_interactions"], item["item_id"])
            )
        else:
            items = sorted(
                items,
                key=lambda item: (-item["recent_30d_interactions"], item["item_id"]),
            )
        items = items[:limit]
        return {
            "catalog_version": bundle.manifest["split_manifest_sha256"],
            "count": len(items),
            "items": [
                {
                    "item_id": item["item_id"],
                    "title": item["title"],
                    "genres": item["genres"],
                    "tags": item["tags"],
                }
                for item in items
            ],
        }

    @app.post("/v1/recommendations")
    def recommendations(payload: RecommendationRequest, request: Request) -> dict[str, Any]:
        bundle = require_bundle()
        started = time.perf_counter()
        if payload.model in ("champion", "recent_popularity"):
            result = bundle.recommend(
                payload.seed_item_ids,
                exclude_item_ids=payload.exclude_item_ids,
                genres=payload.genres,
                k=payload.k,
                model=payload.model,
            )
            catalog_version = bundle.manifest["split_manifest_sha256"]
        else:
            als = app.state.als_model
            if als is None:
                raise HTTPException(status_code=503, detail="ALS comparison model is unavailable")
            genre_set = {genre.casefold() for genre in payload.genres}
            allowed_ids = (
                {
                    item_id
                    for item_id, item in app.state.catalog_by_id.items()
                    if genre_set.intersection(genre.casefold() for genre in item["genres"])
                }
                if payload.genres
                else None
            )
            als_result = als.recommend(
                payload.seed_item_ids,
                exclude_item_ids=payload.exclude_item_ids,
                allowed_item_ids=allowed_ids,
                k=payload.k,
            )
            if als_result["fallback_reason"] == "no_seed_in_als_catalog":
                result = bundle.recommend(
                    payload.seed_item_ids,
                    exclude_item_ids=payload.exclude_item_ids,
                    genres=payload.genres,
                    k=payload.k,
                    model="recent_popularity",
                )
                result["fallback_reason"] = "no_seed_in_als_catalog"
                catalog_version = bundle.manifest["split_manifest_sha256"]
            else:
                als_items = []
                for prediction in als_result["recommendations"]:
                    item = app.state.catalog_by_id.get(prediction["item_id"])
                    if item is None or (
                        genre_set
                        and not genre_set.intersection(genre.casefold() for genre in item["genres"])
                    ):
                        continue
                    als_items.append(
                        {
                            "item_id": item["item_id"],
                            "title": item["title"],
                            "genres": item["genres"],
                            "tags": item["tags"],
                            "release_date": item["release_date"],
                            "ranking_score": prediction["ranking_score"],
                            "explanation": "Collaborative ALS score from games you selected; score is not a probability.",
                            "explanation_evidence": {"algorithm": als_result["model"]},
                        }
                    )
                    if len(als_items) == payload.k:
                        break
                result = {
                    "model_version": als.manifest["source_configuration"],
                    "model": als_result["model"],
                    "recommendations": als_items,
                    "fallback_reason": (
                        "no_candidates_match_genres"
                        if payload.genres
                        and als_result["fallback_reason"] == "no_candidates_match_filter"
                        else als_result["fallback_reason"]
                    ),
                    "unknown_seed_count": als_result["unknown_seed_count"],
                    "requested_k": payload.k,
                    "returned_count": len(als_items),
                }
                catalog_version = als.manifest["split_manifest_sha256"]
        elapsed_ms = (time.perf_counter() - started) * 1000
        if result.get("fallback_reason"):
            app.state.fallback_count += 1
        response = {
            "request_id": str(uuid4()),
            "model_version": result["model_version"],
            "catalog_version": catalog_version,
            "mode": result["model"],
            "fallback_reason": result.get("fallback_reason"),
            "unknown_seed_count": result.get("unknown_seed_count", 0),
            "duplicate_seed_count": result.get("duplicate_seed_count", 0),
            "requested_k": payload.k,
            "returned_count": len(result["recommendations"]),
            "server_processing_ms": elapsed_ms,
            "recommendations": result["recommendations"],
            "feedback_enabled": app.state.feedback_enabled,
        }
        if app.state.feedback_enabled and result["recommendations"]:
            response["impression_token"] = create_impression_token(
                secret=app.state.event_signing_secret,
                model_version=result["model_version"],
                item_ids=[item["item_id"] for item in result["recommendations"]],
            )
        return response

    @app.get("/v1/model-info")
    def model_info() -> dict[str, Any]:
        bundle = require_bundle()
        return {
            "model_version": bundle.manifest["model_version"],
            "catalog_version": bundle.manifest["split_manifest_sha256"],
            "selected_candidate": bundle.manifest["selected_candidate"],
            "comparison_models": ["recent30_popularity", "implicit_als_validation_reference"],
            "als_comparison_available": app.state.als_model is not None,
            "data_task": "future review-interaction ranking",
            "limitations": [
                "A review interaction does not establish that a user liked a game.",
                "The catalog and item metadata are historical snapshots, not current storefront facts.",
                "The selected content model uses an untimestamped historical metadata snapshot.",
                "The ALS comparison model is a validation-era reference and is not the selected champion.",
                "No causal engagement or purchase outcome is measured.",
            ],
            "feedback": {
                "enabled": app.state.feedback_enabled,
                "mode": app.state.feedback_mode,
                "retention_days": 30 if app.state.feedback_enabled else None,
                "per_session_per_minute": 30 if app.state.feedback_enabled else None,
                "rate_limit_distributed": False,
                "reason": None
                if app.state.feedback_enabled
                else "No event store and signing secret are configured.",
            },
            "evaluation": app.state.public_evaluation,
        }

    @app.post("/v1/events")
    async def submit_event(request: Request) -> JSONResponse:
        if not app.state.feedback_enabled:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "disabled",
                    "persisted": False,
                    "reason": "No event store and signing secret are configured.",
                },
            )
        body = await request.body()
        if len(body) > 8192:
            raise HTTPException(status_code=413, detail="Feedback event body exceeds 8 KiB")
        try:
            payload = FeedbackRequest.model_validate_json(body)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail="Invalid feedback event schema") from exc
        try:
            impression = verify_impression_token(
                payload.impression_token,
                secret=app.state.event_signing_secret,
                item_id=payload.item_id,
            )
        except InvalidImpressionToken as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        current_minute = int(time.time() // 60)
        stale_sessions = [
            session_id
            for session_id, (minute, _) in app.state.event_rate_limit.items()
            if minute < current_minute - 1
        ]
        for session_id in stale_sessions:
            del app.state.event_rate_limit[session_id]
        minute, count = app.state.event_rate_limit.get(
            impression["session_id"], (current_minute, 0)
        )
        if minute != current_minute:
            minute, count = current_minute, 0
        if count >= 30:
            raise HTTPException(status_code=429, detail="Feedback rate limit exceeded")
        app.state.event_rate_limit[impression["session_id"]] = (minute, count + 1)
        if len(app.state.event_rate_limit) > 5000:
            oldest = sorted(
                app.state.event_rate_limit,
                key=lambda session_id: app.state.event_rate_limit[session_id][0],
            )[:1000]
            for session_id in oldest:
                del app.state.event_rate_limit[session_id]
        record = {
            "event_id": str(payload.event_id),
            "event_type": payload.event_type,
            "item_id": payload.item_id,
            "rank": impression["item_ids"].index(payload.item_id) + 1,
            "session_id": impression["session_id"],
            "model_version": impression["model_version"],
            "received_at": datetime.now(UTC).isoformat(),
            "event_stream": app.state.event_stream,
        }
        try:
            created = app.state.event_store.put_if_absent(str(payload.event_id), record)
        except (OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=503, detail="Feedback storage failed") from exc
        return JSONResponse(
            status_code=201 if created else 200,
            content={
                "status": "persisted" if created else "duplicate",
                "persisted": True,
                "duplicate": not created,
                "retention_days": 30,
            },
        )

    @app.get("/metrics")
    def metrics(request: Request) -> Response:
        host = request.client.host if request.client else ""
        local = host in {"127.0.0.1", "::1", "testclient"}
        enabled = os.environ.get("GAME_DISCOVERY_METRICS_ENABLED", "false").casefold() == "true"
        if not local and not enabled:
            raise HTTPException(status_code=404, detail="Not found")
        lines = [
            "# HELP game_discovery_requests_total Requests by route and HTTP status.",
            "# TYPE game_discovery_requests_total counter",
        ]
        for (route, status), count in sorted(app.state.request_counts.items()):
            lines.append(
                f'game_discovery_requests_total{{route="{route}",status="{status}"}} {count}'
            )
        lines.extend(
            [
                "# HELP game_discovery_fallbacks_total Recommendation requests using a fallback.",
                "# TYPE game_discovery_fallbacks_total counter",
                f"game_discovery_fallbacks_total {app.state.fallback_count}",
            ]
        )
        return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")

    return app


app = create_app()
