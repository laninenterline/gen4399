# Security / 隐私说明

## 报告问题

如果你发现安全问题（尤其是 PII 泄露、远程请求处理问题），请通过仓库 issue
（或私下联系维护者）报告，不要公开贴出真实身份证号/账号密码。

## 本库的边界

- **默认不提交注册**：`prepare_registration()` 只准备数据；真实提交必须显式
  调用 `submit_registration()`（CLI 加 `--yes`；CLI 默认 dry-run）。
- **支持 `web` / `unified` 两条路径**（2.2.0 起）：`unified` 提交 `POST /ptlogin/register.do`，
  `web` 提交 `POST /user/?_c=reg`（web.4399.com）。两者都需显式调用 / `--yes`。
  2.3.0 起 `web` 路径支持图形验证码流程（`captcha=` 回调 / `--captcha-prompt` /
  `--captcha-cmd`）：验证码图片由 4399 下发、由调用方自行识别，本库不做自动破解。
- **只应使用本人的真实身份信息**：使用他人身份证号可能违法，也可能违反 4399 用户协议。
- 身份信息默认只在内存中使用；只有显式调用 `load_profiles` / 传 `--profile-file` 才会读取文件。
  只有显式真实提交时，姓名/身份证等字段才会发往 4399 官方端点，不经过任何第三方服务器：
  `unified` 路径 `sec=1` 时 AES 加密；`web` 路径只有密码用 DES 加密，
  `true_name` / `sfz` 是**明文**放在 HTTPS POST body（比浏览器原 JSONP GET 的 query
  更不易进 URL 日志，但仍是明文）。
- dry-run 只发 GET（unified：注册表单页；web：`checkUser`，只带用户名），
  不含姓名/身份证、不发注册 POST、不建号；但 dry-run 仍会联网。
- `--show-pii` 会明文显示身份证/密码/QQ；`--output`/`save()` 默认 0600 权限且默认打码。
- 日志与错误信息不会包含密码或完整身份证号；`repr(Account)` / `repr(RegistrationBundle)` /
  `repr(SubmitResult)` 已脱敏；`SubmitResult.to_dict()` 不含密码/身份证/Cookie 值，
  只含字段名、Cookie 名与脱敏后的 `message`/端点/状态等；服务端文案里若回显
  密码/身份证/姓名，会先替换为 `***`。

## 提交能力：风险与同意要求

使用 `submit_registration(..., dry_run=False)` 或 `gen4399 submit --yes` 前，请确认：

1. **你提交的是本人的真实身份信息**；使用他人身份证号可能违法，也违反 4399 用户协议。
2. **你已阅读并同意 4399 用户协议/隐私政策**。4399 用户协议与用户守则禁止未经许可的
   自动化注册与批量操作；是否允许脚本提交请自行确认。
3. **不要批量注册**：不要用本库为他人或批量创建账号。CLI 检测到多身份时会在 stderr
   警告，但那只是提醒，不构成任何授权。
4. **PII 流向**：真实提交只把字段发往 4399 官方端点（`ptlogin.4399.com` /
   `web.4399.com`）。`unified` 的 AES 口令 `lzYW5qaXVqa` 与 `web` 的 DES 算法/
   `encryptCode` 都公开在前端 JS 中，**都不构成机密性保护**，只是协议要求；
   `web` 的 `true_name`/`sfz` 更是明文（HTTPS body）。更在意 PII 时优先用 `unified`。
5. **先 dry-run**：库不会自动提交、CLI 默认 dry-run；先跑一次 dry-run 检查端点/字段/
   加密开关（`unified` 看 `sec`，`web` 看 `encryptCode`/DES 字段），确认后再加 `--yes`。
6. **POST 不自动重试**：超时后服务端可能已建号；请先尝试登录确认，不要立即重跑。
7. **成功判定**：`web` 路径的成功响应已实测（`{"state":true,"code":300,...}` +
   `Pauth`/`Pauths` 等登录 Cookie），但仍建议以登录 `https://u.4399.com/` 为准；
   `unified` 路径实测只返回空白「提示」页（风控空壳，无法判定），`unknown` 不代表失败。
8. **不绕过风控**：本库不破解图形验证码——`captcha` 回调由调用方实现
   （人工输入或外部 OCR）；识别不出时如实返回 `kind=captcha`。同一身份证在
   4399 只能绑定一个账号。

## 建议

- 身份文件请 `chmod 600`（库会对过宽权限给出警告）。
- 不要将 `--show-pii` 的输出贴到聊天/issue/日志。
- 远程接口有频率限制，请遵守 `--min-interval`/重试策略，避免批量骚扰。
