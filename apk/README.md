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

## 架构：协议内核是 C（libgen4399.so）

加密、规则、表单解析、载荷组装、响应判定全部在 **C 库**里，Kotlin 只做界面和 HTTP。

```
app/src/main/cpp/          ← 直接复用 ports/c 的实现
├── crypto_self.c           AES-256-CBC / DES-EDE3-ECB / MD5 / Base64（自带实现，不依赖 OpenSSL）
├── rules.c                 生成/校验、身份证 GB 11643
├── payload.c               form URL、隐藏域解析、unified 载荷组装（含 13 个剔除字段）、结果判定
├── jni.c                   JNI 桥（Java_io_gen4399_app_Native_*）
├── gen4399.h / payload.h
└── CMakeLists.txt          → libgen4399.so
```

| Kotlin | 作用 |
|---|---|
| `Native.kt` | `System.loadLibrary("gen4399")` + external 声明 |
| `Rules.kt` | 薄封装，全部转发到 C |
| `Protocol.kt` | 只用 C 做加密/组装/判定；HTTP 用 `HttpURLConnection`，Cookie/Referer 手工维护 |
| `MainActivity.kt` | Compose UI（身份/设置/运行 + 验证码弹窗） |

`libgen4399.so` 只有 32KB，`readelf` 显示无外部依赖（不链 OpenSSL、不链 libcurl）。

### 已验证（真机同款 .so）

从构建出的 APK 里提取 `lib/arm64-v8a/libgen4399.so`，用 ctypes 直接调用：

```
OK   encode4399('Abc12345','5c43e3')     = 0xfc88a0c93a204a36
OK   encode4399('hello world','abc')     = 0xd22da7b2be6ea575df93303f8204c05a
OK   encode4399('P@ss!','1234567890abcdef') = 0x9b5112a937ab4658
AES: C 加密 → Python decrypt_aes 解出「王五的密码123」
载荷: 9 个字段，fCaptcha / mainDivId 已剔除，password 为 AES 密文
```

## 与其它版本的关系

- **WebUI**（`gen4399/webui.py`，Python）与这个 APK **互不影响**，各自独立；
- Node / C 移植版在 `ports/node`、`ports/c`，与本 APK 也无依赖关系。

## 已知取舍

- **Material 3 没有 1.9.0**：仓库里最新是 1.5.0-rc01，稳定线 1.4.x。
  BOM 2026.08.00 把 material3 定在 1.4.0；如需覆盖，加
  `implementation 'androidx.compose.material3:material3:1.5.0-rc01'`（会连带升级 compose-ui）。
- `minSdk 24`：Compose 要求。
- 未做代理池/验证码自动识别（APK 里以人工填图为准）。
