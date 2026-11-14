"""提交响应的分类器（``gen4399.submit`` 的内部拆分）。"""

from __future__ import annotations

import json
import re
import urllib.parse

from ._submit_types import SubmitKind, _extract_error_message, _page_excerpt
from .remote import RemoteParseError

__all__ = [
    "_JSONP_RE",
    "_SUCCESS_RE",
    "_THROTTLE_RE",
    "_INFO_PAGE_RE",
    "_parse_jsonp",
    "_classify_response",
    "_classify_web_response",
]

_JSONP_RE = re.compile(
    r"^[A-Za-z_$][\w$]*\s*\((.*)\)\s*;?\s*$", re.S
)

_SUCCESS_RE = re.compile(
    r"""isAutoRegSuccess["']?\s*(?:=(?!=)|,|:)\s*true""", re.I
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_SCRIPT_RE = re.compile(r"<(script|style)\b.*?</\1>", re.I | re.S)

#: 服务端重渲染表单里的图形验证码 id（``captcha.do?captchaId=…``）
_CAPTCHA_ID_RE = re.compile(r"captchaId=([A-Za-z0-9]+)")

#: 注册成功后复核账号用的页面（同一会话带 Pauth 等 Cookie 访问）
VERIFY_URL = "https://u.4399.com/"

#: 服务端限流文案（``202`` + 「请稍后再试~」等）
_THROTTLE_RE = re.compile(
    r"请稍后再试|稍后再试|操作过[于快]频繁|访问频繁|lastFalse\s*limit", re.I
)

#: 4399 的「提示」页外壳（``<body id="info_page">``）。实测 unified 路径在风控
#: 触发时返回这种空壳页：没有 ``#Msg``、没有登录 Cookie，内容由 JS/App 渲染，
#: 服务端不给出任何可判定的结果。
_INFO_PAGE_RE = re.compile(r"""<body[^>]*\bid\s*=\s*["']info_page["']""", re.I)

def _classify_response(
    *,
    status: int,
    body: str,
    request_url: str,
    final_url: str,
    login_cookies: tuple[str, ...],
) -> tuple[SubmitKind, bool, str]:
    """把 POST 响应分类成 ``(kind, ok, message)``（启发式）。

    判定顺序：成功标记 → 错误文案 → 登录 Cookie → 验证码 → 跳转离开 ptlogin
    → info_page 空壳页 → unknown。成功标记先于错误文案，是因为真实失败页
    只含 ``isAutoRegSuccess=false``，而成功页可能出现「注册成功，正在跳转」
    之类的 ``Msg`` 文案。

    Note:
        两条路径的成功响应都已实测：``web`` 是 ``state=true`` + ``Pauth`` 等
        Cookie；``unified`` 是 ``isAutoRegSuccess(true)`` + ``Pauth``/``Uauth``/
        ``Xauth`` 等 Cookie。``info_page`` 空壳页是回传了
        :data:`UNIFIED_DROP_FIELDS` 里的字段导致的（2.4.0 起已按需剔除）。
    """
    if _SUCCESS_RE.search(body):
        return "success", True, "注册成功（页面返回 isAutoRegSuccess=true）"

    message = _extract_error_message(body)
    if message:
        return "rejected", False, message

    if login_cookies:
        return (
            "success",
            True,
            "注册成功（服务端已下发登录 Cookie："
            + ", ".join(login_cookies)
            + "）",
        )

    if "验证码" in body or "captcha" in body.lower():
        return "captcha", False, "服务端要求图形验证码/风控校验，需人工处理"

    final_host = (urllib.parse.urlsplit(final_url).hostname or "").lower()
    request_host = (urllib.parse.urlsplit(request_url).hostname or "").lower()
    if final_host and final_host != request_host and 200 <= status < 400:
        return "success", True, f"注册成功（已从 ptlogin 跳转到 {final_host}）"

    if _THROTTLE_RE.search(body):
        return (
            "throttled",
            False,
            "服务端限流（注册接口频率限制）：请等几分钟再试，"
            "不要连续重试；可用 --min-interval 拉开间隔",
        )

    if _INFO_PAGE_RE.search(body):
        return (
            "unknown",
            False,
            "4399 返回空白「提示」页（info_page 外壳，无 #Msg、无登录 Cookie）："
            "通常是回传了 UNIFIED_DROP_FIELDS 里的字段（或实名/风控分支），"
            "无法判定注册结果。请登录 https://u.4399.com/ 确认",
        )

    excerpt = _page_excerpt(body)
    detail = f"；页面摘要：{excerpt}" if excerpt else ""
    return (
        "unknown",
        False,
        "无法确定提交结果，请登录 "
        "https://u.4399.com/ 确认" + detail,
    )


def _parse_jsonp(body: str) -> dict:
    """解析 ``callback({...})`` 形式的 JSONP 响应。"""
    match = _JSONP_RE.match(body.strip())
    if match is None:
        raise RemoteParseError("响应不是 JSONP 格式")
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise RemoteParseError("JSONP 内容不是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise RemoteParseError("JSONP 内容不是对象")
    return payload

def _classify_web_response(
    *,
    payload: dict,
    status: int,
    body: str,
    request_url: str,
    final_url: str,
    login_cookies: tuple[str, ...],
) -> tuple[SubmitKind, bool, str]:
    """把 web 路径的 JSONP 响应分类（state/code/msg/validateState）。"""
    if payload.get("state"):
        validate_state = payload.get("validateState")
        note = ""
        if validate_state not in (None, "", 2, "2"):
            note = (
                f"；validateState={validate_state}"
                "（可能需要激活或补充信息）"
            )
        return "success", True, "web 注册成功（服务端返回 state=true）" + note

    code = payload.get("code")
    message = str(payload.get("msg") or payload.get("message") or "").strip()
    if code == 200:
        detail = f"：{message}" if message else ""
        return (
            "captcha",
            False,
            "服务端要求图形验证码（code=200），需提供 captcha 识别回调" + detail,
        )
    if code == 360:
        detail = f"：{message}" if message else ""
        return "captcha", False, "手机验证码错误（code=360），需人工处理" + detail
    if message and _THROTTLE_RE.search(message):
        return "throttled", False, f"服务端限流：{message}（等几分钟再试）"
    if message:
        return "rejected", False, message
    if login_cookies:
        return (
            "success",
            True,
            "web 注册成功（服务端已下发登录 Cookie："
            + ", ".join(login_cookies)
            + "）",
        )

    excerpt = _page_excerpt(body)
    detail = f"；页面摘要：{excerpt}" if excerpt else ""
    return (
        "unknown",
        False,
        "无法确定 web 提交结果，请登录 https://u.4399.com/ 确认" + detail,
    )
