**Quick Start**

1. **Navigate**
```bash
cd mmmm
```

2. **Environment Setup**
```bash
cp .env.example .env
```

3. **Build & Launch**
```bash
docker compose up --build
```

**Verification**
* FastAPI Server: http://localhost:8000
* Swagger UI: http://localhost:8000/docs
* PostgreSQL: Port 5432
* Redis: Port 6379
* Hot-reload: Enabled (Server auto-reloads when code is modified)

**Common Commands**
- **Stop:** `docker compose down`
- **Background Mode:** `docker compose up -d`
- **Logs:** `docker compose logs -f api`
- **Reset Data:** `docker compose down -v`
- **Rebuild after dependency change:** `docker compose up --build`
- **Run migrations:** `docker compose exec api alembic upgrade head`
- **Rollback migration:** `docker compose exec api alembic downgrade -1`
- **Open DB shell:** `docker compose exec db psql -U comuser -d comdb`
- **Open Redis shell:** `docker compose exec redis redis-cli`