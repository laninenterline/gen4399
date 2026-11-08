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

    # 注册表单：字段定义 + 提交前本地校验（不联网）
    from gen4399 import check_registration_form, get_form
    print([f.name for f in get_form("web").fields])
    profile = RegistrationProfile("张三", "460206194611192084", qq="123456789")
    check_registration_form("abc12345", "Abc123456", profile=profile)
    build_registration_fields("abc12345", "Abc123456", profile=profile)

    # 一键准备好整套注册数据
    bundle = prepare_registration(profile, path="unified", verify_username=False)
    print(bundle.as_text())

    # 2.1.0+：真正的提交（web / unified 两条路径；库不会自动提交）
    #   - dry_run=True  只拉表单、组装/加密，不发 POST，不创建账号（推荐先跑）
    #   - dry_run=False 调用即真实提交（请仅使用本人真实身份，遵守 4399 用户协议）
    #   - CLI 默认 dry-run，必须加 --yes 才发送 POST
    result = submit_registration(bundle, dry_run=True)   # doctest: +SKIP
    print(result.kind)                                   # doctest: +SKIP

    is_valid("Abc12345")            # True
    validate("123456")              # [Violation(code='all_digits', ...)]
"""

from ._rules import (
    RULES_CHECKED_AT,
    RULES_SOURCES,
    RULES_VERSION,
)
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
from .batch import BatchItem, BatchSummary, run_batch
from .config import configure, current_config
from .login import LoginResult, login
from .registration import (
    RegistrationBundle,
    RegistrationError,
    prepare_registration,
)
from .submit import (
    CaptchaSolver,
    SubmitError,
    SubmitResult,
    WEB_CAPTCHA_API,
    WEB_CHECK_USER_API,
    WEB_REG_API,
    WEB_VERIFY_CODE_API,
    submit_registration,
)
from ._captcha import (
    CaptchaSolverError,
    auto_captcha_solver,
    matcher_captcha_solver,
    command_captcha_solver,
    make_solver,
    prompt_captcha_solver,
    save_captcha_images,
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
from .proxy import ProxyError, ProxyPool
from .ua import random_user_agent
from .transport import TransportOptions
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
    GenerationError,
    InvalidFixedPartError,
    InvalidLengthError,
    InvalidPrefixError,
    InvalidSuffixError,
    Violation,
    ViolationCode,
    check_fixed_part,
    entropy_bits,
    validate_fixed_part,
    generate,
    generate_many,
    generate_username,
    generate_usernames,
    is_valid,
    is_valid_username,
    validate,
    validate_username,
)

__version__ = "3.3.0"

__all__ = [
    # ---- 核心：日常只需要这些 ----
    # 生成 / 校验
    "generate",
    "generate_many",
    "generate_username",
    "generate_usernames",
    "validate",
    "is_valid",
    "validate_username",
    "is_valid_username",
    "entropy_bits",
    # 身份
    "RegistrationProfile",
    "InvalidProfileError",
    "load_profiles",
    "parse_profile_line",
    # 编排
    "prepare_registration",
    "RegistrationBundle",
    "RegistrationError",
    # 提交
    "submit_registration",
    "SubmitResult",
    "SubmitError",
    "login",
    "LoginResult",
    "run_batch",
    "BatchSummary",
    "BatchItem",
    "configure",
    "current_config",
    "CaptchaSolver",
    "CaptchaSolverError",
    # 远程
    "RemoteError",
    "check_username",
    "is_username_available",
    "fetch_suggested_username",
    "fetch_suggested_usernames",
    "generate_available_username",
    "generate_account",
    "Account",
    # 传输（代理 / UA）
    "TransportOptions",
    "ProxyPool",
    "ProxyError",
    "random_user_agent",
    "__version__",
]

# ---------------------------------------------------------------------------
# 其余名字仍然可用（`from gen4399 import MIN_LENGTH` 照常工作），只是不再属于
# 「公共契约」，也不出现在 `from gen4399 import *` 里。按域从子模块导入更清晰：
#
#   gen4399.core        常量 / Violation / 生成长度限制
#   gen4399.forms       表单定义、整表校验、build_registration_fields
#   gen4399.identity    姓名/身份证/QQ 校验
#   gen4399.remote      远程错误类型、RetryPolicy、端点常量
#   gen4399.submit      提交端点常量、UNIFIED_DROP_FIELDS
#   gen4399.captcha     prompt/command/auto/matcher 四种识别回调
#   gen4399.constants   规则版本 / 长度 / 端点 / unified 字段策略
#   gen4399.transport   TransportOptions、build_transport
#   gen4399.proxy       ProxyPool、ProxyError、normalize_proxy
#   gen4399.ua          random_user_agent
# ---------------------------------------------------------------------------
