"""CLI `gen4399 login` 子命令测试。"""

import importlib
import contextlib
import io
import unittest
from unittest import mock

from gen4399 import cli
from gen4399.login import LoginResult


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class TestLoginCommand(unittest.TestCase):
    def test_success_exit_0(self):
        result = LoginResult(ok=True, kind="success", message="登录成功",
                             username="abc", cookies=("Pauth", "Uauth"))
        with mock.patch.object(importlib.import_module("gen4399.login"), "login", return_value=result):
            code, out, _ = run(["login", "abc", "--password", "pwd"])
        self.assertEqual(code, 0)
        self.assertIn("OK: 登录成功", out)
        self.assertIn("登录成功", out)

    def test_rejected_exit_1(self):
        result = LoginResult(ok=False, kind="rejected", message="密码错误",
                             username="abc")
        with mock.patch.object(importlib.import_module("gen4399.login"), "login", return_value=result):
            code, out, _ = run(["login", "abc", "--password", "pwd"])
        self.assertEqual(code, 1)
        self.assertIn("FAIL[rejected]", out)
        self.assertIn("密码错误", out)

    def test_json_output(self):
        result = LoginResult(ok=True, kind="success", message="ok",
                             username="abc", cookies=("Pauth",))
        with mock.patch.object(importlib.import_module("gen4399.login"), "login", return_value=result):
            code, out, _ = run(["login", "abc", "--password", "pwd", "--json"])
        self.assertEqual(code, 0)
        self.assertIn('"kind": "success"', out)
        self.assertIn("Pauth", out)

    def test_network_error_exit_2(self):
        from gen4399.remote import RemoteError

        with mock.patch("gen4399.login.login", side_effect=RemoteError("boom")):
            code, _, err = run(["login", "abc", "--password", "pwd"])
        self.assertEqual(code, 2)
        self.assertIn("错误", err)

    def test_password_prompt(self):
        result = LoginResult(ok=True, kind="success", message="ok", username="abc")
        with mock.patch.object(importlib.import_module("gen4399.login"), "login", return_value=result) as login_mock, \
             mock.patch("getpass.getpass", return_value="typed-pwd"):
            code, _, _ = run(["login", "abc"])
        self.assertEqual(code, 0)
        self.assertEqual(login_mock.call_args.args[1], "typed-pwd")

    def test_missing_password_eof_exit_2(self):
        with mock.patch("getpass.getpass", side_effect=EOFError):
            code, _, err = run(["login", "abc"])
        self.assertEqual(code, 2)
        self.assertIn("密码", err)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
