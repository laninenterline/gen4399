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

__all__ = ["TransportOptions"]


@dataclass(frozen=True)
class TransportOptions:
    """一次调用使用的传输配置。

    Attributes:
        timeout: 单次请求超时（秒）。
        proxy: 单个 HTTP(S) 代理；与 ``proxy_pool`` 互斥（池优先）。
        proxy_pool: 代理池；每次 :meth:`new_session` 按策略取一个。
        random_user_agent: 是否为每个会话随机生成 User-Agent。
        retry_policy: GET 重试策略（POST 永远单次）。
    """

    timeout: float = DEFAULT_TIMEOUT
    proxy: str | None = None
    proxy_pool: ProxyPool | None = None
    random_user_agent: bool = False
    retry_policy: RetryPolicy | None = None

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

    def pick_proxy(self) -> str | None:
        """按配置取本次要用的代理（没有则 ``None`` = 直连）。"""
        if self.proxy_pool is not None:
            return self.proxy_pool.next()
        return self.proxy

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
