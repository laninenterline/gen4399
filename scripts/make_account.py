#!/usr/bin/env python3
"""每次运行尝试获取一个 4399 账号。

用法::

    python scripts/make_account.py                    # dry-run（默认：不提交、不建号）
    python scripts/make_account.py --yes              # 真实提交（需本人真实身份）
    python scripts/make_account.py --yes --form-path web
    python scripts/make_account.py --yes --profile-file ids.txt
    python scripts/make_account.py --yes --index 2        # 用第 2 条有效身份
    python scripts/make_account.py --yes --diagnose       # 保存脱敏后的注册响应，排查 unknown

身份文件默认为当前目录的 ``sfz.txt``，每行 ``姓名|身份证号[|QQ]``；本脚本每次
只使用一条身份（默认第 1 条有效记录，可用 ``--index`` 选择）。默认会**跳过**
文件里的无效行并打印行号，``--strict`` 则遇错立即退出。真实提交需要**本人**
真实姓名与身份证号（4399 会做实名核验），使用他人/伪造身份可能违法，也违反
4399 用户协议。

成功（或被判定为 unknown 但已发出 POST）时，账号会追加写入 ``accounts.json``
（权限 0600，含明文密码，请妥善保管）。``unknown`` 表示服务端结果不确定，
请先用用户名/密码登录 https://u.4399.com/ 确认，**不要立即重跑**。

退出码：0 成功或 dry-run；1 被拒 / 需要验证码 / 结果未知；2 参数、网络或配置错误。
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.parse
import warnings
from datetime import datetime
from pathlib import Path

# 允许从仓库根目录直接运行：python scripts/make_account.py
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from gen4399 import (  # noqa: E402
    DEFAULT_TIMEOUT,
    Gen4399Error,
    RegistrationProfile,
    make_solver,
    prepare_registration,
    submit_registration,
)
from gen4399.account import account_record, append_account  # noqa: E402
from gen4399.identity import load_profiles_auto  # noqa: E402
from gen4399.remote import RetryPolicy  # noqa: E402
from gen4399.submit import SubmitResult  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="make_account.py",
        description="每次运行准备并（在 --yes 时）提交一个 4399 账号",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python scripts/make_account.py                 # dry-run\n"
            "  python scripts/make_account.py --yes           # 真实提交\n"
            "  python scripts/make_account.py --yes --form-path web\n"
            "  python scripts/make_account.py --yes --profile-file ids.txt\n"
            "\n"
            "身份文件默认 ./sfz.txt（姓名|身份证号[|QQ]）；仅可使用本人真实身份。\n"
        ),
    )
    p.add_argument("--yes", action="store_true",
                   help="确认真实提交；不加时只做 dry-run（默认）")
    p.add_argument("--form-path", choices=["unified", "web"], default="unified",
                   help="注册路径，默认 unified（AES 加密 PII 更完整）")
    p.add_argument("--app-id", default="u4399", help="仅 unified 使用，默认 u4399")
    p.add_argument("--level", type=int, default=4, help="仅 unified 使用，默认 4")
    p.add_argument("--profile-file", default="sfz.txt", metavar="FILE",
                   help="身份文件，默认 ./sfz.txt")
    p.add_argument("--profile-encoding", default=None, metavar="ENCODING",
                   help="身份文件编码；默认自动（UTF-8-SIG，失败回退 GB18030）")
    p.add_argument("--index", type=int, default=1, metavar="N",
                   help="使用第 N 条有效身份（1-based），默认 1")
    p.add_argument("--strict", action="store_true",
                   help="身份文件有无效行时立即报错（默认跳过并打印行号）")
    p.add_argument("--username", default=None, help="指定用户名（默认自动生成并查重）")
    p.add_argument("--username-length", type=int, default=None, help="自动用户名长度，默认 12")
    p.add_argument("--password-length", type=int, default=None, help="密码长度，默认 16")
    p.add_argument("--prefix", default="", help="用户名固定前缀（只允许字母数字）")
    p.add_argument("--suffix", default="", help="用户名固定后缀（只允许字母数字）")
    p.add_argument("--offline", action="store_true",
                   help="跳过用户名在线查重（更快，但可能撞名）")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                   help=f"单次请求超时秒数，默认 {DEFAULT_TIMEOUT:g}")
    p.add_argument("--retries", type=int, default=None,
                   help="GET 重试次数（注册 POST 永远单次）")
    p.add_argument("--captcha-prompt", action="store_true",
                   help="遇到图形验证码时保存图片并人工输入（web 路径）")
    p.add_argument("--captcha-matcher", action="store_true",
                   help="用内置识别器（专解 4399 的 60x30 验证码）")
    p.add_argument("--captcha-auto", action="store_true",
                   help="自动选识别方式：有 OCR 用 OCR，否则人工输入")
    p.add_argument("--captcha-cmd", default=None, metavar="CMD",
                   help="用外部命令识别验证码：PNG 从 stdin 传入，stdout 第一行作为结果")
    p.add_argument("--captcha-dir", default=None, metavar="DIR",
                   help="把验证码图片保存到该目录（便于人工查看/留存）")
    p.add_argument("--captcha-zoom", type=int, default=1, metavar="N",
                   help="人工识别时把验证码放大 N 倍（需 ImageMagick）")
    p.add_argument("--proxy", default=None, metavar="URL",
                   help="HTTP(S) 代理，如 http://127.0.0.1:8080")
    p.add_argument("--proxy-file", default=None, metavar="FILE",
                   help="代理池文件：一行一个代理，# 开头为注释")
    p.add_argument("--proxy-strategy", choices=["round-robin", "random"],
                   default="round-robin", help="代理池取用策略")
    p.add_argument("--random-ua", action="store_true",
                   help="每个会话随机生成浏览器 User-Agent")
    p.add_argument("--proxy-sticky", action="store_true",
                   help="粘住代理池里的第一个代理（查重+提交用同一个 IP）")
    p.add_argument("--proxy-check", action="store_true",
                   help="建会话前先探活代理，坏的自动换下一个")
    p.add_argument("--verify-login", action="store_true",
                   help="注册成功后立刻用账号密码登录一次，确认号真的能用")
    p.add_argument("--captcha-attempts", type=int, default=3, metavar="N",
                   help="验证码最多重试轮数，默认 3")
    p.add_argument("--output", default="accounts.json", metavar="FILE",
                   help="账号保存文件，默认 ./accounts.json（0600）")
    p.add_argument("--json", action="store_true", help="以 JSON 输出本次结果")
    p.add_argument("--diagnose", action="store_true",
                   help="保存注册 POST 的脱敏响应（status/URL/可见文本/常见原因），"
                        "排查 unknown/rejected；不改变提交行为")
    p.add_argument("--response-file", default=None, metavar="FILE",
                   help="--diagnose 时保存原始响应 HTML 的路径，"
                        "默认 registration-response-<时间戳>.html（0600）")
    return p


def _build_transport(args, *, timeout, policy):
    """按参数构造 TransportOptions；没有代理/随机 UA 时返回 None。"""
    from gen4399.transport import build_transport

    return build_transport(
        proxy=args.proxy,
        proxy_file=args.proxy_file,
        proxy_strategy=args.proxy_strategy,
        random_user_agent=args.random_ua,
        timeout=timeout,
        retry_policy=policy,
        sticky=args.proxy_sticky,
        verify_proxy=args.proxy_check,
    )


def _load_profile(
    path: str,
    encoding: str | None,
    *,
    index: int = 1,
    strict: bool = False,
) -> RegistrationProfile:
    """读取身份文件并取第 ``index`` 条有效身份（默认跳过无效行）。"""
    errors = "raise" if strict else "skip"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        profiles = load_profiles_auto(
            path, encoding=encoding, errors=errors, out=sys.stderr
        )

    skipped = [
        str(item.message) for item in caught if "跳过" in str(item.message)
    ]
    if skipped:
        lines = re.findall(r"第 (\d+) 行", " ".join(skipped))
        shown = ", ".join(lines[:5])
        if len(lines) > 5:
            shown += " …"
        detail = f"（行号：{shown}）" if shown else ""
        print(
            f"# 注意：已跳过 {len(skipped)} 行无效身份{detail}；"
            "如需严格模式请加 --strict",
            file=sys.stderr,
        )

    if not profiles:
        raise ValueError(f"{path} 中没有有效身份（无效行已跳过）")
    if index < 1 or index > len(profiles):
        raise ValueError(
            f"{path} 只有 {len(profiles)} 条有效身份，--index {index} 越界"
        )
    if len(profiles) > 1:
        print(
            f"# 身份文件共 {len(profiles)} 条有效身份，本次使用第 {index} 条",
            file=sys.stderr,
        )
    return profiles[index - 1]


def _redact_text(text: str, bundle) -> str:
    """把响应里可能回显的密码/身份证/姓名替换成 ***。"""
    for secret in (bundle.password, bundle.idcard, bundle.realname):
        if secret:
            text = text.replace(secret, "***")
    return text


def _visible_text(body: str) -> str:
    body = re.sub(r"<(script|style)\b.*?</\1>", "", body, flags=re.I | re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", body))).strip()


def _diagnose_response(response, bundle, output: str | None) -> None:
    """打印并保存注册 POST 响应的脱敏诊断信息（只写 stderr / 0600 文件）。"""
    body = _redact_text(response.body, bundle)
    text = _visible_text(body)
    parsed = urllib.parse.urlsplit(response.url)
    safe_url = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, "", "")
    )
    content_type = response.headers.get("Content-Type", "?")
    print(f"  [诊断] HTTP {response.status} | 最终 URL: {safe_url}", file=sys.stderr)
    print(f"  [诊断] 响应 {len(response.body)} 字节 | Content-Type: {content_type}",
          file=sys.stderr)
    print(f"  [诊断] 可见文本: {text[:600] or '（空）'}", file=sys.stderr)
    hints = (
        ("验证码", "服务端要求验证码/人机验证，需要人工完成"),
        ("频繁", "很可能触发了频率限制，请降低频率并稍后再试"),
        ("稍后", "服务端繁忙或临时限制，稍后再试"),
        ("实名", "实名核验相关提示，确认姓名与身份证号是本人且一致"),
        ("身份证", "身份证相关校验未通过，检查号码/出生日期/校验码"),
        ("已注册", "用户名/账号已存在，换一个用户名"),
        ("存在", "可能用户名/账号已存在"),
        ("非法", "服务端判定请求非法/风控命中"),
        ("安全", "可能触发安全校验/风控"),
    )
    matched = [hint for keyword, hint in hints if keyword in text]
    for hint in matched:
        print(f"  [诊断] 可能原因: {hint}", file=sys.stderr)
    risk_page = (
        "oauthValidation" in body
        or "fingerprint2" in body
        or 'id="info_page"' in body
        or ("4399提示" in text and "4399用户中心" in text)
    )
    if risk_page:
        print(
            "  [诊断] 这是 4399 的风控/JS 验证提示页（依赖浏览器执行 JS/指纹），"
            "纯 HTTP 提交无法完成注册；请改用官方浏览器/手机号注册。",
            file=sys.stderr,
        )
    if not matched and not risk_page:
        print("  [诊断] 未匹配到已知关键词，请查看保存的响应内容", file=sys.stderr)

    path = Path(output) if output else Path(
        f"registration-response-{datetime.now().strftime('%Y%m%d-%H%M%S')}.html"
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, body.encode("utf-8"))
    finally:
        os.close(fd)
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - 非 POSIX
        pass
    print(f"  [诊断] 原始响应（已脱敏）已保存: {path}", file=sys.stderr)


def _print_result(
    result: SubmitResult, bundle, *, show_credentials: bool, output_path: str
) -> None:
    if result.kind == "dry_run":
        print(f"DRY-RUN: 未提交（字段 {len(result.field_names)} 个，"
              f"加密 {len(result.encrypted_fields)} 个）")
        print(f"  用户名: {bundle.username}")
        print(f"  密码:   {'*' * len(bundle.password)}（真实提交后会显示）")
        print(f"  路径:   {result.path}  端点: {result.endpoint}")
        print("  加 --yes 才会真正提交注册")
        return

    print(f"结果: {result.kind}（ok={result.ok}）")
    print(f"  说明: {result.message}")
    if result.kind in ("success", "unknown"):
        print(f"  用户名: {bundle.username}")
        if show_credentials:
            print(f"  密码:   {bundle.password}")
        print(f"  保存到: {output_path}")
    if result.kind == "unknown":
        print("  警告：结果未知；请先登录 https://u.4399.com/ 确认，"
              "不要立即重跑 --yes")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        policy = None
        if args.retries is not None:
            policy = RetryPolicy(attempts=max(1, args.retries))
        profile = _load_profile(
            args.profile_file,
            args.profile_encoding,
            index=args.index,
            strict=args.strict,
        )
        transport = _build_transport(args, timeout=args.timeout, policy=policy)
        captcha = make_solver(
            prompt=args.captcha_prompt,
            command=args.captcha_cmd,
            directory=args.captcha_dir,
            auto=args.captcha_auto,
            matcher=args.captcha_matcher,
            zoom=args.captcha_zoom,
        )
    except (Gen4399Error, TypeError, ValueError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    if not args.yes:
        print("# DRY-RUN：未加 --yes，不会真正提交注册（加 --yes 才发送 POST）",
              file=sys.stderr)
    else:
        print(
            "# 警告：即将真实提交 4399 注册请求。请确认你使用的是本人真实身份，"
            "并已阅读/遵守 4399 用户协议；禁止批量注册他人账号。",
            file=sys.stderr,
        )

    captured: dict = {}

    def _capture_response(response) -> None:
        captured["response"] = response

    try:
        bundle = prepare_registration(
            profile,
            path=args.form_path,
            username=args.username,
            username_length=args.username_length or 12,
            password_length=args.password_length or 16,
            prefix=args.prefix,
            suffix=args.suffix,
            verify_username=not args.offline,
            app_id=args.app_id,
            timeout=args.timeout,
            retry_policy=policy,
            transport=transport,
        )
        result = submit_registration(
            bundle,
            app_id=args.app_id,
            level=args.level,
            timeout=args.timeout,
            dry_run=not args.yes,
            retry_policy=policy,
            on_response=_capture_response if args.diagnose else None,
            captcha=captcha,
            captcha_attempts=args.captcha_attempts,
            transport=transport,
        )
    except (Gen4399Error, TypeError, ValueError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    login_check = None
    if args.verify_login and result.ok:
        from gen4399.login import login as do_login

        try:
            login_check = do_login(
                bundle.username,
                bundle.password,
                app_id=args.app_id,
                timeout=args.timeout,
                transport=transport,
            )
        except Gen4399Error as exc:
            print(f"# 警告：登录复核失败：{exc}", file=sys.stderr)
    if args.diagnose:
        if "response" in captured:
            _diagnose_response(captured["response"], bundle, args.response_file)
        else:
            print("# [诊断] dry-run 未发送注册 POST，没有响应可诊断", file=sys.stderr)

    if args.json:
        payload = {
            "result": result.to_dict(),
            "username": bundle.username,
            "password": None if result.kind == "dry_run" else bundle.password,
            "login": None if login_check is None else login_check.to_dict(),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_result(
            result, bundle, show_credentials=True, output_path=args.output
        )
        print(f"  身份证: {bundle.masked_idcard()}")
        if login_check is not None:
            if login_check.ok:
                print(f"  登录复核: OK（{len(login_check.cookies)} 个登录 Cookie）")
            else:
                print(f"  登录复核: FAIL[{login_check.kind}] {login_check.message}")

    if result.kind in ("success", "unknown"):
        try:
            append_account(args.output, account_record(bundle, result))
        except OSError as exc:
            print(f"错误：写账号文件失败：{exc}", file=sys.stderr)
            return 2
        if not args.json:
            print(f"  已追加到: {args.output}（0600，含明文密码，请妥善保管）")

    if result.kind == "dry_run":
        return 0
    if result.kind == "success":
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
