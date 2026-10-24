FROM node:22-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914 AS frontend
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run typecheck && npm run build

FROM python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534 AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    PORT=8000 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    PATH="/app/.venv/bin:$PATH" \
    GAME_DISCOVERY_BUNDLE=/app/models/release/selected_candidate \
    GAME_DISCOVERY_ALS_COMPARISON=/app/models/release/alternates/als \
    GAME_DISCOVERY_EVALUATION=/app/artifacts/reports/final_test.json

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir uv==0.13.5 && uv sync --locked --no-dev
COPY --from=frontend /src/game_discovery/web ./src/game_discovery/web
COPY models/release/selected_candidate ./models/release/selected_candidate
COPY models/release/alternates/als ./models/release/alternates/als
COPY artifacts/reports/final_test.json ./artifacts/reports/final_test.json

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 CMD ["python", "-c", "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8000')+'/readyz', timeout=2)"]
USER 10001:10001
CMD ["sh", "-c", "uvicorn game_discovery.api:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
