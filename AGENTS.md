# RSS Article Analyzer Project Context

## Project Overview

**AI-Feedly-Curator** is an AI-powered tool designed to streamline RSS feed consumption. It integrates with Feedly to fetch unread articles, uses Large Language Models (LLMs) to analyze, score, and summarize content, and generates comprehensive Markdown reports.

**Key Features:**
*   **Feedly Integration:** Automatically fetches unread articles.
*   **AI Analysis:** Scores articles based on relevance, informativeness, depth, etc., using customizable personas.
*   **Multi-Profile Support:** Switch between different LLM providers (e.g., Local Qwen, DeepSeek, Aliyun) via configuration.
*   **Reporting:** Generates daily/monthly Markdown summaries and archives analyzed data.
*   **Pre-filtering:** Filters out low-quality or irrelevant content (ads, short posts) before LLM processing.

## Architecture & Key Files

*   **`article_analyzer.py`**: The main CLI entry point. Orchestrates fetching, filtering, analyzing, and reporting.
*   **`rss_analyzer/`**: Core package directory.
    *   `config.py`: Configuration management. Handles environment variables, profiles, and scoring weights.
    *   `llm_analyzer.py`: Interface for LLM interactions (scoring and summarizing).
    *   `feedly_client.py`: Client for the Feedly API.
    *   `article_fetcher.py`: Fetches article content from URLs (using `trafilatura`).
    *   `scoring.py`:  (Inferred) Logic for calculating scores.
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
    *   Define profiles in `.env` (e.g., `DEEPSEEK_OPENAI_API_KEY`, `LOCAL_QWEN_OPENAI_BASE_URL`).

### Usage Commands

*   **Fetch and Analyze (Standard Run):**
    ```bash
    python article_analyzer.py --refresh
    ```
    *   Fetches latest unread articles from Feedly.
    *   Analyzes them using the configured LLM profile.
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

## Development Conventions

*   **Configuration:** 
    *   Use `PROJ_CONFIG` in `rss_analyzer/config.py` for defaults and logic.
    *   Use environment variables (via `.env`) for secrets and profile-specific overrides.
    *   Profile naming convention: Uppercase (e.g., `DEEPSEEK`, `LOCAL_QWEN`).
*   **Logging:** Uses standard Python `logging`. Debug mode can be enabled via `--debug` flag or `DEBUG` env var.
*   **Testing:** `unittest` framework. Tests are located in `tests/`.
    *   Run all tests: `python -m unittest discover tests`
*   **Output:** Analyzed data is saved as JSON, summaries as Markdown. Files are timestamped and archived.

## Key Configuration Concepts

*   **Profiles:** Allow switching between different LLM backends for different tasks (e.g., a cheaper/faster model for individual article scoring, and a stronger model for the overall summary).
    *   Configured in `PROJ_CONFIG["analysis_profile"]` and `PROJ_CONFIG["summary_profile"]`.
*   **Scoring Persona:** A text prompt in `config.py` that defines the "personality" and criteria the LLM uses to evaluate articles.
