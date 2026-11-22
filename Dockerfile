FROM ghcr.io/astral-sh/uv:0.12.7 AS uv
FROM python:3.12-slim

COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV PYTHONUNBUFFERED=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH" RADAR_DB=/app/data/product-hunt.sqlite3

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --no-editable \
    && useradd --uid 10001 --no-create-home radar \
    && install -d -o radar -g radar /app/data

USER radar
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "ai_buzz_radar.web:create_app()"]
