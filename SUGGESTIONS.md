> **状态（2.0.0）**：本清单已全部落地——重试策略、类型收紧、PII 治理、
> 身份文件增强、CLI 拆分与子命令、模块化拆包、规则校验脚本、CI/文档/属性测试。
> 唯一有意跳过的是「可选异步 extra」（会增加依赖且非核心需求）。
> 具体见 [CHANGELOG.md](CHANGELOG.md)。

# gen4399 1.10.0 全面评估与改进建议

> 评估对象：`gen4399` 1.10.0（当前 HEAD：`1a82c84`）
> 评估方式：通读 7 个源文件（2,831 行）+ 7 个测试文件（1,829 行）；跑测试、覆盖率、CLI 实测、边界行为探测。
> 结论都基于实测，标注了证据。

---

## 0. 总体判断与「如果只做 5 件事」

**判断**：核心库已经相当扎实——零依赖、239 个测试、95% 分支覆盖率、`py.typed`、CI 矩阵、PyPI 级打包都没问题。
当前主要风险不在"功能对不对"，而在**长尾可靠性、CLI 可维护性、类型精度、PII 边界、规则过期后的维护机制**。

如果只做 5 件事，按投入产出排序：

1. **统一远程重试**：两层重试叠加、最坏 8 次请求 + 35s 退避且不可控，弱网下 CLI 会"卡住且说不清"。
2. **拆分 CLI `main()`**：241 行、51 个分支，是当前最大的维护瓶颈（先拆函数，2.0 再拆子命令）。
3. **收紧类型**：`Violation.code` / `FormField.kind` / `UsernameAvailability.kind` 都是裸 `str`，用 `Literal`/常量后 IDE 和 mypy 才真正有价值。
4. **PII 治理**：身份文件明文、`--show-pii` 直接打印、README/测试里用真实感身份证号；建议权限检查 + 合成样例 + 合规声明。
5. **身份文件输入增强**：stdin、去重、跳过坏行、表头、编码选项——现在"全有或全无"在批量场景太脆。

---

## 1. 现状快照（实测）

| 指标 | 结果 |
|---|---|
| 源码 | 2,831 行 / 7 文件；`remote.py` 676、`forms.py` 661、`cli.py` 446 |
| 测试 | 1,829 行 / 239 passed + 84 subtests |
| 覆盖率 | 95%（core 94%、forms 95%、registration 96%、remote 96%、cli 93%） |
| 依赖 | 运行时零依赖；dev 有 pytest/coverage/ruff/mypy |
| 特征 | `py.typed`、60+ 顶层导出、wheel 含类型标记、console script 正常 |
| CI | Python 3.8/3.10/3.12/3.13 × ruff + pytest + coverage + doctest |
| 最大函数 | `cli.main` 241 行 / 51 分支；`prepare_registration` 112；`fetch_suggested_username` 107 |
| 缺失 | 无 `logging`、mypy 未进 CI、无 git tag、无 `SECURITY.md` / `CONTRIBUTING.md` |

---

## 2. 高优先级：正确性与一致性

### 2.1 远程重试是"两层叠加 + 不可控"（最值得先做）

- 位置：[remote.py:167](gen4399/remote.py#L167)（`_http_get` 内部 retries）、[remote.py:279](gen4399/remote.py#L279)（`fetch_suggested_username` 外层 attempts）。
- 证据：`fetch_suggested_username` 默认 `attempts=4`，每次又调 `_http_get(retries=2)` ⇒ **最多 8 次 HTTP 请求**；
  外层退避 `5s → 10s → 20s`（最坏 35s sleep，未计每次 10s 超时），内层再叠加 0.5s 线性退避。
- 缺失：没有**总 deadline**；不处理 `Retry-After`；CLI 只暴露 `--timeout`，无法配置重试；错误对象不带 `url/status/attempt`。
- 建议：
  - 引入 `RetryPolicy`（`max_attempts`、`base_delay`、`max_delay`、`total_deadline`、`respect_retry_after`）统一到 HTTP 层，外层 fetch 不再重复退避；
  - 错误对象带 `url`、`status`、`attempts`、`elapsed`；
  - CLI 增加 `--retries` / `--retry-delay` / `--max-total-timeout`。

### 2.2 `-n` 语义仍然分裂

- 位置：[cli.py:87](gen4399/cli.py#L87)（`-n/--length`）、[cli.py:140](gen4399/cli.py#L140)（`--username-length`）。
- 证据：`gen4399 -u -n 20` 生成 **20 位用户名**；`gen4399 --account -n 20` 的 `-n` 却是**密码**长度（用户名仍是默认 12 位）。
- 建议：1.x 在 help/README 写清"`-u` 模式下 `-n` 是用户名长度，`--account/--prepare` 下是密码长度"；
  2.0 拆成 `--password-length` / `--username-length`，`-n` 标为 legacy。

### 2.3 `check_username()` 对明显非法名称也发请求

- 位置：[remote.py:452](gen4399/remote.py#L452)。
- 证据：`check_username("a b")` 会真的发 1 次 HTTP（服务端返回"用户名包含敏感字符"）；空串同理。
- 建议：加 `validate_input: bool = False` 或 `strict` 参数：本地已知非法时直接返回 `kind="invalid"`，不联网；
  默认保持"以服务端为准"的现有语义，但在文档里写明。
- 顺带：`fetch_suggested_username(retries=0)` 会静默按 1 次处理（[remote.py:279](gen4399/remote.py#L279)），建议显式 `ValueError`。

### 2.4 `FORMS` 是可变全局

- 位置：[forms.py:148](gen4399/forms.py#L148)。
- 证据：`FORMS["web"] = None` 可成功修改，影响后续 `get_form()`。
- 建议：`MappingProxyType` + 元组；若未来要支持第三/第四条注册路径，提供显式 `register_form(form)` 并做重复校验。

### 2.5 类型精度不足，mypy 价值被浪费

- 位置：[core.py:120](gen4399/core.py#L120)（`Violation.code: str`）、[forms.py:55](gen4399/forms.py#L55)（`kind: str`）、[remote.py:120](gen4399/remote.py#L120)（`kind: str`）。
- 建议：用 `typing.Literal` 或常量（3.8 兼容用 `Literal` + 常量别名；3.11+ 可 `StrEnum`）：
  `ViolationCode = Literal["length","charset","all_digits","all_lower","all_upper"]`、
  `FieldKind = Literal["text","password","checkbox","hidden"]`、
  `AvailabilityKind = Literal["available","taken","invalid","unknown"]`。
- 并把 `mypy` 加进 CI（现在只有配置没执行）。

### 2.6 PII 与合规边界

- 证据/位置：身份文件明文读取（[forms.py:539](gen4399/forms.py#L539)）；`--show-pii` 直接打印 [cli.py:142](gen4399/cli.py#L142)；
  README/测试里的样例身份证 `460206194611192084` 真实感很强。
- 建议：
  - 读取身份文件时检查权限（POSIX 下非 0600 给 warning，不阻断）；输出 `--json`/文件时默认 0600。
  - `--show-pii` 更名或加二次确认（如 `--unsafe-show-pii` / 需同时给 `--yes`）。
  - 样例统一换成**合成身份证号**（写一个基于校验码算法生成假号的测试 helper），避免真实信息争议。
  - README 增加"仅限本人身份、遵守 4399 服务条款、不要批量注册他人账号"的醒目声明。
  - 日志/错误信息永不带密码、完整身份证号（目前 repr 已打码，保持）。

---

## 3. API 与架构建议

| # | 建议 | 说明 | 兼容性 |
|---|---|---|---|
| 1 | 拆 `remote.py` → `remote/http.py` + `remote/api.py` | 676 行已偏大；传输层与业务层分离，便于 mock 和替换 | 内部重构，1.x 可做 |
| 2 | 拆 `forms.py` → `forms.py` + `identity.py` | 661 行；`RegistrationProfile` + 行解析 + 文件加载独立成模块 | 内部重构 |
| 3 | `check_fixed_part` → `validate_fixed_part` | 与 `validate_*` 命名族一致；保留别名 | 1.x |
| 4 | `generate*` 支持 `charset=` / `mixed_case=` | 现在用户名固定"小写+数字"，密码固定大小写+数字；给调用方选择权 | 1.x 增量 |
| 5 | `fetch_suggested_usernames(..., with_availability=True)` | 返回 `list[UsernameAvailability]`，批量拿号时能知道哪些被占用/非法 | 1.x |
| 6 | `Account` / `RegistrationBundle` 增加 `to_dict()` / `save(path, mode=0o600)` / JSON | 方便脚本消费、落盘时强制权限 | 1.x |
| 7 | `prepare_registration` 暴露 `retries` / `retry_delay` / `availability` | 与远程层参数对齐 | 1.x |
| 8 | 规则版本号：`RULES_VERSION` + `--rules-version` | 4399 改规则时能快速判断库是否过期 | 1.x |
| 9 | Python 版本策略 | 3.8 已 EOL；2.0 建议 `requires-python >=3.10`，CI 3.10–3.14 | 2.0 |
| 10 | 顶层导出分组文档 | 60+ 导出对新手偏多；README 加"按场景选 API"速查表 | 文档 |

---

## 4. CLI / 交互建议

- **`--json`**：所有命令支持机器可读输出（尤其 `--prepare`、`--account`、`--check-available`）。
- **`--output DIR`**：`--prepare --profile-file ids.txt --output out/` 每个身份写一个文件（0600），便于跑批。
- **`--offline` 全局开关**：替代目前散落的 `--no-verify`（保留别名）。
- **`--account -c N`**：批量账号（现在 `-c` 只对生成密码/用户名生效）。
- **`--min-interval`**：远程命令限速，默认礼貌间隔，降低被风控概率。
- **`--profile-file -`**：从 stdin 读身份，配合管道；`--limit/--offset` 处理大文件。
- **CJK 表格对齐**：`--form-fields` / `--build-form` 用字符数 padding，中文标签实际显示宽度不同
  （实测同一行显示宽度 32 vs 36），用 `unicodedata.east_asian_width` 写个 `_pad()` 即可修。
- **`--check-form` 支持 `--password-confirm`**：验证两次密码不一致的提示。
- **日志**：加 `logging.getLogger("gen4399")`，`--verbose` 输出"第几次尝试/为什么重试"（不含 PII）。

---

## 5. 测试与质量门禁

现状 239 tests / 95% 分支，缺口主要在：`cli.py` 15 行、`forms.py` 7 行、`remote.py` 6 行、`core.py` 5 行未覆盖。

建议补：

1. **property-based 测试**（`hypothesis` 放 dev extra）：`validate(generate(...)) == []`、前缀后缀保留、`unique` 去重、`parse_profile_line` 往返。
2. **模糊测试**：`_parse_suggested_username` 随机 HTML、`parse_profile_line` 随机分隔符/空白——这两个是最容易被服务端改版打脸的地方。
3. **CLI 子进程测试**：现在直接调 `main()` 很好，但 `argparse` 的 SystemExit/help 用 subprocess 才能覆盖。
4. **批量失败聚合**：`--profile-file` 一份好一份坏时的退出码（2）与输出顺序。
5. **HTTP 细节**：429 + `Retry-After`、重定向、gzip（当前不发 Accept-Encoding，可断言）、UA/Referer。
6. **元数据测试**：`importlib.metadata.version("gen4399") == gen4399.__version__`。
7. **`__main__.py` smoke test**（当前 0% 覆盖）。

CI 增强：`mypy`（先 non-strict，再逐步 strict）、`ruff format --check`、`python -m build && twine check`、coverage XML 上传、`pre-commit`。

---

## 6. 文档与维护

- **FAQ**：为什么密码不能预校验、`regFrame.do` 频率限制、验证码何时出现、规则可能随前端改版过期。
- **`SECURITY.md` / `CONTRIBUTING.md`**：PII 处理原则、如何新增注册路径、如何更新规则。
- **规则快照**：在 `docs/rules.md` 记录 `validation.js` 的抓取日期与关键正则，配 `scripts/verify_rules.py`（拉取并比对关键字符串）。
- **样例数据合成化**：测试/README 统一用生成器产出的假身份证号。
- **发版**：打 `v1.10.0` tag；README 加 CI/License/Python 版本徽章（需要先有远端仓库）。

---

## 7. 可选功能路线图（按 ROI）

| 功能 | 工作量 | 价值 | 建议版本 |
|---|---|---|---|
| `--json` / `--offline` | S | 高（脚本化） | 1.11 |
| profiles：stdin / 去重 / 跳过坏行 / 表头 / `--encoding` | S | 高（批量场景） | 1.11 |
| 重试策略对象 + `--retries` / `--max-total-timeout` | M | 高（弱网可靠性） | 1.11 |
| `--account -c N` 批量 | S | 中 | 1.12 |
| `--output DIR`（0600） | M | 中 | 1.12 |
| `Account/Bundle.to_dict()/save()` | S | 中 | 1.12 |
| 日志 + `--verbose` | S | 中（排障） | 1.12 |
| 异步/并发查询（可选 extra） | L | 中（大批量） | 2.0 |
| 配置对象统一参数传递 | M | 低 | 2.0 |

---

## 8. 不建议做的事

- **自动提交注册**：合规风险高，且会把库从"准备工具"变成"批量注册工具"；保持"只准备、不提交"。
- **绕过验证码/风控**：不碰。
- **引入重依赖**（requests/httpx 作为运行时依赖）：破坏零依赖优势；如需异步，做成可选 extra。
- **泛化到多站点/插件系统**：当前 4399 单点规则清晰，过度抽象得不偿失。

---

## 9. 建议迭代顺序

1. **1.11（低风险高收益）**：`RetryPolicy` + 总 deadline + `Retry-After`；`check_username` 本地预校验开关；
   `FORMS` 只读；`Literal` 类型；profiles stdin/去重/跳过/表头；`--json`；CJK 对齐；PII 权限提示。
2. **1.12**：CLI 拆 `_cmd_*` 函数；`--offline`/`--output`/`--account -c N`；mypy 进 CI；规则校验脚本。
3. **2.0**：argparse 子命令（旧 flag 保留 deprecation 别名）；`--password-length`/`--username-length` 明确化；
   `requires-python >=3.10`；`remote`/`forms` 模块拆分；API 重命名（`validate_fixed_part`）。
4. **持续**：规则快照更新、合成测试数据、文档 FAQ、发版 tag。

---

## 附录：本次实测记录

```bash
python -m pytest -q                     # 239 passed, 84 subtests
python -m coverage run --branch -m pytest -q && python -m coverage report
                                        # TOTAL 95%
python -m pytest --doctest-modules gen4399 -q   # 10 passed, 5 skipped
python -m pip wheel . --no-deps --no-build-isolation   # 1.10.0 wheel，含 py.typed
```

边界实测（均已复现）：

```
gen4399 -u -n 20                    -> 用户名 20 位
gen4399 --account --no-verify -n 20 -> 密码 20 位、用户名 12 位
--profile-file ... --qq 123456789   -> QQ 被静默忽略
check_username("a b")               -> 仍发 1 次 HTTP
fetch_suggested_username(retries=0) -> 静默按 1 次执行
FORMS["web"] = None                 -> 可修改（全局可变）
load_profiles 重复身份证              -> 不提示重复
parse_profile_line("姓名|身份证号")   -> 报 idcard 格式错误（无表头支持）
--form-fields/--build-form 表格列     -> CJK 标签导致列错位（显示宽度 32 vs 36）
```
