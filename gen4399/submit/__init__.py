"""注册提交：把准备好的 :class:`RegistrationBundle` 真正提交到 4399。

支持两条注册路径（2.2.0 起 ``web`` 路径也可提交，详见 ``docs/submit.md``）::

    unified（ptlogin）
      GET  /ptlogin/regFrame.do     # 拿表单隐藏域 + 会话 Cookie（USESSIONID）
      POST /ptlogin/register.do     # 只回传 21 个必要字段（见 UNIFIED_DROP_FIELDS）
        └─ 成功页含 isAutoRegSuccess(true) 与 Pauth/Uauth/Xauth 等 Cookie

    web（web.4399.com 用户中心）
      GET  /user/?_c=login&_a=checkUser   # 取 encryptCode
      POST /user/?_c=reg                  # DES 加密密码 + JSONP 响应
        └─ 解析 {state, code, msg, validateState}
      code=200（风控要图形验证码）时：
        GET  /util/?_c=code&t=reg         # 验证码图片（绑定 WEBSESSION）
        GET  /user/?_c=reg&_a=verifyCode  # 校验验证码 → {state:true}
        POST /user/?_c=reg + chk_code     # 带验证码重提交

本库提供显式提交能力，但**不会自动提交**：必须由调用方显式调用
:func:`submit_registration`；API 默认 ``dry_run=False``（**调用即提交**），
推荐先传 ``dry_run=True`` 演练；命令行默认 dry-run，必须显式加 ``--yes``。

安全与合规：

* 两个路径的 POST **都永不自动重试**，避免超时后重复注册。
* 请仅使用本人的真实身份信息，并自行确认符合 4399 用户协议；
  不要批量注册他人账号。
* 图形验证码需要调用方提供 :data:`CaptchaSolver`（人工识别或外部 OCR）；
  本库不做验证码自动破解。
* unified 路径默认**不提交实名信息**（回传实名/协议字段会让服务端改走空白
  「4399提示」页），见 :data:`UNIFIED_SEND_REALNAME`。
"""

from __future__ import annotations

import re
import time
import urllib.parse
from collections.abc import Callable

from .._aes import encrypt_aes
from .._captcha import CaptchaSolver as CaptchaSolverType
from ..registration import RegistrationBundle
from ..remote import (
    DEFAULT_APP_ID,
    DEFAULT_TIMEOUT,
    RetryPolicy,
)
from ..transport import TransportOptions
from ..remote import _http

from .._submit_types import (  # noqa: F401 - 部分名字仅用于对外再导出
    SubmitError,
    SubmitKind,
    SubmitResult,
    _dry_run_result,
    _extract_error_message,
    _final_result,
    _page_excerpt,
    _redact_text,
    _safe_url,
    mask_proxy,
)
from .._submit_classify import (  # noqa: F401 - 部分名字仅用于对外再导出
    _INFO_PAGE_RE,
    _SUCCESS_RE,
    _THROTTLE_RE,
    _classify_response,
    _classify_web_response,
    _parse_jsonp,
)



__all__ = [
    "CaptchaSolver",
    "UNIFIED_DROP_FIELDS",
    "UNIFIED_SEND_REALNAME",
    "SubmitKind",
    "ResponseHook",
    "SubmitError",
    "SubmitResult",
    "submit_registration",
]

#: ``SubmitResult.kind`` 的合法取值

#: 注册 POST 响应回调（诊断用；收到原始 ``HttpResponse``，不改变提交行为）
ResponseHook = Callable[["_http.HttpResponse"], None]

#: 图形验证码识别回调（唯一定义在 :mod:`gen4399._captcha`：
#: 入参是验证码图片原始字节，返回识别出的文本）。
CaptchaSolver = CaptchaSolverType

#: ``sec=1`` 时需要加密的字段
ENCRYPTED_FIELDS = ("password", "passwordveri", "realname", "idcard")

#: unified 路径要从服务端隐藏域里**剔除**的字段（2.4.0 实测定案）。
#:
#: 实测（2026-11-08）：`regFrame.do` 页面里的这些隐藏域一旦原样回传，
#: ``POST /ptlogin/register.do`` 一律返回空白「4399提示」页（``info_page``
#: 外壳：没有 ``#Msg``、不下发任何登录 Cookie），注册不会发生；剔除后
#: 同一套数据可以正常建号（成功页含 ``isAutoRegSuccess(...true)`` 与
#: ``Pauth``/``Uauth``/``Xauth`` 等 Cookie）。
#:
#: 这些字段分两类：
#:
#: * 布局/防沉迷/前端校验开关（弹窗容器 id、跨域 iframe、是否展示注册信息、
#:   实名前端校验开关等）——服务端有默认值，不需要回传；
#: * 实名与协议字段（``realname`` / ``idcard`` / ``reg_eula_agree`` 等）——
#:   一并回传时服务端会进入实名/风控分支并返回同一张空白提示页
#:   （实测假身份必然触发；未用真实身份验证过）。
UNIFIED_DROP_FIELDS = frozenset({
    "crossDomainUrl",
    "mainDivId",
    "showRegInfo",
    "includeFcmInfo",
    "expandFcmInput",
    "fcmFakeValidate",
    "realnameValidate",
    "userNameLabel",
    "iframeId",
    "email",
    "reg_eula_agree",
    "autoLogin",
    "fCaptcha",
})

#: unified 路径是否把实名信息（``realname`` / ``idcard``）一起提交。
#:
#: 默认 ``True``：实测（2026-11-08）21 字段 + ``realname``/``idcard``（AES）
#: 可以正常建号。注意**必须连带剔除** :data:`UNIFIED_DROP_FIELDS` 里的
#: ``reg_eula_agree`` / ``autoLogin`` / ``fCaptcha``——这三个一起回传时服务端
#: 会改走空白「4399提示」页。
#:
#: 想要「不实名」的账号可以改成 ``False``（只提交用户名/密码）。
UNIFIED_SEND_REALNAME = True

#: 登录成功后 4399 会下发的 Cookie 名（只看名字，不看值）
from ._common import _LOGIN_COOKIE_NAMES  # noqa: E402,F401

#: web 路径注册提交接口（POST；浏览器用 JSONP GET，服务端同样接受 POST）
WEB_REG_API = "https://web.4399.com/user/?_c=reg"

#: web 路径取密码加密 key 的接口
WEB_CHECK_USER_API = "https://web.4399.com/user/?_c=login&_a=checkUser"

#: unified 路径图形验证码图片（绑定当前会话的 ``USESSIONID`` / 页面 captchaId）
UNIFIED_CAPTCHA_API = "https://ptlogin.4399.com/ptlogin/captcha.do"

#: web 路径图形验证码图片（绑定当前会话的 ``WEBSESSION`` Cookie）
WEB_CAPTCHA_API = "https://web.4399.com/util/?_c=code&t=reg"

#: web 路径校验图形验证码（JSONP，``state=true`` 表示通过）
WEB_VERIFY_CODE_API = "https://web.4399.com/user/?_c=reg&_a=verifyCode"

#: web 路径需要 DES 加密的字段
_WEB_ENCRYPTED_FIELDS = ("login_password", "relogin_pwd")

#: JSONP 响应：``callback({...})``（callback 名可含字母/数字/下划线/``$``）

#: 失败信息所在的 ``<div id="Msg">``

#: 成功页标记：isAutoRegSuccess = true / emit("isAutoRegSuccess", true)
#: 只认赋值/逗号/冒号后接 true，避免把 `isAutoRegSuccess == true` 这类比较式
#: 误判为成功。

#: 服务端重渲染表单里的图形验证码 id（``captcha.do?captchaId=…``）
_CAPTCHA_ID_RE = re.compile(r"captchaId=([A-Za-z0-9]+)")

#: 注册成功后复核账号用的页面（同一会话带 Pauth 等 Cookie 访问）
VERIFY_URL = "https://u.4399.com/"

#: 服务端限流文案（``202`` + 「请稍后再试~」等）




from ._common import (  # noqa: F401 - 旧名字兼容
    jsonp_callback as _jsonp_callback,
    present_login_cookies as _present_login_cookies,
    validate_args as _validate_args,
    verify_account as _verify_account,
)
from .unified import submit_unified
from .web import submit_web

#: 兼容旧名字（2.x 里是 ``gen4399.submit._submit_web``）
_submit_web = submit_web
_submit_unified = submit_unified


def _build_payload(
    bundle: RegistrationBundle,
    form: "_http.RegFormSnapshot",
    app_id: str,
    level: int,
) -> tuple[dict[str, str], tuple[str, ...]]:
    """以服务端表单隐藏域为基线，组装最终 POST 字段（不联网）。

    会剔除 :data:`UNIFIED_DROP_FIELDS`（实测回传这些隐藏域会让服务端改走
    空白「4399提示」页）；实名信息只在 :data:`UNIFIED_SEND_REALNAME` 为
    真时才带（默认不带，见该常量的说明）。

    ``sec`` 缺失时按 ``"1"`` 处理（与实测页面一致，宁可加密也不明文发送）。

    Returns:
        ``(payload, encrypted_fields)``。
    """
    payload = {
        name: value
        for name, value in form.hidden.items()
        if name not in UNIFIED_DROP_FIELDS
    }
    payload.update({
        "username": bundle.username,
        "password": bundle.password,
        "passwordveri": bundle.password,
    })
    if UNIFIED_SEND_REALNAME:
        payload["realname"] = bundle.realname
        payload["idcard"] = bundle.idcard
    else:
        # 表单隐藏域里本来就有空的 realname/idcard，关掉开关时要显式去掉
        payload.pop("realname", None)
        payload.pop("idcard", None)
    payload["appId"] = app_id
    payload["level"] = str(level)
    payload.setdefault("regMode", "reg_normal")

    sec = (form.sec or payload.get("sec") or "1").strip()
    payload["sec"] = sec
    encrypted: tuple[str, ...] = ()
    if sec == "1":
        names = tuple(name for name in ENCRYPTED_FIELDS if name in payload)
        for name in names:
            payload[name] = encrypt_aes(payload[name])
        encrypted = names
    return payload, encrypted


def submit_registration(
    bundle: RegistrationBundle,
    *,
    app_id: str = DEFAULT_APP_ID,
    level: int = 4,
    timeout: float = DEFAULT_TIMEOUT,
    dry_run: bool = False,
    retry_policy: RetryPolicy | None = None,
    on_response: ResponseHook | None = None,
    captcha: CaptchaSolver | None = None,
    captcha_attempts: int = 3,
    verify: bool = True,
    transport: "TransportOptions | None" = None,
    throttle_retries: int = 1,
    throttle_backoff: float = 20.0,
) -> SubmitResult:
    """把准备好的注册数据真正提交到 4399（支持 ``web`` / ``unified``）。

    ==========  =====================================================
    ``web``     ``GET user/?_c=login&_a=checkUser`` 取 encryptCode →
                ``encode_4399``（DES）加密密码 → ``POST user/?_c=reg``
                （JSONP 响应，按 ``state/code/msg`` 判定）；返回
                ``code=200`` 时用 ``captcha`` 识别图形验证码后带
                ``chk_code`` 重提交
    ``unified`` ``GET regFrame.do`` 取隐藏域/会话 → ``sec=1`` 时 AES
                加密敏感字段 → ``POST register.do``
    ==========  =====================================================

    Args:
        bundle: :func:`gen4399.prepare_registration` 的返回值。
        app_id: 业务方 appId，默认 ``u4399``（**仅 unified 使用**）。
        level: 注册等级，默认 4（**仅 unified 使用**）。
        timeout: 单次请求超时（秒）。
        dry_run: 为 True 时只拉取必要数据、组装/加密字段，**不发送注册
            POST**。web 路径仍会 GET ``checkUser``（只带用户名）。
        retry_policy: 只作用于 GET；注册 POST 永远单次尝试。
        on_response: 可选的注册 POST 响应回调（``HttpResponse``），用于诊断；
            不改变提交/判定行为。回调抛出的异常会向上传播（此时 POST 已发出）。
        captcha: 图形验证码识别回调（入参 PNG 字节，返回识别文本）。只在
            web 路径服务端返回 ``code=200`` 时调用；不传则直接返回
            ``kind="captcha"``。本库不内置破解，需调用方接入人工/OCR。
        captcha_attempts: 验证码最多重试轮数（含重新取图），必须 >= 1。
        throttle_retries: 遇到 `kind="throttled"`（服务端 202 +「请稍后再试」）时
            额外重试几次，默认 1。这类响应**确定没有建号**，重试是安全的；
            传 0 关闭自动退避。
        throttle_backoff: 首次退避秒数，之后按 2 倍递增（默认 20 秒）。

    Returns:
        :class:`SubmitResult`；``.kind == "success"`` 表示（可判定为）成功。

    Raises:
        SubmitError: 路径不是 ``web`` / ``unified``。
        TypeError / ValueError: 参数不合法。
        RemoteError 子类: GET/POST 网络失败（注册 POST 不会自动重试）。

    Examples:
        >>> from gen4399 import RegistrationProfile, prepare_registration
        >>> p = RegistrationProfile("张三", "460206194611192084")
        >>> b = prepare_registration(p, path="unified", verify_username=False)
        >>> r = submit_registration(b, dry_run=True)   # doctest: +SKIP
        >>> r.kind                                       # doctest: +SKIP
        'dry_run'
    """
    _validate_args(
        bundle, app_id, level, timeout, captcha, captcha_attempts, transport
    )
    for name, value in (
        ("throttle_retries", throttle_retries),
        ("throttle_backoff", throttle_backoff),
    ):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise TypeError(f"{name} 必须是数字")
        if value < 0:
            raise ValueError(f"{name} 不能为负")
    if not isinstance(throttle_retries, int):
        raise TypeError("throttle_retries 必须是 int")

    started = time.monotonic()
    total_attempts = throttle_retries + 1
    for attempt in range(total_attempts):
        result = _submit_once(
            bundle,
            app_id=app_id,
            level=level,
            timeout=timeout,
            dry_run=dry_run,
            retry_policy=retry_policy,
            started=started,
            on_response=on_response,
            captcha=captcha,
            captcha_attempts=captcha_attempts,
            verify=verify,
            transport=transport,
        )
        if result.kind != "throttled" or attempt == total_attempts - 1:
            if attempt:
                result = _with_throttle_note(result, attempt)
            return result
        delay = throttle_backoff * (2 ** attempt)
        time.sleep(delay)


def _with_throttle_note(result: SubmitResult, attempts: int) -> SubmitResult:
    """在「限流后重试过」的结果上加一句说明（字段其余不变）。"""
    from dataclasses import replace

    return replace(
        result,
        message=f"{result.message}（已自动退避重试 {attempts} 次）",
    )


def _submit_once(
    bundle: RegistrationBundle,
    *,
    app_id: str,
    level: int,
    timeout: float,
    dry_run: bool,
    retry_policy: RetryPolicy | None,
    started: float,
    on_response: ResponseHook | None,
    captcha: CaptchaSolver | None,
    captcha_attempts: int,
    verify: bool,
    transport: "TransportOptions | None",
) -> SubmitResult:
    """按路径提交一次（不含限流退避）。"""
    if bundle.path == "web":
        return _submit_web(
            bundle,
            timeout=timeout,
            dry_run=dry_run,
            retry_policy=retry_policy,
            started=started,
            on_response=on_response,
            captcha=captcha,
            captcha_attempts=captcha_attempts,
            verify=verify,
            transport=transport,
        )
    return _submit_unified(
        bundle,
        app_id=app_id,
        level=level,
        timeout=timeout,
        dry_run=dry_run,
        retry_policy=retry_policy,
        started=started,
        on_response=on_response,
        captcha=captcha,
        captcha_attempts=captcha_attempts,
        verify=verify,
        transport=transport,
    )
