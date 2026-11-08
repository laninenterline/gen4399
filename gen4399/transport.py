"""传输层选项：超时、代理/代理池、随机 User-Agent。

把「怎么连」和「发什么」分开：:func:`submit_registration` 等函数只关心后者，
需要代理或换 UA 时传一个 :class:`TransportOptions` 即可。

>>> from gen4399.transport import TransportOptions
>>> from gen4399.proxy import ProxyPool
>>> opts = TransportOptions(proxy="127.0.0.1:8080", random_user_agent=True)
>>> opts.pick_proxy()
'http://127.0.0.1:8080'
"""

from __future__ import annotations

from dataclasses import dataclass

from .proxy import ProxyPool, normalize_proxy
from .remote import DEFAULT_TIMEOUT, RetryPolicy, _http
from .ua import random_user_agent

__all__ = ["TransportOptions", "build_transport"]


@dataclass(frozen=True)
class TransportOptions:
    """一次调用使用的传输配置。

    Attributes:
        timeout: 单次请求超时（秒）。
        proxy: 单个 HTTP(S) 代理；与 ``proxy_pool`` 互斥（池优先）。
        proxy_pool: 代理池；每次 :meth:`new_session` 按策略取一个。
        random_user_agent: 是否为每个会话随机生成 User-Agent。
        retry_policy: GET 重试策略（POST 永远单次）。
        sticky: 是否「粘住」第一个代理——整个注册流程（查重 + 提交）用同一个 IP。
            默认 False（每次 :meth:`new_session` 轮换）。
    """

    timeout: float = DEFAULT_TIMEOUT
    proxy: str | None = None
    proxy_pool: ProxyPool | None = None
    random_user_agent: bool = False
    retry_policy: RetryPolicy | None = None
    sticky: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.timeout, (int, float)) or isinstance(self.timeout, bool):
            raise TypeError("timeout 必须是数字")
        if self.timeout <= 0:
            raise ValueError("timeout 必须 > 0")
        if self.proxy is not None:
            object.__setattr__(self, "proxy", normalize_proxy(self.proxy))
        if self.proxy_pool is not None and not isinstance(self.proxy_pool, ProxyPool):
            raise TypeError("proxy_pool 必须是 ProxyPool")
        if self.proxy is not None and self.proxy_pool is not None:
            raise ValueError("proxy 与 proxy_pool 只能二选一（池优先，不必同时给）")
        # frozen dataclass 里放一个可变小容器，用来缓存 sticky 选中的代理
        object.__setattr__(self, "_sticky_slot", [None])

    def pick_proxy(self) -> str | None:
        """按配置取本次要用的代理（没有则 ``None`` = 直连）。

        ``sticky=True`` 时第一次选中的代理会被缓存，之后一直返回它，
        直到调用 :meth:`reset_sticky`。
        """
        if self.proxy_pool is None:
            return self.proxy
        if not self.sticky:
            return self.proxy_pool.next()
        slot = self._sticky_slot
        if slot[0] is None:
            slot[0] = self.proxy_pool.next()
        return slot[0]

    def reset_sticky(self) -> None:
        """清掉 sticky 缓存（下次 :meth:`pick_proxy` 会重新选一个代理）。"""
        self._sticky_slot[0] = None

    def new_session(self, *, referer: str | None = None) -> "_http.RemoteSession":
        """按配置创建一个新的 :class:`RemoteSession`。"""
        kwargs = {
            "timeout": self.timeout,
            "policy": self.retry_policy,
            "proxy": self.pick_proxy(),
            "user_agent": random_user_agent() if self.random_user_agent else None,
        }
        if referer is not None:
            kwargs["referer"] = referer
        return _http.RemoteSession(**kwargs)


def build_transport(
    *,
    proxy: str | None = None,
    proxy_file: str | None = None,
    proxy_strategy: str = "round-robin",
    random_user_agent: bool = False,
    timeout: float = DEFAULT_TIMEOUT,
    retry_policy: RetryPolicy | None = None,
    sticky: bool = False,
) -> TransportOptions | None:
    """按「命令行式」参数拼一个 :class:`TransportOptions`。

    没有任何代理/随机 UA 需求时返回 ``None``（调用方据此走默认会话）。

    Args:
        proxy: 单个代理 URL。
        proxy_file: 代理池文件路径（优先于 ``proxy``）。
        proxy_strategy: ``round-robin`` / ``random``。
        random_user_agent: 是否每个会话随机 UA。
        timeout: 单次请求超时。
        retry_policy: GET 重试策略。

    Raises:
        ProxyError: 代理或代理池文件不合法。
        OSError: 代理文件读不了。
    """
    pool = None
    if proxy_file:
        pool = ProxyPool.from_file(proxy_file, strategy=proxy_strategy)
    if not proxy and pool is None and not random_user_agent:
        return None
    return TransportOptions(
        timeout=timeout,
        proxy=proxy,
        proxy_pool=pool,
        random_user_agent=random_user_agent,
        retry_policy=retry_policy,
        sticky=sticky,
    )
