"""Durable background jobs backed by the application's SQLite database."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Callable

from rss_analyzer import cache

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(cache.DB_PATH, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def init_schema(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS background_jobs (
                    job_id TEXT PRIMARY KEY,
                    operation TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result TEXT,
                    error TEXT,
                    dedupe_key TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_background_jobs_status
                ON background_jobs(status, created_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_background_jobs_dedupe
                ON background_jobs(dedupe_key, created_at)
                """
            )

    def recover_incomplete(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE background_jobs
                SET status = 'pending', updated_at = ?
                WHERE status = 'running'
                """,
                (_now(),),
            )
            return cursor.rowcount

    def create(
        self,
        operation: str,
        payload: dict,
        *,
        dedupe_key: str | None = None,
        max_attempts: int = 3,
    ) -> dict:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            if dedupe_key:
                row = connection.execute(
                    """
                    SELECT * FROM background_jobs
                    WHERE dedupe_key = ? AND status IN ('pending', 'running', 'succeeded')
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (dedupe_key,),
                ).fetchone()
                if row:
                    connection.commit()
                    return self._decode(row)

            job_id = uuid.uuid4().hex
            timestamp = _now()
            connection.execute(
                """
                INSERT INTO background_jobs (
                    job_id, operation, payload, status, dedupe_key,
                    attempts, max_attempts, created_at, updated_at
                ) VALUES (?, ?, ?, 'pending', ?, 0, ?, ?, ?)
                """,
                (
                    job_id,
                    operation,
                    json.dumps(payload, ensure_ascii=False),
                    dedupe_key,
                    max(1, int(max_attempts)),
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
        finally:
            connection.close()
        return self.get(job_id)

    def get(self, job_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM background_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return self._decode(row) if row else None

    def claim_next(self) -> dict | None:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM background_jobs
                WHERE status = 'pending' AND attempts < max_attempts
                ORDER BY created_at ASC LIMIT 1
                """
            ).fetchone()
            if not row:
                connection.commit()
                return None
            cursor = connection.execute(
                """
                UPDATE background_jobs
                SET status = 'running', attempts = attempts + 1, updated_at = ?
                WHERE job_id = ? AND status = 'pending'
                """,
                (_now(), row["job_id"]),
            )
            connection.commit()
            if cursor.rowcount != 1:
                return None
            return self.get(row["job_id"])
        finally:
            connection.close()

    def succeed(self, job_id: str, result: dict) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE background_jobs
                SET status = 'succeeded', result = ?, error = NULL, updated_at = ?
                WHERE job_id = ?
                """,
                (json.dumps(result, ensure_ascii=False), _now(), job_id),
            )

    def fail(self, job_id: str, error: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE background_jobs
                SET status = 'failed', error = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (error, _now(), job_id),
            )

    def retry(self, job_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status, attempts, max_attempts FROM background_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if not row:
                return None
            if row["status"] != "failed":
                return self.get(job_id)
            connection.execute(
                """
                UPDATE background_jobs
                SET status = 'pending', error = NULL,
                    max_attempts = MAX(max_attempts, attempts + 1), updated_at = ?
                WHERE job_id = ?
                """,
                (_now(), job_id),
            )
        return self.get(job_id)

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict:
        item = dict(row)
        item["payload"] = json.loads(item["payload"])
        item["result"] = json.loads(item["result"]) if item.get("result") else None
        return item


class JobManager:
    def __init__(
        self,
        execute: Callable[[str, dict], dict],
        *,
        store: JobStore | None = None,
        worker_count: int = 2,
        poll_seconds: float = 0.5,
    ) -> None:
        self.store = store or JobStore()
        self.execute = execute
        self.worker_count = max(1, worker_count)
        self.poll_seconds = poll_seconds
        self._condition = threading.Condition()
        self._started = False
        self._stopping = False
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        with self._condition:
            if self._started:
                return
            self.store.init_schema()
            recovered = self.store.recover_incomplete()
            if recovered:
                logger.warning("Recovered %s interrupted background jobs", recovered)
            self._started = True
            for index in range(self.worker_count):
                thread = threading.Thread(
                    target=self._worker,
                    name=f"rss-job-worker-{index + 1}",
                    daemon=True,
                )
                thread.start()
                self._threads.append(thread)

    def submit(
        self,
        operation: str,
        payload: dict,
        *,
        dedupe_key: str | None = None,
        max_attempts: int = 3,
    ) -> dict:
        self.start()
        job = self.store.create(
            operation,
            payload,
            dedupe_key=dedupe_key,
            max_attempts=max_attempts,
        )
        self._notify()
        return job

    def retry(self, job_id: str) -> dict | None:
        self.start()
        job = self.store.retry(job_id)
        self._notify()
        return job

    def _notify(self) -> None:
        with self._condition:
            self._condition.notify_all()

    def _worker(self) -> None:
        while True:
            with self._condition:
                if self._stopping:
                    return
            job = self.store.claim_next()
            if not job:
                with self._condition:
                    self._condition.wait(timeout=self.poll_seconds)
                continue
            try:
                result = self.execute(job["operation"], job["payload"])
                if not isinstance(result, dict):
                    result = {"result": result}
                if result.get("error"):
                    raise RuntimeError(result.get("message") or result["error"])
                self.store.succeed(job["job_id"], result)
            except Exception as exc:
                logger.exception("Background job %s failed", job["job_id"])
                self.store.fail(job["job_id"], str(exc))

    def stop(self) -> None:
        with self._condition:
            self._stopping = True
            self._condition.notify_all()
        for thread in self._threads:
            thread.join(timeout=2)
