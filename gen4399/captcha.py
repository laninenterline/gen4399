"""验证码识别回调的公开入口（实现都在 :mod:`gen4399._captcha`）。

四种用法::

    from gen4399.captcha import prompt_captcha_solver     # 存图 + 人工输入
    from gen4399.captcha import command_captcha_solver    # 调外部 OCR 命令
    from gen4399.captcha import auto_captcha_solver       # 有 OCR 用 OCR，否则人工
    from gen4399.captcha import save_captcha_images       # 只在识别前落盘

本库**不内置验证码破解**：``captcha=`` 回调由调用方提供。
"""

from __future__ import annotations

from ._captcha import (
    CaptchaSolver,
    CaptchaSolverError,
    auto_captcha_solver,
    command_captcha_solver,
    make_solver,
    prompt_captcha_solver,
    save_captcha_images,
)

__all__ = [
    "CaptchaSolver",
    "CaptchaSolverError",
    "auto_captcha_solver",
    "command_captcha_solver",
    "prompt_captcha_solver",
    "save_captcha_images",
    "make_solver",
]
