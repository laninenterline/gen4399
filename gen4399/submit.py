"""注册提交：把准备好的 :class:`RegistrationBundle` 真正提交到 4399。

支持两条注册路径（2.2.0 起 ``web`` 路径也可提交，详见 ``docs/submit.md``）::

    unified（ptlogin）
      GET  /ptlogin/regFrame.do     # 拿表单隐藏域 + 会话 Cookie（USESSIONID）
      POST /ptlogin/register.do     # 只回传 21 个必要字段（见 UNIFIED_DROP_FIELDS）
        └─ 成功页含 isAutoRegSuccess(true) 与 Pauth/Uauth/Xauth 等 Cookie

    web（web.4399.com 用户中心）
      GET  /user/?_c=login&_a=checkUser   # 取 encryptCode
      POST /user/?_c=reg                  # DES 加密密码 + JSONP 响应
        └─ 解析 {state, code, msg, validateState}
      code=200（风控要图形验证码）时：
        GET  /util/?_c=code&t=reg         # 验证码图片（绑定 WEBSESSION）
        GET  /user/?_c=reg&_a=verifyCode  # 校验验证码 → {state:true}
        POST /user/?_c=reg + chk_code     # 带验证码重提交

本库提供显式提交能力，但**不会自动提交**：必须由调用方显式调用
:func:`submit_registration`；API 默认 ``dry_run=False``（**调用即提交**），
推荐先传 ``dry_run=True`` 演练；命令行默认 dry-run，必须显式加 ``--yes``。

安全与合规：

* 两个路径的 POST **都永不自动重试**，避免超时后重复注册。
* 请仅使用本人的真实身份信息，并自行确认符合 4399 用户协议；
  不要批量注册他人账号。
* 图形验证码需要调用方提供 :data:`CaptchaSolver`（人工识别或外部 OCR）；
  本库不做验证码自动破解。
* unified 路径默认**不提交实名信息**（回传实名/协议字段会让服务端改走空白
  「4399提示」页），见 :data:`UNIFIED_SEND_REALNAME`。
"""

from __future__ import annotations

import html
import json
import re
import secrets
import time
import urllib.parse
from dataclasses import dataclass
from typing import Literal

from typing import TYPE_CHECKING

from ._aes import encrypt_aes
from .transport import TransportOptions
from ._captcha import CaptchaSolver as CaptchaSolverType
from ._des import encode_4399
from .core import Gen4399Error
from .registration import RegistrationBundle
from collections.abc import Callable

from .remote import (
    DEFAULT_APP_ID,
    DEFAULT_TIMEOUT,
    RemoteParseError,
    RetryPolicy,
)
from .remote import _http



__all__ = [
    "CaptchaSolver",
    "UNIFIED_DROP_FIELDS",
    "UNIFIED_SEND_REALNAME",
    "SubmitKind",
    "ResponseHook",
    "SubmitError",
    "SubmitResult",
    "submit_registration",
]

#: ``SubmitResult.kind`` 的合法取值
SubmitKind = Literal[
    "success", "rejected", "captcha", "throttled", "unknown", "dry_run"
]

#: 注册 POST 响应回调（诊断用；收到原始 ``HttpResponse``，不改变提交行为）
ResponseHook = Callable[["_http.HttpResponse"], None]

#: 图形验证码识别回调（唯一定义在 :mod:`gen4399._captcha`：
#: 入参是验证码图片原始字节，返回识别出的文本）。
CaptchaSolver = CaptchaSolverType

#: ``sec=1`` 时需要加密的字段
ENCRYPTED_FIELDS = ("password", "passwordveri", "realname", "idcard")

#: unified 路径要从服务端隐藏域里**剔除**的字段（2.4.0 实测定案）。
#:
#: 实测（2026-11-08）：`regFrame.do` 页面里的这些隐藏域一旦原样回传，
#: ``POST /ptlogin/register.do`` 一律返回空白「4399提示」页（``info_page``
#: 外壳：没有 ``#Msg``、不下发任何登录 Cookie），注册不会发生；剔除后
#: 同一套数据可以正常建号（成功页含 ``isAutoRegSuccess(...true)`` 与
#: ``Pauth``/``Uauth``/``Xauth`` 等 Cookie）。
#:
#: 这些字段分两类：
#:
#: * 布局/防沉迷/前端校验开关（弹窗容器 id、跨域 iframe、是否展示注册信息、
#:   实名前端校验开关等）——服务端有默认值，不需要回传；
#: * 实名与协议字段（``realname`` / ``idcard`` / ``reg_eula_agree`` 等）——
#:   一并回传时服务端会进入实名/风控分支并返回同一张空白提示页
#:   （实测假身份必然触发；未用真实身份验证过）。
UNIFIED_DROP_FIELDS = frozenset({
    "crossDomainUrl",
    "mainDivId",
    "showRegInfo",
    "includeFcmInfo",
    "expandFcmInput",
    "fcmFakeValidate",
    "realnameValidate",
    "userNameLabel",
    "iframeId",
    "email",
    "reg_eula_agree",
    "autoLogin",
    "fCaptcha",
})

#: unified 路径是否把实名信息（``realname`` / ``idcard``）一起提交。
#:
#: 默认 ``True``：实测（2026-11-08）21 字段 + ``realname``/``idcard``（AES）
#: 可以正常建号。注意**必须连带剔除** :data:`UNIFIED_DROP_FIELDS` 里的
#: ``reg_eula_agree`` / ``autoLogin`` / ``fCaptcha``——这三个一起回传时服务端
#: 会改走空白「4399提示」页。
#:
#: 想要「不实名」的账号可以改成 ``False``（只提交用户名/密码）。
UNIFIED_SEND_REALNAME = True

#: 登录成功后 4399 会下发的 Cookie 名（只看名字，不看值）
_LOGIN_COOKIE_NAMES = (
    "Pauth", "Pauths", "Uauth", "Xauth", "Puser", "Pnick", "Qnick",
    "user_4399", "ck_accname", "ptusertype",
)

#: web 路径注册提交接口（POST；浏览器用 JSONP GET，服务端同样接受 POST）
WEB_REG_API = "https://web.4399.com/user/?_c=reg"

#: web 路径取密码加密 key 的接口
WEB_CHECK_USER_API = "https://web.4399.com/user/?_c=login&_a=checkUser"

#: unified 路径图形验证码图片（绑定当前会话的 ``USESSIONID`` / 页面 captchaId）
UNIFIED_CAPTCHA_API = "https://ptlogin.4399.com/ptlogin/captcha.do"

#: web 路径图形验证码图片（绑定当前会话的 ``WEBSESSION`` Cookie）
WEB_CAPTCHA_API = "https://web.4399.com/util/?_c=code&t=reg"

#: web 路径校验图形验证码（JSONP，``state=true`` 表示通过）
WEB_VERIFY_CODE_API = "https://web.4399.com/user/?_c=reg&_a=verifyCode"

#: web 路径需要 DES 加密的字段
_WEB_ENCRYPTED_FIELDS = ("login_password", "relogin_pwd")

#: JSONP 响应：``callback({...})``（callback 名可含字母/数字/下划线/``$``）
_JSONP_RE = re.compile(
    r"^[A-Za-z_$][\w$]*\s*\((.*)\)\s*;?\s*$", re.S
)

#: 失败信息所在的 ``<div id="Msg">``
_MSG_RE = re.compile(
    r"""<div\b[^>]*\bid\s*=\s*["']Msg["'][^>]*>(.*?)</div>""",
    re.I | re.S,
)

#: 成功页标记：isAutoRegSuccess = true / emit("isAutoRegSuccess", true)
#: 只认赋值/逗号/冒号后接 true，避免把 `isAutoRegSuccess == true` 这类比较式
#: 误判为成功。
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


class SubmitError(Gen4399Error):
    """提交注册参数或状态不合法（例如路径不支持）。"""


@dataclass(frozen=True, repr=False)
class SubmitResult:
    """一次注册提交的结果。

    Attributes:
        ok: 是否（可判定为）注册成功。
        kind: 结构化结果：``success`` / ``rejected`` / ``captcha`` /
            ``unknown`` / ``dry_run``。
        message: 人读说明；rejected 时是服务端返回的错误文案。
        username: 提交的用户名（不含密码/身份证）。
        path: 注册路径（``web`` / ``unified``）。
        app_id: 提交用的 appId（web 路径不适用，返回空串）。
        endpoint: 实际提交的 POST 端点（dry-run 时也会给出）。
        http_status: POST 的 HTTP 状态码；dry-run 时为 None。
        final_url: 跟随重定向后的最终地址（已去掉 query/fragment，避免 PII）。
        encrypted_fields: 实际加密的字段名。
        login_cookies: 提交后出现的登录 Cookie **名字**（不含值）。
        field_names: 提交的字段名（不含值）。
        dry_run: 是否只是 dry-run（未发送 POST）。
        elapsed: 整个调用的耗时（秒）。

    Note:
        ``repr()`` / :meth:`to_dict` 不含密码、身份证、Cookie 值，
        可安全写入日志。
    """

    ok: bool
    kind: SubmitKind
    message: str
    username: str
    path: str
    app_id: str
    endpoint: str = ""
    http_status: int | None = None
    final_url: str | None = None
    encrypted_fields: tuple[str, ...] = ()
    login_cookies: tuple[str, ...] = ()
    field_names: tuple[str, ...] = ()
    dry_run: bool = False
    captcha_attempts: int = 0
    verified: bool | None = None
    elapsed: float = 0.0

    def __bool__(self) -> bool:  # 让 `if result:` 直接表示是否成功
        return self.ok

    def __repr__(self) -> str:
        return (
            f"SubmitResult(kind={self.kind!r}, ok={self.ok!r}, "
            f"username={self.username!r}, path={self.path!r}, "
            f"app_id={self.app_id!r}, http_status={self.http_status!r}, "
            f"dry_run={self.dry_run!r}, "
            f"captcha_attempts={self.captcha_attempts!r}, "
            f"verified={self.verified!r})"
        )

    def to_dict(self) -> dict[str, object]:
        """转成可 JSON 序列化的字典（已脱敏）。"""
        return {
            "ok": self.ok,
            "kind": self.kind,
            "message": self.message,
            "username": self.username,
            "path": self.path,
            "app_id": self.app_id,
            "endpoint": self.endpoint,
            "http_status": self.http_status,
            "final_url": self.final_url,
            "encrypted_fields": list(self.encrypted_fields),
            "login_cookies": list(self.login_cookies),
            "field_names": list(self.field_names),
            "dry_run": self.dry_run,
            "captcha_attempts": self.captcha_attempts,
            "verified": self.verified,
            "elapsed": round(self.elapsed, 3),
        }


def _present_login_cookies(session: "_http.RemoteSession") -> tuple[str, ...]:
    """当前会话里出现过的登录 Cookie **名字**（不含值）。"""
    return tuple(
        name for name in _LOGIN_COOKIE_NAMES if name in session.cookies
    )


def _dry_run_result(
    bundle: RegistrationBundle,
    *,
    app_id: str,
    endpoint: str,
    encrypted: tuple[str, ...],
    field_names: tuple[str, ...],
    started: float,
    message: str,
) -> SubmitResult:
    """构造 dry-run 结果（未发注册 POST）。"""
    return SubmitResult(
        ok=False,
        kind="dry_run",
        message=message,
        username=bundle.username,
        path=bundle.path,
        app_id=app_id,
        endpoint=endpoint,
        encrypted_fields=encrypted,
        field_names=field_names,
        dry_run=True,
        elapsed=time.monotonic() - started,
    )


def _final_result(
    bundle: RegistrationBundle,
    *,
    kind: SubmitKind,
    ok: bool,
    message: str,
    app_id: str,
    endpoint: str,
    response: "_http.HttpResponse",
    encrypted: tuple[str, ...],
    field_names: tuple[str, ...],
    login_cookies: tuple[str, ...],
    captcha_attempts: int,
    verified: bool | None,
    started: float,
) -> SubmitResult:
    """两条路径共用的终态结果构造（统一脱敏与字段映射）。"""
    return SubmitResult(
        ok=ok,
        kind=kind,
        message=_redact_text(message, bundle),
        username=bundle.username,
        path=bundle.path,
        app_id=app_id,
        endpoint=endpoint,
        http_status=response.status,
        final_url=_safe_url(response.url),
        encrypted_fields=encrypted,
        login_cookies=login_cookies,
        field_names=field_names,
        captcha_attempts=captcha_attempts,
        verified=verified,
        elapsed=time.monotonic() - started,
    )


def _safe_url(url: str | None) -> str | None:
    """去掉 query/fragment，避免把用户名等带进结果/日志。"""
    if not url:
        return None
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, "", "")
    )


def _visible_text(fragment: str) -> str:
    """把 HTML 片段压成一行纯文本。"""
    text = html.unescape(_TAG_RE.sub("", fragment))
    return _WS_RE.sub(" ", text).strip()


def _extract_error_message(body: str) -> str:
    """取 ``<div id="Msg">`` 里的错误文案；没有则返回空串。"""
    match = _MSG_RE.search(body)
    if match is None:
        return ""
    return _visible_text(match.group(1))[:300]


def _page_excerpt(body: str, limit: int = 120) -> str:
    """取页面可见文本摘要（用于 unknown 结果），不包含脚本内容。"""
    text = _visible_text(_SCRIPT_RE.sub("", body))
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def _redact_text(text: str, bundle: RegistrationBundle) -> str:
    """把文本里可能回显的密码/身份证/姓名替换成 ``***``（PII 兜底）。

    在**截断之前**对完整响应体做替换，避免「恰好被截断」时只残留身份证前缀。
    """
    for secret in (bundle.password, bundle.idcard, bundle.realname):
        if secret:
            text = text.replace(secret, "***")
    return text


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


def _build_payload(
    bundle: RegistrationBundle,
    form: "_http.RegFormSnapshot",
    app_id: str,
    level: int,
) -> tuple[dict[str, str], tuple[str, ...]]:
    """以服务端表单隐藏域为基线，组装最终 POST 字段（不联网）。

    会剔除 :data:`UNIFIED_DROP_FIELDS`（实测回传这些隐藏域会让服务端改走
    空白「4399提示」页）；实名信息只在 :data:`UNIFIED_SEND_REALNAME` 为
    真时才带（默认不带，见该常量的说明）。

    ``sec`` 缺失时按 ``"1"`` 处理（与实测页面一致，宁可加密也不明文发送）。

    Returns:
        ``(payload, encrypted_fields)``。
    """
    payload = {
        name: value
        for name, value in form.hidden.items()
        if name not in UNIFIED_DROP_FIELDS
    }
    payload.update({
        "username": bundle.username,
        "password": bundle.password,
        "passwordveri": bundle.password,
    })
    if UNIFIED_SEND_REALNAME:
        payload["realname"] = bundle.realname
        payload["idcard"] = bundle.idcard
    else:
        # 表单隐藏域里本来就有空的 realname/idcard，关掉开关时要显式去掉
        payload.pop("realname", None)
        payload.pop("idcard", None)
    payload["appId"] = app_id
    payload["level"] = str(level)
    payload.setdefault("regMode", "reg_normal")

    sec = (form.sec or payload.get("sec") or "1").strip()
    payload["sec"] = sec
    encrypted: tuple[str, ...] = ()
    if sec == "1":
        names = tuple(name for name in ENCRYPTED_FIELDS if name in payload)
        for name in names:
            payload[name] = encrypt_aes(payload[name])
        encrypted = names
    return payload, encrypted


def _verify_account(
    session: "_http.RemoteSession", username: str
) -> bool | None:
    """注册成功后用同一会话复核账号是否真的可用。

    带 ``Pauth`` 等 Cookie GET ``https://u.4399.com/``，页面里出现用户名即认为
    账号已生效；拿不到页面 / 结构变化时返回 ``None``（无法判断，不下结论）。

    Returns:
        ``True`` 已确认、``False`` 未确认（页面明确是未登录态）、``None`` 无法判断。
    """
    try:
        response = session.get(VERIFY_URL)
    except Exception:  # noqa: BLE001 - 复核是尽力而为，任何失败都只返回 None
        return None
    body = response.body
    if not body:
        return None
    if username in body:
        return True
    # 明确落到登录页 / 提示未登录，说明 Cookie 没生效
    if ("请登录" in body or "登录后" in body) and username not in body:
        return False
    return None


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


def _jsonp_callback(prefix: str = "gen4399cb") -> str:
    """生成一个合法的 JSONP 回调名。"""
    return f"{prefix}_{secrets.token_hex(6)}"


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


def _web_encrypt_code(
    session: "_http.RemoteSession", username: str
) -> str:
    """调 ``checkUser`` 取 web 路径的密码加密 key（encryptCode）。"""
    query = urllib.parse.urlencode({
        "user": username,
        "jsoncallback": _jsonp_callback("gen4399cu"),
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


def _validate_args(
    bundle: RegistrationBundle,
    app_id: str,
    level: int,
    timeout: float,
    captcha: CaptchaSolver | None = None,
    captcha_attempts: int = 3,
    transport: "TransportOptions | None" = None,
) -> None:
    if not isinstance(bundle, RegistrationBundle):
        raise TypeError("bundle 必须是 RegistrationBundle")
    if bundle.path not in ("web", "unified"):
        raise SubmitError(
            f"不支持的注册路径 {bundle.path!r}（可选 web / unified）"
        )
    if not isinstance(app_id, str) or not app_id:
        raise ValueError("app_id 必须是非空 str")
    if not isinstance(level, int) or isinstance(level, bool) or level < 0:
        raise ValueError("level 必须是 >= 0 的 int")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
        raise TypeError("timeout 必须是数字")
    if timeout <= 0:
        raise ValueError("timeout 必须 > 0")
    if transport is not None and not isinstance(transport, TransportOptions):
        raise TypeError("transport 必须是 TransportOptions 或 None")
    if captcha is not None and not callable(captcha):
        raise TypeError("captcha 必须是可调用对象（图片字节 -> 文本）或 None")
    if (
        not isinstance(captcha_attempts, int)
        or isinstance(captcha_attempts, bool)
        or captcha_attempts < 1
    ):
        raise ValueError("captcha_attempts 必须是 >= 1 的 int")


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


def _submit_unified(
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
            message = f"图形验证码 {rounds} 轮仍未通过（最后提示：{message}）"

    verified = _verify_account(session, bundle.username) if (ok and verify) else None
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
        login_cookies=_present_login_cookies(session),
        captcha_attempts=rounds,
        verified=verified,
        started=started,
    )


def _web_post_reg(
    session: "_http.RemoteSession",
    payload: dict[str, str],
    on_response: ResponseHook | None,
) -> "_http.HttpResponse":
    """发送一次 web 注册 POST（**单次**，不自动重试）。"""
    endpoint = f"{WEB_REG_API}&jsoncallback={_jsonp_callback('gen4399reg')}"
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
        "jsoncallback": _jsonp_callback("gen4399vc"),
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
) -> str:
    """拉图 → 调用调用方的识别回调 → 返回去掉首尾空白的验证码文本。"""
    image = _fetch_web_captcha(session)
    raw_code = solver(image)
    return str(raw_code or "").strip()


def _submit_web(
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
        code = _solve_web_captcha(session, captcha)
        if not code:
            continue
        passed, reason = _verify_web_captcha(session, code)
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
            message = f"图形验证码 {rounds} 轮仍未通过（最后提示：{message}）"

    verified = _verify_account(session, bundle.username) if (ok and verify) else None
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
        login_cookies=_present_login_cookies(session),
        captcha_attempts=rounds,
        verified=verified,
        started=started,
    )


def submit_registration(
    bundle: RegistrationBundle,
    *,
    app_id: str = DEFAULT_APP_ID,
    level: int = 4,
    timeout: float = DEFAULT_TIMEOUT,
    dry_run: bool = False,
    retry_policy: RetryPolicy | None = None,
    on_response: ResponseHook | None = None,
    captcha: CaptchaSolver | None = None,
    captcha_attempts: int = 3,
    verify: bool = True,
    transport: "TransportOptions | None" = None,
) -> SubmitResult:
    """把准备好的注册数据真正提交到 4399（支持 ``web`` / ``unified``）。

    ==========  =====================================================
    ``web``     ``GET user/?_c=login&_a=checkUser`` 取 encryptCode →
                ``encode_4399``（DES）加密密码 → ``POST user/?_c=reg``
                （JSONP 响应，按 ``state/code/msg`` 判定）；返回
                ``code=200`` 时用 ``captcha`` 识别图形验证码后带
                ``chk_code`` 重提交
    ``unified`` ``GET regFrame.do`` 取隐藏域/会话 → ``sec=1`` 时 AES
                加密敏感字段 → ``POST register.do``
    ==========  =====================================================

    Args:
        bundle: :func:`gen4399.prepare_registration` 的返回值。
        app_id: 业务方 appId，默认 ``u4399``（**仅 unified 使用**）。
        level: 注册等级，默认 4（**仅 unified 使用**）。
        timeout: 单次请求超时（秒）。
        dry_run: 为 True 时只拉取必要数据、组装/加密字段，**不发送注册
            POST**。web 路径仍会 GET ``checkUser``（只带用户名）。
        retry_policy: 只作用于 GET；注册 POST 永远单次尝试。
        on_response: 可选的注册 POST 响应回调（``HttpResponse``），用于诊断；
            不改变提交/判定行为。回调抛出的异常会向上传播（此时 POST 已发出）。
        captcha: 图形验证码识别回调（入参 PNG 字节，返回识别文本）。只在
            web 路径服务端返回 ``code=200`` 时调用；不传则直接返回
            ``kind="captcha"``。本库不内置破解，需调用方接入人工/OCR。
        captcha_attempts: 验证码最多重试轮数（含重新取图），必须 >= 1。

    Returns:
        :class:`SubmitResult`；``.kind == "success"`` 表示（可判定为）成功。

    Raises:
        SubmitError: 路径不是 ``web`` / ``unified``。
        TypeError / ValueError: 参数不合法。
        RemoteError 子类: GET/POST 网络失败（注册 POST 不会自动重试）。

    Examples:
        >>> from gen4399 import RegistrationProfile, prepare_registration
        >>> p = RegistrationProfile("张三", "460206194611192084")
        >>> b = prepare_registration(p, path="unified", verify_username=False)
        >>> r = submit_registration(b, dry_run=True)   # doctest: +SKIP
        >>> r.kind                                       # doctest: +SKIP
        'dry_run'
    """
    _validate_args(
        bundle, app_id, level, timeout, captcha, captcha_attempts, transport
    )
    started = time.monotonic()
    if bundle.path == "web":
        return _submit_web(
            bundle,
            timeout=timeout,
            dry_run=dry_run,
            retry_policy=retry_policy,
            started=started,
            on_response=on_response,
            captcha=captcha,
            captcha_attempts=captcha_attempts,
            verify=verify,
            transport=transport,
        )
    return _submit_unified(
        bundle,
        app_id=app_id,
        level=level,
        timeout=timeout,
        dry_run=dry_run,
        retry_policy=retry_policy,
        started=started,
        on_response=on_response,
        captcha=captcha,
        captcha_attempts=captcha_attempts,
        verify=verify,
        transport=transport,
    )
