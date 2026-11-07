"""gen4399.remote._http 的 POST 会话与注册表单解析单元测试（不联网）。

用假的 opener 替换 ``urllib.request.build_opener``，但依然走真实的
``HTTPCookieProcessor`` + ``CookieJar``，因此 Cookie 行为与生产路径一致。
"""

import dataclasses
import email.message
import socket
import unittest
import urllib.error
import urllib.request
from unittest import mock

from gen4399.remote._http import (
    DEFAULT_FETCH_RETRY_POLICY,
    DEFAULT_REFERER,
    DEFAULT_TIMEOUT,
    REGISTER_URL,
    HttpResponse,
    RegFormSnapshot,
    RemoteError,
    RemoteHTTPError,
    RemoteParseError,
    RemoteSession,
    RemoteTimeoutError,
    RetryPolicy,
    parse_registration_form,
)

REG_FRAME_URL = "https://ptlogin.4399.com/ptlogin/regFrame.do"


class FakeResponse:
    """模拟 urllib 响应；实现 ``info()`` 供 CookieJar 提取 Set-Cookie。"""

    def __init__(self, body="", status=200, headers=None, url=None):
        self._body = body if isinstance(body, bytes) else body.encode("utf-8")
        self.status = status
        self.headers = dict(headers or {})
        self.url = url
        self.read_args = []
        self.closed = False

    def read(self, size=-1):
        self.read_args.append(size)
        if size is None or size < 0:
            return self._body
        return self._body[:size]

    def geturl(self):
        return self.url

    def info(self):
        msg = email.message.Message()
        for key, value in self.headers.items():
            msg[key] = value
        return msg

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.closed = True
        return False


class FakeOpener:
    """替代 build_opener 返回的 opener：不联网，但保留真实 Cookie 处理。"""

    def __init__(self, processor):
        self.processor = processor
        self.requests = []
        self.timeouts = []
        self._results = []

    def queue(self, result):
        self._results.append(result)
        return self

    def open(self, request, timeout=None):
        self.requests.append(request)
        self.timeouts.append(timeout)
        self.processor.http_request(request)
        result = self._results.pop(0)
        if isinstance(result, BaseException):
            raise result
        if isinstance(result, FakeResponse):
            resp = result
        else:
            body, status, headers, url = result
            resp = FakeResponse(body, status, headers, url)
        if resp.url is None:
            resp.url = request.full_url
        self.processor.http_response(request, resp)
        return resp


def resp(body="", status=200, headers=None, url=None):
    return FakeResponse(body, status, headers, url)


def make_session(results, *, timeout=5, policy=None, referer=None):
    """建一个 RemoteSession，返回 ``(session, opener)``；opener 按顺序回放结果。"""

    def fake_build_opener(*handlers):
        processor = next(
            handler
            for handler in handlers
            if isinstance(handler, urllib.request.HTTPCookieProcessor)
        )
        opener = FakeOpener(processor)
        for result in results:
            opener.queue(result)
        return opener

    kwargs = {"timeout": timeout}
    if policy is not None:
        kwargs["policy"] = policy
    if referer is not None:
        kwargs["referer"] = referer
    with mock.patch(
        "gen4399.remote._http.urllib.request.build_opener",
        side_effect=fake_build_opener,
    ):
        session = RemoteSession(**kwargs)
    return session, session._opener


def request_headers(request):
    """把 Request 的头合成小写 key 的 dict（含 unredirected）。"""
    merged = {}
    for key, value in request.headers.items():
        merged[key.lower()] = value
    for key, value in request.unredirected_hdrs.items():
        merged[key.lower()] = value
    return merged


class TestRemoteSessionGet(unittest.TestCase):
    def test_get_success(self):
        session, opener = make_session(
            [resp("0", 200, {"Content-Type": "text/html"}, REG_FRAME_URL)]
        )
        result = session.get(REG_FRAME_URL)
        self.assertIsInstance(result, HttpResponse)
        self.assertEqual(result.status, 200)
        self.assertEqual(result.body, "0")
        self.assertEqual(result.url, REG_FRAME_URL)
        self.assertIs(type(result.headers), dict)
        self.assertEqual(result.headers["Content-Type"], "text/html")
        self.assertEqual(len(opener.requests), 1)
        self.assertEqual(opener.timeouts, [5])
        self.assertEqual(opener.requests[0].get_method(), "GET")

    def test_get_sends_browser_headers(self):
        session, opener = make_session([resp("ok")])
        session.get(REG_FRAME_URL)
        headers = request_headers(opener.requests[0])
        self.assertIn("Mozilla", headers["user-agent"])
        self.assertEqual(headers["referer"], DEFAULT_REFERER)
        self.assertEqual(headers["accept-language"], "zh-CN,zh;q=0.9")

    def test_referer_override(self):
        session, opener = make_session(
            [resp("ok")], referer="https://example.test/ref"
        )
        session.get(REG_FRAME_URL)
        self.assertEqual(
            request_headers(opener.requests[0])["referer"],
            "https://example.test/ref",
        )

    def test_default_policy_is_fetch_policy(self):
        session, _ = make_session([])
        self.assertIs(session.policy, DEFAULT_FETCH_RETRY_POLICY)
        self.assertEqual(RemoteSession().timeout, DEFAULT_TIMEOUT)

    def test_policy_override(self):
        policy = RetryPolicy(attempts=1)
        session, _ = make_session([], policy=policy)
        self.assertIs(session.policy, policy)

    def test_get_retries_5xx(self):
        policy = RetryPolicy(attempts=2, base_delay=0)
        session, opener = make_session(
            [resp("", 503), resp("ok")], policy=policy
        )
        with mock.patch("gen4399.remote._http.time.sleep"):
            result = session.get(REG_FRAME_URL)
        self.assertEqual(result.body, "ok")
        self.assertEqual(len(opener.requests), 2)

    def test_get_does_not_retry_4xx(self):
        policy = RetryPolicy(attempts=3, base_delay=0)
        session, opener = make_session([resp("", 403)], policy=policy)
        with mock.patch("gen4399.remote._http.time.sleep") as sleep:
            with self.assertRaises(RemoteHTTPError) as ctx:
                session.get(REG_FRAME_URL)
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(len(opener.requests), 1)
        sleep.assert_not_called()

    def test_get_429_respects_retry_after(self):
        policy = RetryPolicy(attempts=2, base_delay=0)
        session, opener = make_session(
            [resp("", 429, {"Retry-After": "2"}), resp("ok")], policy=policy
        )
        with mock.patch("gen4399.remote._http.time.sleep") as sleep:
            result = session.get(REG_FRAME_URL)
        self.assertEqual(result.body, "ok")
        sleep.assert_called_once()
        self.assertGreaterEqual(sleep.call_args.args[0], 2.0)
        self.assertEqual(len(opener.requests), 2)

    def test_get_http_error_exception_is_mapped(self):
        policy = RetryPolicy(attempts=1)
        error = urllib.error.HTTPError(
            REG_FRAME_URL, 500, "boom", {"Retry-After": "3"}, None
        )
        session, _ = make_session([error], policy=policy)
        with self.assertRaises(RemoteHTTPError) as ctx:
            session.get(REG_FRAME_URL)
        self.assertEqual(ctx.exception.status, 500)
        self.assertEqual(ctx.exception.retry_after, 3.0)
        self.assertEqual(ctx.exception.url, REG_FRAME_URL)

    def test_get_timeout(self):
        policy = RetryPolicy(attempts=1)
        session, opener = make_session(
            [socket.timeout("timed out")], policy=policy
        )
        with self.assertRaises(RemoteTimeoutError) as ctx:
            session.get(REG_FRAME_URL)
        self.assertEqual(ctx.exception.url, REG_FRAME_URL)
        self.assertEqual(len(opener.requests), 1)

    def test_get_url_error_timeout(self):
        policy = RetryPolicy(attempts=1)
        session, _ = make_session(
            [urllib.error.URLError(socket.timeout("t"))], policy=policy
        )
        with self.assertRaises(RemoteTimeoutError):
            session.get(REG_FRAME_URL)

    def test_get_network_error(self):
        policy = RetryPolicy(attempts=1)
        session, _ = make_session(
            [urllib.error.URLError("dns failure")], policy=policy
        )
        with self.assertRaises(RemoteError) as ctx:
            session.get(REG_FRAME_URL)
        self.assertNotIsInstance(ctx.exception, RemoteTimeoutError)
        self.assertIn("dns failure", str(ctx.exception))

    def test_get_oserror(self):
        policy = RetryPolicy(attempts=1)
        session, _ = make_session([OSError("boom")], policy=policy)
        with self.assertRaises(RemoteError):
            session.get(REG_FRAME_URL)

    def test_get_retries_exhausted_raises_last_error(self):
        policy = RetryPolicy(attempts=2, base_delay=0)
        session, opener = make_session(
            [urllib.error.URLError("down"), urllib.error.URLError("down")],
            policy=policy,
        )
        with mock.patch("gen4399.remote._http.time.sleep"):
            with self.assertRaises(RemoteError):
                session.get(REG_FRAME_URL)
        self.assertEqual(len(opener.requests), 2)

    def test_get_total_deadline_clamps_delay(self):
        policy = RetryPolicy(
            attempts=2, base_delay=100, max_delay=10, total_deadline=5
        )
        session, _ = make_session(
            [urllib.error.URLError("down"), resp("ok")], policy=policy
        )
        with mock.patch("gen4399.remote._http.time.sleep") as sleep:
            result = session.get(REG_FRAME_URL)
        self.assertEqual(result.body, "ok")
        sleep.assert_called_once()
        self.assertLessEqual(sleep.call_args.args[0], 5.0)

    def test_get_total_deadline_exhausted_stops_retrying(self):
        policy = RetryPolicy(attempts=3, base_delay=0, total_deadline=5)
        session, opener = make_session(
            [urllib.error.URLError("down"), urllib.error.URLError("down")],
            policy=policy,
        )
        with mock.patch(
            "gen4399.remote._http.time.monotonic",
            side_effect=[0.0, 100.0],
        ):
            with self.assertRaises(RemoteError):
                session.get(REG_FRAME_URL)
        self.assertEqual(len(opener.requests), 1)

    def test_response_without_usable_headers(self):
        class BareOpener:
            def __init__(self, response):
                self.response = response
                self.requests = []

            def open(self, request, timeout=None):
                self.requests.append(request)
                return self.response

        for headers in (None, object()):
            with self.subTest(headers=headers):
                response = resp("ok")
                response.headers = headers
                session, _ = make_session([])
                session._opener = BareOpener(response)
                result = session.get(REG_FRAME_URL)
                self.assertEqual(result.headers, {})
                self.assertEqual(result.url, REG_FRAME_URL)

    def test_get_final_url_after_redirect(self):
        final = "https://u.4399.com/register.html"
        session, _ = make_session([resp("ok", 200, {}, final)])
        result = session.get(REG_FRAME_URL)
        self.assertEqual(result.url, final)

    def test_response_body_is_capped(self):
        from gen4399.remote._http import MAX_BODY_BYTES

        response = resp("x" * (MAX_BODY_BYTES + 10))
        session, _ = make_session([response])
        body = session.get(REG_FRAME_URL).body
        self.assertEqual(len(body), MAX_BODY_BYTES)
        self.assertEqual(response.read_args, [MAX_BODY_BYTES])

    def test_response_decode_errors_replaced(self):
        session, _ = make_session([resp(b"ok\xff")])
        self.assertIn("ok", session.get(REG_FRAME_URL).body)


class TestRemoteSessionPost(unittest.TestCase):
    def test_post_success(self):
        session, opener = make_session([resp("注册成功", 200, {}, REGISTER_URL)])
        result = session.post(
            REGISTER_URL,
            {"username": "abc12345", "password": "x y&z", "sec": "1"},
        )
        self.assertEqual(result.status, 200)
        self.assertEqual(result.body, "注册成功")
        self.assertEqual(result.url, REGISTER_URL)
        request = opener.requests[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(
            request.data,
            b"username=abc12345&password=x+y%26z&sec=1",
        )
        headers = request_headers(request)
        self.assertEqual(
            headers["content-type"],
            "application/x-www-form-urlencoded",
        )
        self.assertIn("Mozilla", headers["user-agent"])
        self.assertEqual(headers["referer"], DEFAULT_REFERER)
        self.assertEqual(headers["accept-language"], "zh-CN,zh;q=0.9")

    def test_post_never_retries_5xx(self):
        policy = RetryPolicy(attempts=3, base_delay=0)
        session, opener = make_session([resp("", 503)], policy=policy)
        with mock.patch("gen4399.remote._http.time.sleep") as sleep:
            with self.assertRaises(RemoteHTTPError) as ctx:
                session.post(REGISTER_URL, {"a": "b"})
        self.assertEqual(ctx.exception.status, 503)
        self.assertEqual(len(opener.requests), 1)
        sleep.assert_not_called()

    def test_post_never_retries_network_error(self):
        policy = RetryPolicy(attempts=3, base_delay=0)
        session, opener = make_session(
            [urllib.error.URLError("down"), resp("ok")], policy=policy
        )
        with self.assertRaises(RemoteError):
            session.post(REGISTER_URL, {"a": "b"})
        self.assertEqual(len(opener.requests), 1)

    def test_post_http_error_exception(self):
        error = urllib.error.HTTPError(
            REGISTER_URL, 500, "boom", {"Retry-After": "3"}, None
        )
        session, opener = make_session([error])
        with self.assertRaises(RemoteHTTPError) as ctx:
            session.post(REGISTER_URL, {"a": "b"})
        self.assertEqual(ctx.exception.status, 500)
        self.assertEqual(ctx.exception.retry_after, 3.0)
        self.assertEqual(len(opener.requests), 1)

    def test_post_timeout(self):
        session, opener = make_session([socket.timeout("timed out")])
        with self.assertRaises(RemoteTimeoutError):
            session.post(REGISTER_URL, {"a": "b"})
        self.assertEqual(len(opener.requests), 1)

    def test_post_network_error(self):
        session, _ = make_session([urllib.error.URLError("dns failure")])
        with self.assertRaises(RemoteError) as ctx:
            session.post(REGISTER_URL, {"a": "b"})
        self.assertNotIsInstance(ctx.exception, RemoteTimeoutError)

    def test_post_rejects_non_mapping(self):
        session, opener = make_session([])
        with self.assertRaises(TypeError):
            session.post(REGISTER_URL, [("a", "b")])
        self.assertEqual(opener.requests, [])

    def test_post_final_url_after_redirect(self):
        final = "https://u.4399.com/"
        session, _ = make_session([resp("ok", 200, {}, final)])
        result = session.post(REGISTER_URL, {"a": "b"})
        self.assertEqual(result.url, final)

    def test_session_cookies_empty_initially(self):
        session, _ = make_session([])
        self.assertEqual(session.cookies, {})


class TestRemoteSessionCookies(unittest.TestCase):
    def test_get_stores_cookie(self):
        session, _ = make_session(
            [resp("ok", 200, {"Set-Cookie": "USESSIONID=abc; Path=/"})]
        )
        session.get(REG_FRAME_URL)
        self.assertEqual(session.cookies, {"USESSIONID": "abc"})

    def test_cookie_sent_on_followup_request(self):
        session, opener = make_session(
            [
                resp("ok", 200, {"Set-Cookie": "USESSIONID=abc; Path=/"}),
                resp("ok"),
            ]
        )
        session.get(REG_FRAME_URL)
        session.get(REG_FRAME_URL)
        self.assertEqual(
            request_headers(opener.requests[1]).get("cookie"),
            "USESSIONID=abc",
        )

    def test_cookie_sent_on_post(self):
        session, opener = make_session(
            [
                resp("ok", 200, {"Set-Cookie": "USESSIONID=abc; Path=/"}),
                resp("ok"),
            ]
        )
        session.get(REG_FRAME_URL)
        session.post(REGISTER_URL, {"username": "abc12345"})
        self.assertEqual(
            request_headers(opener.requests[1]).get("cookie"),
            "USESSIONID=abc",
        )

    def test_post_response_cookie_is_stored(self):
        session, _ = make_session(
            [resp("ok", 200, {"Set-Cookie": "Pauth=secret; Path=/"})]
        )
        session.post(REGISTER_URL, {"a": "b"})
        self.assertEqual(session.cookies.get("Pauth"), "secret")

    def test_cookies_property_is_a_copy(self):
        session, _ = make_session(
            [resp("ok", 200, {"Set-Cookie": "USESSIONID=abc; Path=/"})]
        )
        session.get(REG_FRAME_URL)
        cookies = session.cookies
        cookies["injected"] = "1"
        self.assertNotIn("injected", session.cookies)


REG_FORM_HTML = """<!DOCTYPE html>
<html>
<body>
<form id="regForm" action="/ptlogin/register.do" method="POST">
  <input type="hidden" name="appId" value="u4399" />
  <input name="level" type="hidden" value="4">
  <input TYPE="HIDDEN" NAME='sec' VALUE='1'>
  <input type="text" id="j-username" name="username"
         value="4257237567" />
  <input type="password" name="password" />
  <input type="password" name="passwordveri" />
  <input name="realname" type="text">
  <input name="email" type="text">
  <input type="hidden" name="extra" value="a&amp;b&#33;">
  <input type="text" id="inputCaptcha" name="fCaptcha">
</form>
</body>
</html>
"""


class TestParseRegistrationForm(unittest.TestCase):
    def test_full_form(self):
        form = parse_registration_form(REG_FORM_HTML)
        self.assertIsInstance(form, RegFormSnapshot)
        self.assertEqual(form.action, REGISTER_URL)
        self.assertEqual(form.method, "post")
        self.assertEqual(
            form.hidden,
            {"appId": "u4399", "level": "4", "sec": "1", "extra": "a&b!"},
        )
        self.assertEqual(
            form.input_names,
            (
                "username",
                "password",
                "passwordveri",
                "realname",
                "email",
                "fCaptcha",
            ),
        )
        self.assertEqual(form.sec, "1")
        self.assertEqual(form.suggested_username, "4257237567")
        self.assertTrue(form.has_captcha)

    def test_attribute_order_quotes_and_multiline(self):
        html = """
        <FORM
            METHOD = 'post'
            ACTION = "/ptlogin/register.do"
        >
          <INPUT
              VALUE = '4257237567'
              TYPE = 'text'
              ID = 'j-username'
              NAME = 'username'
          >
          <INPUT NAME = 'sec' TYPE = 'hidden' VALUE = '1'>
        </FORM>
        """
        form = parse_registration_form(html)
        self.assertEqual(form.action, REGISTER_URL)
        self.assertEqual(form.method, "post")
        self.assertEqual(form.hidden, {"sec": "1"})
        self.assertEqual(form.input_names, ("username",))
        self.assertEqual(form.suggested_username, "4257237567")

    def test_unquoted_attributes(self):
        html = (
            "<form action=/ptlogin/register.do method=post novalidate>"
            "<input type=hidden name=sec value=1>"
            "<input id=j-username name=username value=abc12345>"
            "</form>"
        )
        form = parse_registration_form(html)
        self.assertEqual(form.action, REGISTER_URL)
        self.assertEqual(form.method, "post")
        self.assertEqual(form.sec, "1")
        self.assertEqual(form.suggested_username, "abc12345")

    def test_relative_action_without_leading_slash(self):
        html = '<form action="ptlogin/register.do" method="post"></form>'
        form = parse_registration_form(html)
        self.assertEqual(form.action, REGISTER_URL)

    def test_absolute_action_is_preserved(self):
        html = (
            '<form action="https://ptlogin.4399.com/ptlogin/register.do'
            '?x=1&amp;y=2" method="post"></form>'
        )
        form = parse_registration_form(html)
        self.assertEqual(
            form.action,
            "https://ptlogin.4399.com/ptlogin/register.do?x=1&y=2",
        )

    def test_missing_action_falls_back_to_register_url(self):
        form = parse_registration_form('<form method="post"></form>')
        self.assertEqual(form.action, REGISTER_URL)

    def test_empty_action_falls_back_to_register_url(self):
        form = parse_registration_form('<form action="" method="post"></form>')
        self.assertEqual(form.action, REGISTER_URL)

    def test_missing_method_defaults_to_get(self):
        form = parse_registration_form('<form action="/x"></form>')
        self.assertEqual(form.method, "get")

    def test_missing_sec_is_empty(self):
        form = parse_registration_form(
            '<form><input type="hidden" name="appId" value="u4399"></form>'
        )
        self.assertEqual(form.sec, "")
        self.assertEqual(form.hidden, {"appId": "u4399"})

    def test_no_captcha(self):
        form = parse_registration_form(
            '<form><input type="text" name="username"></form>'
        )
        self.assertFalse(form.has_captcha)
        self.assertEqual(form.suggested_username, "")

    def test_hidden_without_value_is_empty_string(self):
        form = parse_registration_form(
            '<form><input type="hidden" name="flag"></form>'
        )
        self.assertEqual(form.hidden["flag"], "")

    def test_inputs_outside_form_are_ignored(self):
        html = (
            '<input type="hidden" name="outside" value="x">'
            '<form action="/ptlogin/register.do">'
            '<input type="hidden" name="inside" value="y">'
            "</form>"
            '<input type="text" name="after">'
        )
        form = parse_registration_form(html)
        self.assertEqual(form.hidden, {"inside": "y"})
        self.assertEqual(form.input_names, ())

    def test_html_entities_in_username(self):
        form = parse_registration_form(
            '<form><input id="j-username" value="a&amp;b"></form>'
        )
        self.assertEqual(form.suggested_username, "a&b")

    def test_missing_form_raises(self):
        with self.assertRaises(RemoteParseError):
            parse_registration_form("<html><body>changed</body></html>")

    def test_non_str_raises_type_error(self):
        with self.assertRaises(TypeError):
            parse_registration_form(None)  # type: ignore[arg-type]

    def test_snapshot_is_frozen(self):
        form = parse_registration_form("<form></form>")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            form.action = "x"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()


class TestFormContentType(unittest.TestCase):
    """表单 POST 的 Content-Type 必须与浏览器完全一致（不带 charset）。

    实测 2026-11-08：多带 ``; charset=UTF-8`` 时 4399 返回 202 +
    「请稍后再试~」，看着像限流，其实是请求头不合浏览器。
    """

    def test_form_content_type_matches_browser(self):
        from gen4399.remote import _http

        self.assertEqual(
            _http._FORM_CONTENT_TYPE, "application/x-www-form-urlencoded"
        )
        self.assertNotIn("charset", _http._FORM_CONTENT_TYPE)
