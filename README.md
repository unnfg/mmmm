## Getting Started

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) ≥ 4.x
- [uv](https://docs.astral.sh/uv/) (for local development outside Docker)

### Environment Setup

```bash
cp .env.example .env
```

Required variables in `.env`:

```env
POSTGRES_USER=postgres
POSTGRES_PASSWORD=changeme
POSTGRES_DB=mmmm
SECRET_KEY=your-secret-key
FIRST_SUPERUSER=admin@example.com
FIRST_SUPERUSER_PASSWORD=changeme
```

---

## Running the Application

### Local Development

```bash
docker compose up --build
```

`compose.override.yml` is automatically merged — enables hot-reload and exposes database ports.

| Service | URL |
|---|---|
| API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |
| Adminer (DB UI) | http://localhost:8080 |
| PostgreSQL | localhost:5432 |
| Redis | localhost:6379 |

> Code changes in `./app` are reflected instantly without rebuilding.

### Production

```bash
docker compose -f compose.yml up -d
```

| Service | URL |
|---|---|
| API | http://localhost:8000 |
| Adminer (DB UI) | http://localhost:8080 |

---

## Startup Sequence

```
db (healthy)
    └── redis (healthy)
            └── prestart
                    ├── pre_start.py        → wait for DB
                    ├── alembic upgrade head → apply migrations
                    └── initial_data.py     → seed initial data
                            └── api         → start server
```

`api` only starts after `prestart` exits with code 0.

---

## Development

### Install dependencies locally

```bash
uv sync
```

### Run tests

```bash
uv run pytest
```

### Lint & format

```bash
uv run ruff check .
uv run ruff format .
```

### Type check

```bash
uv run ty check
```

---

## Database

### Apply migrations

```bash
docker compose run --rm prestart bash -c "cd /app && .venv/bin/alembic upgrade head"
```

### Rollback last migration

```bash
docker compose run --rm prestart bash -c "cd /app && .venv/bin/alembic downgrade -1"
```

### Create a new migration

```bash
uv run alembic revision --autogenerate -m "describe your change"
```

### Open DB shell

```bash
docker compose exec db psql -U postgres -d mmmm
```

### List tables

```bash
docker compose exec db psql -U postgres -d mmmm -c "\dt"
```

---

## Redis

```bash
docker compose exec redis redis-cli
```

---

## Docker Reference

| Command | Description |
|---|---|
| `docker compose up --build` | Rebuild and start all services |
| `docker compose up -d` | Start in background |
| `docker compose down` | Stop all services |
| `docker compose down -v` | Stop and delete all data |
| `docker compose logs -f api` | Stream API logs |
| `docker compose logs prestart` | View migration logs |

---

## Environment Files

| File | Purpose |
|---|---|
| `.env` | Local secrets — **never commit** |
| `.env.example` | Template — commit this |

---

## Notes

- `initial_data.py` is idempotent — safe to run multiple times, will not duplicate data.
- `Dockerfile` installs production dependencies only (`--no-dev`).
- `Dockerfile.dev` installs all dependencies including dev group.
- `UV_CACHE_DIR` is set to `/tmp/uv-cache` in both Dockerfiles to avoid permission issues with the non-root `appuser`.