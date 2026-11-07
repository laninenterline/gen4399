#!/usr/bin/env python3
"""每次运行尝试获取一个 4399 账号。

用法::

    python scripts/make_account.py                    # dry-run（默认：不提交、不建号）
    python scripts/make_account.py --yes              # 真实提交（需本人真实身份）
    python scripts/make_account.py --yes --form-path web
    python scripts/make_account.py --yes --profile-file ids.txt

身份文件默认为当前目录的 ``sfz.txt``，每行 ``姓名|身份证号[|QQ]``；本脚本每次
只使用第一条身份。真实提交需要**本人**真实姓名与身份证号（4399 会做实名核验），
使用他人/伪造身份可能违法，也违反 4399 用户协议。

成功（或被判定为 unknown 但已发出 POST）时，账号会追加写入 ``accounts.json``
（权限 0600，含明文密码，请妥善保管）。``unknown`` 表示服务端结果不确定，
请先用用户名/密码登录 https://u.4399.com/ 确认，**不要立即重跑**。

退出码：0 成功或 dry-run；1 被拒 / 需要验证码 / 结果未知；2 参数、网络或配置错误。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
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
    load_profiles,
    prepare_registration,
    submit_registration,
)
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
    p.add_argument("--output", default="accounts.json", metavar="FILE",
                   help="账号保存文件，默认 ./accounts.json（0600）")
    p.add_argument("--json", action="store_true", help="以 JSON 输出本次结果")
    return p


def _load_profile(path: str, encoding: str | None) -> RegistrationProfile:
    if encoding:
        profiles = load_profiles(path, encoding=encoding)
    else:
        try:
            profiles = load_profiles(path, encoding="utf-8-sig")
        except UnicodeDecodeError:
            profiles = load_profiles(path, encoding="gb18030")
            print(
                "# 提示：身份文件不是 UTF-8，已按 GB18030 读取",
                file=sys.stderr,
            )
    if not profiles:
        raise ValueError(f"{path} 中没有有效身份")
    if len(profiles) > 1:
        print(
            f"# 注意：{path} 有 {len(profiles)} 条身份，本脚本只使用第 1 条",
            file=sys.stderr,
        )
    return profiles[0]


def _append_account(path: Path, record: dict) -> None:
    """把账号记录追加到 JSON 文件（保持 0600）。"""
    existing: list = []
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = [existing]
        except (OSError, json.JSONDecodeError):
            print(f"# 警告：{path} 不是合法 JSON，将覆盖写入", file=sys.stderr)
            existing = []
    existing.append(record)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, json.dumps(existing, ensure_ascii=False, indent=2).encode("utf-8"))
    finally:
        os.close(fd)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - 非 POSIX
        pass


def _print_result(result: SubmitResult, bundle, *, show_credentials: bool) -> None:
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
        print(f"  保存到: {result.path}")
    if result.kind == "unknown":
        print("  警告：结果未知；请先登录 https://u.4399.com/ 确认，"
              "不要立即重跑 --yes")


def _make_record(bundle, result: SubmitResult) -> dict:
    return {
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "path": result.path,
        "username": bundle.username,
        "password": bundle.password,
        "kind": result.kind,
        "ok": result.ok,
        "message": result.message,
        "endpoint": result.endpoint,
        "http_status": result.http_status,
        "idcard_masked": bundle.masked_idcard(),
    }


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        policy = None
        if args.retries is not None:
            policy = RetryPolicy(attempts=max(1, args.retries))
        profile = _load_profile(args.profile_file, args.profile_encoding)
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
        )
        result = submit_registration(
            bundle,
            app_id=args.app_id,
            level=args.level,
            timeout=args.timeout,
            dry_run=not args.yes,
            retry_policy=policy,
        )
    except (Gen4399Error, TypeError, ValueError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    if args.json:
        payload = {
            "result": result.to_dict(),
            "username": bundle.username,
            "password": None if result.kind == "dry_run" else bundle.password,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_result(result, bundle, show_credentials=True)
        print(f"  身份证: {bundle.masked_idcard()}")

    if result.kind in ("success", "unknown"):
        try:
            _append_account(Path(args.output), _make_record(bundle, result))
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
