"""CLI 传输参数测试：--proxy / --proxy-file / --random-ua 的解析与透传。"""

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gen4399 import cli
from gen4399.submit import SubmitResult

VALID_ID = "460206194611192084"

_MODULE_TMP = None
_MODULE_CWD = None


def setUpModule():
    global _MODULE_TMP, _MODULE_CWD
    _MODULE_CWD = os.getcwd()
    _MODULE_TMP = tempfile.TemporaryDirectory()
    os.chdir(_MODULE_TMP.name)


def tearDownModule():
    if _MODULE_CWD is not None:
        os.chdir(_MODULE_CWD)
    if _MODULE_TMP is not None:
        _MODULE_TMP.cleanup()


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def _result(**kwargs):
    base = dict(
        ok=False, kind="dry_run", message="dry-run", username="abc12345",
        path="unified", app_id="u4399", endpoint="x",
        encrypted_fields=(), login_cookies=(), field_names=(), dry_run=True,
    )
    base.update(kwargs)
    return SubmitResult(**base)


class TestTransportParser(unittest.TestCase):
    def test_defaults(self):
        args = cli.build_parser().parse_args([])
        self.assertIsNone(args.proxy)
        self.assertIsNone(args.proxy_file)
        self.assertEqual(args.proxy_strategy, "round-robin")
        self.assertFalse(args.random_ua)

    def test_subcommand_defaults(self):
        args = cli.build_subcommand_parser().parse_args(["submit"])
        self.assertIsNone(args.proxy)
        self.assertFalse(args.random_ua)


class TestBuildTransport(unittest.TestCase):
    def _args(self, **kw):
        base = dict(proxy=None, proxy_file=None, proxy_strategy="round-robin",
                    random_ua=False)
        base.update(kw)
        return type("A", (), base)()

    def test_none_when_no_options(self):
        self.assertIsNone(cli._build_transport(self._args(), timeout=10, policy=None))

    def test_single_proxy(self):
        opts = cli._build_transport(self._args(proxy="1.2.3.4:8080"), timeout=10, policy=None)
        self.assertEqual(opts.pick_proxy(), "http://1.2.3.4:8080")

    def test_random_ua(self):
        opts = cli._build_transport(self._args(random_ua=True), timeout=10, policy=None)
        self.assertTrue(opts.random_user_agent)

    def test_proxy_file(self):
        path = Path("proxies.txt")
        path.write_text("# c\n1.1.1.1:80\n2.2.2.2:81\n", encoding="utf-8")
        self.addCleanup(path.unlink, True)
        opts = cli._build_transport(self._args(proxy_file=str(path)), timeout=10, policy=None)
        self.assertEqual(len(opts.proxy_pool), 2)


class TestSubmitWiring(unittest.TestCase):
    def setUp(self):
        p1 = mock.patch("gen4399.cli.prepare_registration", return_value=mock.Mock())
        p1.start()
        self.addCleanup(p1.stop)
        p2 = mock.patch("gen4399.cli.submit_registration", return_value=_result())
        self.submit = p2.start()
        self.addCleanup(p2.stop)
        p3 = mock.patch("gen4399.cli._make_captcha_solver", return_value=None)
        p3.start()
        self.addCleanup(p3.stop)

    def test_transport_passed_to_submit(self):
        code, _, _ = run([
            "submit", "--offline", "--proxy", "1.2.3.4:8080", "--random-ua",
            "--realname", "张三", "--idcard", VALID_ID,
        ])
        self.assertEqual(code, 0)
        transport = self.submit.call_args.kwargs["transport"]
        self.assertIsNotNone(transport)
        self.assertTrue(transport.random_user_agent)
        self.assertEqual(transport.proxy, "http://1.2.3.4:8080")

    def test_no_transport_by_default(self):
        code, _, _ = run([
            "submit", "--offline", "--realname", "张三", "--idcard", VALID_ID,
        ])
        self.assertEqual(code, 0)
        self.assertIsNone(self.submit.call_args.kwargs["transport"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
