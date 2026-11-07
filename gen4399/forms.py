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

import os
import re
import sys
import warnings
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal

from .core import (
    Gen4399Error,
    validate,
    validate_username,
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

_REALNAME_RE = re.compile(
    r"^([\u2E80-\uFE4F\u00B7\u2022]{2,30}"
    r"|(?=[a-zA-Z]{2,}(\s[a-zA-Z]+){1,2}).{2,30})$"
)
_QQ_RE = re.compile(r"^[0-9]{4,11}$")
_IDCARD_RE = re.compile(r"^\d{15}(\d{2}[\dx])?$", re.IGNORECASE)

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
    qq = qq.strip()
    if not qq:
        return []
    return [] if _QQ_RE.fullmatch(qq) else ["QQ 号无效（应为 4~11 位数字）"]


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


# ---------------------------------------------------------------------------
# 从文本文件读取身份信息
# ---------------------------------------------------------------------------

#: 身份信息行支持的分隔符：ASCII 竖线 / 全角竖线
_PROFILE_SEPARATORS = re.compile(r"[|｜]")

#: 格式提示
_PROFILE_FORMAT_HINT = "每行格式：真实姓名|身份证号[|QQ]"


def parse_profile_line(
    line: str, *, line_number: int | None = None
) -> RegistrationProfile:
    """解析一行身份信息。

    行格式为 ``真实姓名|身份证号``，可选的第三列是 QQ 号，
    即 ``真实姓名|身份证号|QQ``。也接受全角竖线 ``｜``。

    Args:
        line: 一行文本（可含首尾空白）。
        line_number: 行号，仅用于错误信息。

    Returns:
        校验通过的 :class:`RegistrationProfile`。

    Raises:
        TypeError: ``line`` 不是 ``str``。
        InvalidProfileError: 格式或字段内容不合法。

    Examples:
        >>> p = parse_profile_line("张三|460206194611192084")
        >>> p.qq is None
        True
        >>> parse_profile_line("张三|460206194611192084|123456789").qq
        '123456789'
    """
    if not isinstance(line, str):
        raise TypeError(f"line 必须是 str，收到 {type(line).__name__}")
    where = f"第 {line_number} 行" if line_number is not None else "该行"
    text = line.lstrip("\ufeff").strip()
    if not text or text.startswith("#"):
        raise InvalidProfileError(f"{where}：空行/注释行不是有效身份信息")

    parts = [part.strip() for part in _PROFILE_SEPARATORS.split(text)]
    if len(parts) < 2:
        raise InvalidProfileError(
            f"{where}：格式错误，应为「真实姓名|身份证号[|QQ]」，当前 {text!r}"
        )
    if len(parts) > 3:
        raise InvalidProfileError(
            f"{where}：字段过多（应为 2~3 列），当前 {len(parts)} 列：{text!r}"
        )

    realname, idcard = parts[0], parts[1]
    qq = parts[2] if len(parts) == 3 and parts[2] else None
    profile = RegistrationProfile(realname, idcard, qq=qq)
    errs = profile.errors()
    if errs:
        detail = "；".join(
            f"{k}: {m}" for k, msgs in errs.items() for m in msgs
        )
        raise InvalidProfileError(f"{where}：{detail}")
    return profile


#: 可能的表头关键词（用于自动跳过首行表头）
_HEADER_REALNAME = {"姓名", "name", "realname", "真实姓名"}
_HEADER_IDCARD = {"身份证号", "身份证", "idcard", "id", "idnumber"}


def _looks_like_header(text: str) -> bool:
    """判断一行是否像表头（如 ``姓名|身份证号``）。"""
    parts = [part.strip().lower() for part in _PROFILE_SEPARATORS.split(text)]
    if len(parts) < 2:
        return False
    return parts[0] in _HEADER_REALNAME and parts[1] in _HEADER_IDCARD


def _warn_loose_permissions(path: str) -> None:
    """身份文件权限过宽时给出提醒（仅在 POSIX 上有意义）。"""
    try:
        mode = os.stat(path).st_mode
    except OSError:  # pragma: no cover - stat 失败交给 open 报错
        return
    if mode & 0o077:
        warnings.warn(
            f"身份文件 {path} 权限为 {oct(mode & 0o777)}，"
            "包含身份证号等敏感信息，建议执行 chmod 600",
            UserWarning,
            stacklevel=3,
        )


def load_profiles(
    path: "str | os.PathLike[str]",
    *,
    encoding: str = "utf-8-sig",
    errors: ProfileLoadErrors = "raise",
    dedupe: bool = True,
    skip_header: bool | None = None,
) -> list[RegistrationProfile]:
    """从 txt 文件读取一批身份信息。

    - 每行一个身份：``真实姓名|身份证号`` 或 ``真实姓名|身份证号|QQ``
    - 空行与 ``#`` 开头的注释行会被跳过
    - 首行如果像表头（如 ``姓名|身份证号``）会自动跳过
    - 支持 UTF-8 BOM（默认 ``utf-8-sig``）和全角竖线 ``｜``
    - ``path="-"`` 时从标准输入读取
    - 默认按身份证号去重；默认任一行不合法即整体报错（错误信息带行号）

    Args:
        path: 文本文件路径，或 ``"-"`` 表示 stdin。
        encoding: 文件编码，默认 ``utf-8-sig``（兼容带 BOM 的 UTF-8）。
        errors: ``"raise"``（默认，遇错即抛）或 ``"skip"``（跳过坏行并警告）。
        dedupe: 是否按身份证号去重（默认 True）。
        skip_header: 是否跳过首个数据行；``None``（默认）表示自动识别表头，
            ``True`` 强制跳过，``False`` 不跳过。

    Returns:
        校验通过的身份信息列表，顺序与文件一致。

    Raises:
        FileNotFoundError: 文件不存在。
        InvalidProfileError: 某行格式/内容不合法（``errors="raise"``），
            或文件里没有有效行。
        ValueError: ``errors`` 取值非法。

    Examples:
        >>> profiles = load_profiles("ids.txt")      # doctest: +SKIP
        >>> profiles[0].realname                     # doctest: +SKIP
        '张三'
        >>> load_profiles("-")[0].realname           # doctest: +SKIP
        '张三'
    """
    if errors not in ("raise", "skip"):
        raise ValueError("errors 只能是 'raise' 或 'skip'")
    if skip_header is None:
        auto_header = True
    else:
        auto_header = False

    if path == "-":
        source = sys.stdin
        close = False
    else:
        _warn_loose_permissions(os.fspath(path))
        source = open(path, "r", encoding=encoding)
        close = True

    profiles: list[RegistrationProfile] = []
    seen: set[str] = set()
    first_data_line = True
    try:
        for lineno, line in enumerate(source, 1):
            text = line.strip()
            if not text or text.startswith("#"):
                continue

            if first_data_line:
                first_data_line = False
                header = _looks_like_header(text)
                if skip_header is True or (auto_header and header):
                    continue

            try:
                profile = parse_profile_line(line, line_number=lineno)
            except InvalidProfileError as exc:
                if errors == "skip":
                    warnings.warn(f"跳过身份信息：{exc}", UserWarning, stacklevel=2)
                    continue
                raise

            if dedupe:
                key = profile.idcard.strip().upper()
                if key in seen:
                    warnings.warn(
                        f"第 {lineno} 行身份证号与前面重复，已跳过",
                        UserWarning,
                        stacklevel=2,
                    )
                    continue
                seen.add(key)
            profiles.append(profile)
    finally:
        if close:
            source.close()

    if not profiles:
        raise InvalidProfileError(
            f"文件 {path!s} 中没有找到有效身份信息（{_PROFILE_FORMAT_HINT}）"
        )
    return profiles


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
