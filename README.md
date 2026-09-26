# 🤖 AgentFlow

**An autonomous AI agent that completes tasks with real tool-calling — and streams every step to your browser, live.**

[![CI](https://github.com/Kushe602/AgentFlow/actions/workflows/ci.yml/badge.svg)](https://github.com/Kushe602/AgentFlow/actions/workflows/ci.yml) ![Python](https://img.shields.io/badge/python-3.11%2B-blue) ![License](https://img.shields.io/badge/license-MIT-green)

AgentFlow gives Claude a goal and a toolbox, then runs the full agentic loop: the model reasons, calls tools, reads the results, and keeps going until the task is done. Every thought, tool call, and result is persisted **and** pushed to the browser over Server-Sent Events, so you watch the agent work — token by token — in real time.

It's a single, all-Python FastAPI app: no separate frontend build, no external queue, no vector database. And it runs with **zero configuration** — leave the API key blank and a deterministic fake agent drives the exact same loop offline.

---

## ✨ Features

- **Real Claude tool-use loop** — multi-turn `tool_use` / `tool_result` orchestration with a hard iteration cap and per-tool timeouts.
- **Live step streaming** — watch reasoning, tool calls, and results stream in over SSE (vanilla `EventSource`), with full replay on reload or reconnect.
- **Pluggable tool registry** — JSON-schema'd tools; add one by writing a handler and registering it.
- **Six built-in tools** — calculator, current time, web fetch, and a sandboxed per-run file workspace (write / read / list).
- **Security-first tools** — SSRF-guarded fetching, an AST-based calculator (no `eval`), and path-traversal-safe file access.
- **Runs offline** — a deterministic fake agent exercises the entire engine with no API key, so tests and demos need nothing.
- **Accounts & history** — bcrypt + JWT cookie auth; every run and step is stored and replayable.
- **Production-shaped** — async SQLAlchemy, SQLite by default / Postgres in Docker, plus Dockerfile, compose, and CI.

---

## 🧠 How it works

```
goal ─▶ ┌──────────────────────────────────────────────┐
        │  run_agent loop   (max N iterations)          │
        │                                               │
        │   Claude.stream_turn ──▶ text + tool_uses     │
        │        │                       │              │
        │        ▼                       ▼              │
        │   stream tokens          run tools (timeout)  │
        │   to browser (SSE)             │              │
        │        │                       ▼              │
        │        │             feed tool_results back   │
        │        └───────────◀───────────┘              │
        │                                               │
        │   no tool calls ──▶ final answer ──▶ done     │
        └──────────────────────────────────────────────┘
```

Each step is written to the database **and** published to an in-process broker. Live viewers subscribe to the broker; anyone loading a finished run replays it straight from the database. The two paths emit identical output, and the client de-duplicates by step index — so reloads and reconnects are seamless.

---

## 🧰 Built-in tools

| Tool | Description | Guardrails |
|------|-------------|------------|
| `calculator` | Evaluate an arithmetic expression | AST-parsed (no `eval`), exponent bounds |
| `current_datetime` | Current UTC time, ISO-8601 | — |
| `web_fetch` | Fetch a URL and return readable text | SSRF-blocked private IPs, no redirects, size caps |
| `write_file` | Write a file in the run's workspace | Sandboxed, path-traversal safe |
| `read_file` | Read a file from the workspace | Sandboxed, size cap |
| `list_files` | List files in the workspace | Sandboxed |

Every run gets its own isolated workspace directory; the file tools cannot escape it.

---

## 🔒 Safety & guardrails

- **No `eval`.** The calculator parses an AST and walks a whitelist of operators, with guards against oversized exponentiation.
- **SSRF protection.** `web_fetch` resolves the host and refuses private, loopback, link-local, multicast, reserved, and unspecified addresses; it disables redirects and caps the response size.
- **Filesystem sandbox.** File tools resolve every path under the per-run workspace and reject anything that escapes it (`..`, absolute paths, or the workspace root itself).
- **Bounded loops.** A max-iteration cap and per-tool `asyncio` timeouts keep runs finite; tool errors are fed back to the model instead of crashing the run.

> **Note:** the auth layer (bcrypt + JWT cookies) is intentionally simple for a portfolio demo. Harden it (CSRF, rate limiting, secret rotation, email verification) before any real deployment.

---

## 🏗️ Tech stack

**FastAPI** · **Uvicorn** · **SQLAlchemy 2.0 (async)** · **SQLite / Postgres** · **Anthropic Claude** · **Jinja2** · **HTMX + Tailwind (CDN)** · **Server-Sent Events** · **pytest** · **ruff** — all Python, no JS build step.

---

## 🚀 Quickstart (no API key needed)

```bash
# 1. Create a virtualenv (Python 3.11+) and install
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# 2. Run it
uvicorn app.main:app --reload
```

Open <http://localhost:8000>, register an account, and give the agent a goal — try *"What is 21 * 2?"* or *"Save a haiku about the ocean to poem.txt."* With no API key set, the **fake agent** runs the whole loop deterministically, which is perfect for a first look.

### With a real Claude API key

```bash
cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY=sk-ant-...
uvicorn app.main:app --reload
```

Now goals are driven by Claude choosing and calling tools for real.

---

## 🐳 Docker

```bash
# App + Postgres in one command:
ANTHROPIC_API_KEY=sk-ant-... docker compose up --build
```

Then open <http://localhost:8000>. Omit the API key to run the fake agent inside the container.

---

## ✅ Tests & linting

```bash
ruff check .
pytest -q
```

The suite covers the tools' guardrails, the full agent loop end-to-end via the fake model, and the HTTP layer — auth, ownership, and a run streamed to completion.

---

## 📁 Project layout

```
app/
  agent/
    engine.py      # the tool-calling loop: drive model, run tools, persist + stream
    models.py      # Claude + deterministic fake model behind one interface
    events.py      # in-process pub/sub broker for live SSE
    prompts.py     # system prompt
    tools/         # calculator, datetime, web_fetch, files + registry
  routers/         # pages, auth, runs (+ the SSE stream endpoint)
  templates/       # Jinja2 + HTMX views
  config.py  database.py  models.py  security.py  dependencies.py  web.py  main.py
tests/             # tools, agent loop, and HTTP-level tests
```---

## ⚙️ Configuration

| Variable | Default | Purpose |
|----------|---------|---------|
| `ANTHROPIC_API_KEY` | *(blank)* | Claude key; blank enables the fake agent |
| `SECRET_KEY` | dev value | Signs JWT session cookies (use 32+ random bytes) |
| `DATABASE_URL` | local SQLite | Async DB URL (`postgresql+asyncpg://…` for Postgres) |
| `CHAT_MODEL` | `claude-sonnet-5` | Model driving the agent |
| `USE_FAKE_AGENT` | `0` | Set `1` to force the fake agent even with a key present |
| `MAX_ITERATIONS` | `8` | Max tool-loop turns per run |
| `TOOL_TIMEOUT_SECONDS` | `15` | Per-tool execution timeout |

---

## 📄 License

MIT — see [LICENSE](LICENSE).
