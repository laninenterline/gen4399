"""web 注册路径「图形验证码」流程测试：全部离线，不联网、不建号。

``gen4399.submit._submit_web`` 在服务端返回 ``code=200`` 时的编排::

    POST /user/?_c=reg                 # 首次提交（不带 chk_code）
    GET  /util/?_c=code&t=reg          # 拉验证码 PNG（绑定当前会话）
    captcha(png_bytes)                 # 调用方识别（人工 / OCR）
    GET  /user/?_c=reg&_a=verifyCode   # 校验 → {"state": true}
    POST /user/?_c=reg + chk_code      # 带验证码重提交

本文件用「按 URL 前缀路由」的假会话替换
``gen4399.submit._http.RemoteSession``：``get()`` 按前缀返回不同的
``HttpResponse``，``post()`` 按调用次数消费预设响应序列。这样既能覆盖
多轮 GET/POST，又不会碰到真实网络。

不复用 ``tests/test_submit.py`` 的 ``FakeSession``（它只返回固定响应），
避免改变既有测试的行为。
"""

import json
import unittest
from collections.abc import Callable
from unittest import mock

from gen4399.forms import RegistrationProfile
from gen4399.registration import prepare_registration
from gen4399.remote import DEFAULT_TIMEOUT, RemoteParseError
from gen4399.remote import _http
from gen4399.submit import (
    WEB_CAPTCHA_API,
    WEB_CHECK_USER_API,
    WEB_REG_API,
    WEB_VERIFY_CODE_API,
    submit_registration,
)

VALID_ID = "460206194611192084"
PROFILE = RegistrationProfile("张三", VALID_ID, qq="123456789")

#: 假 PNG：以真实的 PNG 魔数开头（0x89 不是合法 UTF-8 起始字节，
#: 所以只有走 ``HttpResponse.raw`` 才能拿到完整字节）。
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR-round-one"
OTHER_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR-round-two"

#: checkUser 的 JSONP 响应（encryptCode 固定为 5c43e3，便于断言密文）
CHECK_USER_BODY = 'gen4399cu_test({"state": false, "data": "5c43e3"})'


def jsonp(payload: dict) -> str:
    """构造 ``callback({...})`` 形式的 JSONP 响应体。"""
    return "gen4399cb_test(" + json.dumps(payload, ensure_ascii=False) + ")"


def captcha_required_body(message: str = "注册异常，需校验验证码") -> str:
    """首次注册 POST 的响应：要求图形验证码（code=200）。"""
    return jsonp({"state": False, "code": 200, "msg": message})


def success_body() -> str:
    """带 chk_code 重提交后成功（实测响应样本的简化版）。"""
    return jsonp({
        "state": True,
        "code": 300,
        "msg": "",
        "validateState": "2",
        "toUrl": "/hall.html",
    })


def verify_pass_body() -> str:
    """verifyCode 通过。"""
    return 'gen4399vc_test({"state": true})'


def verify_fail_body(message: str = "验证码错误") -> str:
    """verifyCode 未通过。"""
    return jsonp({"state": False, "msg": message})


def make_response(
    body: str,
    *,
    content_type: str = "text/html; charset=UTF-8",
    status: int = 200,
    url: str = WEB_REG_API,
) -> "_http.HttpResponse":
    """构造普通的文本 ``HttpResponse``。"""
    return _http.HttpResponse(
        status=status,
        url=url,
        headers={"Content-Type": content_type},
        body=body,
        raw=body.encode("utf-8"),
    )


def make_captcha_response(image: bytes = PNG_BYTES) -> "_http.HttpResponse":
    """构造验证码图片响应：``raw`` 是图片原始字节，``body`` 只是解码残片。"""
    return _http.HttpResponse(
        status=200,
        url=WEB_CAPTCHA_API + "&_=1700000000000",
        headers={"Content-Type": "image/png"},
        body=image.decode("utf-8", errors="replace"),
        raw=image,
    )


def static(response) -> Callable[[str], "_http.HttpResponse"]:
    """固定的 GET 响应（每次调用都返回同一个对象）。"""

    def responder(_url: str):
        return response

    return responder


def sequence(*responses) -> Callable[[str], "_http.HttpResponse"]:
    """按调用顺序返回 GET 响应；序列用尽即报错，防止测试静默多跑一轮。"""
    queue = list(responses)

    def responder(url: str):
        if not queue:
            raise AssertionError(f"GET 响应序列已用尽：{url}")
        return queue.pop(0)

    return responder


class RecordingSolver:
    """记录每次收到的图片字节，按顺序返回预设的识别结果。

    识别结果用尽后再被调用会直接报错——这样「多跑了一轮验证码」不会被
    静默忽略。本身就是可调用对象，顺带覆盖 ``captcha`` 接受类实例。
    """

    def __init__(self, *codes: object) -> None:
        self._queue = list(codes)
        self.images: list[bytes] = []

    def __call__(self, image: bytes) -> str:
        self.images.append(image)
        if not self._queue:
            raise AssertionError(
                f"captcha 调用次数超出预期（已收到 {len(self.images)} 张图）"
            )
        return self._queue.pop(0)


class RoutedFakeSession:
    """按 URL 前缀路由的假 ``RemoteSession``。

    * ``get()``：按 :attr:`routes` 的前缀顺序匹配，返回对应响应；
      没有匹配就报错（避免测试意外走真实网络）。
    * ``post()``：按调用顺序消费 :attr:`post_responses`，并记录
      ``(url, payload)``；超出预期也直接报错。

    配置放在类属性上，方便像现有 ``FakeSession`` 一样用
    ``mock.patch("gen4399.submit._http.RemoteSession", RoutedFakeSession)``
    替换；每个用例在 ``setUp`` 里重置。
    """

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
        RoutedFakeSession.instances.append(self)

    def get(self, url: str):
        self.get_calls.append(url)
        for prefix, responder in type(self).routes:
            if url.startswith(prefix):
                response = responder(url) if callable(responder) else responder
                if isinstance(response, Exception):
                    raise response
                return response
        raise AssertionError(f"未配置 GET 路由：{url}")

    def post(self, url: str, data):
        index = len(self.post_calls)
        self.post_calls.append((url, dict(data)))
        responses = type(self).post_responses
        if index >= len(responses):
            raise AssertionError(
                f"第 {index + 1} 次 POST 超出预期"
                f"（只配置了 {len(responses)} 个响应）"
            )
        cookies = type(self).post_cookies
        if index < len(cookies):
            self.cookies.update(cookies[index])
        response = responses[index]
        if isinstance(response, Exception):
            raise response
        return response

    def get_count(self, prefix: str) -> int:
        """统计命中某个前缀的 GET 次数。"""
        return sum(1 for url in self.get_calls if url.startswith(prefix))


class WebCaptchaTestBase(unittest.TestCase):
    """公共夹具：web bundle + checkUser / 验证码 / verifyCode 路由。"""

    def setUp(self):
        RoutedFakeSession.instances.clear()
        RoutedFakeSession.post_cookies = []
        RoutedFakeSession.post_responses = [
            make_response(captcha_required_body())
        ]
        RoutedFakeSession.routes = [
            (WEB_CHECK_USER_API, static(make_response(CHECK_USER_BODY))),
            (WEB_CAPTCHA_API, sequence(make_captcha_response(PNG_BYTES))),
            (WEB_VERIFY_CODE_API, sequence(make_response(verify_pass_body()))),
        ]
        patcher = mock.patch(
            "gen4399.submit._http.RemoteSession", RoutedFakeSession
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.bundle = prepare_registration(
            PROFILE, path="web", verify_username=False
        )

    @property
    def session(self) -> RoutedFakeSession:
        return RoutedFakeSession.instances[-1]

    def set_posts(self, *bodies: str) -> None:
        """按顺序设置 web 注册 POST 的响应体。"""
        RoutedFakeSession.post_responses = [
            make_response(body) for body in bodies
        ]

    def route(self, prefix: str, responder) -> None:
        """替换某个 URL 前缀的 GET 响应。"""
        RoutedFakeSession.routes = [
            (p, responder if p == prefix else r)
            for p, r in RoutedFakeSession.routes
        ]


class TestWebCaptchaFlow(WebCaptchaTestBase):
    """code=200 之后「拉图 → 识别 → 校验 → 重提交」的编排与判定。"""

    def test_success_without_captcha(self):
        """无验证码一次成功：保持原有行为，不拉图、不识别。"""
        self.set_posts(success_body())
        solver = RecordingSolver()
        result = submit_registration(self.bundle, captcha=solver)

        self.assertEqual(result.kind, "success")
        self.assertTrue(result.ok)
        self.assertEqual(result.captcha_attempts, 0)
        self.assertEqual(len(self.session.post_calls), 1)
        self.assertNotIn("chk_code", self.session.post_calls[0][1])
        self.assertEqual(self.session.get_count(WEB_CAPTCHA_API), 0)
        self.assertEqual(self.session.get_count(WEB_VERIFY_CODE_API), 0)
        self.assertEqual(solver.images, [])

    def test_captcha_required_without_solver(self):
        """code=200 且未传 captcha：kind=captcha，仅一次 POST，不重试。"""
        result = submit_registration(self.bundle)

        self.assertEqual(result.kind, "captcha")
        self.assertFalse(result.ok)
        self.assertFalse(result)
        self.assertEqual(result.captcha_attempts, 0)
        self.assertEqual(len(self.session.post_calls), 1)
        self.assertNotIn("chk_code", self.session.post_calls[0][1])
        self.assertIn("captcha=", result.message)
        self.assertEqual(self.session.get_count(WEB_CAPTCHA_API), 0)

    def test_one_round_success(self):
        """一轮验证码就通过：success、captcha_attempts=1、重提交带 chk_code。"""
        self.set_posts(captcha_required_body(), success_body())
        solver = RecordingSolver("a1b2")
        result = submit_registration(self.bundle, captcha=solver)

        self.assertEqual(result.kind, "success")
        self.assertTrue(result.ok)
        self.assertEqual(result.captcha_attempts, 1)
        self.assertIn("第 1 轮", result.message)
        self.assertEqual(result.to_dict()["captcha_attempts"], 1)

        # 首次 payload 不含 chk_code；重提交 payload 含且值正确
        first_url, first_payload = self.session.post_calls[0]
        second_url, second_payload = self.session.post_calls[1]
        self.assertTrue(first_url.startswith(WEB_REG_API))
        self.assertTrue(second_url.startswith(WEB_REG_API))
        self.assertNotIn("chk_code", first_payload)
        self.assertEqual(second_payload["chk_code"], "a1b2")
        self.assertEqual(
            first_payload["login_name"], second_payload["login_name"]
        )
        self.assertEqual(second_payload["sfz"], self.bundle.idcard)

        # GET 顺序：checkUser → 验证码图 → verifyCode（带 code 参数）→ 成功后复核
        urls = self.session.get_calls
        self.assertEqual(len(urls), 4)
        self.assertTrue(urls[3].startswith("https://u.4399.com"))
        self.assertTrue(urls[0].startswith(WEB_CHECK_USER_API))
        self.assertTrue(urls[1].startswith(WEB_CAPTCHA_API))
        self.assertTrue(urls[2].startswith(WEB_VERIFY_CODE_API))
        self.assertIn("code=a1b2", urls[2])

    def test_second_round_success(self):
        """第一轮验证码错误 → 重新取图 → 第二轮通过：captcha_attempts=2。"""
        self.set_posts(captcha_required_body(), success_body())
        self.route(
            WEB_CAPTCHA_API,
            sequence(
                make_captcha_response(PNG_BYTES),
                make_captcha_response(OTHER_PNG_BYTES),
            ),
        )
        self.route(
            WEB_VERIFY_CODE_API,
            sequence(
                make_response(verify_fail_body()),
                make_response(verify_pass_body()),
            ),
        )
        solver = RecordingSolver("bad1", "good2")
        result = submit_registration(self.bundle, captcha=solver)

        self.assertEqual(result.kind, "success")
        self.assertTrue(result.ok)
        self.assertEqual(result.captcha_attempts, 2)
        self.assertIn("第 2 轮", result.message)
        self.assertEqual(len(self.session.post_calls), 2)
        self.assertEqual(self.session.post_calls[1][1]["chk_code"], "good2")
        self.assertEqual(self.session.get_count(WEB_CAPTCHA_API), 2)
        self.assertEqual(self.session.get_count(WEB_VERIFY_CODE_API), 2)
        verify_urls = [
            url
            for url in self.session.get_calls
            if url.startswith(WEB_VERIFY_CODE_API)
        ]
        self.assertIn("code=bad1", verify_urls[0])
        self.assertIn("code=good2", verify_urls[1])

    def test_all_rounds_exhausted_default_attempts(self):
        """全部轮次验证失败：kind=captcha 且 captcha_attempts 等于默认 3。"""
        self.route(
            WEB_CAPTCHA_API,
            sequence(*[make_captcha_response(PNG_BYTES)] * 3),
        )
        self.route(
            WEB_VERIFY_CODE_API,
            sequence(*[make_response(verify_fail_body())] * 3),
        )
        solver = RecordingSolver("c1", "c2", "c3")
        result = submit_registration(self.bundle, captcha=solver)

        self.assertEqual(result.kind, "captcha")
        self.assertFalse(result.ok)
        self.assertEqual(result.captcha_attempts, 3)
        self.assertIn("3 轮", result.message)
        # 只在首提（code=200）时发了 1 次 POST，验证码没通过就不重提交
        self.assertEqual(len(self.session.post_calls), 1)
        self.assertEqual(self.session.get_count(WEB_CAPTCHA_API), 3)
        self.assertEqual(self.session.get_count(WEB_VERIFY_CODE_API), 3)

    def test_attempts_parameter_honored(self):
        """全部轮次失败时 captcha_attempts 等于入参值，而不是默认值。"""
        self.route(
            WEB_CAPTCHA_API,
            sequence(*[make_captcha_response(PNG_BYTES)] * 2),
        )
        self.route(
            WEB_VERIFY_CODE_API,
            sequence(*[make_response(verify_fail_body())] * 2),
        )
        solver = RecordingSolver("c1", "c2")
        result = submit_registration(
            self.bundle, captcha=solver, captcha_attempts=2
        )

        self.assertEqual(result.kind, "captcha")
        self.assertEqual(result.captcha_attempts, 2)
        self.assertEqual(self.session.get_count(WEB_CAPTCHA_API), 2)
        self.assertEqual(self.session.get_count(WEB_VERIFY_CODE_API), 2)

    def test_resubmit_still_requires_captcha(self):
        """每轮都校验通过、但重提交仍返回 code=200：轮数用尽后判 captcha。"""
        self.set_posts(
            captcha_required_body(),
            captcha_required_body(),
            captcha_required_body(),
        )
        self.route(
            WEB_CAPTCHA_API,
            sequence(*[make_captcha_response(PNG_BYTES)] * 2),
        )
        self.route(
            WEB_VERIFY_CODE_API,
            sequence(*[make_response(verify_pass_body())] * 2),
        )
        solver = RecordingSolver("k1", "k2")
        result = submit_registration(
            self.bundle, captcha=solver, captcha_attempts=2
        )

        self.assertEqual(result.kind, "captcha")
        self.assertFalse(result.ok)
        self.assertEqual(result.captcha_attempts, 2)
        self.assertIn("2 轮", result.message)
        # 1 次首提 + 2 次带 chk_code 的重提交
        self.assertEqual(len(self.session.post_calls), 3)
        self.assertEqual(
            [payload["chk_code"] for _, payload in self.session.post_calls[1:]],
            ["k1", "k2"],
        )

    def test_empty_code_skips_verify(self):
        """识别结果为空串：跳过 verifyCode，但仍占用一轮并重新取图。"""
        self.route(
            WEB_CAPTCHA_API,
            sequence(
                make_captcha_response(PNG_BYTES),
                make_captcha_response(OTHER_PNG_BYTES),
            ),
        )
        solver = RecordingSolver("", "")
        result = submit_registration(
            self.bundle, captcha=solver, captcha_attempts=2
        )

        self.assertEqual(result.kind, "captcha")
        self.assertEqual(result.captcha_attempts, 2)
        self.assertEqual(self.session.get_count(WEB_CAPTCHA_API), 2)
        self.assertEqual(self.session.get_count(WEB_VERIFY_CODE_API), 0)
        self.assertEqual(len(self.session.post_calls), 1)

    def test_empty_code_then_success(self):
        """第一轮识别为空 → 第二轮识别通过：success、captcha_attempts=2。"""
        self.set_posts(captcha_required_body(), success_body())
        self.route(
            WEB_CAPTCHA_API,
            sequence(
                make_captcha_response(PNG_BYTES),
                make_captcha_response(OTHER_PNG_BYTES),
            ),
        )
        solver = RecordingSolver("", "ok42")
        result = submit_registration(self.bundle, captcha=solver)

        self.assertEqual(result.kind, "success")
        self.assertTrue(result.ok)
        self.assertEqual(result.captcha_attempts, 2)
        self.assertEqual(self.session.get_count(WEB_VERIFY_CODE_API), 1)
        self.assertEqual(self.session.post_calls[1][1]["chk_code"], "ok42")

    def test_verify_non_jsonp_then_success(self):
        """verifyCode 返回非 JSONP 文本：不崩溃，继续重新取图重试。"""
        self.set_posts(captcha_required_body(), success_body())
        self.route(
            WEB_CAPTCHA_API,
            sequence(
                make_captcha_response(PNG_BYTES),
                make_captcha_response(OTHER_PNG_BYTES),
            ),
        )
        self.route(
            WEB_VERIFY_CODE_API,
            sequence(
                make_response("<html>waf challenge</html>"),
                make_response(verify_pass_body()),
            ),
        )
        solver = RecordingSolver("x1", "x2")
        result = submit_registration(self.bundle, captcha=solver)

        self.assertEqual(result.kind, "success")
        self.assertTrue(result.ok)
        self.assertEqual(result.captcha_attempts, 2)
        self.assertEqual(len(self.session.post_calls), 2)
        self.assertEqual(self.session.post_calls[1][1]["chk_code"], "x2")

    def test_verify_non_jsonp_exhausted(self):
        """verifyCode 一直是异常文本且轮数用尽：判 captcha，消息含解析提示。"""
        self.route(
            WEB_VERIFY_CODE_API,
            sequence(make_response("<html></html>")),
        )
        solver = RecordingSolver("x1")
        result = submit_registration(
            self.bundle, captcha=solver, captcha_attempts=1
        )

        self.assertEqual(result.kind, "captcha")
        self.assertFalse(result.ok)
        self.assertEqual(result.captcha_attempts, 1)
        self.assertIn("无法解析", result.message)

    def test_solver_receives_raw_png_bytes(self):
        """每轮 captcha 回调拿到的都是图片原始字节（含非 UTF-8 的 0x89）。"""
        self.set_posts(captcha_required_body(), success_body())
        self.route(
            WEB_CAPTCHA_API,
            sequence(
                make_captcha_response(PNG_BYTES),
                make_captcha_response(OTHER_PNG_BYTES),
            ),
        )
        self.route(
            WEB_VERIFY_CODE_API,
            sequence(
                make_response(verify_fail_body()),
                make_response(verify_pass_body()),
            ),
        )
        solver = RecordingSolver("r1", "r2")
        submit_registration(self.bundle, captcha=solver)

        self.assertEqual(solver.images, [PNG_BYTES, OTHER_PNG_BYTES])
        self.assertEqual(solver.images[0][:4], b"\x89PNG")
        # 解码后的 body 会丢失原始字节，说明库内部确实用了 HttpResponse.raw
        decoded = solver.images[0].decode("utf-8", errors="replace")
        self.assertNotEqual(
            decoded.encode("utf-8", errors="replace"), PNG_BYTES
        )

    def test_solver_output_is_stripped(self):
        """识别结果首尾空白会被去掉，再用于 verifyCode 和 chk_code。"""
        self.set_posts(captcha_required_body(), success_body())
        solver = RecordingSolver("  ab12  ")
        submit_registration(self.bundle, captcha=solver)

        self.assertEqual(self.session.post_calls[1][1]["chk_code"], "ab12")
        self.assertIn("code=ab12", self.session.get_calls[2])
        self.assertNotIn("code=+ab12", self.session.get_calls[2])

    def test_solver_none_treated_as_empty(self):
        """识别回调返回 None 等价于空串：不调用 verifyCode。"""
        solver = RecordingSolver(None)
        result = submit_registration(
            self.bundle, captcha=solver, captcha_attempts=1
        )

        self.assertEqual(result.kind, "captcha")
        self.assertEqual(result.captcha_attempts, 1)
        self.assertEqual(self.session.get_count(WEB_VERIFY_CODE_API), 0)
        self.assertEqual(len(solver.images), 1)

    def test_on_response_called_for_each_post(self):
        """每次注册 POST（含带 chk_code 的重提交）都会触发 on_response。"""
        self.set_posts(captcha_required_body(), success_body())
        seen = []
        solver = RecordingSolver("zz9")
        result = submit_registration(
            self.bundle, captcha=solver, on_response=seen.append
        )

        self.assertEqual(len(seen), 2)
        self.assertIn('"code": 200', seen[0].body)
        self.assertIn('"state": true', seen[1].body)
        self.assertTrue(result.ok)

    def test_dry_run_skips_captcha(self):
        """dry-run 不提交、不拉验证码、不调用识别回调。"""
        solver = RecordingSolver()
        result = submit_registration(
            self.bundle, dry_run=True, captcha=solver
        )

        self.assertEqual(result.kind, "dry_run")
        self.assertEqual(result.captcha_attempts, 0)
        self.assertEqual(result.endpoint, WEB_REG_API)
        self.assertEqual(self.session.post_calls, [])
        self.assertEqual(self.session.get_count(WEB_CAPTCHA_API), 0)
        self.assertEqual(solver.images, [])

    def test_captcha_body_fallback_when_raw_empty(self):
        """响应没有 raw 字节时回落到 body（UTF-8 编码）。"""
        self.route(
            WEB_CAPTCHA_API,
            static(
                _http.HttpResponse(
                    status=200,
                    url=WEB_CAPTCHA_API,
                    headers={"Content-Type": "image/png"},
                    body="fallback-bytes",
                    raw=b"",
                )
            ),
        )
        self.set_posts(captcha_required_body(), success_body())
        solver = RecordingSolver("fk1")
        result = submit_registration(self.bundle, captcha=solver)

        self.assertEqual(solver.images, [b"fallback-bytes"])
        self.assertTrue(result.ok)

    def test_empty_captcha_image_raises_parse_error(self):
        """验证码接口返回空图：抛 RemoteParseError（不静默重试/误判）。"""
        self.route(
            WEB_CAPTCHA_API,
            static(
                _http.HttpResponse(
                    status=200,
                    url=WEB_CAPTCHA_API,
                    headers={"Content-Type": "image/png"},
                    body="",
                    raw=b"",
                )
            ),
        )
        with self.assertRaises(RemoteParseError):
            submit_registration(self.bundle, captcha=RecordingSolver("x"))
        self.assertEqual(len(self.session.post_calls), 1)


class TestWebResponseEdges(WebCaptchaTestBase):
    """web 响应解析的边界：JSONP 合法但无法判定 / JSONP 本身不合法。"""

    def test_jsonp_without_state_code_msg_is_unknown(self):
        self.set_posts(jsonp({"state": False}))
        result = submit_registration(self.bundle)

        self.assertEqual(result.kind, "unknown")
        self.assertFalse(result.ok)
        self.assertIn("无法确定 web 提交结果", result.message)
        self.assertIn("页面摘要", result.message)

    def test_empty_body_unknown_without_excerpt(self):
        self.set_posts("")
        result = submit_registration(self.bundle)

        self.assertEqual(result.kind, "unknown")
        self.assertIn("无法解析", result.message)
        self.assertNotIn("页面摘要", result.message)

    def test_check_user_invalid_json(self):
        self.route(
            WEB_CHECK_USER_API,
            static(make_response('gen4399cu_bad({"state": )')),
        )
        with self.assertRaises(RemoteParseError) as ctx:
            submit_registration(self.bundle, dry_run=True)
        self.assertIn("checkUser 响应无法解析", str(ctx.exception))
        self.assertIn("JSONP 内容不是合法 JSON", str(ctx.exception))

    def test_check_user_json_not_object(self):
        self.route(
            WEB_CHECK_USER_API,
            static(make_response("gen4399cu_bad([1, 2])")),
        )
        with self.assertRaises(RemoteParseError) as ctx:
            submit_registration(self.bundle, dry_run=True)
        self.assertIn("JSONP 内容不是对象", str(ctx.exception))


class TestCaptchaArguments(WebCaptchaTestBase):
    """captcha / captcha_attempts 的入参校验（校验先于任何网络请求）。"""

    def test_captcha_attempts_must_be_positive_int(self):
        for bad in (0, -1, True, False, 1.0, "3", None):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    submit_registration(
                        self.bundle,
                        dry_run=True,
                        captcha_attempts=bad,  # type: ignore[arg-type]
                    )
        self.assertEqual(RoutedFakeSession.instances, [])

    def test_captcha_must_be_callable(self):
        for bad in ("abc", 42, b"x", [], object()):
            with self.subTest(value=bad):
                with self.assertRaises(TypeError):
                    submit_registration(
                        self.bundle,
                        dry_run=True,
                        captcha=bad,  # type: ignore[arg-type]
                    )
        self.assertEqual(RoutedFakeSession.instances, [])

    def test_none_captcha_is_allowed(self):
        result = submit_registration(
            self.bundle, dry_run=True, captcha=None, captcha_attempts=1
        )
        self.assertEqual(result.kind, "dry_run")
        self.assertEqual(result.captcha_attempts, 0)

    def test_callable_object_solver_accepted(self):
        """captcha 支持可调用对象（类实例），不要求是函数。"""
        self.set_posts(captcha_required_body(), success_body())
        solver = RecordingSolver("obj1")
        result = submit_registration(self.bundle, captcha=solver)

        self.assertTrue(callable(solver))
        self.assertTrue(result.ok)
        self.assertEqual(result.captcha_attempts, 1)


class TestHttpResponseBinary(unittest.TestCase):
    """HttpResponse.raw / is_binary：web 图形验证码依赖这两个新增能力。"""

    def test_raw_defaults_to_empty_bytes(self):
        response = _http.HttpResponse(
            status=200, url=WEB_REG_API, headers={}, body="text"
        )
        self.assertEqual(response.raw, b"")
        self.assertFalse(response.is_binary)

    def test_is_binary_for_image(self):
        for ctype in ("image/png", "image/jpeg", "application/octet-stream"):
            with self.subTest(ctype=ctype):
                response = _http.HttpResponse(
                    status=200,
                    url=WEB_CAPTCHA_API,
                    headers={"Content-Type": ctype},
                    body="",
                    raw=b"\x89PNG",
                )
                self.assertTrue(response.is_binary)
                self.assertEqual(response.raw, b"\x89PNG")

    def test_is_binary_false_for_text_like(self):
        for ctype in (
            "text/html; charset=UTF-8",
            "application/json",
            "application/javascript",
            "text/xml",
            "application/xml",
        ):
            with self.subTest(ctype=ctype):
                response = _http.HttpResponse(
                    status=200,
                    url=WEB_REG_API,
                    headers={"Content-Type": ctype},
                    body="x",
                    raw=b"x",
                )
                self.assertFalse(response.is_binary)


if __name__ == "__main__":
    unittest.main()
