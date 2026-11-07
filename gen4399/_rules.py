"""内置 4399 注册规则的版本与来源信息（内部模块）。

4399 前端随时可能改规则。这里记录"本版本库的规则核对时间与来源"，
配合 ``scripts/verify_rules.py`` 做定期回归。
"""

from __future__ import annotations

#: 规则快照版本
RULES_VERSION = "4399-2026-11"

#: 最近一次人工核对日期（ISO）
RULES_CHECKED_AT = "2026-11-07"

#: 规则来源页面
RULES_SOURCES = (
    "https://web.4399.com/user/reg.php",
    "https://u.4399.com/register.html",
    "https://ptlogin.4399.com/ptlogin/regFrame.do",
)

#: 用于 verify_rules.py 做冒烟检查的关键字符串
RULE_KEYWORDS = (
    "CheakPWD",
    "CheakUsername",
    "6~20",
    "字母和数字",
)

__all__ = [
    "RULES_VERSION",
    "RULES_CHECKED_AT",
    "RULES_SOURCES",
    "RULE_KEYWORDS",
]
