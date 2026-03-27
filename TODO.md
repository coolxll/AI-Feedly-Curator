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

## Next

- [ ] Gradually converge TUI onto the shared backend/service layer
  - Move TUI orchestration away from direct script/module calls where practical
  - Reuse `rss_analyzer/backend_service.py` capabilities as the common execution layer
  - Target architecture: one backend, multiple clients (TUI / Chrome extension / future GUI / Skills)

- [x] Added optional Dockerized ChromaDB service mode
  - `RSS_VECTOR_BACKEND=http` switches the app to Chroma HTTP client mode
  - Existing `rebuild_vector_store.py` now doubles as the migration command from SQLite cache to Docker Chroma

- [ ] Revisit larger repo layout only if needed later (`apps/`, `clients/`, etc.)

## Operational Notes

- [ ] If embedding model/provider changes, rebuild `chroma_db/`
