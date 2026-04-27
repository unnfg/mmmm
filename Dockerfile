FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml .
COPY uv.lock* .

# Run dependencies
RUN uv sync --frozen --no-dev

# Copy src code
COPY . .

# Run in production(no --reload -> optmize worker + threads)
CMD ["uv", "run", "granian", "--interface", "asgi", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4", "--threads", "2", "--no-access-log"]
