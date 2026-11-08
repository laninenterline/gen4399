# gen4399 · Node 版

Python 版（仓库根目录）的 Node 移植，**零依赖**（只用 `node:crypto` + 内置 `fetch`）。

```bash
node cli.mjs generate -n 12          # 生成密码（-n 长度，-c 数量，--username 生成用户名）
node cli.mjs check password Abc12345 # 校验
node cli.mjs idcard 110105198803121893
node cli.mjs fields unified          # 打印字段与剔除清单
node cli.mjs login 账号 --password 密码
node cli.mjs submit 账号 密码 --realname 姓名 --idcard 号码 --dry-run   # 默认 dry-run
node cli.mjs submit 账号 密码 --realname 姓名 --idcard 号码 --yes       # 真正提交
node --test test.mjs                 # 11 个用例
```

| 模块 | 内容 |
|---|---|
| `rules.mjs` | 密码/用户名生成（拒绝采样避免取模偏置）、校验、熵 |
| `identity.mjs` | 姓名 / 身份证（GB 11643 校验码）/ QQ |
| `crypto.mjs` | CryptoJS 口令模式 AES-256-CBC、`encode_4399`（DES/3DES-ECB） |
| `client.mjs` | Cookie 会话、表单解析、unified/web 提交、登录 |

## 与 Python 版的关系

- **协议逐字节一致**：`encode_4399` 三个夹具与 Python 输出完全相同；
  Node 加密的 AES 密文能被 Python `decrypt_aes` 解开（反之亦然）。
- 差异：Node 版不含代理池、验证码识别、批量编排、账号体检——这些只在 Python 版维护。
- OpenSSL 3 关掉了单 DES，`encode_4399` 用「同一把 key 重复三遍的三重 DES」等价实现。

## 注意

仅用于本人账号；`submit` 默认 dry-run，加 `--yes` 才真正发 POST。
