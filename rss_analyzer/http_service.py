"""
HTTP wrapper around the shared backend message dispatcher.
"""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from rss_analyzer.backend_service import handle_message

logger = logging.getLogger(__name__)
ALLOWED_EXTENSION_ORIGIN_PREFIXES = (
    "chrome-extension://",
    "moz-extension://",
    "edge-extension://",
)


class BackendHTTPRequestHandler(BaseHTTPRequestHandler):
    server_version = "RSSBackendHTTP/0.1"

    def _get_request_origin(self) -> str:
        return (self.headers.get("Origin") or "").strip()

    def _is_allowed_origin(self, origin: str) -> bool:
        if not origin:
            return True

        return origin.startswith(ALLOWED_EXTENSION_ORIGIN_PREFIXES)

    def _write_json(self, status_code: int, payload: dict, include_cors: bool = True) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if include_cors:
            origin = self._get_request_origin()
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _reject_disallowed_origin(self) -> None:
        self._write_json(
            403,
            {"error": "forbidden_origin", "message": "Origin is not allowed"},
            include_cors=False,
        )

    def _read_json(self) -> dict:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            return {}

        raw_body = self.rfile.read(content_length)
        if not raw_body:
            return {}

        decoded_body = raw_body.decode("utf-8").strip()
        if not decoded_body:
            return {}

        content_type = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()

        if content_type == "application/x-www-form-urlencoded":
            return self._decode_form_payload(decoded_body)

        try:
            payload = json.loads(decoded_body)
        except json.JSONDecodeError as exc:
            if "=" in decoded_body and "&" in decoded_body:
                return self._decode_form_payload(decoded_body)
            raise ValueError(f"invalid_json: {exc}") from exc

        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid_json: nested payload is not valid JSON ({exc})") from exc

        if isinstance(payload, dict) and isinstance(payload.get("payload"), dict) and "type" not in payload:
            payload = payload["payload"]

        return payload

    def _decode_form_payload(self, body: str) -> dict:
        parsed = parse_qs(body, keep_blank_values=True)
        payload = {key: values[-1] if values else "" for key, values in parsed.items()}
        nested_payload = payload.get("payload")
        if nested_payload and "type" not in payload:
            try:
                decoded_nested = json.loads(nested_payload)
            except json.JSONDecodeError:
                return payload
            if isinstance(decoded_nested, dict):
                return decoded_nested
        return payload

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not self._is_allowed_origin(self._get_request_origin()):
            self._reject_disallowed_origin()
            return
        self._write_json(200, {"ok": True})

    def do_GET(self) -> None:  # noqa: N802
        if not self._is_allowed_origin(self._get_request_origin()):
            self._reject_disallowed_origin()
            return

        if self.path == "/health":
            self._write_json(200, handle_message({"type": "health"}))
            return

        self._write_json(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._is_allowed_origin(self._get_request_origin()):
            self._reject_disallowed_origin()
            return

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
