"""CLI：batch 与 captcha 子命令。"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gen4399 import cli
from gen4399.batch import BatchItem, BatchSummary

ID_A = "460206194611192084"


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class TestBatchCommand(unittest.TestCase):
    def _summary(self, ok=True):
        return BatchSummary(
            items=[BatchItem(1, "user1", "success" if ok else "rejected", ok, "msg")]
        )

    def test_dry_run_exit_0(self):
        with mock.patch("gen4399.batch.run_batch", return_value=self._summary(dry := False) if False else BatchSummary(items=[BatchItem(1, "u", "dry_run", False, "dry")])), \
             mock.patch("gen4399.cli._load_identity_profiles",
                        return_value=[mock.Mock(idcard=ID_A)]):
            code, out, _ = run([
                "batch", "--offline", "--realname", "张三", "--idcard", ID_A,
                "--interval", "0",
            ])
        self.assertEqual(code, 0)
        self.assertIn("dry_run", out)

    def test_success_exit_0_and_json(self):
        with mock.patch("gen4399.batch.run_batch", return_value=self._summary()), \
             mock.patch("gen4399.cli._load_identity_profiles",
                        return_value=[mock.Mock(idcard=ID_A)]):
            code, out, _ = run([
                "batch", "--offline", "--realname", "张三", "--idcard", ID_A,
                "--interval", "0", "--yes", "--json",
            ])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["success"], 1)

    def test_failure_exit_1(self):
        with mock.patch("gen4399.batch.run_batch",
                        return_value=self._summary(ok=False)), \
             mock.patch("gen4399.cli._load_identity_profiles",
                        return_value=[mock.Mock(idcard=ID_A)]):
            code, _, _ = run([
                "batch", "--offline", "--realname", "张三", "--idcard", ID_A,
                "--interval", "0", "--yes",
            ])
        self.assertEqual(code, 1)

    def test_count_limits_profiles(self):
        profiles = [mock.Mock(idcard=ID_A) for _ in range(5)]
        with mock.patch("gen4399.batch.run_batch",
                        return_value=self._summary()) as runner, \
             mock.patch("gen4399.cli._load_identity_profiles",
                        return_value=profiles):
            run([
                "batch", "--offline", "--realname", "张三", "--idcard", ID_A,
                "--interval", "0", "--yes", "-c", "2",
            ])
        self.assertEqual(len(runner.call_args.args[0]), 2)


class TestCaptchaCommand(unittest.TestCase):
    def test_solve(self):
        with mock.patch(
            "gen4399.captcha_web.learning_captcha_solver",
            return_value=lambda img: "ABCD",
        ):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "c.png"
                path.write_bytes(b"x")
                code, out, _ = run(["captcha", "solve", str(path)])
        self.assertEqual(code, 0)
        self.assertIn("ABCD", out)

    def test_label_writes_bank(self):
        glyphs = [[[1, 2]], [[3, 4]], [[5, 6]], [[7, 8]]]
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "imgs"
            src.mkdir()
            (src / "a.png").write_bytes(b"x")
            bank_path = Path(tmp) / "bank.json"
            with mock.patch(
                "gen4399.captcha_web.segment_glyphs", return_value=glyphs
            ), mock.patch("builtins.input", return_value="ABCD"):
                code, out, _ = run([
                    "captcha", "label", str(src), "--bank", str(bank_path),
                ])
            self.assertEqual(code, 0)
            self.assertTrue(bank_path.exists())
            self.assertIn("已标注 1 张", out)

    def test_label_missing_dir(self):
        code, _, err = run(["captcha", "label", "/nonexistent-dir-xyz"])
        self.assertEqual(code, 2)
        self.assertIn("错误", err)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
