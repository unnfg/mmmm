FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

ENV UV_NO_CACHE=1

COPY pyproject.toml .
COPY uv.lock* .

# Run dependencies
RUN uv sync --frozen --no-dev

# Copy src code
COPY . .

# By default, Docker runs as root. If the app is compromised, the attacker
# gets root inside the container — full write access to the filesystem and
# any mounted volumes.
# So, creating a dedicated non-root user limits the blast radius:
# the attacker is locked to appuser's permissions only.
# Fix permissions AFTER copying files - chown -R appuser:appuser /app
RUN adduser --disabled-password --no-create-home appuser && \
    chown -R appuser:appuser /app

USER appuser

# Run in production(no --reload -> optmize worker + threads)
CMD ["uv", "run", "granian", "--interface", "asgi", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "4", "--threads", "2", "--no-access-log"]
