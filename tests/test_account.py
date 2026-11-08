"""gen4399.account：账号记录与落盘。"""

import json
import stat
import tempfile
import unittest
from pathlib import Path

from gen4399.account import account_record, append_account, load_accounts
from gen4399.forms import RegistrationProfile
from gen4399.registration import prepare_registration
from gen4399.submit import SubmitResult


def _bundle():
    return prepare_registration(
        RegistrationProfile("张三", "460206194611192084"),
        path="web", verify_username=False,
    )


def _result(**kw):
    base = dict(ok=True, kind="success", message="注册成功", username="abc",
                path="web", app_id="", endpoint="x")
    base.update(kw)
    return SubmitResult(**base)


class TestAccountRecord(unittest.TestCase):
    def test_record_shape(self):
        bundle = _bundle()
        record = account_record(bundle, _result())
        self.assertEqual(record["username"], bundle.username)
        self.assertEqual(record["password"], bundle.password)
        self.assertEqual(record["kind"], "success")
        self.assertIn("created_at", record)
        self.assertIn("*", record["idcard_masked"])

    def test_created_at_override(self):
        record = account_record(_bundle(), _result(), created_at="2026-01-01T00:00:00")
        self.assertEqual(record["created_at"], "2026-01-01T00:00:00")


class TestAppendAccount(unittest.TestCase):
    def test_creates_file_with_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "accounts.json"
            append_account(path, {"username": "a"})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(json.loads(path.read_text()), [{"username": "a"}])

    def test_appends_to_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "accounts.json"
            path.write_text(json.dumps([{"username": "old"}]), encoding="utf-8")
            append_account(path, {"username": "new"})
            data = json.loads(path.read_text())
        self.assertEqual([d["username"] for d in data], ["old", "new"])

    def test_corrupt_file_is_replaced_with_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "accounts.json"
            path.write_text("not json", encoding="utf-8")
            warnings = []
            append_account(path, {"username": "a"}, warn=warnings.append)
            data = json.loads(path.read_text())
        self.assertEqual(len(warnings), 1)
        self.assertEqual([d["username"] for d in data], ["a"])

    def test_load_accounts_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_accounts(Path(tmp) / "nope.json"), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
