# gen4399 项目全貌与架构说明（2.2.0 快照 + 2.3.0 / 2.4.0 增量）

- **对象**：`gen4399` 2.4.0（2.2.0 快照 + 2026-11-08 增量；2.2.0 tag `v2.2.0`，2026-11-07）
- **内容**：项目定位与边界、仓库地图、分层架构、4399 规则快照、各模块职责、关键数据流、API/CLI 速查、工程质量实测、PII 治理、演进史与已知问题清单。
- **方法**：通读全部源码（6,010 行，含 remote 包与 2.1.0/2.2.0 新增的 submit/_aes/_des）+ 15 个测试文件 + 全部文档；实跑 pytest / coverage / doctest；CLI 与 API 定向探针验证。
- **时效**：基于 2026-11-07 工作区快照，规则版本 `4399-2026-11`；行号引用以该版本源码为准
  （2.3.0 / 2.4.0 增量见下方说明）。

> **2.3.0 增量（2026-11-08）**：web 路径新增**图形验证码**流程（首次 POST 返回
> `code=200` → `GET /util/?_c=code&t=reg` 取图 → 调用方识别 → `verifyCode` 校验 →
> 带 `chk_code` 重提交），`submit_registration()` 增加 `captcha` / `captcha_attempts`
> 参数，`SubmitResult.captcha_attempts` 记录轮次，`HttpResponse` 新增 `raw` / `is_binary`；
> 新增 `gen4399/_captcha.py`（人工输入 / 外部命令 / 落盘，均为现成回调实现，**不破解验证码**）。
> **web 路径已实测建号成功（2026-11-08）**。
>
> **2.4.0 增量（2026-11-08）**：unified 路径**已实测建号成功**。旧版会把 `regFrame.do`
> 的隐藏域原样回传，其中 15 个（布局/防沉迷/前端开关 + 实名/协议）会让 `register.do`
> 稳定返回空白「4399提示」页（`info_page`，无 `#Msg`、无登录 Cookie）——**根因是这些
> 字段，不是风控封 IP**；按 `UNIFIED_DROP_FIELDS` 剔除后同一套数据正常建号（实际提交
> 21 个字段）。新增 `UNIFIED_SEND_REALNAME`（默认 `False`）：unified 默认**不发送**
> `realname`/`idcard`，`encrypted_fields` 只有 `("password","passwordveri")`；
> 打开它会加回实名并 AES 加密，但该组合实测仍返回空白提示页、**未跑通**。
> 已用于实名绑定的身份证再次注册会被服务端拒绝（实测 `msg="姓名身份证不匹配"`，
> 无法区分「已绑定」与「实名不通过」）。下面 2.2.0 时代的行号与「成功响应未实测」
> 表述以此说明为准。

---

## 1. 一句话定位

gen4399 是一个**零运行时依赖**（只用标准库）的 Python 工具库，围绕「4399 账号注册」这一件事，提供六层能力：

1. **本地规则引擎**：按 4399 前端校验规则生成/校验密码与用户名，估算熵，批量去重生成；
2. **官方接口封装**：调用 4399 两个公开 ptlogin 接口（`regFrame.do` 取分配账号、`isExist.do` 查用户名可注册性），带重试/退避/超时预算；
3. **注册表单知识库**：定义 web / unified 两条注册路径的字段、必填、提交地址，并做**提交前本地整表校验**；
4. **注册数据编排**：把「身份信息 → 生成用户名 → 在线查重 → 生成密码 → 整表校验 → 组装字段」串成 `prepare_registration()`，输出一份可以照着填的清单；
5. **真实提交（2.1.0–2.4.0）**：`submit_registration()` / `gen4399 submit` 支持两条路径：
   `unified` POST 到 `ptlogin/register.do`（2.4.0 剔除 15 个隐藏域后已实测跑通，
   默认不发实名，`sec=1` 时只 AES 加密 `password`/`passwordveri`）；
   `web` 先取 `encryptCode`、用 `encode_4399()`（DES）加密密码，再 POST
   `web.4399.com/user/?_c=reg`（2.3.0 起支持图形验证码）。
   **库不会自动提交**：CLI 默认 dry-run（需 `--yes`）；
   API 需显式调用 `submit_registration()`（默认 `dry_run=False`，建议先传 `dry_run=True`）。
6. **提交协议加密（纯标准库）**：`_aes.py`（CryptoJS 兼容 AES-256-CBC）与
   `_des.py`（页面同款 DES/3DES `encode_4399()`），保持零运行时依赖。

> **核心边界**：库**默认不提交注册**；`prepare_registration()` 只准备数据，真实提交必须显式开启。
> 2.2.0 起 `web` / `unified` 两条路径都可提交；2.3.0 起 web 支持图形验证码，
> 2.4.0 起 unified 也在剔除 15 个隐藏域后**实测建号成功（2026-11-08）**，且默认
> **不发送实名信息**（`UNIFIED_SEND_REALNAME=False`）。`web` 路径只有密码用 DES，
> 姓名/身份证是明文在 HTTPS body；unified 默认只上传用户名+密码（两个字段 AES）。
> 图形验证码必须由调用方提供识别回调，库不内置破解；只应使用本人真实身份。
> 定位是「半自动填表/提交助手 + 规则库」，不是批量注册器。

---

## 2. 项目边界（做什么 / 不做什么）

| 做 | 不做（刻意） |
|---|---|
| 生成合规密码/用户名（可带前后缀、自定义字符集、去重批量） | 不默认提交注册：只有显式调用 `submit_registration()` / 加 `--yes` 才发 POST（CLI 默认 dry-run） |
| 校验密码/用户名并给出机器可读违规码 | 不读取/保存 4399 账号的登录态 Cookie（提交只用于注册） |
| 封装 `regFrame.do` / `isExist.do` 两个公开 GET 接口，以及 `register.do` / `web user/?_c=reg` 提交（2.1.0 / 2.2.0 / 2.4.0） | 不提供密码「预校验」接口（4399 没有，只有提交时校验） |
| 定义两条注册路径的表单字段并做本地整表校验 | 不自动填写浏览器、不驱动浏览器（无 Selenium 依赖） |
| 从 `姓名\|身份证[\|QQ]` 的 txt 批量读身份、校验、打码、落盘 | 不绕过验证码/风控、不做协议级批量注册 |
| `unified` 按前端同款 AES 加密敏感字段；`web` 按同款 DES 加密密码（纯标准库） | 不把身份信息发送到除 4399 官方接口以外的任何服务器 |
| 提交结果解析 + 成功判定（web 与 unified 均已实测建号成功） | 不保证 `success` 一定是服务端最终结果，以登录 u.4399.com 为准 |

**合规与伦理**：README / SECURITY.md 均声明「仅限本人真实身份、遵守 4399 用户协议、不要批量注册他人账号」；2.1.0/2.2.0 的提交能力不会自动触发（CLI 默认 dry-run），两种注册 POST 都不自动重试；测试与文档中的身份证号是合成的测试夹具。

---

## 3. 仓库地图

```
lead-workspace/
├── gen4399/                  # 运行时包（零依赖）
│   ├── __init__.py   约 235 行 # 公共门面：submit / 验证码 / 端点常量导出；__version__ = "2.4.0"
│   ├── __main__.py     6 行  # python -m gen4399 → cli.main()
│   ├── core.py       661 行  # 生成/校验/熵/异常/常量（纯规则，无 IO）
│   ├── identity.py   396 行  # 姓名/身份证/QQ 校验 + RegistrationProfile + txt 读取
│   ├── forms.py      399 行  # 两条注册路径字段定义 + 整表校验 + 字段组装
│   ├── registration.py 327行 # prepare_registration 编排 + RegistrationBundle
│   ├── _aes.py       399 行  # 2.1.0 新增：CryptoJS 兼容 AES-256-CBC（纯标准库）
│   ├── _des.py       249 行  # 2.2.0 新增：4399 web 路径 DES/3DES encode_4399（纯标准库）
│   ├── _captcha.py   约 150 行 # 2.3.0 新增：验证码回调实现（人工/外部命令/落盘）+ CaptchaSolverError
│   ├── submit.py     约 915 行 # 2.1.0–2.4.0：submit_registration + SubmitResult/SubmitError + UNIFIED_DROP_FIELDS/UNIFIED_SEND_REALNAME
│   ├── remote/
│   │   ├── __init__.py 65 行 # 再导出（兼容旧 from gen4399.remote import ...）
│   │   ├── _http.py  691 行  # 传输层：urllib、RetryPolicy、错误类型、HTML 解析、CookieJar 会话、POST
│   │   └── _api.py   626 行  # 业务层：取号/查重/批量/Account/generate_*
│   ├── _rules.py      35 行  # 规则快照版本/来源/关键字
│   ├── _width.py      50 行  # CJK 终端显示宽度（表格对齐）
│   └── py.typed              # 类型标记（随包分发）
├── tests/            17 个文件，约 5,700 行，519+ 用例 + 457 subtests（含 test_aes/test_des/test_submit/test_submit_http/test_make_account*、2.3.0 验证码流程测试）
├── scripts/verify_rules.py   # 规则页面关键词冒烟检查（GET + 子串匹配）
├── scripts/make_account.py   # 便捷脚本：每次运行准备并（--yes 时）提交一个账号，追加 accounts.json（0600）；无效身份行默认跳过（--index/--strict）；--diagnose 保存脱敏响应；2.3.0 起支持验证码参数
├── docs/rules.md             # 规则快照、复核流程、改规则清单、提交协议摘要
├── docs/submit.md            # 2.1.0–2.4.0：web/unified 提交协议/字段/AES/DES/图形验证码/隐藏域剔除/判定/安全/限制
├── .github/workflows/ci.yml  # 3.10–3.13 矩阵 × 7 道门禁
├── pyproject.toml            # 版本单一来源、pytest/coverage/ruff/mypy 配置、dev extras
├── README.md / CHANGELOG.md / SECURITY.md / CONTRIBUTING.md / REVIEW.md / SUGGESTIONS.md
└── dist/gen4399-2.0.0-py3-none-any.whl   # 旧构建产物（2.0 时代；2.4.0 请重新构建）
```

依赖关系（实际 import）：

```
cli.py / __main__.py
      │
 __init__.py（门面，re-export）
      │
registration.py ──→ forms.py ──→ identity.py ──→ core.py
      │                │             (Gen4399Error)
      │                └──→ core.py
      │
      ├──→ remote/ ──→ _api.py ──→ _http.py ──→ core.py
      │                (_http 无业务语义，_api 只做业务)
      │
      └──→ submit.py ──→ _aes.py ──→ core.py
                 └──→ registration.py / remote._http（RemoteSession）
```

分层要点：**core 是纯函数层**（无 IO、无网络、无全局状态）；identity/forms 是领域知识层；remote 拆成传输/业务两层；registration 只做编排；submit 是 2.1.0/2.2.0 的「提交用例层」（依赖 `_aes` / `_des` 与 `remote._http`，不反向依赖 CLI）；cli 只做参数翻译与输出；`__init__` 只做门面。依赖方向单向，无环。

---

## 4. 领域规则：4399 注册规则快照（`RULES_VERSION = "4399-2026-11"`，核对日 2026-11-07）

| 项 | 规则 | 实现位置 |
|---|---|---|
| 密码 | 长度 6~20；仅 ASCII 字母数字；**不能**纯数字/纯小写/纯大写；区分大小写 | `core.validate` (`core.py:216-253`) |
| 用户名 | 长度 6~20；仅 ASCII 字母数字；**允许纯数字**（4399 自动账号即 10 位纯数字） | `core.validate_username` (`core.py:261-300`) |
| 真实姓名 | 2~30 位中文（含 `·`/`•`），或英文姓名（空格分隔） | `identity.validate_realname` (`identity.py:44-60`) |
| 身份证 | 18 位；生日 1850~2050 且日历合法；GB 11643 加权校验码；**4399 拒绝 15 位** | `identity.validate_idcard` (`identity.py:76-100`) |
| QQ | 选填；4~11 位数字；空串视为合法 | `identity.validate_qq` (`identity.py:103-117`) |

规则来源：4399 前端 `validation.js` 的 `CheakPWD()` / `CheakUsername()` / `CheckRealname()` / `__checkIdcard()`（注意 4399 自己的拼写是 `Cheak`），以及两个注册页提示。**不是官方文档**——`docs/rules.md` 明确记录「可能随时过期」并给出复核流程。

两条注册路径（`forms.py`）：

| | `web`（网页用户名注册，推荐） | `unified`（ptlogin 统一注册面板） |
|---|---|---|
| 注册页 | `https://web.4399.com/user/reg.php` | `https://u.4399.com/register.html` |
| 提交地址 | `POST /user/?_c=reg` | `POST /ptlogin/register.do` |
| 本库能否提交 | ✅ 2.2.0 起 `submit_registration()`（需显式调用；CLI 默认 dry-run） | ✅ 2.1.0 起 `submit_registration()`（需显式调用） |
| 字段数 | 8 | 21（hidden 基线剔除 15 个后 + 本库写入 6 个，2.4.0 实测） |
| 必填 | 6：login_name / login_password / relogin_pwd / true_name / sfz / agree | 实际提交 6 个显式字段：username / password / passwordveri / appId / level / sec（本地仍要求合法姓名/身份证） |
| 特殊点 | 无 email（页面注释掉）；cid 固定 3000；密码用 `encode_4399()` DES 加密，姓名/身份证明文在 POST body | `sec=1` 时默认只加密 password/passwordveri；默认**不发** realname/idcard/email/reg_eula_agree；回传布局/实名类隐藏域会触发空白 `info_page`（2.4.0 已剔除） |

---

## 5. 模块逐个解剖

### 5.1 `core.py` —— 纯规则引擎
- 常量：`CHARSET` = 62（`a-zA-Z0-9`）；密码 6~20、默认 16；`USERNAME_CHARSET` = 36（小写+数字，为了易读）；用户名 6~20、默认 12。
- 异常族：`Gen4399Error` 基类 → `InvalidLengthError` / `InvalidFixedPartError`（→ `InvalidPrefixError` / `InvalidSuffixError`）/ `GenerationError`。`InvalidLengthError` 等同时继承 `ValueError`，便于调用方 `except ValueError`。
- 校验：`validate()` **不短路**，按 length → charset → all_digits → all_lower → all_upper 顺序收集全部违规（空串同时报 length+charset）；`Violation` 是 frozen dataclass，`code` 用 `Literal` 约束（length/charset/all_digits/all_lower/all_upper）。
- 生成：拒绝采样——`prefix + random_len × secrets.choice(charset) + suffix`，随机部分必须 ≥1 位；prefix/suffix 只允许 ASCII 字母数字且计入总长度；带 `max_attempts` 防死循环。用户名候选无需拒绝（候选必然合法），其重试循环实际是死代码。
- 批量：`generate_many(unique=True)` / `generate_usernames(unique=True)` 用 `max_tries = max(100, count*20)`；**不做可用空间预估**，空间不足时抛 `GenerationError` 并报告「只得到 N 个」。
- 熵：`entropy_bits(length, prefix_length, suffix_length, charset_size) = (length-prefix-suffix) * log2(charset_size)`；**不校验 6~20**（CLI 自行补校验），也不建模拒绝采样，对抗性固定部分会高估。
- 安全性：用 `secrets.choice`（CSPRNG），不是 `random`。

### 5.2 `identity.py` —— 身份信息与 txt 批量
- `RegistrationProfile`（frozen dataclass）：`realname / idcard / qq`；`errors()` / `is_valid()` / `require_valid()`（抛 `InvalidProfileError`）/ `masked_idcard()`（前 6 后 4）/ `masked()`（可安全写日志）。
- 身份证：GB 11643 加权因子 + `10X98765432` 映射；生日 1850~2050 且闰年正确；小写 `x` 先 `upper()` 接受并规范化。
- `parse_profile_line`：`姓名|身份证号[|QQ]`，支持全角 `｜`、行首 BOM、两侧空白；空行/`#` 注释行报错；列数必须 2~3；错误消息带行号。
- `load_profiles`：默认 `utf-8-sig`；`path="-"` 读 stdin（严格字符串比较）；自动识别首行表头（`姓名|身份证号` 等）；默认按身份证（upper）去重；`errors="skip"` 跳坏行；POSIX 下文件权限过宽（`& 0o077`）发 `chmod 600` 警告；全部无效行也抛 `InvalidProfileError`。
- 风险点：`_REALNAME_RE` 英文分支 `(?=[a-zA-Z]{2,}(\s[a-zA-Z]+){1,2}).{2,30}` 的 `.{2,30}` 过宽（`"John Smith 123"` 能过）；`.isdigit()` + `int()` 接受全角数字，全角数字身份证能通过校验码。

### 5.3 `forms.py` —— 表单知识库 + 本地整表校验
- `FormField`（name/label/required/kind/maxlength/note）、`RegistrationForm`（path/title/url/submit_url/fields）、`FormCheckResult`（ok/errors/warnings，`__bool__`、`messages()`）。
- `FORMS = MappingProxyType({...})` 只读；`get_form()` 未知道路抛 `ValueError`。
- `check_registration_form()`：纯本地不联网；用户名套 `validate_username`，密码套 `validate`，确认密码做字符串比较，姓名/身份证/QQ 套 identity 校验；支持 `profile=` 回填（只在显式参数为 `None` 时回填，显式 `""` 会覆盖）；unified 恒定加一条「服务端要求 6~20」警告。**不读 `FormField.required`**（如 agree 不会被检查）。
- `build_registration_fields()`：按表单字段顺序组装 `{参数名: 值}`，硬编码常量（cid=3000、agree=on、regMode=reg_normal、appId=u4399、level=4…）；**只组装不校验**，确认密码不一致也照填。

### 5.4 `registration.py` —— 编排层
`prepare_registration(profile, *, path="web", username=None, username_length=12, password_length=16, prefix="", suffix="", verify_username=True, app_id="u4399", timeout=10.0, retry_delay=0.0, retry_policy=None)`：

1. `get_form(path)`（未知路径先抛 ValueError）→ 校验 profile 类型 → 拒绝「显式 username + 前后缀」组合；
2. `profile.require_valid()`（不合规先抛，**不发网络**）；
3. 用户名：显式 + verify → `check_username`；自动 + verify → `generate_available_username`；自动 + 离线 → `generate_username`；
4. 密码：**永远本地生成**（4399 没有密码预校验接口）；
5. 整表校验（此时数据应必然合规，异常说明参数组合有问题）；
6. 组装字段 → 生成 warnings（未查重提示 + 「用 https 打开」提示）→ 返回 `RegistrationBundle`。

`RegistrationBundle`：frozen、可 hash（fields 用 `frozenset`）、`fields` 是 `MappingProxyType` 只读；`repr` 遮 password/idcard；`masked_fields()` / `to_dict(include_secrets=)` / `save(path, show_pii=False, mode=0o600)` / `as_text(show_pii=False)`。默认 `save` 打码 + 0600。

### 5.5 `remote/` —— 官方接口封装
- **传输层 `_http.py`**：标准库 `urllib.request`；固定 Chrome UA + Referer + Accept-Language；默认 10s 超时；响应最多读 512 KiB（静默截断）、`utf-8 errors="replace"`。
- **2.1.0 新增会话层**：`RemoteSession`（`urllib.request.build_opener` + `HTTPCookieProcessor(CookieJar)`）把 GET/POST 串在同一会话；`cookies` 属性返回 `name -> value` 快照。**GET 按 `RetryPolicy` 重试，POST 永远单次**（失败直接抛 `Remote*Error`，防重复注册）。
- **2.1.0 新增解析**：`HttpResponse(status/url/headers/body)`；`parse_registration_form(html) -> RegFormSnapshot`（`<form action>`、全部 hidden 域、`sec`、`j-username` 预填、`inputCaptcha` 探测；容忍属性顺序/单双引号/跨行/HTML 实体，解析不到 `<form>` 抛 `RemoteParseError`）。
- `RetryPolicy`（frozen）：`attempts/base_delay/max_delay/total_deadline/respect_retry_after`；指数退避 + ±25% 抖动 + 封顶（封顶在抖动前，实际最长 1.25×max_delay）+ 优先 `Retry-After`；`total_deadline` 只在两次尝试之间检查。
- 重试类别：超时、网络错误、5xx、429；**其它 4xx（含 408）不重试**。
- 错误族：`RemoteError`（带 `.url`）、`RemoteTimeoutError`、`RemoteHTTPError`（带 `.status/.retry_after`）、`RemoteParseError`。
- **业务层 `_api.py`**：
  - `fetch_suggested_username(...)`：GET `regFrame.do` → 解析 `<input id="j-username" value="...">`（先定位整标签再取 value，容忍属性顺序/单双引号/跨行）→ 可选 `check_username` 查重 → 外层最多 4 次、内层 HTTP 2 次、退避 5/10/20s（上限 60s）；`fallback_to_local` 可降级本地生成。
  - `check_username(username, validate_input=False)`：GET `isExist.do`，把响应分类为 `available`（body `"0"`）/ `taken`（含「已被注册」等）/ `invalid`（含敏感/长度等关键词）/ `unknown`（空 body 或 HTML → **抛 `RemoteParseError`**）；`validate_input=True` 时明显非法名直接本地拦截不发请求。
  - `generate_available_username()`：本地生成 + 服务端确认；`generate_account()`：账号+密码，显式 username 也会本地校验（不可用抛 `ValueError`/`RemoteError`）；`Account` 同理 frozen + repr 遮密码 + `to_dict/save`。
  - `fetch_suggested_usernames(count, unique=True, with_availability=...)`：凑满数量，凑不满抛 `RemoteError`；`with_availability=True` 返回 `UsernameAvailability` 列表（但**可能包含 taken 项**，见风险）。
- 远程默认参数较「礼貌」：`min_interval` CLI 可调，库自带重试带抖动与总预算。

### 5.6 `_aes.py` + `_des.py` + `submit.py` + `_captcha.py` —— 提交能力（2.1.0 / 2.2.0 / 2.3.0 / 2.4.0）
- **`_aes.py`**：与 4399 前端 CryptoJS 互操作的 AES 实现，**纯标准库**（`hashlib.md5` + 自实现 AES-256-CBC，无 pycryptodome 依赖）。
  - `PASSPHRASE = "lzYW5qaXVqa"`（4399 公开硬编码口令，不是秘密）；`SALT_LEN = 8`。
  - `encrypt_aes(plaintext, passphrase=PASSPHRASE)`：UTF-8 → 随机 8 字节 salt → `EVP_BytesToKey(MD5)` 派生 key/IV → AES-256-CBC + PKCS#7 → `Base64("Salted__" + salt + ct)`；输出以 `U2FsdGVkX1` 开头。
  - `decrypt_aes()` 仅用于互操作验证；非法 Base64 / 缺 `Salted__` / 长度或填充错误 → `CryptoError`。
  - **不提供机密性保护**：口令公开，只用于构造符合协议的表单字段。
- **`_des.py`（2.2.0）**：4399 web 注册页 `action.js` 的 `encode_4399()` 复刻，**纯标准库**（自实现 DES + 3DES-EDE + ECB + 零填充）。
  - `encode_4399(value, key)`：`encodeURIComponent(value)` → NUL 补齐到 8 字节倍数 → `key ≤8` 用 DES / `>8` 用 3DES-EDE → `"0x"+hex`。
  - 真实 JS 向量与 pycryptodome 交叉验证在 `tests/test_des.py`；`DesError(Gen4399Error)`。
  - 同样**不是机密性方案**；DES 已过时，只用于协议互操作。
- **`submit.py`**：提交用例层，支持两条路径。
  - `submit_registration(bundle, *, app_id="u4399", level=4, timeout=10.0, dry_run=False, retry_policy=None, on_response=None, captcha=None, captcha_attempts=3) -> SubmitResult`；`bundle.path` 为 `web` 或 `unified`（其它路径抛 `SubmitError`）。`app_id` / `level` 仅 unified 使用。
  - **unified（2.4.0）**：`RemoteSession` GET `regFrame.do`（拿 Cookie + hidden/action）→ `_build_payload()` 先按 `UNIFIED_DROP_FIELDS` 剔除 15 个隐藏域，再以剩余 hidden 为基线覆盖 `username`/`password`/`passwordveri`/`appId`/`level`/`sec`（共 21 个）→ `sec=="1"` 时默认只对 `password`/`passwordveri` 各自 `encrypt_aes()`（`UNIFIED_SEND_REALNAME=True` 时才加 `realname`/`idcard` 并加密，该组合未跑通）→ 同一会话 POST `form.action` → `_classify_response()` 判定。
  - **web**：GET `user/?_c=login&_a=checkUser` 取 `encryptCode`（JSONP）→ `_build_web_payload()` 用 `encode_4399()` 加密两个密码字段、填写 `cid=3000`/`true_name`/`sfz`/`encrypt=1` → POST `user/?_c=reg`（JSONP 响应）→ `_classify_web_response()` 按 `state/code/msg/validateState` 判定。
  - **web 图形验证码（2.3.0）**：`code=200` 且传了 `captcha` 回调时，循环「`GET /util/?_c=code&t=reg` 取 PNG → `captcha(image)` 识别 → `GET /_a=verifyCode&code=…` 校验 → 带 `chk_code` 重提交」，最多 `captcha_attempts` 轮；识别空串跳过 `verifyCode`。未传回调则直接返回 `kind="captcha"`。
  - `dry_run=True` 仍会 GET（unified 拉表单 / web 取 key），组装/加密后**不发注册 POST**，返回 `kind="dry_run"`。
  - `SubmitResult`（frozen，`repr`/`to_dict()` 脱敏）：`ok/kind/message/username/path/app_id/endpoint/http_status/final_url/encrypted_fields/login_cookies/field_names/dry_run/captcha_attempts/elapsed`；`__bool__` 等价 `ok`；web 的 `app_id` 为空串；`login_cookies` 只存 Cookie **名字**，`final_url` 去掉 query/fragment。
  - 判定：unified 见 `_classify_response()`；web 见 `_classify_web_response()`。**两条路径均已实测建号成功（2026-11-08）**：web 含图形验证码全流程；unified 剔除隐藏域后成功（成功页 `msnger.emit("isAutoRegSuccess",true)` + 登录 Cookie，实测账号 `abkeq7xvesft`）。服务端文案中的密码/身份证/姓名会被替换为 `***`（unified 成功页会回显明文密码，已脱敏）。
  - 注册 POST **不自动重试**；`retry_policy` 只作用于 GET。
  - `on_response` 回调（2.2.0）：注册 POST 后收到原始 `HttpResponse`，用于诊断
    （脚本 `--diagnose` 会脱敏保存响应），不改变判定/提交行为。
  - `UNIFIED_DROP_FIELDS`（2.4.0，`frozenset`）与 `UNIFIED_SEND_REALNAME`（默认 `False`）：
    模块级常量，必须从 `gen4399.submit` 导入/修改；漏剔除或打开实名开关都会回到空白
    `info_page`。
  - `_captcha.py`（2.3.0）：`prompt_captcha_solver()`（存图 + 人工输入）、
    `command_captcha_solver()`（PNG stdin / stdout，超时或非 0 退出抛
    `CaptchaSolverError`）、`save_captcha_images()`、`make_solver()`；纯标准库。
  - `HttpResponse.raw` / `is_binary`（2.3.0）：验证码是 `image/png`，`body` 的 UTF-8
    解码会破坏二进制，改用 `raw` 原始字节交给回调。

### 5.7 `cli.py` —— 双模式 CLI（2.0 子命令 + 1.x flag 兼容）
- **入口 `main()`**：仅当 `argv[0]` 是子命令名时走子命令 parser，否则走 legacy parser；最后统一按固定优先级 dispatch。
- **legacy flag 模式**：`-n/-c/-p/-s/-u/--check/--check-username/--fetch-username/--verify/--account/--no-verify/--offline/--check-available/--form-fields/--check-form/--form-path/--realname/--idcard/--qq/--profile-file/--profile-encoding/--build-form/--prepare/--submit/--yes/--app-id/--level/--show-pii/--entropy/--timeout/--retries/--retry-delay/--max-total-timeout/--min-interval/--output/--json/-v/-V/--rules-version`，全部在同一个 parser 里（**无互斥检查**，多命令同时给时按优先级静默取第一个；`--submit` 在 `--prepare` 之前 dispatch）。
- **子命令模式**：`generate / check / account / fetch / available / form fields|check|build / prepare / submit / profile check / rules / version`；共享 helper 加 `--timeout/--retries/--retry-delay/--max-total-timeout/--min-interval`、`--json/--output`、身份 opts。
- **`submit` 子命令**：`--form-path web|unified`（默认 unified）；默认 dry-run，`--yes` 才发 POST；`--app-id` / `--level`（仅 unified）、身份参数、`--json/--output`（写 `submit.json`）；2.3.0 起加 `--captcha-prompt` / `--captcha-cmd` / `--captcha-dir` / `--captcha-attempts`（仅 web 生效，命令失败退出码 2，成功多打印「验证码轮次」）；2.4.0 起 unified 已实测跑通（默认不发实名）。多身份时 stderr 警告「仅限本人真实身份、勿批量注册」。legacy `--submit` 默认走 web。
- **身份来源**：`--profile-file` / `--realname + --idcard`；两者都没给（且无 `--qq`）时
  默认读取当前目录 `sfz.txt`，不存在则退出码 2。`profile check` 的 `--profile-file` 可选，
  默认同上。编码默认 UTF-8-SIG，解码失败自动回退 GB18030（兼容 GBK）；
  `sfz.txt` / `accounts.json` 已加入 `.gitignore`。
- 退出码约定：**0 成功（含 dry-run）；1 校验失败/注册被拒/未知/验证码；2 参数/网络/配置错误**。
- 输出：文本（`OK:`/`FAIL:`/`DRY-RUN:`/`错误：`/`# 提示:`）与 `--json` 机器可读；`--output DIR` 写 0600 JSON（`bundle-XX.json` / `account-XX.json` / `generated.json` / `submit.json` 等）。

### 5.8 其余
- `__init__.py`：2.1.0/2.2.0 新增 `submit_registration` / `SubmitResult` / `SubmitError` 顶层导出；2.3.0 增 `CaptchaSolver` / `CaptchaSolverError` / `prompt_captcha_solver` / `command_captcha_solver` / `save_captcha_images` / `make_solver` 与 `WEB_REG_API` / `WEB_CAPTCHA_API` / `WEB_VERIFY_CODE_API`；2.4.0 的 `UNIFIED_DROP_FIELDS` / `UNIFIED_SEND_REALNAME` 只在 `gen4399.submit` 模块（未提升到顶层）；门面式 re-export；`py.typed` 随包；版本 2.4.0。
- `__main__.py`：`raise SystemExit(main())`。
- `_rules.py`：`RULES_VERSION` / `RULES_CHECKED_AT` / `RULES_SOURCES` / `RULE_KEYWORDS`（含 `CheakPWD` 原拼写）。
- `_width.py`：`display_width()`（EAW 的 W/F 记 2 列）+ `pad()`，用于 `as_text()` 与 `--form-fields` 的 CJK 表格对齐。
- `scripts/verify_rules.py`：GET 3 个规则页面（最多 2 MiB，UA，15s 超时），检查 4 个关键字符串是否还在；退出码 0/1/2。**只 GET，不提交**。

---

## 6. 关键数据流

### 6.1 `prepare_registration` 端到端（离线/在线两路）

```
RegistrationProfile(realname, idcard, qq)
        │  require_valid()
        ▼
 [username] ──显式──────────────────────────┐
        │                                   │
        ├─ verify=True → check_username() ───┤ 不可用 → RegistrationError
        │                                   │
        └─ 自动 ─ verify=True → generate_available_username()
                 └ verify=False → generate_username()
        ▼
 [password] = generate(length=16)           # 本地，无远程校验
        ▼
 check_registration_form(username, password, profile)   # 本地整表校验
        ▼
 build_registration_fields(...)             # 字段组装（不提交）
        ▼
 RegistrationBundle(path,url,username,password,profile,fields,warnings)
        │
        ├── as_text()           # 照着填的清单（默认打码）
        ├── to_dict()/save()    # JSON（默认打码 + 0600）
        ├── submit_registration(bundle, dry_run=False)   # 2.1.0–2.4.0：显式真实提交（web/unified）
        └── 或用户自己打开 bundle.url 在浏览器手动提交
```

### 6.2 `submit_registration` 提交流程（2.1.0 / 2.2.0 / 2.3.0 / 2.4.0）

```
submit_registration(bundle, dry_run=...)
        │  _validate_args: bundle.path ∈ {web, unified}
        ├── path == "unified" ──────────────────────────────────────────┐
        │                                                              │
        │  RemoteSession (CookieJar, GET 默认重试)                      │
        │   ├─ GET regFrame.do?appId=...&level=...&v=<ms>              │
        │   ├─ parse_registration_form(html)                            │
        │   │    └─ <form action> / hidden{...} / sec / j-username      │
        │   ├─ _build_payload(bundle, form)                             │
        │   │    └─ 剔除 UNIFIED_DROP_FIELDS（15 个）→ 21 字段         │
        │   ├─ sec=="1" ? encrypt_aes(password, passwordveri)           │
        │   │    （UNIFIED_SEND_REALNAME=True 时再加 realname/idcard，   │
        │   │      该组合未跑通）                                       │
        │   ├─ dry_run → SubmitResult(kind="dry_run")（不发 POST）      │
        │   └─ POST form.action（register.do，单次不重试）             │
        │        └─ _classify_response: isAutoRegSuccess → Msg →       │
        │           登录 Cookie → 验证码 → info_page → 跳转 → unknown   │
        │                                                              │
        └── path == "web" ──────────────────────────────────────────────┤
             RemoteSession (CookieJar)                                  │
              ├─ GET user/?_c=login&_a=checkUser&user=<登录名>          │
              │    └─ JSONP {state,data}，data = encryptCode            │
              ├─ _build_web_payload:                                    │
              │    encode_4399(password, code) → login_password/         │
              │    relogin_pwd；cid=3000/qq/true_name/sfz/encrypt=1    │
              ├─ dry_run → SubmitResult(kind="dry_run")（不发 POST）    │
              ├─ POST user/?_c=reg（body=字段，query=jsoncallback）     │
              │    └─ _classify_web_response: state → code 200/360 →  │
              │       msg → 登录 Cookie → unknown                     │
              └─ code=200 且给了 captcha 回调（2.3.0，最多 N 轮）：     │
                   取图 /util/?_c=code&t=reg → captcha(PNG bytes) →    │
                   verifyCode（state=true 才继续）→ 带 chk_code        │
                   重提交 user/?_c=reg → success                       │
```

> **web** `_c=reg` 与 **unified** `register.do` 的成功响应均已**实测建号成功**
> （2026-11-08）：web 含图形验证码流程；unified 剔除 15 个隐藏域后成功
> （成功页约 4 KB，`msnger.emit("isAutoRegSuccess",true)` + 登录 Cookie）。
> unified 默认不发实名信息（`UNIFIED_SEND_REALNAME=False`），打开后实测仍未跑通。
> `unknown` 不代表失败，以登录 `https://u.4399.com/` 为准。详见
> [docs/submit.md](submit.md)。

### 6.3 一次远程查询的内部链路

```
check_username(name)
  → _http_get(IS_EXIST_URL?username=...&appId=...&regMode=reg_normal)
      → _http_get_once: urllib.request.urlopen(req, timeout=10)
          → HTTPError/URLError/socket.timeout 映射为 Remote*Error
      → 失败按 RetryPolicy 重试（指数退避+抖动，优先 Retry-After，可带总预算）
  → _classify_availability(body): "0"→available / 关键词→invalid / 空或HTML→unknown
      unknown → 抛 RemoteParseError（1.9.0 起不再静默当 taken）
  → UsernameAvailability(username, available, kind, message)
```

---

## 7. 工程质量实测（2026-11-07，Python 3.14.8 / Termux aarch64）

| 门禁 | 命令 | 实测结果 | 判定 |
|---|---|---|---|
| 全量测试 | `pytest -q` | **519 passed, 1 skipped, 457 subtests passed, ~1.9s** | ✅ |
| 覆盖率 | `coverage run --branch -m pytest` + `report` | **TOTAL 94%**（2240 stmts / 91 miss / 844 branch / 73 brpart），阈值 90 满足 | ✅ |
| doctest | `pytest --doctest-modules gen4399 -q` | **11 passed, 5 skipped**（skip 均为源码 `# doctest: +SKIP` 的网络/IO 示例） | ✅ |
| ruff | `ruff check .` | 本机未安装（离线不可装） | ⏭️ NOT-RUN |
| mypy | `mypy gen4399` | 未安装；CI 中本身是 `continue-on-error` 观察项 | ⏭️ NOT-RUN |
| 打包 | `python -m build` / `twine check` | build/twine 未安装；2.0 时代曾回退 `pip wheel`/`build_sdist` 成功；2.2.0 已用 `pip wheel --no-build-isolation` 验证可构建 | ⏭️ 待重构建 |
| 安装 | `pip show gen4399` | editable 安装，console script 正常；pip 元数据仍显示旧版本（模块 `__version__` 已是 2.2.0，需重装/重构建后一致） | ⚠️ |

覆盖率结构（薄弱面）：`cli.py` 90%、`remote/_http.py` 93%、`__main__.py` 0%；`submit.py` 96%、`forms.py` / `registration.py` 97%、`_des.py` 98%、`_aes.py` 100%；`core.py` / `remote/_api.py` 95%、`identity.py` 94%。总阈值只卡 TOTAL，故仍通过。

测试风格：纯 `unittest.TestCase` + `unittest.mock.patch`（约 70 处，remote 43/最重）+ `tempfile`；457 个 subtests 来自 `subTest` 参数化；无 pytest fixture/monkeypatch/临时目录/subprocess；hypothesis 属性测试模块因未装依赖整体 skip（非缺陷）。**测试不联网**（全部桩掉 HTTP；`test_submit_http` / `test_submit` / `test_des` 也全部离线）。

工程配置：`pyproject.toml` 版本单一来源（`attr = "gen4399.__version__"`）、pytest/coverage/ruff/mypy 配置、dev extras；CI 矩阵 **3.10–3.13**，7 道门禁（ruff 硬门禁 → mypy 观察 → pytest → coverage 90 → doctest → build+twine）；`.pre-commit-config.yaml` 带 ruff + whitespace/EOF/yaml/toml 检查；MIT License；`py.typed` 随包。

文档链完整：README（安装/API/CLI/安全/FAQ）、`docs/rules.md`（规则快照 + 复核流程 + 提交协议摘要）、`docs/submit.md`（2.1.0/2.2.0 web+unified 提交协议/字段/AES+DES/判定/未验证项）、CHANGELOG（1.8.1 → 2.2.0 逐版本）、SECURITY.md（PII 边界 + 提交同意要求）、CONTRIBUTING.md、REVIEW.md 与 SUGGESTIONS.md（前两轮自审记录，均已标注闭环）。

---

## 8. 安全与 PII 治理（设计 vs 实际）

设计意图（README/SECURITY/CONTRIBUTING 都写了）：**默认打码、不写日志、落盘 0600、默认不提交注册**。

实际做到：
- `Account` / `RegistrationBundle` / `SubmitResult` 的 `repr` 遮蔽敏感信息；
- `prepare` / `form build` 默认遮身份证、密码、QQ；`--show-pii` 才显明文（会打印警告）；
- `--output` 文件 0600；身份文件权限过宽会 warning；错误/日志里的 URL 用 `_safe_url` 去 query；
- 远程库自带重试/限速，`check_username(validate_input=True)` 明显非法名不联网；
- 提交能力不会自动触发（CLI 默认 dry-run）；注册 POST 单次不重试；`SubmitResult` 只含 Cookie **名字**与字段 **名字**，
  `final_url` 去掉 query/fragment，`to_dict()` 可直接安全落盘；
- dry-run 只 GET 表单页（查询参数不含 PII），**不发送姓名/身份证等 PII**；
  真实提交时 PII 只发往 `ptlogin.4399.com`（4399 官方端点），`sec=1` 时先经前端同款 AES 加密
  ——但该口令公开，**不构成机密性保护**。

实测缺口（详见第 10 节风险表）：
- `--account` **默认就地打印明文密码**（无 `--show-pii` 概念、无警告），`--json/--output` 同样明文；
- `realname`（中文姓名）在 `prepare`/`form build`/`profile check --json` 输出中**始终明文**，`--show-pii` 管不到；
- `RegistrationBundle.to_dict(include_secrets=False)` 的**顶层 `qq` 字段仍明文**（fields 里已打码，顶层漏了）；
- `RemoteError.url` 保留 `isExist.do?username=...`，打印异常对象可能带出用户名；
- `parse_profile_line` 的格式错误消息里带原始整行（可能含身份证号）；
- 所有 `save()`/`--output` 都是「先按 umask 建文件 → 再 chmod 0600」，有短暂权限窗口，且非原子写。

---

## 9. 演进史与自审闭环

| 版本 | 内容 |
|---|---|
| 1.8.1 | 初始基线：生成/校验、远程、表单、prepare、CLI |
| 1.9.0 | 修 REVIEW.md 的 P0：响应结构化（kind）、HTML 解析健壮性、批量凑满、CLI 异常兜底、QQ strip、Bundle 只读、repr 打码；加 unique 批量、License/CI/CHANGELOG/类型 |
| 1.10.0 | 身份文件 `load_profiles/parse_profile_line` + CLI `--profile-file` 批量 |
| 2.0.0 | 子命令 CLI + 全局增强（--json/--offline/--output/重试参数）、`RetryPolicy`、类型收紧、模块拆分（remote 拆包、identity 拆出）、规则版本 + verify_rules、property 测试、CI 门禁、SECURITY/CONTRIBUTING/pre-commit、`requires-python>=3.10` |
| 2.1.0 | **真实提交（unified）**：`submit_registration()` / `SubmitResult` / `SubmitError` + `gen4399 submit` 子命令 + legacy `--submit/--yes`；`gen4399/_aes.py`（CryptoJS 兼容 AES-256-CBC，纯标准库）；`RemoteSession`（CookieJar，GET 重试/POST 单次）+ `parse_registration_form()`；`docs/submit.md`；库不自动提交（API 调用即提交、CLI 默认 dry-run）、成功判定为推断、POST 不自动重试 |
| 2.2.0 | **web 路径提交**：`_des.py`（4399 页面同款 DES/3DES `encode_4399()`，纯标准库）；`submit.py` 增加 web 流程（checkUser 取 key → DES 加密码 → POST `user/?_c=reg` → JSONP 判定）；CLI `submit --form-path web\|unified`、legacy `--submit` 默认 web；CLI 未指定身份来源时默认读 `./sfz.txt`；文档/测试同步；成功判定仍为推断、POST 不重试；web 的姓名/身份证明文在 HTTPS body |
| 2.3.0 | **web 图形验证码 + 实测建号**：`code=200` → 取图 → 调用方 `captcha` 回调识别 → `verifyCode` → 带 `chk_code` 重提交（最多 `captcha_attempts` 轮）；`SubmitResult.captcha_attempts`；`HttpResponse.raw` / `is_binary`；`_captcha.py`（人工/外部命令/落盘）+ `CaptchaSolverError`；CLI/脚本验证码参数；**web 实测建号成功（2026-11-08）** |
| 2.4.0 | **unified 修复 + 实测建号**：定位空白「4399提示」页根因（回传 15 个隐藏域，非风控封 IP），新增 `UNIFIED_DROP_FIELDS` 并剔除，实际提交 21 字段；新增 `UNIFIED_SEND_REALNAME`（默认 False，unified 默认不发实名，`encrypted_fields` 只有 2 个；打开后实测未跑通）；**unified 实测建号成功（2026-11-08，账号 `abkeq7xvesft`）** |

`REVIEW.md`（1.8.1 审查）与 `SUGGESTIONS.md`（1.10.0 评估）是两轮「审查 → 修复 → 验证」的记录，文件头均标注了闭环状态；本次深读也核对了其中大部分 P0/P1 确实已在代码中修复（如 `unknown` 抛解析错、`validate_fixed_part` 公开、Bundle MappingProxyType、`unique` 凑满、CLI 子命令等）。项目在单日内完成 16 次提交、从 1.8.1 演进到 2.0.0，属于典型的「先做对、再补工程质量」路径；2.1.0 补上 unified 真实提交层，2.2.0 又补齐 web 路径提交。

---

## 10. 已知问题与风险（按影响排序，均来自源码/实测）

### 🔴 高（行为与文档承诺不一致，涉及安全/隐私）

| # | 问题 | 证据/位置 | 影响与建议 |
|---|---|---|---|
| 1 | **子命令模式 `-v/--verbose` 完全失效** | `main` 只按 `argv[0]` 判模式（`cli.py:957`）；子 parser 不认 `-v`，且 `set_defaults(**legacy_defaults)` 会把 verbose 覆盖为 False（`cli.py:734-738,792-795`）。实测 `-v generate`、`generate -v` 均 exit 2 | 2.0 主打模式的排障日志不可用；README「全局 flag」表述不成立。建议父 parser 支持 `-v` 并子 parser 不覆盖 |
| 2 | **`--offline` 不阻止 `-u --verify`** | `_cmd_generate` 不检查 `_offline`（`cli.py:666-675`）；`generate` 子命令也没有 `--offline` | 用户以为离线却真的发出 `isExist.do` 请求（实测一次）。建议 generate 路径统一走 `_offline()` 判断并补旗标 |
| 3 | **`--account` 默认明文密码 + `--json/--output` 明文** | `cli.py:563-570`、`Account.to_dict/save`（`_api.py:529-544`） | 与 README「默认打码」矛盾；终端/日志/文件直接泄露密码。建议默认打码 + `--show-pii` 显式开启 |
| 4 | **realname 打码缺失 + `to_dict(False)` 顶层 qq 泄露** | `masked_fields()` 不遮 `true_name/realname`；`to_dict(include_secrets=False)` 的 `"qq": self.qq` 恒明文（`registration.py:130-150`）；`form build`/`profile check --json` 同样 | PII 治理口径不一致（身份证/密码打码、姓名/QQ 漏掉）。建议统一打码函数并补测试 |

### 🟠 中（易用性 / 正确性 / 一致性）

| # | 问题 | 证据/位置 |
|---|---|---|
| 5 | `--account -c 0/-1` 静默 exit 0、空输出 | 不校验 count（`cli.py:543-558`），对比 generate 走 core 校验 |
| 6 | `--min-interval` 最后一项后仍 sleep；`fetch` 完全不用它 | `_sleep_between` 在循环体内（`cli.py:445,558,675`）；实测 `-c 3 --min-interval 1` → 3 次 sleep |
| 7 | `--output` 被 `check`/`check-form`/`form-fields` 忽略；legacy 多命令同时给时静默取第一个 | 实测；dispatch 优先级 `cli.py:975-991` |
| 8 | `generate --verify` 忽略 `--timeout/--retry-delay`（子命令定义但 no-op）；`fetch` 的 `--retries` 同时作用于外层取号与内层 HTTP；`--max-total-timeout` 双重语义 | `cli.py:669-674`、`:624-627` |
| 9 | `check_username` 把「非 0、非空、非 HTML、无 invalid 关键词」的响应一律判 `taken`（如 `"1"`、JSON 错误体） | `_api.py:88-101`；`unknown` 实际只覆盖空/HTML，接口异常可能误报「已被注册」 |
| 10 | `fetch_suggested_usernames(with_availability=True)` 可返回 `available=False/taken` 的项（不重试），且 `verify_available` 被静默忽略 | `_api.py:320,330-339` |
| 11 | `verify_rules.py` 网络错误立即 return 2（跳过后续 URL）；非法 URL 的 ValueError 未捕获 → 退出码可能 1；干净 checkout 未安装包时 `sys.path[0]=scripts` 可能 ImportError | `scripts/verify_rules.py:32-48` |
| 12 | 覆盖率薄弱点 `cli 90% / _http 92% / __main__ 0%`，若未来加 per-file 阈值会先卡住 | quality-runner 实测 |
| 13 | 文档漂移：README 写 `pytest --cov=gen4399`，CI 实际用 `coverage run/report`；README「全局 flag」与子命令实际能力不对称；本机 Python 3.14 不在 CI 矩阵/classifier 中 | README、ci.yml、pyproject |

### 🟠 提交能力（2.1.0 / 2.2.0）的新增风险/限制

| # | 问题 | 证据/位置 | 影响与建议 |
|---|---|---|---|
| 14 | **成功判定仍是启发式（两条路径都已实测建号）** | `submit._classify_response()` / `_classify_web_response()`；2026-11-08 两条路径均实测成功 | `success` 仍靠成功标记/Cookie/JSONP 判定，可能误判/漏判；以登录 `u.4399.com` 为准。unified 的空壳 `info_page` 已定位为隐藏域回传问题（2.4.0 修复），`UNIFIED_SEND_REALNAME=True` 仍会触发 |
| 15 | **web 路径 PII 处理弱于 unified** | `_build_web_payload()`；`_des.encode_4399()`；`UNIFIED_SEND_REALNAME=False` | 密码只有 DES（公开算法，无现代机密性），`true_name`/`sfz` 明文在 HTTPS POST body；unified 默认只 AES 加密密码、**不发实名**。更在意 PII 时优先用 unified。浏览器原流程是 JSONP GET（PII 在 query），本库改用 POST body 降低 URL 日志泄露 |
| 16 | **POST 不自动重试，超时后结果不确定** | `RemoteSession.post()` 单次；`submit.py` 注释 | 超时/5xx 时服务端可能已建号；重跑 `--yes` 有重复注册风险。建议先登录确认，必要时人工处理 |
| 17 | **dry-run 仍会联网 GET** | unified `GET regFrame.do`；web `GET checkUser`（只带用户名） | 完全离线环境不可 dry-run；不过 GET 不含姓名/身份证，且不会发注册 POST |
| 18 | **依赖服务端表单/接口结构** | unified：hidden 域/`sec`/action；web：checkUser `data`/JSONP `state/code` | 4399 前端改版即可能失效；已提供 `docs/submit.md` 的 dry-run 复核清单，但无自动结构断言 |

### 🟡 低（健壮性 / 边界 / 可维护性）

- `identity._REALNAME_RE` 英文分支过宽（`"John Smith 123"` 通过）；`\d`+`int()` 接受全角数字，全角数字身份证可过校验码。
- `entropy_bits` 不建模拒绝采样（对抗性固定部分高估，如实测 5.95 vs 实际 5.17 bit）；不校验 6~20 属有意设计。
- 用户名生成的重试循环是死代码（候选必然合法）；`generate_many(unique=True)` 无可用空间预估（`length=6, prefix="abcde"` 空间仅 36，`count=40` 即 `GenerationError`）。
- `_width.pad` 未知 `align` 静默 left；多字符 `fill` 会超宽；Ambiguous 宽度按 1 计。
- HTTP：408 不重试；`Retry-After` 分支无抖动；封顶在抖动前（实际 1.25×）；`total_deadline` 粒度粗；512 KiB 静默截断；无 Content-Type 校验；重定向默认跟随。
- `save()` 非原子写 + chmod 失败静默；`_http_get` 用 `assert`；`fallback_to_local` 在总预算耗尽时不生效、且不传 `retry_policy`。
- CLI 异常捕获不一致（`_cmd_check_available` 只 catch RemoteError；未知异常会 traceback）；`-n` 的 `or` 会把显式 0 吞成默认值；打码逻辑三处重复且细节不一致。
- 构建不可复现（zip 时间戳，正常）；sdist 不含 docs/、scripts/、.github/；无 MANIFEST。
- 规则本身可能过期（依赖 4399 前端改版），`verify_rules.py` 只是关键词冒烟，非结构校验。

---

## 11. 上手路径与常用命令

```bash
pip install -e ".[dev]"          # 安装（运行时零依赖）
python -m pytest                 # 519 项测试
python -m pytest --doctest-modules gen4399 -q
python -m coverage run --branch -m pytest -q && python -m coverage report
```

```python
from gen4399 import *
generate()                                # 16 位合规密码
generate_many(5, unique=True)             # 5 个互不相同
validate("123456")                        # [Violation(code='all_digits', ...)]
generate_username(length=12)              # 小写+数字
check_username("abc12345")                # UsernameAvailability(available/kind/...)
prepare_registration(profile)             # 一键准备（默认会在线查重）
prepare_registration(profile, path="unified")            # unified（AES 加密更完整）
prepare_registration(profile, path="web")                # web（DES 加密码）
submit_registration(bundle, dry_run=True)                # 2.1.0+：dry-run（不发注册 POST）
submit_registration(bundle, dry_run=False)               # 2.1.0+：真实提交（仅本人身份）
```

```bash
python -m gen4399 generate -n 20 -c 5
python -m gen4399 check password "Abc12345"      # 退出码 0/1
python -m gen4399 account --offline -c 3
python -m gen4399 prepare --profile-file ids.txt --json --output out/
python -m gen4399 form build abc12345 Abc123456 --realname 张三 --idcard ...
python -m gen4399 submit --realname 张三 --idcard ...                    # unified dry-run
python -m gen4399 submit --form-path web --realname 张三 --idcard ...    # web dry-run
python -m gen4399 submit --realname 张三 --idcard ... --yes              # unified 真实提交
python -m gen4399 rules                          # 规则版本与来源
```

---

## 12. 总体评价

**优点**：
- 领域边界清晰、目标克制（默认只准备、提交必须显式开启），规则来源与维护流程有记录；
- 分层干净、单向依赖、`__init__` 门面 + 72 个导出、`py.typed`，API 文档与 doctest 齐全；
- 工程配套成熟：零运行时依赖（新增提交层仍只用标准库）、519 测试、94% 覆盖、CI 7 道门禁、MIT、语义化版本、CHANGELOG、SECURITY/CONTRIBUTING、pre-commit；
- 远程层做了真实工程化：重试策略对象、抖动、Retry-After、总预算、结构化错误、HTML 解析健壮性、结构化可用性结果，以及 CookieJar 会话 + 单次 POST；
- 提交层在安全上保守：默认不自动提交（CLI 默认 dry-run）、注册 POST 不自动重试、结果对象脱敏、只发往 4399 官方端点，并如实写明「web 已实测建号成功、unified 受限」「图形验证码需调用方回调」「web PII 弱于 unified」；
- PII 安全意识整体在线（repr 打码、0600、权限警告、日志去 query）。

**主要短板**：
- CLI 2.0 双模式是最大维护瓶颈（1,192 行、两套 parser、`set_defaults` hack），出现 `-v` 失效、`--offline` 漏判、能力不对称、多命令静默优先级等一批一致性问题；
- PII 打码口径不统一（密码默认明文、姓名/QQ 漏遮、`to_dict` 顶层 qq 漏遮），与自身文档冲突；
- 远程分类启发式仍偏「宽容」（未知响应→taken 的兜底、with_availability 可返回 taken）；
- 提交能力边界：web 与 unified 均已实测建号成功（web 含图形验证码；unified 剔除隐藏域后跑通），但都依赖 4399 表单/接口结构；unified 默认不发实名，web 的姓名/身份证明文在 POST body；`UNIFIED_SEND_REALNAME=True` 仍未跑通；
- 覆盖率过线靠 TOTAL，CLI/HTTP 细节分支是薄弱面；
- 规则与提交协议都依赖 4399 前端，存在天然过期风险（已提供复核脚本/ dry-run 复核清单但只能冒烟）。

**一句话**：这是一个「小而完整、工程质量高于同类脚本」的领域工具库——核心规则/表单/远程/编排设计扎实，2.0 补齐工程化，2.1.0–2.4.0 补上 unified / web 两条真实提交路径（2.4.0 两条均实测建号成功），并把边界（库不自动提交 / CLI 默认 dry-run、成功判定仍为启发式、POST 不重试、unified 默认不发实名、web 路径 PII 处理更弱）写得很清楚；当前最值得做的仍是**收敛 CLI 双模式与统一 PII 打码**，并持续用 dry-run 复核提交协议（上面 🔴/🟠 清单）。

---

*本文基于 2026-11-07 工作区快照，2026-11-08 补 2.3.0 / 2.4.0 增量；规则版本 `4399-2026-11`。若源码更新，行号与个别结论可能需要复核。*
