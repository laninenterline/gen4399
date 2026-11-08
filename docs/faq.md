# 常见问题（FAQ）

**Q：为什么密码不能预校验？**
4399 没有密码校验接口，只有注册提交时才校验；本库只能保证通过公开规则。

**Q：`fetch` 为什么经常返回空 / 报频率限制？**
`regFrame.do` 会限流。调大 `--retry-delay`、加 `--min-interval`，或改用本地生成。

**Q：规则会变吗？**
会。`python scripts/verify_rules.py` 做冒烟检查；见 [docs/rules.md](docs/rules.md)。

**Q：能自动提交注册吗？**
2.1.0 起可以，2.2.0 起 `web` / `unified` 两条路径都行，但必须**显式触发**：
库不会自动提交；CLI 需加 `--yes`（默认 dry-run），API 需显式调用
`submit_registration()`（默认 `dry_run=False`，建议先传 `dry_run=True`）。
仅限本人真实身份、遵守 4399 用户协议。两条路径的成功响应均已在 2026-11-08 实测
建号成功（web 含图形验证码流程；unified 剔除隐藏域后跑通），但仍建议以登录
`https://u.4399.com/` 为准。

**Q：unified 会提交实名信息吗？**
会，默认就提交：`UNIFIED_SEND_REALNAME=True`，`realname`/`idcard` 与密码一起
AES-256-CBC 加密（`encrypted_fields` 4 个），实测账号 `abnsm4uw2s77` 即此版本。
确实想建「不实名」账号时，把 `gen4399.submit.UNIFIED_SEND_REALNAME` 设为 `False`
（模块属性，运行期有效），payload 会去掉姓名/身份证（`encrypted_fields` 变 2 个）。
注意 `reg_eula_agree`/`autoLogin`/`fCaptcha` 无论如何都要剔除，否则会回到空白提示页。

**Q：遇到图形验证码怎么办？**
传 `captcha` 回调：`submit_registration(..., captcha=solver, captcha_attempts=3)`。
库里自带三种现成实现：

- `matcher_captcha_solver()`（`--captcha-matcher`）：内置识别器，专解 4399 的
  60×30 四位验证码（unified 路径），实测第 1 轮通过；需要本机 ImageMagick 解码。
- `command_captcha_solver(cmd)`（`--captcha-cmd`）：PNG/JPEG 走 stdin，stdout 首行作为结果。
- `prompt_captcha_solver()`（`--captcha-prompt`）：存图 + 人工输入，配合
  `--captcha-zoom 6~8` 把人眼难认的小图放大。

`auto_captcha_solver()`（`--captcha-auto`）会按「内置识别器 → OCR → 人工」自动回退。
不传回调时遇到验证码只返回 `kind="captcha"`，不会建号。

**Q：dry-run 会联网吗？**
会，但只发 GET、不发注册 POST、不建号：`unified` 路径 `GET regFrame.do` 拉表单；
`web` 路径 `GET checkUser` 取 `encryptCode`（只带用户名）。dry-run 只在内存组装字段，
`unified` 不会发送姓名/身份证、`web` 也不会；用于确认接口/加密
是否仍符合预期。

**Q：POST 超时/失败会自动重试吗？**
不会。POST 永远单次尝试，避免服务端其实已建号却被重复提交；超时后请先尝试登录确认。

---

返回 [README](../README.md)。
