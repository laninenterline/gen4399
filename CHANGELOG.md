# Changelog

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

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
