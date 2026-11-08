"""scripts/make_account.py 的验证码参数透传测试：全部离线、不联网、不建号。

覆盖 2.3.0 新增的 ``--captcha-prompt / --captcha-cmd / --captcha-dir /
--captcha-attempts``：

* 参数解析（默认值 / 显式值 / 类型错误）；
* ``make_solver`` 的组合结果原样传给 ``submit_registration(captcha=...)``，
  轮数传给 ``captcha_attempts=...``；
* ``make_solver`` 抛 ``OSError`` / ``CaptchaSolverError`` → 退出码 2；
* ``--captcha-attempts 0/-1`` 不 mock 提交层，由库内真实校验抛
  ``ValueError`` → 退出码 2、无 traceback。

不改动 ``tests/test_make_account.py`` 与 ``test_make_account_e2e.py``。
"""

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType
from unittest import mock

import scripts.make_account as make_account

from gen4399 import CaptchaSolverError
from gen4399.registration import RegistrationBundle
from gen4399.submit import SubmitResult

VALID_ID = "460206194611192084"


def _bundle() -> RegistrationBundle:
    return RegistrationBundle(
        path="unified",
        url="https://u.4399.com/register.html",
        username="abc12345",
        password="Abc123456",
        realname="张三",
        idcard=VALID_ID,
        qq=None,
        fields=MappingProxyType({"username": "abc12345"}),
    )


def _dry_run_result() -> SubmitResult:
    return SubmitResult(
        ok=False,
        kind="dry_run",
        message="dry-run：未发送 POST",
        username="abc12345",
        path="unified",
        app_id="u4399",
        endpoint="https://ptlogin.4399.com/ptlogin/register.do",
        http_status=None,
        encrypted_fields=("password",),
        field_names=("username", "password"),
        dry_run=True,
    )


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = make_account.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class TestCaptchaParser(unittest.TestCase):
    """--captcha-* 四个参数的解析。"""

    def test_defaults(self):
        args = make_account._build_parser().parse_args([])
        self.assertFalse(args.captcha_prompt)
        self.assertIsNone(args.captcha_cmd)
        self.assertIsNone(args.captcha_dir)
        self.assertEqual(args.captcha_attempts, 3)

    def test_explicit_flags(self):
        args = make_account._build_parser().parse_args([
            "--captcha-prompt",
            "--captcha-cmd", "tesseract stdin stdout",
            "--captcha-dir", "caps",
            "--captcha-attempts", "5",
        ])
        self.assertTrue(args.captcha_prompt)
        self.assertEqual(args.captcha_cmd, "tesseract stdin stdout")
        self.assertEqual(args.captcha_dir, "caps")
        self.assertEqual(args.captcha_attempts, 5)

    def test_attempts_must_be_int(self):
        with self.assertRaises(SystemExit) as ctx:
            with contextlib.redirect_stderr(io.StringIO()):
                make_account._build_parser().parse_args(
                    ["--captcha-attempts", "abc"]
                )
        self.assertEqual(ctx.exception.code, 2)


class TestCaptchaWiring(unittest.TestCase):
    """make_solver 的结果与 --captcha-attempts 必须透传给提交层。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self.old_cwd)
        Path("sfz.txt").write_text("张三|" + VALID_ID + "\n", encoding="utf-8")

        p1 = mock.patch.object(
            make_account, "prepare_registration", return_value=_bundle()
        )
        self.prepare = p1.start()
        self.addCleanup(p1.stop)
        p2 = mock.patch.object(
            make_account, "submit_registration",
            return_value=_dry_run_result(),
        )
        self.submit = p2.start()
        self.addCleanup(p2.stop)
        p3 = mock.patch.object(make_account, "make_solver", return_value=None)
        self.make_solver = p3.start()
        self.addCleanup(p3.stop)
        self.solver = mock.Mock()

    def test_defaults_pass_none_and_three(self):
        code, _, _ = run([])
        self.assertEqual(code, 0)
        self.make_solver.assert_called_once_with(
            prompt=False, command=None, directory=None, auto=False, matcher=False, zoom=1
        )
        kwargs = self.submit.call_args.kwargs
        self.assertIsNone(kwargs["captcha"])
        self.assertEqual(kwargs["captcha_attempts"], 3)

    def test_prompt_and_dir_wired(self):
        self.make_solver.return_value = self.solver
        code, _, _ = run([
            "--captcha-prompt",
            "--captcha-dir", "/tmp/caps",
            "--captcha-attempts", "5",
        ])
        self.assertEqual(code, 0)
        self.make_solver.assert_called_once_with(
            prompt=True, command=None, directory="/tmp/caps", auto=False, matcher=False, zoom=1
        )
        kwargs = self.submit.call_args.kwargs
        self.assertIs(kwargs["captcha"], self.solver)
        self.assertEqual(kwargs["captcha_attempts"], 5)

    def test_command_wired(self):
        self.make_solver.return_value = self.solver
        code, _, _ = run(["--captcha-cmd", "echo hi"])
        self.assertEqual(code, 0)
        self.make_solver.assert_called_once_with(
            prompt=False, command="echo hi", directory=None, auto=False, matcher=False, zoom=1
        )
        kwargs = self.submit.call_args.kwargs
        self.assertIs(kwargs["captcha"], self.solver)
        self.assertEqual(kwargs["captcha_attempts"], 3)

    def test_solver_oserror_exit_2(self):
        self.make_solver.side_effect = OSError("目录不可写")
        code, _, err = run([])
        self.assertEqual(code, 2)
        self.assertIn("目录不可写", err)
        self.assertNotIn("Traceback", err)
        self.prepare.assert_not_called()
        self.submit.assert_not_called()

    def test_solver_captcha_error_exit_2(self):
        self.make_solver.side_effect = CaptchaSolverError(
            "验证码命令超时（0.3s）"
        )
        code, _, err = run(["--captcha-prompt"])
        self.assertEqual(code, 2)
        self.assertIn("超时", err)
        self.assertNotIn("Traceback", err)
        self.submit.assert_not_called()


class TestCaptchaAttemptsRealValidation(unittest.TestCase):
    """不 mock 提交层：--captcha-attempts 0/-1 由库内校验拒绝。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self.old_cwd)
        Path("sfz.txt").write_text("张三|" + VALID_ID + "\n", encoding="utf-8")

    def test_zero_or_negative_attempts_exit_2(self):
        for value in ("0", "-1"):
            with self.subTest(value=value):
                code, out, err = run([
                    "--offline", "--captcha-attempts", value,
                ])
                self.assertEqual(code, 2)
                self.assertIn("captcha_attempts", err)
                self.assertIn(">= 1", err)
                self.assertNotIn("Traceback", err)
                self.assertFalse(Path("accounts.json").exists())
                # 提交前就被拒绝，不应产生结果行
                self.assertNotIn("DRY-RUN:", out)


if __name__ == "__main__":
    unittest.main()
