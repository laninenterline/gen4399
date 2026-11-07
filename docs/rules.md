# 4399 注册规则快照与维护

本库的规则来自 4399 前端 `validation.js` 与注册页提示，**不是官方文档**。
4399 可能随时改规则；这里记录快照与复核流程。

## 当前快照

| 项 | 值 |
|---|---|
| `RULES_VERSION` | `4399-2026-11` |
| 核对日期 | 2026-11-07 |
| 来源 | `web.4399.com/user/reg.php`、`u.4399.com/register.html`、`ptlogin.4399.com/ptlogin/regFrame.do` |

## 规则摘要

- 密码：6~20 位，仅 ASCII 字母数字；不能纯数字 / 纯小写 / 纯大写
- 用户名：6~20 位，仅 ASCII 字母数字；允许纯数字
- 真实姓名：2~30 位中文，或英文姓（空格分隔）
- 身份证：18 位，生日合法（1850~2050），GB 11643 校验码正确；4399 拒绝 15 位
- QQ：4~11 位数字（选填）

## 复核流程

```bash
python scripts/verify_rules.py
```

脚本会 GET 上述页面并检查关键字符串（`CheakPWD` / `CheakUsername` / `6~20` /
`字母和数字`）。退出码 0 = 全部命中；1 = 有关键字缺失（规则可能变了）；
2 = 网络错误。

> 只有 GET + 关键词搜索，不提交任何数据。

## 规则变化时怎么改

1. 打开注册页/`validation.js`，确认新规则；
2. 更新 `gen4399/core.py`（密码/用户名常量与 `validate*`）；
3. 更新 `gen4399/identity.py`（姓名/身份证/QQ 校验）；
4. 更新 `gen4399/forms.py`（字段定义）；
5. 更新 `gen4399/_rules.py` 的 `RULES_VERSION` / `RULES_CHECKED_AT`；
6. 补测试并更新本文件。

## 提交协议（unified 2.1.0 / web 2.2.0 / 图形验证码 2.3.0）

> 来源：`~/4399recon/REPORT-full.md` / `protocol-username-register.json`
> （2026-11-07 被动分析 + 少量无害探测，当时未创建真实账号）；
> 2026-11-08 对 web 路径做了真实建号实测（1 个账号，完整走通图形验证码）。
> 详细说明见 [docs/submit.md](submit.md)。

### 端点与前置

| 步骤 | 请求 | 说明 |
|---|---|---|
| 1 | `GET https://ptlogin.4399.com/ptlogin/regFrame.do?...` | 注册面板；下发 `USESSIONID`（Domain=4399.com）与 `phlogact` 风控 Cookie；返回表单 HTML |
| 2 | `POST https://ptlogin.4399.com/ptlogin/register.do` | 表单 `action`（相对路径）；`application/x-www-form-urlencoded`；同一会话 Cookie |

`regFrame.do` 关键查询参数：`regMode=reg_normal`、`postLoginHandler=refreshParent`、
`appId`（`u4399` / `my` / `www_home`）、`level`（`u4399` 为 4）、`regIdcard=true`、
`externalLogin=qq`、`mainDivId=popup_reg_div`、`v=<毫秒时间戳>`。

### 必填字段

`username`（3~20，字母数字/@）、`password` + `passwordveri`（6~20，两者相同）、
`realname`、`idcard`（18 位，15 位被拒）、`reg_eula_agree=on`、`sec`、`appId`、`level`；
`email` 放 QQ 号（选填）。其余 hidden 域（`regMode` / `postLoginHandler` /
`mainDivId` / `sessionId` 等）以服务端 `regFrame.do` 返回值为基线原样回传。

### sec 与 AES

- `sec=1` 时加密 `password` / `passwordveri` / `realname` / `idcard`
  （4399 前端 `validation.js` 的 `encryptAES()`）。
- 格式：CryptoJS 口令模式 —— `EVP_BytesToKey(MD5, 8 字节 salt)` →
  AES-256-CBC + PKCS#7 → `Base64("Salted__" + salt + ciphertext)`；
  密文以 `U2FsdGVkX1` 开头，每次 salt 随机。
- 口令：`lzYW5qaXVqa`（公开硬编码，不是秘密）。
- 已知样本：`U2FsdGVkX1+XT5RHET9nj1g596L2dfzHBYuZLXYyWJI=` ↔ `123456`。
- 实现：`gen4399/_aes.py`，纯标准库；`encrypt_aes()` 每次随机 salt，
  `decrypt_aes()` 仅用于互操作验证。**该加密不提供机密性保护**。

### 失败页结构

HTTP 200 重渲染 HTML，错误在
`<div id="Msg" class="login_hor login_err_tip">...</div>`，同页含
`isAutoRegSuccess=false`。实测样本：空用户名 → `用户名格式错误`。

### 成功响应（未实测；且实测被风控页挡住）

`register.do` 的成功响应**没有实测样本**（2026-11-07 研究过程未创建真实账号）。
2026-11-08 实测 `POST register.do` 返回一个空白「4399提示」页：`info_page` 壳，
无 `<div id="Msg">`、无登录 Cookie，由 `oauthValidation.js` / `fingerprint2` 等
风控/JS 校验脚本驱动，**纯 HTTP 无法完成，结果无法从响应判定**（归 `unknown`）。

本库判定为启发式：

1. `isAutoRegSuccess=true` → `success`（先于错误文案，避免成功页带「注册成功」Msg 被误判）；
2. `Msg` 非空 → `rejected`；
3. 新增登录 Cookie（`Pauth`/`Uauth`/`Xauth`/`user_4399`/`ck_accname`）→ `success`；
4. 含「验证码」→ `captcha`；跳离 ptlogin → `success`；否则 `unknown`。

最终以登录 `https://u.4399.com/` 为准；`unknown` 不代表失败。

### web 路径提交（2.2.0；图形验证码 2.3.0）

注册页 `https://web.4399.com/user/reg.php` 的表单会被 JS 接管，流程与 ptlogin 不同：

1. `GET https://web.4399.com/user/?_c=login&_a=checkUser&user=<登录名>&jsoncallback=<cb>`
   → JSONP `{state, data, url}`，`data` 即密码加密 key `encryptCode`
   （实测 6 位 hex，如 `5c43e3`；`state` 表示用户名是否可用）。
2. 密码加密：`encode_4399(pwd, encryptCode)`，来自站点 `action.js`：
   `"0x" + hex(DES/3DES-ECB(encodeURIComponent(pwd), key))`；
   key ≤8 字符用 DES、>8 字符用 3DES-EDE，key/明文均 NUL 补齐（明文补齐到 8 字节倍数）。
   实现：`gen4399/_des.py`（纯标准库）；真实 JS 向量见 `tests/test_des.py`。
3. 提交：浏览器用 JSONP GET
   `GET /user/?_c=reg&jsoncallback=?&cid=3000&login_name=…&login_password=0x…&relogin_pwd=0x…&qq=…&true_name=…&sfz=…&encrypt=1`；
   本库改用 **POST 表单体**（`jsoncallback` 放 query，服务端实测同样接受），
   避免姓名/身份证进入 URL 日志。
4. 响应 JSONP：`{state, code, msg, validateState}`。
   `state=true` → 成功（`validateState !== '2'` 时页面提示可能需激活/补充信息）；
   `code=200`（图形验证码）/`360`（手机验证码）→ `captcha`；否则 `msg` → `rejected`。
5. 图形验证码（2.3.0）：`code=200` 时
   `GET /util/?_c=code&t=reg` → `image/png`（150×45，响应 `Set-Cookie: WEBSESSION=…`，
   必须同会话）→ 调用方 `captcha` 回调识别（**库不内置破解**）→
   `GET /user/?_c=reg&_a=verifyCode&code=<code>`，`{"state":true}` 通过、`{"state":false}` 错误
   → 带 `chk_code=<code>` 重提交 `POST /user/?_c=reg`；最多 `captcha_attempts` 轮
   （默认 3），每轮重新取图，识别空串跳过 `verifyCode`。
6. 重提交成功响应（2026-11-08 实测）：
   `{"state":true,"code":300,"msg":"","validateState":"2","toUrl":"/hall.html"}`，
   并下发 `Puser`/`Pauth`/`Pauths`/`Pnick`/`ck_accname` 登录 Cookie。

字段：`cid=3000`、`login_name`、`login_password`（密文）、`relogin_pwd`（密文）、
`qq`、`true_name`、`sfz`、`encrypt=1`；验证码重提交额外带 `chk_code`（首次不带）。
页面上的协议勾选框没有 `name`，不随表单提交。

**实测状态（2026-11-08）**：web 路径**已实测建号成功**——完整走通
`code=200 → 取图 → 识别 → verifyCode → 带 chk_code 重提交 → state=true`，
`SubmitResult.captcha_attempts` 为真实轮次。

**PII 注意**：web 路径只有密码用 DES；`true_name`/`sfz` 是明文（HTTPS body），
DES 本身也不提供现代机密性保护。

**实名限制**：已用于实名绑定的身份证再次注册会被服务端拒绝，实测返回
`msg="姓名身份证不匹配"`（`kind="rejected"`）；该文案与「姓名与身份证不一致」
相同，仅凭响应无法区分，不要据此断言「一证一号」。
