"""4399 web 注册页的密码加密（DES/3DES，纯标准库实现）。

``web.4399.com/user/reg.php`` 的注册 JS 在提交前会调用::

    encode_4399(pwd, encryptCode)

其中 ``encryptCode`` 由 ``GET /user/?_c=login&_a=checkUser&user=...`` 下发；
算法是标准 DES（key 不超过 8 字符时）或 3DES-EDE（key 超过 8 字符时）的
ECB 加密，明文先做 ``encodeURIComponent``、再用 NUL 补齐到 8 字节倍数，
最后输出 ``"0x" + 小写 hex``。

本模块只做「与网页 JS 互操作」这一件事。DES 早已不是安全算法，
口令/数据也不适合用它保护；这里仅用于构造符合 4399 协议的表单字段。
"""

from __future__ import annotations

import urllib.parse

from .core import Gen4399Error

__all__ = [
    "DesError",
    "encode_4399",
]

#: ``encodeURIComponent`` 不转义的额外字符（字母/数字/``_``/``.``/``-``/``~``
#: 由 :func:`urllib.parse.quote` 自身保证）
_URI_SAFE = "!~*'()"


class DesError(Gen4399Error):
    """DES/3DES 加密参数不合法。"""


# ---------------------------------------------------------------------------
# DES 常量表（FIPS 46-3）
# ---------------------------------------------------------------------------

_IP = (
    58, 50, 42, 34, 26, 18, 10, 2, 60, 52, 44, 36, 28, 20, 12, 4,
    62, 54, 46, 38, 30, 22, 14, 6, 64, 56, 48, 40, 32, 24, 16, 8,
    57, 49, 41, 33, 25, 17, 9, 1, 59, 51, 43, 35, 27, 19, 11, 3,
    61, 53, 45, 37, 29, 21, 13, 5, 63, 55, 47, 39, 31, 23, 15, 7,
)
_FP = (
    40, 8, 48, 16, 56, 24, 64, 32, 39, 7, 47, 15, 55, 23, 63, 31,
    38, 6, 46, 14, 54, 22, 62, 30, 37, 5, 45, 13, 53, 21, 61, 29,
    36, 4, 44, 12, 52, 20, 60, 28, 35, 3, 43, 11, 51, 19, 59, 27,
    34, 2, 42, 10, 50, 18, 58, 26, 33, 1, 41, 9, 49, 17, 57, 25,
)
_E = (
    32, 1, 2, 3, 4, 5, 4, 5, 6, 7, 8, 9, 8, 9, 10, 11, 12, 13,
    12, 13, 14, 15, 16, 17, 16, 17, 18, 19, 20, 21, 20, 21, 22, 23,
    24, 25, 24, 25, 26, 27, 28, 29, 28, 29, 30, 31, 32, 1,
)
_P = (
    16, 7, 20, 21, 29, 12, 28, 17, 1, 15, 23, 26, 5, 18, 31, 10,
    2, 8, 24, 14, 32, 27, 3, 9, 19, 13, 30, 6, 22, 11, 4, 25,
)
_PC1 = (
    57, 49, 41, 33, 25, 17, 9, 1, 58, 50, 42, 34, 26, 18, 10, 2,
    59, 51, 43, 35, 27, 19, 11, 3, 60, 52, 44, 36, 63, 55, 47, 39,
    31, 23, 15, 7, 62, 54, 46, 38, 30, 22, 14, 6, 61, 53, 45, 37,
    29, 21, 13, 5, 28, 20, 12, 4,
)
_PC2 = (
    14, 17, 11, 24, 1, 5, 3, 28, 15, 6, 21, 10, 23, 19, 12, 4,
    26, 8, 16, 7, 27, 20, 13, 2, 41, 52, 31, 37, 47, 55, 30, 40,
    51, 45, 33, 48, 44, 49, 39, 56, 34, 53, 46, 42, 50, 36, 29, 32,
)
_SHIFTS = (1, 1, 2, 2, 2, 2, 2, 2, 1, 2, 2, 2, 2, 2, 2, 1)

#: 8 个 S 盒，每个 4 行 × 16 列
_SBOXES = (
    (
        (14, 4, 13, 1, 2, 15, 11, 8, 3, 10, 6, 12, 5, 9, 0, 7),
        (0, 15, 7, 4, 14, 2, 13, 1, 10, 6, 12, 11, 9, 5, 3, 8),
        (4, 1, 14, 8, 13, 6, 2, 11, 15, 12, 9, 7, 3, 10, 5, 0),
        (15, 12, 8, 2, 4, 9, 1, 7, 5, 11, 3, 14, 10, 0, 6, 13),
    ),
    (
        (15, 1, 8, 14, 6, 11, 3, 4, 9, 7, 2, 13, 12, 0, 5, 10),
        (3, 13, 4, 7, 15, 2, 8, 14, 12, 0, 1, 10, 6, 9, 11, 5),
        (0, 14, 7, 11, 10, 4, 13, 1, 5, 8, 12, 6, 9, 3, 2, 15),
        (13, 8, 10, 1, 3, 15, 4, 2, 11, 6, 7, 12, 0, 5, 14, 9),
    ),
    (
        (10, 0, 9, 14, 6, 3, 15, 5, 1, 13, 12, 7, 11, 4, 2, 8),
        (13, 7, 0, 9, 3, 4, 6, 10, 2, 8, 5, 14, 12, 11, 15, 1),
        (13, 6, 4, 9, 8, 15, 3, 0, 11, 1, 2, 12, 5, 10, 14, 7),
        (1, 10, 13, 0, 6, 9, 8, 7, 4, 15, 14, 3, 11, 5, 2, 12),
    ),
    (
        (7, 13, 14, 3, 0, 6, 9, 10, 1, 2, 8, 5, 11, 12, 4, 15),
        (13, 8, 11, 5, 6, 15, 0, 3, 4, 7, 2, 12, 1, 10, 14, 9),
        (10, 6, 9, 0, 12, 11, 7, 13, 15, 1, 3, 14, 5, 2, 8, 4),
        (3, 15, 0, 6, 10, 1, 13, 8, 9, 4, 5, 11, 12, 7, 2, 14),
    ),
    (
        (2, 12, 4, 1, 7, 10, 11, 6, 8, 5, 3, 15, 13, 0, 14, 9),
        (14, 11, 2, 12, 4, 7, 13, 1, 5, 0, 15, 10, 3, 9, 8, 6),
        (4, 2, 1, 11, 10, 13, 7, 8, 15, 9, 12, 5, 6, 3, 0, 14),
        (11, 8, 12, 7, 1, 14, 2, 13, 6, 15, 0, 9, 10, 4, 5, 3),
    ),
    (
        (12, 1, 10, 15, 9, 2, 6, 8, 0, 13, 3, 4, 14, 7, 5, 11),
        (10, 15, 4, 2, 7, 12, 9, 5, 6, 1, 13, 14, 0, 11, 3, 8),
        (9, 14, 15, 5, 2, 8, 12, 3, 7, 0, 4, 10, 1, 13, 11, 6),
        (4, 3, 2, 12, 9, 5, 15, 10, 11, 14, 1, 7, 6, 0, 8, 13),
    ),
    (
        (4, 11, 2, 14, 15, 0, 8, 13, 3, 12, 9, 7, 5, 10, 6, 1),
        (13, 0, 11, 7, 4, 9, 1, 10, 14, 3, 5, 12, 2, 15, 8, 6),
        (1, 4, 11, 13, 12, 3, 7, 14, 10, 15, 6, 8, 0, 5, 9, 2),
        (6, 11, 13, 8, 1, 4, 10, 7, 9, 5, 0, 15, 14, 2, 3, 12),
    ),
    (
        (13, 2, 8, 4, 6, 15, 11, 1, 10, 9, 3, 14, 5, 0, 12, 7),
        (1, 15, 13, 8, 10, 3, 7, 4, 12, 5, 6, 11, 0, 14, 9, 2),
        (7, 11, 4, 1, 9, 12, 14, 2, 0, 6, 10, 13, 15, 3, 5, 8),
        (2, 1, 14, 7, 4, 10, 8, 13, 15, 12, 9, 0, 3, 5, 6, 11),
    ),
)


def _permute(value: int, table: tuple[int, ...], in_bits: int) -> int:
    """按 FIPS 表对 ``in_bits`` 位的整数做置换，输出位置 0 为最高位。"""
    out = 0
    for position in table:
        out = (out << 1) | ((value >> (in_bits - position)) & 1)
    return out


def _key_schedule(key: bytes) -> tuple[int, ...]:
    """生成 16 个 48 位子密钥。"""
    if len(key) != 8:
        raise DesError("DES key 必须是 8 字节")
    pc1 = _permute(int.from_bytes(key, "big"), _PC1, 64)
    left, right = pc1 >> 28, pc1 & 0x0FFFFFFF
    subkeys = []
    for shift in _SHIFTS:
        left = ((left << shift) | (left >> (28 - shift))) & 0x0FFFFFFF
        right = ((right << shift) | (right >> (28 - shift))) & 0x0FFFFFFF
        subkeys.append(_permute((left << 28) | right, _PC2, 56))
    return tuple(subkeys)


def _feistel(right: int, subkey: int) -> int:
    """DES 轮函数 f(R, K)。"""
    mixed = _permute(right, _E, 32) ^ subkey
    out = 0
    for index, sbox in enumerate(_SBOXES):
        chunk = (mixed >> (42 - 6 * index)) & 0x3F
        row = ((chunk >> 4) & 0x2) | (chunk & 0x1)
        column = (chunk >> 1) & 0x0F
        out = (out << 4) | sbox[row][column]
    return _permute(out, _P, 32)


def _des_crypt(block: bytes, subkeys: tuple[int, ...], *, decrypt: bool) -> bytes:
    if len(block) != 8:
        raise DesError("DES 分组必须是 8 字节")
    value = _permute(int.from_bytes(block, "big"), _IP, 64)
    left, right = value >> 32, value & 0xFFFFFFFF
    keys = reversed(subkeys) if decrypt else subkeys
    for subkey in keys:
        left, right = right, left ^ _feistel(right, subkey)
    # 最后一轮后左右交换：FP 的输入是 (R16, L16)
    return _permute((right << 32) | left, _FP, 64).to_bytes(8, "big")


def _des_encrypt_block(block: bytes, key: bytes) -> bytes:
    """单分组 DES 加密（测试/互操作辅助函数）。"""
    return _des_crypt(block, _key_schedule(key), decrypt=False)


def _triple_des_encrypt_block(block: bytes, key: bytes) -> bytes:
    """单分组 3DES-EDE 加密（测试/互操作辅助函数）。"""
    if len(key) != 24:
        raise DesError("3DES key 必须是 24 字节")
    first, second, third = key[:8], key[8:16], key[16:24]
    data = _des_encrypt_block(block, first)
    data = _des_crypt(data, _key_schedule(second), decrypt=True)
    return _des_encrypt_block(data, third)


def _zero_pad(data: bytes) -> bytes:
    """按 CryptoJS/4399 逻辑用 NUL 补齐到 8 字节倍数（已对齐则不变）。"""
    remainder = len(data) % 8
    if remainder:
        data += b"\x00" * (8 - remainder)
    return data


def _ecb_encrypt(data: bytes, key: bytes) -> bytes:
    """DES/3DES ECB 加密（``key`` 长度 8 或 24）。"""
    padded = _zero_pad(data)
    out = bytearray()
    for offset in range(0, len(padded), 8):
        block = padded[offset : offset + 8]
        if len(key) == 24:
            out += _triple_des_encrypt_block(block, key)
        else:
            out += _des_encrypt_block(block, key)
    return bytes(out)


def _prepare_key(key: str) -> bytes:
    """把 JS 里的口令字符串转成 DES/3DES key 字节（NUL 补齐）。"""
    if not isinstance(key, str):
        raise TypeError(f"key 必须是 str，收到 {type(key).__name__}")
    if not key:
        raise ValueError("key 不能为空")
    try:
        raw = key.encode("ascii")
    except UnicodeEncodeError as exc:
        raise DesError("key 必须是 ASCII 字符串") from exc
    if len(raw) <= 8:
        return raw + b"\x00" * (8 - len(raw))
    return raw[:24] + b"\x00" * max(0, 24 - len(raw))


def encode_4399(value: str, key: str) -> str:
    """复刻 4399 web 注册页的 ``encode_4399(value, key)``。

    Args:
        value: 待加密明文（password / 确认密码）。
        key: ``checkUser`` 接口下发的 ``encryptCode``（如 ``"5c43e3"``）。

    Returns:
        ``"0x" + 小写 hex`` 的 DES/3DES-ECB 密文。

    Raises:
        TypeError: ``value`` / ``key`` 不是 str。
        ValueError: ``key`` 为空。
        DesError: ``key`` 含非 ASCII 字符，或内部参数不合法。

    Note:
        仅用于与 4399 页面协议互操作；DES 不提供现代意义上的机密性保护。
    """
    if not isinstance(value, str):
        raise TypeError(f"value 必须是 str，收到 {type(value).__name__}")
    encoded = urllib.parse.quote(value, safe=_URI_SAFE).encode("ascii")
    if not encoded:
        return "0x"
    raw_key = _prepare_key(key)
    ciphertext = _ecb_encrypt(encoded, raw_key)
    return "0x" + ciphertext.hex()
