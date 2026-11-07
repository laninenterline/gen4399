"""gen4399.forms 单元测试（纯本地，不联网）。"""

import unittest

from gen4399.forms import (
    FORMS,
    InvalidProfileError,
    RegistrationProfile,
    build_registration_fields,
    UNIFIED_FORM,
    WEB_USERNAME_FORM,
    check_registration_form,
    get_form,
    validate_idcard,
    validate_qq,
    validate_realname,
)

# 4399 validation.js 里出现过的示例值
VALID_ID = "460206194611192084"
VALID_ID_2 = "440106198101010155"


class TestFormDefinitions(unittest.TestCase):
    def test_paths(self):
        self.assertEqual(set(FORMS), {"web", "unified"})

    def test_get_form(self):
        self.assertIs(get_form("web"), WEB_USERNAME_FORM)
        self.assertIs(get_form("unified"), UNIFIED_FORM)

    def test_unknown_path(self):
        with self.assertRaises(ValueError):
            get_form("phone")

    def test_web_fields(self):
        names = [f.name for f in WEB_USERNAME_FORM.fields]
        for n in ("login_name", "login_password", "relogin_pwd",
                  "qq", "true_name", "sfz", "agree", "cid"):
            self.assertIn(n, names)
        # 页面把 email 注释掉了，不应出现
        self.assertNotIn("email", names)

    def test_unified_fields(self):
        names = [f.name for f in UNIFIED_FORM.fields]
        for n in ("username", "password", "passwordveri", "email",
                  "realname", "idcard", "reg_eula_agree"):
            self.assertIn(n, names)

    def test_required_flags(self):
        req = {f.name for f in WEB_USERNAME_FORM.fields if f.required}
        self.assertEqual(req, {"login_name", "login_password", "relogin_pwd",
                               "true_name", "sfz", "agree"})

    def test_submit_urls(self):
        self.assertEqual(WEB_USERNAME_FORM.submit_url, "/user/?_c=reg")
        self.assertEqual(UNIFIED_FORM.submit_url, "/ptlogin/register.do")


class TestRealname(unittest.TestCase):
    def test_ok(self):
        for v in ("汤十甚", "张三", "John Smith", "欧阳娜娜"):
            with self.subTest(v=v):
                self.assertEqual(validate_realname(v), [])

    def test_bad(self):
        for v in ("", "  ", "张", "A", "123", "张 三"):
            with self.subTest(v=v):
                self.assertTrue(validate_realname(v))

    def test_fullwidth_space_stripped(self):
        self.assertEqual(validate_realname("张三\u3000"), [])

    def test_type_error(self):
        with self.assertRaises(TypeError):
            validate_realname(None)  # type: ignore[arg-type]


class TestIdcard(unittest.TestCase):
    def test_valid_examples_from_4399_js(self):
        self.assertEqual(validate_idcard(VALID_ID), [])
        self.assertEqual(validate_idcard(VALID_ID_2), [])

    def test_lowercase_x(self):
        # 校验码为 X 的号，小写也应接受
        self.assertEqual(validate_idcard("11010119900101004X"), [])
        self.assertEqual(validate_idcard("11010119900101004x"), [])

    def test_fifteen_digits_rejected(self):
        msgs = validate_idcard("110101900101123")
        self.assertTrue(any("15" in m for m in msgs))

    def test_bad_checksum(self):
        msgs = validate_idcard("110101199001011234")
        self.assertTrue(any("校验码" in m for m in msgs))

    def test_bad_date(self):
        msgs = validate_idcard("110101199002301234")
        self.assertTrue(any("出生日期" in m for m in msgs))

    def test_format(self):
        for v in ("", "abc", "11010119900101123", "11010119900101123X"):
            with self.subTest(v=v):
                self.assertTrue(validate_idcard(v))

    def test_type_error(self):
        with self.assertRaises(TypeError):
            validate_idcard(123)  # type: ignore[arg-type]


class TestQQ(unittest.TestCase):
    def test_ok(self):
        for v in ("1234", "123456789", "12345678901", ""):
            with self.subTest(v=v):
                self.assertEqual(validate_qq(v), [])

    def test_bad(self):
        for v in ("123", "123456789012", "abcdef", "12 345"):
            with self.subTest(v=v):
                self.assertTrue(validate_qq(v))

    def test_whitespace_is_stripped(self):
        for v in (" 123456789", "123456789 ", "123456789\n", "\t123456789\t"):
            with self.subTest(v=v):
                self.assertEqual(validate_qq(v), [])


class TestCheckRegistrationForm(unittest.TestCase):
    def test_all_ok(self):
        res = check_registration_form(
            "abc12345", "Abc123456",
            realname="张三", idcard=VALID_ID, qq="123456789",
        )
        self.assertTrue(res.ok)
        self.assertTrue(res)
        self.assertEqual(res.errors, {})

    def test_bad_username_and_password(self):
        res = check_registration_form(
            "ab", "123", realname="张三", idcard=VALID_ID
        )
        self.assertFalse(res.ok)
        self.assertIn("username", res.errors)
        self.assertIn("password", res.errors)

    def test_password_mismatch(self):
        res = check_registration_form(
            "abc12345", "Abc123456", password_confirm="Other123",
            realname="张三", idcard=VALID_ID,
        )
        self.assertIn("password_confirm", res.errors)

    def test_missing_realname_idcard(self):
        res = check_registration_form("abc12345", "Abc123456")
        self.assertIn("realname", res.errors)
        self.assertIn("idcard", res.errors)

    def test_unified_path_warns(self):
        res = check_registration_form(
            "abc12345", "Abc123456",
            path="unified", realname="张三", idcard=VALID_ID,
        )
        self.assertTrue(res.ok)
        self.assertTrue(any("6~20" in w for w in res.warnings))

    def test_unknown_path(self):
        with self.assertRaises(ValueError):
            check_registration_form(
                "abc12345", "Abc123456", path="foo",
                realname="张三", idcard=VALID_ID,
            )

    def test_messages_flattened(self):
        res = check_registration_form("ab", "123", realname="张", idcard="bad")
        msgs = res.messages()
        self.assertTrue(all(":" in m for m in msgs))
        self.assertGreaterEqual(len(msgs), 3)


class TestRegistrationProfile(unittest.TestCase):
    def test_valid(self):
        p = RegistrationProfile("张三", VALID_ID, qq="123456789")
        self.assertTrue(p.is_valid())
        self.assertEqual(p.errors(), {})
        self.assertIs(p.require_valid(), p)

    def test_invalid(self):
        p = RegistrationProfile("张", "110101199001011234")
        self.assertFalse(p.is_valid())
        self.assertIn("realname", p.errors())
        self.assertIn("idcard", p.errors())
        with self.assertRaises(InvalidProfileError):
            p.require_valid()

    def test_type_errors(self):
        with self.assertRaises(TypeError):
            RegistrationProfile(123, VALID_ID)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            RegistrationProfile("张三", 123)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            RegistrationProfile("张三", VALID_ID, qq=123)  # type: ignore[arg-type]

    def test_masked_idcard(self):
        p = RegistrationProfile("张三", VALID_ID)
        masked = p.masked_idcard()
        self.assertNotIn(VALID_ID, masked)
        self.assertTrue(masked.startswith(VALID_ID[:6]))
        self.assertTrue(masked.endswith(VALID_ID[-4:]))

    def test_masked(self):
        p = RegistrationProfile("张三", VALID_ID, qq="123456789")
        text = p.masked()
        self.assertNotIn(VALID_ID, text)
        self.assertNotIn("123456789", text)

    def test_qq_optional(self):
        self.assertTrue(RegistrationProfile("张三", VALID_ID).is_valid())


class TestBuildRegistrationFields(unittest.TestCase):
    def setUp(self):
        self.p = RegistrationProfile("张三", VALID_ID, qq="123456789")

    def test_web_fields(self):
        f = build_registration_fields("abc12345", "Abc123456", profile=self.p)
        self.assertEqual(f["login_name"], "abc12345")
        self.assertEqual(f["login_password"], "Abc123456")
        self.assertEqual(f["relogin_pwd"], "Abc123456")
        self.assertEqual(f["qq"], "123456789")
        self.assertEqual(f["true_name"], "张三")
        self.assertEqual(f["sfz"], VALID_ID)
        self.assertEqual(f["agree"], "on")
        self.assertEqual(f["cid"], "3000")

    def test_unified_fields(self):
        f = build_registration_fields(
            "abc12345", "Abc123456", path="unified", profile=self.p
        )
        self.assertEqual(f["username"], "abc12345")
        self.assertEqual(f["realname"], "张三")
        self.assertEqual(f["idcard"], VALID_ID)
        self.assertEqual(f["email"], "123456789")
        self.assertEqual(f["regMode"], "reg_normal")
        self.assertEqual(f["appId"], "u4399")

    def test_explicit_values_override_profile(self):
        f = build_registration_fields(
            "abc12345", "Abc123456",
            profile=self.p, realname="李四", idcard=VALID_ID_2, qq="987654321",
        )
        self.assertEqual(f["true_name"], "李四")
        self.assertEqual(f["sfz"], VALID_ID_2)
        self.assertEqual(f["qq"], "987654321")

    def test_password_confirm(self):
        f = build_registration_fields(
            "abc12345", "Abc123456", password_confirm="Other123", profile=self.p
        )
        self.assertEqual(f["relogin_pwd"], "Other123")

    def test_unknown_path(self):
        with self.assertRaises(ValueError):
            build_registration_fields("abc12345", "Abc123456", path="x",
                                      profile=self.p)

    def test_bad_profile_type(self):
        with self.assertRaises(TypeError):
            build_registration_fields("abc12345", "Abc123456", profile="x")  # type: ignore[arg-type]


class TestCheckFormWithProfile(unittest.TestCase):
    def test_profile_ok(self):
        p = RegistrationProfile("张三", VALID_ID, qq="123456789")
        res = check_registration_form("abc12345", "Abc123456", profile=p)
        self.assertTrue(res.ok)

    def test_profile_bad(self):
        p = RegistrationProfile("张", "bad")
        res = check_registration_form("abc12345", "Abc123456", profile=p)
        self.assertFalse(res.ok)
        self.assertIn("realname", res.errors)
        self.assertIn("idcard", res.errors)

    def test_profile_bad_type(self):
        with self.assertRaises(TypeError):
            check_registration_form("abc12345", "Abc123456", profile="x")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
