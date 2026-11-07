"""远程传输层：HTTP GET、错误类型、重试策略、响应解析。

本模块不包含业务语义（取号/查重），由 :mod:`gen4399.remote._api` 组合使用。
"""

from __future__ import annotations

import logging
import random
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from ..core import Gen4399Error

#: 模块日志器（只输出非 PII 的调试信息）
logger = logging.getLogger("gen4399.remote")

__all__ = [
    "REG_FRAME_URL",
    "IS_EXIST_URL",
    "DEFAULT_APP_ID",
    "DEFAULT_TIMEOUT",
    "DEFAULT_USER_AGENT",
    "MAX_BODY_BYTES",
    "RetryPolicy",
    "DEFAULT_RETRY_POLICY",
    "DEFAULT_FETCH_RETRY_POLICY",
    "DEFAULT_CHECK_RETRY_POLICY",
    "RemoteError",
    "RemoteTimeoutError",
    "RemoteHTTPError",
    "RemoteParseError",
    "_http_get",
    "_http_get_once",
    "_parse_suggested_username",
    "_parse_retry_after",
]


#: 注册面板接口
REG_FRAME_URL = "https://ptlogin.4399.com/ptlogin/regFrame.do"

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
            "Referer": "https://u.4399.com/register.html",
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


