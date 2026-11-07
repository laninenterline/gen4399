"""gen4399.remote 单元测试（网络全部打桩，不真的发请求）。"""

import unittest
from unittest import mock

from gen4399 import (
    InvalidLengthError,
    InvalidPrefixError,
    InvalidSuffixError,
    validate,
    validate_username,
)
from gen4399.remote import UsernameAvailability
from gen4399.remote import (
    RemoteError,
    RemoteParseError,
    RemoteTimeoutError,
    UsernameAvailability,
    _parse_suggested_username,
    check_username,
    fetch_suggested_username,
    fetch_suggested_usernames,
    generate_account,
    generate_available_username,
    is_username_available,
)

HTML_WITH_NAME = '''
<div>
  <input type="text" autocomplete="off" id="j-username"
         name="username"
         value="4257237567"
         checkstate="err" class="login_ipt iptw2" />
</div>
'''

HTML_EMPTY_NAME = '''
<div>
  <input type="text" autocomplete="off" id="j-username"
         name="username"
         value=""
         checkstate="err" class="login_ipt iptw2" />
</div>
'''

HTML_NO_INPUT = "<div>something changed</div>"


class TestParse(unittest.TestCase):
    def test_parse_ok(self):
        self.assertEqual(_parse_suggested_username(HTML_WITH_NAME), "4257237567")

    def test_parse_empty(self):
        self.assertEqual(_parse_suggested_username(HTML_EMPTY_NAME), "")

    def test_parse_missing(self):
        with self.assertRaises(RemoteParseError):
            _parse_suggested_username(HTML_NO_INPUT)


class TestFetchSuggestedUsername(unittest.TestCase):
    @mock.patch("gen4399.remote._http_get", return_value=HTML_WITH_NAME)
    def test_ok(self, _get):
        self.assertEqual(fetch_suggested_username(retries=1), "4257237567")
        self.assertEqual(_get.call_count, 1)

    @mock.patch("gen4399.remote._http_get", return_value=HTML_EMPTY_NAME)
    def test_empty_raises(self, _get):
        with self.assertRaises(RemoteParseError) as ctx:
            fetch_suggested_username(retries=2, retry_delay=0)
        self.assertIn("频率限制", str(ctx.exception))
        self.assertEqual(_get.call_count, 2)

    @mock.patch("gen4399.remote._http_get")
    def test_retry_then_ok(self, _get):
        _get.side_effect = [HTML_EMPTY_NAME, HTML_WITH_NAME]
        self.assertEqual(
            fetch_suggested_username(retries=3, retry_delay=0), "4257237567"
        )

    @mock.patch("gen4399.remote._http_get", return_value=HTML_NO_INPUT)
    def test_missing_input_raises(self, _get):
        with self.assertRaises(RemoteParseError):
            fetch_suggested_username(retries=1)

    @mock.patch(
        "gen4399.remote._http_get",
        return_value='<input id="j-username" value="ab">',
    )
    def test_bad_format_raises(self, _get):
        with self.assertRaises(RemoteParseError):
            fetch_suggested_username(retries=2, retry_delay=0)

    @mock.patch(
        "gen4399.remote._http_get",
        side_effect=RemoteTimeoutError("请求超时（10s）"),
    )
    def test_timeout_propagates(self, _get):
        with self.assertRaises(RemoteTimeoutError):
            fetch_suggested_username()

    @mock.patch("gen4399.remote._http_get", return_value=HTML_EMPTY_NAME)
    def test_fallback_to_local(self, _get):
        from gen4399 import validate_username
        name = fetch_suggested_username(
            retries=1, retry_delay=0, fallback_to_local=True
        )
        self.assertEqual(validate_username(name), [])

    def test_url_contains_params(self):
        with mock.patch(
            "gen4399.remote._http_get", return_value=HTML_WITH_NAME
        ) as _get:
            fetch_suggested_username(app_id="custom_id", level=6, retries=1)
            url = _get.call_args[0][0]
            self.assertIn("appId=custom_id", url)
            self.assertIn("level=6", url)
            self.assertIn("regMode=reg_normal", url)


class TestRemotePrefixSuffix(unittest.TestCase):
    @mock.patch("gen4399.remote._http_get", return_value=HTML_WITH_NAME)
    def test_prefix(self, _get):
        name = fetch_suggested_username(prefix="u", retries=1)
        self.assertEqual(name, "u4257237567")
        self.assertEqual(validate_username(name), [])

    @mock.patch("gen4399.remote._http_get", return_value=HTML_WITH_NAME)
    def test_suffix(self, _get):
        name = fetch_suggested_username(suffix="gz", retries=1)
        self.assertEqual(name, "4257237567gz")

    @mock.patch("gen4399.remote._http_get", return_value=HTML_WITH_NAME)
    def test_prefix_and_suffix(self, _get):
        name = fetch_suggested_username(prefix="u", suffix="gz", retries=1)
        self.assertEqual(name, "u4257237567gz")
        self.assertEqual(len(name), 13)

    @mock.patch("gen4399.remote._http_get", return_value=HTML_WITH_NAME)
    def test_invalid_prefix(self, _get):
        with self.assertRaises(InvalidPrefixError):
            fetch_suggested_username(prefix="u_", retries=1)

    @mock.patch("gen4399.remote._http_get", return_value=HTML_WITH_NAME)
    def test_invalid_suffix(self, _get):
        with self.assertRaises(InvalidSuffixError):
            fetch_suggested_username(suffix="_u", retries=1)

    @mock.patch("gen4399.remote._http_get", return_value=HTML_WITH_NAME)
    def test_too_long(self, _get):
        # 10 位账号 + 11 位前缀 = 21 位，超过 4399 上限
        with self.assertRaises(InvalidLengthError):
            fetch_suggested_username(prefix="a" * 11, retries=1)

    @mock.patch("gen4399.remote._http_get", return_value=HTML_EMPTY_NAME)
    def test_fallback_with_prefix_suffix(self, _get):
        name = fetch_suggested_username(
            retries=1, retry_delay=0, fallback_to_local=True,
            prefix="u", suffix="gz",
        )
        self.assertTrue(name.startswith("u"))
        self.assertTrue(name.endswith("gz"))
        self.assertEqual(validate_username(name), [])

    @mock.patch("gen4399.remote._http_get", return_value=HTML_WITH_NAME)
    def test_batch_prefix_suffix(self, _get):
        names = fetch_suggested_usernames(2, prefix="u", suffix="gz", unique=False)
        self.assertEqual(names, ["u4257237567gz"] * 2)


class TestFetchSuggestedUsernames(unittest.TestCase):
    @mock.patch("gen4399.remote._http_get", return_value=HTML_WITH_NAME)
    def test_unique_filters_duplicates(self, _get):
        names = fetch_suggested_usernames(3, unique=True)
        self.assertEqual(names, ["4257237567"])

    @mock.patch("gen4399.remote._http_get", return_value=HTML_WITH_NAME)
    def test_unique_false_keeps_duplicates(self, _get):
        names = fetch_suggested_usernames(3, unique=False)
        self.assertEqual(names, ["4257237567"] * 3)

    def test_invalid_count(self):
        with self.assertRaises(ValueError):
            fetch_suggested_usernames(0)
        with self.assertRaises(TypeError):
            fetch_suggested_usernames("2")  # type: ignore[arg-type]


class TestCheckUsername(unittest.TestCase):
    def test_available(self):
        with mock.patch("gen4399.remote._http_get", return_value="0"):
            res = check_username("abc12345")
        self.assertIsInstance(res, UsernameAvailability)
        self.assertTrue(res.available)
        self.assertTrue(res)          # __bool__
        self.assertEqual(res.message, "0")

    def test_taken(self):
        with mock.patch("gen4399.remote._http_get", return_value="用户名已被注册"):
            res = check_username("test123456")
        self.assertFalse(res.available)
        self.assertFalse(res)
        self.assertEqual(res.message, "用户名已被注册")

    def test_sensitive(self):
        with mock.patch(
            "gen4399.remote._http_get", return_value="用户名包含敏感字符"
        ):
            self.assertFalse(is_username_available("admin123"))

    def test_strips_whitespace(self):
        with mock.patch("gen4399.remote._http_get", return_value=" 0\n"):
            self.assertTrue(check_username("abc12345").available)

    def test_url_contains_username(self):
        with mock.patch("gen4399.remote._http_get", return_value="0") as _get:
            check_username("abc12345")
            url = _get.call_args[0][0]
            self.assertIn("username=abc12345", url)
            self.assertIn("appId=u4399", url)

    def test_type_error(self):
        with self.assertRaises(TypeError):
            check_username(123)  # type: ignore[arg-type]


class TestErrorTypes(unittest.TestCase):
    def test_hierarchy(self):
        self.assertTrue(issubclass(RemoteTimeoutError, RemoteError))
        self.assertTrue(issubclass(RemoteParseError, RemoteError))


def _avail(name, ok, msg="0"):
    return UsernameAvailability(username=name, available=ok, message=msg)


class TestVerifyAvailable(unittest.TestCase):
    @mock.patch("gen4399.remote.check_username",
                return_value=_avail("x", True))
    @mock.patch("gen4399.remote._http_get", return_value=HTML_WITH_NAME)
    def test_fetch_verify_ok(self, _get, _chk):
        self.assertEqual(
            fetch_suggested_username(verify_available=True, retries=1),
            "4257237567",
        )
        _chk.assert_called_once()

    @mock.patch("gen4399.remote.check_username",
                return_value=_avail("x", False, "用户名已被注册"))
    @mock.patch("gen4399.remote._http_get", return_value=HTML_WITH_NAME)
    def test_fetch_verify_taken_raises(self, _get, _chk):
        with self.assertRaises(Exception) as ctx:
            fetch_suggested_username(
                verify_available=True, retries=2, retry_delay=0
            )
        self.assertIn("已被占用", str(ctx.exception))
        self.assertEqual(_chk.call_count, 2)

    @mock.patch("gen4399.remote.check_username",
                return_value=_avail("x", True))
    def test_generate_available_local(self, _chk):
        name = generate_available_username()
        self.assertEqual(validate_username(name), [])
        _chk.assert_called_once()

    @mock.patch("gen4399.remote.check_username")
    def test_generate_available_retries(self, _chk):
        _chk.side_effect = [
            _avail("a", False, "用户名已被注册"),
            _avail("b", True),
        ]
        name = generate_available_username()
        self.assertEqual(validate_username(name), [])
        self.assertEqual(_chk.call_count, 2)

    @mock.patch("gen4399.remote.check_username",
                return_value=_avail("x", False, "用户名已被注册"))
    def test_generate_available_exhausted(self, _chk):
        with self.assertRaises(Exception) as ctx:
            generate_available_username(max_attempts=3)
        self.assertIn("连续 3", str(ctx.exception))

    @mock.patch("gen4399.remote.check_username",
                return_value=_avail("x", True))
    def test_generate_account_verify(self, _chk):
        acc = generate_account()
        self.assertEqual(validate_username(acc.username), [])
        self.assertEqual(validate(acc.password), [])
        self.assertTrue(acc.username_available)

    @mock.patch("gen4399.remote.check_username",
                return_value=_avail("x", True))
    def test_generate_account_no_verify(self, _chk):
        acc = generate_account(verify_username=False)
        self.assertIsNone(acc.username_available)
        _chk.assert_not_called()

    @mock.patch("gen4399.remote.check_username",
                return_value=_avail("x", False, "用户名已被注册"))
    def test_generate_account_explicit_taken(self, _chk):
        with self.assertRaises(Exception) as ctx:
            generate_account(username="taken12345")
        self.assertIn("不可用", str(ctx.exception))

    @mock.patch("gen4399.remote.check_username",
                return_value=_avail("x", True))
    def test_generate_account_explicit_ok(self, _chk):
        acc = generate_account(username="free123456", verify_username=True)
        self.assertEqual(acc.username, "free123456")
        self.assertEqual(validate(acc.password), [])


if __name__ == "__main__":
    unittest.main()
