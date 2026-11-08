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
            body='cb({"state":false,"data":"5c43e3"})', url="", raw=b"", status=200
        )
        session.post.return_value = mock.Mock(
            body='cb({"state":false,"code":200,"msg":"x"})', url="", raw=b"",
            status=200,
        )
        opts = TransportOptions(proxy="1.1.1.1:80")
        with mock.patch.object(
            TransportOptions, "new_session", return_value=session
        ) as factory:
            result = submit_registration(bundle, dry_run=False, transport=opts)
        factory.assert_called_once()
        self.assertEqual(result.path, "web")

    def test_invalid_transport_type(self):
        from gen4399.forms import RegistrationProfile
        from gen4399.registration import prepare_registration
        from gen4399.submit import submit_registration

        profile = RegistrationProfile("张三", "460206194611192084")
        bundle = prepare_registration(profile, path="web", verify_username=False)
        with self.assertRaises(TypeError):
            submit_registration(bundle, dry_run=True, transport="http://1.1.1.1:80")


class TestTransportThreading(unittest.TestCase):
    """代理配置不能只覆盖提交，查重/取号也要走同一个 transport。"""

    def test_generate_available_username_passes_transport(self):
        from gen4399.remote import _api

        opts = TransportOptions(proxy="1.1.1.1:80")
        with mock.patch.object(_api, "check_username") as check:
            check.return_value = mock.Mock(available=True, message="0")
            name = _api.generate_available_username(max_attempts=1, transport=opts)
        self.assertTrue(name)
        self.assertIs(check.call_args.kwargs["transport"], opts)

    def test_fetch_suggested_username_passes_transport(self):
        from gen4399.remote import _api

        opts = TransportOptions(proxy="1.1.1.1:80")
        html = '<input type="text" id="j-username" name="username" value="4257237567"/>'
        with mock.patch.object(_api._http, "_http_get", return_value=html) as get:
            name = _api.fetch_suggested_username(transport=opts)
        self.assertEqual(name, "4257237567")
        self.assertIs(get.call_args.kwargs["transport"], opts)

    def test_prepare_registration_passes_transport(self):
        from gen4399.forms import RegistrationProfile
        from gen4399 import registration

        opts = TransportOptions(proxy="1.1.1.1:80")
        profile = RegistrationProfile("张三", "460206194611192084")
        with mock.patch.object(
            registration, "generate_available_username", return_value="abc12345"
        ) as gen:
            registration.prepare_registration(profile, path="web", transport=opts)
        gen.assert_called_once()
        self.assertIs(gen.call_args.kwargs["transport"], opts)


class TestStickyAndThreadSafety(unittest.TestCase):
    def test_sticky_keeps_first_proxy(self):
        pool = ProxyPool(["1.1.1.1:80", "2.2.2.2:80"])
        opts = TransportOptions(proxy_pool=pool, sticky=True)
        picks = [opts.pick_proxy() for _ in range(3)]
        self.assertEqual(picks, ["http://1.1.1.1:80"] * 3)
        opts.reset_sticky()
        self.assertEqual(opts.pick_proxy(), "http://2.2.2.2:80")

    def test_non_sticky_rotates(self):
        opts = TransportOptions(proxy_pool=ProxyPool(["1.1.1.1:80", "2.2.2.2:80"]))
        self.assertNotEqual(opts.pick_proxy(), opts.pick_proxy())

    def test_pool_next_is_thread_safe(self):
        import threading

        pool = ProxyPool(["1.1.1.1:80", "2.2.2.2:80", "3.3.3.3:80", "4.4.4.4:80"])
        results = []
        lock = threading.Lock()

        def worker():
            local = [pool.next() for _ in range(25)]
            with lock:
                results.extend(local)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(results), 100)
        counts = {p: results.count(p) for p in set(results)}
        self.assertEqual(set(counts.values()), {25})
