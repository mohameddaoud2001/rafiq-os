# KICKOFF: build "Rafiq OS" (الرَّفِيق المُسْنِد) as a runnable, tested proof-of-concept

## 0. How you must work (I am away and cannot answer anything)
- Work autonomously until every milestone in section 4 is finished and `bash scripts/verify.sh` exits 0. Never ask questions.
- First actions: read docs/BRIEF.md if exists. Then create AGENTS.md, PROGRESS.md, DECISIONS.md, BLOCKERS.md.
- Git: init if needed, commit after every milestone as M<n>: <what>.
- Shell hygiene: every command non-interactive, timeout, never foreground server, quote paths.

## 1. Non-negotiable rules
1. No invented sources...
2. Scripture never generated...
3. Zero hallucination - return «لا أعلم، لم أجد نصا في المصادر المعتمدة»
4. No LLM writes fiqh text in PoC
5. System never issues fatwa - dossier PENDING + interrupt
6. Adab al-ikhtilaf block takfir
7. Anti-talfiq
8. Hard block bloodshed/takfir of individuals
9. Sufi awrad only ijaza_approved
10. Disclaimers in code
11. No unmeasured claims
12. Privacy digests only

## 2. Stack
Python 3.12 via uv, src layout, Pydantic v2, FastAPI, LangGraph, FastMCP, SQLite FTS5, Jinja2+HTMX, pytest, Ruff. No Node.

## 3. Components
See full spec in original prompt - supervisor golden tests, 4 madhhab stores, 3 MCP servers, 6 agents, graph with interrupt, dossier, audit, API.

## 4. Milestones M0-M8
M0 skeleton ... M8 Docker + verify

## 5. Definition of done
scripts/verify.sh runs: uv sync, ruff, pytest, rafiq demo, API health, golden a-c, hard-block, not-found, dashboard rtl, pending->approve, audit/verify, amin cert, docker compose.
Only when verify.sh passes set PROGRESS.md STATUS: DONE
