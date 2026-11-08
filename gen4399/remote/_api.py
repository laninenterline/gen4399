"""远程业务层：取服务端分配账号、查重、生成 Account。

所有网络调用都经过 :mod:`gen4399.remote._http`。
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
import urllib.parse
from dataclasses import dataclass
from typing import Literal

from ..core import (
    DEFAULT_LENGTH,
    DEFAULT_USERNAME_LENGTH,
    InvalidLengthError,
    generate,
    generate_username,
    validate_fixed_part,
    validate_username,
)
from . import _http
from ._http import (
    DEFAULT_APP_ID,
    DEFAULT_CHECK_RETRY_POLICY,
    DEFAULT_FETCH_RETRY_POLICY,
    DEFAULT_TIMEOUT,
    IS_EXIST_URL,
    REG_FRAME_URL,
    RemoteError,
    RemoteParseError,
    RemoteTimeoutError,
    RetryPolicy,
    _parse_suggested_username,
)

#: ``UsernameAvailability.kind`` 的合法取值
AvailabilityKind = Literal["available", "taken", "invalid", "unknown"]

logger = logging.getLogger("gen4399.remote")


@dataclass(frozen=True)
class UsernameAvailability:
    """用户名可用性查询结果。

    Attributes:
        username: 被查询的用户名。
        available: 是否可注册。
        message: 服务端返回的原始说明（可用时为 ``"0"``）。
        kind: 结构化分类，取值 ``available`` / ``taken`` / ``invalid`` /
            ``unknown``。不传时按 ``message`` 自动推断。
    """

    username: str
    available: bool
    message: str
    kind: AvailabilityKind | None = None

    def __post_init__(self) -> None:
        if self.kind is None:
            object.__setattr__(self, "kind", _classify_availability(self.message))

    def __bool__(self) -> bool:  # 让 `if result:` 直接表示是否可用
        return self.available

    def to_dict(self) -> dict[str, object]:
        """转成可 JSON 序列化的字典。"""
        return {
            "username": self.username,
            "available": self.available,
            "kind": self.kind,
            "message": self.message,
        }


#: 服务端"用户名可用"的响应体
_AVAILABLE_BODY = "0"

#: 服务端表示"名字本身不合法"的提示关键词
_INVALID_HINTS = ("敏感", "至少", "字符", "长度", "格式", "不能", "非法", "限制")


def _classify_availability(body: str) -> AvailabilityKind:
    """把 isExist.do 的响应体分类（内部函数）。

    Returns:
        ``available`` / ``taken`` / ``invalid`` / ``unknown``。
    """
    if body == _AVAILABLE_BODY:
        return "available"
    if not body or "<" in body:
        # 空响应或 HTML 错误页：无法判断，不应当成"已被注册"
        return "unknown"
    if any(hint in body for hint in _INVALID_HINTS):
        return "invalid"
    return "taken"


def _apply_fixed_parts(name: str, prefix: str, suffix: str) -> str:
    """把自定义前后缀套到服务端分配的用户名上，并校验最终结果。"""
    validate_fixed_part(prefix, "prefix")
    validate_fixed_part(suffix, "suffix")
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
    retry_policy: RetryPolicy | None = None,
    max_total_seconds: float | None = None,
) -> str:
    """从 4399 官方注册面板接口获取一个服务端分配的用户名。

    服务端会在注册面板 HTML 的 ``#j-username`` 输入框里预填一个账号
    （一般是 10 位纯数字，例如 ``4257237567``），页面提示语为
    「这是为您分配的账号,也可自己填写」。

    Args:
        app_id: 业务方 appId，默认 ``u4399``。
        level: 注册等级，默认 4。
        timeout: 单次请求超时（秒）。
        retries: 总尝试次数（含首次）。
        retry_delay: 首次重试间隔（秒），之后指数递增（5s、10s、20s…，
            单次封顶 60s），并自动加 ±25% 抖动。实测该接口在 20 秒左右
            间隔下成功率明显更高，需要时自行调大。
        fallback_to_local: 拿不到服务端分配的用户名时，是否降级为本地
            :func:`generate_username` 生成（默认 False，即抛异常）。
        prefix: 加在服务端分配的用户名前面的固定前缀（只允许字母数字）。
        suffix: 加在后面的固定后缀（只允许字母数字）。
        verify_available: 拿到用户名后，是否再调用 ``isExist.do`` 确认它
            仍然可注册（默认 False）。被占用时会继续重试。
        retry_policy: 单次 HTTP 请求的重试策略，默认
            :data:`DEFAULT_FETCH_RETRY_POLICY`。
        max_total_seconds: 整个调用的总时间预算（秒），默认不限制。

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
    if not isinstance(retries, int) or isinstance(retries, bool):
        raise TypeError("retries 必须是 int")
    if retries < 1:
        raise ValueError("retries 必须 >= 1")
    if max_total_seconds is not None and max_total_seconds <= 0:
        raise ValueError("max_total_seconds 必须 > 0 或为 None")

    # 先校验本地参数：前缀/后缀非法时立即报错，不要白跑一次网络请求
    validate_fixed_part(prefix, "prefix")
    validate_fixed_part(suffix, "suffix")

    params = {
        "regMode": "reg_normal",
        "postLoginHandler": "refreshParent",
        "appId": app_id,
        "level": str(level),
        "mainDivId": "popup_reg_div",
        "externalLogin": "qq",
    }
    url = f"{REG_FRAME_URL}?{urllib.parse.urlencode(params)}"

    policy = retry_policy or DEFAULT_FETCH_RETRY_POLICY
    started = time.monotonic()
    last_error: RemoteError | None = None
    attempts = retries
    for attempt in range(1, attempts + 1):
        logger.debug("fetch_suggested_username attempt %d/%d", attempt, attempts)
        html = _http._http_get(url, timeout, policy=policy)
        try:
            name = _parse_suggested_username(html)
        except RemoteParseError as exc:
            last_error = exc
            name = ""
        if name and not validate_username(name):
            candidate = _apply_fixed_parts(name, prefix, suffix)
            if not verify_available:
                return candidate
            res = check_username(
                candidate,
                app_id=app_id,
                timeout=timeout,
                retry_policy=policy,
            )
            if res.available:
                return candidate
            last_error = RemoteParseError(
                f"服务端分配的用户名 {candidate!r} 已被占用（{res.message}）"
            )
        elif name:
            last_error = RemoteParseError(
                f"服务端返回的用户名 {name!r} 不符合 4399 规则"
            )
        if attempt < attempts:
            # 指数退避（封顶 + 抖动）：该接口对短时间高频请求会返回空值
            delay = min(retry_delay * (2 ** (attempt - 1)), 60.0)
            delay *= 1 + random.uniform(0, 0.25)
            if max_total_seconds is not None:
                remaining = max_total_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    break
                delay = min(delay, remaining)
            if delay > 0:
                time.sleep(delay)

    if max_total_seconds is not None and (
        time.monotonic() - started
    ) >= max_total_seconds:
        raise RemoteTimeoutError(
            f"获取分配账号超过总时间预算 {max_total_seconds}s",
            url=url,
        )

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
    with_availability: bool = False,
    retry_policy: RetryPolicy | None = None,
    max_total_seconds: float | None = None,
) -> "list[str] | list[UsernameAvailability]":
    """批量获取服务端分配的用户名。

    Args:
        count: 需要的数量，必须 >= 1。
        unique: 是否保证互不相同（默认 True）。为 True 时最多尝试
            ``count * 3`` 次（该接口有频率限制，重复很常见）。
        with_availability: 为 True 时返回
            ``list[UsernameAvailability]``（会对每个名字再查一次
            ``isExist.do``，多消耗一次请求/名字）。
        其它参数同 :func:`fetch_suggested_username`。

    Returns:
        恰好 ``count`` 个用户名；``with_availability=True`` 时是
        :class:`UsernameAvailability` 列表。

    Raises:
        ValueError: ``count < 1``。
        RemoteError: 尝试次数用尽仍凑不满 ``count`` 个不重复用户名。
        其它异常同 :func:`fetch_suggested_username`。
    """
    if not isinstance(count, int) or isinstance(count, bool):
        raise TypeError("count 必须是 int")
    if count < 1:
        raise ValueError("count 必须 >= 1")

    out: list[str] = []
    seen: set[str] = set()
    max_attempts = count * 3 if unique else count
    for _ in range(max_attempts):
        name = fetch_suggested_username(
            app_id=app_id,
            level=level,
            timeout=timeout,
            retries=retries,
            retry_delay=retry_delay,
            fallback_to_local=fallback_to_local,
            prefix=prefix,
            suffix=suffix,
            verify_available=verify_available and not with_availability,
            retry_policy=retry_policy,
            max_total_seconds=max_total_seconds,
        )
        if unique:
            if name in seen:
                continue
            seen.add(name)
        out.append(name)
        if len(out) == count:
            if with_availability:
                return [
                    check_username(
                        item,
                        app_id=app_id,
                        timeout=timeout,
                        retry_policy=retry_policy,
                    )
                    for item in out
                ]
            return out

    raise RemoteError(
        f"只拿到 {len(out)}/{count} 个不重复用户名（该接口有频率限制）。"
        "可稍后重试、关闭 unique，或改用 generate_usernames() 本地生成。"
    )


def check_username(
    username: str,
    *,
    app_id: str = DEFAULT_APP_ID,
    timeout: float = DEFAULT_TIMEOUT,
    validate_input: bool = False,
    retry_policy: RetryPolicy | None = None,
    transport=None,
) -> UsernameAvailability:
    """查询用户名是否还能注册（调用官方 ``isExist.do``）。

    Args:
        username: 待查询的用户名。
        app_id: 业务方 appId，默认 ``u4399``。
        timeout: 请求超时（秒）。
        validate_input: 为 True 时先用本地规则快速校验，明显非法
            （长度/字符集）直接返回 ``kind="invalid"``，不发网络请求。
        retry_policy: 单次 HTTP 请求的重试策略。

    Returns:
        :class:`UsernameAvailability`，``.available`` 为 True 表示可注册，
        ``.kind`` 为 ``available`` / ``taken`` / ``invalid`` 之一。

    Raises:
        TypeError: ``username`` 不是 ``str``。
        RemoteParseError: 响应为空或像 HTML 错误页，无法判断可用性
            （以前会静默当成"已被注册"，1.9.0 起改为显式报错）。
        RemoteError 子类: 网络失败。

    Examples:
        >>> check_username("abc12345").available   # doctest: +SKIP
        True
        >>> check_username("abc12345").kind        # doctest: +SKIP
        'available'
    """
    if not isinstance(username, str):
        raise TypeError(f"username 必须是 str，收到 {type(username).__name__}")
    if validate_input:
        violations = validate_username(username)
        if violations:
            detail = "；".join(v.message for v in violations)
            return UsernameAvailability(
                username=username,
                available=False,
                message=f"本地校验失败：{detail}",
                kind="invalid",
            )
    query = urllib.parse.urlencode(
        {"username": username, "appId": app_id, "regMode": "reg_normal"}
    )
    body = _http._http_get(
        f"{IS_EXIST_URL}?{query}",
        timeout,
        policy=retry_policy or DEFAULT_CHECK_RETRY_POLICY,
        transport=transport,
    ).strip()
    kind = _classify_availability(body)
    if kind == "unknown":
        raise RemoteParseError(
            f"isExist.do 返回了无法识别的响应（{body[:80]!r}），"
            "可能是风控页或接口异常，请稍后重试"
        )
    return UsernameAvailability(
        username=username,
        available=(kind == "available"),
        message=body,
        kind=kind,
    )


def is_username_available(
    username: str,
    *,
    app_id: str = DEFAULT_APP_ID,
    timeout: float = DEFAULT_TIMEOUT,
    validate_input: bool = False,
    retry_policy: RetryPolicy | None = None,
    transport=None,
) -> bool:
    """判断用户名是否可注册（:func:`check_username` 的布尔便捷版）。

    ``kind="invalid"``（名字本身不合法）也返回 False。
    响应无法识别时抛 :class:`RemoteParseError`，不会静默返回 False。
    """
    return check_username(
        username,
        app_id=app_id,
        timeout=timeout,
        validate_input=validate_input,
        retry_policy=retry_policy,
        transport=transport,
    ).available


def generate_available_username(
    *,
    length: int = DEFAULT_USERNAME_LENGTH,
    prefix: str = "",
    suffix: str = "",
    max_attempts: int = 20,
    app_id: str = DEFAULT_APP_ID,
    timeout: float = DEFAULT_TIMEOUT,
    retry_delay: float = 0.0,
    retry_policy: RetryPolicy | None = None,
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
        res = check_username(
            name, app_id=app_id, timeout=timeout, retry_policy=retry_policy
        )
        if res.available:
            return name
        last = res.message
        if retry_delay and attempt < max_attempts - 1:
            time.sleep(retry_delay)

    raise RemoteError(
        f"连续 {max_attempts} 个用户名都不可用（最后一次原因：{last!r}），"
        "建议换更长的长度或加前后缀提高区分度"
    )


@dataclass(frozen=True, repr=False)
class Account:
    """一套可直接拿去注册的 4399 账号信息。

    Attributes:
        username: 账号名。
        password: 密码。
        username_available: 生成时是否经服务端确认可用；``None`` 表示未校验。

    Note:
        ``repr()`` 会把密码打码，避免被日志/异常带出去；
        需要明文请直接访问 ``.password``。
    """

    username: str
    password: str
    username_available: bool | None = None

    def __repr__(self) -> str:
        return (
            f"Account(username={self.username!r}, password='***', "
            f"username_available={self.username_available!r})"
        )

    def masked(self) -> "Account":
        """返回密码打码后的副本，可安全打印。"""
        return Account(
            username=self.username,
            password="*" * len(self.password),
            username_available=self.username_available,
        )

    def to_dict(self) -> dict[str, object]:
        """转成可 JSON 序列化的字典（含明文密码）。"""
        return {
            "username": self.username,
            "password": self.password,
            "username_available": self.username_available,
        }

    def save(self, path: "str | os.PathLike[str]", *, mode: int = 0o600) -> None:
        """把账号信息写成 JSON 文件（默认权限 0600，含明文密码）。"""
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, indent=2)
        try:
            os.chmod(path, mode)
        except OSError:  # pragma: no cover - 非 POSIX 平台
            pass


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
    retry_policy: RetryPolicy | None = None,
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
        ValueError: 显式传入的 ``username`` 不符合 4399 规则
            （即使 ``verify_username=False`` 也会本地校验）。
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
        violations = validate_username(username)
        if violations:
            detail = "；".join(v.message for v in violations)
            raise ValueError(f"指定的用户名 {username!r} 不符合 4399 规则：{detail}")
        if verify_username:
            res = check_username(
                username,
                app_id=app_id,
                timeout=timeout,
                retry_policy=retry_policy,
            )
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
            retry_policy=retry_policy,
        )
        return Account(username=name, password=pwd, username_available=True)

    name = generate_username(length=username_length, prefix=prefix, suffix=suffix)
    return Account(username=name, password=pwd, username_available=None)
