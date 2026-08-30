# AI Restaurant Receptionist — Backend

FastAPI backend for the AI Restaurant Receptionist. See the repository
root for full documentation:

- [`../DEVELOPMENT_STATUS.md`](../DEVELOPMENT_STATUS.md) — what's built, phase by phase
- [`../docs/architecture.md`](../docs/architecture.md) — system design and decision log
- [`../docs/setup.md`](../docs/setup.md) — local setup instructions
- [`../docs/roadmap.md`](../docs/roadmap.md) — documented gaps and future work

## Quick start

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

## Tests

```bash
pytest tests/ -v
ruff check app/ tests/
mypy app/
```
