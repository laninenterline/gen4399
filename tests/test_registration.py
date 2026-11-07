"""gen4399.registration 单元测试（网络层全部打桩）。"""

import unittest
from unittest import mock

from gen4399 import (
    InvalidProfileError,
    RegistrationError,
    RegistrationProfile,
    prepare_registration,
    validate,
    validate_username,
)
from gen4399.remote import UsernameAvailability

VALID_ID = "460206194611192084"
PROFILE = RegistrationProfile("张三", VALID_ID, qq="123456789")
AV = UsernameAvailability(username="x", available=True, message="0")


class TestPrepareOffline(unittest.TestCase):
    """verify_username=False，完全不联网。"""

    def test_basic(self):
        b = prepare_registration(PROFILE, verify_username=False)
        self.assertEqual(b.path, "web")
        self.assertEqual(b.url, "https://web.4399.com/user/reg.php")
        self.assertEqual(b.realname, "张三")
        self.assertEqual(b.idcard, VALID_ID)
        self.assertEqual(b.qq, "123456789")
        self.assertIsNone(b.username_available)
        self.assertEqual(validate_username(b.username), [])
        self.assertEqual(validate(b.password), [])

    def test_fields_complete(self):
        b = prepare_registration(PROFILE, verify_username=False)
        for key in ("cid", "login_name", "login_password", "relogin_pwd",
                    "qq", "true_name", "sfz", "agree"):
            self.assertIn(key, b.fields)
        self.assertEqual(b.fields["login_name"], b.username)
        self.assertEqual(b.fields["true_name"], "张三")
        self.assertEqual(b.fields["sfz"], VALID_ID)

    def test_warns_no_verify(self):
        b = prepare_registration(PROFILE, verify_username=False)
        self.assertTrue(any("未做在线查重" in w for w in b.warnings))
        self.assertTrue(any("https" in w for w in b.warnings))

    def test_unified_path(self):
        b = prepare_registration(PROFILE, path="unified", verify_username=False)
        self.assertEqual(b.path, "unified")
        self.assertIn("username", b.fields)
        self.assertIn("realname", b.fields)
        self.assertIn("idcard", b.fields)
        self.assertTrue(any("6~20" in w for w in b.warnings))

    def test_unknown_path(self):
        with self.assertRaises(ValueError):
            prepare_registration(PROFILE, path="phone", verify_username=False)

    def test_invalid_profile(self):
        bad = RegistrationProfile("张", "bad")
        with self.assertRaises(InvalidProfileError):
            prepare_registration(bad, verify_username=False)

    def test_bad_profile_type(self):
        with self.assertRaises(TypeError):
            prepare_registration("x", verify_username=False)  # type: ignore[arg-type]

    def test_masking(self):
        b = prepare_registration(PROFILE, verify_username=False)
        masked = b.masked_fields()
        self.assertNotIn(VALID_ID, masked["sfz"])
        self.assertTrue(set(masked["login_password"]) == {"*"})
        text = b.as_text()
        self.assertNotIn(VALID_ID, text)
        self.assertNotIn(b.password, text)

    def test_as_text_show_pii(self):
        b = prepare_registration(PROFILE, verify_username=False)
        text = b.as_text(show_pii=True)
        self.assertIn(VALID_ID, text)
        self.assertIn(b.password, text)


class TestPrepareOnline(unittest.TestCase):
    """verify_username=True，打桩远程调用。"""

    @mock.patch("gen4399.registration.generate_available_username",
                return_value="abc123456")
    def test_generated_username(self, gen):
        b = prepare_registration(PROFILE)
        self.assertEqual(b.username, "abc123456")
        self.assertTrue(b.username_available)
        gen.assert_called_once()

    @mock.patch("gen4399.registration.check_username", return_value=AV)
    def test_explicit_username_ok(self, chk):
        b = prepare_registration(PROFILE, username="myname12345")
        self.assertEqual(b.username, "myname12345")
        self.assertTrue(b.username_available)
        chk.assert_called_once()

    @mock.patch(
        "gen4399.registration.check_username",
        return_value=UsernameAvailability(
            username="x", available=False, message="用户名已被注册"
        ),
    )
    def test_explicit_username_taken(self, chk):
        with self.assertRaises(RegistrationError) as ctx:
            prepare_registration(PROFILE, username="taken12345")
        self.assertIn("不可用", str(ctx.exception))

    @mock.patch("gen4399.registration.generate_available_username",
                return_value="abc123456")
    def test_lengths_respected(self, gen):
        b = prepare_registration(PROFILE, password_length=20)
        self.assertEqual(len(b.password), 20)
        gen.assert_called_once()


class TestBundle(unittest.TestCase):
    def test_frozen(self):
        b = prepare_registration(PROFILE, verify_username=False)
        with self.assertRaises(Exception):
            b.username = "x"  # type: ignore[misc]

    def test_masked_idcard(self):
        b = prepare_registration(PROFILE, verify_username=False)
        self.assertTrue(b.masked_idcard().startswith("460206"))
        self.assertNotEqual(b.masked_idcard(), VALID_ID)


class TestPreparePrefixSuffix(unittest.TestCase):
    def test_offline_prefix_suffix(self):
        for pfx, sfx in (("u", ""), ("", "gz"), ("u", "gz")):
            with self.subTest(prefix=pfx, suffix=sfx):
                b = prepare_registration(
                    PROFILE, prefix=pfx, suffix=sfx, verify_username=False
                )
                self.assertTrue(b.username.startswith(pfx))
                self.assertTrue(b.username.endswith(sfx))
                self.assertEqual(len(b.username), 12)

    def test_offline_prefix_suffix_length(self):
        b = prepare_registration(
            PROFILE, username_length=20, prefix="u", suffix="gz",
            verify_username=False,
        )
        self.assertEqual(len(b.username), 20)
        self.assertTrue(b.username.startswith("u"))
        self.assertTrue(b.username.endswith("gz"))

    @mock.patch("gen4399.registration.generate_available_username",
                return_value="uabc123gz")
    def test_online_prefix_suffix_passed_through(self, gen):
        b = prepare_registration(PROFILE, prefix="u", suffix="gz")
        gen.assert_called_once()
        kwargs = gen.call_args.kwargs
        self.assertEqual(kwargs["prefix"], "u")
        self.assertEqual(kwargs["suffix"], "gz")
        self.assertTrue(b.username.startswith("u"))
        self.assertTrue(b.username.endswith("gz"))

    def test_conflict_with_explicit_username(self):
        with self.assertRaises(ValueError):
            prepare_registration(PROFILE, username="abc12345", prefix="u",
                                 verify_username=False)
        with self.assertRaises(ValueError):
            prepare_registration(PROFILE, username="abc12345", suffix="gz",
                                 verify_username=False)

    def test_prefix_too_long(self):
        with self.assertRaises(Exception):
            prepare_registration(
                PROFILE, prefix="a" * 12, verify_username=False
            )

    def test_fields_use_prefixed_username(self):
        b = prepare_registration(
            PROFILE, prefix="u", suffix="gz", verify_username=False
        )
        self.assertEqual(b.fields["login_name"], b.username)


if __name__ == "__main__":
    unittest.main()
