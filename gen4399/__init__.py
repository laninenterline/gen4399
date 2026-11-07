"""gen4399 —— 生成与校验符合 4399 注册规则的密码。

快速开始::

    from gen4399 import generate, validate, is_valid

    pw = generate()                 # 16 位随机密码
    pw = generate(length=20)        # 20 位
    pw = generate(prefix="lg")      # 以 "lg" 开头的 16 位
    pw = generate(suffix="gz")      # 以 "gz" 结尾的 16 位
    pw = generate(prefix="lg", suffix="gz")
    generate_many(5)                # 一次生成 5 个
    generate_many(5, unique=True)   # 保证 5 个互不相同

    # 账号名（用户名）——本地生成
    generate_username()             # 12 位小写字母+数字
    generate_username(prefix="u")
    validate_username("abc_123")    # 不合规（含下划线）

    # 账号名（用户名）——调用 4399 官方接口
    fetch_suggested_username()      # 服务端分配的账号，如 '4257237567'
    is_username_available("abc12345")   # True / False
    check_username("abc12345").kind     # 'available' / 'taken' / 'invalid'
    generate_available_username()   # 本地生成 + 服务端确认可注册
    generate_account()              # 返回 Account(username, password)

    # 注册表单：字段定义 + 提交前本地校验（不联网、不代提交）
    from gen4399 import check_registration_form, get_form
    print([f.name for f in get_form("web").fields])
    profile = RegistrationProfile("张三", "460206194611192084", qq="123456789")
    check_registration_form("abc12345", "Abc123456", profile=profile)
    build_registration_fields("abc12345", "Abc123456", profile=profile)

    # 一键准备好整套注册数据（仍不代提交）
    bundle = prepare_registration(profile)
    print(bundle.as_text())

    is_valid("Abc12345")            # True
    validate("123456")              # [Violation(code='all_digits', ...)]
"""

from .forms import (
    FORMS,
    FieldKind,
    ProfileLoadErrors,
    InvalidProfileError,
    RegistrationProfile,
    build_registration_fields,
    UNIFIED_FORM,
    WEB_USERNAME_FORM,
    FormCheckResult,
    FormField,
    RegistrationForm,
    check_registration_form,
    get_form,
    load_profiles,
    parse_profile_line,
    validate_idcard,
    validate_qq,
    validate_realname,
)
from .registration import (
    RegistrationBundle,
    RegistrationError,
    prepare_registration,
)
from .remote import (
    DEFAULT_APP_ID,
    DEFAULT_USER_AGENT,
    Account,
    generate_account,
    generate_available_username,
    DEFAULT_TIMEOUT,
    IS_EXIST_URL,
    REG_FRAME_URL,
    RemoteError,
    RemoteHTTPError,
    RemoteParseError,
    RemoteTimeoutError,
    UsernameAvailability,
    check_username,
    fetch_suggested_username,
    fetch_suggested_usernames,
    is_username_available,
)
from .core import (
    CHARSET,
    check_fixed_part,
    DEFAULT_LENGTH,
    DEFAULT_USERNAME_LENGTH,
    MAX_LENGTH,
    MIN_LENGTH,
    USERNAME_CHARSET,
    USERNAME_MAX_LENGTH,
    USERNAME_MIN_LENGTH,
    Gen4399Error,
    GenerationError,
    InvalidFixedPartError,
    InvalidLengthError,
    InvalidPrefixError,
    InvalidSuffixError,
    Violation,
    ViolationCode,
    entropy_bits,
    generate,
    generate_many,
    generate_username,
    generate_usernames,
    is_valid,
    is_valid_username,
    validate,
    validate_username,
)

__version__ = "1.10.0"

__all__ = [
    "CHARSET",
    "MIN_LENGTH",
    "MAX_LENGTH",
    "DEFAULT_LENGTH",
    "USERNAME_CHARSET",
    "USERNAME_MIN_LENGTH",
    "USERNAME_MAX_LENGTH",
    "DEFAULT_USERNAME_LENGTH",
    "Violation",
    "ViolationCode",
    "Gen4399Error",
    "InvalidLengthError",
    "InvalidFixedPartError",
    "InvalidPrefixError",
    "InvalidSuffixError",
    "GenerationError",
    "check_fixed_part",
    "validate",
    "is_valid",
    "generate",
    "generate_many",
    "validate_username",
    "is_valid_username",
    "generate_username",
    "generate_usernames",
    "entropy_bits",
    "REG_FRAME_URL",
    "IS_EXIST_URL",
    "DEFAULT_APP_ID",
    "DEFAULT_USER_AGENT",
    "DEFAULT_TIMEOUT",
    "RemoteError",
    "RemoteTimeoutError",
    "RemoteHTTPError",
    "RemoteParseError",
    "UsernameAvailability",
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
    "RegistrationBundle",
    "RegistrationError",
    "prepare_registration",
    "fetch_suggested_username",
    "fetch_suggested_usernames",
    "check_username",
    "is_username_available",
    "generate_available_username",
    "Account",
    "generate_account",
    "__version__",
]
