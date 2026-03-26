"""
HTTP wrapper around the shared backend message dispatcher.
"""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from rss_analyzer.backend_service import handle_message

logger = logging.getLogger(__name__)


class BackendHTTPRequestHandler(BaseHTTPRequestHandler):
    server_version = "RSSBackendHTTP/0.1"

    def _write_json(self, status_code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            return {}

        raw_body = self.rfile.read(content_length)
        if not raw_body:
            return {}

        try:
            return json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid_json: {exc}") from exc

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._write_json(200, {"ok": True})

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._write_json(200, handle_message({"type": "health"}))
            return

        self._write_json(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/message":
            self._write_json(404, {"error": "not_found"})
            return

        try:
            payload = self._read_json()
        except ValueError as exc:
            self._write_json(400, {"error": str(exc)})
            return

        if not isinstance(payload, dict):
            self._write_json(400, {"error": "invalid_payload"})
            return

        try:
            response = handle_message(payload)
            self._write_json(200, response)
        except Exception as exc:
            logger.exception("Unhandled backend exception")
            self._write_json(
                500,
                {"error": "exception", "message": str(exc)},
            )

    def log_message(self, format: str, *args) -> None:
        logger.info("%s - %s", self.address_string(), format % args)


def create_server(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), BackendHTTPRequestHandler)
