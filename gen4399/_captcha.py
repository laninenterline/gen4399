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
    "command_captcha_solver",
    "prompt_captcha_solver",
    "save_captcha_images",
]

#: 识别回调：图片原始字节 -> 验证码文本
CaptchaSolver = Callable[[bytes], str]


class CaptchaSolverError(Gen4399Error):
    """验证码识别回调/外部识别命令失败（可被 CLI 统一捕获）。"""


def _write_image(image: bytes, directory: str | os.PathLike[str]) -> Path:
    """把验证码图片写进目录，返回文件路径（文件名带毫秒时间戳）。"""
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"
    file_path = path / f"captcha-{stamp}.png"
    file_path.write_bytes(image)
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
    prompt_text: str = "请输入验证码：",
    input_fn: Callable[[str], str] = input,
    out: object = sys.stderr,
) -> CaptchaSolver:
    """人工识别：把图片写到磁盘并提示输入（适合本机/手机/图形界面）。

    Args:
        directory: 图片落地目录；``None`` 表示临时目录。
        prompt_text: 提示语。
        input_fn: 读取输入的函数（默认 :func:`input`，测试可替换）。
        out: 提示输出的流（默认 stderr）。
    """

    def solver(image: bytes) -> str:
        target = directory
        if target is None:
            target = tempfile.mkdtemp(prefix="gen4399-captcha-")
        path = _write_image(image, target)
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


def make_solver(
    *,
    prompt: bool = False,
    command: str | None = None,
    directory: str | os.PathLike[str] | None = None,
) -> CaptchaSolver | None:
    """按 CLI 参数组合出 solver；都不给时返回 ``None``（不识别验证码）。"""
    if command:
        solver: CaptchaSolver = command_captcha_solver(command)
    elif prompt:
        return prompt_captcha_solver(directory=directory)
    else:
        return None
    if directory is not None:
        solver = save_captcha_images(solver, directory)
    return solver
