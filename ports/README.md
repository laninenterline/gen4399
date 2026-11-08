# 移植版：Node 与 C

Python 版（仓库根目录）是主实现，功能最全。这里放两个移植版，覆盖**注册/登录协议的核心**：

| 版本 | 目录 | 依赖 | 能力 |
|---|---|---|---|
| Node | [node/](node/) | 零依赖（`node:crypto` + 内置 `fetch`） | 生成/校验、身份校验、AES/DES、unified+web 提交、登录 |
| C | [c/](c/) | OpenSSL + libcurl | 同上（提交与登录都在，验证码只判断状态不做识别） |

```bash
# Node
cd ports/node && node --test test.mjs && node cli.mjs generate -n 12

# C
cd ports/c && make && make test && ./build/gen4399 generate -n 12
```

## 跨语言一致性（已验证）

| 检查 | 结果 |
|---|---|
| `encode_4399('Abc12345','5c43e3')` | Python / Node / C 三边都是 `0xfc88a0c93a204a36` |
| `encode_4399('hello world','abc')` | 三边都是 `0xd22da7b2be6ea575df93303f8204c05a` |
| AES 密文互解 | Node 加密 → Python 解密 ✅；C 加密 → Python 解密 ✅ |
| 身份证校验 | 三边对 `110105198803121893` 都通过、对错误校验码都拒绝 |

## Android App

原生 Compose 应用在仓库根目录的 [../apk/](../apk/)，与 WebUI 互相独立，
不走 ports/ 这套移植路线（它自己实现协议）。

## 只有 Python 版才有的

代理池 / 粘性代理 / 随机 UA、验证码识别（unified 模板 + web 自学习字库）、
批量注册编排、账号体检与导出、运行期 `configure()`。

## 为什么 C 用三重 DES 代替单 DES

OpenSSL 3 默认关闭了单 DES（`des-ecb` 会报 `unsupported`）。把同一把 8 字节 key
重复三遍做 `des-ede3`，数学上等价于单 DES，能与页面 JS 的输出逐字节对齐。
