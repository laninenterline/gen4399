"""登录：用账号密码换 4399 登录票据（Cookie）。

协议（2026-11-08 实测）::

    POST https://ptlogin.4399.com/ptlogin/login.do?v=1
    body: appId=u4399&username=<账号>&password=<AES 密文>&sec=1
    成功 → 下发 Pauth/Uauth/Xauth/Puser/Pnick/Qnick/ck_accname/ptusertype
    失败 → HTML 里 <div id="Msg">密码错误</div> 之类

注意：**不要**把 ``loginFrame.do`` 的全套隐藏域一起回传——实测那样会拿到
空白「4399提示」页（和注册路径同一个坑）；只发最小字段即可。

典型用途：注册完立刻验一次「这个号真的能登」，比只看注册响应更可靠::

    from gen4399 import login

    r = login("myaccount", "mypassword")
    r.ok        # True
    r.cookies   # ('Pauth', 'Uauth', ...)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from ._aes import encrypt_aes
from .remote import DEFAULT_APP_ID, DEFAULT_TIMEOUT, RetryPolicy, _http

__all__ = ["LoginResult", "login", "LOGIN_URL"]

#: 登录接口
LOGIN_URL = "https://ptlogin.4399.com/ptlogin/login.do?v=1"

#: 登录成功后 4399 会下发的 Cookie 名（只看名字，不看值）
_LOGIN_COOKIE_NAMES = (
    "Pauth", "Pauths", "Uauth", "Xauth", "Puser", "Pnick", "Qnick",
    "user_4399", "ck_accname", "ptusertype",
)

_MSG_RE = re.compile(
    r"""<div\b[^>]*\bid\s*=\s*["']Msg["'][^>]*>(.*?)</div>""", re.I | re.S
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

LoginKind = Literal["success", "rejected", "captcha", "unknown"]


@dataclass(frozen=True, repr=False)
class LoginResult:
    """一次登录的结果（不含密码 / Cookie 值）。

    Attributes:
        ok: 是否登录成功。
        kind: ``success`` / ``rejected`` / ``captcha`` / ``unknown``。
        message: 人读说明；``rejected`` 时是服务端文案（如「密码错误」）。
        username: 登录用的账号。
        app_id: 登录用的 appId。
        cookies: 成功后出现的登录 Cookie **名字**。
        http_status: HTTP 状态码。
    """

    ok: bool
    kind: LoginKind
    message: str
    username: str
    app_id: str = DEFAULT_APP_ID
    cookies: tuple[str, ...] = ()
    http_status: int | None = None

    def __bool__(self) -> bool:
        return self.ok

    def __repr__(self) -> str:
        return (
            f"LoginResult(kind={self.kind!r}, ok={self.ok!r}, "
            f"username={self.username!r}, app_id={self.app_id!r}, "
            f"cookies={self.cookies!r})"
        )

    def to_dict(self) -> dict[str, object]:
        """转成可 JSON 序列化的脱敏字典。"""
        return {
            "ok": self.ok,
            "kind": self.kind,
            "message": self.message,
            "username": self.username,
            "app_id": self.app_id,
            "cookies": list(self.cookies),
            "http_status": self.http_status,
        }


def _visible_text(fragment: str) -> str:
    return _WS_RE.sub(" ", _TAG_RE.sub("", fragment)).strip()


def _classify(body: str, cookies: tuple[str, ...]) -> tuple[LoginKind, bool, str]:
    if cookies:
        return "success", True, "登录成功（服务端已下发登录 Cookie：" + "、".join(cookies) + "）"
    match = _MSG_RE.search(body)
    if match:
        message = _visible_text(match.group(1))[:200]
        if "验证码" in message:
            return "captcha", False, message
        return "rejected", False, message
    if "验证码" in body:
        return "captcha", False, "服务端要求图形验证码，需人工处理"
    return "unknown", False, "无法判定登录结果（响应既无登录 Cookie 也无错误文案）"


def login(
    username: str,
    password: str,
    *,
    app_id: str = DEFAULT_APP_ID,
    timeout: float = DEFAULT_TIMEOUT,
    retry_policy: RetryPolicy | None = None,
    transport=None,
) -> LoginResult:
    """用账号密码登录 4399，返回 :class:`LoginResult`。

    Args:
        username: 4399 账号名。
        password: 明文密码（函数内部按页面同款 AES 加密后提交）。
        app_id: 业务方 appId，默认 ``u4399``。
        timeout: 单次请求超时（秒）。
        retry_policy: GET 重试策略（本函数只发一次 POST）。
        transport: 可选的 :class:`TransportOptions`（代理 / 随机 UA）。

    Returns:
        :class:`LoginResult`；``.ok`` 为 True 表示登录成功。

    Raises:
        TypeError: 参数类型不对。
        RemoteError 子类: 网络失败。
    """
    if not isinstance(username, str) or not username:
        raise TypeError("username 必须是非空 str")
    if not isinstance(password, str) or not password:
        raise TypeError("password 必须是非空 str")

    session = (
        transport.new_session()
        if transport is not None
        else _http.RemoteSession(timeout=timeout, policy=retry_policy)
    )
    payload = {
        "appId": app_id,
        "username": username,
        "password": encrypt_aes(password),
        "sec": "1",
    }
    response = session.post(LOGIN_URL, payload)
    cookies = tuple(
        name for name in _LOGIN_COOKIE_NAMES if name in session.cookies
    )
    kind, ok, message = _classify(response.body, cookies)
    return LoginResult(
        ok=ok,
        kind=kind,
        message=message,
        username=username,
        app_id=app_id,
        cookies=cookies,
        http_status=response.status,
    )
