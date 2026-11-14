"""gen4399.login：登录接口的离线测试。"""

import importlib
import unittest
from unittest import mock

from gen4399.login import LOGIN_URL, LoginResult, login


def _session(body, cookies=(), status=200):
    s = mock.Mock()
    s.cookies = {}
    s.post.return_value = mock.Mock(body=body, status=status, url=LOGIN_URL)

    def _post(url, data):
        s.cookies.update({c: "x" for c in cookies})
        return s.post.return_value

    s.post.side_effect = _post
    return s


class TestLogin(unittest.TestCase):
    def _run(self, body, cookies=(), **kw):
        session = _session(body, cookies)
        patcher = mock.patch.object(
            importlib.import_module("gen4399.login")._http, "RemoteSession", return_value=session
        )
        with patcher as factory:
            result = login("abc12345", "Secret123", **kw)
        return result, session, factory

    def test_success(self):
        result, session, _ = self._run(
            "<html>ok</html>", cookies=("Pauth", "Uauth", "Xauth")
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.kind, "success")
        self.assertEqual(result.cookies, ("Pauth", "Uauth", "Xauth"))
        url, payload = session.post.call_args.args
        self.assertEqual(url, LOGIN_URL)
        self.assertEqual(payload["username"], "abc12345")
        self.assertEqual(payload["sec"], "1")
        self.assertTrue(payload["password"].startswith("U2FsdGVkX1"))

    def test_wrong_password(self):
        result, _, _ = self._run(
            '<div id="Msg" class="x">密码错误</div>'
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.kind, "rejected")
        self.assertEqual(result.message, "密码错误")

    def test_captcha_required(self):
        result, _, _ = self._run('<div id="Msg">请输入验证码</div>')
        self.assertEqual(result.kind, "captcha")

    def test_unknown(self):
        result, _, _ = self._run("<html>system busy</html>")
        self.assertEqual(result.kind, "unknown")
        self.assertFalse(result.ok)

    def test_bool_and_repr(self):
        r = LoginResult(ok=True, kind="success", message="ok", username="a")
        self.assertTrue(r)
        self.assertIn("LoginResult", repr(r))
        self.assertNotIn("Secret123", repr(r))

    def test_to_dict(self):
        r = LoginResult(ok=False, kind="rejected", message="密码错误",
                        username="a", cookies=("Pauth",))
        self.assertEqual(r.to_dict()["kind"], "rejected")
        self.assertEqual(r.to_dict()["cookies"], ["Pauth"])

    def test_invalid_args(self):
        with self.assertRaises(TypeError):
            login("", "x")
        with self.assertRaises(TypeError):
            login("abc", "")

    def test_transport_used(self):
        session = _session("<html>ok</html>", cookies=("Pauth",))
        opts = mock.Mock()
        opts.new_session.return_value = session
        with mock.patch.object(
            importlib.import_module("gen4399.login")._http,
            "RemoteSession",
        ) as factory:
            result = login("abc", "pwd", transport=opts)
        opts.new_session.assert_called_once()
        factory.assert_not_called()
        self.assertTrue(result.ok)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
