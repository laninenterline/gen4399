"""注册提交：把准备好的 :class:`RegistrationBundle` 真正 POST 到 4399。

这是 2.1.0 新增的最后一层：此前库只准备数据，不提交注册。现在提供显式的
提交能力，但**库不会自动提交**：必须由调用方显式调用 :func:`submit_registration`；
API 默认 ``dry_run=False``（**调用即提交**），推荐先传 ``dry_run=True`` 演练；
命令行默认 dry-run，必须显式加 ``--yes`` 才发送 POST。

流程（2026-11-07 对 4399 前端与接口的实测结论，详见 ``docs/submit.md``）::

    GET  /ptlogin/regFrame.do     # 拿表单隐藏域 + 会话 Cookie（USESSIONID）
      └─ 解析 <form action> / hidden / sec
    POST /ptlogin/register.do     # sec=1 时 AES 加密敏感字段
      └─ 解析 <div id="Msg"> / 登录 Cookie / isAutoRegSuccess

安全与合规：

* 只支持 ``unified`` 路径（ptlogin``register.do``）；``web`` 提交端点未经实测，
  请继续用浏览器完成。
* POST **永不自动重试**，避免超时后重复注册。
* 请仅使用本人的真实身份信息，并自行确认符合 4399 用户协议；
  不要批量注册他人账号。
* 成功判定是启发式的：4399 的成功响应未创建真实账号实测过，结果请以
  登录 ``https://u.4399.com/`` 为准。
"""

from __future__ import annotations

import html
import re
import time
import urllib.parse
from dataclasses import dataclass
from typing import Literal

from ._aes import encrypt_aes
from .core import Gen4399Error
from .registration import RegistrationBundle
from .remote import DEFAULT_APP_ID, DEFAULT_TIMEOUT, RetryPolicy
from .remote import _http

__all__ = [
    "SubmitKind",
    "SubmitError",
    "SubmitResult",
    "submit_registration",
]

#: ``SubmitResult.kind`` 的合法取值
SubmitKind = Literal["success", "rejected", "captcha", "unknown", "dry_run"]

#: ``sec=1`` 时需要加密的字段
ENCRYPTED_FIELDS = ("password", "passwordveri", "realname", "idcard")

#: 登录成功后 4399 会下发的 Cookie 名（只看名字，不看值）
_LOGIN_COOKIE_NAMES = ("Pauth", "Uauth", "Xauth", "user_4399", "ck_accname")

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
        path: 注册路径（当前只支持 ``unified``）。
        app_id: 提交用的 appId。
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
    elapsed: float = 0.0

    def __bool__(self) -> bool:  # 让 `if result:` 直接表示是否成功
        return self.ok

    def __repr__(self) -> str:
        return (
            f"SubmitResult(kind={self.kind!r}, ok={self.ok!r}, "
            f"username={self.username!r}, path={self.path!r}, "
            f"app_id={self.app_id!r}, http_status={self.http_status!r}, "
            f"dry_run={self.dry_run!r})"
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
            "elapsed": round(self.elapsed, 3),
        }


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

    ``sec`` 缺失时按 ``"1"`` 处理（与实测页面一致，宁可加密也不明文发送）。

    Returns:
        ``(payload, encrypted_fields)``。
    """
    payload = dict(form.hidden)
    payload.update({
        "username": bundle.username,
        "password": bundle.password,
        "passwordveri": bundle.password,
        "realname": bundle.realname,
        "idcard": bundle.idcard,
        "email": bundle.qq or "",
        "reg_eula_agree": "on",
        "autoLogin": "",
        "fCaptcha": "",
    })
    payload["appId"] = app_id
    payload["level"] = str(level)
    payload.setdefault("regMode", "reg_normal")

    sec = (form.sec or payload.get("sec") or "1").strip()
    payload["sec"] = sec
    encrypted: tuple[str, ...] = ()
    if sec == "1":
        for name in ENCRYPTED_FIELDS:
            payload[name] = encrypt_aes(payload[name])
        encrypted = ENCRYPTED_FIELDS
    return payload, encrypted


def _classify_response(
    *,
    status: int,
    body: str,
    request_url: str,
    final_url: str,
    login_cookies: tuple[str, ...],
) -> tuple[SubmitKind, bool, str]:
    """把 POST 响应分类成 ``(kind, ok, message)``（启发式）。

    4399 的成功响应没有实测样本，因此判定顺序为：成功标记 →
    错误文案 → 登录 Cookie → 验证码 → 跳转离开 ptlogin → unknown。
    成功标记先于错误文案，是因为真实失败页只含 ``isAutoRegSuccess=false``，
    而成功页可能出现「注册成功，正在跳转」之类的 ``Msg`` 文案。
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

    excerpt = _page_excerpt(body)
    detail = f"；页面摘要：{excerpt}" if excerpt else ""
    return (
        "unknown",
        False,
        "无法确定提交结果（4399 成功响应未经实测），请登录 "
        "https://u.4399.com/ 确认" + detail,
    )


def _validate_args(
    bundle: RegistrationBundle,
    app_id: str,
    level: int,
    timeout: float,
) -> None:
    if not isinstance(bundle, RegistrationBundle):
        raise TypeError("bundle 必须是 RegistrationBundle")
    if bundle.path != "unified":
        raise SubmitError(
            f"提交目前只支持 unified 路径（收到 {bundle.path!r}）。"
            "web 提交端点未实测，请继续用浏览器打开 bundle.url 手动提交，"
            "或先用 `prepare --form-path unified` 重新准备。"
        )
    if not isinstance(app_id, str) or not app_id:
        raise ValueError("app_id 必须是非空 str")
    if not isinstance(level, int) or isinstance(level, bool) or level < 0:
        raise ValueError("level 必须是 >= 0 的 int")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
        raise TypeError("timeout 必须是数字")
    if timeout <= 0:
        raise ValueError("timeout 必须 > 0")


def submit_registration(
    bundle: RegistrationBundle,
    *,
    app_id: str = DEFAULT_APP_ID,
    level: int = 4,
    timeout: float = DEFAULT_TIMEOUT,
    dry_run: bool = False,
    retry_policy: RetryPolicy | None = None,
) -> SubmitResult:
    """把准备好的注册数据真正 POST 提交到 4399（仅 ``unified`` 路径）。

    流程：GET ``regFrame.do`` 拿会话 Cookie 与服务端隐藏域 → 按 ``sec`` 决定是否
    用 AES 加密 ``password/passwordveri/realname/idcard`` → POST
    ``register.do`` → 解析结果。

    Args:
        bundle: :func:`gen4399.prepare_registration` 的返回值（``path="unified"``）。
        app_id: 业务方 appId，默认 ``u4399``。
        level: 注册等级，默认 4。
        timeout: 单次请求超时（秒）。
        dry_run: 为 True 时只拉取表单并组装/加密字段，**不发送 POST**。
        retry_policy: 只作用于拉取注册表单的 GET；POST 永远单次尝试。

    Returns:
        :class:`SubmitResult`；``.kind == "success"`` 表示（可判定为）成功。

    Raises:
        SubmitError: 路径不是 ``unified``。
        TypeError / ValueError: 参数不合法。
        RemoteError 子类: GET/POST 网络失败（POST 不会自动重试）。

    Examples:
        >>> from gen4399 import RegistrationProfile, prepare_registration
        >>> p = RegistrationProfile("张三", "460206194611192084")
        >>> b = prepare_registration(p, path="unified", verify_username=False)
        >>> r = submit_registration(b, dry_run=True)   # doctest: +SKIP
        >>> r.kind                                       # doctest: +SKIP
        'dry_run'
    """
    _validate_args(bundle, app_id, level, timeout)
    started = time.monotonic()

    session = _http.RemoteSession(timeout=timeout, policy=retry_policy)
    form_page = session.get(_form_url(app_id, level))
    form = _http.parse_registration_form(form_page.body)
    action = form.action or _http.REGISTER_URL

    payload, encrypted = _build_payload(bundle, form, app_id, level)
    field_names = tuple(payload)

    if dry_run:
        return SubmitResult(
            ok=False,
            kind="dry_run",
            message="dry-run：未发送 POST（需要显式 dry_run=False / --yes）",
            username=bundle.username,
            path=bundle.path,
            app_id=app_id,
            endpoint=_safe_url(action) or "",
            encrypted_fields=encrypted,
            field_names=field_names,
            dry_run=True,
            elapsed=time.monotonic() - started,
        )

    before = set(session.cookies)
    response = session.post(action, payload)
    after = set(session.cookies)
    login_cookies = tuple(
        name for name in _LOGIN_COOKIE_NAMES if name in after and name not in before
    )
    present_login = tuple(
        name for name in _LOGIN_COOKIE_NAMES if name in after
    )
    kind, ok, message = _classify_response(
        status=response.status,
        body=_redact_text(response.body, bundle),
        request_url=action,
        final_url=response.url,
        login_cookies=login_cookies,
    )
    return SubmitResult(
        ok=ok,
        kind=kind,
        message=message,
        username=bundle.username,
        path=bundle.path,
        app_id=app_id,
        endpoint=_safe_url(action) or "",
        http_status=response.status,
        final_url=_safe_url(response.url),
        encrypted_fields=encrypted,
        login_cookies=present_login,
        field_names=field_names,
        elapsed=time.monotonic() - started,
    )
