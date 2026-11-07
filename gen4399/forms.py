"""4399 注册表单：字段定义 + 本地校验（不发网络请求）。

覆盖两条注册路径：

* ``web``     —— https://web.4399.com/user/reg.php 的「用户名注册」
                 （不需要手机号，推荐）
* ``unified`` —— ptlogin 统一注册面板（regFrame.do / register.do），
                 手机端与弹窗走的路径

字段来自对上述页面源码的逐字段解析；校验规则复刻 4399 前端
``validation.js`` 中的 ``CheakPWD`` / ``CheakUsername`` / ``CheckRealname`` /
``__checkIdcard``。

本模块**只做本地校验**，不提供提交注册请求的能力——注册请在浏览器手动完成。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal

from .core import Gen4399Error, validate, validate_username
from .identity import (
    InvalidProfileError,
    RegistrationProfile,
    load_profiles,
    parse_profile_line,
    validate_idcard,
    validate_qq,
    validate_realname,
)

__all__ = [
    "FormField",
    "FieldKind",
    "ProfileLoadErrors",
    "RegistrationForm",
    "FormCheckResult",
    "WEB_USERNAME_FORM",
    "UNIFIED_FORM",
    "FORMS",
    "get_form",
    "validate_realname",
    "validate_idcard",
    "validate_qq",
    "check_registration_form",
    "RegistrationProfile",
    "InvalidProfileError",
    "parse_profile_line",
    "load_profiles",
    "build_registration_fields",
]


# ---------------------------------------------------------------------------
# 表单字段定义
# ---------------------------------------------------------------------------

#: ``FormField.kind`` 的合法取值
FieldKind = Literal["text", "password", "checkbox", "hidden"]

#: ``load_profiles(errors=...)`` 的合法取值
ProfileLoadErrors = Literal["raise", "skip"]


@dataclass(frozen=True)
class FormField:
    """一个注册表单字段。

    Attributes:
        name: 提交时的参数名。
        label: 页面上的中文标签。
        required: 是否必填。
        kind: 控件类型（text / password / checkbox / hidden）。
        maxlength: 最大长度（None 表示页面未限制）。
        note: 页面提示语或补充说明。
    """

    name: str
    label: str
    required: bool = False
    kind: FieldKind = "text"
    maxlength: int | None = None
    note: str = ""


@dataclass(frozen=True)
class RegistrationForm:
    """一套注册表单的定义。

    Attributes:
        path: 路径标识（``web`` / ``unified``）。
        title: 中文标题。
        url: 注册页地址。
        submit_url: 表单提交地址（相对路径）。
        fields: 字段元组。
    """

    path: str
    title: str
    url: str
    submit_url: str
    fields: tuple[FormField, ...]


WEB_USERNAME_FORM = RegistrationForm(
    path="web",
    title="网页「用户名注册」",
    url="https://web.4399.com/user/reg.php",
    submit_url="/user/?_c=reg",
    fields=(
        FormField("cid", "渠道号", False, "hidden", None, "页面自带，固定 3000"),
        FormField("login_name", "用户名", True, "text", 20,
                  "6~20 位字母和数字"),
        FormField("login_password", "密码", True, "password", 20,
                  "6~20 位字母和数字"),
        FormField("relogin_pwd", "确认密码", True, "password", 20, "与密码一致"),
        FormField("qq", "QQ", False, "text", 26,
                  "选填，但唯一可靠的找回渠道"),
        FormField("true_name", "真实姓名", True, "text", 30, "防沉迷要求"),
        FormField("sfz", "身份证号", True, "text", 18, "18 位，需通过校验码"),
        FormField("agree", "同意协议", True, "checkbox", None,
                  "《4399通行证用户服务协议》"),
    ),
)

UNIFIED_FORM = RegistrationForm(
    path="unified",
    title="4399 统一注册（ptlogin）",
    url="https://u.4399.com/register.html",
    submit_url="/ptlogin/register.do",
    fields=(
        FormField("username", "4399用户名", True, "text", 20,
                  "6~20 位；页面允许字母数字，服务端要求字母数字"),
        FormField("password", "密码", True, "password", 20,
                  "6~20 位；提交时由 JS 写入隐藏域"),
        FormField("passwordveri", "再次输入密码", True, "password", 20,
                  "与密码一致"),
        FormField("email", "QQ号", False, "text", 26,
                  "选填，用于找回密码"),
        FormField("realname", "真实姓名", True, "hidden", 30, "防沉迷要求"),
        FormField("idcard", "身份证号", True, "hidden", 18, "18 位，需通过校验码"),
        FormField("reg_eula_agree", "同意协议", True, "checkbox", None,
                  "《用户协议》+《隐私政策》"),
        FormField("autoLogin", "自动登录", False, "checkbox", None, "可选"),
        FormField("fCaptcha", "图形验证码", False, "text", 6,
                  "风控弹窗触发时才出现"),
        FormField("regMode", "注册模式", True, "hidden", None, "固定 reg_normal"),
        FormField("appId", "业务方 ID", True, "hidden", None, "默认 u4399"),
        FormField("level", "注册等级", False, "hidden", None, "默认 4"),
        FormField("postLoginHandler", "登录后回调", False, "hidden", None,
                  "固定 refreshParent"),
        FormField("mainDivId", "容器 ID", False, "hidden", None,
                  "固定 popup_reg_div"),
        FormField("externalLogin", "第三方登录", False, "hidden", None, "默认 qq"),
    ),
)

#: 路径 -> 表单定义（只读，防止运行时被意外改写）
FORMS = MappingProxyType({
    WEB_USERNAME_FORM.path: WEB_USERNAME_FORM,
    UNIFIED_FORM.path: UNIFIED_FORM,
})


def get_form(path: str = "web") -> RegistrationForm:
    """按路径标识取表单定义。

    Args:
        path: ``"web"`` 或 ``"unified"``。

    Returns:
        :class:`RegistrationForm`。

    Raises:
        ValueError: 未知路径。
    """
    try:
        return FORMS[path]
    except KeyError:
        raise ValueError(
            f"未知注册路径 {path!r}，可选：{', '.join(sorted(FORMS))}"
        ) from None


# ---------------------------------------------------------------------------
# 字段校验
# ---------------------------------------------------------------------------

def _check_username_for_path(username: str, path: str) -> list[str]:
    """按注册路径校验用户名，返回错误信息列表。

    两条路径最终都执行服务端同样的 6~20 位字母数字规则；``path`` 参数
    保留是为了以后不同路径规则分叉时不用改调用方。
    """
    return [v.message for v in validate_username(username)]


def _check_password_for_path(password: str, path: str) -> list[str]:
    """按注册路径校验密码，返回错误信息列表（当前两条路径规则一致）。"""
    return [v.message for v in validate(password)]


# ---------------------------------------------------------------------------
# 整表校验
# ---------------------------------------------------------------------------


@dataclass
class FormCheckResult:
    """注册表单校验结果。

    Attributes:
        path: 校验用的路径标识。
        ok: 是否全部通过。
        errors: ``{字段名: [错误信息]}``。
        warnings: 不阻止提交、但值得注意的提示。
    """

    path: str
    ok: bool
    errors: dict[str, list[str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.ok

    def messages(self) -> list[str]:
        """把错误拍平成 ``字段: 信息`` 列表。"""
        return [f"{k}: {m}" for k, msgs in self.errors.items() for m in msgs]


def check_registration_form(
    username: str,
    password: str,
    *,
    path: str = "web",
    password_confirm: str | None = None,
    realname: str | None = None,
    idcard: str | None = None,
    qq: str | None = None,
    profile: "RegistrationProfile | None" = None,
) -> FormCheckResult:
    """按 4399 真实规则校验一份注册表单（纯本地，不联网）。

    Args:
        username: 用户名。
        password: 密码。
        path: ``"web"``（网页用户名注册）或 ``"unified"``（统一注册）。
        password_confirm: 确认密码；为 ``None`` 时按与 password 相同处理。
        realname: 真实姓名。
        idcard: 身份证号。
        qq: QQ 号（选填）。
        profile: :class:`RegistrationProfile`；提供后，``realname`` /
            ``idcard`` / ``qq`` 为 ``None`` 的字段会从 profile 取值。

    Returns:
        :class:`FormCheckResult`。

    Raises:
        ValueError: ``path`` 未知。
        TypeError: 参数类型错误。

    Examples:
        >>> r = check_registration_form(
        ...     "abc12345", "Abc123456",
        ...     realname="张三", idcard="110101199001011234",
        ... )
        >>> r.ok
        False
    """
    form = get_form(path)          # 未知 path 这里就抛 ValueError
    if profile is not None:
        if not isinstance(profile, RegistrationProfile):
            raise TypeError("profile 必须是 RegistrationProfile")
        if realname is None:
            realname = profile.realname
        if idcard is None:
            idcard = profile.idcard
        if qq is None:
            qq = profile.qq
    result = FormCheckResult(path=form.path, ok=True)

    result.errors["username"] = _check_username_for_path(username, form.path)
    result.errors["password"] = _check_password_for_path(password, form.path)

    if password_confirm is None:
        password_confirm = password
    if password_confirm != password:
        result.errors.setdefault("password_confirm", []).append("两次输入的密码不一致")

    if realname is None:
        result.errors["realname"] = ["真实姓名是必填项"]
    else:
        result.errors["realname"] = validate_realname(realname)

    if idcard is None:
        result.errors["idcard"] = ["身份证号是必填项"]
    else:
        result.errors["idcard"] = validate_idcard(idcard)

    if qq is not None:
        result.errors["qq"] = validate_qq(qq)

    result.errors = {k: v for k, v in result.errors.items() if v}
    result.ok = not result.errors

    if form.path == "unified":
        result.warnings.append(
            "统一注册页面允许 3~20 位用户名，但服务端报错文案为「6~20位字母数字」，"
            "建议按 6~20 位字母数字填写"
        )
    return result


def build_registration_fields(
    username: str,
    password: str,
    *,
    path: str = "web",
    password_confirm: str | None = None,
    profile: RegistrationProfile | None = None,
    realname: str | None = None,
    idcard: str | None = None,
    qq: str | None = None,
) -> dict[str, str]:
    """生成「注册表单填什么」的字段清单（只组装数据，不提交）。

    返回的顺序与页面字段顺序一致，方便照着逐项填。

    Args:
        username: 用户名。
        password: 密码。
        path: ``"web"`` 或 ``"unified"``。
        password_confirm: 确认密码；``None`` 时与 password 相同。
        profile: 身份信息对象；提供后覆盖 realname / idcard / qq 中的 ``None``。
        realname / idcard / qq: 也可直接传值。

    Returns:
        ``{参数名: 填写值}``（按表单顺序）。

    Raises:
        ValueError: ``path`` 未知。
        TypeError: ``profile`` 类型错误。

    Examples:
        >>> p = RegistrationProfile("张三", "460206194611192084")
        >>> f = build_registration_fields("abc12345", "Abc123456", profile=p)
        >>> f["login_name"], f["sfz"]
        ('abc12345', '460206194611192084')
    """
    form = get_form(path)
    if profile is not None:
        if not isinstance(profile, RegistrationProfile):
            raise TypeError("profile 必须是 RegistrationProfile")
        realname = realname if realname is not None else profile.realname
        idcard = idcard if idcard is not None else profile.idcard
        qq = qq if qq is not None else profile.qq

    confirm = password if password_confirm is None else password_confirm

    values: dict[str, str] = {}
    for f in form.fields:
        if f.name == "cid":
            values[f.name] = "3000"
        elif f.name in ("login_name", "username"):
            values[f.name] = username
        elif f.name in ("login_password", "password"):
            values[f.name] = password
        elif f.name in ("relogin_pwd", "passwordveri"):
            values[f.name] = confirm
        elif f.name in ("qq", "email"):
            values[f.name] = qq or ""
        elif f.name in ("true_name", "realname"):
            values[f.name] = realname or ""
        elif f.name in ("sfz", "idcard"):
            values[f.name] = idcard or ""
        elif f.name in ("agree", "reg_eula_agree"):
            values[f.name] = "on"
        elif f.name == "regMode":
            values[f.name] = "reg_normal"
        elif f.name == "appId":
            values[f.name] = "u4399"
        elif f.name == "level":
            values[f.name] = "4"
        elif f.name == "postLoginHandler":
            values[f.name] = "refreshParent"
        elif f.name == "mainDivId":
            values[f.name] = "popup_reg_div"
        elif f.name == "externalLogin":
            values[f.name] = "qq"
        elif f.name == "autoLogin":
            values[f.name] = ""
        elif f.name == "fCaptcha":
            values[f.name] = ""
        else:  # 兜底
            values[f.name] = ""
    return values
