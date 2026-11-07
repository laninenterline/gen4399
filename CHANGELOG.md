# Changelog

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [2.2.0] - 2026-11-07

### 新增

- **web 路径真实提交**（`https://web.4399.com/user/reg.php`）：
  - `submit_registration()` 现在接受 `bundle.path in {"web", "unified"}`。
    web 流程：`GET user/?_c=login&_a=checkUser` 取 `encryptCode`（JSONP）→
    页面同款 `encode_4399()` 加密 `login_password` / `relogin_pwd` →
    `POST user/?_c=reg`（JSONP 响应）→ 按 `{state, code, msg, validateState}`
    判定（`state=true` → success；`code=200/360` → captcha；`msg` → rejected）。
  - 新增 `gen4399/_des.py`：纯标准库 DES/3DES-EDE-ECB + `encode_4399()`
    （`encodeURIComponent` + NUL 零填充 + `"0x"` hex），与站点 `action.js`
    的真实 JS 向量（node 提取）及 pycryptodome 交叉验证；不新增运行时依赖。
  - CLI `gen4399 submit --form-path web|unified`（默认 unified）；
    legacy `--submit` 默认走 web（2.1.0 时 web 会报错）。
  - 新增 `tests/test_des.py`；`tests/test_submit.py` / `tests/test_cli.py`
    增加 web 路径的 payload、DES 加密、JSONP 判定、退出码覆盖。
- 文档：`docs/submit.md` 增加 web 协议/字段/DES/判定/PII 对比章节；
  README、`docs/rules.md`、`docs/project-overview.md`、SECURITY 同步。

### 变更

- `SubmitResult.path` 现在为 `web` / `unified`；web 的 `app_id` 返回空串（不适用），
  `app_id` / `level` 参数仅 unified 使用。
- `SubmitResult.encrypted_fields`：web 为 `login_password`/`relogin_pwd`（DES），
  unified 仍为 4 个字段（AES）。
- **web 路径的 PII 处理弱于 unified**：只有密码用 DES；`true_name`/`sfz` 是明文
  放在 HTTPS POST body（浏览器原流程是 JSONP GET 放 query，本库改用 POST body
  降低 URL 日志泄露风险）。
- 两条路径的注册 POST 均**单次不重试**；`retry_policy` 只作用于 GET。
- dry-run 均只 GET：unified 拉 `regFrame.do`，web 取 `encryptCode`（只带用户名）。
- **CLI 默认身份文件**：未指定任何身份来源（无 `--profile-file`，也无
  `--realname/--idcard/--qq`）时，自动读取当前目录下的 `sfz.txt`；文件不存在则
  退出码 2 并提示。`gen4399 profile check --profile-file` 改为可选（默认同上）。
- `__version__ = "2.2.0"`；仍为**零运行时依赖**（AES/DES 均为纯标准库实现）。

### 安全

- web dry-run 不发送姓名/身份证；真实提交才发送，且仅发往 4399 官方端点。
- 成功判定仍是启发式：web 的 `state=true` 成功响应**未实测**（只实测了
  非法用户名被拒 `state=false, code=100`），请以登录 `https://u.4399.com/` 为准。

## [2.1.0] - 2026-11-07

### 新增

- **真实 POST 提交（仅 `unified` 路径）**：
  - `submit_registration(bundle, *, app_id="u4399", level=4, timeout=10.0,
    dry_run=False, retry_policy=None)` → `SubmitResult`
    （`kind` = `success` / `rejected` / `captcha` / `unknown` / `dry_run`）；
    `SubmitError` 表示参数/路径不合法。CLI 侧默认 dry-run。
  - CLI 新增 `submit` 子命令：`gen4399 submit --realname … --idcard …`
    默认 dry-run，加 `--yes` 才真实提交；支持 `--form-path unified`（默认）、
    `--app-id`、`--level`、`--json`、`--output`；legacy 模式新增
    `--submit` / `--yes` / `--app-id` / `--level`。退出码 0/1/2。
  - 提交流程：GET `regFrame.do`（会话 Cookie + 表单 hidden 域）→ 解析
    `<form action>` / `sec` → `sec=1` 时 AES 加密
    `password` / `passwordveri` / `realname` / `idcard` → POST `register.do` →
    解析 `<div id="Msg">` / `isAutoRegSuccess` / 登录 Cookie / 跳转。
  - `gen4399/_aes.py`：CryptoJS 兼容的 AES-256-CBC
    （`EVP_BytesToKey(MD5, 8B salt)` + PKCS#7 + `Salted__` 格式），
    **纯标准库**实现；附 `decrypt_aes()` 用于互操作验证。
  - `gen4399/remote/_http.py`：`RemoteSession`（CookieJar 会话；GET 可重试、
    POST 单次）、`HttpResponse`、`RegFormSnapshot`、`parse_registration_form()`。
  - `gen4399/__init__.py` 导出 `submit_registration` / `SubmitResult` / `SubmitError`；
    新增 `docs/submit.md`（协议、字段、AES、判定规则、未验证项）。
  - `RegistrationBundle.as_text()` 尾注改为「手动填表；或用 submit 提交（需 --yes）」。

### 变更（可能影响调用方）

- **库不会自动提交**：`prepare_registration()` 仍只准备数据；真实提交必须显式
  调用 `submit_registration()`（API 默认 `dry_run=False`，调用即提交；CLI 默认
  dry-run，必须加 `--yes`）。
- **（2.1.0 行为）只支持 `unified`**：`bundle.path == "web"` 提交抛 `SubmitError`
  （2.2.0 起 web 路径已支持，见上）。
- **POST 不自动重试**（超时 / 5xx / 429 直接抛错），避免服务端已建号却重复提交；
  `retry_policy` 只作用于 GET 注册表单。
- `SubmitResult` 的 `repr()` / `to_dict()` 已脱敏：不含明文密码/身份证/Cookie 值，
  `final_url` 去掉 query/fragment。
- **不新增运行时依赖**：AES 由 `_aes.py` 用标准库自实现。

### 安全

- 库不会自动提交（CLI 默认 dry-run）；dry-run 只 GET 表单（不发 POST、不发送 PII）。
- 真实提交的 PII 只发往 4399 官方端点 `ptlogin.4399.com`；`sec=1` 时先 AES 加密，
  但该口令公开在前端 JS 中，**不提供机密性保护**。
- 仅限本人真实身份、遵守 4399 用户协议、禁止批量注册他人账号
  （CLI 多身份时在 stderr 警告）。
- **成功判定为推断**：4399 `register.do` 的成功响应未经实测（研究过程未创建真实账号），
  `success` 为启发式判定；请以登录 `https://u.4399.com/` 为准。
- 不绕过验证码/风控；`captcha` 时需人工处理。

## [2.0.0] - 2026-11-07

### 新增

- **2.0 子命令 CLI**：`generate` / `check` / `account` / `fetch` / `available` /
  `form` / `prepare` / `profile check` / `rules` / `version`；旧 flag 模式保留兼容。
- 全局增强：`--json`、`--offline`、`--output DIR`（0600 文件）、
  `--password-length`、`--retries` / `--retry-delay` / `--max-total-timeout`、
  `--min-interval`、`-v/--verbose`。
- `RetryPolicy`：指数退避 + 抖动 + 单次封顶 + 总 deadline + 优先 `Retry-After`；
  远程错误对象带 `url` / `status` / `retry_after`。
- `check_username(validate_input=True)` 本地预校验，明显非法名称不再发请求。
- `fetch_suggested_usernames(with_availability=True)` 返回可用性对象。
- `Account.to_dict()/save()`、`RegistrationBundle.to_dict()/save()`；
  落盘默认 0600 且打码。
- `generate*` / `generate_username*` 支持 `charset=` 自定义字符集。
- 身份文件增强：stdin（`--profile-file -`）、表头自动跳过、默认去重、
  `errors="skip"`、权限过宽警告、行号错误。
- `--rules-version` + `gen4399/_rules.py` + `scripts/verify_rules.py` 规则冒烟检查。
- `docs/rules.md`、`SECURITY.md`、`CONTRIBUTING.md`、`.pre-commit-config.yaml`、
  property-based 测试（hypothesis，可选）。
- `validate_fixed_part` 成为公开主名（`check_fixed_part` 保留别名）。
- `gen4399/identity.py` 从 `forms.py` 拆出（身份对象/字段校验/txt 读取）；
  `gen4399/remote.py` 拆成 `remote/_http.py`（传输/重试）+ `remote/_api.py`（业务）。

### 变更（可能影响调用方）

- **Python 最低版本 3.10**（3.8/3.9 已 EOL）。
- CLI 的 `-n` 继续兼容旧语义，但推荐改用 `--password-length` / `--username-length`。
- CLI `--show-pii` 会额外打印明文警告。
- 远程默认重试策略改为 `RetryPolicy`（fetch 外层 4 次、HTTP 层 2 次、带总超时能力）。
- 身份文件默认按身份证去重（可用 `dedupe=False` 关闭）。
- 测试/覆盖率门槛 90%；CI 增加 mypy（观察项）与 build/twine 检查。

## [1.10.0] - 2026-11-07

### 新增

- `load_profiles(path)`：从 txt 批量读取身份信息，返回逐行校验过的
  `RegistrationProfile` 列表；支持空行 / `#` 注释 / UTF-8 BOM / 全角竖线 `｜`。
- `parse_profile_line(line)`：解析单行身份信息，
  格式 `真实姓名|身份证号[|QQ]`（2~3 列）。
- CLI 新增 `--profile-file FILE`：`--prepare` / `--build-form` / `--check-form`
  均可用，且支持**多行批量**（每个身份输出一段，带 `# 身份 i/n` 标号）。
- 身份文件任一行不合法时整体报错，错误信息带行号；文件不存在/不可读时
  统一退出码 2，不再出现 traceback。

### 变更

- `--profile-file` 与 `--realname/--idcard` 互斥（同时使用会报错退出码 2）。

## [1.9.0] - 2026-11-07

### 修复

- `check_username()` 不再把空响应 / HTML 错误页静默当成"用户名已被注册"：
  无法识别的响应现在抛 `RemoteParseError`。
- `UsernameAvailability` 新增 `kind` 字段，区分为
  `available` / `taken` / `invalid` / `unknown`。
- `_parse_suggested_username()` 不再依赖属性顺序与引号样式
  （`value` 写在 `id` 前、单引号、跨行属性都能正确解析），
  改为“先定位整个 `<input>` 标签、再取 `value` 属性”的实现。
- `fetch_suggested_usernames(unique=True)` 现在会凑满请求数量；
  凑不满时抛 `RemoteError`，不再静默少返回。
- `generate_account()` 对显式传入的 `username` 增加本地规则校验
  （即使 `verify_username=False`），不再返回非法用户名。
- `validate_qq()` 先 `strip()`，修复尾部 `\n` 能混过校验的问题。
- CLI `--fetch-username` 补齐异常兜底：非法 `count` / 前后缀不再抛 traceback，
  统一返回退出码 2。
- CLI `--entropy` 现在与 `generate` 一致地校验 6~20 长度范围。

### 新增

- `generate_many()` / `generate_usernames()` 新增 `unique=True` 选项，
  保证批量结果互不相同。
- `check_fixed_part()` 成为公开 API（`_check_fixed_part` 保留为兼容别名）。
- CLI 新增 `--timeout SECONDS`。
- `Account` / `RegistrationBundle` 的 `repr()` 会打码密码（和身份证号），
  可安全写日志；`Account.masked()` 返回打码副本。
- `RegistrationBundle.fields` 改为只读 `MappingProxyType`；
  `masked_fields()` 同时打码 QQ。
- 顶层导出 `DEFAULT_USER_AGENT`。

### 变更（可能影响调用方）

- `--account` 的 `-n` 现在只控制密码长度，用户名长度改用 `--username-length`
  （与 `--prepare` 语义统一）。
- 远程请求增加有限重试（超时 / 5xx / 429），退避带 ±25% 抖动并封顶 60s。
- 响应体读取上限 512 KiB。
- 版本号改为单一来源：`pyproject.toml` 动态读取 `gen4399.__version__`。
- 新增 `LICENSE`（MIT）、`CHANGELOG.md`、`.gitignore`、CI、ruff/mypy/pytest/coverage 配置。

## [1.8.1] - 2026-11-07

- 初始版本：密码/用户名生成与校验、4399 远程接口封装、注册表单本地校验、
  `prepare_registration()` 一键准备注册数据、CLI。
