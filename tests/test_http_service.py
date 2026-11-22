import json
import os
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from rss_analyzer.http_service import create_server


class TestHTTPService(unittest.TestCase):
    def setUp(self):
        self.server = create_server("127.0.0.1", 0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def test_health_endpoint(self):
        with urlopen(f"http://127.0.0.1:{self.port}/health") as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["service"], "rss-backend")

    def test_health_endpoint_allows_extension_origin(self):
        request = Request(
            f"http://127.0.0.1:{self.port}/health",
            headers={"Origin": "chrome-extension://abcdefghijklmnop"},
        )

        with urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(
                response.headers.get("Access-Control-Allow-Origin"),
                "chrome-extension://abcdefghijklmnop",
            )

        self.assertTrue(payload["ok"])

    def test_health_endpoint_rejects_web_origin(self):
        request = Request(
            f"http://127.0.0.1:{self.port}/health",
            headers={"Origin": "https://evil.example"},
        )

        with self.assertRaises(HTTPError) as ctx:
            urlopen(request)

        self.assertEqual(ctx.exception.code, 403)

    @patch("rss_analyzer.http_service.handle_message")
    def test_message_endpoint_dispatches_payload(self, mock_handle_message):
        mock_handle_message.return_value = {"ok": True, "echo": "get_scores"}
        request = Request(
            f"http://127.0.0.1:{self.port}/api/message",
            data=json.dumps({"type": "get_scores"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(payload, {"ok": True, "echo": "get_scores"})
        mock_handle_message.assert_called_once_with({"type": "get_scores"})

    @patch("rss_analyzer.http_service.handle_stream_message")
    def test_stream_endpoint_emits_sse_events(self, mock_handle_stream):
        def run_stream(payload, emit):
            emit({"event": "progress", "phase": "analyzing", "current": 1, "total": 2})
            return {"success": True, "processed_count": 2}

        mock_handle_stream.side_effect = run_stream
        request = Request(
            f"http://127.0.0.1:{self.port}/api/stream",
            data=json.dumps({"type": "run_analysis", "limit": 2}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urlopen(request) as response:
            body = response.read().decode("utf-8")
            self.assertEqual(
                response.headers.get_content_type(),
                "text/event-stream",
            )

        self.assertIn("event: accepted", body)
        self.assertIn("event: progress", body)
        self.assertIn('"phase": "analyzing"', body)
        self.assertIn("event: complete", body)
        mock_handle_stream.assert_called_once()

    @patch("rss_analyzer.http_service.SSE_HEARTBEAT_INTERVAL_SECONDS", 0.01)
    @patch("rss_analyzer.http_service.handle_stream_message")
    def test_stream_endpoint_emits_heartbeat_during_slow_work(self, mock_handle_stream):
        def run_stream(payload, emit):
            time.sleep(0.03)
            return {"success": True}

        mock_handle_stream.side_effect = run_stream
        request = Request(
            f"http://127.0.0.1:{self.port}/api/stream",
            data=json.dumps({"type": "get_scores"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urlopen(request) as response:
            body = response.read().decode("utf-8")

        self.assertIn(": heartbeat\n\n", body)
        self.assertIn("event: complete", body)

    def test_message_endpoint_rejects_web_origin(self):
        request = Request(
            f"http://127.0.0.1:{self.port}/api/message",
            data=json.dumps({"type": "health"}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Origin": "https://evil.example",
            },
            method="POST",
        )

        with self.assertRaises(HTTPError) as ctx:
            urlopen(request)

        self.assertEqual(ctx.exception.code, 403)

    @patch("rss_analyzer.http_service.handle_message")
    def test_message_endpoint_accepts_double_encoded_json_payload(self, mock_handle_message):
        mock_handle_message.return_value = {"ok": True}
        request = Request(
            f"http://127.0.0.1:{self.port}/api/message",
            data=json.dumps(json.dumps({"type": "export_articles", "output_file": "output/export.json"})).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(payload, {"ok": True})
        mock_handle_message.assert_called_once_with(
            {"type": "export_articles", "output_file": "output/export.json"}
        )

    @patch("rss_analyzer.http_service.handle_message")
    def test_message_endpoint_accepts_form_encoded_payload(self, mock_handle_message):
        mock_handle_message.return_value = {"success": True}
        request = Request(
            f"http://127.0.0.1:{self.port}/api/message",
            data="type=export_articles&limit=100&output_file=output%2Fexport.json".encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        with urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(payload, {"success": True})
        mock_handle_message.assert_called_once_with(
            {"type": "export_articles", "limit": "100", "output_file": "output/export.json"}
        )

    def test_invalid_route_returns_404(self):
        request = Request(f"http://127.0.0.1:{self.port}/missing")
        with self.assertRaises(HTTPError) as ctx:
            urlopen(request)

        self.assertEqual(ctx.exception.code, 404)

    def test_extension_origin_allowlist_permits_listed_ids_and_rejects_others(self):
        with patch.dict(
            os.environ,
            {"RSS_ALLOWED_EXTENSION_IDS": "allowedid1, allowedid2"},
            clear=False,
        ):
            allowed_req = Request(
                f"http://127.0.0.1:{self.port}/health",
                headers={"Origin": "chrome-extension://allowedid2"},
            )
            with urlopen(allowed_req) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertTrue(payload["ok"])
                self.assertEqual(
                    response.headers.get("Access-Control-Allow-Origin"),
                    "chrome-extension://allowedid2",
                )

            moz_req = Request(
                f"http://127.0.0.1:{self.port}/health",
                headers={"Origin": "moz-extension://allowedid1"},
            )
            with urlopen(moz_req) as response:
                self.assertEqual(response.status, 200)

            blocked_req = Request(
                f"http://127.0.0.1:{self.port}/health",
                headers={"Origin": "chrome-extension://otherid"},
            )
            with self.assertRaises(HTTPError) as ctx:
                urlopen(blocked_req)
            self.assertEqual(ctx.exception.code, 403)

    @patch("rss_analyzer.http_service.handle_stream_message")
    @patch("rss_analyzer.http_service.handle_message")
    def test_api_token_enforced_on_api_routes_but_allows_health_and_options(
        self, mock_handle_message, mock_handle_stream
    ):
        mock_handle_message.return_value = {"ok": True}
        mock_handle_stream.return_value = {"success": True}

        with patch.dict(
            os.environ,
            {"RSS_BACKEND_API_TOKEN": "super-secret-token"},
            clear=False,
        ):
            # /health works without token
            with urlopen(f"http://127.0.0.1:{self.port}/health") as response:
                self.assertEqual(response.status, 200)

            # OPTIONS preflight works without token and advertises Authorization header
            options_req = Request(
                f"http://127.0.0.1:{self.port}/api/message",
                headers={"Origin": "chrome-extension://abcdefghijklmnop"},
                method="OPTIONS",
            )
            with urlopen(options_req) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(
                    "Authorization",
                    response.headers.get("Access-Control-Allow-Headers", ""),
                )

            # /api/message rejects missing token
            no_auth_req = Request(
                f"http://127.0.0.1:{self.port}/api/message",
                data=json.dumps({"type": "get_scores"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(HTTPError) as ctx:
                urlopen(no_auth_req)
            self.assertEqual(ctx.exception.code, 401)

            # /api/message rejects wrong token
            bad_auth_req = Request(
                f"http://127.0.0.1:{self.port}/api/message",
                data=json.dumps({"type": "get_scores"}).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer wrong-token",
                },
                method="POST",
            )
            with self.assertRaises(HTTPError) as ctx:
                urlopen(bad_auth_req)
            self.assertEqual(ctx.exception.code, 401)

            # /api/stream rejects missing token
            no_auth_stream = Request(
                f"http://127.0.0.1:{self.port}/api/stream",
                data=json.dumps({"type": "get_scores"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(HTTPError) as ctx:
                urlopen(no_auth_stream)
            self.assertEqual(ctx.exception.code, 401)

            # Valid Bearer token succeeds on both /api/message and /api/stream
            good_msg_req = Request(
                f"http://127.0.0.1:{self.port}/api/message",
                data=json.dumps({"type": "get_scores"}).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer super-secret-token",
                },
                method="POST",
            )
            with urlopen(good_msg_req) as response:
                self.assertEqual(json.loads(response.read().decode("utf-8")), {"ok": True})

            good_stream_req = Request(
                f"http://127.0.0.1:{self.port}/api/stream",
                data=json.dumps({"type": "get_scores"}).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer super-secret-token",
                },
                method="POST",
            )
            with urlopen(good_stream_req) as response:
                body = response.read().decode("utf-8")
                self.assertIn("event: complete", body)

    @patch("rss_analyzer.http_service.logger")
    @patch("rss_analyzer.http_service.handle_stream_message")
    def test_stream_endpoint_handles_connection_aborted_error_cleanly(
        self, mock_handle_stream, mock_logger
    ):
        mock_handle_stream.side_effect = ConnectionAbortedError("client aborted")
        request = Request(
            f"http://127.0.0.1:{self.port}/api/stream",
            data=json.dumps({"type": "get_scores"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urlopen(request) as response:
            body = response.read().decode("utf-8")

        self.assertIn("event: accepted", body)
        self.assertNotIn("event: error", body)
        mock_logger.exception.assert_not_called()

    @patch("rss_analyzer.http_service.handle_stream_message")
    def test_stream_endpoint_unwraps_dict_error_payload(self, mock_handle_stream):
        mock_handle_stream.return_value = {
            "error": {"code": "invalid_request", "message": "Missing article_id"}
        }
        request = Request(
            f"http://127.0.0.1:{self.port}/api/stream",
            data=json.dumps({"type": "analyze_article"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urlopen(request) as response:
            body = response.read().decode("utf-8")

        self.assertIn("event: error", body)
        self.assertIn('"error": "invalid_request"', body)
        self.assertIn('"message": "Missing article_id"', body)


if __name__ == "__main__":
    unittest.main()
