"""调用 4399 官方接口（兼容 1.x 的 ``gen4399.remote`` 导入路径）。

传输细节在 :mod:`gen4399.remote._http`，业务组合在 :mod:`gen4399.remote._api`。
"""

from __future__ import annotations

from . import _api, _http
from ._api import (
    Account,
    AvailabilityKind,
    UsernameAvailability,
    check_username,
    fetch_suggested_username,
    fetch_suggested_usernames,
    generate_account,
    generate_available_username,
    is_username_available,
)
from ._http import (
    DEFAULT_APP_ID,
    DEFAULT_CHECK_RETRY_POLICY,
    DEFAULT_FETCH_RETRY_POLICY,
    DEFAULT_RETRY_POLICY,
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    IS_EXIST_URL,
    MAX_BODY_BYTES,
    REG_FRAME_URL,
    RemoteError,
    RemoteHTTPError,
    RemoteParseError,
    RemoteTimeoutError,
    RetryPolicy,
    _http_get,
    _http_get_once,
    _parse_retry_after,
    _parse_suggested_username,
)

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
    "UsernameAvailability",
    "AvailabilityKind",
    "Account",
    "fetch_suggested_username",
    "fetch_suggested_usernames",
    "check_username",
    "is_username_available",
    "generate_available_username",
    "generate_account",
]
