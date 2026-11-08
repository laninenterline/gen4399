"""随机 User-Agent 生成（与浏览器真实格式一致，不含 Headless/爬虫标记）。"""

from __future__ import annotations

import random

__all__ = ["random_user_agent"]

#: 各平台的 UA 模板；``{ver}`` 会被替换成对应主版本号
_TEMPLATES: tuple[tuple[str, str], ...] = (
    # Windows Chrome / Edge
    ("windows", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/{ver}.0.0.0 Safari/537.36"),
    ("windows", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/{ver}.0.0.0 Safari/537.36 Edg/{ver}.0.0.0"),
    # macOS Chrome / Safari
    ("mac", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/{ver}.0.0.0 Safari/537.36"),
    ("mac", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/{ver}.0 Safari/605.1.15"),
    # Linux Chrome / Firefox
    ("linux", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/{ver}.0.0.0 Safari/537.36"),
    ("linux", "Mozilla/5.0 (X11; Linux x86_64; rv:{ver}.0) Gecko/20100101 "
              "Firefox/{ver}.0"),
)

#: Chrome / Edge 的主版本号区间（近两年的稳定版）
_CHROMIUM_VERSIONS = tuple(range(120, 133))
#: Firefox 主版本号区间
_FIREFOX_VERSIONS = tuple(range(119, 134))
#: Safari 主版本号区间
_SAFARI_VERSIONS = tuple(range(16, 19))


def random_user_agent(*, rng: random.Random | None = None) -> str:
    """返回一条随机但格式合法的浏览器 User-Agent。

    Args:
        rng: 可选随机源（测试可注入 ``random.Random(seed)``）。

    Returns:
        形如 ``Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...`` 的字符串。
    """
    r = rng or random
    _platform, template = r.choice(_TEMPLATES)
    if "Firefox/" in template:
        version = r.choice(_FIREFOX_VERSIONS)
    elif "Version/" in template:
        version = r.choice(_SAFARI_VERSIONS)
    else:
        version = r.choice(_CHROMIUM_VERSIONS)
    return template.format(ver=version)
