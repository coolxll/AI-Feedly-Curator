# TODO

## Current Branch

- `feature/extension-client-server`
- Branch status: synced with `origin/feature/extension-client-server`

## Done

- [x] Chrome extension switched from Native Messaging to local HTTP service
- [x] Shared backend dispatcher extracted into `rss_analyzer/`
- [x] Runtime outputs moved under `output/`
- [x] Chat model config unified to shared `OPENAI_API_KEY` / `OPENAI_BASE_URL` with task-level model overrides
- [x] Removed `ai_config.json` override path
- [x] Added independent embedding config:
  - `EMBEDDING_API_KEY`
  - `EMBEDDING_BASE_URL`
  - `EMBEDDING_MODEL`
- [x] Added embedding fingerprint check for vector store rebuild warnings
- [x] Added explicit `rebuild_vector_store.py` command to rebuild Chroma from cached SQLite data
- [x] Clarified chromadb runtime guidance:
  - prefer `uv run python ...` or project `.venv`
  - avoid relying on polluted global Python packages
- [x] Moved `COVERAGE.md` under `docs/`

## Environment Notes

- Current global Python environment is inconsistent for ChromaDB:
  - `chromadb 1.4.1`
  - `opentelemetry-sdk 1.37.0`
  - `opentelemetry-exporter-otlp-proto-grpc 1.39.1`
- Project `uv` environment is healthy:
  - `uv run python -c "import chromadb"` succeeds
- Recommended command pattern:
  - `uv run python rss_backend_service.py --host 127.0.0.1 --port 8765`
  - `uv run python rebuild_vector_store.py`
- Current vector-store deployment:
  - Active backend is Dockerized Chroma HTTP service
  - Current endpoint in local use: `http://127.0.0.1:8001`
  - Local embedded `chroma_db/` is no longer the primary runtime path

## Next

- [x] Converged TUI analyze/export/summary flows onto the shared backend/service layer
  - `feedly_tui.py` no longer orchestrates `article_analyzer.main()` or `regenerate_summary` directly
  - `article_analyzer.py` and `regenerate_summary.py` now wrap shared `rss_analyzer/backend_service.py` workflows
  - Target architecture remains: one backend, multiple clients (TUI / Chrome extension / future GUI / Skills)

- [x] Converged TUI filter flows onto the shared backend/service layer
  - `feedly_tui.py` now runs filter workflows via `rss_analyzer/backend_service.py`
  - `feedly_filter.py` is now a thin CLI wrapper over the same shared backend workflow

- [x] Added optional Dockerized ChromaDB service mode
  - `RSS_VECTOR_BACKEND=http` switches the app to Chroma HTTP client mode
  - Existing `rebuild_vector_store.py` now doubles as the migration command from SQLite cache to Docker Chroma

- [ ] Revisit larger repo layout only if needed later (`apps/`, `clients/`, etc.)

## Operational Notes

- [ ] If embedding model/provider changes, rebuild the active vector-store collection
  - For Docker HTTP mode, rerun `uv run python rebuild_vector_store.py` against the configured `RSS_VECTOR_HTTP_URL`
  - For embedded mode, rebuild the local `chroma_db/`
- [ ] Decide when to delete legacy local vector-store leftovers
  - `chroma_db/`
  - `chroma_db_quarantine_20260327_090524/`
