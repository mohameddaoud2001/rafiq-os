# AGENTS.md - How agents must work

## Stack
Python 3.12 via uv, FastAPI, LangGraph + SQLite checkpointer, FastMCP, Pydantic v2, SQLite FTS5, Jinja2+HTMX, pytest, Ruff

## Commands
- uv sync
- ruff check . && ruff format --check .
- pytest -q
- uv run python -m rafiq.cli demo
- uvicorn rafiq.api.main:app --port 8000

## Rules (from KICKOFF section 1 verbatim)
1. No invented sources. Never write quotations, volume/page numbers...
2. Scripture is never generated...
(See KICKOFF.md for full 12 rules)

## Progress
Read PROGRESS.md for milestone checklist, current step, resume.
