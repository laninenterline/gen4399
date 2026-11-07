"""gen4399.remote 的 HTTP 底层单元测试（不联网，替换 urlopen）。"""

import socket
import unittest
import urllib.error
from unittest import mock

from gen4399.remote import (
    MAX_BODY_BYTES,
    RemoteError,
    RemoteHTTPError,
    RemoteTimeoutError,
    RetryPolicy,
    _http_get,
)


class FakeResponse:
    def __init__(self, body: bytes = b"0", status: int = 200,
                 headers: dict | None = None) -> None:
        self._body = body
        self.status = status
        self.headers = headers or {}
        self.read_args: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.read_args.append(size)
        if size is None or size < 0:
            return self._body
        return self._body[:size]

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc_info) -> bool:
        return False


class TestHttpGet(unittest.TestCase):
    def setUp(self):
        self.patcher = mock.patch("gen4399.remote.urllib.request.urlopen")
        self.urlopen = self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_success(self):
        self.urlopen.return_value = FakeResponse(b"0")
        self.assertEqual(_http_get("https://example.test/x", 5), "0")

    def test_http_error_status(self):
        self.urlopen.return_value = FakeResponse(b"", status=500)
        with self.assertRaises(RemoteHTTPError) as ctx:
            _http_get("https://example.test/x", 5)
        self.assertEqual(ctx.exception.status, 500)

    def test_http_error_exception(self):
        self.urlopen.side_effect = urllib.error.HTTPError(
            "https://example.test/x", 404, "Not Found", {}, None
        )
        with self.assertRaises(RemoteHTTPError) as ctx:
            _http_get("https://example.test/x", 5)
        self.assertEqual(ctx.exception.status, 404)

    def test_timeout(self):
        self.urlopen.side_effect = socket.timeout("timed out")
        with self.assertRaises(RemoteTimeoutError):
            _http_get("https://example.test/x", 5)

    def test_urlerror_timeout(self):
        self.urlopen.side_effect = urllib.error.URLError(socket.timeout("t"))
        with self.assertRaises(RemoteTimeoutError):
            _http_get("https://example.test/x", 5)

    def test_urlerror_network(self):
        self.urlopen.side_effect = urllib.error.URLError("dns failure")
        with self.assertRaises(RemoteError) as ctx:
            _http_get("https://example.test/x", 5)
        self.assertIn("dns failure", str(ctx.exception))

    def test_oserror(self):
        self.urlopen.side_effect = OSError("boom")
        with self.assertRaises(RemoteError):
            _http_get("https://example.test/x", 5)

    def test_body_is_capped(self):
        resp = FakeResponse(b"x" * (MAX_BODY_BYTES + 100))
        self.urlopen.return_value = resp
        body = _http_get("https://example.test/x", 5)
        self.assertEqual(len(body), MAX_BODY_BYTES)
        self.assertEqual(resp.read_args, [MAX_BODY_BYTES])

    def test_decode_errors_are_replaced(self):
        self.urlopen.return_value = FakeResponse(b"ok\xff")
        self.assertIn("ok", _http_get("https://example.test/x", 5))

    def test_retries_transient_error(self):
        self.urlopen.side_effect = [
            urllib.error.URLError("temporary"),
            FakeResponse(b"0"),
        ]
        with mock.patch("gen4399.remote.time.sleep") as sleep:
            self.assertEqual(
                _http_get("https://example.test/x", 5, retries=2), "0"
            )
        self.assertEqual(self.urlopen.call_count, 2)
        sleep.assert_called_once()

    def test_4xx_is_not_retried(self):
        self.urlopen.side_effect = urllib.error.HTTPError(
            "https://example.test/x", 403, "Forbidden", {}, None
        )
        with mock.patch("gen4399.remote.time.sleep"):
            with self.assertRaises(RemoteHTTPError):
                _http_get("https://example.test/x", 5, retries=3)
        self.assertEqual(self.urlopen.call_count, 1)

    def test_5xx_is_retried(self):
        self.urlopen.side_effect = [
            FakeResponse(b"", status=503),
            FakeResponse(b"0"),
        ]
        with mock.patch("gen4399.remote.time.sleep"):
            self.assertEqual(
                _http_get("https://example.test/x", 5, retries=2), "0"
            )
        self.assertEqual(self.urlopen.call_count, 2)

    def test_retries_exhausted_raises_last_error(self):
        self.urlopen.side_effect = urllib.error.URLError("down")
        with mock.patch("gen4399.remote.time.sleep"):
            with self.assertRaises(RemoteError):
                _http_get("https://example.test/x", 5, retries=2)
        self.assertEqual(self.urlopen.call_count, 2)

    def test_invalid_retries(self):
        with self.assertRaises(ValueError):
            _http_get("https://example.test/x", 5, retries=0)

    def test_error_carries_url(self):
        self.urlopen.side_effect = urllib.error.HTTPError(
            "https://example.test/x", 500, "err", {}, None
        )
        with self.assertRaises(RemoteHTTPError) as ctx:
            _http_get("https://example.test/x", 5)
        self.assertEqual(ctx.exception.url, "https://example.test/x")

    def test_429_respects_retry_after(self):
        self.urlopen.side_effect = [
            FakeResponse(b"", status=429, headers={"Retry-After": "2"}),
            FakeResponse(b"0"),
        ]
        with mock.patch("gen4399.remote.time.sleep") as sleep:
            self.assertEqual(_http_get("https://example.test/x", 5, retries=2), "0")
        sleep.assert_called_once()
        self.assertGreaterEqual(sleep.call_args.args[0], 2.0)

    def test_policy_delay_is_capped(self):
        policy = RetryPolicy(attempts=2, base_delay=100, max_delay=1)
        self.assertLessEqual(policy.delay_for(1), 1.0 * 1.25)

    def test_policy_validation(self):
        with self.assertRaises(ValueError):
            RetryPolicy(attempts=0)
        with self.assertRaises(ValueError):
            RetryPolicy(total_deadline=0)
        with self.assertRaises(TypeError):
            RetryPolicy(attempts="3")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
