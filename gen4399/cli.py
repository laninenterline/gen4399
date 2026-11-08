"""gen4399 的命令行入口。

用法::

    python -m gen4399                       生成密码
    python -m gen4399 -n 20 -c 5
    python -m gen4399 -p lg -s gz
    python -m gen4399 -u                    生成账号名
    python -m gen4399 -u -n 16 -c 3
    python -m gen4399 --check "abc123ABC"   校验密码
    python -m gen4399 --check-username "abc12345"
    python -m gen4399 --fetch-username           从 4399 官方接口取分配账号
    python -m gen4399 --account                  生成账号名+密码（自动查重）
    python -m gen4399 --form-fields web          查看注册表单字段
    python -m gen4399 --check-form NAME PW --realname 张三 --idcard ...
    python -m gen4399 --build-form NAME PW --realname 张三 --idcard ...
    python -m gen4399 --prepare --realname 张三 --idcard ...   一键准备注册数据
    python -m gen4399 --prepare --profile-file ids.txt       从 txt 批量准备
    python -m gen4399 --prepare                              默认读取 ./sfz.txt
    python -m gen4399 submit --realname 张三 --idcard ... --yes  真实提交（unified）
    python -m gen4399 submit --form-path web --realname 张三 --idcard ... --yes
    python -m gen4399 --check-available "abc12345"
    python -m gen4399 --entropy -p abc

全局增强：``--json`` 机器可读输出、``--offline`` 跳过在线查重、
``--output DIR`` 把结果写成 0600 文件、``--min-interval`` 批量限速、
``--verbose`` 打印重试日志。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Sequence

from . import __version__
from ._rules import RULES_CHECKED_AT, RULES_SOURCES, RULES_VERSION
from ._width import pad
from .registration import prepare_registration
from .submit import submit_registration
from ._captcha import make_solver as _make_captcha_solver
from .identity import load_profiles_auto
from .forms import (
    RegistrationProfile,
    build_registration_fields,
    check_registration_form,
    get_form,
)
from .remote import (
    DEFAULT_APP_ID,
    DEFAULT_TIMEOUT,
    RemoteError,
    RetryPolicy,
    check_username,
    fetch_suggested_usernames,
    generate_account,
    generate_available_username,
)
from .core import (
    CHARSET,
    DEFAULT_LENGTH,
    DEFAULT_USERNAME_LENGTH,
    MAX_LENGTH,
    MIN_LENGTH,
    USERNAME_CHARSET,
    USERNAME_MAX_LENGTH,
    USERNAME_MIN_LENGTH,
    Gen4399Error,
    InvalidLengthError,
    entropy_bits,
    generate_many,
    generate_usernames,
    validate,
    validate_username,
)

logger = logging.getLogger("gen4399.cli")

#: 未指定身份来源时默认读取的身份文件名（当前目录下）
DEFAULT_PROFILE_FILE = "sfz.txt"


def build_parser() -> argparse.ArgumentParser:
    """构造参数解析器（独立出来便于测试）。"""
    p = argparse.ArgumentParser(
        prog="gen4399",
        description="生成 / 校验符合 4399 注册规则的密码与账号名",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python -m gen4399                       生成 1 个 16 位密码\n"
            "  python -m gen4399 -n 20 -c 5            生成 5 个 20 位密码\n"
            "  python -m gen4399 -p lg -s gz           指定前缀和后缀\n"
            "  python -m gen4399 -u                    生成 1 个 12 位账号名\n"
            "  python -m gen4399 -u -n 16 -c 3         生成 3 个 16 位账号名\n"
            '  python -m gen4399 --check "Abc12345"    校验密码\n'
            '  python -m gen4399 --check-username "abc12345"\n'
            "  python -m gen4399 --fetch-username      从官方接口取服务端分配账号\n"
            "  python -m gen4399 --account             生成一套账号名+密码（自动查重）\n"
            '  python -m gen4399 --check-available "abc12345"\n'
            "  python -m gen4399 --entropy -p abc      查看熵\n"
            "  python -m gen4399 --prepare --profile-file ids.txt   批量准备\n"
            "  python -m gen4399 submit --realname 张三 --idcard ... --yes\n"
            "  python -m gen4399 --prepare --profile-file ids.txt --json --output out/\n"
        ),
    )
    p.add_argument("-n", "--length", type=int, default=None,
                   help=f"总长度。密码默认 {DEFAULT_LENGTH}（{MIN_LENGTH}~{MAX_LENGTH}），"
                        f"账号名默认 {DEFAULT_USERNAME_LENGTH}"
                        f"（{USERNAME_MIN_LENGTH}~{USERNAME_MAX_LENGTH}）。"
                        "兼容旧语义：-u 时作用于账号名，--account/--prepare 时作用于密码")
    p.add_argument("--password-length", type=int, default=None,
                   help="密码长度（优先于 -n，仅用于密码/账号/准备命令）")
    p.add_argument("--username-length", type=int, default=None,
                   help="账号名长度（优先于 -n，默认 12）")
    p.add_argument("-c", "--count", type=int, default=1,
                   help="生成/批量账号的个数，默认 1")
    p.add_argument("-p", "--prefix", default="",
                   help="自定义前缀（只允许字母和数字），计入总长度")
    p.add_argument("-s", "--suffix", default="",
                   help="自定义后缀（只允许字母和数字），计入总长度")
    p.add_argument("-u", "--username", action="store_true",
                   help="改为生成账号名（字符集为小写字母+数字）")
    p.add_argument("--check", metavar="PASSWORD", default=None,
                   help="校验给定密码是否符合 4399 规则，合规退出码 0，否则 1")
    p.add_argument("--check-username", metavar="NAME", default=None,
                   help="校验给定账号名是否符合 4399 规则，合规退出码 0，否则 1")
    p.add_argument("--fetch-username", nargs="?", type=int, const=1,
                   default=None, metavar="COUNT",
                   help="调用 4399 官方注册面板接口，获取服务端分配的用户名（默认 1 个，"
                        "支持 -p/-s 追加前后缀）")
    p.add_argument("--verify", action="store_true",
                   help="生成账号名后自动调用官方接口确认可注册（配合 -u / --fetch-username）")
    p.add_argument("--account", action="store_true",
                   help="生成账号名+密码；-c 可批量，默认自动查重")
    p.add_argument("--no-verify", action="store_true",
                   help="配合 --account / --prepare 使用，跳过在线查重（离线可用）")
    p.add_argument("--offline", action="store_true",
                   help="跳过在线查重（--prepare/--account 等）；"
                        "提交类命令仍需联网")
    p.add_argument("--check-available", metavar="NAME", default=None,
                   help="调用 4399 官方 isExist.do 查询用户名是否还能注册")
    p.add_argument("--form-fields", choices=["web", "unified"], default=None,
                   metavar="{web,unified}",
                   help="打印某条注册路径的表单字段定义")
    p.add_argument("--check-form", nargs=2, default=None,
                   metavar=("USERNAME", "PASSWORD"),
                   help="本地校验一份注册表单（不联网、不代提交）")
    p.add_argument("--form-path", choices=["web", "unified"], default="web",
                   help="表单相关命令使用的注册路径，默认 web")
    p.add_argument("--realname", default=None, metavar="NAME",
                   help="真实姓名（用于 --check-form / --build-form / --prepare；"
                        "也可改用 --profile-file）")
    p.add_argument("--idcard", default=None, metavar="ID",
                   help="身份证号（用于 --check-form / --build-form / --prepare；"
                        "也可改用 --profile-file）")
    p.add_argument("--qq", default=None, metavar="QQ",
                   help="QQ 号（选填，配合 --realname/--idcard 使用）")
    p.add_argument("--profile-file", metavar="FILE", default=None,
                   help="身份信息 txt：每行「姓名|身份证号[|QQ]」，"
                        "空行和 # 注释跳过；可多行批量，用于 "
                        "--prepare / --submit / --build-form / --check-form；"
                        "'-' 表示 stdin；未指定且未给 --realname/--idcard 时"
                        "默认读取当前目录 sfz.txt")
    p.add_argument("--profile-encoding", default=None, metavar="ENCODING",
                   help="身份文件编码；默认自动（UTF-8-SIG，失败回退 GB18030）")
    p.add_argument("--build-form", nargs=2, default=None,
                   metavar=("USERNAME", "PASSWORD"),
                   help="生成填表清单（参数名=值），不提交")
    p.add_argument("--prepare", action="store_true",
                   help="一键准备注册数据（生成用户名+密码、查重、校验、输出填表清单；不提交）")
    p.add_argument("--submit", action="store_true",
                   help="准备并真实提交注册（web / unified 两条路径；"
                        "默认 dry-run，需同时加 --yes 才会发送请求）")
    p.add_argument("--yes", action="store_true",
                   help="确认真正提交注册（--submit 不加此参数时只做 dry-run）")
    p.add_argument("--app-id", default=None, metavar="APPID",
                   help="提交/查重使用的 appId，默认 u4399")
    p.add_argument("--level", type=int, default=4, metavar="N",
                   help="注册等级 level，默认 4")
    _add_captcha_opts(p)
    _add_transport_opts(p)
    p.add_argument("--show-pii", action="store_true",
                   help="显示明文身份证号/密码/QQ（默认打码）")
    p.add_argument("--entropy", action="store_true",
                   help="只输出熵估算（bit），不生成")
    _add_remote_opts(p)
    _add_io_opts(p)
    p.add_argument("-v", "--verbose", action="store_true",
                   help="输出重试等调试日志")
    p.add_argument("-V", "--version", action="version",
                   version=f"gen4399 {__version__}")
    p.add_argument("--rules-version", action="version",
                   version=f"4399 rules {RULES_VERSION}（核对于 {RULES_CHECKED_AT}）")
    return p


# ---------------------------------------------------------------------------
# 通用小工具
# ---------------------------------------------------------------------------


def _build_transport(args, *, timeout, policy):
    """按 CLI 参数构造 TransportOptions（没有代理/随机 UA 时返回 None）。"""
    from .transport import build_transport

    return build_transport(
        proxy=getattr(args, "proxy", None),
        proxy_file=getattr(args, "proxy_file", None),
        proxy_strategy=getattr(args, "proxy_strategy", "round-robin"),
        random_user_agent=bool(getattr(args, "random_ua", False)),
        timeout=timeout,
        retry_policy=policy,
        sticky=bool(getattr(args, "proxy_sticky", False)),
        verify_proxy=bool(getattr(args, "proxy_check", False)),
    )


def _offline(args) -> bool:
    return bool(args.no_verify or args.offline)


def _retry_policy(args) -> RetryPolicy | None:
    if (
        args.retries is None
        and args.retry_delay is None
        and args.max_total_timeout is None
    ):
        return None
    attempts = 3 if args.retries is None else args.retries
    base_delay = 0.5 if args.retry_delay is None else args.retry_delay
    return RetryPolicy(
        attempts=attempts,
        base_delay=base_delay,
        total_deadline=args.max_total_timeout,
    )


def _emit_json(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _write_json_file(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - 非 POSIX
        pass


def _maybe_output(args, filename: str, obj) -> None:
    if args.output:
        path = Path(args.output) / filename
        _write_json_file(path, obj)
        print(f"# 已写入 {path}", file=sys.stderr)


def _warn_pii(args) -> None:
    if args.show_pii:
        print("# 警告：正在显示明文身份证号/密码/QQ，请勿在共享屏幕/日志中使用",
              file=sys.stderr)


def _report(violations, raw: str) -> int:
    """打印校验结果并返回退出码。"""
    if not violations:
        print(f"OK: {raw}")
        return 0
    print(f"FAIL: {raw}", file=sys.stderr)
    for v in violations:
        print(f"  - [{v.code}] {v.message}", file=sys.stderr)
    return 1


def _print_form_result(res) -> bool:
    """打印表单校验结果，返回是否通过。"""
    for warning in res.warnings:
        print(f"# 提示: {warning}", file=sys.stderr)
    if res.ok:
        print("OK: 表单全部通过")
        return True
    print("FAIL:", file=sys.stderr)
    for msg in res.messages():
        print(f"  - {msg}", file=sys.stderr)
    return False


def _default_profile_file() -> Path:
    """默认身份文件：当前目录下的 ``sfz.txt``。"""
    return Path.cwd() / DEFAULT_PROFILE_FILE


def _load_profiles_auto(path, encoding: str | None):
    """读取身份文件；未显式指定编码时先 UTF-8-SIG，失败回退 GB18030。"""
    return load_profiles_auto(path, encoding=encoding, out=sys.stderr)


def _load_identity_profiles(args):
    """按 --profile-file / --realname+--idcard / 默认 ./sfz.txt 取身份信息。

    未指定任何身份来源（既没有 --profile-file，也没有 --realname/--idcard/--qq）
    时，自动读取当前目录下的 ``sfz.txt``；文件不存在则报错。

    Raises:
        ValueError: 参数缺失、互相冲突，或默认 sfz.txt 不存在。
        OSError: 身份文件无法读取。
        InvalidProfileError: 身份信息不合法。
    """
    if args.profile_file is not None:
        if args.realname or args.idcard:
            raise ValueError(
                "--profile-file 不能与 --realname/--idcard 同时使用"
            )
        if args.qq is not None:
            raise ValueError("--profile-file 不能与 --qq 同时使用")
        encoding = getattr(args, "profile_encoding", None)
        return _load_profiles_auto(args.profile_file, encoding)

    manual = bool(args.realname or args.idcard or args.qq)
    if not manual:
        default = _default_profile_file()
        if default.is_file():
            encoding = getattr(args, "profile_encoding", None)
            return _load_profiles_auto(default, encoding)
        raise ValueError(
            "未指定身份来源：请用 --profile-file 指定文件，或提供 "
            "--realname + --idcard；也可把身份文件放到默认路径 "
            f"{default}（每行：姓名|身份证号[|QQ]）"
        )

    if not (args.realname and args.idcard):
        raise ValueError(
            "需要同时提供 --realname 和 --idcard，或使用 --profile-file"
            f"（未指定时默认读取 {_default_profile_file()}）"
        )
    return [
        RegistrationProfile(
            args.realname, args.idcard, qq=args.qq
        ).require_valid()
    ]


def _display_length(args, as_username: bool) -> int:
    if as_username:
        if args.username_length is not None:
            return args.username_length
        if args.length is not None:
            return args.length
        return DEFAULT_USERNAME_LENGTH
    if args.password_length is not None:
        return args.password_length
    if args.length is not None:
        return args.length
    return DEFAULT_LENGTH


def _sleep_between(args) -> None:
    if args.min_interval and args.min_interval > 0:
        time.sleep(args.min_interval)


# ---------------------------------------------------------------------------
# 各子命令实现
# ---------------------------------------------------------------------------


def _cmd_check(args) -> int:
    """--check / --check-username"""
    if args.check is not None:
        value, violations, kind = args.check, validate(args.check), "password"
    else:
        value = args.check_username
        violations = validate_username(value)
        kind = "username"
    if args.json:
        _emit_json({
            "kind": kind,
            "value": value,
            "ok": not violations,
            "violations": [
                {"code": v.code, "message": v.message} for v in violations
            ],
        })
        return 0 if not violations else 1
    return _report(violations, value)


def _cmd_form_fields(args) -> int:
    form = get_form(args.form_fields)
    if args.json:
        _emit_json({
            "path": form.path,
            "title": form.title,
            "url": form.url,
            "submit_url": form.submit_url,
            "fields": [
                {
                    "name": f.name,
                    "label": f.label,
                    "required": f.required,
                    "kind": f.kind,
                    "maxlength": f.maxlength,
                    "note": f.note,
                }
                for f in form.fields
            ],
        })
        return 0
    print(f"{form.title}  ({form.path})")
    print(f"页面: {form.url}")
    print(f"提交: POST {form.submit_url}")
    print(
        pad("参数名", 18) + pad("标签", 12) + pad("必填", 5)
        + pad("类型", 9) + pad("上限", 5) + "说明"
    )
    print("-" * 78)
    for f in form.fields:
        print(
            pad(f.name, 18) + pad(f.label, 12)
            + pad("是" if f.required else "否", 5)
            + pad(f.kind, 9) + pad(str(f.maxlength or "-"), 5) + f.note
        )
    return 0


def _cmd_check_form(args) -> int:
    username, password = args.check_form
    if args.profile_file is not None:
        try:
            profiles = _load_identity_profiles(args)
        except (Gen4399Error, TypeError, ValueError, OSError) as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 2
        results = []
        failed = False
        for idx, profile in enumerate(profiles, 1):
            res = check_registration_form(
                username, password, path=args.form_path, profile=profile
            )
            results.append(res)
            if len(profiles) > 1 and not args.json:
                print(f"# 身份 {idx}/{len(profiles)}")
            if not args.json and not _print_form_result(res):
                failed = True
            elif args.json and not res.ok:
                failed = True
        if args.json:
            _emit_json([
                {"ok": r.ok, "errors": r.errors, "warnings": r.warnings}
                for r in results
            ])
        return 1 if failed else 0

    res = check_registration_form(
        username,
        password,
        path=args.form_path,
        realname=args.realname,
        idcard=args.idcard,
        qq=args.qq,
    )
    if args.json:
        _emit_json({
            "ok": res.ok,
            "errors": res.errors,
            "warnings": res.warnings,
        })
        return 0 if res.ok else 1
    return 0 if _print_form_result(res) else 1


def _cmd_prepare(args) -> int:
    policy = _retry_policy(args)
    timeout = DEFAULT_TIMEOUT if args.timeout is None else args.timeout
    try:
        transport = _build_transport(args, timeout=timeout, policy=policy)
        profiles = _load_identity_profiles(args)
        bundles = []
        for profile in profiles:
            bundles.append(prepare_registration(
                profile,
                path=args.form_path,
                username_length=args.username_length
                or DEFAULT_USERNAME_LENGTH,
                password_length=args.password_length
                or args.length or DEFAULT_LENGTH,
                prefix=args.prefix,
                suffix=args.suffix,
                verify_username=not _offline(args),
                timeout=timeout,
                retry_delay=args.retry_delay or 0.0,
                retry_policy=policy,
                transport=transport,
            ))
            _sleep_between(args)
    except (Gen4399Error, TypeError, ValueError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    _warn_pii(args)
    if args.json:
        _emit_json([
            b.to_dict(include_secrets=args.show_pii) for b in bundles
        ])
    else:
        for idx, bundle in enumerate(bundles, 1):
            if len(bundles) > 1:
                if idx > 1:
                    print()
                print(f"# 身份 {idx}/{len(bundles)}")
            print(bundle.as_text(show_pii=args.show_pii))
    if args.output:
        out_dir = Path(args.output)
        out_dir.mkdir(parents=True, exist_ok=True)
        for idx, bundle in enumerate(bundles, 1):
            bundle.save(
                out_dir / f"bundle-{idx:02d}.json",
                show_pii=args.show_pii,
            )
        print(f"# 已写入 {args.output}/bundle-*.json", file=sys.stderr)
    return 0


def _cmd_submit(args) -> int:
    """准备并（在 --yes 时）真实提交注册；默认 dry-run。"""
    try:
        policy = _retry_policy(args)
        timeout = DEFAULT_TIMEOUT if args.timeout is None else args.timeout
    except (TypeError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    app_id = getattr(args, "app_id", None) or DEFAULT_APP_ID
    level = getattr(args, "level", 4)
    confirmed = bool(getattr(args, "yes", False))
    if confirmed:
        print(
            "# 警告：即将真实提交注册请求，仅限本人真实身份，"
            "请确认已阅读并遵守 4399 用户协议；不要批量注册他人账号",
            file=sys.stderr,
        )
    else:
        print(
            "# DRY-RUN：未加 --yes，不会真正提交注册（加 --yes 才发送 POST）",
            file=sys.stderr,
        )

    try:
        profiles = _load_identity_profiles(args)
    except (Gen4399Error, TypeError, ValueError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    if len(profiles) > 1:
        print(
            f"# 警告：共 {len(profiles)} 个身份，将依次提交；"
            "请确保均为本人或已获授权，禁止批量注册他人账号",
            file=sys.stderr,
        )

    try:
        transport = _build_transport(args, timeout=timeout, policy=policy)
        captcha = _make_captcha_solver(
            prompt=bool(getattr(args, "captcha_prompt", False)),
            command=getattr(args, "captcha_cmd", None),
            directory=getattr(args, "captcha_dir", None),
            auto=bool(getattr(args, "captcha_auto", False)),
            matcher=bool(getattr(args, "captcha_matcher", False)),
            zoom=int(getattr(args, "captcha_zoom", 1) or 1),
            learn=getattr(args, "captcha_learn", None),
        )
        captcha_attempts = int(getattr(args, "captcha_attempts", 3))
    except (Gen4399Error, TypeError, ValueError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    results = []
    rc = 0
    #: 只在 --show-pii 且注册成功时保留密码，用于「别把刚建好的号弄丢」
    revealed: dict[str, str] = {}
    for profile in profiles:
        try:
            bundle = prepare_registration(
                profile,
                path=args.form_path,
                username_length=args.username_length
                or DEFAULT_USERNAME_LENGTH,
                password_length=args.password_length
                or args.length or DEFAULT_LENGTH,
                prefix=args.prefix,
                suffix=args.suffix,
                verify_username=not _offline(args),
                timeout=timeout,
                retry_delay=args.retry_delay or 0.0,
                retry_policy=policy,
                transport=transport,
            )
            result = submit_registration(
                bundle,
                app_id=app_id,
                level=level,
                timeout=timeout,
                dry_run=not confirmed,
                retry_policy=policy,
                captcha=captcha,
                captcha_attempts=captcha_attempts,
                transport=transport,
            )
        except (Gen4399Error, TypeError, ValueError, OSError) as exc:
            print(f"错误：{exc}", file=sys.stderr)
            rc = 2
            continue
        results.append(result)
        if result.ok and getattr(args, "show_pii", False):
            revealed[result.username] = bundle.password
        if result.kind not in ("success", "dry_run"):
            rc = max(rc, 1)
        _sleep_between(args)

    if args.json:
        if len(results) == 1:
            _emit_json(results[0].to_dict())
        else:
            _emit_json([r.to_dict() for r in results])
    else:
        for idx, result in enumerate(results, 1):
            if len(results) > 1:
                if idx > 1:
                    print()
                print(f"# 身份 {idx}/{len(results)}")
            if result.kind == "dry_run":
                print(
                    f"DRY-RUN: {result.username} 未提交"
                    f"（字段 {len(result.field_names)} 个，"
                    f"加密 {len(result.encrypted_fields)} 个）"
                )
                print(f"  端点: {result.endpoint or '(未发送 POST)'}")
                print("  加 --yes 才会真正提交注册")
            elif result.kind == "success":
                print(f"OK: 注册成功 {result.username}")
                if result.username in revealed:
                    print(f"  密码: {revealed[result.username]}（--show-pii，请立即保存）")
                print(f"  说明: {result.message}")
                if result.captcha_attempts:
                    print(f"  验证码轮次: {result.captcha_attempts}")
            else:
                print(f"FAIL[{result.kind}]: {result.username} → {result.message}")
                if result.kind == "captcha" and not (
                    getattr(args, "captcha_prompt", False)
                    or getattr(args, "captcha_cmd", None)
                    or getattr(args, "captcha_auto", False)
                ):
                    print(
                        "  提示: 加 --captcha-prompt（人工输入）或 "
                        "--captcha-cmd '<OCR 命令>' 可自动过图形验证码"
                    )
                if result.kind == "throttled":
                    print(
                        "  提示: 4399 注册接口限流，等几分钟再跑；"
                        "批量提交请用 --min-interval 拉开间隔"
                    )
    if args.output:
        payload = results[0].to_dict() if len(results) == 1 else [
            r.to_dict() for r in results
        ]
        _maybe_output(args, "submit.json", payload)
    return rc


def _cmd_build_form(args) -> int:
    username, password = args.build_form
    try:
        profiles = _load_identity_profiles(args)
        form = get_form(args.form_path)
    except (Gen4399Error, TypeError, ValueError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    _warn_pii(args)
    labels = {f.name: f.label for f in form.fields}
    payload = []
    for idx, profile in enumerate(profiles, 1):
        try:
            fields = build_registration_fields(
                username, password, path=args.form_path, profile=profile
            )
        except (Gen4399Error, TypeError, ValueError) as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 2
        shown_fields = fields
        if not args.show_pii:
            shown_fields = dict(fields)
            for key in ("sfz", "idcard"):
                if key in shown_fields:
                    shown_fields[key] = profile.masked_idcard()
            for key in ("login_password", "password",
                        "relogin_pwd", "passwordveri"):
                if key in shown_fields:
                    shown_fields[key] = "*" * len(shown_fields[key])
            for key in ("qq", "email"):
                value = shown_fields.get(key)
                if value:
                    shown_fields[key] = value[:2] + "*" * (len(value) - 2)
        payload.append({
            "index": idx,
            "realname_masked": profile.masked(),
            "fields": shown_fields,
        })
        if args.json:
            continue
        if idx > 1:
            print()
        if len(profiles) > 1:
            print(f"# 身份 {idx}/{len(profiles)}")
        print(f"{form.title}  ({form.path})")
        print(f"页面: {form.url}")
        print(pad("参数名", 18) + pad("标签", 12) + "值")
        print("-" * 70)
        for name, value in shown_fields.items():
            print(pad(name, 18) + pad(labels.get(name, ""), 12) + value)

    if args.json:
        if len(payload) == 1:
            _emit_json(payload[0])
        else:
            _emit_json(payload)
    else:
        print("\n# 提示：身份证/密码/QQ 默认打码，需要明文请加 --show-pii",
              file=sys.stderr)
        print(
            "# 提示：本命令只生成清单；真实提交用 `gen4399 submit --yes`"
            "（仅限本人真实身份）",
            file=sys.stderr,
        )
    if args.output:
        _maybe_output(args, "form-fields.json", payload)
    return 0


def _cmd_account(args) -> int:
    policy = _retry_policy(args)
    timeout = DEFAULT_TIMEOUT if args.timeout is None else args.timeout
    count = args.count
    accounts = []
    try:
        for _ in range(count):
            accounts.append(generate_account(
                verify_username=not _offline(args),
                username_length=args.username_length
                or DEFAULT_USERNAME_LENGTH,
                password_length=args.password_length
                or args.length or DEFAULT_LENGTH,
                prefix=args.prefix,
                suffix=args.suffix,
                timeout=timeout,
                retry_policy=policy,
            ))
            _sleep_between(args)
    except (RemoteError, Gen4399Error, TypeError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    if args.json:
        _emit_json([a.to_dict() for a in accounts])
    else:
        for idx, acc in enumerate(accounts, 1):
            if count > 1:
                print(f"# account {idx}/{count}")
            print(f"username: {acc.username}")
            print(f"password: {acc.password}")
            if acc.username_available is True:
                print("# 账号名已通过官方接口确认可注册", file=sys.stderr)
            elif acc.username_available is None:
                print("# 未做在线查重（--no-verify）", file=sys.stderr)
    if args.output:
        out_dir = Path(args.output)
        out_dir.mkdir(parents=True, exist_ok=True)
        for idx, acc in enumerate(accounts, 1):
            acc.save(out_dir / f"account-{idx:02d}.json")
        print(f"# 已写入 {args.output}/account-*.json", file=sys.stderr)
    return 0


def _cmd_check_available(args) -> int:
    if _offline(args):
        print("错误：--check-available 需要联网，不能与 --offline/--no-verify 同用",
              file=sys.stderr)
        return 2
    timeout = DEFAULT_TIMEOUT if args.timeout is None else args.timeout
    try:
        res = check_username(
            args.check_available,
            timeout=timeout,
            validate_input=True,
            retry_policy=_retry_policy(args),
        )
    except RemoteError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    if args.json:
        _emit_json(res.to_dict())
    elif res.available:
        print(f"AVAILABLE: {res.username}")
    else:
        print(f"UNAVAILABLE: {res.username}  ({res.message})", file=sys.stderr)
    if args.output:
        _maybe_output(args, "availability.json", res.to_dict())
    return 0 if res.available else 1


def _cmd_captcha(args) -> int:
    """gen4399 captcha：标注样本 / 用字库识别一张图。"""
    from .captcha_web import WebCaptchaBank, learning_captcha_solver, segment_glyphs

    bank_path = args.bank
    if args.captcha_command == "solve":
        solver = learning_captcha_solver(bank_path)
        try:
            image = Path(args.image).read_bytes()
        except OSError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 2
        print(solver(image))
        return 0

    # label
    directory = Path(args.directory)
    if not directory.is_dir():
        print(f"错误：{directory} 不是目录", file=sys.stderr)
        return 2
    bank = WebCaptchaBank(bank_path)
    files = sorted(p for p in directory.iterdir() if p.suffix.lower() == args.ext)
    if not files:
        print(f"错误：{directory} 里没有 {args.ext} 文件", file=sys.stderr)
        return 2
    added = skipped = 0
    print(f"共 {len(files)} 张；输入 4 位答案，回车跳过，q 退出")
    for path in files:
        glyphs = segment_glyphs(path.read_bytes())
        if len(glyphs) != 4:
            print(f"{path.name}: 切字失败，跳过")
            skipped += 1
            continue
        try:
            label = input(f"{path.name} > ").strip().upper()
        except EOFError:
            break
        if label.lower() == "q":
            break
        if len(label) != 4 or "?" in label:
            skipped += 1
            continue
        for char, glyph in zip(label, glyphs):
            bank.add(char, glyph)
        added += 1
    if added:
        bank.save()
    print(f"已标注 {added} 张，跳过 {skipped} 张；字库共 {len(bank)} 个样本 → {bank.path}")
    return 0


def _cmd_batch(args) -> int:
    """gen4399 batch：批量注册编排。"""
    from .batch import run_batch

    timeout = DEFAULT_TIMEOUT if args.timeout is None else args.timeout
    try:
        policy = _retry_policy(args)
        transport = _build_transport(args, timeout=timeout, policy=policy)
        captcha = _make_captcha_solver(
            prompt=bool(getattr(args, "captcha_prompt", False)),
            command=getattr(args, "captcha_cmd", None),
            directory=getattr(args, "captcha_dir", None),
            auto=bool(getattr(args, "captcha_auto", False)),
            matcher=bool(getattr(args, "captcha_matcher", False)),
            zoom=int(getattr(args, "captcha_zoom", 1) or 1),
            learn=getattr(args, "captcha_learn", None),
        )
        profiles = _load_identity_profiles(args)
    except (Gen4399Error, TypeError, ValueError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    if args.count:
        profiles = profiles[: args.count]
    if not profiles:
        print("错误：没有可用的身份信息", file=sys.stderr)
        return 2

    confirmed = bool(args.yes)
    if not confirmed:
        print("# DRY-RUN：未加 --yes，不会真正提交（加 --yes 才发送 POST）",
              file=sys.stderr)
    else:
        print(
            f"# 警告：即将真实提交 {len(profiles)} 个注册请求；"
            "只应使用本人真实身份，并遵守 4399 用户协议。",
            file=sys.stderr,
        )

    def progress(index, total, item):
        flag = "OK " if item.ok else "FAIL"
        print(f"[{index}/{total}] {flag} {item.username} {item.kind} "
              f"({item.elapsed:.1f}s)", file=sys.stderr)

    summary = run_batch(
        profiles,
        path=args.form_path,
        captcha=captcha,
        transport=transport,
        interval=args.interval,
        jitter=args.jitter,
        dry_run=not confirmed,
        max_failures=args.max_failures,
        output=getattr(args, "output_file", None),
        verify_login=args.verify_login,
        on_progress=progress,
    )

    if args.json:
        _emit_json(summary.to_dict())
    else:
        print(f"总数 {summary.total}（跳过 {summary.skipped}）"
              f"  成功 {summary.success}  失败 {summary.failed}"
              f"  用时 {summary.elapsed:.1f}s")
        for kind, count in summary.by_kind().items():
            print(f"  {kind}: {count}")
        if summary.aborted:
            print("  （已按 max-failures 中止）")
    return 0 if summary.failed == 0 else 1


def _cmd_accounts(args) -> int:
    """gen4399 accounts：列出 / 统计 / 导出 / 去重本地账号文件。"""
    from .account import (
        account_stats,
        accounts_to_csv,
        accounts_to_jsonl,
        dedupe_accounts,
        load_accounts,
    )

    records = load_accounts(args.file)
    if not records:
        print(f"错误：{args.file} 里没有账号记录", file=sys.stderr)
        return 2

    cmd = args.accounts_cmd
    if cmd == "stats":
        stats = account_stats(records)
        if args.json:
            _emit_json(stats)
        else:
            print(f"总数: {stats['total']}  成功: {stats['ok']}")
            print("按路径: " + "、".join(f"{k}={v}" for k, v in stats["by_path"].items()))
            print("按结果: " + "、".join(f"{k}={v}" for k, v in stats["by_kind"].items()))
        return 0

    if cmd == "dedupe":
        unique, removed = dedupe_accounts(records)
        if args.dry_run:
            print(f"可去掉 {removed} 条重复（共 {len(records)} 条）")
            return 0
        _write_private(args.file, json.dumps(unique, ensure_ascii=False, indent=2))
        print(f"已去重：{len(records)} → {len(unique)} 条（去掉 {removed} 条）")
        return 0

    if cmd == "list":
        if args.json:
            from .account import _public

            _emit_json([_public(r, include_secrets=args.include_secrets) for r in records])
            return 0
        for idx, record in enumerate(records, 1):
            password = record.get("password", "")
            shown = password if args.include_secrets else "*" * len(password)
            print(
                f"{idx:3d}. {record.get('username', '?'):<20} "
                f"{record.get('kind', '?'):<9} {record.get('path', '?'):<8} "
                f"{record.get('created_at', '')[:19]}  {shown}"
            )
        return 0

    text = (
        accounts_to_csv(records, include_secrets=args.include_secrets)
        if args.format == "csv"
        else accounts_to_jsonl(records, include_secrets=args.include_secrets)
    )
    if args.out:
        _write_private(args.out, text)
        print(f"已导出 {len(records)} 条到 {args.out}（0600）")
    else:
        sys.stdout.write(text)
    return 0


def _write_private(path: str, text: str) -> None:
    """把文本原子写入文件并设 0600。"""
    target = Path(path)
    tmp = target.with_name(target.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)
    os.replace(tmp, target)
    try:
        os.chmod(target, 0o600)
    except OSError:  # pragma: no cover
        pass


def _cmd_login(args) -> int:
    """gen4399 login：用账号密码登录，打印结果与 Cookie 名。"""
    import getpass

    from .login import login as do_login

    timeout = DEFAULT_TIMEOUT if args.timeout is None else args.timeout
    try:
        policy = _retry_policy(args)
        transport = _build_transport(args, timeout=timeout, policy=policy)
    except (Gen4399Error, TypeError, ValueError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    password = args.password
    if not password:
        try:
            password = getpass.getpass("4399 密码（不回显）：")
        except EOFError:
            print("错误：没有读到密码", file=sys.stderr)
            return 2

    try:
        result = do_login(
            args.username,
            password,
            app_id=args.app_id or DEFAULT_APP_ID,
            timeout=timeout,
            retry_policy=policy,
            transport=transport,
        )
    except (Gen4399Error, TypeError, ValueError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    if args.json:
        _emit_json(result.to_dict())
    elif result.ok:
        print(f"OK: 登录成功 {result.username}")
        print(f"  说明: {result.message}")
    else:
        print(f"FAIL[{result.kind}]: {result.username} → {result.message}")
    return 0 if result.ok else 1


def _cmd_fetch(args) -> int:
    if _offline(args):
        print("错误：--fetch-username 需要联网，不能与 --offline/--no-verify 同用",
              file=sys.stderr)
        return 2
    timeout = DEFAULT_TIMEOUT if args.timeout is None else args.timeout
    try:
        names = fetch_suggested_usernames(
            args.fetch_username,
            prefix=args.prefix,
            suffix=args.suffix,
            verify_available=args.verify,
            timeout=timeout,
            retries=4 if args.retries is None else args.retries,
            retry_delay=5.0 if args.retry_delay is None else args.retry_delay,
            retry_policy=_retry_policy(args),
            max_total_seconds=args.max_total_timeout,
        )
    except (Gen4399Error, TypeError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    if args.json:
        _emit_json(names)
    else:
        for name in names:
            print(name)
    if args.output:
        _maybe_output(args, "fetched-usernames.json", names)
    return 0


def _cmd_generate(args) -> int:
    as_username = args.username
    charset = USERNAME_CHARSET if as_username else CHARSET
    length = _display_length(args, as_username)
    policy = _retry_policy(args)
    try:
        min_len = USERNAME_MIN_LENGTH if as_username else MIN_LENGTH
        max_len = USERNAME_MAX_LENGTH if as_username else MAX_LENGTH
        if not min_len <= length <= max_len:
            raise InvalidLengthError(
                f"长度必须为 {min_len}~{max_len}，收到 {length}"
            )
        bits = entropy_bits(
            length, len(args.prefix), len(args.suffix), charset_size=len(charset)
        )

        if args.entropy:
            if args.json:
                _emit_json({"kind": "username" if as_username else "password",
                            "length": length, "entropy_bits": round(bits, 4)})
            else:
                print(f"{bits:.1f}")
            return 0

        if as_username and args.verify:
            items = []
            for _ in range(args.count):
                items.append(generate_available_username(
                    length=length,
                    prefix=args.prefix,
                    suffix=args.suffix,
                    retry_policy=policy,
                ))
                _sleep_between(args)
        elif as_username:
            items = generate_usernames(
                args.count, length=length, prefix=args.prefix, suffix=args.suffix
            )
        else:
            items = generate_many(
                args.count, length=length, prefix=args.prefix, suffix=args.suffix
            )
    except (Gen4399Error, TypeError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    if args.json:
        _emit_json({
            "kind": "username" if as_username else "password",
            "length": length,
            "prefix": args.prefix,
            "suffix": args.suffix,
            "entropy_bits": round(bits, 4),
            "items": items,
        })
    else:
        for item in items:
            print(item)
    if args.output:
        _maybe_output(args, "generated.json", {
            "kind": "username" if as_username else "password",
            "items": items,
        })

    rnd = length - len(args.prefix) - len(args.suffix)
    kind = "账号名" if as_username else "密码"
    print(
        f"# {kind} | 总长 {length} | 前缀 {len(args.prefix)} 位 | "
        f"后缀 {len(args.suffix)} 位 | 随机 {rnd} 位 | "
        f"字符集 {len(charset)} | 熵 ≈ {bits:.1f} bit",
        file=sys.stderr,
    )
    if rnd < 8:
        print(
            f"# 警告：随机部分只有 {rnd} 位，熵偏低，建议加长 -n",
            file=sys.stderr,
        )
    return 0


# ---------------------------------------------------------------------------
# 2.0 子命令（旧 flag 模式仍保留兼容）
# ---------------------------------------------------------------------------

_SUBCOMMANDS = {
    "generate", "check", "account", "accounts", "batch", "captcha",
    "fetch", "available", "login",
    "form", "prepare", "submit", "profile", "rules", "version",
}

_LEGACY_DEFAULTS: dict | None = None


def _legacy_defaults() -> dict:
    global _LEGACY_DEFAULTS
    if _LEGACY_DEFAULTS is None:
        _LEGACY_DEFAULTS = vars(build_parser().parse_args([]))
    return dict(_LEGACY_DEFAULTS)


def _add_remote_opts(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--timeout", type=float, default=None, metavar="SECONDS")
    sp.add_argument("--retries", type=int, default=None, metavar="N")
    sp.add_argument("--retry-delay", type=float, default=None, metavar="SECONDS")
    sp.add_argument("--max-total-timeout", type=float, default=None,
                    metavar="SECONDS")
    sp.add_argument("--min-interval", type=float, default=0.0, metavar="SECONDS")


def _add_captcha_opts(sp: argparse.ArgumentParser) -> None:
    sp.add_argument(
        "--captcha-prompt", action="store_true",
        help="遇到图形验证码时保存图片并人工输入（web 路径）",
    )
    sp.add_argument(
        "--captcha-matcher", action="store_true",
        help="用内置识别器（专解 4399 的 60×30 验证码；需要 ImageMagick 解码）",
    )
    sp.add_argument(
        "--captcha-auto", action="store_true",
        help="自动选识别方式：本机有 OCR（tesseract）就用，否则退回人工输入",
    )
    sp.add_argument(
        "--captcha-cmd", default=None, metavar="CMD",
        help="用外部命令识别验证码：PNG 从 stdin 传入，stdout 第一行作为结果",
    )
    sp.add_argument(
        "--captcha-dir", default=None, metavar="DIR",
        help="把验证码图片保存到该目录（便于人工查看/留存）",
    )
    sp.add_argument(
        "--captcha-zoom", type=int, default=1, metavar="N",
        help="人工识别时把验证码放大 N 倍（需本机 ImageMagick；unified 的 60×30 小图建议 6~8）",
    )
    sp.add_argument(
        "--captcha-learn", nargs="?", const="", default=None, metavar="BANK",
        help="用自学习字库识别 web 验证码（150×45）；"
             "不给 BANK 就用 ~/.gen4399/web_captcha_bank.json",
    )
    sp.add_argument(
        "--captcha-attempts", type=int, default=3, metavar="N",
        help="验证码最多重试轮数，默认 3（web 路径）",
    )


def _add_transport_opts(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--proxy", default=None, metavar="URL",
                    help="HTTP(S) 代理，如 http://127.0.0.1:8080（host:port 也可）")
    sp.add_argument("--proxy-file", default=None, metavar="FILE",
                    help="代理池文件：一行一个代理，# 开头为注释")
    sp.add_argument("--proxy-strategy", choices=["round-robin", "random"],
                    default="round-robin",
                    help="代理池取用策略，默认 round-robin")
    sp.add_argument("--random-ua", action="store_true",
                    help="每个会话随机生成浏览器 User-Agent")
    sp.add_argument("--proxy-sticky", action="store_true",
                    help="粘住代理池里的第一个代理（查重+提交用同一个 IP）")
    sp.add_argument("--proxy-check", action="store_true",
                    help="建会话前先探活代理，坏的自动换下一个")


def _add_io_opts(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--output", metavar="DIR", default=None)


def _add_identity_opts(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--profile-file", metavar="FILE", default=None,
                    help="每行「姓名|身份证号[|QQ]」，'-' 表示 stdin；"
                         "未指定且未给 --realname/--idcard 时默认读 ./sfz.txt")
    sp.add_argument("--profile-encoding", default=None, metavar="ENCODING",
                    help="身份文件编码；默认自动（UTF-8-SIG，失败回退 GB18030）")
    sp.add_argument("--realname", default=None, metavar="NAME")
    sp.add_argument("--idcard", default=None, metavar="ID")
    sp.add_argument("--qq", default=None, metavar="QQ")


def _add_generate_opts(sp: argparse.ArgumentParser) -> None:
    sp.add_argument("--kind", choices=["password", "username"],
                    default="password")
    sp.add_argument("-n", "--length", type=int, default=None)
    sp.add_argument("--password-length", type=int, default=None)
    sp.add_argument("--username-length", type=int, default=None)
    sp.add_argument("-c", "--count", type=int, default=1)
    sp.add_argument("-p", "--prefix", default="")
    sp.add_argument("-s", "--suffix", default="")
    sp.add_argument("--verify", action="store_true")
    sp.add_argument("--entropy", action="store_true")
    _add_io_opts(sp)
    _add_remote_opts(sp)


def build_subcommand_parser() -> argparse.ArgumentParser:
    """构造 2.0 子命令解析器（``gen4399 generate`` 等）。"""
    p = argparse.ArgumentParser(
        prog="gen4399",
        description="生成 / 校验符合 4399 注册规则的密码与账号名（子命令模式）",
    )
    p.add_argument("-V", "--version", action="version",
                   version=f"gen4399 {__version__}")
    p.add_argument("-v", "--verbose", action="store_true", default=False)
    sub = p.add_subparsers(dest="command", required=True)
    defaults = _legacy_defaults()

    def new(name: str, help_text: str) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help_text)
        sp.set_defaults(**defaults)
        return sp

    g = new("generate", "生成密码或用户名")
    _add_generate_opts(g)

    c = new("check", "校验密码或用户名")
    c.add_argument("kind", choices=["password", "username"])
    c.add_argument("value")
    c.add_argument("--json", action="store_true")

    a = new("account", "生成一套/多套账号名+密码")
    a.add_argument("-c", "--count", type=int, default=1)
    a.add_argument("-p", "--prefix", default="")
    a.add_argument("-s", "--suffix", default="")
    a.add_argument("--password-length", type=int, default=None)
    a.add_argument("--username-length", type=int, default=None)
    a.add_argument("--no-verify", action="store_true")
    a.add_argument("--offline", action="store_true")
    _add_io_opts(a)
    _add_remote_opts(a)

    f = new("fetch", "从官方接口取分配账号")
    f.add_argument("count", nargs="?", type=int, default=1)
    f.add_argument("-p", "--prefix", default="")
    f.add_argument("-s", "--suffix", default="")
    f.add_argument("--verify", action="store_true")
    f.add_argument("--offline", action="store_true")
    _add_io_opts(f)
    _add_remote_opts(f)

    lg = new("login", "用账号密码登录 4399（换登录 Cookie）")
    lg.add_argument("username")
    lg.add_argument("--password", default=None, metavar="PWD",
                    help="明文密码；不给则从终端交互输入（不回显）")
    lg.add_argument("--app-id", default=None, metavar="APPID")
    _add_io_opts(lg)
    _add_remote_opts(lg)
    _add_transport_opts(lg)

    v = new("available", "查询用户名是否可注册")
    v.add_argument("name")
    v.add_argument("--offline", action="store_true")
    _add_io_opts(v)
    _add_remote_opts(v)

    form = sub.add_parser("form", help="表单字段/校验/填表清单")
    form.set_defaults(**defaults)
    fsub = form.add_subparsers(dest="form_command", required=True)

    ff = fsub.add_parser("fields", help="打印表单字段")
    ff.set_defaults(**defaults)
    ff.add_argument("path", nargs="?", default="web",
                    choices=["web", "unified"])
    ff.add_argument("--json", action="store_true")

    fc = fsub.add_parser("check", help="本地校验表单")
    fc.set_defaults(**defaults)
    fc.add_argument("username")
    fc.add_argument("password")
    fc.add_argument("--form-path", choices=["web", "unified"], default="web")
    fc.add_argument("--json", action="store_true")
    _add_identity_opts(fc)

    fb = fsub.add_parser("build", help="生成填表清单")
    fb.set_defaults(**defaults)
    fb.add_argument("username")
    fb.add_argument("password")
    fb.add_argument("--form-path", choices=["web", "unified"], default="web")
    fb.add_argument("--show-pii", action="store_true")
    _add_identity_opts(fb)
    _add_io_opts(fb)

    bt = new("batch", "批量注册编排（多身份 + 节奏 + 落盘 + 断点续跑）")
    bt.add_argument("--form-path", choices=["web", "unified"], default="unified")
    bt.add_argument("-c", "--count", type=int, default=None,
                    help="最多跑几个身份（默认全部）")
    bt.add_argument("--interval", type=float, default=30.0, metavar="SEC",
                    help="身份之间的基础间隔，默认 30 秒")
    bt.add_argument("--jitter", type=float, default=0.0, metavar="SEC",
                    help="额外随机抖动上限（秒）")
    bt.add_argument("--max-failures", type=int, default=0, metavar="N",
                    help="连续失败 N 次就中止（0 = 不中止）")
    bt.add_argument("--verify-login", action="store_true",
                    help="每个号注册成功后立刻登录复核")
    bt.add_argument("--yes", action="store_true", help="真正提交（默认 dry-run）")
    bt.add_argument("--offline", action="store_true",
                    help="跳过用户名查重（只影响 prepare 阶段的 isExist.do）")
    _add_identity_opts(bt)
    _add_io_opts(bt)
    _add_remote_opts(bt)
    _add_transport_opts(bt)
    _add_captcha_opts(bt)

    cap = new("captcha", "web 验证码字库：标注样本 / 试识别")
    cap.set_defaults(**defaults)
    csub = cap.add_subparsers(dest="captcha_command", required=True)

    cl = csub.add_parser("label", help="标注目录里的验证码样本，写进字库")
    cl.set_defaults(**defaults)
    cl.add_argument("directory")
    cl.add_argument("--bank", default=None, metavar="FILE",
                    help="字库路径（默认 ~/.gen4399/web_captcha_bank.json）")
    cl.add_argument("--ext", default=".png", help="只处理这个后缀，默认 .png")

    cs = csub.add_parser("solve", help="用字库识别一张验证码图片")
    cs.set_defaults(**defaults)
    cs.add_argument("image")
    cs.add_argument("--bank", default=None, metavar="FILE")

    acc = new("accounts", "查看 / 导出 / 去重本地账号文件（accounts.json）")
    acc.set_defaults(**defaults)
    asub = acc.add_subparsers(dest="accounts_command", required=True)

    def _acct_base(sp):
        sp.set_defaults(**defaults)
        sp.add_argument("--file", default="accounts.json", metavar="FILE",
                        help="账号文件，默认 ./accounts.json")
        sp.add_argument("--json", action="store_true")

    al = asub.add_parser("list", help="列出账号（密码默认打码）")
    _acct_base(al)
    al.add_argument("--include-secrets", action="store_true",
                    help="输出明文密码")

    ast_ = asub.add_parser("stats", help="统计：总数 / 成功数 / 按路径分组")
    _acct_base(ast_)

    ae = asub.add_parser("export", help="导出为 CSV / JSONL")
    _acct_base(ae)
    ae.add_argument("--format", choices=["csv", "jsonl"], default="csv")
    ae.add_argument("--out", default=None, metavar="FILE",
                    help="写入文件（0600）；不给则打到 stdout")
    ae.add_argument("--include-secrets", action="store_true",
                    help="导出明文密码（默认打码）")

    ad = asub.add_parser("dedupe", help="按 (账号, 密码) 去重并原地重写")
    _acct_base(ad)
    ad.add_argument("--dry-run", action="store_true", help="只报告，不改文件")

    subcmd = new("submit", "准备并提交注册（web / unified；默认 dry-run，需 --yes）")
    subcmd.add_argument(
        "--form-path", choices=["web", "unified"], default="unified",
        help="注册路径，默认 unified（推荐）；web 走 web.4399.com 用户中心",
    )
    subcmd.add_argument("--app-id", default=None, metavar="APPID")
    subcmd.add_argument("--level", type=int, default=4, metavar="N")
    subcmd.add_argument("-p", "--prefix", default="")
    subcmd.add_argument("-s", "--suffix", default="")
    subcmd.add_argument("--password-length", type=int, default=None)
    subcmd.add_argument("--username-length", type=int, default=None)
    subcmd.add_argument("--no-verify", action="store_true")
    subcmd.add_argument(
        "--offline", action="store_true",
        help="跳过用户名在线查重（dry-run/提交本身仍需联网）",
    )
    subcmd.add_argument("--yes", action="store_true",
                        help="确认真正发送 POST；不加时只做 dry-run")
    subcmd.add_argument("--show-pii", action="store_true",
                        help="注册成功时在终端打印刚生成的密码（默认不打印）")
    _add_identity_opts(subcmd)
    _add_io_opts(subcmd)
    _add_remote_opts(subcmd)
    _add_captcha_opts(subcmd)
    _add_transport_opts(subcmd)
    subcmd.set_defaults(submit=True, form_path="unified")

    pr = new("prepare", "一键准备注册数据")
    pr.add_argument("--form-path", choices=["web", "unified"], default="web")
    pr.add_argument("-p", "--prefix", default="")
    pr.add_argument("-s", "--suffix", default="")
    pr.add_argument("--password-length", type=int, default=None)
    pr.add_argument("--username-length", type=int, default=None)
    pr.add_argument("--no-verify", action="store_true")
    pr.add_argument("--offline", action="store_true")
    pr.add_argument("--show-pii", action="store_true")
    _add_identity_opts(pr)
    _add_io_opts(pr)
    _add_remote_opts(pr)

    pf = new("profile", "身份文件操作")
    pfsub = pf.add_subparsers(dest="profile_command", required=True)
    pfcheck = pfsub.add_parser("check", help="校验身份文件（默认 ./sfz.txt）")
    pfcheck.set_defaults(**defaults)
    pfcheck.add_argument(
        "--profile-file", metavar="FILE", default=None,
        help="身份文件；未指定时默认当前目录 sfz.txt",
    )
    pfcheck.add_argument(
        "--profile-encoding", default=None, metavar="ENCODING",
        help="身份文件编码；默认自动（UTF-8-SIG，失败回退 GB18030）",
    )
    pfcheck.add_argument("--json", action="store_true")

    new("rules", "打印内置规则版本")
    new("version", "打印版本")

    return p


def _cmd_profile_check(args) -> int:
    try:
        profiles = _load_identity_profiles(args)
    except (Gen4399Error, TypeError, ValueError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    if args.json:
        _emit_json([
            {
                "realname": p.realname,
                "idcard": p.masked_idcard(),
                "qq": p.qq,
            }
            for p in profiles
        ])
        return 0
    print(f"OK: {len(profiles)} 条身份信息全部合法")
    for profile in profiles:
        print(f"  - {profile.masked()}")
    return 0


def _cmd_rules(_args) -> int:
    print(f"4399 rules {RULES_VERSION}（核对于 {RULES_CHECKED_AT}）")
    for url in RULES_SOURCES:
        print(f"  - {url}")
    return 0


def _normalize_subcommand(args) -> None:
    """把子命令参数映射到旧 handler 使用的字段。"""
    cmd = args.command
    if cmd == "generate":
        args.username = args.kind == "username"
    elif cmd == "check":
        if args.kind == "password":
            args.check = args.value
            args.check_username = None
        else:
            args.check_username = args.value
            args.check = None
    elif cmd == "account":
        args.account = True
    elif cmd == "fetch":
        args.fetch_username = args.count
    elif cmd == "available":
        args.check_available = args.name
    elif cmd == "form":
        sub = args.form_command
        if sub == "fields":
            args.form_fields = args.path
        elif sub == "check":
            args.check_form = [args.username, args.password]
        elif sub == "build":
            args.build_form = [args.username, args.password]
    elif cmd == "prepare":
        args.prepare = True
    elif cmd == "submit":
        args.submit = True
    elif cmd == "login":
        args.login_cmd = True
    elif cmd == "accounts":
        args.accounts_cmd = args.accounts_command
    elif cmd == "batch":
        args.batch_cmd = True
    elif cmd == "captcha":
        args.captcha_cmd_name = args.captcha_command


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 主函数。返回退出码：0 成功，1 校验失败，2 参数/远程错误。

    两种调用方式：

    * 旧 flag 模式：``gen4399 -n 20 -c 5``（保持兼容）
    * 2.0 子命令：``gen4399 generate -n 20`` / ``gen4399 check password ...``
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in _SUBCOMMANDS:
        args = build_subcommand_parser().parse_args(argv)
        if args.command == "version":
            print(f"gen4399 {__version__}")
            return 0
        if args.command == "rules":
            return _cmd_rules(args)
        if args.command == "profile":
            return _cmd_profile_check(args)
        _normalize_subcommand(args)
    else:
        args = build_parser().parse_args(argv)
    if args.verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(levelname)s %(name)s: %(message)s",
        )

    if args.check is not None or args.check_username is not None:
        return _cmd_check(args)
    if args.form_fields is not None:
        return _cmd_form_fields(args)
    if args.check_form is not None:
        return _cmd_check_form(args)
    if getattr(args, "submit", False):
        return _cmd_submit(args)
    if getattr(args, "login_cmd", False):
        return _cmd_login(args)
    if getattr(args, "accounts_cmd", None):
        return _cmd_accounts(args)
    if getattr(args, "batch_cmd", False):
        return _cmd_batch(args)
    if getattr(args, "captcha_cmd_name", None):
        return _cmd_captcha(args)
    if args.prepare:
        return _cmd_prepare(args)
    if args.build_form is not None:
        return _cmd_build_form(args)
    if args.account:
        return _cmd_account(args)
    if args.check_available is not None:
        return _cmd_check_available(args)
    if args.fetch_username is not None:
        return _cmd_fetch(args)
    return _cmd_generate(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
