"""CLI `gen4399 accounts` 子命令测试。"""

import contextlib
import io
import json
import stat
import tempfile
import unittest
from pathlib import Path

from gen4399 import cli


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


_RECORDS = [
    {"created_at": "2026-01-01T00:00:00", "path": "web", "username": "aaa",
     "password": "p1", "kind": "success", "ok": True},
    {"created_at": "2026-01-02T00:00:00", "path": "unified", "username": "bbb",
     "password": "p2", "kind": "unknown", "ok": False},
    {"created_at": "2026-01-03T00:00:00", "path": "web", "username": "aaa",
     "password": "p1", "kind": "success", "ok": True},
]


class TestAccountsCommand(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "accounts.json"
        self.path.write_text(json.dumps(_RECORDS), encoding="utf-8")

    def test_stats(self):
        code, out, _ = run(["accounts", "stats", "--file", str(self.path)])
        self.assertEqual(code, 0)
        self.assertIn("总数: 3", out)
        self.assertIn("成功: 2", out)

    def test_stats_json(self):
        code, out, _ = run(["accounts", "stats", "--file", str(self.path), "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["total"], 3)

    def test_list_masks_password(self):
        code, out, _ = run(["accounts", "list", "--file", str(self.path)])
        self.assertEqual(code, 0)
        self.assertIn("aaa", out)
        self.assertNotIn("p1", out)

    def test_list_include_secrets(self):
        code, out, _ = run([
            "accounts", "list", "--file", str(self.path), "--include-secrets",
        ])
        self.assertEqual(code, 0)
        self.assertIn("p1", out)

    def test_export_csv_to_file(self):
        out_path = Path(self.tmp.name) / "out.csv"
        code, out, _ = run([
            "accounts", "export", "--file", str(self.path),
            "--format", "csv", "--out", str(out_path),
        ])
        self.assertEqual(code, 0)
        self.assertTrue(out_path.exists())
        self.assertEqual(stat.S_IMODE(out_path.stat().st_mode), 0o600)
        self.assertIn("username", out_path.read_text())

    def test_export_jsonl_stdout(self):
        code, out, _ = run([
            "accounts", "export", "--file", str(self.path), "--format", "jsonl",
        ])
        self.assertEqual(code, 0)
        self.assertEqual(len(out.strip().splitlines()), 3)

    def test_dedupe_dry_run_keeps_file(self):
        code, out, _ = run([
            "accounts", "dedupe", "--file", str(self.path), "--dry-run",
        ])
        self.assertEqual(code, 0)
        self.assertIn("可去掉 1 条", out)
        self.assertEqual(len(json.loads(self.path.read_text())), 3)

    def test_dedupe_rewrites(self):
        code, out, _ = run(["accounts", "dedupe", "--file", str(self.path)])
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(self.path.read_text())), 2)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_missing_file_exit_2(self):
        code, _, err = run([
            "accounts", "stats", "--file", str(Path(self.tmp.name) / "nope.json"),
        ])
        self.assertEqual(code, 2)
        self.assertIn("错误", err)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
