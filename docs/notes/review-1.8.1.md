> **状态（1.9.0）**：本报告中的 P0 全部修复，P1 已修 1/2/4/5/6/7/8/9/10/11/12/13/14，
> 工程化缺口（License / CI / lint / 测试 / 版本单一来源）已补齐。
> 具体改动见 [CHANGELOG.md](CHANGELOG.md)；本文件保留为 1.8.1 的审查记录。

# gen4399 1.8.1 代码审查：可完善之处

> 审查对象：`lead-workspace/`（从 `gen4399-1.8.1.zip` 解压）
> 审查方式：通读全部 8 个源文件 + 4 个测试文件；运行测试、覆盖率、打包、CLI、真实接口探测。
> 所有结论都经过实际复现，不是"看起来可能"。

---

## 一、总体结论

**底子不错**：模块分层清晰（core / forms / registration / remote / cli）、类型注解齐全、
异常层次合理、零依赖、PII 默认打码、`py.typed` 已打包、wheel 构建和 `pip install -e .` 均正常。

| 指标 | 结果 |
|---|---|
| 测试 | 150 passed + 74 subtests，0.3s |
| 分支覆盖率 | 95%（core 94% / forms 93% / registration 96% / **remote 83%**） |
| 打包 | wheel 13 项，含 `py.typed`、console script 正常 |
| 语法 | 用 `ast.parse(feature_version=(3,8))` 验证，3.8 语法兼容 |
| 真实接口 | `isExist.do` 可用（`0`=可注册），`regFrame.do` 能取到分配账号 |

**主要短板集中在 4 处**：
1. 远程接口层对"异常响应"太宽容（把错误当业务结果）；
2. CLI 对 `--fetch-username` 的错误处理缺口，会直接抛 traceback；
3. `unified` 路径允许 `_@` 的规则是**不可达死代码**，与文档/警告自相矛盾；
4. 工程化配套缺失（License / CI / lint / CLI 测试 / 版本单一来源）。

---

## 二、P0 明确缺陷（建议先修）

### P0-1 `check_username()` 把"服务端错误页"当成"用户名已被注册"

- 位置：[remote.py:363-373](gen4399/remote.py#L363-L373)
- 代码：`available=(body == "0")` —— 只要响应不是 `"0"` 就判为不可用。
- 影响：接口返回空 body、502 HTML 页、风控页时，都会得到 `available=False`。
  更糟的是 [generate_available_username()](gen4399/remote.py#L426-L439) 会把它当"撞名"继续重试，
  最后抛出误导性的 `RemoteError("连续 N 个用户名都不可用")`。
- 复现：

  ```python
  with mock.patch("gen4399.remote._http_get", return_value="<html>502 Bad Gateway</html>"):
      check_username("abc12345").available   # 实际 False，应为"未知/报错"
  ```

- 建议：把响应解析成结构化结果，区分 `available / taken / invalid / unknown`；
  `unknown`（空串、HTML）抛 `RemoteParseError`，不要静默当成 taken。
  例如给 `UsernameAvailability` 增加 `kind: Literal["available","taken","invalid","unknown"]`。

### P0-2 HTML 解析对属性顺序/引号太脆弱，失败时静默返回空串

- 位置：[remote.py:84-85](gen4399/remote.py#L84-L85)、[remote.py:157-165](gen4399/remote.py#L157-L165)
- 复现（已实测）：

  | 输入 | 当前结果 |
  |---|---|
  | `<input value="4257237567" id="j-username">`（value 在 id 前） | `''` → 被当成"频率限制" |
  | `<input id='j-username' value='...'>`（单引号） | `RemoteParseError` |
  | 属性跨行 | 正常 |

- 影响：`value` 写在 `id` 前后的页面改版会让所有调用"假空"，用户只会看到"频率限制"提示。
- 建议：先匹配整个 `<input ... id="j-username" ...>` 标签（容忍单/双引号、属性顺序），
  再在标签体内找 `value`；找不到 `value` 属性本身才抛 `RemoteParseError`。
  更稳的做法是用 `html.parser.HTMLParser`（标准库，仍零依赖）。

### P0-3 `fetch_suggested_usernames(unique=True)` 会少返回，且不报错

- 位置：[remote.py:320-336](gen4399/remote.py#L320-L336)
- 复现：服务端反复给同一个名字时，要 3 个只返回 1 个（现有测试 `test_unique_filters_duplicates` 甚至把这个行为固化了下来）。
- 影响：调用方假设 `len(结果) == count`，批量注册场景会悄悄少号。
- 建议：`unique=True` 时循环到凑满 `count`（带最大尝试次数上限，防死循环），
  凑不满时抛 `RemoteError` 或显式返回并标注；同时把现有测试改为断言新语义。

### P0-4 `generate_account()` 显式传 username 且离线时不校验

- 位置：[remote.py:501-509](gen4399/remote.py#L501-L509)
- 复现：

  ```python
  a = generate_account(username="ab", verify_username=False)
  # Account(username='ab', ...) —— "ab" 只有 2 位，违反 6~20 规则
  generate_account(username="", verify_username=False)  # 返回用户名 ''
  ```

- 影响：违背库自己的核心承诺"生成的账号一定合规"。`prepare_registration` 因为后面有整表校验所以没事，
  但 `generate_account` 这条路径漏了。
- 建议：进入函数时先 `validate_username(...)`，非法立即抛 `ValueError`（或 `Gen4399Error`），
  与"显式传入就要自己负责"的隐含假设说清楚。

### P0-5 CLI `--fetch-username` 的错误处理会直接崩出 traceback

- 位置：[cli.py:297-311](gen4399/cli.py#L297-L311)（只 `except RemoteError`）
- 实测会抛栈的输入：
  - `python -m gen4399 --fetch-username 0` → `ValueError: count 必须 >= 1`
  - `python -m gen4399 --fetch-username -p a_b` → `InvalidPrefixError`
  - `python -m gen4399 --fetch-username -p aaaaaaaaaaaaaaaaaaaaaaaa` → `InvalidLengthError`
- 影响：CLI 承诺"2 = 参数错误"，实际是 Python traceback + 退出码 1。
- 建议：与其它分支一致，`except (Gen4399Error, TypeError, ValueError)` 打 `错误：...` 返回 2。

### P0-6 `unified` 路径的 `_@` / 特殊字符规则是不可达死代码

- 位置：[forms.py:184-186](gen4399/forms.py#L184-L186)、[forms.py:267-281](gen4399/forms.py#L267-L281)
- 逻辑：先跑 `validate_username()`（只允许字母数字），**只有它全通过**才会去匹配
  `_UNIFIED_USERNAME_RE`（允许 `_@`）。字母数字永远满足 `_@` 正则 ⇒ 那两行永远不生效。
  密码的 `_UNIFIED_PASSWORD_RE` 同理。
- 实测：`check_registration_form("abc_1234", ..., path="unified")` 返回 charset 错误；
  `"Abc!12345"` 也返回"只允许使用字母和数字"。
- 建议二选一：
  - **删掉**这两个正则和对应分支（推荐：文档里也说了服务端要 6~20 字母数字）；
  - 或真正实现"unified 页面允许 `_@`"——但需要先联网确认服务端是否真的接受，风险更高。
  无论哪种，现在这种"写了但永不执行 + 注释说允许"的状态最差。

### P0-7 `validate_qq()` 不 strip，尾部换行能混过校验

- 位置：[forms.py:251-264](gen4399/forms.py#L251-L264)
- 实测：`validate_qq("123456789\n") == []`（通过），`" 123456789"` 反而失败。
  原因：`re.match` 的 `$` 允许匹配末尾 `\n` 之前。
- 影响：QQ 字段里带换行的值能通过校验，最终被拼进提交字段。
- 建议：`qq = qq.strip()`（与 realname / idcard 的处理保持一致），并用 `fullmatch`。

### P0-8 `RegistrationBundle` 声明 frozen，但 `fields` 字典仍可变且对象不可哈希

- 位置：[registration.py:49-75](gen4399/registration.py#L49-L75)（`fields: dict`）
- 实测：`b.fields["login_name"] = "hacked"` 成功；`hash(b)` 抛 `TypeError: unhashable type: 'dict'`。
- 影响：`frozen=True` 给出错误的安全预期；未来有人拿它做 dict key 会炸。
- 建议：`fields` 改为不可变映射（构造时 `types.MappingProxyType(dict(fields))`），
  或去掉 `frozen=True`；`masked_fields()` 返回普通 dict 即可。

### P0-9 CLI `--account` 的 `-n` 同时改用户名和密码长度，`--username-length` 被忽略

- 位置：[cli.py:263-272](gen4399/cli.py#L263-L272)
- 实测：`python -m gen4399 --account --no-verify -n 8` → 用户名 8 位、密码 8 位。
  而 `--prepare` 用的是 `-n`=密码长度、`--username-length`=用户名长度，两套语义不一致。
- 建议：让 `--account` 与 `--prepare` 统一（`--username-length` 生效、`-n` 只管密码），
  并在 README 写清楚。

---

## 三、P1 一致性与设计问题

| # | 问题 | 位置 | 建议 |
|---|---|---|---|
| 1 | `entropy_bits()` 不校验 6~20，CLI `--entropy -n 100` 能输出 595.4 bit，而 `generate -n 100` 报错 | [core.py:251-287](gen4399/core.py#L251-L287)、[cli.py:319-326](gen4399/cli.py#L319-L326) | 要么加范围校验，要么在文档里明确"这是通用熵计算，不限制 4399 规则" |
| 2 | `--verify` 的默认重试策略太慢：`retries=4, retry_delay=5` ⇒ 最坏 sleep 5+10+20=35s，再叠加 4 次请求超时；无 jitter、无总 deadline | [remote.py:186-196](gen4399/remote.py#L186-L196)、[remote.py:241-266](gen4399/remote.py#L241-L266) | 加 `max_total_timeout`、`retry_delay` 指数退避加 jitter；CLI 暴露 `--timeout` |
| 3 | `_http_get()` 对瞬时网络错误不重试（只对"解析出空用户名"重试） | [remote.py:126-154](gen4399/remote.py#L126-L154) | 区分可重试错误（超时/5xx）与不可重试错误，给 `_http_get` 或 fetch 层加 retry |
| 4 | 跨模块引用私有符号 `_check_fixed_part` | [remote.py:39](gen4399/remote.py#L39) | 在 core 里导出公开名（如 `validate_fixed_part`），或把校验挪进 remote |
| 5 | `DEFAULT_USER_AGENT` 在 `remote.__all__` 里，但顶层 `gen4399` 没导出 | [remote.py:51](gen4399/remote.py#L51)、[__init__.py:108](gen4399/__init__.py#L108) | 补进顶层 `__all__`/import |
| 6 | 版本号双写：`pyproject.toml:7` 与 `__init__.py:106` 各写一份 | [pyproject.toml:7](pyproject.toml#L7)、[__init__.py:106](gen4399/__init__.py#L106) | 单一来源：`importlib.metadata.version("gen4399")` + fallback |
| 7 | 未使用导入：forms 的 `MAX_LENGTH/MIN_LENGTH/USERNAME_CHARSET`；remote 的 `validate`；test_core 的 `CHARSET/GenerationError`；test_remote 第 13、14 行重复导入 `UsernameAvailability` | [forms.py:22-29](gen4399/forms.py#L22-L29)、[remote.py:34-44](gen4399/remote.py#L34-L44)、[test_core.py:7-15](tests/test_core.py#L7-L15)、[test_remote.py:13-14](tests/test_remote.py#L13-L14) | 清理；接 ruff 后自动发现 |
| 8 | 打码策略不一致：`as_text()` 默认打码身份证/密码，却明文显示 QQ | [registration.py:81-118](gen4399/registration.py#L81-L118) | QQ 也算半敏感信息，建议默认打码或加参数说明 |
| 9 | `Account` / `RegistrationBundle` 的 `repr` 会显示明文密码，容易被日志/报错带出去 | [remote.py:442-454](gen4399/remote.py#L442-L454) | 自定义 `__repr__` 输出 `password='***'`，或提供 `.masked()` |
| 10 | `generate_many()` 不保证去重（docstring 已诚实写"概率上"），但调用方容易误解 | [core.py:370-411](gen4399/core.py#L370-L411) | 增加 `unique: bool = False` 参数；或文档加粗提醒 |
| 11 | 服务端对非法用户名返回的是"用户名至少要3个字符"这类提示，而 `check_username` 直接压成 `available=False` | [remote.py:368-373](gen4399/remote.py#L368-L373) | 同 P0-1，结构化 `kind` |
| 12 | `generate()` 的 `GenerationError` 可触发（固定部分+1 位随机 + `max_attempts=1` 时），但注释说"理论上不会发生" | [core.py:365-367](gen4399/core.py#L365-L367) | 修正注释；或对必失败组合提前判定 |
| 13 | `--no-verify` 的 help 写"配合 --account 使用"，实际 `--prepare` 也支持 | [cli.py:106-107](gen4399/cli.py#L106-L107) | 更新 help |
| 14 | `--build-form` 提示"复制时请看原始文件或加 --show-pii"，但命令不写任何文件 | [cli.py:258-259](gen4399/cli.py#L258-L259) | 改成"需要明文请加 --show-pii"，或增加 `--output` 写文件 |

---

## 四、P2 工程化与文档配套（目前基本为零）

- **缺 LICENSE**：`pyproject.toml` 也没有 `license` 字段，PyPI 上会告警；README 无许可证章节。
- **缺 CHANGELOG / .gitignore / git 仓库**：当前目录不是 git repo，无法回溯"1.8.1 改了什么"。
- **缺 CI**：建议 GitHub Actions 跑 `3.8 / 3.10 / 3.12 / 3.13` × `pytest` + `ruff` + `mypy`。
  （已用 `ast.parse(feature_version=(3,8))` 验证语法兼容，但需要真机矩阵确认运行时行为。）
- **缺 lint/format/type 配置**：无 `[tool.ruff]` / `[tool.mypy]`；本次审查用自写 AST 脚本才发现未使用导入。
- **缺 `[tool.pytest.ini_options]` 与 dev extras**：`pip install -e ".[dev]"` 不存在；
  另注意 `cd tests && python -m unittest discover` 会失败（4 errors），只支持从仓库根跑。
- **测试覆盖缺口**：
  - `remote.py` 83%：`_http_get()` 的 HTTPError / URLError / socket.timeout 映射（[remote.py:126-154](gen4399/remote.py#L126-L154)）**完全没有单测**（测试全部 mock 掉了 `_http_get`）；
  - **CLI 一个测试都没有**（[cli.py](gen4399/cli.py) 的 `build_parser` 注释写着"便于测试"）；
  - `registration.py:209`（`RegistrationError` 分支）未覆盖；
  - `forms.py` 的 `_valid_birthday` 多个 false 分支、`masked()` 边界未覆盖。
- **doctest**：pytest 默认开 `ELLIPSIS`，所以 `validate("abc")` 这种"省略号占位"的示例能过，
  但用 `python -m doctest` 跑会失败（已实测）；另有 4 个 `# doctest: +SKIP`。建议 CI 显式跑
  `pytest --doctest-modules` 并把示例写准确。
- **README 缺内容**：`--form-path`、`--qq`、`--username-length`、`--prepare` 也支持 `--no-verify`
  都未说明；"规则来源"只提了 web 的 `validation.js`，没提 unified 面板；无 License 章节。
- **可选功能**：`--json` 输出（便于脚本消费）、`--output FILE`、`generate_accounts(count)` 批量、
  `examples/` 目录。

---

## 五、建议实施顺序

1. **修 P0**（约 1~2 小时 + 测试）：远程响应结构化（P0-1/2/3）、`generate_account` 本地校验（P0-4）、
   CLI 异常兜底（P0-5）、unified 死代码决策（P0-6）、QQ strip（P0-7）、Bundle 不可变（P0-8）。
2. **统一 CLI 语义**（P0-9 + P1-13/14）：`-n` / `--username-length` / `--no-verify` / `--show-pii`。
3. **工程门禁**：ruff + mypy + pytest 配置 + coverage 下限 + CI 矩阵 + `pip install -e ".[dev]"`。
4. **补测试**：`test_cli.py`、`test_http_get`（错误映射）、registration 错误分支。
5. **文档收尾**：README 全参数表、License、CHANGELOG、doctest 修正。
6. **可选增强**：`--json`、批量账号、repr 打码、unique 批量。

---

## 附录 A：本次验证命令与结果

```bash
python -m pytest -q                     # 150 passed, 74 subtests
python -m coverage run --branch -m pytest -q && python -m coverage report -m
                                        # TOTAL 95%，remote.py 83%
python -m pip wheel . --no-deps --no-build-isolation   # wheel OK，含 py.typed
python -m gen4399 --version             # gen4399 1.8.1
python -m pytest --doctest-modules gen4399 -q          # 9 passed, 4 skipped
python -m doctest gen4399/core.py       # 失败（ELLIPSIS 占位示例）
```

真实接口探测（`ptlogin.4399.com`）：

```
isExist("abc12345")  -> 用户名已被注册   (available=False)
isExist("ab")        -> 用户名至少要3个字符 (当前也被判 available=False ← P0-1/P1-11)
isExist("4257220954")-> 0                (available=True)
regFrame.do          -> 返回分配账号 4257269775 / 4257270384
```

> 说明：以上只调用了 4399 公开的"用户名是否存在"查询，没有提交任何注册请求。

## 附录 B：复现脚本

审查时的临时脚本在 `lead-workspace/.probe/`（probe.py / probe2.py / probe3.py 等），
可直接 `python .probe/probe.py` 复现 P0 中的行为差异；确认后可以整个目录删掉。
