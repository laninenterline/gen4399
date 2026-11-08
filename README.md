# gen4399

生成与校验**符合 4399 注册规则**的密码与账号名。零依赖（只用标准库）。

- 本地：生成 / 校验密码、用户名，估算熵，批量生成（可保证不重复）
- 远程：封装 4399 官方两个 ptlogin 接口
  - `fetch_suggested_username()` —— 取服务端「为您分配的账号」
  - `check_username()` / `is_username_available()` —— 查询用户名是否可注册
- 表单：两条注册路径的字段定义 + 提交前本地整表校验（不联网）
- 编排：`prepare_registration()` 一键准备好「可照着填 / 可直接提交」的注册数据
- 提交（2.1.0 / 2.2.0 / 2.3.0 / 2.4.0 / 2.5.0）：`submit_registration()` / `gen4399 submit`
  真实提交到 4399 ——**库不会自动提交**（CLI 默认 dry-run）；支持 `web` 与 `unified`
  两条路径，**两条路径均已实测建号成功（2026-11-08）**
- 结果与运维（2.5.0）：`SubmitResult.verified` 注册后自动复核账号；`kind="throttled"`
  识别 4399 注册接口限流；`--captcha-auto` 自动用本机 OCR，没有就退回人工输入
- unified 修复（2.4.0）：剔除 13 个会让服务端返回空白「4399提示」页的隐藏域后，
  unified 路径跑通，并默认**提交实名**（`realname`/`idcard` 走 AES 加密）
- 图形验证码（2.3.0 / 2.6.0）：web 路径遇到 `code=200` 时按「取图 → 识别 →
  verifyCode → 带 `chk_code` 重提交」处理；unified 遇到验证码页时按「取图 →
  识别 → 带 `inputCaptcha` 重提交」处理。**识别由调用方的 `captcha` 回调提供**，
  库里自带三种现成实现：内置识别器（60×30 专用）、外部 OCR 命令、人工输入
- 身份信息：可从 `姓名|身份证号[|QQ]` 格式的 txt 批量读取
- 传输层（2.7.0）：代理 / 代理池 / 随机 User-Agent，统一由 `TransportOptions` 传参

> **默认不提交注册**：`prepare_registration()` 只准备数据，不会自动提交；
> 真实提交必须显式调用 `submit_registration()`，命令行必须显式加 `--yes`。
> 2.2.0 起 `web` / `unified` 两条路径都可提交；2.3.0 起 web 路径支持图形验证码
> （调用方提供回调）；2.4.0 起 unified 也已实测建号成功，并默认提交实名（AES 加密）。
> 请只使用你本人的真实身份信息，并遵守 4399 的用户协议。
> **已用于实名绑定的身份证再次注册会被服务端拒绝**（实测返回 `姓名身份证不匹配`）；
> 本库无法仅凭响应区分「已绑定」与「实名不通过」，请只使用本人未绑定过 4399 的身份证。

## API 分层

日常只需要顶层这几个名字：

```python
from gen4399 import RegistrationProfile, prepare_registration, submit_registration
```

顶层 `__all__` 是**核心 34 个**（生成/校验、身份、编排、提交、远程、传输 + `__version__`）。
其余名字（常量、表单细节、验证码回调、错误子类等）**仍然可以 `from gen4399 import X`**，
只是不再属于公共契约、也不进 `from gen4399 import *`。按域取更清晰：

| 模块 | 内容 |
|---|---|
| `gen4399.forms` | 表单字段定义、整表校验、`build_registration_fields()` |
| `gen4399.identity` | `RegistrationProfile`、姓名/身份证/QQ 校验、txt 批量读取 |
| `gen4399.remote` | 服务端分配账号 / 查重接口、`RetryPolicy`、远程错误类型 |
| `gen4399.captcha` | `prompt` / `command` / `auto` / `save` 四种识别回调 |
| `gen4399.submit` | `submit_registration()`、`SubmitResult`、提交端点常量 |
| `gen4399.constants` | 规则版本、长度限制、端点 URL、`UNIFIED_DROP_FIELDS` 等纯常量 |
| `gen4399.transport` | `TransportOptions`（超时 / 代理 / 代理池 / 随机 UA / 重试） |
| `gen4399.proxy` | `ProxyPool`、`ProxyError`、`normalize_proxy()` |
| `gen4399.ua` | `random_user_agent()` |
| `gen4399.login` | `login()`、`LoginResult`（账号密码换登录 Cookie） |
| `gen4399.batch` | `run_batch()`、`BatchSummary`（批量编排） |
| `gen4399.config` | `configure()`、`current_config()`（运行期开关） |

> `gen4399.constants` 是常量的**完整**出口：`UNIFIED_DROP_FIELDS`、`VERIFY_URL`
> 这类实现细节只在这里（以及 `gen4399.submit`）导出，不占顶层命名空间。

## 代理与随机 UA（2.7.0）

4399 对单 IP 的注册频率有硬限制（连续注册会拿到 `202` + 「请稍后再试~」），
需要换 IP / 换指纹时用传输层选项：

```python
from gen4399 import (
    ProxyPool, TransportOptions, prepare_registration, submit_registration,
)

pool = ProxyPool.from_file("proxies.txt", strategy="round-robin")  # 一行一个
opts = TransportOptions(proxy_pool=pool, random_user_agent=True, timeout=15)

bundle = prepare_registration(profile, path="unified", transport=opts)
result = submit_registration(bundle, transport=opts, captcha=matcher_captcha_solver())
```

```bash
# CLI / make_account.py 同款参数
gen4399 submit --form-path unified --proxy http://127.0.0.1:8080 --random-ua --yes
gen4399 submit --form-path unified --proxy-file proxies.txt --proxy-strategy random --random-ua --yes
python scripts/make_account.py --yes --form-path unified --proxy-file proxies.txt --random-ua
```

| 选项 | 说明 |
|---|---|
| `--proxy URL` | 单个 HTTP(S) 代理；`host:port` 会自动补 `http://` |
| `--proxy-file FILE` | 代理池，一行一个，`#` 注释 |
| `--proxy-strategy` | `round-robin`（默认）/ `random` |
| `--random-ua` | 每个会话随机生成真实格式的浏览器 UA |
| `--proxy-sticky` | 粘住代理池里的第一个代理（查重 + 提交同一个 IP） |

> 只支持 HTTP(S) 代理（SOCKS 需要额外依赖，本库保持零运行时依赖）。
> 每次调用会自动取下一个代理；同一会话内（GET→POST→验证码）始终用同一个 IP。

## 安装

```bash
pip install -e .            # 运行时零依赖
pip install -e ".[dev]"     # 开发：pytest / coverage / ruff / mypy
```

或者不安装，直接在本目录下 `import gen4399`。

> 2.0 起要求 **Python >= 3.10**。

## 快速开始

```python
from gen4399 import (
    generate, generate_many, validate, is_valid,
    generate_username, generate_usernames,
    validate_username, is_valid_username,
    fetch_suggested_username, fetch_suggested_usernames,
    check_username, is_username_available,
)

generate()                      # 16 位随机密码
generate(length=20)             # 20 位
generate(prefix="lg")           # 以 "lg" 开头的 16 位
generate(suffix="gz")           # 以 "gz" 结尾的 16 位
generate(prefix="lg", suffix="gz", length=20)
generate_many(5)                # 一次生成 5 个
generate_many(5, unique=True)   # 保证 5 个互不相同

is_valid("Abc12345")            # True
validate("123456")              # [Violation(code='all_digits', ...)]

# 账号名（用户名）
generate_username()             # 12 位小写字母+数字
generate_username(length=16)
generate_username(prefix="u", suffix="gz")
generate_usernames(5, unique=True)   # 去重批量生成

validate_username("abc12345")   # []
validate_username("4257220954") # []（纯数字允许，4399 自动账号就是纯数字）
validate_username("abc_12345")  # [Violation(code='charset', ...)]
```

> 用户名规则：长度 6~20、只允许字母和数字、允许纯数字、不允许 `_` `@` 中文。
> 生成默认用小写字母+数字（36 字符集），更好读。

```python
# 2.1.0+：把准备好的注册数据真正提交出去（先 dry-run，不创建账号）
from gen4399 import submit_registration

# bundle = prepare_registration(profile, path="unified")   # 或 path="web"
r = submit_registration(bundle, dry_run=True)   # 只拉必要数据 + 组装/加密，不发注册 POST
r.kind                                          # 'dry_run'
r = submit_registration(bundle, dry_run=False)  # 真实提交（web / unified；仅限本人身份）
# 2.3.0：web 路径若要求图形验证码，传 captcha=回调（PNG 字节 -> 识别文本）
# r = submit_registration(bundle, dry_run=False, captcha=my_solver, captcha_attempts=3)
if r:                                           # SubmitResult.__bool__ == r.ok
    print("判定成功：", r.message, "验证码轮次：", r.captcha_attempts)
```

> 详细字段、结果判定、CLI 退出码与合规要求见 [提交注册（web / unified，2.4.0）](#提交注册web--unified240)。

## 远程接口（调用 4399 官方 API）

```python
from gen4399 import (
    fetch_suggested_username, fetch_suggested_usernames,
    check_username, is_username_available, RemoteError,
)

# 1) 取服务端分配的账号（形如 4257237567）
name = fetch_suggested_username()

# 拿到后自动查重（被占用会继续重试）
name = fetch_suggested_username(verify_available=True)

# 支持追加前后缀（服务端账号 + 自定义前缀/后缀）
name = fetch_suggested_username(prefix="u", suffix="gz")   # 'u4257237567gz'

# 接口有频率限制，拿不到时可降级到本地生成
name = fetch_suggested_username(fallback_to_local=True)

# 批量：unique=True 会凑满数量，凑不满抛 RemoteError（不再静默少返回）
names = fetch_suggested_usernames(3, unique=True)

# 2) 查询用户名是否还能注册（官方 isExist.do）
res = check_username("abc12345")
res.available     # True / False
res.kind          # 'available' / 'taken' / 'invalid'
res.message       # '0' 或 '用户名已被注册' 等

is_username_available("abc12345")   # True / False
```

> **1.9.0 起**：接口返回空 body 或 HTML 错误页时，`check_username()` 抛
> `RemoteParseError`，不再静默当成「已被注册」；`kind="invalid"` 表示名字
> 本身不合法（如太短），与「已被占用」区分开。
>
> 远程请求带有限重试（超时 / 5xx / 429），指数退避 + 抖动、单次封顶 60s；
> 可用 `timeout=` 控制单次超时。

## 自动探测可用性

```python
from gen4399 import (
    generate_available_username,   # 本地生成 + 服务端确认可注册
    generate_account,              # 一键生成 Account(username, password)
)

name = generate_available_username()      # 保证 isExist.do 返回 0
acc = generate_account()                  # 默认已查重账号名
print(acc.username, acc.password)
repr(acc)                                 # 密码打码，可安全写日志
```

> `generate_account(username="ab", verify_username=False)` 这种显式指定非法
> 用户名的用法现在会直接抛 `ValueError`——生成结果始终保证合规。
>
> 账号名可以「预探测」（官方 `isExist.do`）；**密码无法预探测**——
> 4399 没有密码校验接口，只有注册提交时才校验（2.1.0 起可显式提交，见
> [提交注册（web / unified，2.4.0）](#提交注册web--unified240)）。
> 密码侧只能保证通过公开规则（本库 `validate()` 在本地保证）。

## 批量注册编排（3.2.0）

```bash
gen4399 batch --profile-file identities.txt --form-path unified \
  --captcha-matcher --interval 45 --jitter 30 --max-failures 3 \
  --verify-login --output accounts.json --yes
```

- 每个身份独立 `prepare → submit`；代理池 + 随机 UA 让每个号走不同出口
- `--interval/--jitter` 控制节奏（默认 30s + 0 抖动）
- `--max-failures 3`：连续失败 3 次自动停
- **断点续跑**：账号记录写入 `idcard_hash`，已成功的身份下次自动跳过
- 每条结果立即落盘（0600），中断不丢已建好的号
- `--json` 输出汇总（总数/成功/失败/按 kind/用时）

```python
from gen4399 import RegistrationProfile, run_batch, matcher_captcha_solver

summary = run_batch(
    [RegistrationProfile("张三", "460206194611192084")],
    path="unified", captcha=matcher_captcha_solver(),
    interval=45, jitter=30, output="accounts.json",
)
summary.success, summary.failed, summary.by_kind()
```

## web 验证码识别（3.1.0）

unified 的 60×30 用 `--captcha-matcher`（内置模板，实测一次过）。**web 是另一套**：
150×45、细线描边 + 3D 实心块两种风格、还带斜体，两套字形不通用，缩放到 60×30
再套 unified 模板只会得到乱码。

所以 web 走**自学习字库**：

```bash
gen4399 submit --form-path web --captcha-learn --yes
python scripts/make_account.py --yes --form-path web --captcha-learn
```

- 字形先**骨架化**（描边和实心块细化后形状接近），归一化到 24×32，
  再按 **chamfer 距离**做最近邻（含 ±1 像素平移增强）
- 每次服务端 `verifyCode` 判定通过，就把这 4 个字形连同答案写进字库
  （默认 `~/.gen4399/web_captcha_bank.json`）——用得越多越准
- 随库附带 61 个已标注样本作为种子，开箱即可用
- **web 验证码的字符集比 unified 宽**（实测出现过 `L` 等 unified 25 字集里没有的字符），
  所以字库按实际样本学习，不假设固定字符集
- 拿不准时会退到 `--captcha-prompt`；在交互终端里没显式指定也会自动问人，
  答对后回填字库（不需要额外配置）

实测（61 样本留一法）：**字符准确率 88%**，即单轮整码约 60%，3 轮约 94%。
随时可以自测：`gen4399 captcha bench <目录>`（目录里要有 `labels.json`）。

3D 块状字形在种子里样本偏少，是目前最大的误差来源——遇到时会走
`--captcha-prompt` 分支，并把人工答案通过 `feedback` 补进字库。

## 登录（2.10.0）

拿账号密码换登录 Cookie，用来确认「这个号真的能登」：

```python
from gen4399 import login

r = login("myaccount", "mypassword")
r.ok          # True
r.kind        # 'success' / 'rejected' / 'captcha' / 'unknown'
r.cookies     # ('Pauth', 'Uauth', 'Xauth', ...)，只有名字
```

```bash
gen4399 login myaccount --password 'mypassword'   # 不给 --password 会交互输入
python scripts/make_account.py --yes --verify-login   # 注册完自动登录复核
```

协议：`POST https://ptlogin.4399.com/ptlogin/login.do?v=1`，
body 只有 `appId` / `username` / `password`（AES）/ `sec=1`。
**不要**把 `loginFrame.do` 的全套隐藏域一起回传——实测那样会拿到空白
「4399提示」页（和注册路径是同一个坑）。失败时返回 `<div id="Msg">密码错误</div>`。

## 注册表单（字段定义 + 本地校验）

覆盖两条注册路径：2.2.0 起 `web` / `unified` 都可**显式提交**
（见[提交注册](#提交注册web--unified240)一节）。本地校验本身不联网、不提交：

```python
from gen4399 import get_form, check_registration_form

# 1) 查表单需要提交哪些字段
form = get_form("web")            # 或 "unified"
for f in form.fields:
    print(f.name, f.label, "必填" if f.required else "选填", f.note)

# 2) 提交前把数据校验一遍（用户名/密码/姓名/身份证/QQ）
res = check_registration_form(
    "abc12345", "Abc123456",
    path="web",
    realname="张三",
    idcard="460206194611192084",
    qq="123456789",
)
res.ok          # True
res.errors      # {'idcard': ['身份证号校验码不正确，请核对']}
res.messages()  # ['idcard: 身份证号校验码不正确，请核对']
```

| 路径 | 页面 | 提交地址 | 本库能否提交 |
|---|---|---|---|
| `web` | https://web.4399.com/user/reg.php | `POST /user/?_c=reg` | ✅ 2.2.0 起 `submit_registration()`（CLI 需 `--yes`，默认 dry-run）；2.3.0 起支持图形验证码回调 |
| `unified` | https://u.4399.com/register.html | `POST /ptlogin/register.do` | ✅ 2.1.0 起（CLI 需 `--yes`，默认 dry-run）；2.4.0 实测跑通（剔除隐藏域、默认提交实名） |

单独校验字段也可用：`validate_realname()` / `validate_idcard()` / `validate_qq()`
（QQ 会自动 `strip()`，首尾空白不会导致误判）。

### 身份信息（姓名 + 身份证）

```python
from gen4399 import (
    RegistrationProfile, InvalidProfileError,
    check_registration_form, build_registration_fields,
)

profile = RegistrationProfile(
    realname="张三",
    idcard="460206194611192084",
    qq="123456789",
)

profile.is_valid()          # True
profile.errors()            # {} 或 {'idcard': ['身份证号校验码不正确，请核对']}
profile.masked_idcard()     # '460206********2084'，可安全写日志
profile.masked()            # '张* 460206********2084 qq=12*******'
profile.require_valid()     # 不合规时抛 InvalidProfileError

# 校验整套表单
check_registration_form("abc12345", "Abc123456", profile=profile).ok

# 生成「照着填」的清单（只组装数据，不提交）
build_registration_fields("abc12345", "Abc123456", profile=profile)
# {'cid': '3000', 'login_name': 'abc12345', 'login_password': 'Abc123456',
#  'relogin_pwd': 'Abc123456', 'qq': '123456789', 'true_name': '张三',
#  'sfz': '460206194611192084', 'agree': 'on'}
```

> 身份信息默认只在你本机内存中使用。只有显式调用
> `submit_registration(..., dry_run=False)` / `gen4399 submit --yes` 时，
> 姓名、身份证等字段才会（`sec=1` 时 AES 加密后）发往 4399 官方端点；
> `dry_run` 只 GET 注册表单页，不发送任何 PII、也不发 POST。

### 一键准备注册数据

```python
from gen4399 import RegistrationProfile, prepare_registration

profile = RegistrationProfile("张三", "460206194611192084", qq="123456789")
bundle = prepare_registration(profile)        # 生成用户名 → 查重 → 生成密码 → 校验 → 组装字段

print(bundle.username)        # 已查重可用
print(bundle.password)        # 合规密码
print(bundle.fields)          # 只读映射，直接照着填
print(bundle.as_text())       # 可读清单（身份证/密码/QQ 默认打码）
print(bundle.masked_fields()) # 打码后的字段字典，可安全贴日志

# 自定义用户名前后缀（计入总长度，至少留 1 位随机）
bundle = prepare_registration(profile, prefix="u", suffix="gz")

# 拿不到网络时也可离线准备
bundle = prepare_registration(profile, verify_username=False)
```

> **`prepare_registration()` 本身不会提交注册**。它把能自动化的部分（生成、查重、校验、组字段）
> 全做完；2.1.0 起可在拿到 `bundle` 后显式调用 `submit_registration()` 提交
> （2.2.0 起 `web` / `unified` 都支持，见下一节），
> 或继续在 `bundle.url` 页面手动提交。

对应的 `RemoteError` 子类：`RemoteTimeoutError`、`RemoteHTTPError`、`RemoteParseError`。

> 长度 `-n` 是**总长度**，前缀和后缀都算在内；固定部分越长，随机部分越短。

### 从 txt 批量读取身份信息

`ids.txt` 每行一个身份：`真实姓名|身份证号`，可选第三列 QQ；
空行与 `#` 开头的注释会跳过，支持全角竖线 `｜` 和 UTF-8 BOM：

```text
# 我的身份
张三|460206194611192084
李四|440106198101010155|123456789
```

```python
from gen4399 import load_profiles, parse_profile_line

profiles = load_profiles("ids.txt")      # list[RegistrationProfile]，已逐行校验
profiles[0].masked()                     # 可安全打印

parse_profile_line("张三|460206194611192084|123456789")   # 单行解析

for profile in profiles:
    bundle = prepare_registration(profile, verify_username=False)
    print(bundle.as_text())
```

CLI 也支持批量（每个身份输出一段）：

```bash
python -m gen4399 --prepare --no-verify --profile-file ids.txt
python -m gen4399 --build-form abc12345 Abc123456 --profile-file ids.txt
python -m gen4399 --check-form abc12345 Abc123456 --profile-file ids.txt
```

> `--profile-file` 与 `--realname/--idcard` 互斥；某行格式/内容不合法时整体报错，
> 错误信息带行号（退出码 2）。
>
> **默认身份文件**：如果既没给 `--profile-file`，也没给 `--realname/--idcard/--qq`，
> CLI 会自动读取**当前目录下的 `sfz.txt`**（格式同样是 `姓名|身份证号[|QQ]`）。
> 文件不存在时退出码 2 并提示；`gen4399 profile check` 也适用（其 `--profile-file`
> 已改为可选）。编码默认先按 UTF-8（含 BOM）读取，失败自动回退 **GB18030**（兼容
> GBK 文件）；也可用 `--profile-encoding` 显式指定。`sfz.txt` / `accounts.json`
> 已加入 `.gitignore`，避免身份/账号误提交。

## 提交注册（web / unified，2.4.0）

2.1.0 起支持 `unified`（ptlogin）路径提交，2.2.0 起也支持 `web`
（web.4399.com 用户中心）路径，2.3.0 起 web 路径支持**图形验证码**流程，
2.4.0 起 unified 路径**也已实测建号成功**（剔除 13 个触发空白提示页的隐藏域，
默认提交实名）。两者都是显式操作：库不会自动提交；**CLI 默认 dry-run**
（必须加 `--yes` 才发送注册请求）；API 调用 `submit_registration()` 即视为提交
（默认 `dry_run=False`），**推荐先传 `dry_run=True` 演练**，确认无误后再真实提交。

| 路径 | 提交流程 | 敏感字段处理 |
|---|---|---|
| `web` | `GET user/?_c=login&_a=checkUser` 取 `encryptCode` → `POST user/?_c=reg`（JSONP 响应）；若返回 `code=200`：取验证码图 → `verifyCode` 校验 → 带 `chk_code` 重提交 | 密码用页面同款 `encode_4399()`（DES/3DES）；`true_name`/`sfz` 明文在 HTTPS 请求体中 |
| `unified` | `GET regFrame.do` 取隐藏域/会话 → **剔除 13 个隐藏域** → `POST register.do` | `sec=1` 时 AES-256-CBC 加密 `password/passwordveri/realname/idcard`；默认**发送实名** |

> **实测状态**：`web` 与 `unified` 均已在 2026-11-08 真实建号成功
> （unified 实测账号用户名 `abkeq7xvesft`、`abnsm4uw2s77`，密码不记录；
> 后者就是「21 基础字段 + 实名 AES」的 23 字段版本）。

> 协议细节（端点、字段表、AES/DES 参数、图形验证码、结果判定、已知限制）见
> [docs/submit.md](docs/submit.md)。
>
> **图形验证码必须由调用方提供识别回调**（`captcha=Callable[[bytes], str]`，
> 入参是验证码 PNG 原始字节）：本库**不内置破解**，也不内置 OCR；可用人工输入、
> 外部 OCR 命令，或自己接入识别服务。
>
> **已用于实名绑定的身份证再次注册会被服务端拒绝**（实测 `msg="姓名身份证不匹配"`、
> `kind="rejected"`；该文案无法区分「已绑定」与「实名不通过」）。
> 请只使用本人、且未绑定过 4399 的身份证。

### 验证码与字段剔除（协议细节见 [docs/submit.md](docs/submit.md)）

- **web**：首次 `POST /user/?_c=reg` 常返回 `code=200`（要图形验证码）。
  同一会话内「取图 → 识别 → `verifyCode` → 带 `chk_code` 重提交」即可；
  `captcha=` 不传则返回 `kind="captcha"`，不重试。
- **unified**：`regFrame.do` 的隐藏域原样回传会让服务端返回空白「4399提示」页
  （不是风控封 IP）。库按 `UNIFIED_DROP_FIELDS`（13 个）剔除后提交 23 个字段；
  默认连实名一起 AES 加密（`UNIFIED_SEND_REALNAME=True`）。
- **unified 验证码**：响应重渲染成带 `inputCaptcha` / `captcha.do?captchaId=…`
  的表单时，`captcha=` 回调会被调用并带 `inputCaptcha` 重提交（字段名**不是**
  `fCaptcha`，`sessionId` 要换成页面给的 captchaId）。
- 端点、字段表、AES/DES 参数、实测样本见 [docs/submit.md](docs/submit.md)；
  规则来源见 [docs/rules.md](docs/rules.md)。

### API

```python
from gen4399 import (
    RegistrationProfile, prepare_registration,
    submit_registration, SubmitResult, SubmitError,
    prompt_captcha_solver,          # 2.3.0：人工识别（保存图片 + 终端提示输入）
    command_captcha_solver,         # 2.3.0：外部 OCR 命令（PNG stdin → stdout）
)

profile = RegistrationProfile("张三", "460206194611192084", qq="123456789")

# 两条路径都支持：web（默认）与 unified
bundle = prepare_registration(profile, path="web")        # 或 path="unified"

# 1) dry-run（推荐先跑）：只拉必要数据、本地组装/加密字段，不发注册 POST
result = submit_registration(bundle, dry_run=True)
result.kind              # 'dry_run'
bool(result)             # False（dry-run 不算成功）
result.endpoint          # 将要 POST 的地址
result.encrypted_fields  # web: 2 个(DES)；unified: 2 个(AES，默认不含实名)

# 2) 真实提交（仅限本人真实身份，请先确认遵守 4399 用户协议）
#    web 路径若返回 code=200，会调用 captcha 识别图形验证码后带 chk_code 重提交
solver = prompt_captcha_solver()          # 或 command_captcha_solver("your-ocr-cmd")
result = submit_registration(
    bundle, dry_run=False,
    captcha=solver,                       # 不传则遇到图形验证码直接返回 kind="captcha"
    captcha_attempts=3,                   # 最多 3 轮（默认），必须 >= 1
)

if result:               # SubmitResult.__bool__ 等价于 result.ok
    print("判定成功：", result.message, "验证码轮次：", result.captcha_attempts)
else:
    print("未成功：", result.kind, result.message)
```

> `captcha` 回调的入参是验证码 PNG 的**原始字节**（`HttpResponse.raw`，2.3.0 新增），
> 返回值是识别出的文本。`prompt_captcha_solver()` / `command_captcha_solver()` 只是
> 现成的「人工输入 / 调外部命令」实现，**都不是验证码破解**：
> 前者把图片存成 0600 的 PNG 后让你输入，后者把 PNG 交给外部命令（如 tesseract）。
> 外部命令超时或非 0 退出会抛 `CaptchaSolverError`（`Gen4399Error` 子类）。

函数签名：

```python
submit_registration(
    bundle: RegistrationBundle, *,
    app_id: str = "u4399",        # 仅 unified 使用
    level: int = 4,               # 仅 unified 使用
    timeout: float = 10.0,
    dry_run: bool = False,
    retry_policy: RetryPolicy | None = None,
    on_response: ResponseHook | None = None,   # 诊断用：收到注册 POST 的 HttpResponse
    captcha: CaptchaSolver | None = None,       # 2.3.0：PNG 字节 -> 验证码文本
    captcha_attempts: int = 3,                  # 2.3.0：最多重试轮数（>= 1）
) -> SubmitResult
```

`SubmitResult`（frozen dataclass；`repr()` 与 `to_dict()` 均已脱敏，可安全写日志）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `ok` | `bool` | 是否（可判定为）注册成功；`bool(result)` 等价于它 |
| `kind` | `str` | `success` / `rejected` / `captcha` / `unknown` / `dry_run` |
| `message` | `str` | 人读说明；`rejected` 时是服务端错误文案 |
| `username` | `str` | 提交的用户名 |
| `path` | `str` | 注册路径：`web` 或 `unified` |
| `app_id` | `str` | 提交用的 appId；web 路径不适用，返回空串 |
| `endpoint` | `str` | 实际（dry-run 时是「将要」）POST 的地址 |
| `http_status` | `int \| None` | 注册 POST 的 HTTP 状态码；dry-run 为 `None` |
| `final_url` | `str \| None` | 跟随重定向后的最终地址（已去掉 query/fragment） |
| `encrypted_fields` | `tuple[str, ...]` | 实际加密的字段名（web 2 个 DES；unified 默认 2 个 AES：`password`/`passwordveri`；`UNIFIED_SEND_REALNAME=True` 时 4 个） |
| `login_cookies` | `tuple[str, ...]` | 提交后 CookieJar 中的登录 Cookie **名字**（不含值） |
| `field_names` | `tuple[str, ...]` | 提交的字段名（不含值；web 首次提交不含 `chk_code`） |
| `dry_run` | `bool` | 是否只是 dry-run（未发注册 POST） |
| `captcha_attempts` | `int` | 2.3.0：实际执行的图形验证码轮数（`0` 表示没遇到/不需要验证码） |
| `verified` | `bool \| None` | 2.5.0：注册成功后是否用同会话访问 `u.4399.com` 复核到该账号（`None` = 无法判断） |
| `elapsed` | `float` | 整个调用的耗时（秒） |

- `SubmitResult.to_dict()` 返回可 JSON 序列化的脱敏字典（`--json` 用的就是它，
  含 `captcha_attempts` 与 `verified`）。
- `kind` 新增 `throttled`：服务端返回 `202` + 「请稍后再试~」时表示注册接口限流，
  肯定没建号，等几分钟再跑（别连续重试）。
- `SubmitError`：参数/路径不合法。网络失败抛 `RemoteError` 子类
  （`RemoteTimeoutError` / `RemoteHTTPError` / `RemoteParseError`）；
  `captcha` 回调/外部识别命令失败抛 `CaptchaSolverError`（`Gen4399Error` 子类）。
- `unified` 的 `field_names` 默认是 **21 个**（见上一节）；`web` 首次提交 8 个，
  验证码重提交额外带 `chk_code`。
- `retry_policy` 只作用于 **GET**（unified 拉表单 / web 取 encryptCode / 取验证码图）；
  **注册 POST 永远单次尝试、不自动重试**（防止超时后重复注册）。

### CLI

```bash
# 默认 dry-run：本地组装/加密，绝不发注册 POST
gen4399 submit --realname 张三 --idcard 460206194611192084
gen4399 submit --form-path web --realname 张三 --idcard 460206194611192084      # web
gen4399 submit --form-path unified --realname 张三 --idcard 460206194611192084  # unified

# 真实提交：必须显式加 --yes
gen4399 submit --form-path web --realname 张三 --idcard 460206194611192084 --qq 123456789 --yes
gen4399 submit --form-path unified --realname 张三 --idcard 460206194611192084 --yes

# 2.3.0：web 图形验证码（人工输入 / 外部 OCR / 保存图片 / 轮数）
gen4399 submit --form-path web --realname 张三 --idcard 460206194611192084 --yes \
    --captcha-prompt --captcha-dir ./captcha
gen4399 submit --form-path web --realname 张三 --idcard 460206194611192084 --yes \
    --captcha-cmd "tesseract stdin stdout -l eng --psm 8" --captcha-attempts 5

# 其它选项：JSON / 输出目录（--output 写 out/submit.json，0600）
gen4399 submit --realname 张三 --idcard ... --timeout 10 --json --output out/

# 批量身份（必须均为本人或已获授权；多于 1 个时 stderr 会警告）
gen4399 submit --profile-file ids.txt          # dry-run
gen4399 submit --profile-file ids.txt --yes    # 真实提交
```

- `--form-path` 可选 `web` / `unified`，**默认 `unified`**（推荐：默认不发送姓名/身份证，PII 更少）。
- `--yes` 才发送注册 POST；不加 `--yes` 时只做 dry-run（仍会 GET 一次：
  unified 拉 `regFrame.do`，web 取 `encryptCode`；dry-run 不取验证码图）。
- 不传任何验证码选项时，web 路径一旦遇到 `code=200` 就以 `kind="captcha"`
  结束（退出码 1），并提示可加 `--captcha-prompt` / `--captcha-cmd`。
- 多身份会依次提交；可用 `--min-interval` 控制间隔，`--json` / `--output` 汇总结果。
- 退出码：**0** 成功或 dry-run；**1** 被拒 / 未知 / 需要验证码（含验证码轮次用尽）；
  **2** 参数、网络或配置错误（含验证码命令失败）。
- 成功时输出会多一行「验证码轮次: N」（`captcha_attempts > 0` 时）。
- **注册成功但没记下密码？** 默认只打用户名；加 `--show-pii` 会在成功后在终端打印
  刚生成的密码（`--json` 仍脱敏）。要自动落盘保存账号请用 `scripts/make_account.py`
  （成功即追加 `accounts.json`，0600）。

2.3.0 图形验证码选项（仅 web 路径实际用到）：

| 参数 | 说明 |
|---|---|
| `--captcha-prompt` | 每轮把验证码存成 PNG 并提示**人工输入** |
| `--captcha-cmd CMD` | 调外部命令识别：PNG 从 stdin 传入，stdout 第一行作为结果（命令经 shell 执行，不要拼接不可信输入） |
| `--captcha-dir DIR` | 把每轮验证码图片保存到该目录（0600，便于人工查看/留存）；**单独给不会识别**，需配合前两者 |
| `--captcha-zoom N` | 人工识别时把图放大 N 倍再存（需本机 ImageMagick；unified 的 60×30 小图建议 6~8，人眼才认得清） |
| `--captcha-auto` | 自动选识别方式：内置识别器 → 外部 OCR（`tesseract`）→ 人工输入 |
| `--captcha-matcher` | 用内置识别器（专解 4399 的 60×30 四位验证码，需本机 ImageMagick 解码） |
| `--captcha-attempts N` | 最多重试轮数，默认 3；必须 ≥ 1 |

- legacy 模式同样可用（legacy 的 `--form-path` 默认是 `web`），验证码参数相同：

```bash
gen4399 --submit --yes --realname 张三 --idcard 460206194611192084
gen4399 --submit --form-path unified --yes --realname 张三 --idcard 460206194611192084
```

### 便捷脚本：每次运行获取一个账号

[scripts/make_account.py](scripts/make_account.py) 把「读身份 → 准备 → 提交 → 保存」串成一次运行，
**每次运行只处理一条身份、只提交一个账号**：

```bash
# 1) 身份文件（默认 ./sfz.txt；也可 --profile-file 指定）
printf '你的姓名|你的18位身份证号|你的QQ\n' > sfz.txt
chmod 600 sfz.txt

# 2) 默认 dry-run（不发注册 POST）
python scripts/make_account.py

# 3) 真实提交（仅限本人真实身份；成功/unknown 时追加到 accounts.json）
python scripts/make_account.py --yes

# 其它：web 路径 / 输出文件 / JSON
python scripts/make_account.py --yes --form-path web --output my_accounts.json
python scripts/make_account.py --json

# 排查 unknown/rejected：保存 4399 的脱敏响应（status/URL/可见文本/常见原因）
python scripts/make_account.py --yes --diagnose
python scripts/make_account.py --yes --diagnose --response-file resp.html

# 2.3.0：web 图形验证码（参数与 gen4399 submit 相同）
python scripts/make_account.py --yes --form-path web --captcha-prompt
python scripts/make_account.py --yes --form-path web \
    --captcha-cmd "tesseract stdin stdout -l eng --psm 8" --captcha-attempts 5
```

- 身份文件编码默认 UTF-8（失败自动回退 GB18030）；`sfz.txt` / `accounts.json`
  已在 `.gitignore` 中，避免 PII/账号误提交。
- **无效行容错**：身份文件里若有格式/校验不通过的行，脚本默认**跳过**并打印行号
  （例如 `行号：2`），继续用第 1 条有效身份；`--strict` 改为遇错立即退出；
  多行文件可用 `--index N` 指定用第 N 条有效身份。
- **图形验证码（2.3.0）**：脚本新增 `--captcha-prompt` / `--captcha-cmd` /
  `--captcha-dir` / `--captcha-attempts`（同样仅 web 路径生效）；不传时遇到
  `code=200` 直接返回 `captcha`、不会建号。
- 成功或被判定为 `unknown` 时会追加到 `accounts.json`（默认 0600，含明文密码，
  请妥善保管）；`unknown` 请先登录 `https://u.4399.com/` 确认，不要立刻重跑。
- **诊断**：`--diagnose` 会在注册 POST 后把响应打印到 stderr（状态码/最终 URL/
  可见文本/常见原因），并保存一份**脱敏后**的响应 HTML（默认 0600 的
  `registration-response-<时间戳>.html`）；它能识别 4399 的「4399提示」空壳页
  （`info_page` / `oauthValidation` / `fingerprint2`）并打印提示。该页在 2.4.0 前
  的 unified 流程里出现过；现在按 `UNIFIED_DROP_FIELDS` 剔除隐藏域后已可正常建号
  （启用 `UNIFIED_SEND_REALNAME=True` 时仍可能触发）。它不改变提交/判定行为，
  也不绕过风控；dry-run 没有 POST，因此没有可诊断的响应。
- 退出码：0 成功/dry-run；1 被拒/验证码/未知；2 参数/网络/配置错误。
- 脚本不会循环、不会重试注册 POST；每次运行都是一个独立的新账号准备流程。

### 流程简述

```
web 路径（2.2.0；2.3.0 增加图形验证码）
GET  https://web.4399.com/user/?_c=login&_a=checkUser&user=<登录名>
  └─ JSONP {state,data}，data = encryptCode
        ↓
encode_4399(password, encryptCode)  # DES/3DES-ECB + 零填充 + "0x"+hex
        ↓
POST https://web.4399.com/user/?_c=reg&jsoncallback=<cb>
  字段：cid=3000, login_name, login_password(密文), relogin_pwd(密文),
        qq, true_name, sfz, encrypt=1
        ↓
解析 JSONP {state, code, msg, validateState}
  state=true → success；code=200 → 图形验证码；code=360 → 手机验证码；
  msg → rejected；否则 unknown
        ↓ code=200 且提供了 captcha 回调（最多 captcha_attempts 轮）
GET  https://web.4399.com/util/?_c=code&t=reg&_=<ms>   # image/png，绑定 WEBSESSION
        ↓
captcha(image_bytes) → code（空串则跳过 verifyCode，换图进入下一轮）
        ↓
GET  https://web.4399.com/user/?_c=reg&_a=verifyCode&jsoncallback=<cb>&code=<code>
  ├─ {"state":true}  → 通过
  └─ {"state":false} → 错误：换图重试
        ↓
POST https://web.4399.com/user/?_c=reg&jsoncallback=<cb>（body 额外带 chk_code=<code>）
  └─ {"state":true,"code":300,"msg":"","validateState":"2","toUrl":"/hall.html"}
     + Cookie Puser/Pauth/Pauths/Pnick/ck_accname → success

unified 路径（2.1.0；2.4.0 剔除隐藏域后实测跑通）
GET  https://ptlogin.4399.com/ptlogin/regFrame.do
  ├─ 下发 USESSIONID Cookie（会话）
  └─ 解析 <form action> + 全部 hidden 隐藏域 + sec
        ↓
剔除 UNIFIED_DROP_FIELDS 的 13 个字段（布局/防沉迷/前端开关 + 协议开关）
        ↓
以剩余 hidden 为基线，覆盖 username / password / passwordveri / realname / idcard
（共 23 个字段；UNIFIED_SEND_REALNAME=False 时去掉 realname/idcard → 21 个）
        ↓
sec == "1" 时，用 AES 加密 password / passwordveri（+ realname / idcard）
        ↓
POST <form action>（即 /ptlogin/register.do）
        ↓
解析结果：isAutoRegSuccess → <div id="Msg"> → 登录 Cookie → info_page → 跳转
```

### 限制与成功判定

- **web 路径已实测建号成功（2026-11-08）**：完整走通了「`checkUser` 取 key →
  DES 加密 → 首次 POST 返回 `code=200` → 取验证码图/识别 → `verifyCode` 通过 →
  带 `chk_code` 重提交」，服务端返回
  `{"state":true,"code":300,"msg":"","validateState":"2","toUrl":"/hall.html"}`
  并下发 `Puser`/`Pauth`/`Pauths`/`Pnick`/`ck_accname` 登录 Cookie，账号真实创建成功。
  `SubmitResult.captcha_attempts` 记录的就是实测的验证码轮次。
- **unified 路径已实测建号成功（2026-11-08）**：`POST /ptlogin/register.do` 返回
  约 4 KB 的成功页，可见文本为「注册成功 请一定记住您注册的用户名和密码！
  用户名：… 密码：…」，脚本里 `msnger.emit("isAutoRegSuccess",true)`，并下发
  `Pauth`/`Uauth`/`Xauth`/`Puser`/`Pnick`/`Qnick`/`ck_accname`/`ptusertype`
  Cookie。实测账号用户名 `abkeq7xvesft`（密码不记录）。
- **空白「4399提示」页的根因**：把 `regFrame.do` 的 13 个隐藏域原样回传时，
  服务端会返回 `info_page` 空壳（无 `#Msg`、无登录 Cookie，注册不发生）——
  不是「风控封 IP」。2.4.0 起按 `UNIFIED_DROP_FIELDS` 剔除后同一套数据正常建号，
  实际提交 23 个字段（含实名）；详见上一节。
- **unified 默认提交实名**（`UNIFIED_SEND_REALNAME=True`）：`realname`/`idcard`
  与密码一起 AES 加密，`encrypted_fields` 有 4 个；账号建好即带实名信息。
  设为 `False` 可只提交用户名/密码（`encrypted_fields` 变 2 个）。
- **unified 成功页会回显明文密码**：库用 `_redact_text()` 把密码/身份证/姓名替换成
  `***` 后才写入 `message`，`SubmitResult.to_dict()` 与 CLI 输出都不含明文密码。
- 判定规则（两条路径均已实测成功；分类逻辑如下）：
  - `web`：`state=true` → `success`；`code=200` → `captcha`（图形验证码，
    传了 `captcha` 回调则自动重试）；`code=360` → `captcha`（手机验证码）；
    `msg` → `rejected`；出现登录 Cookie → `success`；非 JSONP 响应 → `unknown`。
  - `unified`：`isAutoRegSuccess=true` → `success`；`<div id="Msg">` 有文案 →
    `rejected`；新增登录 Cookie 或跳离 ptlogin → `success`；含「验证码」→
    `captcha`；`info_page` 空壳 → `unknown`（专用提示）；否则 `unknown`。
  **最终请以登录 `https://u.4399.com/` 为准**；`unknown` 不代表失败。
- **实名绑定限制**：已用于实名绑定的身份证再次注册会被服务端拒绝，实测返回
  `msg="姓名身份证不匹配"`（`kind="rejected"`）；姓名与身份证不一致时也是同一文案。
  本库无法仅凭响应区分「已绑定」与「实名不通过」，请只使用本人未绑定过 4399 的身份证。
- **两条路径的 PII 对比**：`web` 只有密码用 DES（页面协议要求，无现代机密性），
  `true_name`/`sfz` 以明文放在 HTTPS POST body（浏览器原流程是 JSONP GET 放 query；
  本库改用 POST body 以降低 URL 日志泄露风险）。`unified` 的姓名/身份证与密码
  都走 AES-256-CBC，**是两条路径里 PII 处理更好的那条**。
- **POST 不自动重试**：超时 / 5xx / 429 都直接抛错。若超时后不确定是否已建号，
  请先尝试登录确认，不要立即重跑 `--yes`。
- 图形验证码**不绕过、不破解**：只按协议拉图 → 调调用方回调 → `verifyCode` 校验；
  轮次用尽或未提供回调时返回 `captcha`，需人工处理（CLI 可用 `--captcha-prompt`）。
- 结果对象不含明文密码、身份证或 Cookie 值；`final_url` 已去掉 query/fragment，
  服务端文案若回显密码/身份证/姓名会被替换为 `***`。

## CLI

2.0 起提供两种用法，旧 flag 模式完全兼容；2.1.0 新增 `submit` 子命令，2.2.0 起支持 `web` 路径，
2.3.0 起 web 路径支持图形验证码（`--captcha-prompt` / `--captcha-cmd` / `--captcha-dir` /
`--captcha-attempts`），2.4.0 起 unified 已实测跑通并默认提交实名：

```bash
# 2.0 子命令（推荐）
gen4399 generate -n 20 -c 5
gen4399 check password "Abc12345"
gen4399 account --offline -c 3
gen4399 form fields web
gen4399 prepare --profile-file ids.txt --json
gen4399 profile check --profile-file ids.txt
gen4399 submit --realname 张三 --idcard ...         # 2.1.0+：默认 dry-run
gen4399 submit --form-path web --realname 张三 --idcard ...   # 2.2.0：web dry-run
gen4399 rules

# 旧 flag 模式（与 1.x 兼容）
gen4399 -n 20 -c 5
gen4399 --check "Abc12345"
gen4399 --submit --yes --realname 张三 --idcard ...                  # legacy 默认 web
gen4399 --submit --form-path unified --yes --realname 张三 --idcard ...
```

### 子命令

| 子命令 | 作用 |
|---|---|
| `generate` | 生成密码/用户名（`--kind password\|username`） |
| `check` | 校验（`check password VALUE` / `check username NAME`） |
| `account` | 生成账号+密码，`-c N` 批量 |
| `fetch` | 取服务端分配账号 |
| `available` | 查询用户名可注册性 |
| `form fields/check/build` | 表单字段 / 本地校验 / 填表清单 |
| `prepare` | 一键准备注册数据 |
| `submit` | 准备并提交注册（默认 dry-run，需 `--yes`；`web` / `unified`；2.3.0 起 web 支持图形验证码选项；2.4.0 起 unified 已实测跑通） |
| `profile check` | 校验身份 txt |
| `rules` / `version` | 规则版本 / 版本 |

### 全局增强

| 参数 | 说明 |
|---|---|
| `--json` | 机器可读输出 |
| `--offline` | 跳过在线查重（`fetch`/`available` 等必须联网的命令会报错；`submit` 的 dry-run/提交仍需联网，`--offline` 只跳过用户名查重） |
| `--output DIR` | 结果写成 JSON 文件（0600，敏感值默认打码） |
| `--password-length` / `--username-length` | 明确区分两种长度 |
| `--retries` / `--retry-delay` / `--max-total-timeout` | 远程重试与总预算 |
| `--min-interval` | 批量远程调用之间的间隔（秒） |
| `--show-pii` | 显示明文身份证/密码/QQ（会打印警告） |
| `--rules-version` | 打印内置规则快照版本 |
| `-v/--verbose` | 重试等调试日志（不含 PII） |

```bash
python -m gen4399                            # 生成 1 个 16 位密码
python -m gen4399 -n 20 -c 5
python -m gen4399 -p lg -s gz -n 20
python -m gen4399 -u                         # 生成账号名
python -m gen4399 -u -n 16 -c 3
python -m gen4399 --check "Abc12345"         # 退出码 0/1
python -m gen4399 --check-username "abc12345"
python -m gen4399 --entropy -p abc           # 只算熵
python -m gen4399 --fetch-username           # 取服务端分配账号
python -m gen4399 --fetch-username 3 -p u    # 批量 + 前缀
python -m gen4399 -u --verify                # 本地生成 + 在线查重
python -m gen4399 --account                  # 账号名+密码，默认查重
python -m gen4399 --account --no-verify -n 20 --username-length 10
python -m gen4399 --form-fields web           # 查看注册表单字段
python -m gen4399 --form-fields unified
python -m gen4399 --check-form NAME PW --realname 张三 --idcard 460206194611192084
python -m gen4399 --build-form NAME PW --realname 张三 --idcard ... --show-pii
python -m gen4399 --prepare --realname 张三 --idcard 460206194611192084 -p u -s gz
python -m gen4399 --prepare --no-verify --realname 张三 --idcard ...
python -m gen4399 --prepare --no-verify --profile-file ids.txt   # 批量
python -m gen4399 --check-available "abc12345"
python -m gen4399 --timeout 3 --check-available "abc12345"
python -m gen4399 submit --realname 张三 --idcard ...              # 2.1.0+：dry-run
python -m gen4399 submit --realname 张三 --idcard ... --yes        # 2.1.0+：真实提交（默认 unified）
python -m gen4399 submit --form-path web --realname 张三 --idcard ... --yes   # 2.2.0：web 真实提交
python -m gen4399 submit --form-path web --realname 张三 --idcard ... --yes --captcha-prompt   # 2.3.0：人工过图形验证码
```

- `-n` 是**密码**总长度（默认 16）；自动生成用户名长度用 `--username-length`（默认 12）。
  `--account` 与 `--prepare` 语义一致。
- `--show-pii` 让 `--build-form` 显示完整身份证号/密码/QQ；默认全部打码。
- 远程命令失败统一退出码 **2**（不会再抛 traceback）；校验失败退出码 **1**；
  `submit` 的 **1** 表示被拒/未知/需要验证码，**0** 表示成功或 dry-run。
- 安装后也可直接用 `gen4399` 命令。

## 安全与合规

- **默认不提交注册**：`prepare` / `form build` 只准备数据；真实提交必须显式
  `submit_registration(..., dry_run=False)` 或 `gen4399 submit --yes`；
  2.2.0 起 `web` / `unified` 两条路径都支持；2.3.0 起 web 的图形验证码也必须由
  调用方提供 `captcha` 回调（人工/OCR），**库不内置破解、不绕过风控**；
  2.4.0 起 unified 已实测跑通，且**默认提交实名**（见下）。
- **实名限制**：已用于实名绑定的身份证再次注册会被服务端拒绝（实测 `姓名身份证不匹配`）；
  姓名与身份证不一致同样会被拒。请只使用**本人**、未绑定过 4399 的真实身份信息；
  使用他人身份可能违法，也违反 4399 用户协议。
  不要批量注册他人账号。
- 真实提交只把字段发往 **4399 官方端点**（`ptlogin.4399.com` /
  `web.4399.com`），库不经过任何第三方服务器。`unified` 默认发送
  `realname`/`idcard`（`UNIFIED_SEND_REALNAME=True`），与 `password`/
  `passwordveri` 一起走页面同款 AES-256-CBC；`web` 路径只有密码用页面同款 DES，
  `true_name`/`sfz` 是明文在 HTTPS POST body（比浏览器原 JSONP GET 的 query
  更不易进 URL 日志，但仍是明文）。AES 口令/DES 算法均公开在前端 JS 中，
  **都不提供机密性保护**，只是协议要求。
- 确实不想提交实名时再把 `UNIFIED_SEND_REALNAME` 设为 `False`；默认是提交的
  （AES 加密，且实测可正常建号）。
- `--yes` 前请先跑一次 dry-run；POST **不自动重试**，超时后先确认是否已建号。
- 身份文件建议 `chmod 600`（库会警告过宽权限）；`--show-pii`/`--output --show-pii`
  会输出明文，注意屏幕共享与日志。
- 远程接口有频率限制：遵守 `--min-interval`、不要高频轰炸；库重试已带抖动与封顶。
- 日志/错误信息不含密码与完整身份证号，`repr()` / `SubmitResult.to_dict()` 默认脱敏。
- 文档与测试中的身份证号均为**测试夹具**（非真实个人信息），请勿用于真实注册。

## FAQ

常见问题（密码能否预校验、fetch 为什么限流、能不能自动提交、验证码怎么办、
dry-run 联不联网……）见 [docs/faq.md](docs/faq.md)。

## 规则来源

- 4399 前端 `validation.js` 的 `CheakPWD()` / `CheakUsername()` / `CheckRealname()` / `__checkIdcard()`
- `https://web.4399.com/user/reg.php` 注册页与其 `web_reg.js` / `action.js`（`encode_4399` DES 加密）
- `https://u.4399.com/register.html`（ptlogin 统一注册面板）

密码：长度 6~20、只允许字母和数字、不能纯数字/纯小写/纯大写。

用户名：长度 6~20、只允许字母和数字、允许纯数字。

## 开发

```bash
pip install -e ".[dev]"
python -m pytest                 # 测试
python -m pytest --cov=gen4399   # 覆盖率（阈值 90%）
ruff check .                     # lint
python -m pytest --doctest-modules gen4399 -q   # 文档示例
mypy gen4399                                     # 类型检查（观察项）
python scripts/verify_rules.py                   # 4399 规则冒烟检查
python -m build && python -m twine check dist/*  # 打包检查
```

版本历史见 [CHANGELOG.md](CHANGELOG.md)，许可证为 [MIT](LICENSE)。

项目全貌（架构、规则、API、质量与已知问题）见 [docs/project-overview.md](docs/project-overview.md)。
