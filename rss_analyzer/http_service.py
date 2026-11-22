"""
HTTP wrapper around the shared backend message dispatcher.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs

from rss_analyzer.backend_service import handle_message, handle_stream_message

logger = logging.getLogger(__name__)
SSE_HEARTBEAT_INTERVAL_SECONDS = 15.0
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

        raw_allowed_ids = (os.getenv("RSS_ALLOWED_EXTENSION_IDS") or "").strip()
        if raw_allowed_ids:
            allowed_ids = {
                item.strip() for item in raw_allowed_ids.split(",") if item.strip()
            }
            for prefix in ALLOWED_EXTENSION_ORIGIN_PREFIXES:
                if origin.startswith(prefix):
                    ext_id = origin[len(prefix):]
                    return ext_id in allowed_ids
            return False

        return origin.startswith(ALLOWED_EXTENSION_ORIGIN_PREFIXES)

    def _is_authorized(self) -> bool:
        expected_token = (os.getenv("RSS_BACKEND_API_TOKEN") or "").strip()
        if not expected_token:
            return True

        auth_header = (self.headers.get("Authorization") or "").strip()
        scheme, _, provided_token = auth_header.partition(" ")
        if scheme.lower() != "bearer" or not provided_token.strip():
            return False

        return hmac.compare_digest(provided_token.strip(), expected_token)

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
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _reject_disallowed_origin(self) -> None:
        self._write_json(
            403,
            {"error": "forbidden_origin", "message": "Origin is not allowed"},
            include_cors=False,
        )

    def _reject_unauthorized(self) -> None:
        self._write_json(
            401,
            {"error": "unauthorized", "message": "Missing or invalid API token"},
        )

    def _start_sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "close")
        origin = self._get_request_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()

    def _write_sse(self, payload: dict) -> None:
        event = str(payload.get("event") or "message")
        data = {key: value for key, value in payload.items() if key != "event"}
        frame = (
            f"event: {event}\n"
            f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        ).encode("utf-8")
        self.wfile.write(frame)
        self.wfile.flush()

    def _write_sse_heartbeat(self) -> None:
        self.wfile.write(b": heartbeat\n\n")
        self.wfile.flush()

    def _serve_sse(self, payload: dict) -> None:
        """Stream one request, keeping the connection alive during slow model calls."""
        messages: queue.Queue[tuple[str, Any]] = queue.Queue()
        client_disconnected = threading.Event()

        def emit(event: dict) -> None:
            if client_disconnected.is_set():
                raise ConnectionResetError("SSE client disconnected")
            messages.put(("event", event))

        def run_request() -> None:
            try:
                messages.put(("result", handle_stream_message(payload, emit)))
            except Exception as exc:
                messages.put(("exception", exc))

        worker = threading.Thread(target=run_request, daemon=True)
        worker.start()

        try:
            while True:
                try:
                    kind, value = messages.get(timeout=SSE_HEARTBEAT_INTERVAL_SECONDS)
                except queue.Empty:
                    self._write_sse_heartbeat()
                    continue

                if kind == "event":
                    self._write_sse(value)
                    continue
                if kind == "exception":
                    raise value

                response = value
                err_obj = response.get("error")
                if err_obj:
                    if isinstance(err_obj, dict):
                        error_code = err_obj.get("code", "error")
                        error_message = err_obj.get(
                            "message", response.get("message", "Request failed")
                        )
                    else:
                        error_code = err_obj
                        error_message = response.get("message", "Request failed")
                    self._write_sse(
                        {
                            "event": "error",
                            "error": error_code,
                            "message": error_message,
                        }
                    )
                else:
                    self._write_sse({"event": "complete", "result": response})
                return
        finally:
            client_disconnected.set()

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

        if self.path not in {"/api/message", "/api/stream"}:
            self._write_json(404, {"error": "not_found"})
            return

        if not self._is_authorized():
            self._reject_unauthorized()
            return

        try:
            payload = self._read_json()
        except ValueError as exc:
            self._write_json(400, {"error": str(exc)})
            return

        if not isinstance(payload, dict):
            self._write_json(400, {"error": "invalid_payload"})
            return

        if self.path == "/api/stream":
            self._start_sse()
            try:
                self._write_sse({"event": "accepted", "type": payload.get("type")})
                self._serve_sse(payload)
            except ConnectionError:
                logger.info("SSE client disconnected; request processing stopped")
            except Exception as exc:
                logger.exception("Unhandled streaming backend exception")
                try:
                    self._write_sse(
                        {"event": "error", "error": "exception", "message": str(exc)}
                    )
                except ConnectionError:
                    pass
            finally:
                self.close_connection = True
            return

        try:
            response = handle_message(payload)
            self._write_json(200, response)
        except Exception as exc:
            logger.exception("Unhandled backend exception")
            self._write_json(500, {"error": "exception", "message": str(exc)})

    def log_message(self, format: str, *args) -> None:
        logger.info("%s - %s", self.address_string(), format % args)


def create_server(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), BackendHTTPRequestHandler)
