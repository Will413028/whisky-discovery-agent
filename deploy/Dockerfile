FROM ghcr.io/astral-sh/uv:0.12.9@sha256:8b940d3a9d65bed080436972241af2e21c84b5e8c9193f7014ed71479ee795ff AS uv
FROM python:3.13.13-slim-bookworm@sha256:355bfa66770995d7e9a0da4b3473b44d0cb451f6b56f5615ad9c39e3c4eca03f AS build
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
COPY backend/src ./src
COPY backend/migrations ./migrations
ENV UV_PYTHON_DOWNLOADS=never UV_HTTP_TIMEOUT=120
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --python /usr/local/bin/python

FROM python:3.13.13-slim-bookworm@sha256:355bfa66770995d7e9a0da4b3473b44d0cb451f6b56f5615ad9c39e3c4eca03f
COPY --from=build /app/backend/.venv /app/backend/.venv
ENV PATH="/app/backend/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN install -d -o 10001 -g 10001 -m 700 /var/tmp/whisky-export
USER 10001:10001
EXPOSE 8417
CMD ["whisky-api", "--host", "0.0.0.0", "--port", "8417"]
