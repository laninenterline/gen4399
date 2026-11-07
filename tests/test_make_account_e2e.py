"""make_account.py 全链路集成测试：真实 prepare/submit 代码 + 假 4399 传输。

不打桩 prepare_registration / submit_registration，而是替换传输层
``gen4399.submit._http.RemoteSession``：脚本、表单组装、加密、结果判定、
accounts.json 落盘都走真实实现，但不联网、不创建真实账号。
"""

import contextlib
import importlib.util
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gen4399.remote import _http

VALID_ID = "460206194611192084"
_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "make_account.py"
_spec = importlib.util.spec_from_file_location("make_account_e2e", _SCRIPT)
assert _spec is not None and _spec.loader is not None
make_account = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_account)

REG_FORM = """<html><body>
<form id="reg_form" method="post" action="/ptlogin/register.do">
<input type="hidden" name="postLoginHandler" value="refreshParent"/>
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
</form></body></html>"""

UNIFIED_SUCCESS = "<script>window.parent.isAutoRegSuccess=true;</script>"
WEB_SUCCESS = 'cb({"state":true,"validateState":"2"})'


class FakeSession:
    """假 4399 会话：unified 返回 form + 成功页；web 返回 JSONP。"""

    unified_post_body = UNIFIED_SUCCESS
    web_post_body = WEB_SUCCESS
    last_post: dict = {}
    instances: list["FakeSession"] = []

    def __init__(self, **kwargs) -> None:
        self.cookies: dict[str, str] = {}
        FakeSession.instances.append(self)

    def get(self, url: str) -> "_http.HttpResponse":
        if "regFrame.do" in url:
            body = REG_FORM
        elif "_c=login" in url and "_a=checkUser" in url:
            body = 'cb({"state":false,"data":"5c43e3"})'
        else:
            body = "<html></html>"
        return _http.HttpResponse(200, url, {}, body)

    def post(self, url: str, data) -> "_http.HttpResponse":
        FakeSession.last_post = dict(data)
        if "_c=reg" in url:
            return _http.HttpResponse(200, url, {}, self.web_post_body)
        if "isAutoRegSuccess=true" in self.unified_post_body:
            self.cookies["Pauth"] = "mock"
        return _http.HttpResponse(200, url, {}, self.unified_post_body)


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = make_account.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class MakeAccountE2E(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self.old_cwd)
        Path("sfz.txt").write_text("张三|" + VALID_ID + "\n", encoding="utf-8")
        FakeSession.last_post = {}
        FakeSession.instances = []
        FakeSession.unified_post_body = UNIFIED_SUCCESS
        FakeSession.web_post_body = WEB_SUCCESS
        p = mock.patch.object(_http, "RemoteSession", FakeSession)
        p.start()
        self.addCleanup(p.stop)

    def test_unified_full_flow_saves_account(self):
        code, out, _ = run(["--yes", "--offline", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["result"]["kind"], "success")
        self.assertEqual(data["result"]["path"], "unified")
        self.assertEqual(
            data["result"]["encrypted_fields"],
            ["password", "passwordveri", "realname", "idcard"],
        )
        # 真实组装出的 POST 字段：4 个敏感字段都是 AES 密文（含实名）
        self.assertEqual(FakeSession.last_post["sec"], "1")
        for name in ("password", "passwordveri", "realname", "idcard"):
            self.assertTrue(
                FakeSession.last_post[name].startswith("U2FsdGVkX1")
            )
        path = Path("accounts.json")
        self.assertTrue(path.exists())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["kind"], "success")
        self.assertEqual(saved[0]["username"], data["username"])

    def test_web_full_flow_saves_account(self):
        code, out, _ = run(["--yes", "--offline", "--form-path", "web", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["result"]["kind"], "success")
        self.assertEqual(data["result"]["path"], "web")
        self.assertEqual(
            data["result"]["encrypted_fields"],
            ["login_password", "relogin_pwd"],
        )
        self.assertEqual(FakeSession.last_post["encrypt"], "1")
        self.assertEqual(FakeSession.last_post["cid"], "3000")
        self.assertTrue(FakeSession.last_post["login_password"].startswith("0x"))
        self.assertEqual(len(json.loads(
            Path("accounts.json").read_text(encoding="utf-8")
        )), 1)

    def test_diagnose_saves_sanitized_response(self):
        # 真·未知结果（服务端既无错误文案也无成功标记）→ 记 unknown 并落盘
        FakeSession.unified_post_body = (
            "<html><head><title>4399提示</title></head>"
            "<body>系统繁忙</body></html>"
        )
        code, _, err = run(["--yes", "--offline", "--json", "--diagnose"])
        self.assertEqual(code, 1)
        self.assertIn("系统繁忙", err)
        files = list(Path(".").glob("registration-response-*.html"))
        self.assertEqual(len(files), 1)
        self.assertEqual(stat.S_IMODE(files[0].stat().st_mode), 0o600)
        content = files[0].read_text(encoding="utf-8")
        self.assertIn("系统繁忙", content)
        self.assertNotIn(VALID_ID, content)
        saved = json.loads(
            Path("accounts.json").read_text(encoding="utf-8")
        )
        self.assertEqual(saved[0]["kind"], "unknown")
        self.assertNotIn(saved[0]["password"], content)

    def test_throttled_does_not_save_account(self):
        # 限流（202 + 请稍后再试）→ kind=throttled，肯定没建号，不写 accounts.json
        FakeSession.unified_post_body = (
            "<html><head><title>4399提示</title></head>"
            "<body>操作频繁，请稍后再试</body></html>"
        )
        code, _, err = run(["--yes", "--offline", "--json", "--diagnose"])
        self.assertEqual(code, 1)
        self.assertIn("操作频繁", err)
        self.assertIn("频率限制", err)
        self.assertFalse(Path("accounts.json").exists())

    def test_diagnose_detects_js_risk_page(self):
        FakeSession.unified_post_body = (
            '<html><head><title>4399用户中心</title>'
            '<script src="//ptlogin.3304399.net/resource/oauthValidation.js">'
            "</script></head><body id=\"info_page\"><h2>4399提示</h2>"
            "</body></html>"
        )
        code, _, err = run(["--yes", "--offline", "--diagnose"])
        self.assertEqual(code, 1)
        self.assertIn("风控/JS 验证提示页", err)

    def test_diagnose_custom_response_file(self):
        code, _, err = run([
            "--yes", "--offline", "--diagnose", "--response-file", "resp.html",
        ])
        self.assertEqual(code, 0)
        self.assertIn("resp.html", err)
        self.assertTrue(Path("resp.html").exists())

    def test_diagnose_dry_run_has_no_response(self):
        code, _, err = run(["--diagnose"])
        self.assertEqual(code, 0)
        self.assertIn("dry-run 未发送注册 POST", err)
        self.assertEqual(list(Path(".").glob("registration-response-*.html")), [])

    def test_full_flow_rejected_does_not_save(self):
        FakeSession.unified_post_body = (
            '<div id="Msg" class="login_hor login_err_tip">用户名已被注册</div>'
        )
        code, out, _ = run(["--yes", "--offline", "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["result"]["kind"], "rejected")
        self.assertFalse(Path("accounts.json").exists())


if __name__ == "__main__":
    unittest.main()
