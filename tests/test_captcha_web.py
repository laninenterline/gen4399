"""web 验证码自学习识别器（gen4399.captcha_web）的离线测试。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gen4399 import captcha_web
from gen4399.captcha_web import (
    WebCaptchaBank,
    _pack,
    _unpack,
    learning_captcha_solver,
    segment_glyphs,
)


def _glyph(seed: int, n: int = 20):
    """造一个确定性的「字形」点集。"""
    return [[(seed * 3 + i) % 24, (seed * 5 + i) % 32] for i in range(n)]


class TestPacking(unittest.TestCase):
    def test_roundtrip(self):
        pts = [[0, 0], [23, 31], [5, 17]]
        self.assertEqual(_unpack(_pack(pts)), pts)

    def test_unpack_accepts_legacy_list(self):
        pts = [[1, 2], [3, 4]]
        self.assertEqual(_unpack(pts), pts)  # type: ignore[arg-type]


class TestBank(unittest.TestCase):
    def test_empty_bank_returns_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            bank = WebCaptchaBank(Path(tmp) / "empty.json")
        bank.glyphs = {}
        self.assertEqual(bank.match(_glyph(1)), ("?", 99.0))

    def test_add_and_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            bank = WebCaptchaBank(Path(tmp) / "b.json")
        bank.glyphs = {}
        bank.add("A", _glyph(1))
        bank.add("B", _glyph(9))
        char, dist = bank.match(_glyph(1))
        self.assertEqual(char, "A")
        self.assertLess(dist, 1.0)

    def test_caps_samples_per_char(self):
        with tempfile.TemporaryDirectory() as tmp:
            bank = WebCaptchaBank(Path(tmp) / "b.json")
        bank.glyphs = {}
        for i in range(20):
            bank.add("A", _glyph(i))
        self.assertEqual(len(bank.glyphs["A"]), captcha_web._MAX_PER_CHAR)

    def test_save_and_load_packed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "b.json"
            bank = WebCaptchaBank(path)
            bank.glyphs = {}
            bank.add("A", _glyph(3))
            bank.save()
            raw = json.loads(path.read_text())
            self.assertIsInstance(raw["A"][0], str)
            again = WebCaptchaBank(path)
        self.assertEqual(again.match(_glyph(3))[0], "A")

    def test_seed_bank_ships_with_library(self):
        seed = captcha_web.seed_bank_path()
        self.assertTrue(seed.exists())
        data = json.loads(seed.read_text())
        self.assertGreaterEqual(len(data), 20)


class TestLearningSolver(unittest.TestCase):
    def _solver(self, bank_glyphs, prompt=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bank = WebCaptchaBank(Path(tmp.name) / "b.json")
        bank.glyphs = dict(bank_glyphs)
        solver = learning_captcha_solver(Path(tmp.name) / "b.json", prompt=prompt)
        solver.bank.glyphs = dict(bank_glyphs)
        solver.bank._maps.clear()
        return solver

    def test_confident_answer(self):
        glyphs = [_glyph(1), _glyph(9), _glyph(17), _glyph(25)]
        bank = {c: [g] for c, g in zip("ABCD", glyphs)}
        solver = self._solver(bank)
        with mock.patch.object(captcha_web, "segment_glyphs", return_value=glyphs):
            self.assertEqual(solver(b"img"), "ABCD")

    def test_low_margin_falls_back_to_prompt(self):
        glyphs = [_glyph(1)] * 4
        bank = {"A": [_glyph(1)], "B": [_glyph(1)]}
        asked = []

        def prompt_fn(image, hint=""):
            asked.append(hint)
            return "ZZZZ"

        solver = self._solver(bank, prompt=prompt_fn)
        with mock.patch.object(captcha_web, "segment_glyphs", return_value=glyphs):
            self.assertEqual(solver(b"img"), "ZZZZ")
        self.assertTrue(asked)

    def test_feedback_learns(self):
        glyphs = [_glyph(1), _glyph(9), _glyph(17), _glyph(25)]
        solver = self._solver({})
        with mock.patch.object(captcha_web, "segment_glyphs", return_value=glyphs):
            solver.feedback(b"img", "WXYZ", True)
        self.assertEqual(sorted(solver.bank.glyphs), ["W", "X", "Y", "Z"])

    def test_feedback_ignores_rejected(self):
        glyphs = [_glyph(1)] * 4
        solver = self._solver({})
        with mock.patch.object(captcha_web, "segment_glyphs", return_value=glyphs):
            solver.feedback(b"img", "WXYZ", False)
        self.assertEqual(solver.bank.glyphs, {})

    def test_no_prompt_returns_best_guess(self):
        solver = self._solver({})
        with mock.patch.object(captcha_web, "segment_glyphs", return_value=[]):
            self.assertEqual(solver(b"img"), "")


class TestSegmentation(unittest.TestCase):
    def test_bad_image_returns_empty(self):
        self.assertEqual(segment_glyphs(b"not-an-image"), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestSegmentationReal(unittest.TestCase):
    """用合成 PPM 覆盖解码 / 切字 / 细化 / 强制 4 段。"""

    def _ppm(self, blobs):
        w, h = 150, 45
        px = bytearray([255] * (w * h * 3))
        for x0, x1 in blobs:
            for y in range(5, 40):
                for x in range(x0, x1 + 1):
                    i = (y * w + x) * 3
                    px[i:i + 3] = bytes([30, 30, 30])
        return b"P6\n150 45\n255\n" + bytes(px)

    def _run(self, blobs):
        header = self._ppm(blobs)
        completed = mock.Mock(returncode=0, stdout=header)
        with mock.patch(
            "gen4399.captcha_web.shutil.which", return_value="/usr/bin/magick"
        ), mock.patch(
            "gen4399.captcha_web.subprocess.run", return_value=completed
        ):
            return segment_glyphs(b"fake")

    def test_four_blobs(self):
        glyphs = self._run([(10, 25), (40, 55), (70, 85), (100, 115)])
        self.assertEqual(len(glyphs), 4)
        self.assertTrue(all(glyphs))

    def test_three_blobs_split_into_four(self):
        glyphs = self._run([(10, 25), (40, 55), (70, 120)])
        self.assertEqual(len(glyphs), 4)

    def test_five_blobs_merged_into_four(self):
        glyphs = self._run([(10, 25), (32, 40), (50, 65), (80, 95), (110, 125)])
        self.assertEqual(len(glyphs), 4)

    def test_missing_magick_returns_empty(self):
        with mock.patch("gen4399.captcha_web.shutil.which", return_value=None):
            self.assertEqual(segment_glyphs(b"x"), [])


class TestSolverFallbacks(unittest.TestCase):
    def test_no_bank_no_prompt_returns_best_effort(self):
        with tempfile.TemporaryDirectory() as tmp:
            solver = learning_captcha_solver(Path(tmp) / "b.json")
        solver.bank.glyphs = {}
        glyphs = [_glyph(1)] * 4
        with mock.patch.object(captcha_web, "segment_glyphs", return_value=glyphs):
            self.assertEqual(solver(b"img"), "????")

    def test_feedback_with_bad_segmentation_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            solver = learning_captcha_solver(Path(tmp) / "b.json")
        solver.bank.glyphs = {}
        with mock.patch.object(captcha_web, "segment_glyphs", return_value=[]):
            solver.feedback(b"img", "ABCD", True)
        self.assertEqual(solver.bank.glyphs, {})


class TestBenchmark(unittest.TestCase):
    def test_benchmark_counts(self):
        import json as _json

        from gen4399.captcha_web import benchmark

        glyphs = [[[1, 2]], [[3, 4]], [[5, 6]], [[7, 8]]]
        with tempfile.TemporaryDirectory() as tmp:
            dirpath = Path(tmp)
            for stem in ("a", "b"):
                (dirpath / f"{stem}.png").write_bytes(stem.encode())
            (dirpath / "labels.json").write_text(
                _json.dumps({"a": "ABCD", "b": "ABCD", "skip": "A?CD"}),
                encoding="utf-8",
            )
            with mock.patch.object(
                captcha_web, "segment_glyphs", return_value=glyphs
            ):
                stats = benchmark(str(dirpath))
        self.assertEqual(stats["samples"], 2)
        self.assertEqual(stats["total"], 8)
        self.assertGreaterEqual(stats["accuracy"], 0.0)

    def test_benchmark_missing_labels(self):
        from gen4399.captcha_web import benchmark

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                benchmark(tmp)
