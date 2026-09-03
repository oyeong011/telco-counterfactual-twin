FROM ghcr.io/astral-sh/uv:0.11.6 AS uv

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=uv /uv /uvx /usr/local/bin/
COPY backend/pyproject.toml backend/uv.lock backend/
RUN uv sync --project backend --locked --no-dev
COPY backend/src backend/src
COPY backend/fixtures/scenarios backend/fixtures/scenarios
COPY backend/tests/fixtures/approval backend/tests/fixtures/approval
COPY specs/schemas specs/schemas
RUN useradd --uid 10001 --create-home twin && chown -R twin:twin /app
USER twin
EXPOSE 8080
CMD ["uv","run","--no-sync","--project","backend","uvicorn","telco_twin.api.app:app","--app-dir","backend/src","--host","0.0.0.0","--port","8080"]
