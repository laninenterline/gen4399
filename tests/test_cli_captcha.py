"""CLI 图形验证码参数测试：``--captcha-*`` 的解析、透传与退出码。

提交层用 mock 替换（``prepare_registration`` / ``submit_registration``），
不联网、不建号；另一个用例故意不 mock ``submit_registration``，验证
``--captcha-attempts 0`` 由库内 ``ValueError`` 触发 CLI 退出码 2。
"""

import contextlib
import io
import os
import tempfile
import unittest
from unittest import mock

from gen4399 import cli
from gen4399.submit import SubmitResult

VALID_ID = "460206194611192084"

_MODULE_TMP = None
_MODULE_CWD = None


def setUpModule():
    """在空的临时目录中跑，避免读到用户本地的 ./sfz.txt。"""
    global _MODULE_TMP, _MODULE_CWD
    _MODULE_CWD = os.getcwd()
    _MODULE_TMP = tempfile.TemporaryDirectory()
    os.chdir(_MODULE_TMP.name)


def tearDownModule():
    if _MODULE_CWD is not None:
        os.chdir(_MODULE_CWD)
    if _MODULE_TMP is not None:
        _MODULE_TMP.cleanup()


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def _submit_result(**kwargs):
    base = dict(
        ok=False,
        kind="dry_run",
        message="dry-run：未发送 POST",
        username="abc12345",
        path="web",
        app_id="",
        endpoint="https://web.4399.com/user/?_c=reg",
        encrypted_fields=("login_password", "relogin_pwd"),
        login_cookies=(),
        field_names=("login_name",),
        dry_run=True,
    )
    base.update(kwargs)
    return SubmitResult(**base)


def _identity_args():
    return ["--realname", "张三", "--idcard", VALID_ID]


class TestCaptchaParser(unittest.TestCase):
    """两种入口（子命令 / legacy flag）都要有同一组 --captcha-* 参数。"""

    def assert_defaults(self, args):
        self.assertFalse(args.captcha_prompt)
        self.assertIsNone(args.captcha_cmd)
        self.assertIsNone(args.captcha_dir)
        self.assertEqual(args.captcha_attempts, 3)

    def test_subcommand_defaults(self):
        args = cli.build_subcommand_parser().parse_args(["submit"])
        self.assert_defaults(args)

    def test_legacy_defaults(self):
        args = cli.build_parser().parse_args([])
        self.assert_defaults(args)

    def test_subcommand_flags(self):
        args = cli.build_subcommand_parser().parse_args([
            "submit",
            "--captcha-prompt",
            "--captcha-cmd", "tesseract stdin stdout",
            "--captcha-dir", "caps",
            "--captcha-attempts", "5",
        ])
        self.assertTrue(args.captcha_prompt)
        self.assertEqual(args.captcha_cmd, "tesseract stdin stdout")
        self.assertEqual(args.captcha_dir, "caps")
        self.assertEqual(args.captcha_attempts, 5)

    def test_legacy_flags(self):
        args = cli.build_parser().parse_args([
            "--submit",
            "--captcha-prompt",
            "--captcha-cmd", "ocr",
            "--captcha-dir", "caps",
            "--captcha-attempts", "2",
        ])
        self.assertTrue(args.captcha_prompt)
        self.assertEqual(args.captcha_cmd, "ocr")
        self.assertEqual(args.captcha_dir, "caps")
        self.assertEqual(args.captcha_attempts, 2)

    def test_attempts_must_be_int(self):
        with self.assertRaises(SystemExit) as ctx:
            with contextlib.redirect_stderr(io.StringIO()):
                cli.build_subcommand_parser().parse_args(
                    ["submit", "--captcha-attempts", "abc"]
                )
        self.assertEqual(ctx.exception.code, 2)


class TestSubmitCaptchaWiring(unittest.TestCase):
    """_cmd_submit 必须把 solver 和轮数原样传给 submit_registration。"""

    def setUp(self):
        p1 = mock.patch(
            "gen4399.cli.prepare_registration", return_value=mock.Mock()
        )
        self.prepare = p1.start()
        self.addCleanup(p1.stop)
        p2 = mock.patch(
            "gen4399.cli.submit_registration", return_value=_submit_result()
        )
        self.submit = p2.start()
        self.addCleanup(p2.stop)
        self.solver = mock.Mock()

    def test_defaults_pass_none_and_three(self):
        code, _, _ = run(["submit", "--offline", *_identity_args()])
        self.assertEqual(code, 0)
        kwargs = self.submit.call_args.kwargs
        self.assertIsNone(kwargs["captcha"])
        self.assertEqual(kwargs["captcha_attempts"], 3)

    def test_prompt_and_dir_wired(self):
        with mock.patch(
            "gen4399.cli._make_captcha_solver", return_value=self.solver
        ) as factory:
            code, _, _ = run([
                "submit", "--offline", "--captcha-prompt",
                "--captcha-dir", "/tmp/caps",
                "--captcha-attempts", "5",
                *_identity_args(),
            ])
        self.assertEqual(code, 0)
        factory.assert_called_once_with(
            prompt=True, command=None, directory="/tmp/caps", auto=False, matcher=False, zoom=1
        )
        kwargs = self.submit.call_args.kwargs
        self.assertIs(kwargs["captcha"], self.solver)
        self.assertEqual(kwargs["captcha_attempts"], 5)

    def test_command_wired(self):
        with mock.patch(
            "gen4399.cli._make_captcha_solver", return_value=self.solver
        ) as factory:
            code, _, _ = run([
                "submit", "--offline", "--captcha-cmd", "echo hi",
                *_identity_args(),
            ])
        self.assertEqual(code, 0)
        factory.assert_called_once_with(
            prompt=False, command="echo hi", directory=None, auto=False, matcher=False, zoom=1
        )
        self.assertIs(self.submit.call_args.kwargs["captcha"], self.solver)

    def test_legacy_flags_wired(self):
        with mock.patch(
            "gen4399.cli._make_captcha_solver", return_value=self.solver
        ) as factory:
            code, _, _ = run([
                "--submit", "--offline", "--captcha-prompt",
                "--captcha-attempts", "2",
                *_identity_args(),
            ])
        self.assertEqual(code, 0)
        factory.assert_called_once_with(
            prompt=True, command=None, directory=None, auto=False, matcher=False, zoom=1
        )
        kwargs = self.submit.call_args.kwargs
        self.assertIs(kwargs["captcha"], self.solver)
        self.assertEqual(kwargs["captcha_attempts"], 2)

    def test_solver_factory_oserror_exit_2(self):
        with mock.patch(
            "gen4399.cli._make_captcha_solver",
            side_effect=OSError("目录不可写"),
        ):
            code, _, err = run(["submit", "--offline", *_identity_args()])
        self.assertEqual(code, 2)
        self.assertIn("目录不可写", err)
        self.assertNotIn("Traceback", err)
        self.submit.assert_not_called()
        self.prepare.assert_not_called()

    def test_valueerror_from_submit_exit_2(self):
        """CLI 在 try 里调用 submit_registration，ValueError → 退出码 2。"""
        self.submit.side_effect = ValueError("captcha_attempts 必须是 >= 1 的 int")
        code, _, err = run([
            "submit", "--offline", "--captcha-attempts", "0",
            *_identity_args(),
        ])
        self.assertEqual(code, 2)
        self.assertIn("captcha_attempts", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(self.submit.call_args.kwargs["captcha_attempts"], 0)

    def test_success_prints_captcha_rounds(self):
        self.submit.return_value = _submit_result(
            ok=True, kind="success", message="注册成功",
            dry_run=False, captcha_attempts=2,
        )
        code, out, _ = run(
            ["submit", "--offline", "--yes", *_identity_args()]
        )
        self.assertEqual(code, 0)
        self.assertIn("验证码轮次: 2", out)

    def test_hint_when_captcha_without_solver(self):
        self.submit.return_value = _submit_result(
            ok=False, kind="captcha", message="需要图形验证码", dry_run=False,
        )
        code, out, _ = run(
            ["submit", "--offline", "--yes", *_identity_args()]
        )
        self.assertEqual(code, 1)
        self.assertIn("FAIL[captcha]", out)
        self.assertIn("--captcha-prompt", out)
        self.assertIn("--captcha-cmd", out)

    def test_no_hint_when_solver_given(self):
        self.submit.return_value = _submit_result(
            ok=False, kind="captcha", message="需要图形验证码", dry_run=False,
        )
        with mock.patch(
            "gen4399.cli._make_captcha_solver", return_value=self.solver
        ):
            code, out, _ = run([
                "submit", "--offline", "--yes", "--captcha-prompt",
                *_identity_args(),
            ])
        self.assertEqual(code, 1)
        self.assertIn("FAIL[captcha]", out)
        self.assertNotIn("提示:", out)


class TestSubmitCaptchaValidation(unittest.TestCase):
    """不 mock submit_registration：真实库内校验触发 CLI 退出码 2。"""

    def test_zero_or_negative_attempts_exit_2(self):
        for value in ("0", "-1"):
            with self.subTest(value=value):
                code, out, err = run([
                    "submit", "--offline", "--form-path", "web",
                    "--captcha-attempts", value,
                    *_identity_args(),
                ])
                self.assertEqual(code, 2)
                self.assertIn("captcha_attempts", err)
                self.assertNotIn("Traceback", err)
                # 提交前就失败，不应产生任何结果行
                self.assertNotIn("DRY-RUN:", out)


if __name__ == "__main__":
    unittest.main()
