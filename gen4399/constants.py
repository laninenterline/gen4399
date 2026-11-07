"""常量集中出口：规则、长度、端点、unified 字段策略。

这些名字在 ``gen4399`` 顶层同样可用（保持兼容）；单独成模块是为了让「常量」
和「函数/类」在使用时能分开——写业务代码时一般只需要顶层那十来个名字。

举例::

    from gen4399.constants import UNIFIED_DROP_FIELDS, WEB_REG_API
"""

from __future__ import annotations

from ._rules import RULES_CHECKED_AT, RULES_SOURCES, RULES_VERSION
from .core import (
    CHARSET,
    DEFAULT_LENGTH,
    DEFAULT_USERNAME_LENGTH,
    MAX_LENGTH,
    MIN_LENGTH,
    USERNAME_CHARSET,
    USERNAME_MAX_LENGTH,
    USERNAME_MIN_LENGTH,
)
from .remote import (
    DEFAULT_APP_ID,
    DEFAULT_TIMEOUT,
    DEFAULT_USER_AGENT,
    IS_EXIST_URL,
    REG_FRAME_URL,
)
from .submit import (
    ENCRYPTED_FIELDS,
    UNIFIED_CAPTCHA_API,
    UNIFIED_DROP_FIELDS,
    UNIFIED_SEND_REALNAME,
    VERIFY_URL,
    WEB_CAPTCHA_API,
    WEB_CHECK_USER_API,
    WEB_REG_API,
    WEB_VERIFY_CODE_API,
)

__all__ = [
    # 规则快照
    "RULES_VERSION",
    "RULES_CHECKED_AT",
    "RULES_SOURCES",
    # 密码 / 账号名
    "CHARSET",
    "MIN_LENGTH",
    "MAX_LENGTH",
    "DEFAULT_LENGTH",
    "USERNAME_CHARSET",
    "USERNAME_MIN_LENGTH",
    "USERNAME_MAX_LENGTH",
    "DEFAULT_USERNAME_LENGTH",
    # 端点与会话
    "REG_FRAME_URL",
    "IS_EXIST_URL",
    "DEFAULT_APP_ID",
    "DEFAULT_USER_AGENT",
    "DEFAULT_TIMEOUT",
    "WEB_REG_API",
    "WEB_CHECK_USER_API",
    "WEB_CAPTCHA_API",
    "WEB_VERIFY_CODE_API",
    "UNIFIED_CAPTCHA_API",
    "VERIFY_URL",
    # unified 字段策略
    "UNIFIED_DROP_FIELDS",
    "UNIFIED_SEND_REALNAME",
    "ENCRYPTED_FIELDS",
]
