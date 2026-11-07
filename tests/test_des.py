"""gen4399._des 的单元测试：真实 JS 向量 + pycryptodome 交叉验证。"""

import ast
import pathlib
import unittest

from gen4399.core import Gen4399Error
from gen4399._des import DesError, encode_4399

try:
    from Crypto.Cipher import DES, DES3
    _HAS_CRYPTO = True
except ImportError:  # pragma: no cover - 环境缺 pycryptodome
    _HAS_CRYPTO = False

#: 从 4399 站点 action.js 的 encode_4399 提取的真实向量（node 执行得到）
JS_VECTORS = (
    ("Abc123456", "5c43e3", "0xfc88a0c93a204a36f741ec06e0e7db05"),
    ("zZ9aBcDe", "a0d178", "0x6dafb1f30c98ac2d"),
    ("abc123", "5c43e3", "0x0aeb285e9ebdec9a"),
    ("Aa1Bb2Cc3Dd4Ee5F", "012345",
     "0x08853d37ff8aa289fb911e5df01f4e75"),
    ("password1", "12345678", "0x8a65e0e80532b5fad1407e2836e3451f"),
    ("p", "abcdef", "0x83d2d480fb3f5f04"),
    ("A1b2C3d4", "0123456789abcdef", "0x5f7f0a3c852c28f8"),
)

#: FIPS 46-3 经典 DES 向量
FIPS_DES_KEY = bytes.fromhex("0123456789ABCDEF")
FIPS_DES_PLAIN = bytes.fromhex("4E6F772069732074")
FIPS_DES_CIPHER = bytes.fromhex("3FA40E8A984D4815")


def _pad8(data: bytes) -> bytes:
    remainder = len(data) % 8
    return data + b"\x00" * (8 - remainder) if remainder else data


def _quote_bytes(value: str) -> bytes:
    import urllib.parse
    return urllib.parse.quote(value, safe="!~*'()").encode("ascii")


class TestEncode4399Vectors(unittest.TestCase):
    def test_js_vectors(self):
        for value, key, expected in JS_VECTORS:
            with self.subTest(value=value, key=key):
                self.assertEqual(encode_4399(value, key), expected)

    def test_output_format(self):
        result = encode_4399("Abc123456", "5c43e3")
        self.assertTrue(result.startswith("0x"))
        self.assertEqual(result, result.lower())
        self.assertEqual(len(result) % 2, 0)

    def test_empty_value(self):
        self.assertEqual(encode_4399("", "abcdef"), "0x")

    def test_unicode_is_percent_encoded(self):
        # encodeURIComponent("密码") = %E5%AF%86%E7%A0%81，共 18 字节 -> 24 字节
        result = encode_4399("密码", "abcdef")
        self.assertEqual(len(result), 2 + 24 * 2)

    def test_key_lengths(self):
        # 8 字符 = DES；16/24 字符 = 3DES；6 字符 = 补 NUL 的 DES
        for key in ("abcdef", "12345678", "0123456789abcdef",
                    "0123456789abcdef01234567"):
            with self.subTest(key=key):
                self.assertTrue(encode_4399("Abc123456", key).startswith("0x"))


class TestPrimitives(unittest.TestCase):
    def test_des_fips_vector(self):
        from gen4399._des import _des_encrypt_block
        self.assertEqual(
            _des_encrypt_block(FIPS_DES_PLAIN, FIPS_DES_KEY), FIPS_DES_CIPHER
        )

    def test_key_schedule_length(self):
        from gen4399._des import _key_schedule
        self.assertEqual(len(_key_schedule(FIPS_DES_KEY)), 16)
        self.assertTrue(all(0 <= k < (1 << 48) for k in _key_schedule(FIPS_DES_KEY)))

    def test_bad_block_length(self):
        from gen4399._des import _des_encrypt_block
        with self.assertRaises(DesError):
            _des_encrypt_block(b"1234567", FIPS_DES_KEY)
        with self.assertRaises(DesError):
            _des_encrypt_block(b"12345678", b"1234567")

    def test_zero_pad(self):
        from gen4399._des import _zero_pad
        self.assertEqual(_zero_pad(b""), b"")
        self.assertEqual(_zero_pad(b"12345678"), b"12345678")
        self.assertEqual(_zero_pad(b"123"), b"123" + b"\x00" * 5)


@unittest.skipUnless(_HAS_CRYPTO, "未安装 pycryptodome")
class TestPyCryptodomeCrossCheck(unittest.TestCase):
    def test_six_char_key_is_null_padded_des(self):
        for value, key, expected in JS_VECTORS:
            with self.subTest(value=value, key=key):
                data = _pad8(_quote_bytes(value))
                if len(key) <= 8:
                    cipher = DES.new(
                        key.encode("ascii").ljust(8, b"\x00"), DES.MODE_ECB
                    )
                else:
                    cipher = DES3.new(
                        key.encode("ascii").ljust(24, b"\x00")[:24],
                        DES3.MODE_ECB,
                    )
                self.assertEqual("0x" + cipher.encrypt(data).hex(), expected)

    def test_random_roundtrip_shape(self):
        # 用随机 key/明文做形状/长度交叉验证（不比内容，内容由 JS 向量保证）
        import secrets
        for _ in range(5):
            key = secrets.token_hex(3)  # 6 字符
            value = "Ab1" + secrets.token_hex(4)
            out = encode_4399(value, key)
            blocks = (len(_quote_bytes(value)) + 7) // 8
            expected_len = 2 + blocks * 16
            self.assertEqual(len(out), expected_len)


class TestErrors(unittest.TestCase):
    def test_value_type(self):
        with self.assertRaises(TypeError):
            encode_4399(b"abc", "abcdef")  # type: ignore[arg-type]

    def test_key_type(self):
        with self.assertRaises(TypeError):
            encode_4399("abc", b"abcdef")  # type: ignore[arg-type]

    def test_empty_key(self):
        with self.assertRaises(ValueError):
            encode_4399("abc", "")

    def test_non_ascii_key(self):
        with self.assertRaises(DesError):
            encode_4399("abc", "密钥ab")

    def test_des_error_is_gen4399_error(self):
        self.assertTrue(issubclass(DesError, Gen4399Error))


class TestNoThirdPartyImport(unittest.TestCase):
    def test_source_only_stdlib(self):
        source = pathlib.Path("gen4399/_des.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
        for name in modules:
            top = name.split(".")[0]
            self.assertIn(
                top,
                {"urllib", "__future__", "core", "gen4399"},
                f"第三方 import: {name}",
            )


if __name__ == "__main__":
    unittest.main()
