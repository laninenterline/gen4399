"""gen4399._captcha 的单元测试：人工输入 / 外部命令 / 图片落盘。

全部离线：外部命令测试用当前解释器 ``python3 -c`` 回显 stdin，
不依赖真实 OCR 工具或网络。``prompt_captcha_solver`` 用 ``input_fn``
打桩，不会阻塞在终端输入上。
"""

import io
import shlex
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gen4399 import _captcha
from gen4399._captcha import (
    CaptchaSolverError,
    command_captcha_solver,
    make_solver,
    prompt_captcha_solver,
    save_captcha_images,
)
from gen4399.core import Gen4399Error

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR-test-image"

#: 当前解释器（Termux 下 ``python3`` 存在，但用 sys.executable 最稳）
_PYTHON = shlex.quote(sys.executable)


def py_command(code: str) -> str:
    """构造 ``python3 -c <code>`` 的 shell 命令行（shell=True 用）。"""
    return f"{_PYTHON} -c {shlex.quote(code)}"


def mode_of(path: Path) -> int:
    """取文件权限位（例如 ``0o600``）。"""
    return stat.S_IMODE(path.stat().st_mode)


def fake_clock(*stamps: float) -> mock.Mock:
    """可预测的 ``time`` 替身：固定 strftime，毫秒后缀按顺序取值。"""
    clock = mock.Mock()
    clock.strftime.return_value = "20260101-120000"
    clock.time.side_effect = list(stamps)
    return clock


class TestPromptCaptchaSolver(unittest.TestCase):
    """人工识别：图片必须落盘（0600），提示语透传给 input_fn。"""

    def test_writes_image_and_returns_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            prompts = []
            out = io.StringIO()

            def input_fn(prompt):
                prompts.append(prompt)
                return "a8b9"

            solver = prompt_captcha_solver(
                directory=tmp,
                prompt_text="看图输入：",
                input_fn=input_fn,
                out=out,
            )
            self.assertEqual(solver(PNG_BYTES), "a8b9")
            self.assertEqual(prompts, ["看图输入："])

            files = list(Path(tmp).glob("captcha-*.png"))
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].read_bytes(), PNG_BYTES)
            self.assertIn(str(files[0]), out.getvalue())
            self.assertIn("图片已保存", out.getvalue())

    def test_default_prompt_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            prompts = []
            solver = prompt_captcha_solver(
                directory=tmp,
                input_fn=lambda prompt: prompts.append(prompt) or "",
                out=io.StringIO(),
            )
            solver(b"img")
            self.assertEqual(prompts, ["请输入验证码："])

    def test_creates_missing_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "a" / "b"
            solver = prompt_captcha_solver(
                directory=target,
                input_fn=lambda _prompt: "x",
                out=io.StringIO(),
            )
            solver(PNG_BYTES)
            files = list(target.glob("captcha-*.png"))
            self.assertEqual(len(files), 1)

    def test_saved_file_is_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            solver = prompt_captcha_solver(
                directory=tmp,
                input_fn=lambda _prompt: "x",
                out=io.StringIO(),
            )
            solver(PNG_BYTES)
            files = list(Path(tmp).glob("captcha-*.png"))
            self.assertEqual(mode_of(files[0]), 0o600)

    def test_default_directory_uses_mkdtemp(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with mock.patch(
                "gen4399._captcha.tempfile.mkdtemp", return_value=tmp
            ) as mkdtemp:
                solver = prompt_captcha_solver(
                    input_fn=lambda _prompt: "code", out=out
                )
                self.assertEqual(solver(b"img"), "code")
            mkdtemp.assert_called_once_with(prefix="gen4399-captcha-")
            files = list(Path(tmp).glob("captcha-*.png"))
            self.assertEqual(len(files), 1)
            self.assertIn(str(files[0]), out.getvalue())

    def test_strips_nothing_from_input(self):
        """输入原样返回（去空白由 submit 层负责）。"""
        with tempfile.TemporaryDirectory() as tmp:
            solver = prompt_captcha_solver(
                directory=tmp,
                input_fn=lambda _prompt: "  ab  ",
                out=io.StringIO(),
            )
            self.assertEqual(solver(b"img"), "  ab  ")


class TestSaveCaptchaImages(unittest.TestCase):
    """给任意 solver 套一层「先存图」：不改变返回值，调用次数一致。"""

    def test_wraps_solver_and_saves_each_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            seen = []

            def inner(image):
                seen.append(image)
                return "code-1"

            with mock.patch("gen4399._captcha.time", fake_clock(0.5, 1.25)):
                wrapped = save_captcha_images(inner, tmp)
                self.assertEqual(wrapped(b"img-1"), "code-1")
                self.assertEqual(wrapped(b"img-2"), "code-1")

            self.assertEqual(seen, [b"img-1", b"img-2"])
            files = sorted(Path(tmp).glob("captcha-*.png"))
            by_name = {f.name: f.read_bytes() for f in files}
            self.assertEqual(
                by_name,
                {
                    "captcha-20260101-120000-500.png": b"img-1",
                    "captcha-20260101-120000-250.png": b"img-2",
                },
            )
            for path in files:
                self.assertEqual(mode_of(path), 0o600)

    def test_creates_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "dir"
            wrapped = save_captcha_images(lambda _image: "x", target)
            self.assertEqual(wrapped(b"img"), "x")
            self.assertEqual(len(list(target.glob("captcha-*.png"))), 1)


class TestCommandCaptchaSolver(unittest.TestCase):
    """外部命令识别：PNG 走 stdin，stdout 第一行是结果。"""

    def test_reads_png_from_stdin_and_returns_first_line(self):
        code = (
            "import sys; d = sys.stdin.buffer.read(); "
            "sys.stdout.write(d.hex() + chr(10) + 'ignored line')"
        )
        solver = command_captcha_solver(py_command(code))
        self.assertEqual(solver(PNG_BYTES), PNG_BYTES.hex())

    def test_stderr_ignored_and_unicode_kept(self):
        code = (
            "import sys; sys.stdin.buffer.read(); "
            "sys.stderr.write('warn text' + chr(10)); "
            "sys.stdout.write('验证码 42')"
        )
        solver = command_captcha_solver(py_command(code))
        self.assertEqual(solver(b"x"), "验证码 42")

    def test_stdout_is_stripped(self):
        code = (
            "import sys; sys.stdin.buffer.read(); "
            "sys.stdout.write(chr(10) + '  ab12  ' + chr(10))"
        )
        solver = command_captcha_solver(py_command(code))
        self.assertEqual(solver(b"x"), "ab12")

    def test_empty_stdout_returns_empty_string(self):
        solver = command_captcha_solver(
            py_command("import sys; sys.stdin.buffer.read()")
        )
        self.assertEqual(solver(b"x"), "")

    def test_whitespace_only_stdout_returns_empty_string(self):
        code = (
            "import sys; sys.stdin.buffer.read(); "
            "sys.stdout.write('    ' + chr(10) + '  ')"
        )
        solver = command_captcha_solver(py_command(code))
        self.assertEqual(solver(b"x"), "")

    def test_nonzero_exit_raises_solver_error(self):
        code = (
            "import sys; sys.stderr.write('ocr broken'); sys.exit(3)"
        )
        solver = command_captcha_solver(py_command(code))
        with self.assertRaises(CaptchaSolverError) as ctx:
            solver(b"x")
        message = str(ctx.exception)
        self.assertIn("退出码 3", message)
        self.assertIn("ocr broken", message)

    def test_timeout_raises_solver_error(self):
        solver = command_captcha_solver(
            py_command("import time; time.sleep(5)"), timeout=0.2
        )
        with self.assertRaises(CaptchaSolverError) as ctx:
            solver(b"x")
        message = str(ctx.exception)
        self.assertIn("超时", message)
        self.assertIn("0.2s", message)

    def test_error_is_gen4399_error(self):
        self.assertTrue(issubclass(Gen4399Error))
        error = CaptchaSolverError("boom")
        self.assertIsInstance(error, Gen4399Error)
        self.assertEqual(str(error), "boom")


class TestMakeSolver(unittest.TestCase):
    """make_solver 的三种组合：都不给 / prompt / command（command 优先）。"""

    def test_none_returns_none(self):
        self.assertIsNone(make_solver())
        self.assertIsNone(
            make_solver(prompt=False, command=None, directory="/tmp/unused")
        )

    def test_prompt_only(self):
        sentinel = object()
        with mock.patch(
            "gen4399._captcha.prompt_captcha_solver", return_value=sentinel
        ) as factory:
            solver = make_solver(prompt=True)
        self.assertIs(solver, sentinel)
        factory.assert_called_once_with(directory=None, zoom=1)

    def test_prompt_with_directory(self):
        sentinel = object()
        with mock.patch(
            "gen4399._captcha.prompt_captcha_solver", return_value=sentinel
        ) as factory:
            solver = make_solver(prompt=True, directory="/tmp/caps")
        self.assertIs(solver, sentinel)
        factory.assert_called_once_with(directory="/tmp/caps", zoom=1)

    def test_command_only(self):
        solver = make_solver(command="echo from-command")
        self.assertTrue(callable(solver))
        self.assertEqual(solver(b"png"), "from-command")

    def test_command_wins_over_prompt(self):
        with mock.patch(
            "gen4399._captcha.prompt_captcha_solver"
        ) as factory:
            solver = make_solver(prompt=True, command="echo combo")
        factory.assert_not_called()
        self.assertEqual(solver(b"png"), "combo")

    def test_command_with_directory_saves_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            solver = make_solver(command="echo saved", directory=tmp)
            self.assertEqual(solver(PNG_BYTES), "saved")
            files = list(Path(tmp).glob("captcha-*.png"))
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].read_bytes(), PNG_BYTES)
            self.assertEqual(mode_of(files[0]), 0o600)

    def test_prompt_with_directory_does_not_double_wrap(self):
        """prompt solver 自己已经落盘，make_solver 不应再套 save 层。"""
        sentinel = object()
        with mock.patch(
            "gen4399._captcha.prompt_captcha_solver", return_value=sentinel
        ) as factory, mock.patch(
            "gen4399._captcha.save_captcha_images"
        ) as save:
            solver = make_solver(prompt=True, directory="/tmp/caps")
        self.assertIs(solver, sentinel)
        save.assert_not_called()
        factory.assert_called_once_with(directory="/tmp/caps", zoom=1)


class TestPackageExports(unittest.TestCase):
    """_captcha 的公开符号已从 gen4399 包顶层导出。"""

    def test_top_level_exports(self):
        import gen4399

        self.assertIs(gen4399.CaptchaSolverError)
        self.assertIs(gen4399.prompt_captcha_solver, prompt_captcha_solver)
        self.assertIs(gen4399.command_captcha_solver, command_captcha_solver)
        self.assertIs(gen4399.save_captcha_images, save_captcha_images)
        self.assertIs(gen4399.make_solver, make_solver)
        self.assertIs(_captcha.CaptchaSolverError)


if __name__ == "__main__":
    unittest.main()


class TestAutoCaptchaSolver(unittest.TestCase):
    """auto_captcha_solver：有 OCR 用 OCR，没有就退回人工输入。"""

    def test_falls_back_to_prompt_without_ocr(self):
        from gen4399._captcha import auto_captcha_solver

        sentinel = object()

        def fake_prompt(_image):
            return sentinel

        with mock.patch("gen4399._captcha.shutil.which", return_value=None), \
             mock.patch(
                 "gen4399._captcha.prompt_captcha_solver",
                 return_value=fake_prompt,
             ):
            solver = auto_captcha_solver()
            # 内置识别器对随手给的字节会失败，于是回退到人工输入
            self.assertIs(solver(b"\xff\xd8not-a-captcha"), sentinel)

    def test_raises_without_ocr_and_no_fallback(self):
        from gen4399._captcha import auto_captcha_solver

        with mock.patch("gen4399._captcha.shutil.which", return_value=None):
            solver = auto_captcha_solver(prompt_fallback=False)
        with self.assertRaises(CaptchaSolverError):
            solver(b"\xff\xd8not-a-captcha")

    def test_uses_ocr_command_when_available(self):
        from gen4399._captcha import auto_captcha_solver

        seen = {}

        def fake_run(cmd, input=None, shell=None, capture_output=None,
                     timeout=None, check=None):
            seen["cmd"] = cmd
            seen["input"] = input
            return mock.Mock(returncode=0, stdout=b"XY99\n", stderr=b"")

        with mock.patch("gen4399._captcha.shutil.which", return_value="/usr/bin/tesseract"), \
             mock.patch("gen4399._captcha.subprocess.run", side_effect=fake_run):
            solver = auto_captcha_solver()
            self.assertEqual(solver(b"\x89PNGdata"), "XY99")
        self.assertIn("tesseract", seen["cmd"])
        self.assertEqual(seen["input"], b"\x89PNGdata")

    def test_make_solver_auto(self):
        from gen4399._captcha import make_solver

        sentinel = object()
        with mock.patch(
            "gen4399._captcha.auto_captcha_solver", return_value=sentinel
        ) as factory:
            self.assertIs(make_solver(auto=True), sentinel)
        factory.assert_called_once_with()

    def test_make_solver_command_wins_over_auto(self):
        from gen4399._captcha import make_solver

        with mock.patch("gen4399._captcha.auto_captcha_solver") as factory:
            solver = make_solver(command="echo hi", auto=True)
        factory.assert_not_called()
        self.assertTrue(callable(solver))


class TestZoom(unittest.TestCase):
    """prompt solver 的放大选项（依赖可选的本机 ImageMagick）。"""

    def test_upscale_noop_for_factor_one(self):
        from gen4399._captcha import _upscale

        self.assertIsNone(_upscale(b"img", 1))

    def test_upscale_without_tool(self):
        from gen4399._captcha import _upscale

        with mock.patch("gen4399._captcha.shutil.which", return_value=None):
            self.assertIsNone(_upscale(b"img", 6))

    def test_upscale_uses_tool(self):
        from gen4399._captcha import _upscale

        completed = mock.Mock(returncode=0, stdout=b"PNGDATA")
        with mock.patch("gen4399._captcha.shutil.which", return_value="/usr/bin/magick"), \
             mock.patch("gen4399._captcha.subprocess.run", return_value=completed) as run:
            self.assertEqual(_upscale(b"img", 6), b"PNGDATA")
        self.assertIn("600%", run.call_args.args[0])

    def test_upscale_tool_failure_returns_none(self):
        from gen4399._captcha import _upscale

        completed = mock.Mock(returncode=1, stdout=b"")
        with mock.patch("gen4399._captcha.shutil.which", return_value="/usr/bin/magick"), \
             mock.patch("gen4399._captcha.subprocess.run", return_value=completed):
            self.assertIsNone(_upscale(b"img", 6))

    def test_write_image_uses_upscaled_bytes(self):
        import tempfile
        from pathlib import Path

        from gen4399._captcha import _write_image

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch("gen4399._captcha._upscale", return_value=b"BIGPNG"):
            path = _write_image(b"orig", tmp, zoom=6)
            self.assertEqual(Path(path).read_bytes(), b"BIGPNG")
            self.assertTrue(path.name.endswith(".png"))

    def test_write_image_falls_back_to_raw(self):
        import tempfile
        from pathlib import Path

        from gen4399._captcha import _write_image

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch("gen4399._captcha._upscale", return_value=None):
            path = _write_image(b"orig", tmp, zoom=6)
            self.assertEqual(Path(path).read_bytes(), b"orig")


class TestMatcher(unittest.TestCase):
    """内置识别器（60×30，移植 guiwow1337/4399-captcha）。"""

    def test_templates_loaded(self):
        from gen4399._captcha_templates import INK_OFF, TEMPLATES

        self.assertEqual(len(TEMPLATES), 25)
        self.assertGreater(len(INK_OFF), 3000)
        for ch, th, tw, nink, need, off, clo, chi in TEMPLATES:
            self.assertEqual(len(ch), 1)
            self.assertLessEqual(need, nink)
            self.assertEqual(len(clo), 4)
            self.assertEqual(len(chi), 4)
            self.assertLessEqual(off + nink * 2, len(INK_OFF))

    def test_recognize_requires_decoder(self):
        from gen4399._captcha_matcher import MatcherError, recognize

        with mock.patch("gen4399._captcha_matcher.shutil.which", return_value=None):
            with self.assertRaises(MatcherError):
                recognize(b"\xff\xd8fake")

    def test_classify_returns_four_chars_from_charset(self):
        from gen4399._captcha_matcher import classify
        from gen4399._captcha_templates import TEMPLATES

        charset = {t[0] for t in TEMPLATES}
        out = classify([0] * 30)     # 全白图：上游实现会挑「墨最少」的模板
        self.assertEqual(len(out), 4)
        self.assertTrue(set(out) <= charset, out)

    def test_matcher_solver_wraps_error(self):
        from gen4399._captcha import matcher_captcha_solver

        solver = matcher_captcha_solver()
        with mock.patch("gen4399._captcha_matcher.shutil.which", return_value=None):
            with self.assertRaises(CaptchaSolverError):
                solver(b"\xff\xd8fake")


class TestMatcherDecode(unittest.TestCase):
    """matcher 的解码路径（用假的 ImageMagick 输出打桩）。"""

    def _ppm(self, fill: int = 255) -> bytes:
        w, h = 60, 30
        return b"P6\n60 30\n255\n" + bytes([fill] * (w * h * 3))

    def test_recognize_with_mocked_magick(self):
        from gen4399._captcha_matcher import recognize

        completed = mock.Mock(returncode=0, stdout=self._ppm())
        with mock.patch("gen4399._captcha_matcher.shutil.which", return_value="/usr/bin/magick"), \
             mock.patch("gen4399._captcha_matcher.subprocess.run", return_value=completed):
            out = recognize(b"fake-jpeg")
        self.assertEqual(len(out), 4)

    def test_wrong_size_raises(self):
        from gen4399._captcha_matcher import MatcherError, recognize

        small = b"P6\n10 10\n255\n" + bytes([255] * (10 * 10 * 3))
        completed = mock.Mock(returncode=0, stdout=small)
        with mock.patch("gen4399._captcha_matcher.shutil.which", return_value="/usr/bin/magick"), \
             mock.patch("gen4399._captcha_matcher.subprocess.run", return_value=completed):
            with self.assertRaises(MatcherError):
                recognize(b"fake")

    def test_tool_failure_raises(self):
        from gen4399._captcha_matcher import MatcherError, recognize

        completed = mock.Mock(returncode=1, stdout=b"")
        with mock.patch("gen4399._captcha_matcher.shutil.which", return_value="/usr/bin/magick"), \
             mock.patch("gen4399._captcha_matcher.subprocess.run", return_value=completed):
            with self.assertRaises(MatcherError):
                recognize(b"fake")
