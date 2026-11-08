# gen4399 · C 版

Python 版核心能力的 C11 移植，依赖 **OpenSSL**（AES/DES/MD5）与 **libcurl**（HTTP）。

```bash
make            # 生成 build/gen4399
make test       # 自测（DES 与 Python 版逐字节比对）
./build/gen4399 generate -n 12          # 生成密码（--username 生成用户名）
./build/gen4399 check password Abc12345
./build/gen4399 idcard 110105198803121893
./build/gen4399 encode4399 'Abc12345' '5c43e3'
./build/gen4399 aes '明文'              # CryptoJS 口令模式
./build/gen4399 fields
./build/gen4399 submit 账号 密码 --realname 姓名 --idcard 号码 --dry-run
./build/gen4399 submit 账号 密码 --realname 姓名 --idcard 号码 --yes
./build/gen4399 login 账号 --password 密码
```

## 已实现

| 能力 | 说明 |
|---|---|
| 生成/校验 | 密码与用户名（拒绝采样，避免取模偏置） |
| 身份校验 | 姓名 / 身份证（GB 11643 校验码 + 生日）/ QQ |
| 加密 | AES-256-CBC（CryptoJS `Salted__` + EVP_BytesToKey）、`encode_4399` |
| 提交 | unified（拉表单 → 剔除 13 个隐藏域 → AES 加密 → POST）与 web（checkUser → DES → POST） |
| 登录 | `login.do?v=1`，按会话里的 `Pauth/Uauth/...` 判断成功 |
| dry-run | 默认只组装字段不发 POST |

## 复用给 Android

`crypto_self.c`（无 OpenSSL 的 AES/DES/MD5/Base64）与 `payload.c`（表单/载荷/判定）
会被 `apk/app/src/main/cpp/` 直接拿去编成 `libgen4399.so`，
APK 的协议内核就是这份 C 代码。

## 与 Python 版的关系

- `make test` 里的三个 `encode_4399` 夹具直接来自 Python 版，输出必须完全一致；
- C 加密的 AES 密文可用 Python `gen4399._aes.decrypt_aes` 解开（已验证）；
- 不含代理池 / 验证码识别 / 批量编排 / 账号体检。

## 已知限制

- 验证码只识别「需要验证码」这个状态，不做图像识别（返回 `kind="captcha"`）；
- OpenSSL 3 关闭了单 DES，`encode_4399` 用「同一把 key 重复三遍的三重 DES」等价实现；
- 服务端限流（`请稍后再试~` / HTTP 202）统一归类为 `throttled`。
