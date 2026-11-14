"""unified 路径（``ptlogin.4399.com``，AES 加密 + 表单页）。"""

from __future__ import annotations

import re
import time
import urllib.parse

from .._captcha import CaptchaSolver
from ._common import _LOGIN_COOKIE_NAMES, present_login_cookies
from .._submit_classify import _classify_response
from .._submit_types import (
    SubmitResult,
    _dry_run_result,
    _final_result,
    _redact_text,
    _safe_url,
    mask_proxy,
)
from ..registration import RegistrationBundle
from ..transport import TransportOptions
from ..remote import RemoteParseError, RetryPolicy, _http
from . import (
    UNIFIED_CAPTCHA_API,
    UNIFIED_DROP_FIELDS,
    ResponseHook,
)
from . import _common

__all__ = ["submit_unified"]

_CAPTCHA_ID_RE = re.compile(r"captchaId=([A-Za-z0-9]+)")


def submit_unified(
    bundle: RegistrationBundle,
    *,
    app_id: str,
    level: int,
    timeout: float,
    dry_run: bool,
    retry_policy: RetryPolicy | None,
    started: float,
    on_response: ResponseHook | None = None,
    captcha: CaptchaSolver | None = None,
    captcha_attempts: int = 3,
    verify: bool = True,
    transport: "TransportOptions | None" = None,
) -> SubmitResult:
    """unified 路径：regFrame.do -> AES 加密 -> POST register.do。

    服务端在风控判定下会改渲染带图形验证码的表单（``inputCaptcha`` +
    ``captcha.do?captchaId=…``），此时若提供了 ``captcha`` 回调，就取图识别后
    带 ``fCaptcha`` 重提交，最多 ``captcha_attempts`` 轮。
    """
    # 延迟导入：``UNIFIED_SEND_REALNAME`` 是模块级开关，运行期改了要立刻生效
    from . import _build_payload

    session = (
        transport.new_session()
        if transport is not None
        else _http.RemoteSession(timeout=timeout, policy=retry_policy)
    )
    form_url = _form_url(app_id, level)
    form_page = session.get(form_url)
    form = _http.parse_registration_form(form_page.body)
    action = form.action or _http.REGISTER_URL
    # 浏览器提交 regFrame 里的表单时，Referer 是 regFrame 自身、并带 Origin /
    # Sec-Fetch-*。缺少这些头时服务端会返回 202 + 「请稍后再试~」
    # （实测 2026-11-08：补齐后同一套字段直接建号成功）。
    session.referer = form_url
    session.extra_headers = {
        "Origin": "https://ptlogin.4399.com",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "iframe",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
    }

    payload, encrypted = _build_payload(bundle, form, app_id, level)
    field_names = tuple(payload)

    if dry_run:
        return _dry_run_result(
            bundle,
            app_id=app_id,
            endpoint=_safe_url(action) or "",
            encrypted=encrypted,
            field_names=field_names,
            started=started,
            message="dry-run：未发送 POST（需要显式 dry_run=False / --yes）",
        )

    def _post(
        data: dict[str, str],
    ) -> tuple["_http.HttpResponse", tuple[str, ...]]:
        before = set(session.cookies)
        resp = session.post(action, data)
        if on_response is not None:
            on_response(resp)
        new_login = tuple(
            name
            for name in _LOGIN_COOKIE_NAMES
            if name in session.cookies and name not in before
        )  # 与 _present_login_cookies 的区别：只看本次新增
        return resp, new_login

    def _classify(resp, new_login):
        return _classify_response(
            status=resp.status,
            body=_redact_text(resp.body, bundle),
            request_url=action,
            final_url=resp.url,
            login_cookies=new_login,
        )

    response, login_cookies = _post(payload)
    kind, ok, message = _classify(response, login_cookies)

    rounds = 0
    while not ok and captcha is not None and rounds < captcha_attempts:
        captcha_id = _unified_captcha_id(response.body)
        if not captcha_id:
            break
        rounds += 1
        image = _fetch_unified_captcha(session, captcha_id)
        code = str(captcha(image) or "").strip()
        if not code:
            continue
        retry_payload = _captcha_retry_payload(payload, response.body, code)
        response, login_cookies = _post(retry_payload)
        kind, ok, message = _classify(response, login_cookies)
        if ok:
            message = f"注册成功（第 {rounds} 轮图形验证码后通过；{message}）"

    if not ok and _unified_captcha_id(response.body):
        kind = "captcha"
        if captcha is None:
            message = (
                "服务端要求图形验证码（inputCaptcha）：请通过 captcha= 传入识别"
                f"回调后重试；服务端提示：{message}"
            )
        elif rounds:
            message = (
                f"图形验证码 {rounds} 轮仍未通过（最后提示：{message}）；"
                "若一直失败，可能是识别模板已过期，可改用 captcha="
                "prompt_captcha_solver() 人工输入，或用 --captcha-cmd 接外部 OCR"
            )

    verified = _common.verify_account(session, bundle.username) if (ok and verify) else None
    return _final_result(
        bundle,
        kind=kind,
        ok=ok,
        message=message,
        app_id=app_id,
        endpoint=_safe_url(action) or "",
        response=response,
        encrypted=encrypted,
        field_names=field_names,
        login_cookies=present_login_cookies(session),
        captcha_attempts=rounds,
        verified=verified,
        started=started,
        proxy=mask_proxy(getattr(session, "proxy", None)),
    )


def _unified_captcha_id(body: str) -> str:
    """从服务端重渲染的注册表单里取图形验证码的 ``captchaId``（没有则空串）。"""
    if "fCaptcha" not in body and "inputCaptcha" not in body:
        return ""
    match = _CAPTCHA_ID_RE.search(body)
    return match.group(1) if match else ""


def _fetch_unified_captcha(
    session: "_http.RemoteSession", captcha_id: str
) -> bytes:
    """拉一张 unified 图形验证码（JPEG/PNG 原始字节，绑定当前会话）。"""
    url = f"{UNIFIED_CAPTCHA_API}?captchaId={urllib.parse.quote(captcha_id)}"
    response = session.get(url)
    image = response.raw or response.body.encode("utf-8", errors="replace")
    if not image:
        raise RemoteParseError("验证码接口没有返回图片数据")
    return image


def _captcha_field_name(body: str) -> str:
    """服务端重渲染的验证码页里，验证码输入框的字段名。

    实测 2026-11-08：用户名注册的验证码页同时有 ``inputCaptcha``（可见输入框）
    和 ``fCaptcha``（手机验证码弹窗模板里的输入框），**服务端校验的是前者**；
    只发 ``fCaptcha`` 会一直得到「验证码错误」。
    """
    if 'name="inputCaptcha"' in body or "name='inputCaptcha'" in body:
        return "inputCaptcha"
    return "fCaptcha"


def _captcha_retry_payload(
    payload: dict[str, str], body: str, code: str
) -> dict[str, str]:
    """带验证码的重提交字段：优先用响应页表单的新隐藏域做基线。

    ``sessionId`` 会被页面覆盖成本次验证码的 id（服务端据此校验）。
    """
    retry = dict(payload)
    try:
        form = _http.parse_registration_form(body)
    except Exception:  # pragma: no cover - 解析失败就退回原 payload
        form = None
    if form is not None and form.hidden:
        base = {
            name: value
            for name, value in form.hidden.items()
            if name not in UNIFIED_DROP_FIELDS
        }
        for name in ("username", "password", "passwordveri"):
            if name in payload:
                base[name] = payload[name]
        retry = base
    retry[_captcha_field_name(body)] = code
    return retry


def _form_url(app_id: str, level: int) -> str:
    """构造注册面板 GET 地址（与服务端页面同参数）。"""
    params = {
        "regMode": "reg_normal",
        "postLoginHandler": "refreshParent",
        "displayMode": "",
        "bizId": "",
        "redirectUrl": "",
        "css": "",
        "appId": app_id,
        "gameId": "",
        "noEmail": "false",
        "regIdcard": "true",
        "autoLogin": "false",
        "cid": "",
        "aid": "",
        "ref": "",
        "level": str(level),
        "mainDivId": "popup_reg_div",
        "includeFcmInfo": "false",
        "externalLogin": "qq",
        "fcmFakeValidate": "false",
        "expandFcmInput": "false",
        "userNameLabel": "",
        "userNameTip": "",
        "welcomeTip": "",
        "v": str(int(time.time() * 1000)),
    }
    return f"{_http.REG_FRAME_URL}?{urllib.parse.urlencode(params)}"
