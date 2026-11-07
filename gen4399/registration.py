"""注册编排：把库的各模块串起来，准备一套「可以直接去网页填」的注册数据。

本模块**只做准备**，不提交注册请求：

1. 校验身份信息（姓名 / 身份证 / QQ）
2. 生成或校验用户名（可选调用官方 isExist.do 查重）
3. 生成密码
4. 按 4399 真实规则整表校验
5. 组装成页面字段清单 + 注册页地址

2.1.0 起提供 :func:`gen4399.submit_registration` 做真实提交（2.2.0 起支持
``web`` / ``unified`` 两条路径），但 :func:`prepare_registration` 本身仍然
不会自动提交；提交必须由调用方显式触发。
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from ._width import pad
from .core import (
    DEFAULT_LENGTH,
    DEFAULT_USERNAME_LENGTH,
    Gen4399Error,
    generate,
    generate_username,
)
from .forms import (
    RegistrationProfile,
    build_registration_fields,
    check_registration_form,
    get_form,
)
from .remote import (
    DEFAULT_APP_ID,
    DEFAULT_TIMEOUT,
    check_username,
    generate_available_username,
)

__all__ = [
    "RegistrationBundle",
    "RegistrationError",
    "prepare_registration",
]


class RegistrationError(Gen4399Error):
    """准备注册数据失败（用户名不可用、表单校验不通过等）。"""


@dataclass(frozen=True, repr=False)
class RegistrationBundle:
    """一套准备好的注册数据。

    Attributes:
        path: 注册路径（``web`` / ``unified``）。
        url: 注册页地址。
        username: 用户名。
        password: 密码。
        realname: 真实姓名。
        idcard: 身份证号。
        qq: QQ 号（可能为 None）。
        fields: 只读的 ``{参数名: 值}``，按表单顺序。
        username_available: 是否经服务端确认可用；None 表示未查重。
        warnings: 提示信息。

    Note:
        ``fields`` 是 ``MappingProxyType``，不可修改；``repr()`` 会把密码与
        身份证号打码，可安全写日志。
    """

    path: str
    url: str
    username: str
    password: str
    realname: str
    idcard: str
    qq: str | None
    fields: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )
    username_available: bool | None = None
    warnings: tuple[str, ...] = ()

    def __repr__(self) -> str:
        return (
            f"RegistrationBundle(path={self.path!r}, url={self.url!r}, "
            f"username={self.username!r}, password='***', "
            f"realname={self.realname!r}, idcard={self.masked_idcard()!r}, "
            f"qq={self.qq!r}, username_available={self.username_available!r})"
        )

    def __hash__(self) -> int:
        # fields 是 mapping，用 frozenset 保证与 eq 一致的顺序无关哈希
        return hash((
            self.path,
            self.url,
            self.username,
            self.password,
            self.realname,
            self.idcard,
            self.qq,
            frozenset(self.fields.items()),
            self.username_available,
            self.warnings,
        ))

    def masked_idcard(self) -> str:
        """打码后的身份证号。"""
        return RegistrationProfile(self.realname, self.idcard, self.qq).masked_idcard()

    def masked_fields(self) -> dict[str, str]:
        """打码后的字段清单（身份证、密码、QQ），可安全贴到日志/聊天里。"""
        out = dict(self.fields)
        for key in ("sfz", "idcard"):
            if key in out:
                out[key] = self.masked_idcard()
        for key in ("login_password", "password", "relogin_pwd", "passwordveri"):
            if key in out:
                out[key] = "*" * len(out[key])
        for key in ("qq", "email"):
            value = out.get(key)
            if value:
                out[key] = value[:2] + "*" * max(0, len(value) - 2)
        return out

    def to_dict(self, *, include_secrets: bool = True) -> dict[str, object]:
        """转成可 JSON 序列化的字典。

        Args:
            include_secrets: 为 False 时密码/身份证/QQ 用打码值。
        """
        fields = dict(
            self.fields if include_secrets else self.masked_fields()
        )
        return {
            "path": self.path,
            "url": self.url,
            "username": self.username,
            "password": self.password if include_secrets else "*" * len(self.password),
            "realname": self.realname,
            "idcard": self.idcard if include_secrets else self.masked_idcard(),
            "qq": self.qq,
            "fields": fields,
            "username_available": self.username_available,
            "warnings": list(self.warnings),
        }

    def save(
        self,
        path: "str | os.PathLike[str]",
        *,
        show_pii: bool = False,
        mode: int = 0o600,
    ) -> None:
        """把 bundle 写成 JSON 文件（默认打码，权限 0600）。"""
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(
                self.to_dict(include_secrets=show_pii),
                fh,
                ensure_ascii=False,
                indent=2,
            )
        try:
            os.chmod(path, mode)
        except OSError:  # pragma: no cover - 非 POSIX
            pass

    def as_text(self, *, show_pii: bool = False) -> str:
        """渲染成可读的填表清单。

        Args:
            show_pii: 是否显示完整身份证号与密码（默认打码）。

        Returns:
            多行文本。
        """
        form = get_form(self.path)
        labels = {f.name: f.label for f in form.fields}
        rows = self.fields if show_pii else self.masked_fields()
        lines = [
            f"{form.title}  ({form.path})",
            f"页面: {self.url}",
            pad("参数名", 18) + pad("标签", 12) + "值",
            "-" * 70,
        ]
        for name, value in rows.items():
            lines.append(pad(name, 18) + pad(labels.get(name, ""), 12) + value)
        if self.warnings:
            lines.append("")
            for w in self.warnings:
                lines.append(f"# 提示: {w}")
        lines.append("")
        lines.append(
            "# 手动填表，或调用 submit_registration(dry_run=False) / "
            "`python -m gen4399 submit --yes` 提交"
        )
        lines.append("# 仅限本人真实身份；提交前请确认遵守 4399 用户协议")
        return "\n".join(lines)


def prepare_registration(
    profile: RegistrationProfile,
    *,
    path: str = "web",
    username: str | None = None,
    username_length: int = DEFAULT_USERNAME_LENGTH,
    password_length: int = DEFAULT_LENGTH,
    prefix: str = "",
    suffix: str = "",
    verify_username: bool = True,
    app_id: str = DEFAULT_APP_ID,
    timeout: float = DEFAULT_TIMEOUT,
    retry_delay: float = 0.0,
    retry_policy=None,
) -> RegistrationBundle:
    """准备一套 4399 注册数据（生成 + 查重 + 校验 + 组装字段）。

    只做本地准备与官方查重，**不会提交注册**。拿到结果后可以打开
    ``bundle.url`` 按 ``bundle.fields`` 逐项填写并自行提交，或显式调用
    :func:`gen4399.submit_registration` 提交（仅限本人真实身份）。

    Args:
        profile: 身份信息（姓名、身份证、可选 QQ）。
        path: 注册路径，``"web"``（默认）或 ``"unified"``。
        username: 指定用户名；与 ``prefix`` / ``suffix`` 互斥。
        username_length: 自动生成用户名时的长度，默认 12。
        password_length: 密码长度，默认 16。
        prefix / suffix: 自动生成用户名时的固定前后缀，计入
            ``username_length``（必填 6~20，且至少留 1 位随机）。
        verify_username: 是否调用官方 ``isExist.do`` 确认用户名可用。
        app_id: 业务方 appId。
        timeout: 查重请求超时（秒）。

    Returns:
        :class:`RegistrationBundle`。

    Raises:
        InvalidProfileError: 身份信息不合规。
        RegistrationError: 用户名不可用，或整表校验不通过。
        ValueError: ``path`` 未知，或同时指定了 ``username`` 与前后缀。
        RemoteError: ``verify_username=True`` 时查重失败。
        ValueError: ``path`` 未知。

    Examples:
        >>> from gen4399 import RegistrationProfile, prepare_registration
        >>> p = RegistrationProfile("张三", "460206194611192084")
        >>> bundle = prepare_registration(p, verify_username=False)  # doctest: +SKIP
        >>> bundle.username, len(bundle.password)                   # doctest: +SKIP
        ('xxxxxxxxxxxx', 16)
    """
    form = get_form(path)                 # 未知 path 直接抛 ValueError
    if not isinstance(profile, RegistrationProfile):
        raise TypeError("profile 必须是 RegistrationProfile")
    if username is not None and (prefix or suffix):
        raise ValueError(
            "已显式指定 username 时不应再传 prefix/suffix（前后缀只用于自动生成用户名）"
        )
    profile.require_valid()               # 身份信息不合规直接抛

    # 1) 用户名
    available: bool | None = None
    if username is not None:
        if verify_username:
            res = check_username(
                username,
                app_id=app_id,
                timeout=timeout,
                retry_policy=retry_policy,
            )
            if not res.available:
                raise RegistrationError(
                    f"指定的用户名 {username!r} 不可用：{res.message}"
                )
            available = True
    elif verify_username:
        username = generate_available_username(
            length=username_length,
            prefix=prefix,
            suffix=suffix,
            app_id=app_id,
            timeout=timeout,
            retry_delay=retry_delay,
            retry_policy=retry_policy,
        )
        available = True
    else:
        username = generate_username(
            length=username_length, prefix=prefix, suffix=suffix
        )

    # 2) 密码
    password = generate(length=password_length)

    # 3) 整表校验（此时数据必然合规，异常说明参数组合有问题）
    check = check_registration_form(
        username, password, path=path, profile=profile
    )
    if not check.ok:
        raise RegistrationError("表单校验未通过：" + "；".join(check.messages()))

    # 4) 组装字段
    fields = build_registration_fields(
        username, password, path=path, profile=profile
    )

    warnings = list(check.warnings)
    if not verify_username:
        warnings.append("未做在线查重，用户名可能已被注册")
    warnings.append("请用 https 打开注册页，避免密码明文走 HTTP")

    return RegistrationBundle(
        path=form.path,
        url=form.url,
        username=username,
        password=password,
        realname=profile.realname,
        idcard=profile.idcard,
        qq=profile.qq,
        fields=MappingProxyType(dict(fields)),
        username_available=available,
        warnings=tuple(warnings),
    )
