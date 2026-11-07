# gen4399

生成与校验**符合 4399 注册规则**的密码与账号名。零依赖（只用标准库）。

除了本地生成，还封装了 4399 官方的两个登录接口：

- `fetch_suggested_username()` —— 取服务端「为您分配的账号」
- `check_username()` / `is_username_available()` —— 查询用户名是否还能注册

## 安装

```bash
pip install -e .
```

或者不安装，直接在本目录下 `import gen4399`。

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

is_valid("Abc12345")            # True
validate("123456")              # [Violation(code='all_digits', ...)]

# 账号名（用户名）
generate_username()             # 12 位小写字母+数字
generate_username(length=16)
generate_username(prefix="u", suffix="gz")
generate_usernames(5)           # 一次生成 5 个

validate_username("abc12345")   # []
validate_username("4257220954") # []（纯数字允许，4399 自动账号就是纯数字）
validate_username("abc_12345")  # [Violation(code='charset', ...)]
```

> 用户名规则：长度 6~20、只允许字母和数字、允许纯数字、不允许 `_` `@` 中文。
> 生成默认用小写字母+数字（36 字符集），更好读。

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

# 2) 查询用户名是否还能注册（官方 isExist.do）
res = check_username("abc12345")
res.available     # True / False
res.message       # '0' 或 '用户名已被注册' 等

is_username_available("abc12345")   # True / False
```

## 自动探测可用性

```python
from gen4399 import (
    generate_available_username,   # 本地生成 + 服务端确认可注册
    generate_account,              # 一键生成 Account(username, password)
)

name = generate_available_username()      # 保证 isExist.do 返回 0
acc = generate_account()                  # 默认已查重账号名
print(acc.username, acc.password)
```

> 账号名可以「预探测」（官方 `isExist.do`）；**密码无法预探测**——
> 4399 没有密码校验接口，只有注册提交时才校验。
> 密码侧只能保证通过公开规则（本库 `validate()` 在本地保证）。

## 注册表单（字段定义 + 本地校验）

覆盖两条注册路径，**只做本地校验，不代你提交注册**：

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

| 路径 | 页面 | 提交地址 |
|---|---|---|
| `web` | https://web.4399.com/user/reg.php | `POST /user/?_c=reg` |
| `unified` | https://u.4399.com/register.html | `POST /ptlogin/register.do` |

单独校验字段也可用：`validate_realname()` / `validate_idcard()` / `validate_qq()`。

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

> 身份信息只在你本机内存中使用，本库不会发送到任何服务器。

### 一键准备注册数据

```python
from gen4399 import RegistrationProfile, prepare_registration

profile = RegistrationProfile("张三", "460206194611192084", qq="123456789")
bundle = prepare_registration(profile)        # 生成用户名 → 查重 → 生成密码 → 校验 → 组装字段

print(bundle.username)        # 已查重可用
print(bundle.password)        # 合规密码
print(bundle.fields)          # 直接照着填的表单字段
print(bundle.as_text())       # 可读清单（身份证/密码默认打码）

# 自定义用户名前后缀（计入总长度，至少留 1 位随机）
bundle = prepare_registration(profile, prefix="u", suffix="gz")

# 拿不到网络时也可离线准备
bundle = prepare_registration(profile, verify_username=False)
```

> **这个函数不会提交注册**。它把能自动化的部分（生成、查重、校验、组字段）全做完，
> 最后一步请在 `bundle.url` 页面手动提交。

对应的 `RemoteError` 子类：`RemoteTimeoutError`、`RemoteHTTPError`、`RemoteParseError`。

> 长度 `-n` 是**总长度**，前缀和后缀都算在内；固定部分越长，随机部分越短。

## CLI

```bash
python -m gen4399
python -m gen4399 -n 20 -c 5
python -m gen4399 -p lg
python -m gen4399 -s gz
python -m gen4399 -p lg -s gz -n 20
python -m gen4399 -u                       # 生成账号名
python -m gen4399 -u -n 16 -c 3
python -m gen4399 --check "Abc12345"
python -m gen4399 --check-username "abc12345"
python -m gen4399 --fetch-username          # 取服务端分配账号
python -m gen4399 --fetch-username -p u     # 加前缀
python -m gen4399 --fetch-username 3 -p u -s gz
python -m gen4399 -u --verify               # 生成账号名并在线查重
python -m gen4399 --account                 # 生成账号名+密码，自动查重
python -m gen4399 --account --no-verify     # 离线，跳过查重
python -m gen4399 --form-fields web          # 查看注册表单字段
python -m gen4399 --form-fields unified
python -m gen4399 --check-form NAME PW --realname 张三 --idcard 460206194611192084
python -m gen4399 --build-form NAME PW --realname 张三 --idcard ... --show-pii
python -m gen4399 --prepare --realname 张三 --idcard 460206194611192084 -p u -s gz
python -m gen4399 --check-available "abc12345"
python -m gen4399 --entropy -p abc
```

安装后也可直接用 `gen4399` 命令。

## 规则来源

- 4399 前端 `validation.js` 的 `CheakPWD()`
- `https://web.4399.com/user/reg.php` 注册页提示

密码：长度 6~20、只允许字母和数字、不能纯数字/纯小写/纯大写。

用户名：长度 6~20、只允许字母和数字、允许纯数字。
