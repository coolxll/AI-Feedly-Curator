# TODO

## Current Branch

- `feature/extension-client-server`
- Branch status: ahead of `origin/feature/extension-client-server` by 1 commit

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
- [x] Added tests for embedding config and fingerprint behavior

## In Progress

- [ ] Commit and/or push the follow-up chromadb environment guidance change
  - Current uncommitted files:
    - `README.md`
    - `rss_analyzer/vector_store.py`
  - Goal:
    - make runtime error message explicitly point to `uv run python ...` or project `.venv`
    - document that global Python may have broken `chromadb` / `opentelemetry` dependency mix

## Next

- [ ] Decide whether to commit `COVERAGE.md` relocation as a separate commit
  - Current workspace state:
    - delete `COVERAGE.md`
    - add `docs/COVERAGE.md`

- [ ] Push current branch to remote after the remaining local changes are committed

## Environment Notes

- Current global Python environment is inconsistent for ChromaDB:
  - `chromadb 1.4.1`
  - `opentelemetry-sdk 1.37.0`
  - `opentelemetry-exporter-otlp-proto-grpc 1.39.1`
- Project `uv` environment is healthy:
  - `uv run python -c "import chromadb"` succeeds
- Recommended command pattern:
  - `uv run python rss_backend_service.py --host 127.0.0.1 --port 8765`

## Later

- [ ] If embedding model/provider changes, rebuild `chroma_db/`
- [ ] Optionally add an explicit rebuild command for vector DB instead of manual cleanup
- [ ] Revisit larger repo layout only if needed later (`apps/`, `clients/`, etc.)
