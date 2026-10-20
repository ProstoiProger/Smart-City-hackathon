# syntax=docker/dockerfile:1
# Astana Walk. Targets:
#   app        production image: FastAPI + built frontend, container port 8000 (host port set in compose)
#   dev        app + tests and scripts (pytest, review-signal extraction, QA)
#   collector  data collectors (2GIS reviews, OSM, sources) with their own dependencies
#   ui         frontend build only (tsc + i18n validation + vite)

FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements-lock.txt ./
RUN pip install -r requirements-lock.txt
RUN useradd --create-home --uid 10001 walker

FROM base AS app
COPY --chown=walker backend/ ./backend/
COPY --chown=walker data/ ./data/
COPY --chown=walker run.py ./
COPY --from=ui --chown=walker /ui/dist ./frontend/dist/
USER walker
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"
CMD ["python", "run.py", "--host", "0.0.0.0", "--port", "8000"]

FROM app AS dev
COPY --chown=walker tests/ ./tests/
COPY --chown=walker scripts/ ./scripts/
COPY --chown=walker qa/rag_cases.json ./qa/rag_cases.json
CMD ["python", "-m", "pytest", "tests", "-q"]

FROM python:3.13-slim AS collector
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app/collector
COPY collector/requirements.txt ./
RUN pip install -r requirements.txt pytest
RUN useradd --create-home --uid 10001 walker
COPY --chown=walker collector/ ./
# Collector modules create their raw/processed caches on import.
RUN mkdir -p data/raw data/processed output && chown -R walker /app/collector
USER walker
ENTRYPOINT ["python"]
CMD ["-m", "pytest", "tests", "-q"]
