# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Sports betting system (`sistema-apuestas-deportivas`) — academic project for the Software Architecture course at UTPL, 2026.

## Tech Stack (from .gitignore)

The project is Python-based. The .gitignore pre-configures ignores for:
- **Web frameworks**: Django or Flask
- **Task queue**: Celery
- **Message brokers**: Redis, RabbitMQ, ActiveMQ
- **Database**: SQLite (dev), likely a production DB via ORM

The actual framework and dependency manager (pip/poetry/pipenv/uv) will be confirmed once implementation begins.

## Commands

These will be defined once the project structure is established. Common patterns to expect:

```bash
# Install dependencies (once requirements file or pyproject.toml exists)
pip install -r requirements.txt
# or: poetry install / uv sync

# Run development server
python manage.py runserver        # Django
# or: flask run / uvicorn app:app

# Run tests
pytest
python manage.py test             # Django

# Run a single test
pytest path/to/test_file.py::TestClass::test_method

# Lint / format
ruff check .
ruff format .
```
