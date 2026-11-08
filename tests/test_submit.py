"""gen4399.submit 的单元测试：全部打桩，不联网、不创建真实账号。"""

import json
import unittest
from unittest import mock

from gen4399._aes import decrypt_aes
from gen4399._des import encode_4399
from gen4399.registration import RegistrationBundle, prepare_registration
from gen4399.forms import RegistrationProfile
from gen4399.remote import DEFAULT_TIMEOUT, RemoteError, RetryPolicy
from gen4399.remote import _http
from gen4399.submit import (
    WEB_REG_API,
    SubmitError,
    SubmitResult,
    _extract_error_message,
    _page_excerpt,
    _safe_url,
    submit_registration,
)

VALID_ID = "460206194611192084"
PROFILE = RegistrationProfile("张三", VALID_ID, qq="123456789")
ENDPOINT = "https://ptlogin.4399.com/ptlogin/register.do"

REG_FORM_HTML = """<!DOCTYPE html>
<html><head><script>var appId='u4399';</script></head><body>
<form onSubmit="return check_reg_new('Msg');" id="reg_form" name="reg_form"
      method="post" action="/ptlogin/register.do">
    <input type="hidden" name="postLoginHandler" value="refreshParent"/>
    <input type="hidden" name="displayMode" value="embed"/>
    <input type="hidden" name="appId" value="u4399"/>
    <input type="hidden" name="regMode" value="reg_normal"/>
    <input type="hidden" name="level" value="4"/>
    <input type="hidden" name="mainDivId" value="popup_reg_div"/>
    <input type="hidden" name="sec" value="1"/>
    <input type="hidden" name="password" value=""/>
    <input type="hidden" name="passwordveri" value=""/>
    <input type="hidden" name="realname" value=""/>
    <input type="hidden" name="idcard" value=""/>
    <input type="text" id="j-username" name="username" value="4257237567"/>
    <input type="checkbox" id="reg_eula_agree" name="reg_eula_agree"/>
</form>
</body></html>"""

REJECT_HTML = (
    '<html><body><div id="Msg" class="login_hor login_err_tip">'
    "用户名格式错误</div></body></html>"
)
SUCCESS_HTML = (
    "<html><script>window.parent.isAutoRegSuccess=true;</script></html>"
)
#: unified 实测成功页的简化版：Messenger.emit + 回显用户名/密码
UNIFIED_SUCCESS_HTML = (
    "<html><body><script>"
    'msnger.emit("isAutoRegSuccess",true);'
    "</script>"
    "注册成功 请一定记住您注册的用户名和密码！"
    "用户名：abc12345 密码：Sup3rSecret"
    "</body></html>"
)
CAPTCHA_HTML = "<html><body>请输入验证码</body></html>"
UNKNOWN_HTML = "<html><body>系统繁忙</body></html>"
THROTTLE_HTML = "<html><body>请稍后再试~</body></html>"


class FakeSession:
    """替身 RemoteSession：记录 GET/POST，可按测试注入响应与 Cookie。"""

    get_response = None
    post_response = None
    post_cookies: dict[str, str] = {}
    instances: list["FakeSession"] = []

    def __init__(self, *, timeout: float = DEFAULT_TIMEOUT, policy=None) -> None:
        self.timeout = timeout
        self.policy = policy
        self.cookies: dict[str, str] = {}
        self.get_calls: list[str] = []
        self.post_calls: list[tuple[str, dict[str, str]]] = []
        FakeSession.instances.append(self)

    def get(self, url: str):
        self.get_calls.append(url)
        response = self.get_response
        if isinstance(response, Exception):
            raise response
        return response

    def post(self, url: str, data):
        self.post_calls.append((url, dict(data)))
        response = self.post_response
        if isinstance(response, Exception):
            raise response
        self.cookies.update(self.post_cookies)
        return response


def response(body: str, *, status: int = 200, url: str = ENDPOINT):
    return _http.HttpResponse(
        status=status, url=url, headers={"Content-Type": "text/html"}, body=body
    )


class SubmitTestBase(unittest.TestCase):
    def setUp(self):
        FakeSession.instances = []
        FakeSession.post_cookies = {}
        self.session_patch = mock.patch(
            "gen4399.submit._http.RemoteSession", FakeSession
        )
        self.session_patch.start()
        self.addCleanup(self.session_patch.stop)
        self.bundle = prepare_registration(
            PROFILE, path="unified", verify_username=False
        )
        FakeSession.get_response = response(REG_FORM_HTML)
        FakeSession.post_response = response(SUCCESS_HTML)

    @property
    def session(self) -> FakeSession:
        return FakeSession.instances[-1]


class TestSubmitResult(unittest.TestCase):
    def make(self, **kwargs):
        base = dict(
            ok=True,
            kind="success",
            message="注册成功",
            username="abc12345",
            path="unified",
            app_id="u4399",
            endpoint=ENDPOINT,
            encrypted_fields=("password",),
            login_cookies=("Pauth",),
            field_names=("username", "password"),
        )
        base.update(kwargs)
        return SubmitResult(**base)

    def test_bool(self):
        self.assertTrue(self.make())
        self.assertFalse(self.make(ok=False, kind="rejected"))

    def test_repr_is_masked(self):
        text = repr(self.make())
        self.assertIn("SubmitResult", text)
        self.assertNotIn("secret", text)

    def test_repr_includes_new_fields(self):
        text = repr(self.make(captcha_attempts=2, verified=True))
        self.assertIn("captcha_attempts=2", text)
        self.assertIn("verified=True", text)

    def test_to_dict_is_json_safe(self):
        data = self.make().to_dict()
        self.assertEqual(data["kind"], "success")
        self.assertEqual(data["login_cookies"], ["Pauth"])
        json.dumps(data, ensure_ascii=False)

    def test_to_dict_no_cookie_values(self):
        result = self.make(login_cookies=("Pauth",))
        self.assertNotIn("Pauth=", json.dumps(result.to_dict()))


class TestValidation(SubmitTestBase):
    def test_bundle_type(self):
        with self.assertRaises(TypeError):
            submit_registration("not-a-bundle")  # type: ignore[arg-type]

    def test_unsupported_path(self):
        bundle = RegistrationBundle(
            path="phone",
            url="https://example.test/reg",
            username="abc12345",
            password="Abc123456",
            realname=PROFILE.realname,
            idcard=PROFILE.idcard,
            qq=None,
        )
        with self.assertRaises(SubmitError):
            submit_registration(bundle, dry_run=True)

    def test_bad_app_id(self):
        with self.assertRaises(ValueError):
            submit_registration(self.bundle, app_id="", dry_run=True)

    def test_bad_level(self):
        with self.assertRaises(ValueError):
            submit_registration(self.bundle, level=-1, dry_run=True)
        with self.assertRaises(ValueError):
            submit_registration(
                self.bundle, level=True, dry_run=True  # type: ignore[arg-type]
            )

    def test_bad_timeout(self):
        with self.assertRaises(ValueError):
            submit_registration(self.bundle, timeout=0, dry_run=True)
        with self.assertRaises(TypeError):
            submit_registration(
                self.bundle, timeout="x", dry_run=True  # type: ignore[arg-type]
            )


class TestDryRun(SubmitTestBase):
    def test_no_post(self):
        result = submit_registration(
            self.bundle, dry_run=True, timeout=7.5
        )
        self.assertEqual(result.kind, "dry_run")
        self.assertFalse(result.ok)
        self.assertTrue(result.dry_run)
        self.assertEqual(result.endpoint, ENDPOINT)
        self.assertTrue(
            self.session.get_calls[0].startswith(
                "https://ptlogin.4399.com/ptlogin/regFrame.do?"
            )
        )
        self.assertEqual(self.session.post_calls, [])
        self.assertEqual(result.encrypted_fields,
                         ("password", "passwordveri", "realname", "idcard"))
        self.assertIn("username", result.field_names)
        self.assertNotIn(self.bundle.password, json.dumps(result.to_dict()))

    def test_session_options(self):
        policy = RetryPolicy(attempts=2)
        submit_registration(
            self.bundle, dry_run=True, timeout=4.2, retry_policy=policy
        )
        self.assertEqual(self.session.timeout, 4.2)
        self.assertIs(self.session.policy, policy)


class TestPayloadBuilding(SubmitTestBase):
    def test_hidden_fields_merged_and_overridden(self):
        submit_registration(self.bundle)
        url, data = self.session.post_calls[0]
        self.assertEqual(url, ENDPOINT)
        # 服务端隐藏域保留（布局/前端校验开关除外，见 UNIFIED_DROP_FIELDS）
        self.assertEqual(data["postLoginHandler"], "refreshParent")
        self.assertEqual(data["regMode"], "reg_normal")
        self.assertNotIn("mainDivId", data)
        self.assertNotIn("showRegInfo", data)
        # 显式字段被覆盖
        self.assertEqual(data["username"], self.bundle.username)
        self.assertEqual(data["appId"], "u4399")
        self.assertEqual(data["level"], "4")
        self.assertNotIn("email", data)
        self.assertNotIn("reg_eula_agree", data)
        self.assertEqual(data["sec"], "1")

    def test_layout_fields_dropped(self):
        """布局/前端校验开关不回传（否则服务端返回空白 info_page）。"""
        from gen4399.submit import UNIFIED_DROP_FIELDS

        submit_registration(self.bundle)
        _, data = self.session.post_calls[0]
        for name in UNIFIED_DROP_FIELDS:
            self.assertNotIn(name, data, name)
        for name in ("username", "password", "passwordveri", "realname", "idcard"):
            self.assertIn(name, data, name)

    def test_sensitive_fields_encrypted(self):
        submit_registration(self.bundle)
        _, data = self.session.post_calls[0]
        for name in ("password", "passwordveri", "realname", "idcard"):
            self.assertNotEqual(data[name], "")
            self.assertTrue(data[name].startswith("U2FsdGVkX1"), name)
        self.assertEqual(decrypt_aes(data["password"]), self.bundle.password)
        self.assertEqual(decrypt_aes(data["passwordveri"]), self.bundle.password)
        self.assertEqual(decrypt_aes(data["realname"]), PROFILE.realname)
        self.assertEqual(decrypt_aes(data["idcard"]), PROFILE.idcard)

    def test_send_realname_switch_off(self):
        """把 UNIFIED_SEND_REALNAME 关掉就只发用户名/密码（默认是开）。"""
        with mock.patch("gen4399.submit.UNIFIED_SEND_REALNAME", False):
            result = submit_registration(self.bundle, dry_run=True)
        self.assertNotIn("realname", result.field_names)
        self.assertNotIn("idcard", result.field_names)
        self.assertEqual(result.encrypted_fields, ("password", "passwordveri"))

    def test_sec_zero_sends_plaintext(self):
        FakeSession.get_response = response(
            REG_FORM_HTML.replace('name="sec" value="1"',
                                  'name="sec" value="0"')
        )
        submit_registration(self.bundle)
        _, data = self.session.post_calls[0]
        self.assertEqual(data["password"], self.bundle.password)
        self.assertEqual(data["idcard"], PROFILE.idcard)
        self.assertEqual(data["sec"], "0")

    def test_app_id_and_level_options(self):
        submit_registration(self.bundle, app_id="my", level=0)
        url, data = self.session.post_calls[0]
        self.assertIn("appId=my", self.session.get_calls[0])
        self.assertIn("level=0", self.session.get_calls[0])
        self.assertEqual(data["appId"], "my")
        self.assertEqual(data["level"], "0")

    def test_missing_sec_defaults_to_encrypt(self):
        FakeSession.get_response = response(
            REG_FORM_HTML.replace(
                '<input type="hidden" name="sec" value="1"/>', ""
            )
        )
        result = submit_registration(self.bundle, dry_run=True)
        self.assertEqual(result.encrypted_fields,
                         ("password", "passwordveri", "realname", "idcard"))


class TestVerifyAccount(unittest.TestCase):
    """注册成功后的账号复核（尽力而为）。"""

    class Session:
        def __init__(self, response=None, error=None):
            self._response = response
            self._error = error
            self.calls = []

        def get(self, url):
            self.calls.append(url)
            if self._error is not None:
                raise self._error
            return self._response

    def test_username_on_page(self):
        from gen4399.submit import _verify_account

        session = self.Session(response=response("<html>欢迎 abc12345</html>"))
        self.assertTrue(_verify_account(session, "abc12345"))
        self.assertTrue(session.calls[0].startswith("https://u.4399.com"))

    def test_login_page_means_not_verified(self):
        from gen4399.submit import _verify_account

        session = self.Session(response=response("<html>请登录后查看</html>"))
        self.assertFalse(_verify_account(session, "abc12345"))

    def test_network_error_is_inconclusive(self):
        from gen4399.submit import _verify_account

        session = self.Session(error=RemoteError("boom"))
        self.assertIsNone(_verify_account(session, "abc12345"))

    def test_empty_body_is_inconclusive(self):
        from gen4399.submit import _verify_account

        self.assertIsNone(_verify_account(self.Session(response=response("")), "abc12345"))

    def test_unknown_page_is_inconclusive(self):
        from gen4399.submit import _verify_account

        session = self.Session(response=response("<html>4399 首页</html>"))
        self.assertIsNone(_verify_account(session, "abc12345"))


class TestVerifyWiring(SubmitTestBase):
    def test_success_runs_verification(self):
        FakeSession.post_response = response(SUCCESS_HTML)
        with mock.patch(
            "gen4399.submit._verify_account", return_value=True
        ) as verify:
            result = submit_registration(self.bundle)
        self.assertTrue(result.ok)
        self.assertTrue(result.verified)
        verify.assert_called_once()

    def test_verify_false_skips(self):
        FakeSession.post_response = response(SUCCESS_HTML)
        with mock.patch("gen4399.submit._verify_account") as verify:
            result = submit_registration(self.bundle, verify=False)
        self.assertIsNone(result.verified)
        verify.assert_not_called()

    def test_rejected_does_not_verify(self):
        FakeSession.post_response = response(REJECT_HTML)
        with mock.patch("gen4399.submit._verify_account") as verify:
            result = submit_registration(self.bundle)
        self.assertFalse(result.ok)
        self.assertIsNone(result.verified)
        verify.assert_not_called()


class TestClassify(SubmitTestBase):
    def test_rejected_message(self):
        FakeSession.post_response = response(REJECT_HTML)
        result = submit_registration(self.bundle)
        self.assertEqual(result.kind, "rejected")
        self.assertFalse(result.ok)
        self.assertEqual(result.message, "用户名格式错误")
        self.assertEqual(result.http_status, 200)

    def test_rejected_message_strips_nested_tags(self):
        FakeSession.post_response = response(
            '<div id="Msg">用户名<strong>格式</strong>错误</div>'
        )
        result = submit_registration(self.bundle)
        self.assertEqual(result.message, "用户名格式错误")

    def test_success_marker(self):
        FakeSession.post_response = response(SUCCESS_HTML)
        result = submit_registration(self.bundle)
        self.assertEqual(result.kind, "success")
        self.assertTrue(result.ok)
        self.assertTrue(result)
        self.assertIn("isAutoRegSuccess", result.message)

    def test_unified_live_success_page(self):
        """实测成功页（简化）：isAutoRegSuccess + 回显用户名/密码。"""
        FakeSession.post_response = response(UNIFIED_SUCCESS_HTML)
        FakeSession.post_cookies = {
            "Pauth": "x", "Uauth": "x", "Xauth": "x",
            "Puser": "x", "Pnick": "x", "ck_accname": "x",
        }
        result = submit_registration(self.bundle)
        self.assertEqual(result.kind, "success")
        self.assertTrue(result.ok)
        self.assertIn("Pauth", result.login_cookies)
        self.assertIn("ck_accname", result.login_cookies)
        # 成功页会回显明文密码，message 里不能带出来
        self.assertNotIn(self.bundle.password, result.message)

    def test_success_login_cookie(self):
        FakeSession.post_cookies = {"USESSIONID": "u", "Pauth": "secret"}
        FakeSession.post_response = response("<html></html>")
        result = submit_registration(self.bundle)
        self.assertEqual(result.kind, "success")
        self.assertEqual(result.login_cookies, ("Pauth",))
        self.assertNotIn("secret", json.dumps(result.to_dict()))

    def test_success_redirect(self):
        FakeSession.post_response = response(
            "<html></html>", url="https://u.4399.com/"
        )
        result = submit_registration(self.bundle)
        self.assertEqual(result.kind, "success")
        self.assertIn("u.4399.com", result.message)

    def test_final_url_strips_query(self):
        FakeSession.post_cookies = {"Pauth": "x"}
        FakeSession.post_response = response(
            "<html></html>",
            url="https://u.4399.com/home?username=abc&token=secret",
        )
        result = submit_registration(self.bundle)
        self.assertEqual(result.final_url, "https://u.4399.com/home")
        self.assertNotIn("secret", json.dumps(result.to_dict()))

    def test_captcha(self):
        FakeSession.post_response = response(CAPTCHA_HTML)
        result = submit_registration(self.bundle)
        self.assertEqual(result.kind, "captcha")
        self.assertFalse(result.ok)
        self.assertIn("验证码", result.message)

    def test_unknown(self):
        FakeSession.post_response = response(UNKNOWN_HTML)
        result = submit_registration(self.bundle)
        self.assertEqual(result.kind, "unknown")
        self.assertFalse(result.ok)
        self.assertIn("无法确定", result.message)
        self.assertIn("系统繁忙", result.message)

    def test_throttled(self):
        FakeSession.post_response = response(THROTTLE_HTML, status=202)
        result = submit_registration(self.bundle, throttle_retries=0)
        self.assertEqual(result.kind, "throttled")
        self.assertFalse(result.ok)
        self.assertIn("限流", result.message)
        self.assertIn("--min-interval", result.message)

    def test_elapsed_and_fields(self):
        FakeSession.post_response = response(SUCCESS_HTML)
        result = submit_registration(self.bundle)
        self.assertGreaterEqual(result.elapsed, 0.0)
        self.assertIn("username", result.field_names)
        self.assertEqual(result.path, "unified")
        self.assertEqual(result.app_id, "u4399")


    def test_success_marker_wins_over_msg_text(self):
        FakeSession.post_response = response(
            '<div id="Msg">注册成功，正在跳转…</div>'
            "<script>window.parent.isAutoRegSuccess = true;</script>"
        )
        result = submit_registration(self.bundle)
        self.assertEqual(result.kind, "success")

    def test_comparison_not_treated_as_success(self):
        FakeSession.post_response = response(
            '<div id="Msg"></div><script>var isAutoRegSuccess=false;'
            "if (isAutoRegSuccess == true) {}</script>"
        )
        result = submit_registration(self.bundle)
        self.assertNotEqual(result.kind, "success")

    def test_emit_form_success(self):
        FakeSession.post_response = response(
            '<script>msnger.emit("isAutoRegSuccess",true);</script>'
        )
        result = submit_registration(self.bundle)
        self.assertEqual(result.kind, "success")

    def test_captcha_before_redirect(self):
        FakeSession.post_response = response(
            "<html>请输入验证码</html>",
            url="https://u.4399.com/captcha.html",
        )
        result = submit_registration(self.bundle)
        self.assertEqual(result.kind, "captcha")

    def test_rejected_message_redacts_pii(self):
        FakeSession.post_response = response(
            f'<div id="Msg">身份证号 {VALID_ID} 格式错误</div>'
        )
        result = submit_registration(self.bundle)
        self.assertEqual(result.kind, "rejected")
        self.assertNotIn(VALID_ID, result.message)
        self.assertNotIn(VALID_ID, json.dumps(result.to_dict()))
        self.assertIn("***", result.message)

    def test_long_message_redacts_before_truncation(self):
        FakeSession.post_response = response(
            '<div id="Msg">' + "x" * 280 + f"身份证 {VALID_ID} 错误</div>"
        )
        result = submit_registration(self.bundle)
        self.assertEqual(result.kind, "rejected")
        self.assertNotIn("4602", result.message)
        self.assertIn("***", result.message)


class TestWebSubmit(SubmitTestBase):
    def setUp(self):
        super().setUp()
        self.web_bundle = prepare_registration(
            PROFILE, path="web", verify_username=False
        )
        FakeSession.get_response = response(
            'cb_1({"state":false,"data":"5c43e3"})'
        )
        FakeSession.post_response = response(
            'cb_2({"state":true,"validateState":"2"})'
        )

    def test_dry_run(self):
        result = submit_registration(self.web_bundle, dry_run=True)
        self.assertEqual(result.kind, "dry_run")
        self.assertEqual(result.path, "web")
        self.assertEqual(result.endpoint, WEB_REG_API)
        self.assertEqual(result.app_id, "")
        self.assertEqual(result.encrypted_fields,
                         ("login_password", "relogin_pwd"))
        self.assertIn("login_name", result.field_names)
        self.assertTrue(self.session.get_calls[0].startswith(
            "https://web.4399.com/user/?_c=login&_a=checkUser&"
        ))
        self.assertIn("user=" + self.web_bundle.username,
                      self.session.get_calls[0])
        self.assertEqual(self.session.post_calls, [])
        self.assertNotIn(self.web_bundle.password,
                         json.dumps(result.to_dict()))

    def test_payload_and_password_encryption(self):
        submit_registration(self.web_bundle)
        url, data = self.session.post_calls[0]
        self.assertTrue(url.startswith(WEB_REG_API))
        self.assertIn("jsoncallback=gen4399reg_", url)
        self.assertEqual(data["cid"], "3000")
        self.assertEqual(data["login_name"], self.web_bundle.username)
        self.assertEqual(data["true_name"], PROFILE.realname)
        self.assertEqual(data["sfz"], PROFILE.idcard)
        self.assertEqual(data["qq"], PROFILE.qq)
        self.assertEqual(data["encrypt"], "1")
        expected = encode_4399(self.web_bundle.password, "5c43e3")
        self.assertEqual(data["login_password"], expected)
        self.assertEqual(data["relogin_pwd"], expected)
        self.assertTrue(data["login_password"].startswith("0x"))
        self.assertNotEqual(data["login_password"], self.web_bundle.password)

    def test_success_state(self):
        result = submit_registration(self.web_bundle)
        self.assertEqual(result.kind, "success")
        self.assertTrue(result.ok)
        self.assertIn("state=true", result.message)
        self.assertEqual(result.http_status, 200)

    def test_success_validate_state_note(self):
        FakeSession.post_response = response(
            'cb({"state":true,"validateState":"3"})'
        )
        result = submit_registration(self.web_bundle)
        self.assertEqual(result.kind, "success")
        self.assertIn("validateState=3", result.message)

    def test_rejected(self):
        FakeSession.post_response = response(
            'cb({"state":false,"code":100,"msg":"用户名已被注册"})'
        )
        result = submit_registration(self.web_bundle)
        self.assertEqual(result.kind, "rejected")
        self.assertEqual(result.message, "用户名已被注册")

    def test_captcha_codes(self):
        for code in (200, 360):
            with self.subTest(code=code):
                FakeSession.post_response = response(
                    'cb({"state":false,"code":%d,"msg":"请验证"})' % code
                )
                result = submit_registration(self.web_bundle)
                self.assertEqual(result.kind, "captcha")
                self.assertIn("验证码", result.message)

    def test_unknown_non_jsonp_response(self):
        FakeSession.post_response = response("<html>error page</html>")
        result = submit_registration(self.web_bundle)
        self.assertEqual(result.kind, "unknown")
        self.assertIn("无法解析", result.message)

    def test_success_by_login_cookie(self):
        FakeSession.post_cookies = {"Pauth": "secret"}
        FakeSession.post_response = response('cb({"state":false})')
        result = submit_registration(self.web_bundle)
        self.assertEqual(result.kind, "success")
        self.assertEqual(result.login_cookies, ("Pauth",))

    def test_check_user_missing_data(self):
        FakeSession.get_response = response('cb({"state":false})')
        with self.assertRaises(Exception):
            submit_registration(self.web_bundle, dry_run=True)

    def test_check_user_bad_jsonp(self):
        FakeSession.get_response = response("<html>challenge</html>")
        with self.assertRaises(Exception):
            submit_registration(self.web_bundle, dry_run=True)

    def test_message_redacts_pii(self):
        FakeSession.post_response = response(
            'cb({"state":false,"code":100,'
            f'"msg":"身份证号 {VALID_ID} 格式错误"}})'
        )
        result = submit_registration(self.web_bundle)
        self.assertEqual(result.kind, "rejected")
        self.assertNotIn(VALID_ID, result.message)
        self.assertIn("***", result.message)

    def test_post_error_propagates(self):
        FakeSession.post_response = RemoteError("boom")
        with self.assertRaises(RemoteError):
            submit_registration(self.web_bundle)


class TestResponseHook(SubmitTestBase):
    def test_unified_hook_receives_response(self):
        seen = []
        submit_registration(self.bundle, on_response=seen.append)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].status, 200)
        self.assertIn("isAutoRegSuccess", seen[0].body)

    def test_dry_run_does_not_call_hook(self):
        seen = []
        submit_registration(self.bundle, dry_run=True, on_response=seen.append)
        self.assertEqual(seen, [])

    def test_web_hook_receives_response(self):
        web = prepare_registration(PROFILE, path="web", verify_username=False)
        FakeSession.get_response = response(
            'cb({"state":false,"data":"5c43e3"})'
        )
        FakeSession.post_response = response('cb({"state":true})')
        seen = []
        submit_registration(web, on_response=seen.append)
        self.assertEqual(len(seen), 1)
        self.assertIn('"state":true', seen[0].body)


class TestErrors(SubmitTestBase):
    def test_get_error_propagates(self):
        FakeSession.get_response = RemoteError("boom")
        with self.assertRaises(RemoteError):
            submit_registration(self.bundle)

    def test_post_error_propagates(self):
        FakeSession.post_response = RemoteError("boom")
        with self.assertRaises(RemoteError):
            submit_registration(self.bundle)
        self.assertEqual(len(self.session.post_calls), 1)


class TestHelpers(unittest.TestCase):
    def test_safe_url_none(self):
        self.assertIsNone(_safe_url(None))
        self.assertIsNone(_safe_url(""))

    def test_safe_url_strips_query_and_fragment(self):
        self.assertEqual(
            _safe_url("https://x.test/p?a=1#f"), "https://x.test/p"
        )

    def test_page_excerpt_truncates(self):
        excerpt = _page_excerpt("<html><body>" + "长" * 200 + "</body></html>")
        self.assertEqual(len(excerpt), 121)
        self.assertTrue(excerpt.endswith("…"))

    def test_page_excerpt_ignores_scripts(self):
        excerpt = _page_excerpt(
            "<script>var secret='x'</script><body>可见</body>"
        )
        self.assertEqual(excerpt, "可见")

    def test_extract_error_message_absent(self):
        self.assertEqual(_extract_error_message("<html></html>"), "")

    def test_remote_package_reexports(self):
        from gen4399.remote import (
            REGISTER_URL,
            HttpResponse,
            RegFormSnapshot,
            RemoteSession,
            parse_registration_form,
        )

        self.assertTrue(REGISTER_URL.endswith("/ptlogin/register.do"))
        self.assertEqual(HttpResponse.__name__, "HttpResponse")
        self.assertEqual(RegFormSnapshot.__name__, "RegFormSnapshot")
        self.assertTrue(callable(parse_registration_form))
        self.assertEqual(RemoteSession.__name__, "RemoteSession")


if __name__ == "__main__":
    unittest.main()


class TestMaskProxy(unittest.TestCase):
    def test_masks_credentials(self):
        from gen4399._submit_types import mask_proxy

        self.assertEqual(
            mask_proxy("http://user:pass@1.2.3.4:8080"), "http://***@1.2.3.4:8080"
        )
        self.assertEqual(mask_proxy("http://1.2.3.4:80"), "http://1.2.3.4:80")
        self.assertIsNone(mask_proxy(None))
        self.assertIsNone(mask_proxy(object()))  # 非字符串一律当作没有

    def test_to_dict_includes_proxy(self):
        r = SubmitResult(
            ok=True, kind="success", message="ok", username="a", path="web",
            app_id="", proxy="http://***@1.2.3.4:8080",
        )
        self.assertEqual(r.to_dict()["proxy"], "http://***@1.2.3.4:8080")


class ThrottleBackoffTest(SubmitTestBase):
    """服务端限流（202）时的自动退避重试。"""

    def setUp(self):
        super().setUp()
        self._responses = []
        outer = self

        class SeqSession(FakeSession):
            def post(self, url, data):  # noqa: D401 - 测试替身
                self.post_calls.append((url, dict(data)))
                resp = outer._responses.pop(0)
                if isinstance(resp, Exception):
                    raise resp
                return resp

        self.session_patch.stop()
        self.session_patch = mock.patch(
            "gen4399.submit._http.RemoteSession", SeqSession
        )
        self.session_patch.start()
        self.addCleanup(self.session_patch.stop)

    def test_retry_then_success(self):
        self._responses = [
            response(THROTTLE_HTML, status=202),
            response(SUCCESS_HTML),
        ]
        with mock.patch("gen4399.submit.time.sleep") as sleep:
            result = submit_registration(
                self.bundle, throttle_retries=1, throttle_backoff=5.0
            )
        self.assertEqual(result.kind, "success")
        sleep.assert_called_once_with(5.0)

    def test_backoff_doubles(self):
        self._responses = [
            response(THROTTLE_HTML, status=202),
            response(THROTTLE_HTML, status=202),
            response(SUCCESS_HTML),
        ]
        with mock.patch("gen4399.submit.time.sleep") as sleep:
            result = submit_registration(
                self.bundle, throttle_retries=2, throttle_backoff=5.0
            )
        self.assertEqual(result.kind, "success")
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [5.0, 10.0])

    def test_exhausted_adds_note(self):
        self._responses = [
            response(THROTTLE_HTML, status=202),
            response(THROTTLE_HTML, status=202),
        ]
        with mock.patch("gen4399.submit.time.sleep"):
            result = submit_registration(
                self.bundle, throttle_retries=1, throttle_backoff=0.0
            )
        self.assertEqual(result.kind, "throttled")
        self.assertIn("已自动退避重试 1 次", result.message)

    def test_zero_retries_no_sleep(self):
        self._responses = [response(THROTTLE_HTML, status=202)]
        with mock.patch("gen4399.submit.time.sleep") as sleep:
            result = submit_registration(self.bundle, throttle_retries=0)
        self.assertEqual(result.kind, "throttled")
        sleep.assert_not_called()

    def test_invalid_retry_args(self):
        with self.assertRaises(TypeError):
            submit_registration(self.bundle, throttle_retries="1")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            submit_registration(self.bundle, throttle_retries=-1)
        with self.assertRaises(ValueError):
            submit_registration(self.bundle, throttle_backoff=-1.0)
