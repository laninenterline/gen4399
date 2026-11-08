"""图形验证码识别回调的现成实现（人工输入 / 外部命令 / 落盘备查）。

:func:`gen4399.submit.submit_registration` 的 ``captcha`` 参数要求一个
``Callable[[bytes], str]``：入参是验证码图片的原始字节（PNG），返回识别出的
文本。本模块提供几个开箱即用的组合，**不做自动破解**：

* :func:`prompt_captcha_solver` —— 把图片存成文件，提示人看图输入；
* :func:`command_captcha_solver` —— 调外部 OCR 命令（PNG 走 stdin，结果走 stdout）；
* :func:`save_captcha_images` —— 给任意 solver 套一层「先把图片存到目录」。

三者都只依赖标准库。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from .core import Gen4399Error

__all__ = [
    "CaptchaSolver",
    "CaptchaSolverError",
    "auto_captcha_solver",
    "command_captcha_solver",
    "prompt_captcha_solver",
    "save_captcha_images",
]

#: 识别回调：图片原始字节 -> 验证码文本
CaptchaSolver = Callable[[bytes], str]


class CaptchaSolverError(Gen4399Error):
    """验证码识别回调/外部识别命令失败（可被 CLI 统一捕获）。"""


def _upscale(image: bytes, factor: int) -> bytes | None:
    """用本机 ImageMagick 把验证码放大（便于人眼识别）；不可用时返回 ``None``。

    只做放大 + 灰度，不改内容；找不到 ``magick`` / ``convert`` 时静默放弃。
    """
    if factor <= 1:
        return None
    tool = shutil.which("magick") or shutil.which("convert")
    if not tool:
        return None
    try:
        completed = subprocess.run(
            [tool, "-", "-colorspace", "Gray", "-filter", "Lanczos",
             "-resize", f"{factor * 100}%", "png:-"],
            input=image, capture_output=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0 or not completed.stdout:
        return None
    return completed.stdout


def _write_image(
    image: bytes,
    directory: str | os.PathLike[str],
    *,
    zoom: int = 1,
) -> Path:
    """把验证码图片写进目录，返回文件路径（文件名带毫秒时间戳）。

    ``zoom > 1`` 时优先写入本机 ImageMagick 放大后的 PNG（便于人眼识别），
    放大不可用则退回原图。
    """
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"
    payload = _upscale(image, zoom)
    file_path = path / f"captcha-{stamp}.png"
    file_path.write_bytes(payload if payload is not None else image)
    try:
        os.chmod(file_path, 0o600)
    except OSError:  # pragma: no cover - 某些文件系统不支持 chmod
        pass
    return file_path


def save_captcha_images(
    solver: CaptchaSolver,
    directory: str | os.PathLike[str],
) -> CaptchaSolver:
    """给 ``solver`` 套一层：每次识别前先把图片存到 ``directory``。"""

    def wrapped(image: bytes) -> str:
        _write_image(image, directory)
        return solver(image)

    return wrapped


def prompt_captcha_solver(
    *,
    directory: str | os.PathLike[str] | None = None,
    zoom: int = 1,
    prompt_text: str = "请输入验证码：",
    input_fn: Callable[[str], str] = input,
    out: object = sys.stderr,
) -> CaptchaSolver:
    """人工识别：把图片写到磁盘并提示输入（适合本机/手机/图形界面）。

    Args:
        directory: 图片落地目录；``None`` 表示临时目录。
        zoom: 放大倍数（需要本机 ImageMagick；``1`` 表示不放大）。
            4399 的 unified 验证码只有 60×30，放大 6~8 倍人眼才好认。
        prompt_text: 提示语。
        input_fn: 读取输入的函数（默认 :func:`input`，测试可替换）。
        out: 提示输出的流（默认 stderr）。
    """

    def solver(image: bytes) -> str:
        target = directory
        if target is None:
            target = tempfile.mkdtemp(prefix="gen4399-captcha-")
        path = _write_image(image, target, zoom=zoom)
        print(f"[验证码] 图片已保存：{path}", file=out)  # type: ignore[arg-type]
        return input_fn(prompt_text)

    return solver


def command_captcha_solver(
    command: str,
    *,
    timeout: float = 30.0,
) -> CaptchaSolver:
    """调外部命令识别：PNG 字节从 stdin 传入，stdout 的第一行作为结果。

    例：``command_captcha_solver("tesseract stdin stdout -l eng --psm 8")``

    Raises:
        CaptchaSolverError: 命令超时或非 0 退出。
    """

    def solver(image: bytes) -> str:
        try:
            completed = subprocess.run(
                command,
                input=image,
                shell=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise CaptchaSolverError(
                f"验证码命令超时（{timeout:g}s）"
            ) from exc
        if completed.returncode != 0:
            raise CaptchaSolverError(
                f"验证码命令退出码 {completed.returncode}："
                f"{completed.stderr.decode('utf-8', 'replace').strip()[:200]}"
            )
        text = completed.stdout.decode("utf-8", "replace").strip()
        return text.splitlines()[0] if text else ""

    return solver


#: 常见 OCR 命令（能找到可执行文件就用它，PNG 走 stdin、结果走 stdout）
_OCR_COMMANDS: tuple[tuple[str, str], ...] = (
    (
        "tesseract",
        "tesseract stdin stdout -l eng --psm 8 "
        "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    ),
)


def _find_ocr_command() -> str | None:
    """返回本机可用的 OCR 命令（找不到返回 ``None``）。"""
    for binary, command in _OCR_COMMANDS:
        if shutil.which(binary):
            return command
    return None


def auto_captcha_solver(
    *,
    prompt_fallback: bool = True,
    timeout: float = 30.0,
) -> CaptchaSolver:
    """自动选一个识别方式：本机有 OCR 就用 OCR，否则退回人工输入。

    找不到 OCR 且 ``prompt_fallback=False`` 时抛 :class:`CaptchaSolverError`。

    注意：这是**调用方侧**的便利封装——本库仍然不内置验证码破解，只是把
    「有 tesseract 就自动用」这件事替你做掉。
    """
    command = _find_ocr_command()
    if command is not None:
        return command_captcha_solver(command, timeout=timeout)
    if prompt_fallback:
        return prompt_captcha_solver()
    raise CaptchaSolverError(
        "本机没有可用的 OCR 命令（未找到 tesseract）；"
        "请改用 --captcha-prompt 人工输入，或用 --captcha-cmd 指定识别命令"
    )


def make_solver(
    *,
    prompt: bool = False,
    command: str | None = None,
    directory: str | os.PathLike[str] | None = None,
    auto: bool = False,
    zoom: int = 1,
) -> CaptchaSolver | None:
    """按 CLI 参数组合出 solver；都不给时返回 ``None``（不识别验证码）。

    优先级：``command`` > ``auto``（有 OCR 用 OCR，否则人工）> ``prompt``。
    """
    if command:
        solver: CaptchaSolver = command_captcha_solver(command)
    elif auto:
        solver = auto_captcha_solver()
    elif prompt:
        return prompt_captcha_solver(directory=directory, zoom=zoom)
    else:
        return None
    if directory is not None:
        solver = save_captcha_images(solver, directory)
    return solver
