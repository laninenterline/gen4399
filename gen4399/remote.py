"""调用 4399 官方接口：获取服务端建议的用户名、查询用户名是否可用。

本模块只需要标准库（``urllib``），不引入第三方依赖。

用到的两个官方接口（均为 4399 统一登录 ptlogin 的公开接口）::

    GET https://ptlogin.4399.com/ptlogin/regFrame.do
        注册面板 iframe。服务端会在这个 HTML 里预填一个「为您分配的账号」，
        形如 <input id="j-username" value="4257237567">。
        注意：该分配有频率限制，短时间内反复请求可能返回空 value。

    GET https://ptlogin.4399.com/ptlogin/isExist.do
        用户名查重。返回 ``0`` 表示可用；
        其它内容为错误原因，如 ``用户名已被注册``、``用户名包含敏感字符``。

示例::

    from gen4399 import fetch_suggested_username, is_username_available

    name = fetch_suggested_username()      # '4257237567'
    is_username_available(name)            # True
"""

from __future__ import annotations

import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .core import (
    DEFAULT_LENGTH,
    DEFAULT_USERNAME_LENGTH,
    Gen4399Error,
    InvalidLengthError,
    _check_fixed_part,
    generate,
    generate_username,
    validate,
    validate_username,
)

__all__ = [
    "REG_FRAME_URL",
    "IS_EXIST_URL",
    "DEFAULT_APP_ID",
    "DEFAULT_TIMEOUT",
    "DEFAULT_USER_AGENT",
    "RemoteError",
    "RemoteTimeoutError",
    "RemoteHTTPError",
    "RemoteParseError",
    "UsernameAvailability",
    "Account",
    "fetch_suggested_username",
    "fetch_suggested_usernames",
    "check_username",
    "is_username_available",
    "generate_available_username",
    "generate_account",
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

_J_USERNAME_RE = re.compile(r'id="j-username"(?P<attrs>.*?)>', re.S)
_VALUE_RE = re.compile(r'value="([^"]*)"')


class RemoteError(Gen4399Error):
    """调用 4399 远程接口失败。"""


class RemoteTimeoutError(RemoteError):
    """请求超时。"""


class RemoteHTTPError(RemoteError):
    """HTTP 状态码非 2xx。"""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


class RemoteParseError(RemoteError):
    """响应内容无法解析出预期数据。"""


@dataclass(frozen=True)
class UsernameAvailability:
    """用户名可用性查询结果。

    Attributes:
        username: 被查询的用户名。
        available: 是否可注册。
        message: 服务端返回的原始说明（可用时为 ``"0"``）。
    """

    username: str
    available: bool
    message: str

    def __bool__(self) -> bool:  # 让 `if result:` 直接表示是否可用
        return self.available


def _http_get(url: str, timeout: float) -> str:
    """最小的 HTTP GET 封装（内部函数，便于测试时打桩）。"""
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
                raise RemoteHTTPError(f"HTTP {status}", status)
            raw = resp.read()
    except urllib.error.HTTPError as exc:  # 4xx / 5xx
        raise RemoteHTTPError(f"HTTP {exc.code}", exc.code) from exc
    except socket.timeout as exc:
        raise RemoteTimeoutError(f"请求超时（{timeout}s）") from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, socket.timeout):
            raise RemoteTimeoutError(f"请求超时（{timeout}s）") from exc
        raise RemoteError(f"网络错误：{reason}") from exc
    except OSError as exc:
        raise RemoteError(f"网络错误：{exc}") from exc
    return raw.decode("utf-8", errors="replace")


def _parse_suggested_username(html: str) -> str:
    """从注册面板 HTML 里取出服务端预填的用户名。"""
    m = _J_USERNAME_RE.search(html)
    if not m:
        raise RemoteParseError(
            "响应中没有找到用户名输入框（j-username），接口结构可能已变化"
        )
    vm = _VALUE_RE.search(m.group("attrs"))
    return vm.group(1).strip() if vm else ""


def _apply_fixed_parts(name: str, prefix: str, suffix: str) -> str:
    """把自定义前后缀套到服务端分配的用户名上，并校验最终结果。"""
    _check_fixed_part(prefix, "prefix")
    _check_fixed_part(suffix, "suffix")
    candidate = prefix + name + suffix
    violations = validate_username(candidate)
    if not violations:
        return candidate
    detail = "；".join(v.message for v in violations)
    if any(v.code == "length" for v in violations):
        raise InvalidLengthError(
            f"服务端分配的用户名 {name!r} 加上前后缀后长度不合法（{detail}）"
        )
    raise RemoteParseError(
        f"服务端分配的用户名 {name!r} 加上前后缀后不符合 4399 规则（{detail}）"
    )


def fetch_suggested_username(
    *,
    app_id: str = DEFAULT_APP_ID,
    level: int = 4,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = 4,
    retry_delay: float = 5.0,
    fallback_to_local: bool = False,
    prefix: str = "",
    suffix: str = "",
    verify_available: bool = False,
) -> str:
    """从 4399 官方注册面板接口获取一个服务端分配的用户名。

    服务端会在注册面板 HTML 的 ``#j-username`` 输入框里预填一个账号
    （一般是 10 位纯数字，例如 ``4257237567``），页面提示语为
    「这是为您分配的账号,也可自己填写」。

    Args:
        app_id: 业务方 appId，默认 ``u4399``。
        level: 注册等级，默认 4。
        timeout: 单次请求超时（秒）。
        retries: 返回空用户名时的重试次数。
        retry_delay: 首次重试间隔（秒），之后按指数递增（5s、10s、20s…）。
            实测该接口在 20 秒左右间隔下成功率明显更高，需要时自行调大。
        fallback_to_local: 拿不到服务端分配的用户名时，是否降级为本地
            :func:`generate_username` 生成（默认 False，即抛异常）。
        prefix: 加在服务端分配的用户名前面的固定前缀（只允许字母数字）。
        suffix: 加在后面的固定后缀（只允许字母数字）。
        verify_available: 拿到用户名后，是否再调用 ``isExist.do`` 确认它
            仍然可注册（默认 False）。被占用时会继续重试。

    Returns:
        服务端分配的用户名字符串（已用 :func:`validate_username` 校验格式）。

    Raises:
        RemoteTimeoutError: 请求超时。
        RemoteHTTPError: HTTP 状态异常。
        RemoteParseError: 响应里没有可用的用户名（常见原因是被频率限制）。
        RemoteError: 其它网络错误。

    Examples:
        >>> fetch_suggested_username()        # doctest: +SKIP
        '4257237567'
    """
    params = {
        "regMode": "reg_normal",
        "postLoginHandler": "refreshParent",
        "appId": app_id,
        "level": str(level),
        "mainDivId": "popup_reg_div",
        "externalLogin": "qq",
    }
    url = f"{REG_FRAME_URL}?{urllib.parse.urlencode(params)}"

    last_error: RemoteError | None = None
    attempts = max(1, retries)
    for attempt in range(attempts):
        html = _http_get(url, timeout)
        try:
            name = _parse_suggested_username(html)
        except RemoteParseError as exc:
            last_error = exc
            name = ""
        if name and not validate_username(name):
            candidate = _apply_fixed_parts(name, prefix, suffix)
            if not verify_available:
                return candidate
            res = check_username(candidate, app_id=app_id, timeout=timeout)
            if res.available:
                return candidate
            last_error = RemoteParseError(
                f"服务端分配的用户名 {candidate!r} 已被占用（{res.message}）"
            )
        elif name:
            last_error = RemoteParseError(
                f"服务端返回的用户名 {name!r} 不符合 4399 规则"
            )
        if attempt < attempts - 1:
            # 指数退避：该接口对短时间高频请求会返回空值
            time.sleep(retry_delay * (2 ** attempt))

    if fallback_to_local:
        if verify_available:
            return generate_available_username(
                prefix=prefix,
                suffix=suffix,
                app_id=app_id,
                timeout=timeout,
            )
        return generate_username(prefix=prefix, suffix=suffix)

    detail = f"（最后一次原因：{last_error}）" if last_error else ""
    raise RemoteParseError(
        "未能从 4399 获取到可用的用户名。"
        "该接口有频率限制，短时间内反复调用可能返回空值；"
        "建议把 retry_delay 调到 20 秒左右，"
        "或使用 fallback_to_local=True / generate_username() 走本地生成。"
        + detail
    ) from last_error


def fetch_suggested_usernames(
    count: int = 1,
    *,
    app_id: str = DEFAULT_APP_ID,
    level: int = 4,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = 4,
    retry_delay: float = 5.0,
    unique: bool = True,
    fallback_to_local: bool = False,
    prefix: str = "",
    suffix: str = "",
    verify_available: bool = False,
) -> list[str]:
    """批量获取服务端分配的用户名。

    Args:
        count: 需要的数量，必须 >= 1。
        unique: 是否去除重复（默认 True）。
        其它参数同 :func:`fetch_suggested_username`。

    Returns:
        用户名列表。

    Raises:
        ValueError: ``count < 1``。
        其它异常同 :func:`fetch_suggested_username`。
    """
    if not isinstance(count, int) or isinstance(count, bool):
        raise TypeError("count 必须是 int")
    if count < 1:
        raise ValueError("count 必须 >= 1")
    out: list[str] = []
    for _ in range(count):
        name = fetch_suggested_username(
            app_id=app_id,
            level=level,
            timeout=timeout,
            retries=retries,
            retry_delay=retry_delay,
            fallback_to_local=fallback_to_local,
            prefix=prefix,
            suffix=suffix,
            verify_available=verify_available,
        )
        if unique and name in out:
            continue
        out.append(name)
    return out


def check_username(
    username: str,
    *,
    app_id: str = DEFAULT_APP_ID,
    timeout: float = DEFAULT_TIMEOUT,
) -> UsernameAvailability:
    """查询用户名是否还能注册（调用官方 ``isExist.do``）。

    Args:
        username: 待查询的用户名。
        app_id: 业务方 appId，默认 ``u4399``。
        timeout: 请求超时（秒）。

    Returns:
        :class:`UsernameAvailability`，``.available`` 为 True 表示可注册。

    Raises:
        TypeError: ``username`` 不是 ``str``。
        RemoteError 子类: 网络或解析失败。

    Examples:
        >>> check_username("abc12345").available   # doctest: +SKIP
        True
    """
    if not isinstance(username, str):
        raise TypeError(f"username 必须是 str，收到 {type(username).__name__}")
    query = urllib.parse.urlencode(
        {"username": username, "appId": app_id, "regMode": "reg_normal"}
    )
    body = _http_get(f"{IS_EXIST_URL}?{query}", timeout).strip()
    return UsernameAvailability(
        username=username,
        available=(body == "0"),
        message=body,
    )


def is_username_available(
    username: str,
    *,
    app_id: str = DEFAULT_APP_ID,
    timeout: float = DEFAULT_TIMEOUT,
) -> bool:
    """判断用户名是否可注册（:func:`check_username` 的布尔便捷版）。"""
    return check_username(username, app_id=app_id, timeout=timeout).available


def generate_available_username(
    *,
    length: int = DEFAULT_USERNAME_LENGTH,
    prefix: str = "",
    suffix: str = "",
    max_attempts: int = 20,
    app_id: str = DEFAULT_APP_ID,
    timeout: float = DEFAULT_TIMEOUT,
    retry_delay: float = 0.0,
) -> str:
    """本地生成用户名，并用官方 ``isExist.do`` 自动确认它真的能注册。

    本地随机名的冲突概率极低，通常第一次探测就通过。

    Args:
        length: 用户名总长度 6~20，默认 12。
        prefix: 固定前缀（只允许字母数字），计入总长度。
        suffix: 固定后缀（只允许字母数字），计入总长度。
        max_attempts: 最多生成并探测多少次。
        app_id: 业务方 appId，默认 ``u4399``。
        timeout: 单次查询超时（秒）。
        retry_delay: 名字被占用时，换下一个之前的等待（秒）。

    Returns:
        一个经服务端确认「可注册」的用户名。

    Raises:
        ValueError: ``max_attempts < 1``。
        RemoteError: 查询失败，或 ``max_attempts`` 次都撞名/查询失败。

    Examples:
        >>> name = generate_available_username()   # doctest: +SKIP
        >>> is_username_available(name)            # doctest: +SKIP
        True
    """
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool):
        raise TypeError("max_attempts 必须是 int")
    if max_attempts < 1:
        raise ValueError("max_attempts 必须 >= 1")

    last = ""
    for attempt in range(max_attempts):
        name = generate_username(length=length, prefix=prefix, suffix=suffix)
        res = check_username(name, app_id=app_id, timeout=timeout)
        if res.available:
            return name
        last = res.message
        if retry_delay and attempt < max_attempts - 1:
            time.sleep(retry_delay)

    raise RemoteError(
        f"连续 {max_attempts} 个用户名都不可用（最后一次原因：{last!r}），"
        "建议换更长的长度或加前后缀提高区分度"
    )


@dataclass(frozen=True)
class Account:
    """一套可直接拿去注册的 4399 账号信息。

    Attributes:
        username: 账号名。
        password: 密码。
        username_available: 生成时是否经服务端确认可用；``None`` 表示未校验。
    """

    username: str
    password: str
    username_available: bool | None = None


def generate_account(
    *,
    verify_username: bool = True,
    username: str | None = None,
    username_length: int = DEFAULT_USERNAME_LENGTH,
    password_length: int = DEFAULT_LENGTH,
    prefix: str = "",
    suffix: str = "",
    max_attempts: int = 20,
    app_id: str = DEFAULT_APP_ID,
    timeout: float = DEFAULT_TIMEOUT,
) -> Account:
    """生成一套合规的账号名 + 密码，并（默认）校验账号名可用性。

    密码无法在服务端「预校验」——4399 没有密码查重/校验接口，
    只有注册提交时才会校验。因此密码侧只能保证**通过 4399 的公开规则**，
    这一点由 :func:`gen4399.validate` 在本地保证。

    Args:
        verify_username: 是否调用官方接口确认账号名可注册（默认 True）。
        username: 指定账号名；为 ``None`` 时自动生成。
        username_length: 自动生成账号名时的总长度，默认 12。
        password_length: 密码总长度，默认 16。
        prefix / suffix: 账号名的固定前后缀。
        max_attempts: 账号名被占用时最多重试几次。
        app_id: 业务方 appId。
        timeout: 查询账号名可用性的超时（秒）。

    Returns:
        :class:`Account`。

    Raises:
        RemoteError: ``verify_username=True`` 时查询失败，或名字一直不可用。
        InvalidLengthError / InvalidPrefixError / InvalidSuffixError:
            参数不合法。

    Examples:
        >>> acc = generate_account()            # doctest: +SKIP
        >>> validate(acc.password)              # doctest: +SKIP
        []
    """
    # 密码侧：本地规则保证（服务端不提供预校验）
    pwd = generate(length=password_length)

    if username is not None:
        if verify_username:
            res = check_username(username, app_id=app_id, timeout=timeout)
            if not res.available:
                raise RemoteError(
                    f"指定的用户名 {username!r} 不可用：{res.message}"
                )
        available: bool | None = True if verify_username else None
        return Account(username=username, password=pwd, username_available=available)

    if verify_username:
        name = generate_available_username(
            length=username_length,
            prefix=prefix,
            suffix=suffix,
            max_attempts=max_attempts,
            app_id=app_id,
            timeout=timeout,
        )
        return Account(username=name, password=pwd, username_available=True)

    name = generate_username(length=username_length, prefix=prefix, suffix=suffix)
    return Account(username=name, password=pwd, username_available=None)
