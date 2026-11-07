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
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from . import __version__
from .registration import prepare_registration
from .forms import (
    RegistrationProfile,
    load_profiles,
    build_registration_fields,
    check_registration_form,
    get_form,
)
from .remote import (
    DEFAULT_TIMEOUT,
    RemoteError,
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
        ),
    )
    p.add_argument("-n", "--length", type=int, default=None,
                   help=f"总长度。密码默认 {DEFAULT_LENGTH}（{MIN_LENGTH}~{MAX_LENGTH}），"
                        f"账号名默认 {DEFAULT_USERNAME_LENGTH}"
                        f"（{USERNAME_MIN_LENGTH}~{USERNAME_MAX_LENGTH}）")
    p.add_argument("-c", "--count", type=int, default=1,
                   help="生成个数，默认 1")
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
                   help="生成一套账号名+密码，默认自动调用官方接口查重账号名")
    p.add_argument("--no-verify", action="store_true",
                   help="配合 --account / --prepare 使用，跳过在线查重（离线可用）")
    p.add_argument("--check-available", metavar="NAME", default=None,
                   help="调用 4399 官方 isExist.do 查询用户名是否还能注册")
    p.add_argument("--form-fields", choices=["web", "unified"], default=None,
                   metavar="{web,unified}",
                   help="打印某条注册路径的表单字段定义")
    p.add_argument("--check-form", nargs=2, default=None,
                   metavar=("USERNAME", "PASSWORD"),
                   help="本地校验一份注册表单（不联网、不代提交）")
    p.add_argument("--form-path", choices=["web", "unified"], default="web",
                   help="--check-form 使用的注册路径，默认 web")
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
                        "--prepare / --build-form / --check-form")
    p.add_argument("--build-form", nargs=2, default=None,
                   metavar=("USERNAME", "PASSWORD"),
                   help="生成填表清单（参数名=值），不提交")
    p.add_argument("--prepare", action="store_true",
                   help="一键准备注册数据（生成用户名+密码、查重、校验、输出填表清单；不提交）")
    p.add_argument("--username-length", type=int, default=None,
                   help="--prepare / --account 自动生成用户名的长度，默认 12")
    p.add_argument("--show-pii", action="store_true",
                   help="配合 --build-form 显示完整身份证号/密码/QQ（默认打码）")
    p.add_argument("--entropy", action="store_true",
                   help="只输出熵估算（bit），不生成")
    p.add_argument("--timeout", type=float, default=None, metavar="SECONDS",
                   help=f"远程接口单次超时，默认 {DEFAULT_TIMEOUT:g} 秒")
    p.add_argument("-V", "--version", action="version",
                   version=f"gen4399 {__version__}")
    return p


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
        return load_profiles(args.profile_file)
    if not (args.realname and args.idcard):
        raise ValueError(
            "需要同时提供 --realname 和 --idcard，或使用 --profile-file"
        )
    return [
        RegistrationProfile(
            args.realname, args.idcard, qq=args.qq
        ).require_valid()
    ]


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 主函数。返回退出码：0 成功，1 校验失败，2 参数错误。"""
    args = build_parser().parse_args(argv)
    timeout = DEFAULT_TIMEOUT if args.timeout is None else args.timeout

    # 校验模式
    if args.check is not None:
        return _report(validate(args.check), args.check)
    if args.check_username is not None:
        return _report(
            validate_username(args.check_username), args.check_username
        )

    # 打印注册表单字段
    if args.form_fields is not None:
        form = get_form(args.form_fields)
        print(f"{form.title}  ({form.path})")
        print(f"页面: {form.url}")
        print(f"提交: POST {form.submit_url}")
        print(f"{'参数名':<18}{'标签':<12}{'必填':<5}{'类型':<9}{'上限':<5}说明")
        print("-" * 78)
        for f in form.fields:
            print(
                f"{f.name:<18}{f.label:<12}"
                f"{'是' if f.required else '否':<5}{f.kind:<9}"
                f"{f.maxlength or '-':<5}{f.note}"
            )
        return 0

    # 校验注册表单
    if args.check_form is not None:
        username, password = args.check_form
        if args.profile_file is not None:
            try:
                profiles = _load_identity_profiles(args)
            except (Gen4399Error, TypeError, ValueError, OSError) as exc:
                print(f"错误：{exc}", file=sys.stderr)
                return 2
            failed = False
            for idx, profile in enumerate(profiles, 1):
                if len(profiles) > 1:
                    print(f"# 身份 {idx}/{len(profiles)}")
                res = check_registration_form(
                    username, password, path=args.form_path, profile=profile
                )
                if not _print_form_result(res):
                    failed = True
            return 1 if failed else 0
        res = check_registration_form(
            username,
            password,
            path=args.form_path,
            realname=args.realname,
            idcard=args.idcard,
            qq=args.qq,
        )
        return 0 if _print_form_result(res) else 1

    # 一键准备注册数据
    if args.prepare:
        try:
            profiles = _load_identity_profiles(args)
            bundles = [
                prepare_registration(
                    profile,
                    path=args.form_path,
                    username_length=args.username_length
                    or DEFAULT_USERNAME_LENGTH,
                    password_length=args.length or DEFAULT_LENGTH,
                    prefix=args.prefix,
                    suffix=args.suffix,
                    verify_username=not args.no_verify,
                    timeout=timeout,
                )
                for profile in profiles
            ]
        except (Gen4399Error, TypeError, ValueError, OSError) as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 2
        for idx, bundle in enumerate(bundles, 1):
            if len(bundles) > 1:
                if idx > 1:
                    print()
                print(f"# 身份 {idx}/{len(bundles)}")
            print(bundle.as_text(show_pii=args.show_pii))
        return 0

    # 生成填表清单
    if args.build_form is not None:
        username, password = args.build_form
        try:
            profiles = _load_identity_profiles(args)
            form = get_form(args.form_path)
        except (Gen4399Error, TypeError, ValueError, OSError) as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 2

        labels = {f.name: f.label for f in form.fields}
        for idx, profile in enumerate(profiles, 1):
            try:
                fields = build_registration_fields(
                    username, password, path=args.form_path, profile=profile
                )
            except (Gen4399Error, TypeError, ValueError) as exc:
                print(f"错误：{exc}", file=sys.stderr)
                return 2
            if idx > 1:
                print()
            if len(profiles) > 1:
                print(f"# 身份 {idx}/{len(profiles)}")
            print(f"{form.title}  ({form.path})")
            print(f"页面: {form.url}")
            print(f"{'参数名':<18}{'标签':<12}值")
            print("-" * 70)
            for name, value in fields.items():
                shown = value
                if name in ("sfz", "idcard") and not args.show_pii:
                    shown = profile.masked_idcard()
                elif name in ("login_password", "password",
                              "relogin_pwd", "passwordveri") and not args.show_pii:
                    shown = "*" * len(value)
                elif name in ("qq", "email") and not args.show_pii:
                    shown = (
                        value[:2] + "*" * max(0, len(value) - 2) if value else value
                    )
                print(f"{name:<18}{labels.get(name, ''):<12}{shown}")
        print("\n# 提示：身份证/密码/QQ 默认打码，需要明文请加 --show-pii",
              file=sys.stderr)
        print("# 提示：本命令只生成清单，不会提交注册", file=sys.stderr)
        return 0

    # 一键生成账号名 + 密码
    if args.account:
        try:
            acc = generate_account(
                verify_username=not args.no_verify,
                username_length=args.username_length
                or DEFAULT_USERNAME_LENGTH,
                password_length=args.length or DEFAULT_LENGTH,
                prefix=args.prefix,
                suffix=args.suffix,
                timeout=timeout,
            )
        except (RemoteError, Gen4399Error, TypeError, ValueError) as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 2
        print(f"username: {acc.username}")
        print(f"password: {acc.password}")
        if acc.username_available is True:
            print("# 账号名已通过官方接口确认可注册", file=sys.stderr)
        elif acc.username_available is None:
            print("# 未做在线查重（--no-verify）", file=sys.stderr)
        return 0

    # 远程：查询用户名可用性
    if args.check_available is not None:
        try:
            res = check_username(args.check_available, timeout=timeout)
        except RemoteError as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 2
        if res.available:
            print(f"AVAILABLE: {res.username}")
            return 0
        print(f"UNAVAILABLE: {res.username}  ({res.message})", file=sys.stderr)
        return 1

    # 远程：获取服务端分配的用户名
    if args.fetch_username is not None:
        try:
            names = fetch_suggested_usernames(
                args.fetch_username,
                prefix=args.prefix,
                suffix=args.suffix,
                verify_available=args.verify,
                timeout=timeout,
            )
        except (Gen4399Error, TypeError, ValueError) as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 2
        for name in names:
            print(name)
        return 0

    as_username = args.username
    charset = USERNAME_CHARSET if as_username else CHARSET
    length = args.length
    if length is None:
        length = DEFAULT_USERNAME_LENGTH if as_username else DEFAULT_LENGTH

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
            print(f"{bits:.1f}")
            return 0

        if as_username:
            if args.verify:
                items = [
                    generate_available_username(
                        length=length, prefix=args.prefix, suffix=args.suffix
                    )
                    for _ in range(args.count)
                ]
            else:
                items = generate_usernames(
                    args.count, length=length, prefix=args.prefix, suffix=args.suffix
                )
        else:
            items = generate_many(
                args.count, length=length, prefix=args.prefix, suffix=args.suffix
            )
        for item in items:
            print(item)
    except (Gen4399Error, TypeError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
