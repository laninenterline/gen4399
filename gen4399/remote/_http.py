"""远程传输层：HTTP GET / POST 会话、错误类型、重试策略、响应解析。

本模块不包含业务语义（取号/查重/提交），由 :mod:`gen4399.remote._api` 与
:mod:`gen4399.submit` 组合使用。
"""

from __future__ import annotations

import http.cookiejar
import logging
import random
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape

from ..core import Gen4399Error

#: 模块日志器（只输出非 PII 的调试信息）
logger = logging.getLogger("gen4399.remote")

__all__ = [
    "REG_FRAME_URL",
    "REGISTER_URL",
    "IS_EXIST_URL",
    "DEFAULT_APP_ID",
    "DEFAULT_TIMEOUT",
    "DEFAULT_USER_AGENT",
    "DEFAULT_REFERER",
    "MAX_BODY_BYTES",
    "RetryPolicy",
    "DEFAULT_RETRY_POLICY",
    "DEFAULT_FETCH_RETRY_POLICY",
    "DEFAULT_CHECK_RETRY_POLICY",
    "RemoteError",
    "RemoteTimeoutError",
    "RemoteHTTPError",
    "RemoteParseError",
    "HttpResponse",
    "RegFormSnapshot",
    "parse_registration_form",
    "RemoteSession",
    "_http_get",
    "_http_get_once",
    "_parse_suggested_username",
    "_parse_retry_after",
]


#: 注册面板接口
REG_FRAME_URL = "https://ptlogin.4399.com/ptlogin/regFrame.do"

#: 注册提交接口（注册表单 action 的绝对地址）
REGISTER_URL = "https://ptlogin.4399.com/ptlogin/register.do"

#: 用户名查重接口
IS_EXIST_URL = "https://ptlogin.4399.com/ptlogin/isExist.do"

#: 默认 appId
DEFAULT_APP_ID = "u4399"

#: 默认超时（秒）
DEFAULT_TIMEOUT = 10.0

#: 请求用的 User-Agent
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

#: 请求默认 Referer
DEFAULT_REFERER = "https://u.4399.com/register.html"


@dataclass(frozen=True)
class RetryPolicy:
    """远程请求的重试策略。

    Attributes:
        attempts: 总尝试次数（含首次），必须 >= 1。
        base_delay: 第一次失败后的等待基数（秒），之后指数递增。
        max_delay: 单次等待上限（秒）。
        total_deadline: 整次调用的总时间预算（秒），``None`` 表示不限制。
        respect_retry_after: 是否优先采用服务端 ``Retry-After`` 头。
    """

    attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 10.0
    total_deadline: float | None = None
    respect_retry_after: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.attempts, int) or isinstance(self.attempts, bool):
            raise TypeError("attempts 必须是 int")
        if self.attempts < 1:
            raise ValueError("attempts 必须 >= 1")
        if self.base_delay < 0 or self.max_delay < 0:
            raise ValueError("delay 不能为负")
        if self.total_deadline is not None and self.total_deadline <= 0:
            raise ValueError("total_deadline 必须 > 0 或为 None")

    def delay_for(self, failed_attempt: int, retry_after: float | None = None) -> float:
        """返回第 ``failed_attempt`` 次失败后的等待时间（含 ±25% 抖动）。"""
        if retry_after is not None and self.respect_retry_after:
            return min(max(retry_after, 0.0), self.max_delay)
        delay = min(self.base_delay * (2 ** (failed_attempt - 1)), self.max_delay)
        return delay * (1 + random.uniform(0, 0.25))


#: 通用默认策略（单次请求，含有限重试）
DEFAULT_RETRY_POLICY = RetryPolicy()

#: 取分配账号时，单次 HTTP 请求内部的重试策略
DEFAULT_FETCH_RETRY_POLICY = RetryPolicy(attempts=2, base_delay=0.5, max_delay=2.0)

#: 查重时单次 HTTP 请求内部的重试策略
DEFAULT_CHECK_RETRY_POLICY = RetryPolicy(attempts=2, base_delay=0.5, max_delay=2.0)

# 匹配 <input ... id="j-username" ...> 整个标签：不依赖属性顺序、单双引号皆可
_INPUT_TAG_RE = re.compile(
    r"""<input\b[^>]*\bid\s*=\s*["']j-username["'][^>]*>""",
    re.I | re.S,
)
# 在标签体内取 value 属性
_VALUE_ATTR_RE = re.compile(
    r"""\bvalue\s*=\s*(?:"([^"]*)"|'([^']*)')""",
    re.I | re.S,
)

#: 请求体读取上限，避免异常接口返回超大内容
MAX_BODY_BYTES = 512 * 1024


class RemoteError(Gen4399Error):
    """调用 4399 远程接口失败。

    Attributes:
        url: 出错的请求地址（可能为 None）。
    """

    def __init__(self, message: str, *, url: str | None = None) -> None:
        super().__init__(message)
        self.url = url


class RemoteTimeoutError(RemoteError):
    """请求超时。"""


class RemoteHTTPError(RemoteError):
    """HTTP 状态码非 2xx。

    Attributes:
        status: HTTP 状态码。
        retry_after: 服务端 ``Retry-After`` 解析出的秒数（可能为 None）。
    """

    def __init__(
        self,
        message: str,
        status: int,
        *,
        retry_after: float | None = None,
        url: str | None = None,
    ) -> None:
        super().__init__(message, url=url)
        self.status = status
        self.retry_after = retry_after


class RemoteParseError(RemoteError):
    """响应内容无法解析出预期数据。"""


def _parse_retry_after(headers) -> float | None:
    """解析 ``Retry-After`` 头（秒数或 HTTP-date），失败返回 None。"""
    if headers is None:
        return None
    value = headers.get("Retry-After") if hasattr(headers, "get") else None
    if not value:
        return None
    value = str(value).strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())


def _safe_url(url: str) -> str:
    """日志用：去掉 query，避免把用户名等写进日志。"""
    return url.split("?", 1)[0]


def _http_get(
    url: str,
    timeout: float,
    *,
    retries: int = 1,
    policy: RetryPolicy | None = None,
    transport=None,
    _session=None,
) -> str:
    """带重试策略的最小 HTTP GET 封装（内部函数，便于测试时打桩）。

    Args:
        url: 请求地址。
        timeout: 单次请求超时（秒）。
        retries: 旧参数；未提供 ``policy`` 时用它构造单次策略。
        policy: 显式重试策略；超时 / 网络错误 / 5xx / 429 会重试，
            其它 4xx 直接抛出，``Retry-After`` 优先。

    Returns:
        响应体文本。

    Raises:
        RemoteTimeoutError / RemoteHTTPError / RemoteError: 请求失败。
    """
    if retries < 1:
        raise ValueError("retries 必须 >= 1")
    if _session is not None:
        # 复用调用方的会话（同一个代理 / Cookie / 重试策略）
        return _session.get(url).body
    if transport is not None:
        # 交给会话（已带代理 / UA / 重试）
        return transport.new_session().get(url).body
    if policy is None:
        policy = RetryPolicy(attempts=retries)

    start = time.monotonic()
    last_error: RemoteError | None = None
    for attempt in range(1, policy.attempts + 1):
        logger.debug(
            "GET %s (attempt %d/%d)", _safe_url(url), attempt, policy.attempts
        )
        try:
            return _http_get_once(url, timeout)
        except RemoteHTTPError as exc:
            if 400 <= exc.status < 500 and exc.status != 429:
                raise
            last_error = exc
        except RemoteError as exc:
            last_error = exc

        if attempt >= policy.attempts:
            break
        delay = policy.delay_for(attempt, getattr(last_error, "retry_after", None))
        if policy.total_deadline is not None:
            remaining = policy.total_deadline - (time.monotonic() - start)
            if remaining <= 0:
                break
            delay = min(delay, remaining)
        if delay > 0:
            logger.debug("retry in %.2fs after %s", delay, type(last_error).__name__)
            time.sleep(delay)

    assert last_error is not None
    raise last_error


def _http_get_once(url: str, timeout: float) -> str:
    """执行一次 HTTP GET 并把底层异常统一成 :class:`RemoteError` 子类。"""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Referer": DEFAULT_REFERER,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            if status and not 200 <= status < 300:
                raise RemoteHTTPError(
                    f"HTTP {status}",
                    status,
                    retry_after=_parse_retry_after(getattr(resp, "headers", None)),
                    url=url,
                )
            raw = resp.read(MAX_BODY_BYTES)
    except urllib.error.HTTPError as exc:  # 4xx / 5xx
        raise RemoteHTTPError(
            f"HTTP {exc.code}",
            exc.code,
            retry_after=_parse_retry_after(getattr(exc, "headers", None)),
            url=url,
        ) from exc
    except socket.timeout as exc:
        raise RemoteTimeoutError(f"请求超时（{timeout}s）", url=url) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, socket.timeout):
            raise RemoteTimeoutError(f"请求超时（{timeout}s）", url=url) from exc
        raise RemoteError(f"网络错误：{reason}", url=url) from exc
    except OSError as exc:
        raise RemoteError(f"网络错误：{exc}", url=url) from exc
    return raw.decode("utf-8", errors="replace")


def _parse_suggested_username(html: str) -> str:
    """从注册面板 HTML 里取出服务端预填的用户名。

    先定位包含 ``id="j-username"`` 的 ``<input>`` 整个标签，再在标签内找
    ``value`` 属性——这样不依赖属性出现的顺序，也兼容单/双引号。

    Args:
        html: 注册面板页面的 HTML。

    Returns:
        用户名；标签存在但 ``value`` 为空时返回 ``""``。

    Raises:
        RemoteParseError: 响应里找不到 ``j-username`` 输入框（接口结构可能变了）。
    """
    m = _INPUT_TAG_RE.search(html)
    if not m:
        raise RemoteParseError(
            "响应中没有找到用户名输入框（j-username），接口结构可能已变化"
        )
    vm = _VALUE_ATTR_RE.search(m.group(0))
    if vm is None:
        return ""
    value = vm.group(1) if vm.group(1) is not None else vm.group(2)
    return value.strip()


# ---------------------------------------------------------------------------
# POST 提交支持：响应模型、注册表单解析、带 Cookie 的会话
# ---------------------------------------------------------------------------

#: POST 表单的 Content-Type（4399 服务端要求 UTF-8 形式）
#: 表单 POST 的 Content-Type。**必须与浏览器完全一致**（不带 charset）：
#: 实测 2026-11-08，多带 ``; charset=UTF-8`` 时 4399 会返回
#: ``202`` + 「请稍后再试~」（看着像限流，其实是请求头不合浏览器）。
_FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"

#: 解析相对 action 时使用的基准地址
_FORM_BASE_URL = "https://ptlogin.4399.com"

#: ``<form ...>`` 开始标签（属性内部可能跨行）
_FORM_TAG_RE = re.compile(r"<form\b([^>]*)>", re.I | re.S)
#: ``</form>`` 结束标签
_FORM_END_RE = re.compile(r"</form\s*>", re.I)
#: ``<input ...>`` 标签（属性内部可能跨行）
_FORM_INPUT_RE = re.compile(r"<input\b([^>]*)>", re.I | re.S)
#: 单个 HTML 属性：名字 + 可选值（双引号 / 单引号 / 无引号）
_ATTR_RE = re.compile(
    r"""([A-Za-z_:][-A-Za-z0-9_:.]*)
        (?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?""",
    re.X | re.S,
)
#: 验证码输入框的 id
_CAPTCHA_ID_RE = re.compile(r"""\bid\s*=\s*["']inputCaptcha["']""", re.I)


@dataclass(frozen=True)
class HttpResponse:
    """一次 HTTP 请求的结果。

    Attributes:
        status: HTTP 状态码。
        url: 跟随重定向后的最终 URL。
        headers: 响应头（普通 dict）。
        body: 响应体文本（UTF-8 解码，非法字节替换为 ``U+FFFD``）。
        raw: 响应体原始字节（图片等二进制响应只能用这个）。
    """

    status: int
    url: str
    headers: dict[str, str]
    body: str
    raw: bytes = b""

    @property
    def is_binary(self) -> bool:
        """``Content-Type`` 是否明显不是文本（例如图片验证码）。"""
        ctype = self.headers.get("Content-Type", "").lower()
        return not (
            not ctype
            or ctype.startswith("text/")
            or "json" in ctype
            or "javascript" in ctype
            or "xml" in ctype
        )


@dataclass(frozen=True)
class RegFormSnapshot:
    """注册表单结构的只读快照。

    Attributes:
        action: 表单提交地址（绝对 URL）。
        method: 表单方法（小写；缺省时为 ``"get"``）。
        hidden: 全部 ``type=hidden`` 的 ``name -> value``（已做 HTML 反转义）。
        input_names: 非 hidden 输入框的 ``name``（按出现顺序）。
        sec: 隐藏域 ``sec`` 的值（去掉首尾空白）；缺失时为 ``""``。
        suggested_username: ``id="j-username"`` 输入框的预填值；缺失时为 ``""``。
        has_captcha: 是否存在 ``id="inputCaptcha"`` 的元素。
    """

    action: str
    method: str
    hidden: dict[str, str]
    input_names: tuple[str, ...]
    sec: str
    suggested_username: str
    has_captcha: bool


def _parse_attrs(raw: str) -> dict[str, str]:
    """解析标签内部的属性串。

    属性顺序随意，值可用双引号 / 单引号 / 不加引号；属性名统一小写，
    值做 HTML 反转义。同一属性重复出现时以第一次为准（与浏览器一致）。
    """
    attrs: dict[str, str] = {}
    for match in _ATTR_RE.finditer(raw):
        name = match.group(1).lower()
        if match.group(2) is not None:
            value = match.group(2)
        elif match.group(3) is not None:
            value = match.group(3)
        elif match.group(4) is not None:
            value = match.group(4)
        else:
            value = ""
        attrs.setdefault(name, unescape(value))
    return attrs


def parse_registration_form(html: str) -> RegFormSnapshot:
    """从注册表单页 HTML 中解析出提交所需的结构。

    只解析第一个 ``<form>``，并容忍属性顺序、单双引号、跨行与 HTML 实体。
    ``action`` 为相对路径时按 ``https://ptlogin.4399.com`` 转为绝对 URL；
    ``action`` 缺失或为空时回落到 :data:`REGISTER_URL`。

    Args:
        html: ``GET regFrame.do`` 返回的页面 HTML。

    Returns:
        表单结构快照。

    Raises:
        RemoteParseError: HTML 里找不到 ``<form>``（接口结构可能已变化）。
        TypeError: ``html`` 不是 ``str``。
    """
    if not isinstance(html, str):
        raise TypeError("html 必须是 str")
    form_match = _FORM_TAG_RE.search(html)
    if form_match is None:
        raise RemoteParseError(
            "响应中没有找到注册表单（<form>），接口结构可能已变化"
        )

    form_attrs = _parse_attrs(form_match.group(1))
    end_match = _FORM_END_RE.search(html, form_match.end())
    form_body = (
        html[form_match.end() : end_match.start()]
        if end_match is not None
        else html[form_match.end() :]
    )

    hidden: dict[str, str] = {}
    input_names: list[str] = []
    suggested_username = ""
    for tag_match in _FORM_INPUT_RE.finditer(form_body):
        attrs = _parse_attrs(tag_match.group(1))
        name = attrs.get("name", "")
        input_type = attrs.get("type", "text").strip().lower()
        if input_type == "hidden":
            if name:
                hidden[name] = attrs.get("value", "")
            continue
        if name:
            input_names.append(name)
        if attrs.get("id", "") == "j-username":
            suggested_username = attrs.get("value", "").strip()

    action = form_attrs.get("action", "").strip()
    action = (
        urllib.parse.urljoin(_FORM_BASE_URL, action) if action else REGISTER_URL
    )
    method = form_attrs.get("method", "").strip().lower() or "get"

    return RegFormSnapshot(
        action=action,
        method=method,
        hidden=hidden,
        input_names=tuple(input_names),
        sec=hidden.get("sec", "").strip(),
        suggested_username=suggested_username,
        has_captcha=bool(_CAPTCHA_ID_RE.search(form_body)),
    )


def _response_headers(resp) -> dict[str, str]:
    """把响应头（``HTTPMessage`` 等）转成普通 dict。"""
    headers = getattr(resp, "headers", None)
    if headers is None:
        return {}
    try:
        items = headers.items()
    except AttributeError:
        return {}
    result: dict[str, str] = {}
    for key, value in items:
        result[str(key)] = str(value)
    return result


def _response_url(resp, fallback: str) -> str:
    """取跟随重定向后的最终 URL（兼容 ``geturl()`` 与 ``.url`` 两种实现）。"""
    geturl = getattr(resp, "geturl", None)
    if callable(geturl):
        value = geturl()
        if value:
            return str(value)
    value = getattr(resp, "url", None)
    if value:
        return str(value)
    return fallback


class RemoteSession:
    """带 CookieJar 的 HTTP 会话；GET 默认重试，POST 永远单次。

    POST 单次是为了防止提交注册请求被重复发送（服务端可能已成功建立账号，
    重试会造成重复注册），因此无论 5xx / 429 / 超时都直接抛错。

    Attributes:
        timeout: 单次请求超时（秒）。
        policy: GET 使用的重试策略（POST 不使用）。
        referer: 请求头 ``Referer``。
    """

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        policy: RetryPolicy | None = None,
        referer: str = DEFAULT_REFERER,
        user_agent: str | None = None,
        proxy: str | None = None,
    ) -> None:
        self.timeout = timeout
        self.policy = (
            DEFAULT_FETCH_RETRY_POLICY if policy is None else policy
        )
        self.referer = referer
        #: 本次会话使用的 User-Agent（默认内置的桌面 Chrome）
        self.user_agent = user_agent or DEFAULT_USER_AGENT
        #: HTTP(S) 代理，形如 ``http://host:port``；``None`` 表示直连
        self.proxy = proxy
        #: 额外请求头（默认空；提交注册时按浏览器补 Origin / Sec-Fetch-*）。
        self.extra_headers: dict[str, str] = {}
        self._cookiejar = http.cookiejar.CookieJar()
        handlers: list[urllib.request.BaseHandler] = []
        if proxy:
            handlers.append(
                urllib.request.ProxyHandler({"http": proxy, "https": proxy})
            )
        handlers.append(urllib.request.HTTPCookieProcessor(self._cookiejar))
        self._opener = urllib.request.build_opener(*handlers)

    @property
    def cookies(self) -> dict[str, str]:
        """当前会话 Cookie 的只读快照（``name -> value``）。"""
        return {cookie.name: cookie.value for cookie in self._cookiejar}

    def get(self, url: str) -> HttpResponse:
        """HTTP GET（按 :attr:`policy` 重试）。

        Raises:
            RemoteTimeoutError / RemoteHTTPError / RemoteError: 请求失败。
        """
        return self._request_with_retry(url)

    def post(self, url: str, data: Mapping[str, str]) -> HttpResponse:
        """HTTP POST 表单；**只尝试一次**，任何失败直接抛出。

        Args:
            url: 提交地址（通常是 ``<form action>``）。
            data: 表单字段（``str -> str``）。

        Raises:
            TypeError: ``data`` 不是 Mapping。
            RemoteTimeoutError / RemoteHTTPError / RemoteError: 请求失败。
        """
        if not isinstance(data, Mapping):
            raise TypeError("data 必须是 Mapping[str, str]")
        payload = urllib.parse.urlencode(
            [(str(key), str(value)) for key, value in data.items()]
        ).encode("utf-8")
        logger.debug("POST %s (single attempt)", _safe_url(url))
        return self._open_once(
            "POST", url, data=payload, content_type=_FORM_CONTENT_TYPE
        )

    def _base_headers(self, content_type: str | None = None) -> dict[str, str]:
        headers = {
            "User-Agent": self.user_agent,
            "Referer": self.referer,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        if content_type is not None:
            headers["Content-Type"] = content_type
        # 可选：额外请求头（如浏览器同款 Origin / Sec-Fetch-*）。
        # 用实例属性而不是构造参数，方便已有调用方与测试替身保持兼容。
        headers.update(getattr(self, "extra_headers", None) or {})
        return headers

    def _open_once(
        self,
        method: str,
        url: str,
        *,
        data: bytes | None = None,
        content_type: str | None = None,
    ) -> HttpResponse:
        """执行一次请求，并把底层异常统一成 :class:`RemoteError` 子类。"""
        request = urllib.request.Request(
            url,
            data=data,
            headers=self._base_headers(content_type),
            method=method,
        )
        try:
            with self._opener.open(request, timeout=self.timeout) as resp:
                status = getattr(resp, "status", None)
                status = 200 if status is None else int(status)
                if not 200 <= status < 300:
                    raise RemoteHTTPError(
                        f"HTTP {status}",
                        status,
                        retry_after=_parse_retry_after(
                            getattr(resp, "headers", None)
                        ),
                        url=url,
                    )
                raw = resp.read(MAX_BODY_BYTES)
                final_url = _response_url(resp, url)
                resp_headers = _response_headers(resp)
        except urllib.error.HTTPError as exc:
            raise RemoteHTTPError(
                f"HTTP {exc.code}",
                exc.code,
                retry_after=_parse_retry_after(getattr(exc, "headers", None)),
                url=url,
            ) from exc
        except socket.timeout as exc:
            raise RemoteTimeoutError(
                f"请求超时（{self.timeout}s）", url=url
            ) from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, socket.timeout):
                raise RemoteTimeoutError(
                    f"请求超时（{self.timeout}s）", url=url
                ) from exc
            raise RemoteError(f"网络错误：{reason}", url=url) from exc
        except OSError as exc:
            raise RemoteError(f"网络错误：{exc}", url=url) from exc

        return HttpResponse(
            status=status,
            url=final_url,
            headers=resp_headers,
            body=raw.decode("utf-8", errors="replace"),
            raw=raw,
        )

    def _request_with_retry(self, url: str) -> HttpResponse:
        """GET 的重试循环：超时 / 网络 / 5xx / 429 重试，其它 4xx 直接抛出。"""
        policy = self.policy
        start = time.monotonic()
        last_error: RemoteError | None = None
        for attempt in range(1, policy.attempts + 1):
            logger.debug(
                "GET %s (attempt %d/%d)",
                _safe_url(url),
                attempt,
                policy.attempts,
            )
            try:
                return self._open_once("GET", url)
            except RemoteHTTPError as exc:
                if 400 <= exc.status < 500 and exc.status != 429:
                    raise
                last_error = exc
            except RemoteError as exc:
                last_error = exc

            if attempt >= policy.attempts:
                break
            delay = policy.delay_for(
                attempt, getattr(last_error, "retry_after", None)
            )
            if policy.total_deadline is not None:
                remaining = policy.total_deadline - (time.monotonic() - start)
                if remaining <= 0:
                    break
                delay = min(delay, remaining)
            if delay > 0:
                logger.debug(
                    "retry in %.2fs after %s",
                    delay,
                    type(last_error).__name__,
                )
                time.sleep(delay)

        assert last_error is not None
        raise last_error


