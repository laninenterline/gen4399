"""代理池：解析、归一化与轮换。"""

from __future__ import annotations

import os
import random
import urllib.parse
from collections.abc import Iterable, Iterator, Sequence

from .core import Gen4399Error

__all__ = ["ProxyError", "ProxyPool", "normalize_proxy"]


class ProxyError(Gen4399Error):
    """代理配置不合法。"""


def normalize_proxy(raw: str) -> str:
    """把 ``host:port`` / ``scheme://host:port`` 归一化成 urllib 能用的 URL。

    Raises:
        ProxyError: 空串、缺少端口或协议不支持。
    """
    text = (raw or "").strip()
    if not text:
        raise ProxyError("代理不能为空")
    if "://" not in text:
        text = "http://" + text
    parts = urllib.parse.urlsplit(text)
    if parts.scheme not in ("http", "https"):
        raise ProxyError(f"只支持 http/https 代理：{raw!r}")
    if not parts.hostname or not parts.port:
        raise ProxyError(f"代理需要 host:port：{raw!r}")
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, "", "", "")
    )


class ProxyPool:
    """一组代理，按策略轮换。

    >>> pool = ProxyPool(["127.0.0.1:8080", "http://127.0.0.1:8081"])
    >>> pool.next()
    'http://127.0.0.1:8080'
    """

    def __init__(
        self,
        proxies: Iterable[str],
        *,
        strategy: str = "round-robin",
        rng: random.Random | None = None,
    ) -> None:
        items = [normalize_proxy(p) for p in proxies if str(p).strip()]
        if not items:
            raise ProxyError("代理池为空")
        if strategy not in ("round-robin", "random"):
            raise ProxyError("strategy 只能是 round-robin 或 random")
        self._items = tuple(items)
        self._strategy = strategy
        self._rng = rng or random
        self._index = 0

    @classmethod
    def from_lines(
        cls,
        lines: Sequence[str],
        *,
        strategy: str = "round-robin",
        rng: random.Random | None = None,
    ) -> "ProxyPool":
        """从文本行构造；``#`` 开头与空行会跳过。"""
        cleaned = [
            line.strip()
            for line in lines
            if line.strip() and not line.strip().startswith("#")
        ]
        return cls(cleaned, strategy=strategy, rng=rng)

    @classmethod
    def from_file(
        cls,
        path: "str | os.PathLike[str]",
        *,
        strategy: str = "round-robin",
        encoding: str = "utf-8",
        rng: random.Random | None = None,
    ) -> "ProxyPool":
        """从文件读取（一行一个代理，``#`` 注释跳过）。"""
        with open(path, encoding=encoding) as fh:
            return cls.from_lines(fh.readlines(), strategy=strategy, rng=rng)

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[str]:
        return iter(self._items)

    def next(self) -> str:
        """按策略取下一个代理。"""
        if self._strategy == "random":
            return self._rng.choice(self._items)
        value = self._items[self._index % len(self._items)]
        self._index += 1
        return value
