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

import re
from dataclasses import dataclass, field

from .core import (
    MAX_LENGTH,
    MIN_LENGTH,
    USERNAME_CHARSET,
    Gen4399Error,
    validate,
    validate_username,
)

__all__ = [
    "FormField",
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
    "build_registration_fields",
]


# ---------------------------------------------------------------------------
# 表单字段定义
# ---------------------------------------------------------------------------


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
    kind: str = "text"
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

#: 路径 -> 表单定义
FORMS = {
    WEB_USERNAME_FORM.path: WEB_USERNAME_FORM,
    UNIFIED_FORM.path: UNIFIED_FORM,
}


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

_REALNAME_RE = re.compile(
    r"^([\u2E80-\uFE4F\u00B7\u2022]{2,30}"
    r"|(?=[a-zA-Z]{2,}(\s[a-zA-Z]+){1,2}).{2,30})$"
)
_QQ_RE = re.compile(r"^[0-9]{4,11}$")
_IDCARD_RE = re.compile(r"^\d{15}(\d{2}[\dx])?$", re.IGNORECASE)
_WEB_USERNAME_RE = re.compile(r"^[A-Za-z0-9]+$")
_UNIFIED_USERNAME_RE = re.compile(r"^[A-Za-z0-9_@]+$")
_UNIFIED_PASSWORD_RE = re.compile(r"^[\w.(!@#$%&)]+$")

_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID_CHECK = "10X98765432"


def validate_realname(realname: str) -> list[str]:
    """校验真实姓名（复刻 4399 ``regRealName``）。

    Args:
        realname: 姓名。

    Returns:
        错误信息列表，空表示合规。
    """
    if not isinstance(realname, str):
        raise TypeError("realname 必须是 str")
    name = realname.replace("\u3000", "").strip()
    if not name:
        return ["姓名不能为空"]
    if not _REALNAME_RE.match(name):
        return ["姓名格式不正确（2~30 位中文，或英文姓名字间加空格）"]
    return []


def _valid_birthday(birth: str) -> bool:
    """birth 形如 YYYYMMDD。"""
    if len(birth) != 8 or not birth.isdigit():
        return False
    year, month, day = int(birth[:4]), int(birth[4:6]), int(birth[6:])
    if not 1850 <= year <= 2050:
        return False
    days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    if year % 400 == 0 or (year % 4 == 0 and year % 100 != 0):
        days[1] = 29
    return 1 <= month <= 12 and 1 <= day <= days[month - 1]


def validate_idcard(idcard: str) -> list[str]:
    """校验身份证号（复刻 4399 ``__checkIdcard``）。

    规则：18 位、出生日期合法（1850~2050）、GB 11643 校验码正确。
    15 位身份证 4399 一律拒绝。

    Args:
        idcard: 身份证号。

    Returns:
        错误信息列表，空表示合规。
    """
    if not isinstance(idcard, str):
        raise TypeError("idcard 必须是 str")
    s = idcard.strip().upper()
    if not _IDCARD_RE.match(s):
        return ["身份证号格式不正确（应为 18 位数字，末位可为 X）"]
    if len(s) == 15:
        return ["4399 不接受 15 位身份证，请填写 18 位"]
    if not _valid_birthday(s[6:14]):
        return ["身份证号中的出生日期不合法"]
    total = sum(int(s[i]) * _ID_WEIGHTS[i] for i in range(17))
    if _ID_CHECK[total % 11] != s[17]:
        return ["身份证号校验码不正确，请核对"]
    return []


def validate_qq(qq: str) -> list[str]:
    """校验 QQ 号（复刻 4399 ``regQq``：4~11 位数字）。

    Args:
        qq: QQ 号。

    Returns:
        错误信息列表，空表示合规。
    """
    if not isinstance(qq, str):
        raise TypeError("qq 必须是 str")
    if not qq:
        return []
    return [] if _QQ_RE.match(qq) else ["QQ 号无效（应为 4~11 位数字）"]


def _check_username_for_path(username: str, path: str) -> list[str]:
    errs = validate_username(username)
    msgs = [v.message for v in errs]
    if path == "unified" and not msgs:
        if not _UNIFIED_USERNAME_RE.match(username):
            msgs.append("统一注册的用户名只允许字母、数字、下划线、@")
    return msgs


def _check_password_for_path(password: str, path: str) -> list[str]:
    msgs = [v.message for v in validate(password)]
    if path == "unified" and not msgs:
        if not _UNIFIED_PASSWORD_RE.match(password):
            msgs.append("密码包含不支持的特殊字符")
    return msgs


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


# ---------------------------------------------------------------------------
# 身份信息（真实姓名 + 身份证号）
# ---------------------------------------------------------------------------


class InvalidProfileError(Gen4399Error, ValueError):
    """身份信息不合法。"""


@dataclass(frozen=True)
class RegistrationProfile:
    """一份注册用的身份信息。

    仅用于**本地校验和填表清单生成**，本库不会把它发送到任何服务器。

    Attributes:
        realname: 真实姓名。
        idcard: 18 位身份证号。
        qq: QQ 号（选填，用于找回密码）。
    """

    realname: str
    idcard: str
    qq: str | None = None

    def __post_init__(self) -> None:
        for name, val in (("realname", self.realname), ("idcard", self.idcard)):
            if not isinstance(val, str):
                raise TypeError(f"{name} 必须是 str，收到 {type(val).__name__}")
        if self.qq is not None and not isinstance(self.qq, str):
            raise TypeError("qq 必须是 str 或 None")

    def errors(self) -> dict[str, list[str]]:
        """返回各字段的错误信息；空字典表示全部合规。

        Returns:
            ``{"realname": [...], "idcard": [...], "qq": [...]}``，
            只包含有问题的字段。
        """
        found: dict[str, list[str]] = {
            "realname": validate_realname(self.realname),
            "idcard": validate_idcard(self.idcard),
        }
        if self.qq is not None:
            found["qq"] = validate_qq(self.qq)
        return {k: v for k, v in found.items() if v}

    def is_valid(self) -> bool:
        """身份信息是否全部合规。"""
        return not self.errors()

    def require_valid(self) -> "RegistrationProfile":
        """不合规时抛 :class:`InvalidProfileError`，合规则返回自身。

        Returns:
            self

        Raises:
            InvalidProfileError: 存在不合规字段。
        """
        errs = self.errors()
        if errs:
            detail = "；".join(f"{k}: {m}" for k, msgs in errs.items() for m in msgs)
            raise InvalidProfileError(detail)
        return self

    def masked_idcard(self) -> str:
        """打码后的身份证号（保留前 6 后 4），用于日志输出。"""
        s = self.idcard.strip()
        if len(s) <= 10:
            return "*" * len(s)
        return s[:6] + "*" * (len(s) - 10) + s[-4:]

    def masked(self) -> str:
        """打码后的整体描述，可安全写日志。"""
        parts = [self.realname[:1] + "*" * max(0, len(self.realname) - 1),
                 self.masked_idcard()]
        if self.qq:
            parts.append("qq=" + self.qq[:2] + "*" * max(0, len(self.qq) - 2))
        return " ".join(parts)


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
