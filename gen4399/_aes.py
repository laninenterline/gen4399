"""4399 注册表单的 CryptoJS 兼容 AES 加解密（纯标准库实现）。

4399 注册页在前端用 CryptoJS 的「口令模式」加密敏感字段
（密码 / 确认密码 / 真实姓名 / 身份证号）：

    EVP_BytesToKey(MD5, 随机 8 字节 salt) -> AES-256-CBC + PKCS#7
    -> Base64("Salted__" + salt + ciphertext)

本模块只做「与网页 JS 互操作」这一件事。**它不是为机密保护设计的**：
口令 ``lzYW5qaXVqa`` 硬编码在 4399 的公开 JS 里，任何人都能看到；
因此不要把它当成安全存储或安全传输手段，只用于构造符合协议的表单字段。

实现约束：只用标准库（``hashlib`` / ``base64`` / ``secrets``），
AES-256 的分组加密与解密由本模块按 FIPS-197 自行实现，不依赖任何第三方库。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import secrets

from .core import Gen4399Error

__all__ = [
    "PASSPHRASE",
    "SALT_LEN",
    "CryptoError",
    "encrypt_aes",
    "decrypt_aes",
]

#: 4399 注册页前端硬编码的 CryptoJS 口令（公开可查，不是秘密）
PASSPHRASE: str = "lzYW5qaXVqa"

#: CryptoJS / OpenSSL "Salted__" 格式的 salt 长度（字节）
SALT_LEN: int = 8

_KEY_LEN = 32  # AES-256
_IV_LEN = 16
_BLOCK_SIZE = 16
_NUM_ROUNDS = 14  # AES-256：Nk=8，Nr = Nk + 6
_SALTED_PREFIX = b"Salted__"


class CryptoError(Gen4399Error):
    """AES 加解密失败（格式非法、填充错误、密钥/口令不匹配等）。"""


# ---------------------------------------------------------------------------
# GF(2^8) 运算与 AES S 盒
# ---------------------------------------------------------------------------


def _rotl8(value: int, shift: int) -> int:
    """把 8 位整数循环左移 ``shift`` 位。"""
    return ((value << shift) | (value >> (8 - shift))) & 0xFF


def _gmul(a: int, b: int) -> int:
    """GF(2^8) 乘法，模 AES 不可约多项式 0x11B。"""
    result = 0
    for _ in range(8):
        if b & 1:
            result ^= a
        high = a & 0x80
        a = (a << 1) & 0xFF
        if high:
            a ^= 0x1B
        b >>= 1
    return result


def _ginv(a: int) -> int:
    """GF(2^8) 乘法逆元；0 的逆元按 AES 约定取 0。"""
    if a == 0:
        return 0
    # a^254 == a^-1（a != 0），用平方-乘法求幂
    result = 1
    base = a
    exponent = 254
    while exponent:
        if exponent & 1:
            result = _gmul(result, base)
        base = _gmul(base, base)
        exponent >>= 1
    return result


def _build_sbox() -> tuple[int, ...]:
    """按仿射变换生成 AES S 盒（S(x) = inv(x)⊕rotl1..4⊕0x63）。"""
    box = []
    for value in range(256):
        inv = _ginv(value)
        box.append(
            inv
            ^ _rotl8(inv, 1)
            ^ _rotl8(inv, 2)
            ^ _rotl8(inv, 3)
            ^ _rotl8(inv, 4)
            ^ 0x63
        )
    return tuple(box)


def _build_inv_sbox(sbox: tuple[int, ...]) -> tuple[int, ...]:
    """由 S 盒反推逆 S 盒。"""
    inverse = [0] * 256
    for index, value in enumerate(sbox):
        inverse[value] = index
    return tuple(inverse)


_SBOX = _build_sbox()
_INV_SBOX = _build_inv_sbox(_SBOX)


# ---------------------------------------------------------------------------
# AES-256 分组加密 / 解密（FIPS-197）
# ---------------------------------------------------------------------------


def _expand_key(key: bytes) -> list[list[int]]:
    """AES 密钥扩展，返回每轮的 16 字节轮密钥（共 Nr+1 组）。

    Args:
        key: 16/24/32 字节密钥；本模块只使用 32 字节（AES-256）。

    Raises:
        ValueError: 密钥长度不是 16/24/32 字节。
    """
    if len(key) not in (16, 24, 32):
        raise ValueError(f"AES 密钥长度必须是 16/24/32 字节，收到 {len(key)}")
    nk = len(key) // 4
    rounds = nk + 6
    words = [list(key[4 * i : 4 * i + 4]) for i in range(nk)]
    rcon = 1
    for i in range(nk, 4 * (rounds + 1)):
        temp = list(words[i - 1])
        if i % nk == 0:
            temp = temp[1:] + temp[:1]
            temp = [_SBOX[b] for b in temp]
            temp[0] ^= rcon
            rcon = _gmul(rcon, 2)
        elif nk > 6 and i % nk == 4:
            temp = [_SBOX[b] for b in temp]
        words.append([words[i - nk][j] ^ temp[j] for j in range(4)])
    # 每轮 4 个 word 按列拼成 16 字节轮密钥（与 state 的列主序一致）
    return [sum(words[4 * r : 4 * r + 4], []) for r in range(rounds + 1)]


def _add_round_key(state: list[int], round_key: list[int]) -> None:
    for i in range(16):
        state[i] ^= round_key[i]


def _sub_bytes(state: list[int], box: tuple[int, ...]) -> None:
    for i in range(16):
        state[i] = box[state[i]]


def _shift_rows(state: list[int]) -> None:
    """行移位：第 r 行循环左移 r 字节；state 下标 = r + 4*c。"""
    original = list(state)
    for r in range(4):
        for c in range(4):
            state[r + 4 * c] = original[r + 4 * ((c + r) % 4)]


def _inv_shift_rows(state: list[int]) -> None:
    """逆行移位：第 r 行循环右移 r 字节。"""
    original = list(state)
    for r in range(4):
        for c in range(4):
            state[r + 4 * c] = original[r + 4 * ((c - r) % 4)]


def _mix_columns(state: list[int]) -> None:
    for c in range(4):
        base = 4 * c
        a0, a1, a2, a3 = state[base : base + 4]
        state[base] = _gmul(a0, 2) ^ _gmul(a1, 3) ^ a2 ^ a3
        state[base + 1] = a0 ^ _gmul(a1, 2) ^ _gmul(a2, 3) ^ a3
        state[base + 2] = a0 ^ a1 ^ _gmul(a2, 2) ^ _gmul(a3, 3)
        state[base + 3] = _gmul(a0, 3) ^ a1 ^ a2 ^ _gmul(a3, 2)


def _inv_mix_columns(state: list[int]) -> None:
    for c in range(4):
        base = 4 * c
        a0, a1, a2, a3 = state[base : base + 4]
        state[base] = (
            _gmul(a0, 14) ^ _gmul(a1, 11) ^ _gmul(a2, 13) ^ _gmul(a3, 9)
        )
        state[base + 1] = (
            _gmul(a0, 9) ^ _gmul(a1, 14) ^ _gmul(a2, 11) ^ _gmul(a3, 13)
        )
        state[base + 2] = (
            _gmul(a0, 13) ^ _gmul(a1, 9) ^ _gmul(a2, 14) ^ _gmul(a3, 11)
        )
        state[base + 3] = (
            _gmul(a0, 11) ^ _gmul(a1, 13) ^ _gmul(a2, 9) ^ _gmul(a3, 14)
        )


def _encrypt_block(round_keys: list[list[int]], block: bytes) -> bytes:
    """加密单个 16 字节分组（AES-256，14 轮）。"""
    state = list(block)
    _add_round_key(state, round_keys[0])
    for round_index in range(1, _NUM_ROUNDS):
        _sub_bytes(state, _SBOX)
        _shift_rows(state)
        _mix_columns(state)
        _add_round_key(state, round_keys[round_index])
    _sub_bytes(state, _SBOX)
    _shift_rows(state)
    _add_round_key(state, round_keys[_NUM_ROUNDS])
    return bytes(state)


def _decrypt_block(round_keys: list[list[int]], block: bytes) -> bytes:
    """解密单个 16 字节分组（AES-256，14 轮）。"""
    state = list(block)
    _add_round_key(state, round_keys[_NUM_ROUNDS])
    for round_index in range(_NUM_ROUNDS - 1, 0, -1):
        _inv_shift_rows(state)
        _sub_bytes(state, _INV_SBOX)
        _add_round_key(state, round_keys[round_index])
        _inv_mix_columns(state)
    _inv_shift_rows(state)
    _sub_bytes(state, _INV_SBOX)
    _add_round_key(state, round_keys[0])
    return bytes(state)


# ---------------------------------------------------------------------------
# CBC 模式、EVP_BytesToKey 与 PKCS#7 填充
# ---------------------------------------------------------------------------


def _evp_bytes_to_key(
    passphrase: bytes, salt: bytes
) -> tuple[bytes, bytes]:
    """OpenSSL / CryptoJS 的 ``EVP_BytesToKey(MD5, salt, 1 轮)``。

    依次计算 ``D_i = MD5(D_{i-1} + passphrase + salt)``（``D_0 = b""``），
    拼接后取前 32 字节为 AES-256 密钥、接下来 16 字节为 CBC 的 IV。

    Args:
        passphrase: 口令的 UTF-8 字节。
        salt: EVP 格式的 salt（通常 8 字节）。

    Returns:
        ``(key, iv)``，分别为 32 与 16 字节。
    """
    derived = b""
    previous = b""
    while len(derived) < _KEY_LEN + _IV_LEN:
        # 这里 MD5 只用于复刻协议，不是安全用途
        previous = hashlib.md5(
            previous + passphrase + salt, usedforsecurity=False
        ).digest()
        derived += previous
    return derived[:_KEY_LEN], derived[_KEY_LEN : _KEY_LEN + _IV_LEN]


def _pkcs7_pad(data: bytes) -> bytes:
    """PKCS#7 填充（空数据补满一整块）。"""
    pad = _BLOCK_SIZE - len(data) % _BLOCK_SIZE
    return data + bytes([pad]) * pad


def _pkcs7_unpad(data: bytes) -> bytes:
    """去掉 PKCS#7 填充；填充非法时抛 :class:`CryptoError`。"""
    if not data or len(data) % _BLOCK_SIZE != 0:
        raise CryptoError("密文长度不是 16 字节的整数倍")
    pad = data[-1]
    if not 1 <= pad <= _BLOCK_SIZE:
        raise CryptoError("PKCS#7 填充无效（填充字节越界）")
    if data[-pad:] != bytes([pad]) * pad:
        raise CryptoError("PKCS#7 填充无效（填充内容不一致）")
    return data[:-pad]


def _cbc_encrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    """AES-CBC 加密；要求 ``data`` 已按 ``_BLOCK_SIZE`` 对齐。"""
    round_keys = _expand_key(key)
    out = bytearray()
    previous = bytes(iv)
    for offset in range(0, len(data), _BLOCK_SIZE):
        block = data[offset : offset + _BLOCK_SIZE]
        mixed = bytes(a ^ b for a, b in zip(block, previous))
        previous = _encrypt_block(round_keys, mixed)
        out += previous
    return bytes(out)


def _cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    """AES-CBC 解密；``data`` 长度非法时抛 :class:`CryptoError`。"""
    if not data or len(data) % _BLOCK_SIZE != 0:
        raise CryptoError("密文长度不是 16 字节的整数倍")
    round_keys = _expand_key(key)
    out = bytearray()
    previous = bytes(iv)
    for offset in range(0, len(data), _BLOCK_SIZE):
        block = data[offset : offset + _BLOCK_SIZE]
        plain = _decrypt_block(round_keys, block)
        out += bytes(a ^ b for a, b in zip(plain, previous))
        previous = block
    return bytes(out)


# ---------------------------------------------------------------------------
# 公开接口
# ---------------------------------------------------------------------------


def _normalize_passphrase(passphrase: str | bytes) -> bytes:
    """把口令统一成 UTF-8 字节；``str`` 与 ``bytes`` 等价。"""
    if isinstance(passphrase, str):
        return passphrase.encode("utf-8")
    if isinstance(passphrase, bytes):
        return passphrase
    raise TypeError(
        f"passphrase 必须是 str 或 bytes，收到 {type(passphrase).__name__}"
    )


def encrypt_aes(plaintext: str, passphrase: str | bytes = PASSPHRASE) -> str:
    """按 CryptoJS 口令模式加密字符串。

    格式：``Base64("Salted__" + 随机 salt + AES-256-CBC(PKCS#7 填充后的密文))``。

    Args:
        plaintext: 待加密明文；按 UTF-8 编码。
        passphrase: 口令，``str`` 按 UTF-8 编码；默认 4399 的硬编码口令。

    Returns:
        Base64 字符串，以 ``U2FsdGVkX1``（``Salted__`` 的前缀）开头。
        每次调用都用新的随机 salt，因此相同明文两次加密结果不同。

    Raises:
        TypeError: ``plaintext`` 不是 ``str``，或 ``passphrase`` 不是
            ``str``/``bytes``。

    Note:
        仅用于与 4399 注册页的协议互操作，**不提供机密保护**。
    """
    if not isinstance(plaintext, str):
        raise TypeError(f"plaintext 必须是 str，收到 {type(plaintext).__name__}")
    passphrase_bytes = _normalize_passphrase(passphrase)
    salt = secrets.token_bytes(SALT_LEN)
    key, iv = _evp_bytes_to_key(passphrase_bytes, salt)
    ciphertext = _cbc_encrypt(key, iv, _pkcs7_pad(plaintext.encode("utf-8")))
    return base64.b64encode(_SALTED_PREFIX + salt + ciphertext).decode("ascii")


def decrypt_aes(ciphertext: str, passphrase: str | bytes = PASSPHRASE) -> str:
    """解密 CryptoJS 口令模式生成的 Base64 密文。

    Args:
        ciphertext: ``encrypt_aes`` 或 CryptoJS 产出的 Base64 字符串。
        passphrase: 口令，``str`` 按 UTF-8 编码；默认 4399 的硬编码口令。

    Returns:
        解密后的 UTF-8 明文。

    Raises:
        TypeError: ``ciphertext`` 不是 ``str``，或 ``passphrase`` 不是
            ``str``/``bytes``。
        CryptoError: Base64 非法、缺少 ``Salted__`` 头、密文长度非法、
            PKCS#7 填充错误、口令不匹配，或结果不是合法 UTF-8 文本。

    Note:
        仅用于与 4399 注册页的协议互操作，**不提供机密保护**。
    """
    if not isinstance(ciphertext, str):
        raise TypeError(
            f"ciphertext 必须是 str，收到 {type(ciphertext).__name__}"
        )
    passphrase_bytes = _normalize_passphrase(passphrase)
    try:
        raw = base64.b64decode(ciphertext.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise CryptoError("密文不是合法的 Base64 字符串") from exc
    if len(raw) < len(_SALTED_PREFIX) + SALT_LEN + _BLOCK_SIZE:
        raise CryptoError("密文过短：缺少 Salted__ 头、salt 或密文分组")
    if not raw.startswith(_SALTED_PREFIX):
        raise CryptoError("不是 CryptoJS 兼容格式：缺少 Salted__ 前缀")
    salt = raw[len(_SALTED_PREFIX) : len(_SALTED_PREFIX) + SALT_LEN]
    body = raw[len(_SALTED_PREFIX) + SALT_LEN :]
    key, iv = _evp_bytes_to_key(passphrase_bytes, salt)
    padded = _cbc_decrypt(key, iv, body)
    plaintext = _pkcs7_unpad(padded)
    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CryptoError("解密结果不是合法的 UTF-8 文本（口令可能不匹配）") from exc
