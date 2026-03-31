import json
import threading
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


if __name__ == "__main__":
    unittest.main()
