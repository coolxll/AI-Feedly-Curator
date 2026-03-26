# RSS Article Analyzer Project Context

## Project Overview

**AI-Feedly-Curator** is an AI-powered tool designed to streamline RSS feed consumption. It integrates with Feedly to fetch unread articles, uses Large Language Models (LLMs) to analyze, score, and summarize content, and generates comprehensive Markdown reports.

**Key Features:**
*   **Feedly Integration:** Automatically fetches unread articles.
*   **AI Analysis:** Scores articles based on relevance, informativeness, depth, etc., using customizable personas.
*   **Task-Scoped Model Config:** Share one provider config and switch models per task for analysis and overall summary.
*   **Reporting:** Generates daily/monthly Markdown summaries and archives analyzed data.
*   **Pre-filtering:** Filters out low-quality or irrelevant content (ads, short posts) before LLM processing.
*   **Local Service + Extension:** A local HTTP backend powers the Chrome Feedly overlay and can be shared by other local clients.

## Architecture & Key Files

*   **`article_analyzer.py`**: The main CLI entry point. Orchestrates fetching, filtering, analyzing, and reporting.
*   **`rss_backend_service.py`**: Local HTTP service entry point for the Chrome extension and other local clients.
*   **`rss_analyzer/`**: Core package directory.
    *   `config.py`: Configuration management. Handles task-scoped model settings, environment variables, and scoring weights.
    *   `llm_analyzer.py`: Interface for LLM interactions (scoring and summarizing).
    *   `feedly_client.py`: Client for the Feedly API.
    *   `article_fetcher.py`: Fetches article content from URLs (using `trafilatura`).
    *   `scoring.py`: Logic for calculating scores.
    *   `backend_service.py`: Shared message dispatcher for service/native/local clients.
    *   `http_service.py`: Thin HTTP wrapper exposing `/health` and `/api/message`.
*   **`extension/`**: Chrome extension that injects scores/summaries into Feedly and talks to the local HTTP service.
*   **`native_host/`**: Legacy native host adapter, now reduced to a thin stdio transport over the shared backend dispatcher.
*   **`requirements.txt`**: Python dependencies (`requests`, `openai`, `trafilatura`, `beautifulsoup4`, etc.).
*   **`.env`**: (User-created) Stores API keys and secrets.
*   **`output/`**: Directory where analyzed JSON data and Markdown summaries are saved, organized by month.

## Building and Running

### Prerequisites

*   Python 3.8+
*   Feedly Account (and Developer Token)
*   LLM API Access (OpenAI compatible, e.g., DeepSeek, Local LLM)

### Setup

1.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

2.  **Configuration:**
    *   Copy `.env.example` to `.env`.
    *   Fill in the required API keys (Feedly, OpenAI/LLM providers).
    *   Define shared provider keys plus task-scoped models in `.env` (e.g., `OPENAI_BASE_URL`, `ANALYSIS_OPENAI_MODEL`, `SUMMARY_OPENAI_MODEL`).

### Usage Commands

*   **Fetch and Analyze (Standard Run):**
    ```bash
    python article_analyzer.py --refresh
    ```
    *   Fetches latest unread articles from Feedly.
    *   Analyzes them using the configured task-scoped LLM settings.
    *   Generates a report.

*   **Analyze Local File:**
    ```bash
    python article_analyzer.py --input unread_news.json
    ```

*   **Refresh Only (Dry Run/Limit):**
    ```bash
    python article_analyzer.py --refresh --limit 50
    ```

*   **Regenerate Summary Only:**
    ```bash
    python regenerate_summary.py
    ```

*   **Run Local Backend Service:**
    ```bash
    python rss_backend_service.py --host 127.0.0.1 --port 8765
    ```

## Development Conventions

*   **Configuration:** 
    *   Use `PROJ_CONFIG` in `rss_analyzer/config.py` for defaults and scoring logic.
    *   Use environment variables (via `.env`) for shared provider settings plus task-scoped model settings.
    *   Recommended pattern: global `OPENAI_API_KEY` / `OPENAI_BASE_URL`, task model overrides via `ANALYSIS_OPENAI_MODEL` and `SUMMARY_OPENAI_MODEL`.
*   **Logging:** Uses standard Python `logging`. Debug mode can be enabled via `--debug` flag or `DEBUG` env var.
*   **Testing:** `unittest` framework. Tests are located in `tests/`.
    *   Run all tests: `python -m unittest discover tests`
*   **Output:** Analyzed data is saved as JSON, summaries as Markdown. Files are timestamped and archived.
*   **Architecture:** Treat this repo as one product with multiple deployable clients. Shared logic belongs in `rss_analyzer/`; UI clients should stay thin and call the local service rather than duplicating AI logic.

## Key Configuration Concepts

*   **Task Config:** Use task prefixes mainly to route different models for different jobs (e.g., a cheaper analysis model and a stronger summary model).
    *   Recommended: shared `OPENAI_*` provider config plus `ANALYSIS_OPENAI_MODEL` / `SUMMARY_OPENAI_MODEL`.
*   **Scoring Persona:** A text prompt in `config.py` that defines the "personality" and criteria the LLM uses to evaluate articles.



