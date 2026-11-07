# 提交注册（POST）协议与用法

本文记录 gen4399 2.1.0 的 `unified` 路径提交流程。协议细节来自 2026-11-07 对
4399 公开页面与前端 JS 的被动分析，以及少量无害探测（来源：`~/4399recon/`
的 `REPORT-full.md` 与 `protocol-username-register.json`）。

> **重要边界**：研究过程**没有创建任何真实账号**，因此
> **`register.do` 的成功响应属于推断、未经实测**。本库的成功判定只能是启发式的，
> 最终请以能否登录 `https://u.4399.com/` 为准。
>
> 本库只支持 `unified` 路径（`ptlogin/register.do`）；`web` 的
> `POST /user/?_c=reg` 未实测，请继续用浏览器。
>
> 请只使用**本人**真实身份信息，并遵守 4399 用户协议；禁止批量注册他人账号。

## 1. 端点与流程

| 步骤 | 请求 | 作用 |
|---|---|---|
| 1 | `GET https://ptlogin.4399.com/ptlogin/regFrame.do?…` | 取注册表单 HTML；下发会话 Cookie `USESSIONID`（域 `4399.com`）与风控埋点 `phlogact` |
| 2 | 解析表单 | 取 `<form action>`、全部 `type=hidden` 隐藏域、`sec` 开关 |
| 3 | 组装字段 | 以服务端隐藏域为基线，覆盖可见字段（见第 2 节） |
| 4 | 加密 | `sec == "1"` 时用 AES 加密 `password` / `passwordveri` / `realname` / `idcard` |
| 5 | `POST https://ptlogin.4399.com/ptlogin/register.do` | `application/x-www-form-urlencoded`，带同一会话 Cookie |
| 6 | 解析响应 | 成功标记 → 错误文案 → 登录 Cookie → 验证码 → 跳转（见第 4 节） |

`regFrame.do` 的查询参数（本库按此构造 GET；POST 的 hidden 域则以服务端返回为准）：

```
regMode=reg_normal
postLoginHandler=refreshParent
displayMode=            bizId=          redirectUrl=      css=
appId=u4399             gameId=         noEmail=false     regIdcard=true
autoLogin=false         cid=            aid=              ref=
level=4                 mainDivId=popup_reg_div
includeFcmInfo=false    externalLogin=qq
fcmFakeValidate=false   expandFcmInput=false
userNameLabel=          userNameTip=    welcomeTip=
v=<毫秒时间戳>
```

> 注意：`u.4399.com/register` 入口使用 `appId=u4399`、`level=4`；
> `my.4399.com` 用 `appId=my`、`level=0`；移动端 `www_home`。
> 本库默认 `app_id="u4399"`、`level=4`，可用参数覆盖。

会话要点：真正把 GET 与 POST 串起来的是 Cookie（`USESSIONID`）。
表单里的 `sessionId` 通常为空，实际会话靠 Cookie 识别。因此
`submit_registration()` 在同一个 `RemoteSession`（带 `CookieJar`）内先 GET 再 POST。

## 2. 提交字段

以 `regFrame.do` 返回的 hidden 字段为基线，再覆盖下列字段
（代码：`gen4399/submit.py` 的 `_build_payload()`）：

| 字段 | 本库取值 | 说明 |
|---|---|---|
| `username` | `bundle.username` | 3~20 位；服务端页面会预填一个 10 位数字候选（`id="j-username"`） |
| `password` | `bundle.password` | 6~20 位；`sec=1` 时加密 |
| `passwordveri` | 同 `password` | 确认密码；`sec=1` 时加密 |
| `realname` | `bundle.realname` | 强制实名；`sec=1` 时加密 |
| `idcard` | `bundle.idcard` | 18 位身份证（15 位被 4399 拒绝）；`sec=1` 时加密 |
| `email` | `bundle.qq or ""` | 4399 把 QQ 号放在 `email` 字段，选填 |
| `reg_eula_agree` | `on` | 协议勾选，必须 |
| `autoLogin` | `""` | 本库不自动登录（留空） |
| `fCaptcha` | `""` | 图形验证码只在风控弹窗出现；本库不处理验证码 |
| `appId` | 参数，默认 `u4399` | 业务方标识 |
| `level` | 参数，默认 `4` | 注册等级 |
| `sec` | 服务端表单值；缺失按 `1` | `1` = 敏感字段 AES 加密；其它 = 明文 |
| 其它 hidden | 原样回传 | `regMode` / `postLoginHandler` / `mainDivId` / `sessionId` / `regIdcard` 等 |

> 变体说明：早期抓包样本里还出现过 `displayMode` / `bizId` / `gameId` /
> `cid` / `aid` / `ref` / `crossDomainIFrame` / `showRegInfo` 等字段。
> 本库不猜测这些值，而是**原样回传服务端下发的 hidden 域**，只覆盖上表字段。

## 3. AES 加密（`sec=1`）

4399 前端 `validation.js` 的加密函数：

```js
function encryptAES(IdVal) {
    return CryptoJS.AES.encrypt(IdVal, 'lzYW5qaXVqa').toString();
}
```

这是 **CryptoJS 的「口令模式」**（不是 raw key）：

```
口令 lzYW5qaXVqa（公开硬编码，不是秘密）
        │
EVP_BytesToKey(MD5, 随机 8 字节 salt)   # D_i = MD5(D_{i-1} + passphrase + salt)
        │  → 32 字节 key + 16 字节 IV
AES-256-CBC + PKCS#7 填充
        │
Base64("Salted__" + salt + ciphertext)  # 密文以 U2FsdGVkX1 开头
```

- 加密字段固定为 `password`、`passwordveri`、`realname`、`idcard`。
- 每次加密使用**新的随机 salt**，同一明文两次密文不同。
- 已知互操作样本：`U2FsdGVkX1+XT5RHET9nj1g596L2dfzHBYuZLXYyWJI=`
  解密为明文 `123456`（已用 pycryptodome 交叉核对）。
- 本库实现：`gen4399/_aes.py`，**纯标准库**（自实现 AES-256 + `hashlib.md5`），
  不新增运行时依赖；`encrypt_aes()` 用于提交，`decrypt_aes()` 仅用于互操作验证。
- 这不是安全存储/保密方案：口令公开、实现只用于构造符合协议的表单字段。

## 4. 结果判定（启发式）

4399 失败响应的实测结构：HTTP **200** 重渲染 HTML，错误文案在

```html
<div id="Msg" class="login_hor login_err_tip">用户名格式错误</div>
```

失败页同时含 `isAutoRegSuccess=false`。实测请求（空用户名）：

```
POST /ptlogin/register.do
body: appId=www_home&regMode=false&level=4&username=&password=&passwordveri=&sessionId=&sec=1
→ 200 text/html → <div id="Msg">用户名格式错误</div>
```

本库 `_classify_response()` 的判定顺序（成功标记先于错误文案，避免把带
「注册成功」文案的成功页误判为失败）：

| 顺序 | 条件 | `kind` | `ok` |
|---|---|---|---|
| 1 | `isAutoRegSuccess` 赋值/逗号/冒号后接 `true`（不含 `== true` 比较式） | `success` | `True` |
| 2 | `<div id="Msg">` 有非空文案 | `rejected` | `False` |
| 3 | 提交后新增登录 Cookie：`Pauth` / `Uauth` / `Xauth` / `user_4399` / `ck_accname` | `success` | `True` |
| 4 | 页面含「验证码」或 `captcha` | `captcha` | `False` |
| 5 | 最终 URL 跳离 `ptlogin.4399.com`（且 2xx/3xx） | `success` | `True` |
| 6 | 其它 | `unknown` | `False` |

- **成功响应未经实测**，2/3/4 都是代码推断；`success` 只代表「可判定为成功」。
- 第 4 条会先把 URL 的 query/fragment 去掉再写进 `SubmitResult.final_url`，避免带出 PII。
- `SubmitResult.login_cookies` 记录提交后 CookieJar 中**出现过的登录 Cookie 名字**
  （不含值）；`field_names` 记录提交字段名（不含值）；服务端文案中的已知
  密码/身份证/姓名会被替换成 `***`。
- `unknown` 不代表失败：请登录 `https://u.4399.com/` 确认；**不要**立即重跑 `--yes`
  （可能已建号，重跑要么被拒要么造成重复注册）。

## 5. 安全与合规

- **库不会自动提交，但 API 调用即提交**：必须由调用方显式调用
  `submit_registration()`；其默认 `dry_run=False`（**调用即提交**），推荐先显式传
  `dry_run=True` 检查 `sec` / 字段数 / 加密字段。CLI 默认 dry-run（不带 `--yes` 只做
  dry-run，需要 `--yes` 才发 POST）。
- **dry-run 不发送 PII**：dry-run 只 `GET regFrame.do`（查询参数不含 PII，
  只有 appId/level/时间戳等），本地组装与加密字段后即返回，不发 POST、不建号。
- **PII 只发往 4399 官方端点**：`ptlogin.4399.com`；不经过任何第三方服务器。
  `sec=1` 时先加密再发，但如第 3 节所述，该加密不提供机密性保护。
- **仅限本人真实身份**：使用他人身份证号可能违法，也违反 4399 用户协议。
  **禁止批量注册他人账号**；CLI 检测到多身份时会在 stderr 警告。
- **遵守 ToS**：4399 用户协议/用户守则禁止未经许可的自动化注册与批量操作；
  是否允许脚本提交请自行确认。
- **POST 不自动重试**：超时 / 5xx / 429 均直接抛错，防止重复注册。
- **不绕过验证码/风控**：出现 `captcha` 时需人工处理。
- 结果对象与日志不含明文密码、身份证或 Cookie 值；`SubmitResult.to_dict()` 可安全落盘。
  服务端文案（`message`）若回显提交的密码/身份证/姓名，会先替换为 `***`。

## 6. 未验证项与已知限制

| 项 | 状态 |
|---|---|
| `register.do` **成功响应**（登录 Cookie / `isAutoRegSuccess` / 跳转） | ❌ 未实测（未创建真实账号），判定为启发式 |
| `web` 路径 `POST /user/?_c=reg` | ❌ 未实测，本库不提交 |
| `appId` / `level` 不同取值的服务端差异 | ⚠️ 只验证了表单能拉取，未验证提交效果 |
| 服务端是否会拒绝回放的 hidden 域 / 过期会话 | ⚠️ 未系统验证（本库按服务端返回值回传） |
| 实名/身份证服务端核验细节（`realNameVerify.do` 等） | ⚠️ 未纳入本库 |
| 图形验证码、风控升级、频率限制 | ⚠️ 未处理；遇到即 `captcha` 或网络错误 |
| ToS/协议文本是否随流程变化 | ⚠️ 以 `getUserAgreements.do` 实际下发为准 |

## 7. 代码位置与用法

| 文件 | 内容 |
|---|---|
| `gen4399/submit.py` | `submit_registration()`、`SubmitResult`、`SubmitError`、`_build_payload()`、`_classify_response()` |
| `gen4399/_aes.py` | `PASSPHRASE`、`encrypt_aes()` / `decrypt_aes()`、`CryptoError`（纯标准库 AES-256-CBC） |
| `gen4399/remote/_http.py` | `RemoteSession`（CookieJar，GET 重试 / POST 单次）、`parse_registration_form()`、`HttpResponse`、`RegFormSnapshot`；内部常量 `REG_FRAME_URL` / `REGISTER_URL` / `DEFAULT_REFERER` |
| `gen4399/cli.py` | `submit` 子命令、legacy `--submit/--yes/--app-id/--level`、`_cmd_submit()` |
| `gen4399/__init__.py` | 2.1.0 顶层导出 `submit_registration` / `SubmitResult` / `SubmitError` |

### Python API

```python
from gen4399 import (
    RegistrationProfile, prepare_registration,
    submit_registration, SubmitResult, SubmitError,
)

profile = RegistrationProfile("张三", "460206194611192084", qq="123456789")
bundle = prepare_registration(profile, path="unified")

# dry-run：只 GET 表单，不发 POST
r = submit_registration(bundle, dry_run=True)
print(r.kind, r.endpoint, r.encrypted_fields)
# dry_run https://ptlogin.4399.com/ptlogin/register.do
# ('password', 'passwordveri', 'realname', 'idcard')

# 真实提交（仅限本人身份）：
# r = submit_registration(bundle, dry_run=False)
# if r:  ...
# print(r.to_dict())   # 脱敏、可 JSON 序列化
```

异常：`SubmitError`（路径不支持等）、`TypeError` / `ValueError`（参数非法）、
`RemoteError` 子类（GET/POST 网络失败；POST 不会自动重试）。

### CLI

```bash
# dry-run（默认）：只 GET 表单，不发 POST
gen4399 submit --realname 张三 --idcard 460206194611192084

# 真实提交：显式 --yes
gen4399 submit --realname 张三 --idcard 460206194611192084 --yes

# 指定 appId / level / 超时 / JSON / 输出
gen4399 submit --realname 张三 --idcard ... --app-id u4399 --level 4 \
    --timeout 10 --json --output out/

# 批量身份（仅本人或已获授权；>1 时 stderr 警告）
gen4399 submit --profile-file ids.txt --yes

# legacy 模式（必须显式 --form-path unified）
gen4399 --submit --form-path unified --yes --realname 张三 --idcard ...
```

退出码：**0** 成功或 dry-run；**1** 被拒 / `unknown` / 需要验证码；
**2** 参数、网络或配置错误（含 legacy 模式 `--form-path web`）。

### 复核建议

协议可能随 4399 前端改版而变化。定期用 dry-run 复核：

1. `GET` 的 `regFrame.do` 是否仍返回表单、`sec` 是否仍为 `1`；
2. `<form action>` 是否仍是 `/ptlogin/register.do`；
3. hidden 字段集合是否变化（本库以服务端返回为基线，通常无需改代码）；
4. AES 样本是否仍可互操作（`gen4399/_aes.py` 的已知样本测试）。

## 8. 来源

- `~/4399recon/REPORT-full.md` —— 4399 Web 注册协议逆向报告（2026-11-07）
- `~/4399recon/protocol-username-register.json` —— 机器可读协议规格
  （`meta.not_verified` 明确列出 `register.do success response`）
- `~/4399recon/validation.js` —— `encryptAES()` / 表单校验
- `~/4399recon/regframe.html` / `regframe_my.html` —— 注册表单页样本
- `~/4399recon/reg_post_resp.html` —— 失败响应样本
