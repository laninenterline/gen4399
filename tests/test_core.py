"""gen4399 单元测试（只用标准库 unittest）。"""

import math
import unittest

from unittest import mock

from gen4399 import (
    CHARSET,
    DEFAULT_LENGTH,
    DEFAULT_USERNAME_LENGTH,
    MAX_LENGTH,
    MIN_LENGTH,
    USERNAME_CHARSET,
    USERNAME_MAX_LENGTH,
    USERNAME_MIN_LENGTH,
    GenerationError,
    InvalidFixedPartError,
    InvalidLengthError,
    InvalidPrefixError,
    InvalidSuffixError,
    Violation,
    check_fixed_part,
    validate_fixed_part,
    entropy_bits,
    generate,
    generate_many,
    generate_username,
    generate_usernames,
    is_valid,
    is_valid_username,
    validate,
    validate_username,
)


class TestValidate(unittest.TestCase):
    def test_valid_passwords(self):
        for pw in ("Abc12345", "aB3", "Xy9ZzZ", "a1" * 10):
            if len(pw) < MIN_LENGTH or len(pw) > MAX_LENGTH:
                continue
            with self.subTest(pw=pw):
                self.assertEqual(validate(pw), [])
                self.assertTrue(is_valid(pw))

    def test_length_bounds(self):
        self.assertIn("length", [v.code for v in validate("Ab1")])
        self.assertIn("length", [v.code for v in validate("Aa1" + "b" * 18)])

    def test_charset(self):
        codes = [v.code for v in validate("Abc 12345")]
        self.assertIn("charset", codes)
        codes = [v.code for v in validate("Abc_12345")]
        self.assertIn("charset", codes)
        codes = [v.code for v in validate("密码Abc123")]
        self.assertIn("charset", codes)

    def test_pure_digits(self):
        self.assertIn("all_digits", [v.code for v in validate("123456")])

    def test_pure_lower(self):
        self.assertIn("all_lower", [v.code for v in validate("abcdef")])

    def test_pure_upper(self):
        self.assertIn("all_upper", [v.code for v in validate("ABCDEF")])

    def test_violation_str(self):
        v = Violation("length", "测试消息")
        self.assertEqual(str(v), "测试消息")

    def test_type_error(self):
        with self.assertRaises(TypeError):
            validate(None)  # type: ignore[arg-type]


class TestGenerate(unittest.TestCase):
    def test_default(self):
        pw = generate()
        self.assertEqual(len(pw), DEFAULT_LENGTH)
        self.assertEqual(validate(pw), [])

    def test_lengths(self):
        for n in (MIN_LENGTH, 10, MAX_LENGTH):
            pw = generate(length=n)
            self.assertEqual(len(pw), n)
            self.assertEqual(validate(pw), [])

    def test_prefix(self):
        for prefix in ("", "lg", "4399abc", "123456", "abcdef", "ABC"):
            with self.subTest(prefix=prefix):
                pw = generate(length=MAX_LENGTH, prefix=prefix)
                self.assertTrue(pw.startswith(prefix))
                self.assertEqual(validate(pw), [])

    def test_invalid_prefix_charset(self):
        for bad in ("my_pwd", "我的", "ab-cd", "a b"):
            with self.subTest(bad=bad):
                with self.assertRaises(InvalidPrefixError):
                    generate(prefix=bad)

    def test_prefix_too_long(self):
        with self.assertRaises(InvalidLengthError):
            generate(length=16, prefix="a" * 16)

    def test_bad_length(self):
        for n in (5, 21, 0, -1):
            with self.subTest(n=n):
                with self.assertRaises(InvalidLengthError):
                    generate(length=n)

    def test_type_errors(self):
        with self.assertRaises(TypeError):
            generate(length="16")  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            generate(prefix=123)  # type: ignore[arg-type]

    def test_max_attempts_validation(self):
        with self.assertRaises(ValueError):
            generate(max_attempts=0)

    def test_batch_all_valid(self):
        for pw in generate_many(500):
            self.assertEqual(validate(pw), [])


class TestFixedPartAlias(unittest.TestCase):
    def test_validate_fixed_part_is_public(self):
        import gen4399.core as core

        self.assertIs(core.validate_fixed_part, core.check_fixed_part)
        validate_fixed_part("abc123", "prefix")


class TestGenerateMany(unittest.TestCase):
    def test_count(self):
        self.assertEqual(len(generate_many(7)), 7)

    def test_invalid_count(self):
        for c in (0, -3):
            with self.subTest(c=c):
                with self.assertRaises(ValueError):
                    generate_many(c)
        with self.assertRaises(TypeError):
            generate_many("3")  # type: ignore[arg-type]

    def test_prefix_preserved(self):
        for pw in generate_many(50, prefix="4399"):
            self.assertTrue(pw.startswith("4399"))
            self.assertEqual(validate(pw), [])

    def test_suffix_preserved(self):
        for pw in generate_many(50, suffix="gz"):
            self.assertTrue(pw.endswith("gz"))
            self.assertEqual(validate(pw), [])


class TestSuffix(unittest.TestCase):
    def test_suffix(self):
        for suffix in ("", "gz", "4399", "xyz123", "ABC"):
            with self.subTest(suffix=suffix):
                pw = generate(length=MAX_LENGTH, suffix=suffix)
                self.assertTrue(pw.endswith(suffix))
                self.assertEqual(len(pw), MAX_LENGTH)
                self.assertEqual(validate(pw), [])

    def test_prefix_and_suffix(self):
        for prefix, suffix in (("lg", "gz"), ("a", "z"), ("ab12", "cd34")):
            with self.subTest(prefix=prefix, suffix=suffix):
                pw = generate(length=MAX_LENGTH, prefix=prefix, suffix=suffix)
                self.assertTrue(pw.startswith(prefix))
                self.assertTrue(pw.endswith(suffix))
                self.assertEqual(len(pw), MAX_LENGTH)
                self.assertEqual(validate(pw), [])

    def test_invalid_suffix_charset(self):
        for bad in ("my_pwd", "我的", "ab-cd", "a b"):
            with self.subTest(bad=bad):
                with self.assertRaises(InvalidSuffixError):
                    generate(suffix=bad)

    def test_suffix_inherits_common_base(self):
        self.assertTrue(issubclass(InvalidSuffixError, InvalidFixedPartError))
        self.assertTrue(issubclass(InvalidPrefixError, InvalidFixedPartError))
        self.assertTrue(issubclass(InvalidFixedPartError, ValueError))

    def test_prefix_plus_suffix_too_long(self):
        with self.assertRaises(InvalidLengthError):
            generate(length=16, prefix="a" * 8, suffix="b" * 8)
        with self.assertRaises(InvalidLengthError):
            generate(length=16, prefix="a" * 10, suffix="b" * 10)

    def test_type_error(self):
        with self.assertRaises(TypeError):
            generate(suffix=123)  # type: ignore[arg-type]

    def test_batch_all_valid_with_suffix(self):
        for pw in generate_many(200, prefix="lg", suffix="gz"):
            self.assertTrue(pw.startswith("lg"))
            self.assertTrue(pw.endswith("gz"))
            self.assertEqual(validate(pw), [])


class TestCheckFixedPart(unittest.TestCase):
    def test_ok(self):
        check_fixed_part("abc123", "prefix")
        check_fixed_part("", "suffix")

    def test_invalid(self):
        with self.assertRaises(InvalidPrefixError):
            check_fixed_part("a_b", "prefix")
        with self.assertRaises(InvalidSuffixError):
            check_fixed_part("中", "suffix")

    def test_type_error(self):
        with self.assertRaises(TypeError):
            check_fixed_part(123, "prefix")  # type: ignore[arg-type]

    def test_private_alias_kept(self):
        import gen4399.core as core

        self.assertIs(core._check_fixed_part, core.check_fixed_part)


class TestCharset(unittest.TestCase):
    def test_password_custom_charset(self):
        for pw in generate_many(20, charset="abc123"):
            self.assertEqual(validate(pw), [])
            self.assertTrue(set(pw) <= set("abc123"))

    def test_password_charset_requires_letter_and_digit(self):
        for bad in ("123456789", "abcdefgh", "a_b1", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    generate(charset=bad)

    def test_password_charset_type(self):
        with self.assertRaises(TypeError):
            generate(charset=123)  # type: ignore[arg-type]

    def test_username_mixed_case_charset(self):
        name = generate_username(length=12, charset=CHARSET)
        self.assertEqual(validate_username(name), [])
        self.assertTrue(set(name) <= set(CHARSET))

    def test_username_invalid_charset(self):
        with self.assertRaises(ValueError):
            generate_username(charset="ab_12")


class TestUniqueBatch(unittest.TestCase):
    def test_password_batch_unique(self):
        items = generate_many(30, unique=True)
        self.assertEqual(len(items), 30)
        self.assertEqual(len(set(items)), 30)
        for pw in items:
            self.assertEqual(validate(pw), [])

    def test_username_batch_unique(self):
        items = generate_usernames(30, unique=True)
        self.assertEqual(len(items), 30)
        self.assertEqual(len(set(items)), 30)

    def test_unique_exhausted_raises(self):
        with mock.patch("gen4399.core.generate", return_value="Abc123"):
            with self.assertRaises(GenerationError):
                generate_many(2, unique=True)


class TestEntropy(unittest.TestCase):
    def test_value(self):
        self.assertAlmostEqual(entropy_bits(16), 16 * math.log2(62))

    def test_prefix_length(self):
        self.assertAlmostEqual(entropy_bits(16, 2), 14 * math.log2(62))

    def test_suffix_length(self):
        self.assertAlmostEqual(entropy_bits(16, 0, 2), 14 * math.log2(62))
        self.assertAlmostEqual(entropy_bits(20, 2, 3), 15 * math.log2(62))

    def test_negative(self):
        with self.assertRaises(InvalidLengthError):
            entropy_bits(10, 11)
        with self.assertRaises(InvalidLengthError):
            entropy_bits(10, 5, 6)
        with self.assertRaises(ValueError):
            entropy_bits(10, 0, -1)


class TestUsername(unittest.TestCase):
    def test_valid_usernames(self):
        for name in ("abc12345", "4257220954", "abcdef", "A1b2C3", "a" * 20):
            with self.subTest(name=name):
                self.assertEqual(validate_username(name), [])
                self.assertTrue(is_valid_username(name))

    def test_allows_pure_digits(self):
        # 4399 自动分配的账号就是纯数字，所以用户名允许纯数字
        self.assertEqual(validate_username("4257220954"), [])

    def test_length(self):
        self.assertEqual(
            [v.code for v in validate_username("a" * 5)], ["length"]
        )
        self.assertEqual(
            [v.code for v in validate_username("a" * 21)], ["length"]
        )
        for n in (USERNAME_MIN_LENGTH, USERNAME_MAX_LENGTH):
            self.assertEqual(validate_username("a" * n), [])

    def test_charset(self):
        for bad in ("abc_12345", "abc@12345", "账号abc123", "ab-cd-12", "ab cd 12"):
            with self.subTest(bad=bad):
                self.assertEqual(
                    [v.code for v in validate_username(bad)], ["charset"]
                )

    def test_type_error(self):
        with self.assertRaises(TypeError):
            validate_username(None)  # type: ignore[arg-type]


class TestGenerateUsername(unittest.TestCase):
    def test_default(self):
        name = generate_username()
        self.assertEqual(len(name), DEFAULT_USERNAME_LENGTH)
        self.assertEqual(validate_username(name), [])

    def test_lengths(self):
        for n in (USERNAME_MIN_LENGTH, 10, USERNAME_MAX_LENGTH):
            with self.subTest(n=n):
                name = generate_username(length=n)
                self.assertEqual(len(name), n)
                self.assertEqual(validate_username(name), [])

    def test_charset_is_lower_digits(self):
        for name in generate_usernames(200):
            self.assertTrue(
                all(c in USERNAME_CHARSET for c in name), name
            )

    def test_prefix_suffix(self):
        for prefix, suffix in (("u", ""), ("", "gz"), ("u", "gz")):
            with self.subTest(prefix=prefix, suffix=suffix):
                name = generate_username(
                    length=USERNAME_MAX_LENGTH, prefix=prefix, suffix=suffix
                )
                self.assertTrue(name.startswith(prefix))
                self.assertTrue(name.endswith(suffix))
                self.assertEqual(validate_username(name), [])

    def test_bad_length(self):
        for n in (USERNAME_MIN_LENGTH - 1, USERNAME_MAX_LENGTH + 1):
            with self.subTest(n=n):
                with self.assertRaises(InvalidLengthError):
                    generate_username(length=n)

    def test_invalid_prefix_suffix(self):
        with self.assertRaises(InvalidPrefixError):
            generate_username(prefix="u_")
        with self.assertRaises(InvalidSuffixError):
            generate_username(suffix="_u")

    def test_type_error(self):
        with self.assertRaises(TypeError):
            generate_username(prefix=1)  # type: ignore[arg-type]


class TestGenerateUsernames(unittest.TestCase):
    def test_count(self):
        self.assertEqual(len(generate_usernames(5)), 5)

    def test_batch_all_valid(self):
        for name in generate_usernames(500):
            self.assertEqual(validate_username(name), [])

    def test_invalid_count(self):
        with self.assertRaises(ValueError):
            generate_usernames(0)
        with self.assertRaises(TypeError):
            generate_usernames("3")  # type: ignore[arg-type]


class TestUsernameEntropy(unittest.TestCase):
    def test_username_charset_entropy(self):
        self.assertAlmostEqual(
            entropy_bits(12, charset_size=len(USERNAME_CHARSET)),
            12 * math.log2(36),
        )

    def test_invalid_charset_size(self):
        with self.assertRaises(ValueError):
            entropy_bits(12, charset_size=1)


if __name__ == "__main__":
    unittest.main()
