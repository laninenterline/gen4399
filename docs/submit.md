# 提交注册协议与用法（web / unified，2.2.0）

本文记录 gen4399 的真实注册提交流程。协议细节来自 2026-11-07 对 4399 公开页面与
前端 JS 的被动分析、对公开接口的少量无害探测，以及 `~/4399recon/` 中的历史抓包样本
（`REPORT-full.md`、`protocol-username-register.json` 等）。

2.1.0 支持 `unified`（ptlogin）路径，2.2.0 起也支持 `web`（web.4399.com 用户中心）
路径。

> **重要边界**：研究过程**没有创建任何真实账号**，因此
> **两条路径的成功响应都属于推断、未经实测**。本库的成功判定只能是启发式的，
> 最终请以能否登录 `https://u.4399.com/` 为准。
>
> 请只使用**本人**真实身份信息，并遵守 4399 用户协议；禁止批量注册他人账号。

## 0. 两条路径对比

| | `web`（web.4399.com 用户中心） | `unified`（ptlogin 统一注册） |
|---|---|---|
| 注册页 | `https://web.4399.com/user/reg.php` | `https://u.4399.com/register.html` / 弹窗 |
| 提交接口 | `POST https://web.4399.com/user/?_c=reg`（浏览器用 JSONP GET） | `POST https://ptlogin.4399.com/ptlogin/register.do` |
| 前置请求 | `GET /user/?_c=login&_a=checkUser` 取 `encryptCode` | `GET /ptlogin/regFrame.do` 取隐藏域/Cookie |
| 密码加密 | `encode_4399()`：DES/3DES-ECB + 零填充 + `0x`+hex | `encryptAES()`：AES-256-CBC（CryptoJS 口令模式） |
| 其他 PII | `true_name` / `sfz` **明文**在 HTTPS POST body | `realname` / `idcard` 也 AES 加密 |
| 响应格式 | JSONP `{state, code, msg, validateState}` | HTML（`<div id="Msg">` / `isAutoRegSuccess` / Cookie） |
| 本库加密字段 | `login_password`、`relogin_pwd`（DES） | `password`、`passwordveri`、`realname`、`idcard`（AES） |

> **PII 取舍**：`web` 路径的密码只有页面同款 DES（公开算法，无现代机密性），
> 姓名/身份证是明文（HTTPS 保护传输，但服务端可见）。更在意 PII 时优先用
> `unified` 路径（4 个敏感字段都 AES 加密）。

---

## 1. web 路径（2.2.0）

### 1.1 流程

| 步骤 | 请求 | 作用 |
|---|---|---|
| 1 | `GET https://web.4399.com/user/?_c=login&_a=checkUser&user=<登录名>&jsoncallback=<cb>` | 返回 JSONP `{state,data,url}`；`data` 是密码加密 key（实测 6 位 hex，如 `5c43e3`） |
| 2 | 本地 `encode_4399(password, data)` | 分别加密 `login_password` / `relogin_pwd` |
| 3 | `POST https://web.4399.com/user/?_c=reg&jsoncallback=<cb>` | 表单体提交（见 1.3） |
| 4 | 解析 JSONP `{state, code, msg, validateState}` | 成功/验证码/失败判定（见 1.4） |

浏览器原流程第 3 步是 **JSONP GET**（`$.getJSON('/user/?_c=reg&jsoncallback=?&'+param)`），
所有字段都在 URL query 里。本库改用 **POST 表单体**（`jsoncallback` 仍放 query，
服务端实测同样接受），避免姓名/身份证进入 URL 日志。`cid` 固定 `3000`
（取自注册页 hidden 域）。

### 1.2 `encode_4399()`（DES/3DES）

4399 web 注册页 `action.js` 中的实现：

```js
encode_4399: function(str, key){
    return util.str_to_hex(util.des(key, encodeURIComponent(str), 1, 0));
}
```

语义（本库用纯标准库实现于 `gen4399/_des.py`）：

```
明文 = encodeURIComponent(value)          # UTF-8 百分号编码
     → NUL 补齐到 8 字节倍数（已对齐则不变）
key  = encryptCode ASCII 字节：
       ≤8 字符 → DES，NUL 补齐到 8
       >8 字符 → 3DES-EDE，NUL 补齐到 24（16 字符时第三段全 0）
加密 = ECB
输出 = "0x" + 小写 hex
```

- 真实 JS 向量（node 执行站点 `action.js` 得到，已用 pycryptodome 交叉核对）：
  - `encode_4399("Abc123456", "5c43e3")` → `0xfc88a0c93a204a36f741ec06e0e7db05`
  - `encode_4399("abc123", "5c43e3")` → `0x0aeb285e9ebdec9a`
  - `encode_4399("A1b2C3d4", "0123456789abcdef")` → `0x5f7f0a3c852c28f8`
- 这不是保密方案：DES/3DES 已过时，`encryptCode` 也是服务端下发的协议 key；
  仅用于构造 4399 期望的表单字段。
- 空明文按 JS 行为返回 `"0x"`；`key` 含非 ASCII 字符会抛 `DesError`。

### 1.3 提交字段（POST body）

| 字段 | 本库取值 | 说明 |
|---|---|---|
| `cid` | `3000` | 页面固定 hidden 值 |
| `login_name` | `bundle.username` | 6~20 位字母数字 |
| `login_password` | `encode_4399(bundle.password, encryptCode)` | DES/3DES 密文 |
| `relogin_pwd` | 同上 | 确认密码，与密码用相同 key 独立加密 |
| `qq` | `bundle.qq or ""` | 选填，用于找回 |
| `true_name` | `bundle.realname` | **明文**（HTTPS body） |
| `sfz` | `bundle.idcard` | 18 位身份证，**明文**（HTTPS body） |
| `encrypt` | `1` | 表示密码为密文 |
| `jsoncallback` | `gen4399reg_*` | 放 query，服务端据此返回 JSONP |

> 浏览器端的协议勾选框 `agree` 没有 `name`，不会随表单提交；本库同样不发。
> 用户名合法性已在 `prepare_registration()` / `check_registration_form()` 本地校验。

### 1.4 响应判定（JSONP）

浏览器 `web_reg.js` 的处理逻辑：

```js
re.state        // true = 注册成功
re.validateState !== '2'  // 需要激活/补充信息（可能）
re.code == 200  // 需要图形验证码（弹验证码框）
re.code == 360  // 手机验证码错误
re.msg          // 失败文案
```

本库 `_classify_web_response()`：

| 顺序 | 条件 | `kind` | `ok` |
|---|---|---|---|
| 1 | `state == true` | `success` | `True`（`validateState` 非 2 时在 message 里提示） |
| 2 | `code in (200, 360)` | `captcha` | `False`（需人工处理验证码） |
| 3 | `msg` 非空 | `rejected` | `False`（message 为服务端文案） |
| 4 | 提交后出现登录 Cookie | `success` | `True` |
| 5 | 响应不是 JSONP | `unknown` | `False`（POST 已发出，结果不确定） |

实测（非法用户名 `"a"`，服务端在创建账号前拒绝）：

```
POST https://web.4399.com/user/?_c=reg&jsoncallback=gen4399reg_xxx
body: cid=3000&login_name=a&login_password=0x…&relogin_pwd=0x…&qq=…&true_name=…&sfz=…&encrypt=1
→ 200 JSONP: {"state":false,"code":100,"msg":"用户名只能为6~20位的字母数字组合"}
```

---

## 2. unified 路径（2.1.0）

### 2.1 端点与流程

| 步骤 | 请求 | 作用 |
|---|---|---|
| 1 | `GET https://ptlogin.4399.com/ptlogin/regFrame.do?…` | 取注册表单 HTML；下发会话 Cookie `USESSIONID`（域 `4399.com`）与风控埋点 `phlogact` |
| 2 | 解析表单 | 取 `<form action>`、全部 `type=hidden` 隐藏域、`sec` 开关 |
| 3 | 组装字段 | 以服务端隐藏域为基线，覆盖可见字段（见 2.3） |
| 4 | 加密 | `sec == "1"` 时用 AES 加密 `password` / `passwordveri` / `realname` / `idcard` |
| 5 | `POST https://ptlogin.4399.com/ptlogin/register.do` | `application/x-www-form-urlencoded`，带同一会话 Cookie |
| 6 | 解析响应 | 成功标记 → 错误文案 → 登录 Cookie → 验证码 → 跳转（见第 3 节） |

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

### 2.2 提交字段

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

### 2.3 AES 加密（`sec=1`）

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

---

## 3. unified 结果判定（启发式）

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

- **成功响应未经实测**，以上 1/3/5 都是代码推断；`success` 只代表「可判定为成功」。
- 第 5 条会先把 URL 的 query/fragment 去掉再写进 `SubmitResult.final_url`，避免带出 PII。
- `SubmitResult.login_cookies` 记录提交后 CookieJar 中的登录 Cookie 名字（不含值）；
  `field_names` 记录提交字段名（不含值）；服务端文案中的已知密码/身份证/姓名
  会被替换成 `***`。
- `unknown` 不代表失败：请登录 `https://u.4399.com/` 确认；**不要**立即重跑 `--yes`
  （可能已建号，重跑要么被拒要么造成重复注册）。

---

## 4. 安全与合规

- **库不会自动提交，但 API 调用即提交**：必须由调用方显式调用
  `submit_registration()`；其默认 `dry_run=False`（**调用即提交**），推荐先显式传
  `dry_run=True`。CLI 默认 dry-run（不带 `--yes` 只做 dry-run，需要 `--yes` 才发 POST）。
- **dry-run 仍会联网**：`unified` GET `regFrame.do`（查询参数不含 PII）；
  `web` GET `checkUser`（只带用户名）。两者都不发注册 POST、不发送姓名/身份证、
  不建号。
- **PII 流向**：只发往 4399 官方端点（`ptlogin.4399.com` / `web.4399.com`），
  不经过任何第三方服务器。`unified` 的 AES 与 `web` 的 DES 都是公开算法/口令，
  **不提供机密性保护**；`web` 的 `true_name`/`sfz` 是明文（HTTPS body）。
- **仅限本人真实身份**：使用他人身份证号可能违法，也违反 4399 用户协议。
  **禁止批量注册他人账号**；CLI 检测到多身份时会在 stderr 警告。
- **遵守 ToS**：4399 用户协议/用户守则禁止未经许可的自动化注册与批量操作；
  是否允许脚本提交请自行确认。
- **注册 POST 不自动重试**：超时 / 5xx / 429 均直接抛错，防止重复注册。
- **不绕过验证码/风控**：出现 `captcha` 时需人工处理。
- 结果对象与日志不含明文密码、身份证或 Cookie 值；`SubmitResult.to_dict()` 可安全落盘。
  服务端文案（`message`）若回显提交的密码/身份证/姓名，会先替换为 `***`。

## 5. 未验证项与已知限制

| 项 | 状态 |
|---|---|
| `unified` `register.do` **成功响应** | ❌ 未实测（未创建真实账号），判定为启发式 |
| `web` `_c=reg` **成功响应**（`state=true`） | ❌ 未实测；只实测了非法用户名被拒（`state=false, code=100`） |
| `web` 的 `validateState` 具体语义 | ⚠️ 从 JS 推断（非 2 时提示可能需激活/补充信息） |
| `web` 图形/手机验证码触发表单 | ⚠️ 从 `web_reg.js` 推断（`code=200/360`），未实际触发 |
| 浏览器 JSONP GET vs 本库 POST body | ✅ 服务端实测均接受（非法用户名探针） |
| `appId` / `level` 不同取值的服务端差异 | ⚠️ 只验证了表单能拉取，未验证提交效果 |
| 实名/身份证服务端核验细节（`realNameVerify.do` 等） | ⚠️ 未纳入本库 |
| 图形验证码、风控升级、频率限制 | ⚠️ 未处理；遇到即 `captcha` 或网络错误 |
| ToS/协议文本是否随流程变化 | ⚠️ 以 `getUserAgreements.do` 实际下发为准 |

## 6. 代码位置与用法

| 文件 | 内容 |
|---|---|
| `gen4399/submit.py` | `submit_registration()`、`SubmitResult`、`SubmitError`、web/unified 两条流程与结果判定 |
| `gen4399/_aes.py` | `PASSPHRASE`、`encrypt_aes()` / `decrypt_aes()`、`CryptoError`（unified 路径 AES-256-CBC） |
| `gen4399/_des.py` | `encode_4399()`、`DesError`（web 路径 DES/3DES-ECB） |
| `gen4399/remote/_http.py` | `RemoteSession`（CookieJar，GET 重试 / POST 单次）、`parse_registration_form()`、`HttpResponse`、`RegFormSnapshot` |
| `gen4399/cli.py` | `submit` 子命令（`--form-path web\|unified`）、legacy `--submit/--yes/--app-id/--level` |
| `gen4399/__init__.py` | 顶层导出 `submit_registration` / `SubmitResult` / `SubmitError` |
| `scripts/make_account.py` | 便捷脚本：读身份 → `prepare_registration()` → `submit_registration()` → 保存到 `accounts.json`（默认 dry-run，`--yes` 才提交） |

### Python API

```python
from gen4399 import (
    RegistrationProfile, prepare_registration,
    submit_registration, SubmitResult, SubmitError,
)

profile = RegistrationProfile("张三", "460206194611192084", qq="123456789")

# web 路径（2.2.0）
web = prepare_registration(profile, path="web")
r = submit_registration(web, dry_run=True)       # 只 GET checkUser + 本地加密
print(r.kind, r.endpoint, r.encrypted_fields)    # dry_run … ('login_password','relogin_pwd')

# unified 路径（2.1.0）
uni = prepare_registration(profile, path="unified")
r = submit_registration(uni, dry_run=True)       # 只 GET regFrame.do + 本地 AES
print(r.kind, r.endpoint, r.encrypted_fields)    # dry_run … 4 个字段

# 真实提交（仅限本人身份）：
# r = submit_registration(web, dry_run=False)
# if r: ...
```

### CLI

```bash
# web 路径
gen4399 submit --form-path web --realname 张三 --idcard 460206194611192084            # dry-run
gen4399 submit --form-path web --realname 张三 --idcard 460206194611192084 --yes      # 真实提交

# unified 路径（默认）
gen4399 submit --realname 张三 --idcard 460206194611192084                            # dry-run
gen4399 submit --realname 张三 --idcard 460206194611192084 --yes                      # 真实提交
```
