"""web 路径（``web.4399.com``，DES 加密 + JSONP 响应）。"""

from __future__ import annotations

import time
import urllib.parse

from .._captcha import CaptchaSolver
from .._des import encode_4399
from .._submit_classify import _classify_web_response, _parse_jsonp
from .._submit_types import (
    SubmitKind,
    SubmitResult,
    _dry_run_result,
    _final_result,
    _page_excerpt,
    _redact_text,
    mask_proxy,
)
from ..registration import RegistrationBundle
from ..transport import TransportOptions
from ..remote import RemoteParseError, RetryPolicy, _http
from . import (
    WEB_CAPTCHA_API,
    WEB_CHECK_USER_API,
    WEB_REG_API,
    WEB_VERIFY_CODE_API,
    _WEB_ENCRYPTED_FIELDS,
    ResponseHook,
)
from . import _common
from ._common import (
    _LOGIN_COOKIE_NAMES,
    jsonp_callback,
    present_login_cookies,
)

__all__ = ["submit_web"]


def _web_post_reg(
    session: "_http.RemoteSession",
    payload: dict[str, str],
    on_response: ResponseHook | None,
) -> "_http.HttpResponse":
    """发送一次 web 注册 POST（**单次**，不自动重试）。"""
    endpoint = f"{WEB_REG_API}&jsoncallback={jsonp_callback('gen4399reg')}"
    response = session.post(endpoint, payload)
    if on_response is not None:
        on_response(response)
    return response


def _web_step(
    response: "_http.HttpResponse",
    bundle: RegistrationBundle,
    login_cookies: tuple[str, ...],
) -> tuple[SubmitKind, bool, str, bool]:
    """解析一次 web 注册响应。

    Returns:
        ``(kind, ok, message, needs_image_captcha)``。
        ``needs_image_captcha`` 为 True 表示服务端返回 ``code=200``，
        需要用图形验证码重提交（不是 360 手机验证码）。
    """
    body = _redact_text(response.body, bundle)
    try:
        data = _parse_jsonp(body)
    except RemoteParseError:
        excerpt = _page_excerpt(body)
        message = (
            "web 提交响应无法解析（POST 已发送，结果未知），"
            "请登录 https://u.4399.com/ 确认"
        )
        if excerpt:
            message += f"；页面摘要：{excerpt}"
        return "unknown", False, message, False

    kind, ok, message = _classify_web_response(
        payload=data,
        status=response.status,
        body=body,
        request_url=WEB_REG_API,
        final_url=response.url,
        login_cookies=login_cookies,
    )
    needs_captcha = (not ok) and data.get("code") == 200
    return kind, ok, message, needs_captcha


def _fetch_web_captcha(session: "_http.RemoteSession") -> bytes:
    """拉一张 web 图形验证码图片（PNG 原始字节，绑定当前会话）。"""
    url = f"{WEB_CAPTCHA_API}&_={int(time.time() * 1000)}"
    response = session.get(url)
    image = response.raw or response.body.encode("utf-8", errors="replace")
    if not image:
        raise RemoteParseError("验证码接口没有返回图片数据")
    return image


def _verify_web_captcha(
    session: "_http.RemoteSession", code: str
) -> tuple[bool, str]:
    """调 ``verifyCode`` 校验图形验证码。

    Returns:
        ``(passed, reason)``；``reason`` 仅在未通过时有意义。
    """
    query = urllib.parse.urlencode({
        "jsoncallback": jsonp_callback("gen4399vc"),
        "code": code,
        "_": str(int(time.time() * 1000)),
    })
    response = session.get(f"{WEB_VERIFY_CODE_API}&{query}")
    body = response.body.strip()
    try:
        data = _parse_jsonp(body)
    except RemoteParseError:
        return False, _page_excerpt(body, limit=60) or "校验响应无法解析"
    if data.get("state"):
        return True, ""
    message = str(data.get("msg") or "").strip()
    return False, message or "验证码错误"


def _solve_web_captcha(
    session: "_http.RemoteSession", solver: CaptchaSolver
) -> tuple[bytes, str]:
    """拉图 → 调用识别回调 → 返回 ``(图片字节, 去掉首尾空白的验证码)``。"""
    image = _fetch_web_captcha(session)
    raw_code = solver(image)
    return image, str(raw_code or "").strip()


def submit_web(
    bundle: RegistrationBundle,
    *,
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
    """web 路径：checkUser 取 key → DES 加密密码 → POST /user/?_c=reg。

    服务端返回 ``code=200``（风控要求图形验证码）时，若提供了 ``captcha``
    回调，则走「拉图 → 识别 → verifyCode 校验 → 带 ``chk_code`` 重提交」，
    最多 ``captcha_attempts`` 轮。
    """
    session = (
        transport.new_session()
        if transport is not None
        else _http.RemoteSession(timeout=timeout, policy=retry_policy)
    )
    # web 流程全程用注册页做 Referer（与浏览器一致，协议保真）
    session.referer = "https://web.4399.com/user/reg.php"
    encrypt_code = _web_encrypt_code(session, bundle.username)
    payload, encrypted = _build_web_payload(bundle, encrypt_code)
    field_names = tuple(payload)

    if dry_run:
        return _dry_run_result(
            bundle,
            app_id="",
            endpoint=WEB_REG_API,
            encrypted=encrypted,
            field_names=field_names,
            started=started,
            message="dry-run：未发送 web 注册 POST（需要显式 dry_run=False / --yes）",
        )

    def login_cookies_since(before: set[str]) -> tuple[str, ...]:
        after = set(session.cookies)
        return tuple(
            name
            for name in _LOGIN_COOKIE_NAMES
            if name in after and name not in before
        )

    before = set(session.cookies)
    response = _web_post_reg(session, payload, on_response)
    kind, ok, message, needs_captcha = _web_step(
        response, bundle, login_cookies_since(before)
    )

    rounds = 0
    if needs_captcha and captcha is None:
        message = (
            "服务端要求图形验证码（code=200）：请通过 captcha= 传入识别回调"
            "（人工输入或外部 OCR）后重试"
        )
    while needs_captcha and captcha is not None and rounds < captcha_attempts:
        rounds += 1
        image, code = _solve_web_captcha(session, captcha)
        if not code:
            continue
        passed, reason = _verify_web_captcha(session, code)
        _common.notify_captcha_feedback(captcha, image, code, passed)
        if not passed:
            message = f"验证码未通过（{reason}），已重新取图重试"
            continue
        before = set(session.cookies)
        retry_payload = dict(payload)
        retry_payload["chk_code"] = code
        response = _web_post_reg(session, retry_payload, on_response)
        kind, ok, message, needs_captcha = _web_step(
            response, bundle, login_cookies_since(before)
        )
        if ok:
            message = f"web 注册成功（第 {rounds} 轮验证码后通过；{message}）"

    if not ok and needs_captcha:
        kind = "captcha"
        if rounds:
            message = (
                f"图形验证码 {rounds} 轮仍未通过（最后提示：{message}）；"
                "web 的验证码是 150×45，它的识别要用 --captcha-learn"
                "（自学习字库，实测字符准确率约 80%）或 --captcha-prompt "
                "--captcha-zoom 8 人工输入；unified 路径的 60×30 才走 --captcha-matcher"
            )

    verified = _common.verify_account(session, bundle.username) if (ok and verify) else None
    return _final_result(
        bundle,
        kind=kind,
        ok=ok,
        message=message,
        app_id="",
        endpoint=WEB_REG_API,
        response=response,
        encrypted=encrypted,
        field_names=field_names,
        login_cookies=present_login_cookies(session),
        captcha_attempts=rounds,
        verified=verified,
        started=started,
        proxy=mask_proxy(getattr(session, "proxy", None)),
    )


def _web_encrypt_code(
    session: "_http.RemoteSession", username: str
) -> str:
    """调 ``checkUser`` 取 web 路径的密码加密 key（encryptCode）。"""
    query = urllib.parse.urlencode({
        "user": username,
        "jsoncallback": jsonp_callback("gen4399cu"),
        "_": str(int(time.time() * 1000)),
    })
    response = session.get(f"{WEB_CHECK_USER_API}&{query}")
    try:
        payload = _parse_jsonp(response.body)
    except RemoteParseError as exc:
        raise RemoteParseError(f"checkUser 响应无法解析：{exc}") from exc
    code = payload.get("data")
    if not isinstance(code, str) or not code:
        raise RemoteParseError(
            "checkUser 未返回 encryptCode，接口结构可能已变化"
        )
    return code


def _build_web_payload(
    bundle: RegistrationBundle, encrypt_code: str
) -> tuple[dict[str, str], tuple[str, ...]]:
    """组装 web 路径提交字段（密码用页面同款 ``encode_4399`` 加密）。"""
    payload = {
        "cid": "3000",
        "login_name": bundle.username,
        "login_password": encode_4399(bundle.password, encrypt_code),
        "relogin_pwd": encode_4399(bundle.password, encrypt_code),
        "qq": bundle.qq or "",
        "true_name": bundle.realname,
        "sfz": bundle.idcard,
        "encrypt": "1",
    }
    return payload, _WEB_ENCRYPTED_FIELDS
