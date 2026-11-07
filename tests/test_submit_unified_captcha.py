"""unified 路径图形验证码流程测试：全部离线，不联网、不建号。

服务端在风控判定下会把 ``register.do`` 的响应重渲染成带图形验证码的表单
（``inputCaptcha`` + ``captcha.do?captchaId=…``，``<div id="Msg">验证码错误``）。
本文件验证 ``_submit_unified`` 的「取图 → 识别 → 带 fCaptcha 重提交」编排。
"""

import unittest
from unittest import mock

from gen4399.forms import RegistrationProfile
from gen4399.registration import prepare_registration
from gen4399.remote import DEFAULT_TIMEOUT, _http
from gen4399.submit import UNIFIED_CAPTCHA_API, submit_registration

VALID_ID = "460206194611192084"
PROFILE = RegistrationProfile("张三", VALID_ID)

PNG_BYTES = b"\xff\xd8\xff\xe0" + b"JFIF-captcha-bytes"

REG_FORM_HTML = """<!DOCTYPE html><html><body>
<form id="reg_form" name="reg_form" method="post"
      action="/ptlogin/register.do">
  <input type="hidden" name="postLoginHandler" value="refreshParent"/>
  <input type="hidden" name="appId" value="u4399"/>
  <input type="hidden" name="regMode" value="reg_normal"/>
  <input type="hidden" name="level" value="4"/>
  <input type="hidden" name="sessionId" value=""/>
  <input type="hidden" name="sec" value="1"/>
  <input type="hidden" name="password" value=""/>
  <input type="hidden" name="passwordveri" value=""/>
  <input type="text" name="username" value=""/>
</form>
</body></html>"""

CAPTCHA_PAGE = """<!DOCTYPE html><html><body>
<form id="reg_form" name="reg_form" method="post"
      action="/ptlogin/register.do">
  <input type="hidden" name="postLoginHandler" value="refreshParent"/>
  <input type="hidden" name="appId" value="u4399"/>
  <input type="hidden" name="regMode" value="reg_normal"/>
  <input type="hidden" name="level" value="4"/>
  <input type="hidden" name="sessionId" value="sess-2"/>
  <input type="hidden" name="sec" value="1"/>
  <input type="hidden" name="password" value=""/>
  <input type="hidden" name="passwordveri" value=""/>
  <input type="text" name="username" value=""/>
  <div id="Msg" class="login_hor login_err_tip">验证码错误</div>
  <input type="text" id="inputCaptcha" name="fCaptcha" value=""/>
  <img id='captcha' class="login_captcha"
       src="/ptlogin/captcha.do?captchaId=captchaReqABC123"/>
</form>
</body></html>"""

SUCCESS_PAGE = (
    '<html><body><script>msnger.emit("isAutoRegSuccess",true);</script>'
    "注册成功 请一定记住您注册的用户名和密码！</body></html>"
)


def make_response(body, *, status=200, url="https://ptlogin.4399.com/ptlogin/register.do",
                  content_type="text/html", raw=None, bytes_body=False):
    if bytes_body:
        return _http.HttpResponse(
            status=status, url=url,
            headers={"Content-Type": content_type},
            body=body.decode("utf-8", "replace"),
            raw=raw if raw is not None else body,
        )
    return _http.HttpResponse(
        status=status, url=url,
        headers={"Content-Type": content_type},
        body=body,
        raw=raw if raw is not None else body.encode("utf-8", "replace"),
    )


class RoutedSession:
    """按 URL 前缀路由 GET、按顺序消费 POST 的假会话。"""

    routes: list = []
    post_responses: list = []
    post_cookies: list = []
    instances: list = []

    def __init__(self, *, timeout=DEFAULT_TIMEOUT, policy=None, referer=None):
        self.timeout = timeout
        self.policy = policy
        self.referer = referer
        self.cookies: dict[str, str] = {}
        self.get_calls: list[str] = []
        self.post_calls: list[tuple[str, dict[str, str]]] = []
        RoutedSession.instances.append(self)

    def get(self, url):
        self.get_calls.append(url)
        for prefix, response in type(self).routes:
            if url.startswith(prefix):
                return response
        raise AssertionError(f"未配置 GET 路由：{url}")

    def post(self, url, data):
        index = len(self.post_calls)
        self.post_calls.append((url, dict(data)))
        responses = type(self).post_responses
        if index >= len(responses):
            raise AssertionError(f"第 {index + 1} 次 POST 超出预期")
        cookies = type(self).post_cookies
        if index < len(cookies):
            self.cookies.update(cookies[index])
        return responses[index]

    @property
    def last_post(self):
        return self.post_calls[-1][1]


class Solver:
    def __init__(self, *codes):
        self.codes = list(codes)
        self.images = []

    def __call__(self, image):
        self.images.append(image)
        if not self.codes:
            raise AssertionError("captcha 调用次数超出预期")
        return self.codes.pop(0)


class UnifiedCaptchaTestBase(unittest.TestCase):
    def setUp(self):
        RoutedSession.instances.clear()
        RoutedSession.post_cookies = []
        RoutedSession.post_responses = [make_response(CAPTCHA_PAGE)]
        RoutedSession.routes = [
            ("https://ptlogin.4399.com/ptlogin/regFrame.do",
             make_response(REG_FORM_HTML)),
            (UNIFIED_CAPTCHA_API, make_response(
                PNG_BYTES, content_type="image/jpeg", bytes_body=True)),
        ]
        patcher = mock.patch("gen4399.submit._http.RemoteSession", RoutedSession)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.bundle = prepare_registration(
            PROFILE, path="unified", verify_username=False
        )

    @property
    def session(self):
        return RoutedSession.instances[-1]


class TestUnifiedCaptchaFlow(UnifiedCaptchaTestBase):
    def test_one_round_success(self):
        RoutedSession.post_responses = [
            make_response(CAPTCHA_PAGE),
            make_response(SUCCESS_PAGE),
        ]
        RoutedSession.post_cookies = [
            {},
            {"Pauth": "x", "Uauth": "x", "Xauth": "x"},
        ]
        solver = Solver("ab12")
        result = submit_registration(
            self.bundle, captcha=solver, captcha_attempts=3
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.kind, "success")
        self.assertEqual(result.captcha_attempts, 1)
        self.assertIn("Pauth", result.login_cookies)
        self.assertEqual(solver.images, [PNG_BYTES])
        self.assertEqual(self.session.last_post["fCaptcha"], "ab12")
        self.assertIn("第 1 轮图形验证码", result.message)

    def test_captcha_id_from_page_used(self):
        RoutedSession.post_responses = [
            make_response(CAPTCHA_PAGE),
            make_response(SUCCESS_PAGE),
        ]
        RoutedSession.post_cookies = [{}, {"Pauth": "x"}]
        submit_registration(self.bundle, captcha=Solver("zz99"))
        captcha_gets = [
            url for url in self.session.get_calls
            if url.startswith(UNIFIED_CAPTCHA_API)
        ]
        self.assertEqual(len(captcha_gets), 1)
        self.assertIn("captchaId=captchaReqABC123", captcha_gets[0])

    def test_no_solver_returns_captcha_kind(self):
        result = submit_registration(self.bundle)
        self.assertFalse(result.ok)
        self.assertEqual(result.kind, "captcha")
        self.assertIn("captcha=", result.message)
        self.assertEqual(result.captcha_attempts, 0)
        self.assertFalse(
            [u for u in self.session.get_calls if u.startswith(UNIFIED_CAPTCHA_API)]
        )

    def test_empty_code_skips_resubmit(self):
        RoutedSession.post_responses = [make_response(CAPTCHA_PAGE)]
        result = submit_registration(
            self.bundle, captcha=Solver("", ""), captcha_attempts=2
        )
        self.assertEqual(result.kind, "captcha")
        self.assertEqual(result.captcha_attempts, 2)
        self.assertEqual(len(self.session.post_calls), 1)

    def test_two_rounds_then_success(self):
        RoutedSession.post_responses = [
            make_response(CAPTCHA_PAGE),
            make_response(CAPTCHA_PAGE),
            make_response(SUCCESS_PAGE),
        ]
        RoutedSession.post_cookies = [{}, {}, {"Pauth": "x"}]
        result = submit_registration(
            self.bundle, captcha=Solver("bad1", "good"), captcha_attempts=3
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.captcha_attempts, 2)

    def test_exhausted_rounds(self):
        RoutedSession.post_responses = [make_response(CAPTCHA_PAGE)] * 3
        result = submit_registration(
            self.bundle, captcha=Solver("a", "b", "c"), captcha_attempts=2
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.kind, "captcha")
        self.assertEqual(result.captcha_attempts, 2)
        self.assertIn("2 轮仍未通过", result.message)

    def test_retry_payload_uses_response_form_baseline(self):
        RoutedSession.post_responses = [
            make_response(CAPTCHA_PAGE),
            make_response(SUCCESS_PAGE),
        ]
        RoutedSession.post_cookies = [{}, {"Pauth": "x"}]
        submit_registration(self.bundle, captcha=Solver("ok01"))
        retry = self.session.last_post
        # 响应页面的新 hidden 值被采用
        self.assertEqual(retry["sessionId"], "sess-2")
        self.assertEqual(retry["postLoginHandler"], "refreshParent")
        # 敏感字段沿用首次 payload（AES 密文），不是页面里的空值
        self.assertTrue(retry["password"].startswith("U2FsdGVkX1"))
        self.assertEqual(retry["fCaptcha"], "ok01")

    def test_traditional_success_without_captcha(self):
        RoutedSession.post_responses = [make_response(SUCCESS_PAGE)]
        RoutedSession.post_cookies = [{"Pauth": "x"}]
        result = submit_registration(self.bundle)
        self.assertTrue(result.ok)
        self.assertEqual(result.captcha_attempts, 0)
        self.assertEqual(len(self.session.post_calls), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
