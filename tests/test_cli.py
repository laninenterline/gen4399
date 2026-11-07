"""gen4399.cli 单元测试：全部走本地逻辑或打桩，不联网。"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gen4399 import cli
from gen4399.core import validate, validate_username
from gen4399.remote import Account, RemoteError, UsernameAvailability
from gen4399.submit import SubmitResult

VALID_ID = "460206194611192084"


_MODULE_TMP = None
_MODULE_CWD = None


def setUpModule():
    """CLI 测试统一在空的临时目录中跑，避免读到用户本地的 ./sfz.txt。"""
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


class TestParser(unittest.TestCase):
    def test_defaults(self):
        args = cli.build_parser().parse_args([])
        self.assertIsNone(args.length)
        self.assertEqual(args.count, 1)
        self.assertEqual(args.form_path, "web")
        self.assertIsNone(args.timeout)
        self.assertFalse(args.entropy)

    def test_timeout_option(self):
        args = cli.build_parser().parse_args(["--timeout", "3.5"])
        self.assertEqual(args.timeout, 3.5)

    def test_unknown_path_rejected(self):
        with self.assertRaises(SystemExit) as ctx:
            cli.build_parser().parse_args(["--form-fields", "phone"])
        self.assertEqual(ctx.exception.code, 2)


class TestGenerate(unittest.TestCase):
    def test_passwords(self):
        code, out, err = run(["-n", "8", "-c", "3"])
        self.assertEqual(code, 0)
        lines = out.split()
        self.assertEqual(len(lines), 3)
        for pw in lines:
            self.assertEqual(len(pw), 8)
            self.assertEqual(validate(pw), [])
        self.assertIn("密码", err)

    def test_usernames(self):
        code, out, err = run(["-u", "-n", "10", "-c", "2"])
        self.assertEqual(code, 0)
        lines = out.split()
        self.assertEqual(len(lines), 2)
        for name in lines:
            self.assertEqual(len(name), 10)
            self.assertEqual(validate_username(name), [])
        self.assertIn("账号名", err)

    def test_entropy(self):
        code, out, _ = run(["--entropy", "-p", "abc"])
        self.assertEqual(code, 0)
        self.assertGreater(float(out.strip()), 0)

    def test_entropy_length_out_of_range(self):
        code, _, err = run(["--entropy", "-n", "5"])
        self.assertEqual(code, 2)
        self.assertIn("6~20", err)

    def test_bad_length(self):
        code, _, err = run(["-n", "5"])
        self.assertEqual(code, 2)
        self.assertIn("错误", err)


class TestCheck(unittest.TestCase):
    def test_password_ok(self):
        code, out, _ = run(["--check", "Abc12345"])
        self.assertEqual(code, 0)
        self.assertIn("OK", out)

    def test_password_bad(self):
        code, _, err = run(["--check", "123456"])
        self.assertEqual(code, 1)
        self.assertIn("all_digits", err)

    def test_username_ok(self):
        code, out, _ = run(["--check-username", "abc12345"])
        self.assertEqual(code, 0)
        self.assertIn("OK", out)

    def test_username_bad(self):
        code, _, err = run(["--check-username", "abc_12345"])
        self.assertEqual(code, 1)
        self.assertIn("charset", err)


class TestFormCommands(unittest.TestCase):
    def test_form_fields(self):
        code, out, _ = run(["--form-fields", "web"])
        self.assertEqual(code, 0)
        self.assertIn("login_name", out)
        self.assertIn("reg.php", out)

    def test_check_form_ok(self):
        code, out, _ = run([
            "--check-form", "abc12345", "Abc123456",
            "--realname", "张三", "--idcard", VALID_ID,
        ])
        self.assertEqual(code, 0)
        self.assertIn("OK", out)

    def test_check_form_bad(self):
        code, _, err = run([
            "--check-form", "ab", "123",
            "--realname", "张三", "--idcard", VALID_ID,
        ])
        self.assertEqual(code, 1)
        self.assertIn("FAIL", err)

    def test_build_form_masks_by_default(self):
        code, out, err = run([
            "--build-form", "abc12345", "Abc123456",
            "--realname", "张三", "--idcard", VALID_ID, "--qq", "123456789",
        ])
        self.assertEqual(code, 0)
        self.assertNotIn(VALID_ID, out)
        self.assertNotIn("Abc123456", out)
        self.assertNotIn("123456789", out)
        self.assertIn("--show-pii", err)

    def test_build_form_show_pii(self):
        code, out, _ = run([
            "--build-form", "abc12345", "Abc123456",
            "--realname", "张三", "--idcard", VALID_ID, "--show-pii",
        ])
        self.assertEqual(code, 0)
        self.assertIn(VALID_ID, out)
        self.assertIn("Abc123456", out)

    def test_build_form_requires_identity(self):
        code, _, err = run(["--build-form", "abc12345", "Abc123456"])
        self.assertEqual(code, 2)
        self.assertIn("--realname", err)

    def test_prepare_offline(self):
        code, out, err = run([
            "--prepare", "--no-verify",
            "--realname", "张三", "--idcard", VALID_ID,
        ])
        self.assertEqual(code, 0)
        self.assertIn("login_name", out)
        self.assertNotIn(VALID_ID, out)
        self.assertIn("未做在线查重", err + out)

    def test_prepare_requires_identity(self):
        code, _, err = run(["--prepare"])
        self.assertEqual(code, 2)

    def test_prepare_bad_password_length(self):
        code, _, err = run([
            "--prepare", "--no-verify", "-n", "5",
            "--realname", "张三", "--idcard", VALID_ID,
        ])
        self.assertEqual(code, 2)
        self.assertIn("错误", err)


class TestProfileFile(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _write(self, content, name="ids.txt"):
        path = self.root / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_prepare_batch(self):
        path = self._write(
            "张三|" + VALID_ID + "\n李四|440106198101010155|123456789\n"
        )
        code, out, _ = run(
            ["--prepare", "--no-verify", "--profile-file", str(path)]
        )
        self.assertEqual(code, 0)
        self.assertIn("# 身份 1/2", out)
        self.assertIn("# 身份 2/2", out)
        self.assertEqual(out.count("login_name"), 2)
        self.assertNotIn(VALID_ID, out)

    def test_build_form_batch(self):
        path = self._write(
            "张三|" + VALID_ID + "\n李四|440106198101010155\n"
        )
        code, out, _ = run([
            "--build-form", "abc12345", "Abc123456",
            "--profile-file", str(path),
        ])
        self.assertEqual(code, 0)
        self.assertEqual(out.count("login_name"), 2)
        self.assertIn("# 身份 2/2", out)
        self.assertNotIn(VALID_ID, out)

    def test_check_form_batch(self):
        path = self._write(
            "张三|" + VALID_ID + "\n李四|440106198101010155\n"
        )
        code, out, _ = run([
            "--check-form", "abc12345", "Abc123456",
            "--profile-file", str(path),
        ])
        self.assertEqual(code, 0)
        self.assertEqual(out.count("OK: 表单全部通过"), 2)

    def test_single_line_no_group_header(self):
        path = self._write("张三|" + VALID_ID + "\n")
        code, out, _ = run(
            ["--prepare", "--no-verify", "--profile-file", str(path)]
        )
        self.assertEqual(code, 0)
        self.assertIn("login_name", out)
        self.assertNotIn("# 身份", out)

    def test_conflict_with_realname(self):
        path = self._write("张三|" + VALID_ID + "\n")
        code, _, err = run([
            "--prepare", "--no-verify", "--profile-file", str(path),
            "--realname", "张三",
        ])
        self.assertEqual(code, 2)
        self.assertIn("不能与", err)

    def test_missing_file(self):
        code, _, err = run([
            "--prepare", "--no-verify",
            "--profile-file", str(self.root / "nope.txt"),
        ])
        self.assertEqual(code, 2)
        self.assertIn("错误", err)
        self.assertNotIn("Traceback", err)

    def test_bad_line_reports_number(self):
        path = self._write("张三|" + VALID_ID + "\n坏行\n", name="bad.txt")
        code, _, err = run(
            ["--prepare", "--no-verify", "--profile-file", str(path)]
        )
        self.assertEqual(code, 2)
        self.assertIn("第 2 行", err)


class TestJsonOutput(unittest.TestCase):
    def test_generate_json(self):
        code, out, _ = run(["-n", "8", "-c", "2", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["kind"], "password")
        self.assertEqual(len(data["items"]), 2)
        self.assertEqual(data["length"], 8)
        for item in data["items"]:
            self.assertEqual(validate(item), [])

    def test_username_generate_json(self):
        code, out, _ = run(["-u", "-n", "10", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["kind"], "username")
        self.assertEqual(len(data["items"][0]), 10)

    def test_check_json(self):
        code, out, _ = run(["--check", "123456", "--json"])
        self.assertEqual(code, 1)
        data = json.loads(out)
        self.assertFalse(data["ok"])
        self.assertEqual(data["violations"][0]["code"], "all_digits")

    def test_entropy_json(self):
        code, out, _ = run(["--entropy", "-n", "8", "--json"])
        self.assertEqual(code, 0)
        self.assertGreater(json.loads(out)["entropy_bits"], 0)

    def test_form_fields_json(self):
        code, out, _ = run(["--form-fields", "web", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["path"], "web")
        self.assertIn("login_name", [f["name"] for f in data["fields"]])

    def test_build_form_json(self):
        code, out, _ = run([
            "--build-form", "abc12345", "Abc123456",
            "--realname", "张三", "--idcard", VALID_ID, "--json",
        ])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertNotIn(VALID_ID, json.dumps(data, ensure_ascii=False))
        self.assertEqual(data["fields"]["login_name"], "abc12345")

    def test_prepare_json(self):
        code, out, _ = run([
            "--prepare", "--offline",
            "--realname", "张三", "--idcard", VALID_ID, "--json",
        ])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(len(data), 1)
        self.assertNotIn(VALID_ID, out)

    def test_check_available_json(self):
        avail = UsernameAvailability(
            username="abc12345", available=True, message="0"
        )
        with mock.patch("gen4399.cli.check_username", return_value=avail):
            code, out, _ = run(["--check-available", "abc12345", "--json"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["available"])

    def test_fetch_json(self):
        with mock.patch("gen4399.cli.fetch_suggested_usernames",
                        return_value=["u4257237567"]):
            code, out, _ = run(["--fetch-username", "1", "-p", "u", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), ["u4257237567"])


class TestNewFlags(unittest.TestCase):
    def test_password_length_and_username_length(self):
        code, out, _ = run([
            "--account", "--no-verify",
            "--password-length", "20", "--username-length", "10",
        ])
        self.assertEqual(code, 0)
        lines = dict(line.split(": ", 1) for line in out.strip().splitlines())
        self.assertEqual(len(lines["username"]), 10)
        self.assertEqual(len(lines["password"]), 20)

    def test_account_batch_count(self):
        code, out, _ = run(["--account", "--no-verify", "-c", "3"])
        self.assertEqual(code, 0)
        self.assertEqual(out.count("username: "), 3)

    def test_check_available_offline_errors(self):
        code, _, err = run(["--check-available", "abc12345", "--offline"])
        self.assertEqual(code, 2)
        self.assertIn("需要联网", err)

    def test_fetch_offline_errors(self):
        code, _, err = run(["--fetch-username", "--offline"])
        self.assertEqual(code, 2)
        self.assertIn("需要联网", err)

    def test_retry_policy_passed(self):
        avail = UsernameAvailability(
            username="abc12345", available=True, message="0"
        )
        with mock.patch("gen4399.cli.check_username", return_value=avail) as chk:
            run(["--check-available", "abc12345",
                 "--retries", "5", "--retry-delay", "0.1"])
        policy = chk.call_args.kwargs["retry_policy"]
        self.assertEqual(policy.attempts, 5)
        self.assertEqual(policy.base_delay, 0.1)

    def test_output_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = run([
                "--prepare", "--offline",
                "--realname", "张三", "--idcard", VALID_ID,
                "--output", tmp,
            ])
            self.assertEqual(code, 0)
            files = list(Path(tmp).glob("bundle-*.json"))
            self.assertEqual(len(files), 1)
            mode = files[0].stat().st_mode & 0o777
            data = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(mode, 0o600)
        self.assertNotIn(VALID_ID, json.dumps(data, ensure_ascii=False))

    def test_profile_file_stdin(self):
        old = sys.stdin
        sys.stdin = io.StringIO("张三|" + VALID_ID + "\n")
        try:
            code, out, _ = run([
                "--prepare", "--offline", "--profile-file", "-",
            ])
        finally:
            sys.stdin = old
        self.assertEqual(code, 0)
        self.assertIn("login_name", out)

    def test_show_pii_warning(self):
        code, _, err = run([
            "--build-form", "abc12345", "Abc123456",
            "--realname", "张三", "--idcard", VALID_ID, "--show-pii",
        ])
        self.assertEqual(code, 0)
        self.assertIn("警告", err)

    def test_profile_file_with_qq_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ids.txt"
            path.write_text("张三|" + VALID_ID + "\n", encoding="utf-8")
            code, _, err = run([
                "--prepare", "--offline", "--profile-file", str(path),
                "--qq", "123456789",
            ])
        self.assertEqual(code, 2)
        self.assertIn("不能与", err)


class TestAccount(unittest.TestCase):
    def test_offline_lengths(self):
        code, out, err = run([
            "--account", "--no-verify", "-n", "20", "--username-length", "10",
        ])
        self.assertEqual(code, 0)
        lines = dict(line.split(": ", 1) for line in out.strip().splitlines())
        self.assertEqual(len(lines["username"]), 10)
        self.assertEqual(len(lines["password"]), 20)
        self.assertIn("未做在线查重", err)

    def test_online_verify(self):
        acc = Account(username="free123456", password="Abc123456",
                      username_available=True)
        with mock.patch("gen4399.cli.generate_account", return_value=acc) as gen:
            code, out, _ = run(["--account"])
        self.assertEqual(code, 0)
        self.assertIn("free123456", out)
        gen.assert_called_once()

    def test_online_error(self):
        with mock.patch("gen4399.cli.generate_account",
                        side_effect=RuntimeError("boom")):
            # RuntimeError 不属于约定异常，不应被吞掉
            with self.assertRaises(RuntimeError):
                run(["--account"])


class TestRemoteCommands(unittest.TestCase):
    def test_check_available(self):
        avail = UsernameAvailability(
            username="abc12345", available=True, message="0"
        )
        with mock.patch("gen4399.cli.check_username", return_value=avail) as chk:
            code, out, _ = run(["--check-available", "abc12345",
                                "--timeout", "3"])
        self.assertEqual(code, 0)
        self.assertIn("AVAILABLE", out)
        self.assertEqual(chk.call_args.kwargs["timeout"], 3.0)

    def test_check_available_taken(self):
        avail = UsernameAvailability(
            username="abc12345", available=False, message="用户名已被注册"
        )
        with mock.patch("gen4399.cli.check_username", return_value=avail):
            code, _, err = run(["--check-available", "abc12345"])
        self.assertEqual(code, 1)
        self.assertIn("UNAVAILABLE", err)

    def test_fetch_ok(self):
        with mock.patch("gen4399.cli.fetch_suggested_usernames",
                        return_value=["u4257237567"]) as fetch:
            code, out, _ = run(["--fetch-username", "2", "-p", "u"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "u4257237567")
        self.assertEqual(fetch.call_args.args[0], 2)
        self.assertEqual(fetch.call_args.kwargs["prefix"], "u")

    def test_fetch_bad_count(self):
        code, _, err = run(["--fetch-username", "0"])
        self.assertEqual(code, 2)
        self.assertIn("错误", err)
        self.assertNotIn("Traceback", err)

    def test_fetch_bad_prefix(self):
        code, _, err = run(["--fetch-username", "-p", "a_b"])
        self.assertEqual(code, 2)
        self.assertIn("前缀", err)
        self.assertNotIn("Traceback", err)

    def test_fetch_remote_error(self):
        with mock.patch("gen4399.cli.fetch_suggested_usernames",
                        side_effect=cli.RemoteError("接口异常")):
            code, _, err = run(["--fetch-username"])
        self.assertEqual(code, 2)
        self.assertIn("接口异常", err)


class TestSubcommands(unittest.TestCase):
    def test_generate_json(self):
        code, out, _ = run(["generate", "-n", "8", "-c", "2", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["kind"], "password")
        self.assertEqual(len(data["items"]), 2)

    def test_generate_username_json(self):
        code, out, _ = run(["generate", "--kind", "username", "-n", "10",
                            "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["kind"], "username")

    def test_check_password_bad(self):
        code, _, err = run(["check", "password", "123456"])
        self.assertEqual(code, 1)
        self.assertIn("all_digits", err)

    def test_check_username_ok(self):
        code, out, _ = run(["check", "username", "abc12345"])
        self.assertEqual(code, 0)
        self.assertIn("OK", out)

    def test_account_batch(self):
        code, out, _ = run(["account", "--offline", "-c", "2"])
        self.assertEqual(code, 0)
        self.assertEqual(out.count("username: "), 2)

    def test_form_fields(self):
        code, out, _ = run(["form", "fields", "web"])
        self.assertEqual(code, 0)
        self.assertIn("login_name", out)

    def test_form_build(self):
        code, out, _ = run([
            "form", "build", "abc12345", "Abc123456",
            "--realname", "张三", "--idcard", VALID_ID,
        ])
        self.assertEqual(code, 0)
        self.assertIn("login_name", out)
        self.assertNotIn(VALID_ID, out)

    def test_prepare(self):
        code, out, _ = run([
            "prepare", "--offline",
            "--realname", "张三", "--idcard", VALID_ID,
        ])
        self.assertEqual(code, 0)
        self.assertIn("login_name", out)

    def test_profile_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ids.txt"
            path.write_text("张三|" + VALID_ID + "\n", encoding="utf-8")
            code, out, _ = run(["profile", "check", "--profile-file",
                                str(path), "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(len(data), 1)
        self.assertNotIn(VALID_ID, out)

    def test_rules(self):
        code, out, _ = run(["rules"])
        self.assertEqual(code, 0)
        self.assertIn("rules", out)

    def test_version(self):
        code, out, _ = run(["version"])
        self.assertEqual(code, 0)
        self.assertIn("gen4399", out)


def _submit_result(**kwargs):
    base = dict(
        ok=False,
        kind="dry_run",
        message="dry-run：未发送 POST",
        username="abc12345",
        path="unified",
        app_id="u4399",
        endpoint="https://ptlogin.4399.com/ptlogin/register.do",
        encrypted_fields=("password", "passwordveri", "realname", "idcard"),
        login_cookies=(),
        field_names=("username", "password"),
        dry_run=True,
    )
    base.update(kwargs)
    return SubmitResult(**base)


class TestSubmitParser(unittest.TestCase):
    def test_subcommand_defaults(self):
        args = cli.build_subcommand_parser().parse_args(["submit"])
        self.assertTrue(args.submit)
        self.assertEqual(args.form_path, "unified")
        self.assertFalse(args.yes)
        self.assertIsNone(args.app_id)
        self.assertEqual(args.level, 4)

    def test_legacy_flags(self):
        args = cli.build_parser().parse_args(["--submit", "--yes"])
        self.assertTrue(args.submit)
        self.assertTrue(args.yes)
        self.assertEqual(args.level, 4)
        self.assertIsNone(args.app_id)

    def test_help(self):
        with self.assertRaises(SystemExit) as ctx:
            with contextlib.redirect_stdout(io.StringIO()):
                cli.build_subcommand_parser().parse_args(["submit", "--help"])
        self.assertEqual(ctx.exception.code, 0)


class TestSubmitCommand(unittest.TestCase):
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

    def _identity_args(self):
        return ["--realname", "张三", "--idcard", VALID_ID]

    def test_default_is_dry_run(self):
        code, out, err = run(["submit", "--offline", *self._identity_args()])
        self.assertEqual(code, 0)
        self.submit.assert_called_once()
        self.assertTrue(self.submit.call_args.kwargs["dry_run"])
        self.assertIn("DRY-RUN", out)
        self.assertIn("DRY-RUN", err)
        self.prepare.assert_called_once()

    def test_yes_really_submits(self):
        code, out, err = run(
            ["submit", "--offline", "--yes", *self._identity_args()]
        )
        self.assertEqual(code, 0)
        self.assertFalse(self.submit.call_args.kwargs["dry_run"])
        self.assertIn("警告", err)

    def test_success(self):
        self.submit.return_value = _submit_result(
            ok=True, kind="success", message="注册成功", dry_run=False
        )
        code, out, _ = run(
            ["submit", "--offline", "--yes", *self._identity_args()]
        )
        self.assertEqual(code, 0)
        self.assertIn("OK: 注册成功", out)

    def test_rejected_exit_1(self):
        self.submit.return_value = _submit_result(
            ok=False, kind="rejected", message="用户名已被注册", dry_run=False
        )
        code, out, _ = run(
            ["submit", "--offline", "--yes", *self._identity_args()]
        )
        self.assertEqual(code, 1)
        self.assertIn("FAIL[rejected]", out)
        self.assertIn("用户名已被注册", out)

    def test_unknown_exit_1(self):
        self.submit.return_value = _submit_result(
            ok=False, kind="unknown", message="无法确定", dry_run=False
        )
        code, out, _ = run(
            ["submit", "--offline", "--yes", *self._identity_args()]
        )
        self.assertEqual(code, 1)
        self.assertIn("FAIL[unknown]", out)

    def test_remote_error_exit_2(self):
        self.submit.side_effect = RemoteError("网络错误")
        code, _, err = run(
            ["submit", "--offline", "--yes", *self._identity_args()]
        )
        self.assertEqual(code, 2)
        self.assertIn("错误", err)

    def test_bad_retry_args_exit_2(self):
        for extra in (
            ["--retries", "0"],
            ["--retry-delay", "-1"],
            ["--max-total-timeout", "0"],
        ):
            with self.subTest(extra=extra):
                code, _, err = run(
                    ["submit", "--offline", *extra, *self._identity_args()]
                )
                self.assertEqual(code, 2)
                self.assertNotIn("Traceback", err)
                self.assertIn("错误", err)
                self.submit.assert_not_called()
                self.prepare.assert_not_called()

    def test_identity_missing_exit_2(self):
        code, _, err = run(["submit", "--offline"])
        self.assertEqual(code, 2)
        self.assertIn("错误", err)
        self.submit.assert_not_called()

    def test_legacy_submit(self):
        self.submit.return_value = _submit_result(
            ok=True, kind="success", message="注册成功", dry_run=False
        )
        code, out, _ = run([
            "--submit", "--offline", "--yes", "--form-path", "unified",
            *self._identity_args(),
        ])
        self.assertEqual(code, 0)
        self.assertIn("OK", out)
        self.submit.assert_called_once()

    def test_legacy_default_web_path(self):
        code, out, err = run(
            ["--submit", "--offline", *self._identity_args()]
        )
        self.assertEqual(code, 0)
        self.assertIn("DRY-RUN", out)
        self.assertEqual(
            self.prepare.call_args.kwargs["path"], "web"
        )
        self.submit.assert_called_once()
        self.assertTrue(self.submit.call_args.kwargs["dry_run"])

    def test_subcommand_web_path(self):
        code, out, _ = run([
            "submit", "--offline", "--form-path", "web",
            *self._identity_args(),
        ])
        self.assertEqual(code, 0)
        self.assertIn("DRY-RUN", out)
        self.assertEqual(
            self.prepare.call_args.kwargs["path"], "web"
        )

    def test_subcommand_web_path_yes(self):
        code, _, err = run([
            "submit", "--offline", "--form-path", "web", "--yes",
            *self._identity_args(),
        ])
        self.assertEqual(code, 0)
        self.assertFalse(self.submit.call_args.kwargs["dry_run"])
        self.assertIn("警告", err)

    def test_json_output(self):
        code, out, _ = run(
            ["submit", "--offline", "--json", *self._identity_args()]
        )
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["kind"], "dry_run")
        self.assertNotIn("password", data)

    def test_dry_run_does_not_print_pii(self):
        code, out, _ = run(["submit", "--offline", *self._identity_args()])
        self.assertEqual(code, 0)
        self.assertNotIn(VALID_ID, out)
        self.assertNotIn("张三", out)

    def test_output_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = run([
                "submit", "--offline", "--output", tmp,
                *self._identity_args(),
            ])
            path = Path(tmp) / "submit.json"
            self.assertEqual(code, 0)
            self.assertTrue(path.exists())
            self.assertIn("submit.json", err)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["kind"], "dry_run")

    def test_batch_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ids.txt"
            path.write_text(
                "张三|" + VALID_ID + "\n李四|11010119900101004X\n",
                encoding="utf-8",
            )
            code, _, err = run([
                "submit", "--offline", "--profile-file", str(path),
            ])
        self.assertEqual(code, 0)
        self.assertEqual(self.submit.call_count, 2)
        self.assertIn("2 个身份", err)


class TestDefaultProfileFile(unittest.TestCase):
    """未指定身份来源时默认读取当前目录的 sfz.txt。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self.old_cwd)

    def _write(self, text: str, name: str = "sfz.txt"):
        path = Path(name)
        path.write_text(text, encoding="utf-8")
        return path

    def test_prepare_uses_default_sfz_txt(self):
        self._write("张三|" + VALID_ID + "\n")
        code, out, _ = run(["--prepare", "--offline", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["realname"], "张三")
        self.assertNotIn(VALID_ID, out)

    def test_missing_default_errors(self):
        code, _, err = run(["--prepare", "--offline"])
        self.assertEqual(code, 2)
        self.assertIn("sfz.txt", err)

    def test_qq_alone_does_not_fall_back(self):
        self._write("张三|" + VALID_ID + "\n")
        code, _, err = run(["--prepare", "--offline", "--qq", "123456789"])
        self.assertEqual(code, 2)
        self.assertIn("realname", err)

    def test_explicit_profile_file_wins(self):
        self._write("张三|" + VALID_ID + "\n")
        other = self._write("李四|11010119900101004X\n", "other.txt")
        code, out, _ = run([
            "--prepare", "--offline", "--json",
            "--profile-file", str(other),
        ])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)[0]["realname"], "李四")

    def test_realname_idcard_wins_over_default(self):
        self._write("张三|" + VALID_ID + "\n")
        code, out, _ = run([
            "--prepare", "--offline", "--json",
            "--realname", "李四", "--idcard", "11010119900101004X",
        ])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)[0]["realname"], "李四")

    def test_profile_check_uses_default(self):
        self._write("张三|" + VALID_ID + "\n")
        code, out, _ = run(["profile", "check", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data[0]["realname"], "张三")
        self.assertNotIn(VALID_ID, out)

    def test_profile_check_missing_default_errors(self):
        code, _, err = run(["profile", "check"])
        self.assertEqual(code, 2)
        self.assertIn("sfz.txt", err)

    def test_gb18030_default_file_falls_back(self):
        Path("sfz.txt").write_bytes(
            ("张三|" + VALID_ID + "\n").encode("gb18030")
        )
        code, out, err = run(["--prepare", "--offline", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)[0]["realname"], "张三")
        self.assertIn("GB18030", err)

    def test_explicit_gbk_file_falls_back(self):
        path = Path("gbk.txt")
        path.write_bytes(("李四|11010119900101004X\n").encode("gb18030"))
        code, out, _ = run([
            "--prepare", "--offline", "--json", "--profile-file", str(path),
        ])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)[0]["realname"], "李四")

    def test_submit_uses_default_sfz_txt(self):
        self._write("张三|" + VALID_ID + "\n")
        with mock.patch(
            "gen4399.cli.submit_registration", return_value=_submit_result()
        ) as submit:
            code, out, _ = run(["submit", "--offline", "--form-path", "web"])
        self.assertEqual(code, 0)
        self.assertIn("DRY-RUN", out)
        bundle = submit.call_args.args[0]
        self.assertEqual(bundle.realname, "张三")


class TestMisc(unittest.TestCase):
    def test_version(self):
        with self.assertRaises(SystemExit) as ctx:
            with contextlib.redirect_stdout(io.StringIO()):
                cli.main(["--version"])
        self.assertEqual(ctx.exception.code, 0)

    def test_rules_version(self):
        with self.assertRaises(SystemExit) as ctx:
            with contextlib.redirect_stdout(io.StringIO()):
                cli.main(["--rules-version"])
        self.assertEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
