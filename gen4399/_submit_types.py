"""提交结果类型与文本工具（``gen4399.submit`` 的内部拆分）。

只放不依赖提交流程状态的东西：``SubmitResult`` / ``SubmitError``、结果工厂、
以及脱敏与 HTML 文本提取的小工具。
"""

from __future__ import annotations

import html
import re
import time
import urllib.parse
from dataclasses import dataclass
from typing import Literal

from .core import Gen4399Error
from .registration import RegistrationBundle
from .remote import _http

__all__ = [
    "SubmitKind",
    "SubmitError",
    "SubmitResult",
    "_dry_run_result",
    "_final_result",
    "_safe_url",
    "_visible_text",
    "_extract_error_message",
    "_page_excerpt",
    "_redact_text",
    "mask_proxy",
]

#: ``SubmitResult.kind`` 的合法取值
SubmitKind = Literal[
    "success", "rejected", "captcha", "throttled", "unknown", "dry_run"
]

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_SCRIPT_RE = re.compile(r"<(script|style)\b.*?</\1>", re.I | re.S)

#: 失败信息所在的 ``<div id="Msg">``
_MSG_RE = re.compile(
    r"""<div\b[^>]*\bid\s*=\s*["']Msg["'][^>]*>(.*?)</div>""",
    re.I | re.S,
)

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
    proxy: str | None = None
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
            f"verified={self.verified!r}, proxy={self.proxy!r})"
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
            "proxy": self.proxy,
            "elapsed": round(self.elapsed, 3),
        }


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
    proxy: str | None = None,
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
        proxy=proxy,
        elapsed=time.monotonic() - started,
    )


def mask_proxy(proxy: str | None) -> str | None:
    """把代理 URL 里的账号密码打码（``http://user:pass@h:p`` → ``http://***@h:p``）。"""
    if not proxy or not isinstance(proxy, str):
        return None
    parts = urllib.parse.urlsplit(proxy)
    if parts.username or parts.password:
        netloc = parts.hostname or ""
        if parts.port:
            netloc += f":{parts.port}"
        return urllib.parse.urlunsplit(
            (parts.scheme, f"***@{netloc}", "", "", "")
        )
    return proxy


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
