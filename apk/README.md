# gen4399 · Android App（Kotlin + Jetpack Compose）

**独立应用**：不依赖 WebUI，自己实现 4399 的注册协议（AES/DES、表单、Cookie）。

| 组件 | 版本 |
|---|---|
| Gradle | **9.7.0**（`/opt/gradle-9.7.0/gradle-9.7.0/bin/gradle`） |
| AGP | **9.4.0** |
| Kotlin | **2.4.20** |
| compileSdk / targetSdk | **37** |
| Compose BOM | **2026.08.00**（→ compose-ui **1.12.0**） |
| Material 3 | **1.4.0**（BOM 决定，见下方说明） |
| aapt2 | `/root/android-sdk/build-tools/36.1.0/aapt2`（box64 包装） |
| SDK | `/root/android-sdk` |

## 构建

```bash
proot-distro login ubuntu -- bash -lc '
  cd /data/data/com.termux/files/home/lead-workspace/apk &&
  export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-arm64 &&
  /opt/gradle-9.7.0/gradle-9.7.0/bin/gradle assembleDebug --no-daemon'
# 产物 app/build/outputs/apk/debug/app-debug.apk
```

## 功能

- **身份**：粘贴或 `导入 sfz.txt`（SAF 文件选择器），按 `姓名|身份证[|QQ]` 解析，
  逐条显示身份证校验码 / 姓名格式是否通过
- **设置**：通道（unified / web）、生成数量、密码长度、用户名前缀/后缀、
  账号间隔、dry-run 开关
- **运行**：后台协程逐个注册，实时进度条 + 结果列表 + 日志；
  遇到图形验证码**弹出图片**让人填（unified 的 `inputCaptcha` 与 web 的 `code=200` 都支持）
- **导出**：SAF 保存 CSV（账号 / 密码 / 结果 / 说明）

## 协议实现

| 文件 | 内容 |
|---|---|
| `Crypto.kt` | CryptoJS 口令模式 AES-256-CBC（EVP_BytesToKey+MD5、`Salted__`）、`encode_4399`（DESede-ECB，K1=K2=K3 等价单 DES） |
| `Rules.kt` | 密码/用户名生成与校验、身份证（GB 11643 校验码）、姓名、QQ |
| `Protocol.kt` | 会话（Cookie/Referer/UA）、unified 表单解析 + 13 个隐藏域剔除 + 加密、web checkUser→DES→提交、结果判定（success/captcha/throttled/rejected/unknown） |
| `MainActivity.kt` | Compose UI（Tab：身份/设置/运行 + 验证码弹窗） |

## 与其它版本的关系

- **WebUI**（`gen4399/webui.py`，Python）与这个 APK **互不影响**，各自独立；
- Node / C 移植版在 `ports/node`、`ports/c`，与本 APK 也无依赖关系。

## 已知取舍

- **Material 3 没有 1.9.0**：仓库里最新是 1.5.0-rc01，稳定线 1.4.x。
  BOM 2026.08.00 把 material3 定在 1.4.0；如需覆盖，加
  `implementation 'androidx.compose.material3:material3:1.5.0-rc01'`（会连带升级 compose-ui）。
- `minSdk 24`：Compose 要求。
- 未做代理池/验证码自动识别（APK 里以人工填图为准）。
