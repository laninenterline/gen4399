"""运行期配置（3.0 起替代直接改模块属性）。

2.x 里想改「unified 是否提交实名」只能写
``gen4399.submit.UNIFIED_SEND_REALNAME = False``——那是模块级可变全局，改起来
不直观、也不好在测试里隔离。3.0 提供 :func:`configure` 作为稳定入口，
旧的属性写法仍然有效（内部就是同一个全局，便于测试打桩）。

>>> from gen4399 import configure
>>> configure(unified_send_realname=False)   # doctest: +SKIP
>>> configure()                             # doctest: +SKIP
"""

from __future__ import annotations

__all__ = ["configure", "current_config"]


def configure(*, unified_send_realname: bool | None = None) -> dict[str, bool]:
    """修改运行期配置，返回修改后的全量配置。

    Args:
        unified_send_realname: unified 路径是否提交实名（姓名 + 身份证）。
            传 ``None`` 表示不改。

    Returns:
        当前配置字典，便于打日志 / 断言。

    Examples:
        >>> configure(unified_send_realname=False)["unified_send_realname"]
        False
        >>> configure(unified_send_realname=True)["unified_send_realname"]
        True
    """
    from . import submit

    if unified_send_realname is not None:
        submit.UNIFIED_SEND_REALNAME = bool(unified_send_realname)
    return current_config()


def current_config() -> dict[str, bool]:
    """读取当前运行期配置。"""
    from . import submit

    return {"unified_send_realname": bool(submit.UNIFIED_SEND_REALNAME)}
