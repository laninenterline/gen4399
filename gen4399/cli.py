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
from ._width import pad
from .registration import prepare_registration
from .forms import (
    RegistrationProfile,
    build_registration_fields,
    check_registration_form,
    get_form,
    load_profiles,
)
from .remote import (
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
                   help="全局离线模式：等价于 --no-verify；对必须联网的命令报错")
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
                        "--prepare / --build-form / --check-form；'-' 表示 stdin")
    p.add_argument("--build-form", nargs=2, default=None,
                   metavar=("USERNAME", "PASSWORD"),
                   help="生成填表清单（参数名=值），不提交")
    p.add_argument("--prepare", action="store_true",
                   help="一键准备注册数据（生成用户名+密码、查重、校验、输出填表清单；不提交）")
    p.add_argument("--show-pii", action="store_true",
                   help="显示明文身份证号/密码/QQ（默认打码）")
    p.add_argument("--entropy", action="store_true",
                   help="只输出熵估算（bit），不生成")
    p.add_argument("--timeout", type=float, default=None, metavar="SECONDS",
                   help=f"远程接口单次超时，默认 {DEFAULT_TIMEOUT:g} 秒")
    p.add_argument("--retries", type=int, default=None, metavar="N",
                   help="远程重试总尝试次数（默认：fetch 4 次，其它 2~3 次）")
    p.add_argument("--retry-delay", type=float, default=None, metavar="SECONDS",
                   help="首次重试等待（秒），之后指数递增并加抖动")
    p.add_argument("--max-total-timeout", type=float, default=None,
                   metavar="SECONDS", help="单次远程调用的总时间预算（秒）")
    p.add_argument("--min-interval", type=float, default=0.0, metavar="SECONDS",
                   help="批量远程命令之间的最小间隔（秒），默认 0")
    p.add_argument("--output", metavar="DIR", default=None,
                   help="把结果写成 JSON 文件（目录，文件权限 0600）")
    p.add_argument("--json", action="store_true",
                   help="以 JSON 输出（便于脚本消费）")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="输出重试等调试日志")
    p.add_argument("-V", "--version", action="version",
                   version=f"gen4399 {__version__}")
    return p


# ---------------------------------------------------------------------------
# 通用小工具
# ---------------------------------------------------------------------------


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


def _load_identity_profiles(args):
    """按 --profile-file 或 --realname/--idcard 取得身份信息列表。

    Raises:
        ValueError: 参数缺失或互相冲突。
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
        return load_profiles(args.profile_file, encoding="utf-8-sig")
    if not (args.realname and args.idcard):
        raise ValueError(
            "需要同时提供 --realname 和 --idcard，或使用 --profile-file"
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
        print("# 提示：本命令只生成清单，不会提交注册", file=sys.stderr)
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


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 主函数。返回退出码：0 成功，1 校验失败，2 参数/远程错误。"""
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
