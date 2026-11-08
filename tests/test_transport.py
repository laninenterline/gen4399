"""代理池 / 随机 UA / TransportOptions 的测试（全部离线）。"""

import random
import unittest
from unittest import mock

from gen4399.proxy import ProxyError, ProxyPool, normalize_proxy
from gen4399.transport import TransportOptions
from gen4399.ua import random_user_agent


class TestNormalizeProxy(unittest.TestCase):
    def test_bare_host_port(self):
        self.assertEqual(normalize_proxy("127.0.0.1:8080"), "http://127.0.0.1:8080")

    def test_keeps_scheme_and_auth(self):
        self.assertEqual(
            normalize_proxy("http://user:pass@10.0.0.1:3128"),
            "http://user:pass@10.0.0.1:3128",
        )

    def test_strips_path(self):
        self.assertEqual(
            normalize_proxy("http://1.2.3.4:80/abc"), "http://1.2.3.4:80"
        )

    def test_rejects_bad_input(self):
        for bad in ("", "   ", "socks5://1.2.3.4:1080", "1.2.3.4"):
            with self.assertRaises(ProxyError, msg=bad):
                normalize_proxy(bad)


class TestProxyPool(unittest.TestCase):
    def test_round_robin(self):
        pool = ProxyPool(["1.1.1.1:80", "2.2.2.2:80"])
        got = [pool.next() for _ in range(5)]
        self.assertEqual(
            got,
            ["http://1.1.1.1:80", "http://2.2.2.2:80",
             "http://1.1.1.1:80", "http://2.2.2.2:80",
             "http://1.1.1.1:80"],
        )

    def test_random_with_seed(self):
        pool = ProxyPool(
            ["1.1.1.1:80", "2.2.2.2:80"], strategy="random",
            rng=random.Random(7),
        )
        picks = {pool.next() for _ in range(50)}
        self.assertEqual(picks, {"http://1.1.1.1:80", "http://2.2.2.2:80"})

    def test_from_lines_skips_comments(self):
        pool = ProxyPool.from_lines(["# 注释", "", "1.1.1.1:80", "  2.2.2.2:80  "])
        self.assertEqual(len(pool), 2)

    def test_from_file(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "proxies.txt"
            path.write_text("# c\n1.1.1.1:80\n2.2.2.2:81\n", encoding="utf-8")
            pool = ProxyPool.from_file(path)
        self.assertEqual(len(pool), 2)
        self.assertEqual(pool.next(), "http://1.1.1.1:80")

    def test_empty_pool_rejected(self):
        with self.assertRaises(ProxyError):
            ProxyPool([])

    def test_bad_strategy_rejected(self):
        with self.assertRaises(ProxyError):
            ProxyPool(["1.1.1.1:80"], strategy="sticky")


class TestRandomUserAgent(unittest.TestCase):
    def test_shape(self):
        ua = random_user_agent(rng=random.Random(1))
        self.assertTrue(ua.startswith("Mozilla/5.0"))
        self.assertNotIn("Headless", ua)
        self.assertNotIn("bot", ua.lower())

    def test_variety(self):
        seen = {random_user_agent(rng=random.Random(i)) for i in range(30)}
        self.assertGreater(len(seen), 3)

    def test_deterministic_with_seed(self):
        self.assertEqual(
            random_user_agent(rng=random.Random(42)),
            random_user_agent(rng=random.Random(42)),
        )


class TestTransportOptions(unittest.TestCase):
    def test_defaults(self):
        opts = TransportOptions()
        self.assertIsNone(opts.pick_proxy())
        session = opts.new_session()
        self.assertIsNone(session.proxy)
        self.assertIn("Mozilla/5.0", session.user_agent)

    def test_proxy_normalized(self):
        opts = TransportOptions(proxy="127.0.0.1:8080")
        self.assertEqual(opts.pick_proxy(), "http://127.0.0.1:8080")

    def test_proxy_pool_rotation(self):
        pool = ProxyPool(["1.1.1.1:80", "2.2.2.2:80"])
        opts = TransportOptions(proxy_pool=pool)
        self.assertEqual(opts.pick_proxy(), "http://1.1.1.1:80")
        self.assertEqual(opts.pick_proxy(), "http://2.2.2.2:80")

    def test_proxy_and_pool_conflict(self):
        with self.assertRaises(ValueError):
            TransportOptions(proxy="1.1.1.1:80", proxy_pool=ProxyPool(["2.2.2.2:80"]))

    def test_random_ua(self):
        opts = TransportOptions(random_user_agent=True)
        a = opts.new_session().user_agent
        b = opts.new_session().user_agent
        self.assertIn("Mozilla/5.0", a)
        self.assertIn("Mozilla/5.0", b)

    def test_invalid_timeout(self):
        with self.assertRaises(ValueError):
            TransportOptions(timeout=0)
        with self.assertRaises(TypeError):
            TransportOptions(timeout="10")  # type: ignore[arg-type]


class TestSubmitUsesTransport(unittest.TestCase):
    def test_transport_session_used(self):
        from gen4399.forms import RegistrationProfile
        from gen4399.registration import prepare_registration
        from gen4399.submit import submit_registration

        profile = RegistrationProfile("张三", "460206194611192084")
        bundle = prepare_registration(profile, path="web", verify_username=False)

        session = mock.Mock()
        session.cookies = {}
        session.get.return_value = mock.Mock(
            body='cb({"state":false,"data":"5c43e3"})', url="", raw=b""
        )
        session.post.return_value = mock.Mock(
            body='cb({"state":false,"code":200,"msg":"x"})', url="", raw=b"",
            status=200,
        )
        opts = mock.Mock()
        opts.new_session.return_value = session
        result = submit_registration(bundle, dry_run=False, transport=opts)
        opts.new_session.assert_called_once()
        self.assertEqual(result.path, "web")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
