"""gen4399._aes 单元测试（只用标准库 unittest，不联网）。"""

import ast
import base64
import hashlib
import inspect
import secrets
import unittest

from gen4399 import _aes
from gen4399._aes import (
    PASSPHRASE,
    SALT_LEN,
    CryptoError,
    decrypt_aes,
    encrypt_aes,
)
from gen4399.core import Gen4399Error

try:  # 可选依赖：只用于交叉验证；没装 pycryptodome 时相关测试整体跳过
    from Crypto.Cipher import AES as _CryptoAES
    from Crypto.Hash import MD5 as _CryptoMD5
    from Crypto.Util.Padding import pad as _crypto_pad
    from Crypto.Util.Padding import unpad as _crypto_unpad

    _HAVE_PYCRYPTODOME = True
except ImportError:  # pragma: no cover - 取决于运行环境
    _CryptoAES = None
    _CryptoMD5 = None
    _crypto_pad = None
    _crypto_unpad = None
    _HAVE_PYCRYPTODOME = False


#: 实测抓包样本（pycryptodome 核对过）：解密结果是 "123456"
KNOWN_CIPHERTEXT = "U2FsdGVkX1+XT5RHET9nj1g596L2dfzHBYuZLXYyWJI="
KNOWN_PLAINTEXT = "123456"

#: CryptoJS "Salted__" 格式的固定前缀
SALTED_PREFIX = b"Salted__"

_BLOCK = 16
_KEY_LEN = 32
_IV_LEN = 16


def _split_salted(encoded: str) -> tuple[bytes, bytes]:
    """从 Base64 密文里拆出 (salt, ciphertext)，并校验 Salted__ 结构。"""
    raw = base64.b64decode(encoded.encode("ascii"), validate=True)
    if not raw.startswith(SALTED_PREFIX):
        raise AssertionError("缺少 Salted__ 前缀")
    head = len(SALTED_PREFIX)
    return raw[head : head + SALT_LEN], raw[head + SALT_LEN :]


def _craft(salt: bytes, ciphertext: bytes) -> str:
    """把 (salt, ciphertext) 包成 CryptoJS 风格的 Base64 字符串。"""
    return base64.b64encode(SALTED_PREFIX + salt + ciphertext).decode("ascii")


def _bad_padding_ciphertext() -> str:
    """构造「填充非法」的合法结构密文（末字节 0x41 不是合法填充）。"""
    salt = b"\x01\x02\x03\x04\x05\x06\x07\x08"
    key, iv = _aes._evp_bytes_to_key(PASSPHRASE.encode(), salt)
    body = _aes._cbc_encrypt(key, iv, b"A" * _BLOCK)
    return _craft(salt, body)


def _bad_utf8_ciphertext() -> str:
    """构造「填充合法但 UTF-8 非法」的密文（明文是 0xFF + 15 个 0x0F）。"""
    salt = b"\x08\x07\x06\x05\x04\x03\x02\x01"
    key, iv = _aes._evp_bytes_to_key(PASSPHRASE.encode(), salt)
    body = _aes._cbc_encrypt(key, iv, b"\xff" + b"\x0f" * 15)
    return _craft(salt, body)


class TestKnownSample(unittest.TestCase):
    """真实抓包样本必须能解密（最重要的一条契约）。"""

    def test_decrypt_known_sample(self):
        self.assertEqual(decrypt_aes(KNOWN_CIPHERTEXT), KNOWN_PLAINTEXT)

    def test_decrypt_known_sample_with_bytes_passphrase(self):
        self.assertEqual(
            decrypt_aes(KNOWN_CIPHERTEXT, b"lzYW5qaXVqa"), KNOWN_PLAINTEXT
        )

    def test_known_sample_structure(self):
        salt, body = _split_salted(KNOWN_CIPHERTEXT)
        self.assertEqual(len(salt), SALT_LEN)
        # "123456" 共 6 字，PKCS#7 补到 16 字，恰好 1 个分组
        self.assertEqual(len(body), _BLOCK)

    def test_default_passphrase_value(self):
        self.assertEqual(PASSPHRASE, "lzYW5qaXVqa")
        self.assertEqual(SALT_LEN, 8)


class TestEncryptFormat(unittest.TestCase):
    """加密输出的结构：Salted__ + 随机 salt + Base64。"""

    def test_starts_with_salted_prefix(self):
        for plaintext in ("123456", "", "中文密码", "😀" * 20):
            with self.subTest(plaintext=plaintext):
                encoded = encrypt_aes(plaintext)
                self.assertTrue(encoded.startswith("U2FsdGVkX1"))
                self.assertTrue(encoded.isascii())
                _split_salted(encoded)  # 结构校验

    def test_salt_is_random_per_call(self):
        encoded = [encrypt_aes("same-plaintext") for _ in range(20)]
        self.assertEqual(len(set(encoded)), len(encoded))
        salts = {_split_salted(item)[0] for item in encoded}
        self.assertEqual(len(salts), len(encoded))
        for encoded_item in encoded:
            self.assertEqual(len(_split_salted(encoded_item)[0]), SALT_LEN)

    def test_same_plaintext_twice_different(self):
        self.assertNotEqual(encrypt_aes("123456"), encrypt_aes("123456"))

    def test_ciphertext_block_lengths(self):
        for length, blocks in (
            (0, 1),
            (1, 1),
            (15, 1),
            (16, 2),
            (17, 2),
            (31, 2),
            (32, 3),
        ):
            with self.subTest(length=length):
                plaintext = "a" * length
                _, body = _split_salted(encrypt_aes(plaintext))
                self.assertEqual(len(body), blocks * _BLOCK)

    def test_output_decodable_as_base64(self):
        raw = base64.b64decode(encrypt_aes("x"), validate=True)
        self.assertEqual(raw[: len(SALTED_PREFIX)], SALTED_PREFIX)


class TestRoundTrip(unittest.TestCase):
    """encrypt_aes / decrypt_aes 往返。"""

    def test_empty_string(self):
        self.assertEqual(decrypt_aes(encrypt_aes("")), "")

    def test_ascii_values(self):
        for plaintext in ("123456", "a", "Abc12345", "x" * 100):
            with self.subTest(plaintext=plaintext):
                self.assertEqual(decrypt_aes(encrypt_aes(plaintext)), plaintext)

    def test_unicode_values(self):
        values = (
            "中文密码",
            "密码Abc123",
            "表情😀🎮🔒",
            "混合 mixed 文本 123",
            "换行\n制表\t字符",
            "\u00e9\u00e8\u00ea\u00eb",
        )
        for plaintext in values:
            with self.subTest(plaintext=plaintext):
                self.assertEqual(decrypt_aes(encrypt_aes(plaintext)), plaintext)

    def test_custom_str_passphrase(self):
        encoded = encrypt_aes("secret", "custom-passphrase")
        self.assertEqual(decrypt_aes(encoded, "custom-passphrase"), "secret")

    def test_bytes_and_str_passphrase_equivalent(self):
        encoded = encrypt_aes("等价口令", PASSPHRASE.encode("utf-8"))
        self.assertEqual(decrypt_aes(encoded, PASSPHRASE), "等价口令")
        encoded = encrypt_aes("等价口令2", PASSPHRASE)
        self.assertEqual(decrypt_aes(encoded, PASSPHRASE.encode()), "等价口令2")

    def test_roundtrip_lengths(self):
        for length in range(0, 33):
            with self.subTest(length=length):
                plaintext = "".join(chr(0x4E00 + i) for i in range(length))
                self.assertEqual(decrypt_aes(encrypt_aes(plaintext)), plaintext)


class TestCryptoError(unittest.TestCase):
    """所有格式/填充错误都必须是 CryptoError。"""

    def test_crypto_error_is_gen4399_error(self):
        self.assertTrue(issubclass(CryptoError, Gen4399Error))

    def test_invalid_base64(self):
        for ciphertext in ("!!!not-base64!!!", "abc", "", "====", "中文"):
            with self.subTest(ciphertext=ciphertext):
                with self.assertRaises(CryptoError):
                    decrypt_aes(ciphertext)

    def test_missing_salted_prefix(self):
        raw = b"NotSalted__" + b"\x00" * 24
        with self.assertRaises(CryptoError):
            decrypt_aes(base64.b64encode(raw).decode("ascii"))

    def test_too_short(self):
        for raw in (
            b"Salted__",
            b"Salted__" + b"\x00" * 8,
            b"Salted__" + b"\x00" * 8 + b"\x00" * 15,
        ):
            with self.subTest(raw_len=len(raw)):
                with self.assertRaises(CryptoError):
                    decrypt_aes(base64.b64encode(raw).decode("ascii"))

    def test_misaligned_ciphertext_body(self):
        raw = SALTED_PREFIX + b"12345678" + b"\x00" * 17
        with self.assertRaises(CryptoError):
            decrypt_aes(base64.b64encode(raw).decode("ascii"))

    def test_bad_padding(self):
        with self.assertRaises(CryptoError):
            decrypt_aes(_bad_padding_ciphertext())

    def test_invalid_utf8_plaintext(self):
        with self.assertRaises(CryptoError):
            decrypt_aes(_bad_utf8_ciphertext())

    def test_wrong_passphrase(self):
        with self.assertRaises(CryptoError):
            decrypt_aes(KNOWN_CIPHERTEXT, "wrong-passphrase")

    def test_zero_ciphertext_block(self):
        raw = SALTED_PREFIX + b"\x00" * SALT_LEN + b"\x00" * _BLOCK
        with self.assertRaises(CryptoError):
            decrypt_aes(base64.b64encode(raw).decode("ascii"))


class TestTypeError(unittest.TestCase):
    """类型错误必须是 TypeError（而不是 CryptoError）。"""

    def test_encrypt_plaintext_not_str(self):
        for value in (None, 123, b"bytes", 1.5, ["x"]):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    encrypt_aes(value)  # type: ignore[arg-type]

    def test_decrypt_ciphertext_not_str(self):
        for value in (None, 123, b"U2FsdGVkX1", 1.5):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    decrypt_aes(value)  # type: ignore[arg-type]

    def test_bad_passphrase_type(self):
        for value in (None, 123, 1.5, bytearray(b"abc"), ["x"]):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    encrypt_aes("x", value)  # type: ignore[arg-type]
                with self.assertRaises(TypeError):
                    decrypt_aes(KNOWN_CIPHERTEXT, value)  # type: ignore[arg-type]


class TestAesPrimitives(unittest.TestCase):
    """AES-256 / CBC / PKCS#7 的内部实现正确性。"""

    def test_fips197_aes256_vector(self):
        # FIPS-197 附录 C.3 的 AES-256 测试向量
        key = bytes(range(_KEY_LEN))
        plaintext = bytes.fromhex("00112233445566778899aabbccddeeff")
        expected = bytes.fromhex("8ea2b7ca516745bfeafc49904b496089")
        round_keys = _aes._expand_key(key)
        self.assertEqual(_aes._encrypt_block(round_keys, plaintext), expected)
        self.assertEqual(_aes._decrypt_block(round_keys, expected), plaintext)

    def test_expand_key_round0_is_key_prefix(self):
        key = bytes(range(_KEY_LEN))
        round_keys = _aes._expand_key(key)
        self.assertEqual(len(round_keys), 15)  # Nr + 1
        # 每轮轮密钥 16 字节；第 0 轮取 32 字节密钥的前半部分
        self.assertEqual(len(round_keys[0]), _BLOCK)
        self.assertEqual(bytes(round_keys[0]), key[:_BLOCK])
        self.assertEqual(bytes(round_keys[1]), key[_BLOCK:])

    def test_expand_key_rejects_bad_length(self):
        with self.assertRaises(ValueError):
            _aes._expand_key(b"\x00" * 8)

    def test_sbox_known_values(self):
        self.assertEqual(_aes._SBOX[0x00], 0x63)
        self.assertEqual(_aes._SBOX[0x01], 0x7C)
        self.assertEqual(_aes._SBOX[0x53], 0xED)
        self.assertEqual(_aes._SBOX[0xFF], 0x16)
        for value in range(256):
            with self.subTest(value=value):
                self.assertEqual(_aes._INV_SBOX[_aes._SBOX[value]], value)

    def test_pkcs7_pad(self):
        self.assertEqual(_aes._pkcs7_pad(b""), b"\x10" * 16)
        padded = _aes._pkcs7_pad(b"abc")
        self.assertEqual(len(padded), 16)
        self.assertEqual(padded[-13:], b"\x0d" * 13)
        self.assertEqual(len(_aes._pkcs7_pad(b"a" * 16)), 32)

    def test_pkcs7_unpad_roundtrip(self):
        for data in (b"", b"a", b"a" * 15, b"a" * 16, b"a" * 31):
            with self.subTest(length=len(data)):
                self.assertEqual(_aes._pkcs7_unpad(_aes._pkcs7_pad(data)), data)

    def test_pkcs7_unpad_rejects_bad_padding(self):
        cases = (
            b"",  # 空
            b"a" * 15,  # 非整块
            b"a" * 15 + b"\x00",  # 填充字节为 0
            b"a" * 15 + b"\x11",  # 填充字节 > 16
            b"a" * 14 + b"\x02\x03",  # 填充内容不一致
        )
        for data in cases:
            with self.subTest(data=data):
                with self.assertRaises(CryptoError):
                    _aes._pkcs7_unpad(data)

    def test_cbc_decrypt_rejects_misaligned(self):
        key = bytes(range(_KEY_LEN))
        with self.assertRaises(CryptoError):
            _aes._cbc_decrypt(key, b"\x00" * _IV_LEN, b"a" * 15)

    def test_evp_bytes_to_key_lengths(self):
        key, iv = _aes._evp_bytes_to_key(b"pw", b"\x00" * SALT_LEN)
        self.assertEqual(len(key), _KEY_LEN)
        self.assertEqual(len(iv), _IV_LEN)

    def test_evp_bytes_to_key_matches_manual_md5(self):
        salt = b"12345678"
        expected = b""
        previous = b""
        while len(expected) < _KEY_LEN + _IV_LEN:
            previous = hashlib.md5(
                previous + b"pw" + salt, usedforsecurity=False
            ).digest()
            expected += previous
        self.assertEqual(
            _aes._evp_bytes_to_key(b"pw", salt),
            (expected[:_KEY_LEN], expected[_KEY_LEN:]),
        )


class TestStandardLibraryOnly(unittest.TestCase):
    """零运行时依赖：模块只能 import 标准库。"""

    def test_no_third_party_imports(self):
        tree = ast.parse(inspect.getsource(_aes))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertNotIn("Crypto", imported)
        allowed = {"__future__", "base64", "binascii", "hashlib", "secrets", "core"}
        self.assertEqual(imported - allowed, set())


@unittest.skipUnless(_HAVE_PYCRYPTODOME, "未安装 pycryptodome，跳过交叉验证")
class TestPycryptodomeCompat(unittest.TestCase):
    """与 pycryptodome（独立实现）互相验证。"""

    @staticmethod
    def _evp_md5(passphrase: bytes, salt: bytes) -> tuple[bytes, bytes]:
        derived = b""
        previous = b""
        while len(derived) < _KEY_LEN + _IV_LEN:
            previous = _CryptoMD5.new(previous + passphrase + salt).digest()
            derived += previous
        return derived[:_KEY_LEN], derived[_KEY_LEN:]

    def test_evp_bytes_to_key_matches_crypto(self):
        salt = bytes.fromhex("974f9447113f678f")
        self.assertEqual(
            _aes._evp_bytes_to_key(PASSPHRASE.encode(), salt),
            self._evp_md5(PASSPHRASE.encode(), salt),
        )

    def test_known_sample_decrypts_with_pycryptodome(self):
        salt, body = _split_salted(KNOWN_CIPHERTEXT)
        key, iv = self._evp_md5(PASSPHRASE.encode(), salt)
        cipher = _CryptoAES.new(key, _CryptoAES.MODE_CBC, iv)
        plaintext = _crypto_unpad(cipher.decrypt(body), _BLOCK)
        self.assertEqual(plaintext, KNOWN_PLAINTEXT.encode())

    def test_our_ciphertext_decrypts_with_pycryptodome(self):
        plaintext = "pycryptodome 交叉验证 😀"
        encoded = encrypt_aes(plaintext)
        salt, body = _split_salted(encoded)
        key, iv = self._evp_md5(PASSPHRASE.encode(), salt)
        cipher = _CryptoAES.new(key, _CryptoAES.MODE_CBC, iv)
        decrypted = _crypto_unpad(cipher.decrypt(body), _BLOCK)
        self.assertEqual(decrypted.decode("utf-8"), plaintext)

    def test_pycryptodome_ciphertext_decrypts_with_ours(self):
        plaintext = "CryptoJS 兼容性 🚀"
        salt = secrets.token_bytes(SALT_LEN)
        key, iv = self._evp_md5(PASSPHRASE.encode(), salt)
        cipher = _CryptoAES.new(key, _CryptoAES.MODE_CBC, iv)
        body = cipher.encrypt(_crypto_pad(plaintext.encode("utf-8"), _BLOCK))
        self.assertEqual(decrypt_aes(_craft(salt, body)), plaintext)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
