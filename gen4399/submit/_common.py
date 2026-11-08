"""提交流程的公共小工具（``gen4399.submit`` 包内部）。"""

from __future__ import annotations

import secrets

from .._captcha import CaptchaSolver
from .._submit_types import SubmitError
from ..registration import RegistrationBundle
from ..remote import _http
from ..transport import TransportOptions
from . import UNIFIED_SEND_REALNAME  # noqa: F401 - 供文档/测试引用

__all__ = [
    "notify_captcha_feedback",
    "verify_account",
    "present_login_cookies",
    "jsonp_callback",
    "validate_args",
]

#: 复核账号用的用户中心地址（页面里出现用户名即视为账号已生效）
VERIFY_URL = "https://u.4399.com/"
_LOGIN_COOKIE_NAMES = (
    "Pauth", "Pauths", "Uauth", "Xauth", "Puser", "Pnick", "Qnick",
    "user_4399", "ck_accname", "ptusertype",
)


def verify_account(
    session: "_http.RemoteSession", username: str
) -> bool | None:
    """注册成功后用同一会话复核账号是否真的可用。

    带 ``Pauth`` 等 Cookie GET ``https://u.4399.com/``，页面里出现用户名即认为
    账号已生效；拿不到页面 / 结构变化时返回 ``None``（无法判断，不下结论）。

    Returns:
        ``True`` 已确认、``False`` 未确认（页面明确是未登录态）、``None`` 无法判断。
    """
    try:
        response = session.get(VERIFY_URL)
    except Exception:  # noqa: BLE001 - 复核是尽力而为，任何失败都只返回 None
        return None
    body = response.body
    if not body:
        return None
    if username in body:
        return True
    # 明确落到登录页 / 提示未登录，说明 Cookie 没生效
    if ("请登录" in body or "登录后" in body) and username not in body:
        return False
    return None


def present_login_cookies(session: "_http.RemoteSession") -> tuple[str, ...]:
    """当前会话里出现过的登录 Cookie **名字**（不含值）。"""
    return tuple(
        name for name in _LOGIN_COOKIE_NAMES if name in session.cookies
    )


def jsonp_callback(prefix: str = "gen4399cb") -> str:
    """生成一个合法的 JSONP 回调名。"""
    return f"{prefix}_{secrets.token_hex(6)}"


def validate_args(
    bundle: RegistrationBundle,
    app_id: str,
    level: int,
    timeout: float,
    captcha: CaptchaSolver | None = None,
    captcha_attempts: int = 3,
    transport: "TransportOptions | None" = None,
) -> None:
    if not isinstance(bundle, RegistrationBundle):
        raise TypeError("bundle 必须是 RegistrationBundle")
    if bundle.path not in ("web", "unified"):
        raise SubmitError(
            f"不支持的注册路径 {bundle.path!r}（可选 web / unified）"
        )
    if not isinstance(app_id, str) or not app_id:
        raise ValueError("app_id 必须是非空 str")
    if not isinstance(level, int) or isinstance(level, bool) or level < 0:
        raise ValueError("level 必须是 >= 0 的 int")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool):
        raise TypeError("timeout 必须是数字")
    if timeout <= 0:
        raise ValueError("timeout 必须 > 0")
    if transport is not None and not isinstance(transport, TransportOptions):
        raise TypeError("transport 必须是 TransportOptions 或 None")
    if captcha is not None and not callable(captcha):
        raise TypeError("captcha 必须是可调用对象（图片字节 -> 文本）或 None")
    if (
        not isinstance(captcha_attempts, int)
        or isinstance(captcha_attempts, bool)
        or captcha_attempts < 1
    ):
        raise ValueError("captcha_attempts 必须是 >= 1 的 int")


def notify_captcha_feedback(solver, image: bytes, code: str, accepted: bool) -> None:
    """如果识别器支持 ``feedback``（自学习字库），把这次结果告诉它。

    识别器抛异常不影响注册流程——学习是尽力而为。
    """
    callback = getattr(solver, "feedback", None)
    if not callable(callback):
        return
    try:
        callback(image, code, accepted)
    except Exception:  # pragma: no cover - 学习失败不影响主流程
        pass
