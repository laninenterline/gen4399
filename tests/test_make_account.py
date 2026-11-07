"""scripts/make_account.py 的单元测试（全部打桩，不联网、不建号）。"""

import contextlib
import importlib.util
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType
from unittest import mock

from gen4399.registration import RegistrationBundle
from gen4399.submit import SubmitResult

VALID_ID = "460206194611192084"
_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "make_account.py"
_spec = importlib.util.spec_from_file_location("make_account", _SCRIPT)
assert _spec is not None and _spec.loader is not None
make_account = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_account)


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


def _result(**kwargs) -> SubmitResult:
    base = dict(
        ok=True,
        kind="success",
        message="注册成功",
        username="abc12345",
        path="unified",
        app_id="u4399",
        endpoint="https://ptlogin.4399.com/ptlogin/register.do",
        http_status=200,
        encrypted_fields=("password",),
        field_names=("username", "password"),
    )
    base.update(kwargs)
    return SubmitResult(**base)


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = make_account.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class MakeAccountTest(unittest.TestCase):
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
            make_account, "submit_registration", return_value=_result()
        )
        self.submit = p2.start()
        self.addCleanup(p2.stop)

    def test_dry_run_writes_nothing(self):
        self.submit.return_value = _result(
            ok=False, kind="dry_run", message="dry-run", http_status=None
        )
        code, out, err = run([])
        self.assertEqual(code, 0)
        self.assertIn("DRY-RUN", err)
        self.assertIn("DRY-RUN", out)
        self.assertNotIn(Path("accounts.json"), list(Path(".").iterdir()))
        self.assertTrue(self.submit.call_args.kwargs["dry_run"])

    def test_success_saves_account_0600(self):
        code, out, _ = run(["--yes"])
        self.assertEqual(code, 0)
        self.assertIn("abc12345", out)
        path = Path("accounts.json")
        self.assertTrue(path.exists())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["username"], "abc12345")
        self.assertEqual(data[0]["password"], "Abc123456")
        self.assertFalse(data[0]["ok"] is False)

    def test_rejected_exit_1_no_file(self):
        self.submit.return_value = _result(
            ok=False, kind="rejected", message="用户名已被注册"
        )
        code, out, _ = run(["--yes"])
        self.assertEqual(code, 1)
        self.assertIn("rejected", out)
        self.assertFalse(Path("accounts.json").exists())

    def test_unknown_exit_1_still_saves(self):
        self.submit.return_value = _result(
            ok=False, kind="unknown", message="结果未知"
        )
        code, out, _ = run(["--yes"])
        self.assertEqual(code, 1)
        self.assertIn("不要立即重跑", out)
        data = json.loads(Path("accounts.json").read_text(encoding="utf-8"))
        self.assertEqual(data[0]["kind"], "unknown")

    def test_gb18030_sfz_txt(self):
        Path("sfz.txt").write_bytes(
            ("张三|" + VALID_ID + "\n").encode("gb18030")
        )
        self.submit.return_value = _result(
            ok=False, kind="dry_run", message="dry-run", http_status=None
        )
        code, _, err = run([])
        self.assertEqual(code, 0)
        self.assertIn("GB18030", err)
        self.assertEqual(self.prepare.call_count, 1)

    def test_skips_invalid_lines_by_default(self):
        Path("sfz.txt").write_text(
            "bad|not-an-id\n李四|11010119900101004X\n", encoding="utf-8"
        )
        self.submit.return_value = _result(
            ok=False, kind="dry_run", message="dry-run", http_status=None
        )
        code, _, err = run([])
        self.assertEqual(code, 0)
        self.assertIn("已跳过 1 行", err)
        self.assertIn("行号：1", err)
        self.assertEqual(self.prepare.call_args.args[0].realname, "李四")

    def test_strict_mode_errors_on_invalid_line(self):
        Path("sfz.txt").write_text(
            "bad|not-an-id\n李四|11010119900101004X\n", encoding="utf-8"
        )
        code, _, err = run(["--strict"])
        self.assertEqual(code, 2)
        self.assertIn("错误", err)
        self.prepare.assert_not_called()

    def test_index_selects_second_valid_profile(self):
        Path("sfz.txt").write_text(
            "张三|" + VALID_ID + "\n李四|11010119900101004X\n",
            encoding="utf-8",
        )
        self.submit.return_value = _result(
            ok=False, kind="dry_run", message="dry-run", http_status=None
        )
        code, _, err = run(["--index", "2"])
        self.assertEqual(code, 0)
        self.assertIn("使用第 2 条", err)
        self.assertEqual(self.prepare.call_args.args[0].realname, "李四")

    def test_index_out_of_range(self):
        code, _, err = run(["--index", "9"])
        self.assertEqual(code, 2)
        self.assertIn("越界", err)

    def test_missing_profile_exit_2(self):
        Path("sfz.txt").unlink()
        code, _, err = run([])
        self.assertEqual(code, 2)
        self.assertIn("错误", err)
        self.submit.assert_not_called()

    def test_json_output_dry_run(self):
        self.submit.return_value = _result(
            ok=False, kind="dry_run", message="dry-run", http_status=None
        )
        code, out, _ = run(["--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["result"]["kind"], "dry_run")
        self.assertIsNone(data["password"])

    def test_append_keeps_existing(self):
        Path("accounts.json").write_text(
            json.dumps([{"username": "old"}]), encoding="utf-8"
        )
        make_account._append_account(
            Path("accounts.json"),
            {"username": "new", "password": "x"},
        )
        data = json.loads(Path("accounts.json").read_text(encoding="utf-8"))
        self.assertEqual([item["username"] for item in data], ["old", "new"])


if __name__ == "__main__":
    unittest.main()
