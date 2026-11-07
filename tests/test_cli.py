"""gen4399.cli 单元测试：全部走本地逻辑或打桩，不联网。"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gen4399 import cli
from gen4399.core import validate, validate_username
from gen4399.remote import Account, UsernameAvailability

VALID_ID = "460206194611192084"


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
