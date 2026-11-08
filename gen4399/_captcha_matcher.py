"""4399 60×30 验证码识别（移植自 guiwow1337/4399-captcha 的 matcher.c）。

算法（见上游 README/matcher.c）：白底 + 细条纹 + 4 个互相叠压的彩色字形。
本实现用「包含判定」而不是相关/IoU：

1. 灰度 < 170 记为墨；
2. 25 个手扣字形模板在 4 个槽位的窗口内滑动，**允许滑出图外**
   （图外的墨像素既不算溢出也不算界内，直接忽略）；
3. 每个槽位挑「溢出最少」的模板，溢出相同再挑墨量最少的，
   并要求界内墨 ≥ 模板墨量的 60%。

上游对同一批验证码报 100% 正确率；本移植保留同样的常量与判据。

依赖：解码用本机 ImageMagick（``magick`` / ``convert``），只做 JPEG→灰度 PGM。

License: MIT, Copyright (c) 2026 _zrs（数据见 _captcha_templates.py）。
"""

from __future__ import annotations

import shutil
import subprocess

from ._captcha_templates import INK_OFF, TEMPLATES

__all__ = ["recognize", "MatcherError", "IMAGE_WIDTH", "IMAGE_HEIGHT"]

IMAGE_WIDTH = 60
IMAGE_HEIGHT = 30
_PADY = 16
_PADX = 16
_THR = 170
_IMG_MASK = (1 << IMAGE_WIDTH) - 1


class MatcherError(RuntimeError):
    """识别失败（解码不了 / 尺寸不对 / 没有可用的解码工具）。"""


def _build_templates():
    built = []
    for ch, _th, _tw, nink, need, off, clo, chi in TEMPLATES:
        rows: dict[int, int] = {}
        for j in range(nink):
            dy = INK_OFF[off + 2 * j]
            dx = INK_OFF[off + 2 * j + 1]
            rows[dy] = rows.get(dy, 0) | (1 << dx)
        built.append((ch, need, clo, chi, tuple(rows.items())))
    return tuple(built)


_TMPL = _build_templates()


def _decode_ppm(image: bytes) -> bytes:
    """用 ImageMagick 把任意图片转成 8 位 RGB PPM。

    注意必须保留 RGB：上游用 ``(R+G+B)/3`` 做二值化，而 ImageMagick 的
    灰度是加权亮度，对彩色字形结果会不一样（这点差异足以让识别全错）。
    """
    tool = shutil.which("magick") or shutil.which("convert")
    if not tool:
        raise MatcherError(
            "需要本机 ImageMagick（magick/convert）来解码验证码图片"
        )
    try:
        completed = subprocess.run(
            [tool, "-", "-depth", "8", "ppm:-"],
            input=image,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise MatcherError(f"调用 ImageMagick 失败：{exc}") from exc
    if completed.returncode != 0 or not completed.stdout:
        raise MatcherError("ImageMagick 解码验证码失败")
    return completed.stdout


def _ink_rows(image: bytes) -> list[int]:
    """把图片转成逐行的墨位图（bit x = 列 x）。"""
    ppm = _decode_ppm(image)
    if not ppm.startswith(b"P6"):
        raise MatcherError("不是 PPM 数据")
    parts = ppm.split(b"\n", 3)
    if len(parts) < 4:
        raise MatcherError("PPM 头不完整")
    width, height = (int(v) for v in parts[1].split())
    data = parts[3]
    if (width, height) != (IMAGE_WIDTH, IMAGE_HEIGHT):
        raise MatcherError(f"尺寸是 {width}x{height}，不是 60x30")
    rows = []
    for y in range(height):
        base = y * width * 3
        bits = 0
        for x in range(width):
            i = base + x * 3
            if (data[i] + data[i + 1] + data[i + 2]) // 3 < _THR:
                bits |= 1 << x
        rows.append(bits)
    return rows


def classify(rows: list[int]) -> str:
    """对 4 个槽位各挑一个模板，返回 4 个字符。"""
    out = []
    for slot in range(4):
        best_vio = 10 ** 9
        best_ink = -1
        best_ch = "?"
        for ch, need, clo, chi, row_masks in _TMPL:
            for anchor_r in range(IMAGE_HEIGHT + _PADY):
                iy0 = anchor_r - _PADY
                for anchor_c in range(clo[slot], chi[slot] + 1):
                    ix0 = anchor_c - _PADX
                    vio = 0
                    ov = 0
                    too_much = False
                    for dy, mask in row_masks:
                        iy = iy0 + dy
                        if iy < 0 or iy >= IMAGE_HEIGHT:
                            continue
                        shifted = (
                            (mask << ix0) & _IMG_MASK
                            if ix0 >= 0
                            else (mask >> -ix0)
                        )
                        if not shifted:
                            continue
                        ov += shifted.bit_count()
                        vio += (shifted & ~rows[iy] & _IMG_MASK).bit_count()
                        if vio > best_vio:
                            too_much = True
                            break
                    if too_much or ov < need:
                        continue
                    if vio < best_vio or (
                        vio == best_vio and len(row_masks) < best_ink
                    ):
                        best_vio = vio
                        best_ink = len(row_masks)
                        best_ch = ch
        out.append(best_ch)
    return "".join(out)


def recognize(image: bytes) -> str:
    """识别一张 60×30 的 4399 验证码，返回 4 个字符。

    Raises:
        MatcherError: 解码失败、尺寸不对或没有 ImageMagick。
    """
    return classify(_ink_rows(image))
