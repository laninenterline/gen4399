"""WebUI（gen4399.webui）的离线测试：解析、任务、导出、验证码桥。"""

import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from gen4399 import webui
from gen4399.batch import BatchItem, BatchSummary


def _post(port, path, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as res:
        return json.loads(res.read())


def _get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as res:
        return res.read()


class TestParseProfiles(unittest.TestCase):
    def test_parse(self):
        profiles = webui._parse_profiles("王五|110105198803121893\n李四|460206194611192084\n")
        self.assertEqual(len(profiles), 2)
        self.assertEqual(profiles[0].realname, "王五")

    def test_parse_qq_column(self):
        profiles = webui._parse_profiles("王五|110105198803121893|123456")
        self.assertEqual(profiles[0].qq, "123456")


class TestWebCaptchaBridge(unittest.TestCase):
    def test_blocking_until_answer(self):
        bridge = webui._WebCaptcha()
        result = {}

        def run():
            result["code"] = bridge(b"img")

        thread = threading.Thread(target=run)
        thread.start()
        for _ in range(50):
            snapshot = bridge.snapshot()
            if snapshot:
                break
            threading.Event().wait(0.01)
        self.assertIsNotNone(bridge.snapshot())
        self.assertTrue(bridge.submit("AB12"))
        thread.join(timeout=5)
        self.assertEqual(result["code"], "AB12")
        self.assertIsNone(bridge.snapshot())

    def test_submit_without_pending(self):
        self.assertFalse(webui._WebCaptcha().submit("X"))


class TestStaticServing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.dist = root / "dist"
        (self.dist / "assets").mkdir(parents=True)
        (self.dist / "index.html").write_text("<html>spa</html>", encoding="utf-8")
        (self.dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")

        webui._Handler.accounts_path = str(root / "accounts.json")
        webui._Handler.dry_run_only = True
        webui._Handler.static_dir = self.dist
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), webui._Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(setattr, webui._Handler, "static_dir", None)

    def test_index_served_from_dist(self):
        self.assertIn(b"spa", _get(self.port, "/"))

    def test_asset_served_with_mime(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/assets/app.js") as res:
            self.assertIn("javascript", res.headers["Content-Type"])
            self.assertIn(b"console.log", res.read())

    def test_spa_fallback_for_unknown_route(self):
        self.assertIn(b"spa", _get(self.port, "/some/route"))

    def test_missing_asset_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            _get(self.port, "/assets/missing.js")
        self.assertEqual(ctx.exception.code, 404)

    def test_unknown_non_asset_falls_back_to_index(self):
        self.assertIn(b"spa", _get(self.port, "/unknown"))


class TestHttpApi(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        webui._Handler.accounts_path = str(Path(self.tmp.name) / "accounts.json")
        webui._Handler.dry_run_only = True
        webui._Handler.static_dir = None
        webui.TASK = webui._Task()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), webui._Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)

    def test_health(self):
        data = json.loads(_get(self.port, "/api/health"))
        self.assertTrue(data["ok"])
        self.assertIn("version", data)

    def test_index_page(self):
        html = _get(self.port, "/").decode()
        self.assertIn("gen4399 WebUI", html)

    def test_parse_endpoint(self):
        data = _post(self.port, "/api/parse", {"sfz": "王五|110105198803121893"})
        self.assertEqual(data["count"], 1)

    def test_run_dry_run_and_status(self):
        summary = BatchSummary(items=[BatchItem(1, "u1", "dry_run", False, "dry")])

        def fake_run(profiles, **kwargs):
            kwargs["on_progress"](1, len(profiles), summary.items[0])
            return summary

        with mock.patch("gen4399.webui.run_batch", fake_run):
            started = _post(self.port, "/api/run", {
                "sfz": "王五|110105198803121893", "count": 1, "path": "unified",
                "interval": 0, "jitter": 0, "captcha": "", "dry_run": True,
            })
            self.assertTrue(started["ok"])
            for _ in range(100):
                status = json.loads(_get(self.port, "/api/status"))
                if not status["running"]:
                    break
                threading.Event().wait(0.02)
        self.assertEqual(status["finished"], 1)
        self.assertEqual(status["items"][0]["username"], "u1")

    def test_run_rejects_when_dry_run_only(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            _post(self.port, "/api/run", {
                "sfz": "王五|110105198803121893", "dry_run": False,
            })
        self.assertEqual(ctx.exception.code, 403)

    def test_export_csv(self):
        Path(webui._Handler.accounts_path).write_text(
            json.dumps([{"username": "u1", "password": "p", "kind": "success", "ok": True}]),
            encoding="utf-8",
        )
        body = _get(self.port, "/api/export?format=csv").decode("utf-8-sig")
        self.assertIn("username", body.splitlines()[0])
        self.assertIn("u1", body)

    def test_export_json(self):
        Path(webui._Handler.accounts_path).write_text(
            json.dumps([{"username": "u2"}]), encoding="utf-8"
        )
        data = json.loads(_get(self.port, "/api/export?format=json"))
        self.assertEqual(data[0]["username"], "u2")

    def test_captcha_endpoint_empty(self):
        data = json.loads(_get(self.port, "/api/captcha"))
        self.assertEqual(data, {})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
