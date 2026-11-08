"""web 图形验证码（150×45）的自学习识别器。

为什么不能像 unified 那样直接用模板：web 这套验证码有两种渲染风格
（细线描边 + 3D 实心块），而且带斜体，跟 unified 的 60×30 不是同一套字形。
实测把 150×45 缩到 60×30 再套 unified 模板、或者用 9 个样本做模板匹配，
字符准确率都只有 18%~33%，不够用。

所以这里走「自学习」：字形先做**骨架化**（描边和实心块细化后形状接近），
归一化后按 chamfer 距离做最近邻；每成功解一次（服务端 ``verifyCode`` 判定通过）
就把这次的 4 个字形连同答案存进字库。用得越多越准。

>>> from gen4399.captcha_web import learning_captcha_solver
>>> solver = learning_captcha_solver()      # doctest: +SKIP
>>> solver(png_bytes)                       # doctest: +SKIP
'98FW'
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from ._captcha import CaptchaSolverError

__all__ = [
    "WebCaptchaBank",
    "learning_captcha_solver",
    "default_bank_path",
    "segment_glyphs",
]

#: 字形归一化后的画布尺寸
_W, _H = 24, 32
#: 二值化阈值（RGB 均值）
_THR = 190
#: 每个字符最多保留多少个样本
_MAX_PER_CHAR = 12
#: chamfer 距离超过这个值就不敢认（交给人工）
_MAX_DISTANCE = 4.2


def default_bank_path() -> Path:
    """默认字库位置（``~/.gen4399/web_captcha_bank.json``）。"""
    return Path.home() / ".gen4399" / "web_captcha_bank.json"


def seed_bank_path() -> Path:
    """随库附带的种子字库（26 个已标注样本）。"""
    return Path(__file__).with_name("_web_captcha_seed.json")


def _decode(image: bytes) -> tuple[int, int, bytes]:
    """用 ImageMagick 把任意图片解成 RGB 像素。"""
    tool = shutil.which("magick") or shutil.which("convert")
    if tool is None:
        raise CaptchaSolverError("需要 ImageMagick（magick/convert）来解码验证码图片")
    proc = subprocess.run(
        [tool, "-", "-depth", "8", "ppm:-"], input=image, capture_output=True
    )
    if proc.returncode != 0 or not proc.stdout.startswith(b"P6"):
        raise CaptchaSolverError("验证码图片解码失败")
    parts = proc.stdout.split(b"\n", 3)
    if len(parts) < 4:
        raise CaptchaSolverError("验证码图片格式异常")
    width, height = (int(v) for v in parts[1].split())
    return width, height, parts[3]


def _rows(image: bytes) -> tuple[int, int, list[int]]:
    width, height, data = _decode(image)
    rows = []
    for y in range(height):
        bits = 0
        base = y * width * 3
        for x in range(width):
            i = base + x * 3
            if (data[i] + data[i + 1] + data[i + 2]) // 3 < _THR:
                bits |= 1 << x
        rows.append(bits)
    return width, height, rows


def _spans(width: int, height: int, rows: list[int]) -> list[tuple[int, int]]:
    cols = [sum(1 for y in range(height) if rows[y] >> x & 1) for x in range(width)]
    spans: list[tuple[int, int]] = []
    start = None
    for x in range(width):
        if cols[x] and start is None:
            start = x
        elif not cols[x] and start is not None:
            spans.append((start, x - 1))
            start = None
    if start is not None:
        spans.append((start, width - 1))
    merged: list[tuple[int, int]] = []
    for a, b in spans:
        if merged and a - merged[-1][1] <= 2:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    return _force_four(merged, cols)


def _force_four(
    spans: list[tuple[int, int]], cols: list[int]
) -> list[tuple[int, int]]:
    """把列投影得到的区间强行整理成 4 段。

    验证码固定 4 个字符，但 3D 块状字形常和相邻字符粘在一起（得到 3 段），
    或者噪声把某一笔断开（得到 5 段）。这里按「墨量最少处」切开、
    按「间隙最小」合并。
    """
    spans = list(spans)
    while len(spans) > 4:
        gaps = [
            (spans[i + 1][0] - spans[i][1], i) for i in range(len(spans) - 1)
        ]
        _, idx = min(gaps)
        spans[idx] = (spans[idx][0], spans[idx + 1][1])
        del spans[idx + 1]
    while len(spans) < 4 and spans:
        # 找最宽的一段，在中间区域墨量最少的列切开
        widest = max(range(len(spans)), key=lambda i: spans[i][1] - spans[i][0])
        a, b = spans[widest]
        if b - a < 4:
            break
        lo, hi = a + 2, b - 2
        cut = min(range(lo, hi + 1), key=lambda x: cols[x]) if hi >= lo else (a + b) // 2
        spans[widest:widest + 1] = [(a, cut), (cut + 1, b)]
    return spans


def _thin(sub: list[list[int]], max_iter: int = 40) -> list[list[int]]:
    """Zhang-Suen 细化（把描边 / 实心块都收敛成单像素骨架）。"""
    h, w = len(sub), len(sub[0])
    changed = True
    iteration = 0
    while changed and iteration < max_iter:
        changed = False
        iteration += 1
        for step in (0, 1):
            marked = []
            for y in range(1, h - 1):
                row_up, row, row_dn = sub[y - 1], sub[y], sub[y + 1]
                for x in range(1, w - 1):
                    if not row[x]:
                        continue
                    p = [
                        row_up[x], row_up[x + 1], row[x + 1], row_dn[x + 1],
                        row_dn[x], row_dn[x - 1], row[x - 1], row_up[x - 1],
                    ]
                    total = sum(p)
                    if total < 2 or total > 6:
                        continue
                    transitions = sum(
                        1 for i in range(8) if p[i] == 0 and p[(i + 1) % 8] == 1
                    )
                    if transitions != 1:
                        continue
                    p2, p4, p6, p8 = p[0], p[2], p[4], p[6]
                    if step == 0:
                        if p2 and p4 and p6:
                            continue
                        if p4 and p6 and p8:
                            continue
                    else:
                        if p2 and p4 and p8:
                            continue
                        if p2 and p6 and p8:
                            continue
                    marked.append((y, x))
            for y, x in marked:
                sub[y][x] = 0
                changed = True
    return sub


def _normalize(points: set[tuple[int, int]]) -> list[list[int]]:
    if not points:
        return []
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    gw = max(1, x1 - x0)
    gh = max(1, y1 - y0)
    out = set()
    for x, y in points:
        nx = min(_W - 1, max(0, (x - x0) * _W // gw))
        ny = min(_H - 1, max(0, (y - y0) * _H // gh))
        out.add((nx, ny))
    return [[x, y] for x, y in sorted(out)]


def segment_glyphs(image: bytes) -> list[list[list[int]]]:
    """把验证码切成 4 个归一化字形（骨架点集）。

    Returns:
        长度为 4 的列表；切不出 4 个字形时返回空列表。
    """
    try:
        width, height, rows = _rows(image)
    except CaptchaSolverError:
        return []
    spans = _spans(width, height, rows)
    if len(spans) != 4:
        return []
    glyphs = []
    for x0, x1 in spans:
        ys = [y for y in range(height) if any(rows[y] >> x & 1 for x in range(x0, x1 + 1))]
        if not ys:
            return []
        y0, y1 = min(ys), max(ys)
        sub = [
            [1 if (rows[y] >> x & 1) else 0 for x in range(x0, x1 + 1)]
            for y in range(y0, y1 + 1)
        ]
        thinned = _thin(sub)
        pts = {
            (x0 + x, y0 + y)
            for y in range(len(thinned))
            for x in range(len(thinned[0]))
            if thinned[y][x]
        }
        glyphs.append(_normalize(pts))
    return glyphs


#: 打包字符集：x(0-23) 和 y(0-31) 各占一个字符
_PACK = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


def _pack(points: list[list[int]]) -> str:
    """把点集压成一个短字符串（每点 2 字符），用于字库存储。"""
    return "".join(_PACK[x] + _PACK[y] for x, y in points)


def _unpack(text: str) -> list[list[int]]:
    """``_pack`` 的逆运算；也兼容 ``[[x, y], ...]`` 的旧格式。"""
    if isinstance(text, list):
        return text
    return [
        [_PACK.index(text[i]), _PACK.index(text[i + 1])]
        for i in range(0, len(text) - 1, 2)
    ]


#: 数据增强：每个样本再生成 ±1 像素平移的变体（实测字符准确率 73% → 80%）
_SHIFTS = ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))


def _variants(points: list[list[int]]) -> list[list[list[int]]]:
    """生成平移增强后的变体（用于匹配，不写回字库）。"""
    out = [points]
    for dx, dy in _SHIFTS[1:]:
        out.append(
            [
                [min(_W - 1, max(0, x + dx)), min(_H - 1, max(0, y + dy))]
                for x, y in points
            ]
        )
    return out


def _distance_map(points: list[list[int]]) -> list[int]:
    """对 24×32 网格做一次距离变换，之后求 chamfer 就是 O(点数)。

    曼哈顿距离用两遍扫描（前向 + 后向）即可，纯整数运算。
    """
    inf = 10_000
    grid = [inf] * (_W * _H)
    for x, y in points:
        grid[y * _W + x] = 0
    # 前向
    for y in range(_H):
        for x in range(_W):
            idx = y * _W + x
            best = grid[idx]
            if x:
                best = min(best, grid[idx - 1] + 1)
            if y:
                best = min(best, grid[idx - _W] + 1)
            grid[idx] = best
    # 后向
    for y in range(_H - 1, -1, -1):
        for x in range(_W - 1, -1, -1):
            idx = y * _W + x
            best = grid[idx]
            if x + 1 < _W:
                best = min(best, grid[idx + 1] + 1)
            if y + 1 < _H:
                best = min(best, grid[idx + _W] + 1)
            grid[idx] = best
    return grid


def _chamfer(points: list[list[int]], dmap: list[int]) -> float:
    if not points:
        return 99.0
    return sum(dmap[y * _W + x] for x, y in points) / len(points)


def _distance(a: list[list[int]], b: list[list[int]]) -> float:
    if not a or not b:
        return 99.0
    return (_chamfer(a, _distance_map(b)) + _chamfer(b, _distance_map(a))) / 2


class WebCaptchaBank:
    """字形字库：``字符 -> [归一化骨架点集, ...]``。"""

    def __init__(self, path: "str | os.PathLike[str] | None" = None) -> None:
        self.path = Path(path) if path is not None else default_bank_path()
        self.glyphs: dict[str, list[list[list[int]]]] = {}
        self._maps: dict[tuple, list[int]] = {}
        self.load()
        if not self.glyphs:
            # 用户字库还不存在 → 先用随库附带的种子，保证开箱即用
            self.path = seed_bank_path() if Path(self.path) == default_bank_path() else self.path
            self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(raw, dict):
            self.glyphs = {
                str(k): [_unpack(g) for g in v if g]
                for k, v in raw.items()
                if isinstance(v, list)
            }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        packed = {
            char: [_pack(g) for g in samples]
            for char, samples in self.glyphs.items()
        }
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, json.dumps(packed, ensure_ascii=False).encode("utf-8"))
        finally:
            os.close(fd)
        os.replace(tmp, self.path)

    def __len__(self) -> int:
        return sum(len(v) for v in self.glyphs.values())

    def add(self, char: str, glyph: list[list[int]]) -> None:
        """把一个字形样本加进字库（每个字符最多 ``_MAX_PER_CHAR`` 个）。"""
        if not glyph or len(char) != 1:
            return
        bucket = self.glyphs.setdefault(char, [])
        bucket.append(glyph)
        if len(bucket) > _MAX_PER_CHAR:
            del bucket[0]
        self._maps.clear()

    def match(self, glyph: list[list[int]]) -> tuple[str, float]:
        """返回 ``(最可能的字符, 距离)``；字库为空时返回 ``("?", 99.0)``。"""
        scored = self.rank(glyph)
        if not scored:
            return "?", 99.0
        return scored[0][1], scored[0][0]

    def rank(self, glyph: list[list[int]]) -> list[tuple[float, str]]:
        """按距离从近到远返回 ``[(距离, 字符), ...]``（含平移增强）。"""
        if not glyph or not self.glyphs:
            return []
        query_map = _distance_map(glyph)
        out: list[tuple[float, str]] = []
        for char, samples in self.glyphs.items():
            best = 99.0
            for idx, sample in enumerate(samples):
                for vidx, variant in enumerate(_variants(sample)):
                    key = (char, idx, vidx)
                    dmap = self._maps.get(key)
                    if dmap is None:
                        dmap = self._maps[key] = _distance_map(variant)
                    d = (_chamfer(variant, query_map) + _chamfer(glyph, dmap)) / 2
                    if d < best:
                        best = d
            out.append((best, char))
        out.sort()
        return out


def _accepts_hint(fn) -> bool:
    try:
        import inspect

        return len(inspect.signature(fn).parameters) >= 2
    except (TypeError, ValueError):  # pragma: no cover
        return False


def learning_captcha_solver(
    bank_path: "str | os.PathLike[str] | None" = None,
    *,
    prompt=None,
    out=None,
    max_distance: float = _MAX_DISTANCE,
    min_margin: float = 0.2,
):
    """构造一个「先查字库、没把握就问人」的 web 验证码识别器。

    Args:
        bank_path: 字库路径，默认 ``~/.gen4399/web_captcha_bank.json``。
        prompt: 人工输入函数 ``(图片字节) -> str``；不给就不问。
        out: 提示输出流（默认 stdout）。
        max_distance: 最近邻距离超过它就认为「没把握」。
        min_margin: 最近两个候选的距离差小于它也算「没把握」（宁可不答）。

    Returns:
        ``solver(image_bytes) -> str``，并带一个
        ``solver.feedback(image_bytes, code, accepted)`` 方法：解对时把字形存进字库。
    """
    bank = WebCaptchaBank(bank_path)
    fallback = prompt

    def solver(image: bytes) -> str:
        glyphs = segment_glyphs(image)
        guess = ""
        sure = True
        for glyph in glyphs:
            ranked = bank.rank(glyph)
            if not ranked:
                sure = False
                guess += "?"
                continue
            best_d, best_c = ranked[0]
            other = next((d for d, c in ranked if c != best_c), 99.0)
            if best_d > max_distance or (other - best_d) < min_margin:
                sure = False
            guess += best_c
        if sure and len(guess) == 4 and "?" not in guess:
            return guess
        if fallback is not None:
            hint = f"（自动识别把握不大，参考：{guess}）" if guess else ""
            return fallback(image, hint) if _accepts_hint(fallback) else fallback(image)
        return guess

    def feedback(image: bytes, code: str, accepted: bool) -> None:
        """服务端判定通过时，把这四段字形连同答案写进字库。"""
        if not accepted or len(code) != 4:
            return
        glyphs = segment_glyphs(image)
        if len(glyphs) != 4:
            return
        for char, glyph in zip(code, glyphs):
            bank.add(char.upper(), glyph)
        try:
            bank.save()
        except OSError:
            pass

    solver.feedback = feedback  # type: ignore[attr-defined]
    solver.bank = bank  # type: ignore[attr-defined]
    return solver
