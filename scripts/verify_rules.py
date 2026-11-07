#!/usr/bin/env python3
"""冒烟检查：4399 注册规则页面是否还包含我们依赖的关键信息。

用法::

    python scripts/verify_rules.py            # 检查内置来源
    python scripts/verify_rules.py URL ...    # 检查指定 URL

退出码：0 = 全部命中；1 = 有关键字缺失（规则可能变了）；2 = 网络错误。

注意：本脚本只做 GET + 关键词搜索，不提交任何数据。
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request

from gen4399._rules import RULE_KEYWORDS, RULES_SOURCES, RULES_VERSION

TIMEOUT = 15
UA = "Mozilla/5.0 (compatible; gen4399-rules-check)"


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read(2 * 1024 * 1024).decode("utf-8", errors="replace")


def main(argv: list[str]) -> int:
    urls = argv or list(RULES_SOURCES)
    missing_total = 0
    for url in urls:
        print(f"== {url} ==")
        try:
            html = fetch(url)
        except (urllib.error.URLError, OSError) as exc:
            print(f"  网络错误: {exc}", file=sys.stderr)
            return 2
        missing = [kw for kw in RULE_KEYWORDS if kw not in html]
        if missing:
            missing_total += len(missing)
            print(f"  缺少关键字: {missing}")
        else:
            print(f"  OK（规则版本 {RULES_VERSION} 的关键字全部命中）")
    return 1 if missing_total else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
