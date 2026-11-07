"""gen4399 核心实现：4399 注册账号名 / 密码的生成与校验。

规则来源（均已实测核对）：
  * 4399 前端 `validation.js` 中的 `CheakPWD()` / `CheakUsername()`
  * https://web.4399.com/user/reg.php 注册页的表单提示
  * 服务端报错文案 `用户名只能为6~20位的字母数字组合`

密码规则
--------
- 长度 6~20 个字符（注册；登录允许更短，本库只管注册）
- 只允许 ASCII 字母和数字
- 不允许纯数字 / 纯小写字母 / 纯大写字母
- 区分大小写

用户名规则
----------
- 长度 6~20 个字符
- 只允许 ASCII 字母和数字
- 允许纯数字（4399 自动分配的账号就是 10 位纯数字）
- 不允许下划线、@、中文等（服务端会拒绝）
"""

from __future__ import annotations

import math
import re
import secrets
import string
from collections.abc import Callable
from dataclasses import dataclass

__all__ = [
    "CHARSET",
    "MIN_LENGTH",
    "MAX_LENGTH",
    "DEFAULT_LENGTH",
    "USERNAME_CHARSET",
    "USERNAME_MIN_LENGTH",
    "USERNAME_MAX_LENGTH",
    "DEFAULT_USERNAME_LENGTH",
    "Violation",
    "Gen4399Error",
    "InvalidLengthError",
    "InvalidFixedPartError",
    "InvalidPrefixError",
    "InvalidSuffixError",
    "GenerationError",
    "check_fixed_part",
    "validate",
    "is_valid",
    "generate",
    "generate_many",
    "validate_username",
    "is_valid_username",
    "generate_username",
    "generate_usernames",
    "entropy_bits",
]

#: 生成密码所用的字符集（大小写字母 + 数字，共 62 个）
CHARSET: str = string.ascii_letters + string.digits

#: 4399 注册密码允许的最小长度
MIN_LENGTH: int = 6

#: 4399 注册密码允许的最大长度
MAX_LENGTH: int = 20

#: 默认生成密码长度
DEFAULT_LENGTH: int = 16

#: 生成用户名所用的字符集（小写字母 + 数字，共 36 个）
#: 用小写是为了易读、避免登录时大小写记错；用户名不是秘密，熵够用即可。
USERNAME_CHARSET: str = string.ascii_lowercase + string.digits

#: 4399 用户名允许的最小长度
USERNAME_MIN_LENGTH: int = 6

#: 4399 用户名允许的最大长度
USERNAME_MAX_LENGTH: int = 20

#: 默认生成用户名长度
DEFAULT_USERNAME_LENGTH: int = 12

_ALNUM_RE = re.compile(r"[A-Za-z0-9]+")
_DIGITS_RE = re.compile(r"[0-9]+")
_LOWER_RE = re.compile(r"[a-z]+")
_UPPER_RE = re.compile(r"[A-Z]+")


class Gen4399Error(Exception):
    """本库所有异常的基类。"""


class InvalidLengthError(Gen4399Error, ValueError):
    """长度参数不合法（不在 6~20 之间，或随机部分不足 1 位）。"""


class InvalidFixedPartError(Gen4399Error, ValueError):
    """固定部分（前缀/后缀）不合法（含非字母数字字符）。"""


class InvalidPrefixError(InvalidFixedPartError):
    """前缀不合法（含非字母数字字符）。"""


class InvalidSuffixError(InvalidFixedPartError):
    """后缀不合法（含非字母数字字符）。"""


class GenerationError(Gen4399Error):
    """在给定尝试次数内没能生成合法结果。

    常见于固定部分过长导致随机部分只剩 1 位、且 ``max_attempts`` 设得很小，
    或批量去重时可用空间不足。
    """


@dataclass(frozen=True)
class Violation:
    """一条密码规则违规记录。

    Attributes:
        code: 机器可读的违规代码，见下方列表。
        message: 中文说明，可直接展示给用户。

    可能的 code：
        ``length``     长度不在 6~20
        ``charset``    含非字母数字字符
        ``all_digits`` 纯数字
        ``all_lower``  纯小写字母
        ``all_upper``  纯大写字母
    """

    code: str
    message: str

    def __str__(self) -> str:  # pragma: no cover - 简单代理
        return self.message


def _require_str(value: object, name: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} 必须是 str，收到 {type(value).__name__}")


def _check_length_int(length: object) -> None:
    if not isinstance(length, int) or isinstance(length, bool):
        raise TypeError(f"length 必须是 int，收到 {type(length).__name__}")


def check_fixed_part(value: object, name: str) -> None:
    """校验 prefix / suffix 只含 ASCII 字母数字。

    Args:
        value: 待校验的固定部分。
        name: ``"prefix"`` 或 ``"suffix"``，用于错误信息。

    Raises:
        InvalidPrefixError: prefix 不合法。
        InvalidSuffixError: suffix 不合法。
        TypeError: 传入的不是 ``str``。
    """
    _require_str(value, name)
    if value and not _ALNUM_RE.fullmatch(value):
        if name == "prefix":
            raise InvalidPrefixError(
                "前缀只能包含 ASCII 字母和数字（4399 不允许其它字符）"
            )
        raise InvalidSuffixError(
            "后缀只能包含 ASCII 字母和数字（4399 不允许其它字符）"
        )


#: 兼容旧名字（1.8.x 内部使用）；新代码请用 :func:`check_fixed_part`。
_check_fixed_part = check_fixed_part


def validate(password: str) -> list[Violation]:
    """校验密码是否符合 4399 注册规则。

    Args:
        password: 待校验的密码明文。

    Returns:
        违规列表；空列表表示完全合规。

    Raises:
        TypeError: 传入的不是 ``str``。

    Examples:
        >>> validate("abc")
        [Violation(code='length', message='长度必须...')]
        >>> validate("Abc12345")
        []
    """
    _require_str(password, "password")
    result: list[Violation] = []
    n = len(password)

    if not MIN_LENGTH <= n <= MAX_LENGTH:
        result.append(
            Violation(
                "length",
                f"长度必须为 {MIN_LENGTH}~{MAX_LENGTH} 个字符，当前 {n}",
            )
        )
    if not _ALNUM_RE.fullmatch(password):
        result.append(Violation("charset", "只允许使用字母和数字"))
    if _DIGITS_RE.fullmatch(password):
        result.append(Violation("all_digits", "不能使用纯数字"))
    if _LOWER_RE.fullmatch(password):
        result.append(Violation("all_lower", "不能使用纯小写字母"))
    if _UPPER_RE.fullmatch(password):
        result.append(Violation("all_upper", "不能使用纯大写字母"))
    return result


def is_valid(password: str) -> bool:
    """判断密码是否合规。等同于 ``not validate(password)``。"""
    return not validate(password)


def validate_username(username: str) -> list[Violation]:
    """校验用户名（账号名）是否符合 4399 注册规则。

    规则与密码不同：用户名只校验「长度 6~20」和「字母数字」，
    **允许纯数字**（4399 自动分配的账号就是 10 位纯数字）。

    Args:
        username: 待校验的账号名。

    Returns:
        违规列表；空列表表示可用。

    Raises:
        TypeError: 传入的不是 ``str``。

    Examples:
        >>> validate_username("abc12345")
        []
        >>> [v.code for v in validate_username("ab")]
        ['length']
        >>> [v.code for v in validate_username("abc_12345")]
        ['charset']
    """
    _require_str(username, "username")
    result: list[Violation] = []
    n = len(username)

    if not USERNAME_MIN_LENGTH <= n <= USERNAME_MAX_LENGTH:
        result.append(
            Violation(
                "length",
                f"用户名长度必须为 {USERNAME_MIN_LENGTH}~{USERNAME_MAX_LENGTH} "
                f"个字符，当前 {n}",
            )
        )
    if not _ALNUM_RE.fullmatch(username):
        result.append(
            Violation("charset", "用户名只允许使用字母和数字")
        )
    return result


def is_valid_username(username: str) -> bool:
    """判断用户名是否合规。等同于 ``not validate_username(username)``。"""
    return not validate_username(username)


def entropy_bits(
    length: int = DEFAULT_LENGTH,
    prefix_length: int = 0,
    suffix_length: int = 0,
    charset_size: int | None = None,
) -> float:
    """估算随机部分的熵（以 bit 为单位）。

    Args:
        length: 密码总长度。
        prefix_length: 固定前缀长度（前缀不贡献熵）。
        suffix_length: 固定后缀长度（后缀不贡献熵）。
        charset_size: 字符集大小，默认 ``len(CHARSET)``；生成用户名时传
            ``len(USERNAME_CHARSET)``。

    Returns:
        ``(length - prefix_length - suffix_length) * log2(charset_size)``

    Raises:
        InvalidLengthError: 固定部分长度超过了总长度。
    """
    _check_length_int(length)
    for name, val in (("prefix_length", prefix_length), ("suffix_length", suffix_length)):
        if not isinstance(val, int) or isinstance(val, bool):
            raise TypeError(f"{name} 必须是 int")
        if val < 0:
            raise ValueError(f"{name} 不能为负")
    if charset_size is None:
        charset_size = len(CHARSET)
    if not isinstance(charset_size, int) or isinstance(charset_size, bool):
        raise TypeError("charset_size 必须是 int")
    if charset_size < 2:
        raise ValueError("charset_size 至少为 2")
    random_len = length - prefix_length - suffix_length
    if random_len < 0:
        raise InvalidLengthError("固定部分（前缀+后缀）长度超过了总长度")
    return random_len * math.log2(charset_size)


def _validate_params(
    length: int,
    prefix: str,
    suffix: str,
    max_attempts: int,
    *,
    min_len: int = MIN_LENGTH,
    max_len: int = MAX_LENGTH,
    label: str = "长度",
) -> int:
    """内部参数校验，返回随机部分的长度。"""
    _check_length_int(length)
    check_fixed_part(prefix, "prefix")
    check_fixed_part(suffix, "suffix")
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool):
        raise TypeError("max_attempts 必须是 int")
    if max_attempts < 1:
        raise ValueError("max_attempts 必须 >= 1")
    if not min_len <= length <= max_len:
        raise InvalidLengthError(
            f"{label}必须为 {min_len}~{max_len}，收到 {length}"
        )
    random_len = length - len(prefix) - len(suffix)
    if random_len < 1:
        raise InvalidLengthError(
            f"前缀 {len(prefix)} 位 + 后缀 {len(suffix)} 位，"
            f"总长度 {length} 位，随机部分不足 1 位"
        )
    return random_len


def generate(
    *,
    length: int = DEFAULT_LENGTH,
    prefix: str = "",
    suffix: str = "",
    max_attempts: int = 10_000,
) -> str:
    """生成一个符合 4399 注册规则的随机密码。

    Args:
        length: 密码总长度，必须在 6~20 之间，默认 16。
        prefix: 固定前缀（只允许字母和数字），计入总长度。
        suffix: 固定后缀（只允许字母和数字），计入总长度。
        max_attempts: 最大重试次数，避免极端情况下死循环。

    Returns:
        符合规则的密码字符串，形如 ``prefix + 随机部分 + suffix``。

    Raises:
        InvalidLengthError: length 越界，或前缀+后缀占满全部长度。
        InvalidPrefixError: 前缀含非字母数字字符。
        InvalidSuffixError: 后缀含非字母数字字符。
        TypeError: 参数类型错误。
        GenerationError: 超过 ``max_attempts`` 仍未生成合法密码。

    Examples:
        >>> len(generate())
        16
        >>> generate(prefix="lg").startswith("lg")
        True
        >>> generate(suffix="gz").endswith("gz")
        True
        >>> generate(prefix="lg", suffix="gz").startswith("lg")
        True
    """
    random_len = _validate_params(length, prefix, suffix, max_attempts)
    for _ in range(max_attempts):
        candidate = (
            prefix
            + "".join(secrets.choice(CHARSET) for _ in range(random_len))
            + suffix
        )
        if not validate(candidate):
            return candidate
    raise GenerationError(
        f"尝试 {max_attempts} 次后仍未生成合法密码（固定部分过长时可能出现）"
    )


def _generate_batch(
    count: int,
    *,
    unique: bool,
    make: Callable[[], str],
    label: str,
) -> list[str]:
    """批量生成的公共实现。

    Args:
        count: 需要的数量。
        unique: 是否保证互不相同。
        make: 生成单个元素的零参函数。
        label: 错误信息里用的中文名称（"密码" / "用户名"）。

    Returns:
        生成结果列表。

    Raises:
        GenerationError: ``unique=True`` 且尝试次数用尽仍凑不满。
    """
    if not unique:
        return [make() for _ in range(count)]

    seen: set[str] = set()
    out: list[str] = []
    # 可用空间不足时避免死循环：给一个宽松但有限的上限
    max_tries = max(100, count * 20)
    for _ in range(max_tries):
        item = make()
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
        if len(out) == count:
            return out
    raise GenerationError(
        f"生成 {count} 个互不相同的{label}失败："
        f"尝试 {max_tries} 次后只得到 {len(out)} 个，"
        "请增加长度或减少数量"
    )


def generate_many(
    count: int,
    *,
    length: int = DEFAULT_LENGTH,
    prefix: str = "",
    suffix: str = "",
    max_attempts: int = 10_000,
    unique: bool = False,
) -> list[str]:
    """批量生成合规密码。

    Args:
        count: 生成个数，必须 >= 1。
        length / prefix / suffix / max_attempts: 同 :func:`generate`。
        unique: 为 ``True`` 时保证结果互不相同（默认 ``False``，只保证概率上不同）。

    Returns:
        密码列表。

    Raises:
        ValueError: ``count < 1``。
        GenerationError: ``unique=True`` 时可用空间不足，凑不满 ``count`` 个。
        其它异常同 :func:`generate`。

    Examples:
        >>> len(generate_many(3))
        3
        >>> all(p.endswith("gz") for p in generate_many(3, suffix="gz"))
        True
        >>> len(set(generate_many(5, unique=True)))
        5
    """
    if not isinstance(count, int) or isinstance(count, bool):
        raise TypeError("count 必须是 int")
    if count < 1:
        raise ValueError("count 必须 >= 1")
    # 先校验一次参数，避免生成到一半才抛错
    _validate_params(length, prefix, suffix, max_attempts)
    return _generate_batch(
        count,
        unique=unique,
        make=lambda: generate(
            length=length,
            prefix=prefix,
            suffix=suffix,
            max_attempts=max_attempts,
        ),
        label="密码",
    )


def generate_username(
    *,
    length: int = DEFAULT_USERNAME_LENGTH,
    prefix: str = "",
    suffix: str = "",
    max_attempts: int = 10_000,
) -> str:
    """生成一个符合 4399 注册规则的随机用户名（账号名）。

    字符集为小写字母 + 数字（``USERNAME_CHARSET``，共 36 个），
    这样比大小写混排更好读、登录时不容易记错。

    Args:
        length: 用户名总长度，必须在 6~20 之间，默认 12。
        prefix: 固定前缀（只允许字母和数字），计入总长度。
        suffix: 固定后缀（只允许字母和数字），计入总长度。
        max_attempts: 最大重试次数。

    Returns:
        符合规则的用户名，形如 ``prefix + 随机部分 + suffix``。

    Raises:
        InvalidLengthError: length 越界，或前缀+后缀占满全部长度。
        InvalidPrefixError: 前缀含非字母数字字符。
        InvalidSuffixError: 后缀含非字母数字字符。
        TypeError: 参数类型错误。
        GenerationError: 超过 ``max_attempts`` 仍未生成合法用户名。

    Examples:
        >>> len(generate_username())
        12
        >>> generate_username(prefix="u").startswith("u")
        True
        >>> generate_username(suffix="gz").endswith("gz")
        True
    """
    random_len = _validate_params(
        length,
        prefix,
        suffix,
        max_attempts,
        min_len=USERNAME_MIN_LENGTH,
        max_len=USERNAME_MAX_LENGTH,
        label="用户名长度",
    )
    for _ in range(max_attempts):
        candidate = (
            prefix
            + "".join(secrets.choice(USERNAME_CHARSET) for _ in range(random_len))
            + suffix
        )
        if not validate_username(candidate):
            return candidate
    raise GenerationError(
        f"尝试 {max_attempts} 次后仍未生成合法用户名（固定部分过长时可能出现）"
    )


def generate_usernames(
    count: int,
    *,
    length: int = DEFAULT_USERNAME_LENGTH,
    prefix: str = "",
    suffix: str = "",
    max_attempts: int = 10_000,
    unique: bool = False,
) -> list[str]:
    """批量生成符合 4399 注册规则的随机用户名。

    Args:
        count: 生成个数，必须 >= 1。
        length / prefix / suffix / max_attempts: 同 :func:`generate_username`。
        unique: 为 ``True`` 时保证结果互不相同。

    Returns:
        用户名列表。

    Raises:
        ValueError: ``count < 1``。
        GenerationError: ``unique=True`` 时可用空间不足，凑不满 ``count`` 个。
        其它异常同 :func:`generate_username`。

    Examples:
        >>> len(generate_usernames(3))
        3
        >>> all(u.startswith("u") for u in generate_usernames(3, prefix="u"))
        True
        >>> len(set(generate_usernames(5, unique=True)))
        5
    """
    if not isinstance(count, int) or isinstance(count, bool):
        raise TypeError("count 必须是 int")
    if count < 1:
        raise ValueError("count 必须 >= 1")
    # 先校验一次参数，避免生成到一半才抛错
    _validate_params(
        length,
        prefix,
        suffix,
        max_attempts,
        min_len=USERNAME_MIN_LENGTH,
        max_len=USERNAME_MAX_LENGTH,
        label="用户名长度",
    )
    return _generate_batch(
        count,
        unique=unique,
        make=lambda: generate_username(
            length=length,
            prefix=prefix,
            suffix=suffix,
            max_attempts=max_attempts,
        ),
        label="用户名",
    )
