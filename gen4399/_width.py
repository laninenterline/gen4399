"""终端显示宽度工具：让中文标签的表格也能对齐（内部模块）。

Python 的 ``str.ljust`` / 格式化是按字符（code point）计数，
而 CJK 字符在终端占 2 列，直接 padding 会导致列错位。
"""

from __future__ import annotations

from unicodedata import east_asian_width

__all__ = ["display_width", "pad"]


def _char_width(ch: str) -> int:
    if unicodedata_east_asian_width(ch) in ("W", "F"):
        return 2
    return 1


def display_width(text: str) -> int:
    """返回字符串在等宽终端下的显示宽度（CJK 字符按 2 列计）。"""
    return sum(_char_width(ch) for ch in text)


def pad(text: str, width: int, *, align: str = "left", fill: str = " ") -> str:
    """按**显示宽度**补空格，返回宽度至少为 ``width`` 的字符串。

    Args:
        text: 原文本（必须已转成 str）。
        width: 目标显示宽度。
        align: ``"left"`` / ``"right"`` / ``"center"``。
        fill: 填充字符（通常是一个空格）。

    Returns:
        补齐后的字符串；原文更宽时原样返回。
    """
    gap = width - display_width(text)
    if gap <= 0:
        return text
    if align == "right":
        return fill * gap + text
    if align == "center":
        left = gap // 2
        return fill * left + text + fill * (gap - left)
    return text + fill * gap


# 为了兼容不同 Python 版本里 unicodedata 的行为，这里显式包一层。
def unicodedata_east_asian_width(ch: str) -> str:
    return east_asian_width(ch)
