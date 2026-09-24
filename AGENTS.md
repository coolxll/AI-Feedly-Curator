# RSS Article Analyzer Project Context

## Project Overview

**AI-Feedly-Curator** is an AI-powered tool designed to streamline RSS feed consumption. It integrates with Feedly to fetch unread articles, uses Large Language Models (LLMs) to analyze, score, and summarize content, and generates comprehensive Markdown reports.

**Key Features:**
*   **Feedly Integration:** Automatically fetches unread articles with unified authentication and token management (`rss_analyzer/feedly_auth.py`).
*   **AI Analysis & Versioned Cache:** Scores articles based on relevance, informativeness, depth, etc., using customizable personas and cached fingerprints.
*   **Task-Scoped Model Config:** Share one provider config and switch models per task for analysis and overall summary, while keeping embedding config independent.
*   **Reporting:** Generates daily/monthly Markdown summaries and archives analyzed data.
*   **Pre-filtering & Readflow:** Filters out low-quality or irrelevant content (ads, short posts) and supports multi-stage triage before LLM processing.
*   **Local Service + SSE Streaming:** A local HTTP service exposing `/health`, `/api/message`, and `/api/stream` (Server-Sent Events) powers the Chrome Feedly overlay and other clients.
*   **Vector Outbox & Flexible Backends:** SQLite-backed vector indexing outbox guarantees DB-to-Chroma consistency, supporting both embedded Chroma and Dockerized Chroma HTTP service.
*   **Interactive TUI:** Full-featured terminal user interface (`feedly_tui.py`) for stream selection, review, reporting, and cleanup.

## Architecture & Key Files

*   **CLI Entry Points:**
    *   `feedly_tui.py`: Interactive TUI application for stream review, reports, triage, and filtering.
    *   `article_analyzer.py`: Main CLI entry point for batch fetching, filtering, analyzing, and reporting.
    *   `rss_backend_service.py`: Local HTTP/SSE service entry point for Chrome extension and other local clients.
    *   `feedly_filter.py`: CLI for unread article filtering, score evaluation, and progressive mark-as-read.
    *   `feedly_token.py`: Thin CLI for Feedly OAuth token checking, manual refresh, and PKCE initialization.
    *   `rebuild_vector_store.py`: Vector store rebuild and migration CLI (from SQLite cache to Chroma collection).
*   **`rss_analyzer/`**: Core package directory.
    *   `config.py`: Configuration management. Handles task-scoped chat model settings, independent embedding settings, environment variables, and scoring weights.
    *   `feedly_auth.py`: Centralized Feedly OAuth, token refresh, PKCE authorization, proxy handling, and config resolution.
    *   `feedly_client.py`: API client for Feedly REST endpoints.
    *   `analysis_service.py`: Unified article scoring/analysis pipeline with cache fingerprinting.
    *   `llm_analyzer.py`: Interface for LLM interactions (scoring and summarizing).
    *   `article_fetcher.py`: Fetches full article content from URLs (using `trafilatura`).
    *   `scoring.py`: Logic for calculating composite scores.
    *   `vector_service.py`: Vector store lifecycle and rebuild orchestration.
    *   `vector_store.py`: ChromaDB integration wrapper (supporting embedded and HTTP client modes).
    *   `report_service.py`: Summary report, daily digest, and article export workflows.
    *   `feed_analysis_workflow.py`: Feedly fetch, score, report generation, and mark-as-read analysis pipeline.
    *   `filter_workflows.py`: Article filtering, scoring, and progressive mark-as-read workflows.
    *   `readflow_workflows.py`: Stream overview, batch triage, P2 deep reads, and batch mark-as-read workflows.
    *   `backend_service.py`: Stable compatibility facade and message dispatcher.
    *   `http_service.py`: Local HTTP server exposing `/health`, `/api/message`, and SSE `/api/stream`.
    *   `analysis_handlers.py`, `feedly_handlers.py`, `report_handlers.py`, `vector_handlers.py`: Transport message and SSE progress adapters.
    *   `tui/`: Modular TUI components (`support.py`, `stream_selection.py`, `review.py`, `reports.py`, `cleanup.py`, `menus.py`).
*   **`extension/`**: Chrome extension that injects scores/summaries into Feedly and talks to the local HTTP/SSE service.
*   **`skills/feedly-readflow/`**: Agent skill for multi-agent RSS triage, packets preparation, and reading reports.
*   **`pyproject.toml` / `uv.lock`**: Project dependencies, packaging, and tool configurations (Python >=3.13).
*   **`.env`**: (User-created) Stores API keys and secrets.
*   **`output/`**: Directory where analyzed JSON data and Markdown summaries are saved, organized by month.

## Building and Running

### Prerequisites

*   Python 3.13+
*   Feedly Account (and Developer Token or OAuth credentials)
*   LLM API Access (OpenAI compatible, e.g., DeepSeek, Qwen, Local LLM)
*   `uv` package manager (recommended)

### Setup

1.  **Install Dependencies:**
    ```bash
    # Set target venv for your platform (see below) and sync
    uv sync
    ```

2.  **Configuration:**
    *   Copy `.env.example` to `.env`.
    *   Fill in the required API keys (Feedly, OpenAI/LLM providers).
    *   Define shared chat provider keys plus task-scoped models in `.env` (e.g., `OPENAI_BASE_URL`, `ANALYSIS_OPENAI_MODEL`, `SUMMARY_OPENAI_MODEL`).
    *   If semantic search is enabled, configure embedding separately via `EMBEDDING_API_KEY`, `EMBEDDING_BASE_URL`, `EMBEDDING_MODEL`.

### Virtual Environments (Windows vs WSL)

Source code, `pyproject.toml`, and `uv.lock` are shared across Windows and
WSL, but the virtual environment is **not** — a Windows venv
(`Scripts/python.exe`) and a Linux venv (`bin/python`, `lib64 -> lib`) are
incompatible. Do not let one `.venv` serve both. Use explicitly named venvs
per platform so neither side can clobber or delete the other:

| Platform | Venv path | Interpreter |
|---|---|---|
| Windows | `.venv-win/` | `.venv-win/Scripts/python.exe` |
| WSL/Linux | `.venv-wsl/` | `.venv-wsl/bin/python` |

All three of `.venv/`, `.venv-wsl/`, `.venv-win/` are gitignored. `uv.lock`
**is** committed; venvs are not.

> The repo historically shipped a Linux-created `.venv/` (its `pyvenv.cfg`
> points at a Linux interpreter and it only has a `lib64` symlink), which
> breaks `uv run` on Windows with "access denied" when uv tries to rebuild
> the symlink. The fix is to stop using the shared `.venv/` name and use the
> per-platform names above. On WSL, rename the existing `.venv/` to
> `.venv-wsl/` (or recreate it) so Windows is never tempted to touch it.

#### Windows setup (PowerShell)

```powershell
$env:UV_PROJECT_ENVIRONMENT=".venv-win"
uv sync                       # one-time; installs into .venv-win
uv run python -V              # should print 3.13.x
uv run python article_analyzer.py --refresh
uv run python rss_backend_service.py --host 127.0.0.1 --port 8765
uv run python skills/feedly-readflow/scripts/prepare_packets.py --limit 60
```

`uv run` reads `UV_PROJECT_ENVIRONMENT` and syncs deps into that venv before
running, so the bare `.venv/` is never touched. Set it once per shell, or
persist it in a `.env` / shell profile.

> If `uv` is unavailable, the system Python (3.11+) with the same packages
> installed globally also works for non-chromadb scripts, but prefer
> `.venv-win/` so chromadb/opentelemetry versions stay consistent. To build
> the venv manually without `uv sync`:
> ```powershell
> uv venv .venv-win --python 3.13
> uv pip install --python .venv-win/Scripts/python.exe `
>   beautifulsoup4 chromadb "httpx[socks]" openai pandas prompt-toolkit `
>   python-dotenv questionary requests rich socksio trafilatura
> ```

#### WSL setup (bash)

```bash
export UV_PROJECT_ENVIRONMENT=.venv-wsl
uv sync
uv run python -V
```

#### VSCode

When opening via WSL Remote, select `.venv-wsl/bin/python`; when opening
locally on Windows, select `.venv-win/Scripts/python.exe`. Do not let VSCode
auto-pick a bare `.venv/` — that is what causes the Windows/WSL mix-up.

### Usage Commands

*   **Interactive TUI (Recommended):**
    ```bash
    uv run feedly_tui.py
    ```
    *   Interactive terminal user interface for stream selection, article review, daily digest, and filtering.

*   **Fetch and Analyze (Standard Run):**
    ```bash
    uv run python article_analyzer.py --refresh
    ```
    *   Fetches latest unread articles from Feedly.
    *   Analyzes them using the configured task-scoped LLM settings.
    *   Generates a report.

*   **Filter and Progressive Mark-as-Read:**
    ```bash
    uv run python feedly_filter.py --threshold 2.5
    ```

*   **Feedly Token Management:**
    ```bash
    uv run python feedly_token.py check
    uv run python feedly_token.py refresh
    uv run python feedly_token.py init
    ```

*   **Analyze Local File:**
    ```bash
    uv run python article_analyzer.py --input output/unread_news.json
    ```

*   **Refresh Only (Dry Run/Limit):**
    ```bash
    uv run python article_analyzer.py --refresh --limit 50
    ```

*   **Run Local Backend Service (HTTP + SSE):**
    ```bash
    uv run python rss_backend_service.py --host 127.0.0.1 --port 8765
    ```

*   **Rebuild Active Vector Store:**
    ```bash
    uv run python rebuild_vector_store.py
    ```

## Development Conventions

*   **Configuration:** 
    *   Use `PROJ_CONFIG` in `rss_analyzer/config.py` for defaults and scoring logic.
    *   Use environment variables (via `.env`) for shared chat provider settings, task-scoped model settings, and independent embedding settings.
    *   Recommended pattern: global `OPENAI_API_KEY` / `OPENAI_BASE_URL`, task model overrides via `ANALYSIS_OPENAI_MODEL` and `SUMMARY_OPENAI_MODEL`, plus independent `EMBEDDING_*`.
*   **Logging:** Uses standard Python `logging`. Debug mode can be enabled via `--debug` flag or `DEBUG` env var.
*   **Testing:** `pytest` test suite with 170+ unit and integration tests in `tests/`.
    *   Run all tests: `uv run pytest tests/`
*   **Output:** Analyzed data is saved as JSON, summaries as Markdown in `output/` organized by month.
*   **Architecture:** Treat this repo as one product with multiple deployable clients. Shared logic belongs in `rss_analyzer/`; UI clients should stay thin and call the local service or handlers rather than duplicating AI logic.
    *   Agent skills (`skills/feedly-readflow/`, Hermes/Codex/Claude) are clients too. They may own prompts, orchestration, report style, and delivery, but Feedly API access, token refresh, caching, scoring, and mark-read behavior should live in `rss_analyzer/` or thin project CLIs.
    *   Do not add a second Feedly client or token refresh implementation inside a skill. Add the shared capability here first, then have the skill call this repo.

## Key Configuration Concepts

*   **Task Config:** Use task prefixes mainly to route different chat models for different jobs (e.g., a cheaper analysis model and a stronger summary model).
    *   Recommended: shared `OPENAI_*` provider config plus `ANALYSIS_OPENAI_MODEL` / `SUMMARY_OPENAI_MODEL`.
*   **Embedding Config & Vector Store:** Keep semantic-search embeddings on their own provider/model path using `EMBEDDING_*`.
    *   Supports embedded Chroma (`RSS_VECTOR_BACKEND=embedded`) and Docker HTTP Chroma (`RSS_VECTOR_BACKEND=http`).
    *   The vector DB stores an embedding fingerprint and will warn if the configured embedding base URL/model no longer matches stored vectors.
    *   Use `rebuild_vector_store.py` to rebuild the active Chroma collection from cached SQLite article data after an embedding change.
*   **Vector Outbox:** SQLite-backed outbox queue guarantees reliable DB-to-Chroma synchronization without losing writes upon transient Chroma downtime.
*   **SSE Streaming (`POST /api/stream`):** Long-running operations (refresh, analysis, digest, vector rebuild) stream phase, progress, and article events in a single HTTP request with heartbeats.
*   **Scoring Persona:** A text prompt in `config.py` that defines the "personality" and criteria the LLM uses to evaluate articles.



