import io
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from check_public_health import check_public_health


class PublicHealthTests(unittest.TestCase):
    def test_redirect_to_healthy_endpoint_is_rejected_without_following(self):
        followed = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/health/ready":
                    self.send_response(302)
                    self.send_header("Location", "/other")
                    self.end_headers()
                else:
                    followed.append(self.path)
                    self.send_response(200)
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(b'{"status":"ok"}')

            def log_message(self, *_args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with (
                patch(
                    "check_public_health.PUBLIC_READY_URL",
                    f"http://127.0.0.1:{server.server_port}/health/ready",
                ),
                self.assertRaises(RuntimeError),
            ):
                check_public_health()
            self.assertEqual(followed, [])
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_ready_requires_exact_status_body_and_no_store(self):
        with patch("check_public_health.open_readiness") as fetch:
            response = fetch.return_value.__enter__.return_value
            response.status = 200
            response.headers = {"Cache-Control": "no-store"}
            response.read.return_value = b'{"status":"ok"}'
            check_public_health()
            request = fetch.call_args.args[0]
            self.assertEqual(
                request.full_url,
                "https://whisky-discovery-web.fathompod.workers.dev/health/ready",
            )
            self.assertEqual(fetch.call_args.kwargs["timeout"], 10)
            self.assertEqual(
                request.get_header("User-agent"), "WhiskyDiscoveryAvailability/1.0"
            )
            response.read.return_value = b'{"status":"unavailable"}'
            with self.assertRaises(RuntimeError):
                check_public_health()
            response.read.return_value = b'{"status":"ok"}'
            response.headers = {}
            with self.assertRaises(RuntimeError):
                check_public_health()

    def test_http_and_network_failures_fail_monitor(self):
        for error in (
            HTTPError("https://example.invalid", 503, "unavailable", {}, io.BytesIO()),
            URLError("offline"),
        ):
            with (
                self.subTest(error=type(error).__name__),
                patch("check_public_health.open_readiness", side_effect=error),
                self.assertRaises(RuntimeError),
            ):
                check_public_health()


if __name__ == "__main__":
    unittest.main()
