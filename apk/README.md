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
# 调试包
proot-distro login ubuntu -- bash -lc '
  cd /data/data/com.termux/files/home/lead-workspace/apk &&
  export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-arm64 &&
  /opt/gradle-9.7.0/gradle-9.7.0/bin/gradle assembleRelease --no-daemon'
# 产物 app/build/outputs/apk/release/app-release.apk（已签名）
```

**release 签名**：`keystore.properties`（不入库）指向自己的 keystore：

```properties
storeFile=keystore/gen4399-release.jks
storePassword=...
keyAlias=gen4399
keyPassword=...
```

没有这个文件时 release 不签名（`assembleRelease` 仍能出未签名包）。

首次生成 keystore：

```bash
keytool -genkeypair -keystore keystore/gen4399-release.jks -alias gen4399 \
  -keyalg RSA -keysize 2048 -validity 10000
```

## 图标

`art/icon-source.jpg` 是原图（828×808），构建前用 ImageMagick 生成各密度：

```bash
magick art/icon-source.jpg -gravity center -crop 808x808+0+0 +repage art/icon-square.png
# mdpi 48 / hdpi 72 / xhdpi 96 / xxhdpi 144 / xxxhdpi 192
# 另外生成 720×720 前景图给 adaptive icon（API 26+，底色 #8A8A8A）
```

产物：`mipmap-*/ic_launcher.png`、`ic_launcher_round.png`、`ic_launcher_foreground.png`、
`mipmap-anydpi-v26/ic_launcher.xml`。

## 验证码自动识别

两条通道都自动识别，认不出才弹窗（`CaptchaAuto.solve()` 按尺寸分派）：

| 通道 | 尺寸 | 方案 | 实测 |
|---|---|---|---|
| unified | 60×30 | `matcher.c` + 25 个字形模板（包含判据） | 模板自测 100/100 |
| web | 150×45 | `web_matcher.c` 骨架 + chamfer + 414 字形字库 | 整码 96.1% / 字符 99.0% |

图片解码交给平台（`BitmapFactory`），识别全在 C，零外部依赖。

## 大文件与断点续跑

25MB 的 `sfz.txt` 有 80 多万行，不可能一次读进内存：

- `SfzFile.loadPage(uri, offset, 2000)` **流式读一页**，返回 `nextOffset` / `eof`
- 跑完一批点「继续下一批」，断点存 `SharedPreferences`，重启 App 也能续
- 结果列表跨批次累积，最后统一导出
- 分页正确性：5000 行切 8 批，无丢行/重复/乱序（固定样本验证）

## 导出格式

| 格式 | 内容 |
|---|---|
| CSV | `index,username,password,kind,ok,message,path` |
| JSON | 对象数组，字段同上 |
| TXT | `账号\|密码\|结果`，每行一条 |

## 功能

- **身份**：粘贴或 `导入 sfz.txt`（SAF 文件选择器），按 `姓名|身份证[|QQ]` 解析，
  逐条显示身份证校验码 / 姓名格式是否通过
- **设置**：通道（unified / web）、生成数量、密码长度、用户名前缀/后缀、
  账号间隔、dry-run 开关
- **运行**：后台协程逐个注册，实时进度条 + 结果列表 + 日志；
  遇到图形验证码**弹出图片**让人填（unified 的 `inputCaptcha` 与 web 的 `code=200` 都支持）
- **导出**：SAF 保存 CSV（账号 / 密码 / 结果 / 说明）

## 架构：全部逻辑在 C（libgen4399.so），Kotlin 只管显示

| 层 | 负责 | 位置 |
|---|---|---|
| **C 内核** | 账号生成、AES/DES 加密、表单解析、载荷组装、注册流程、验证码重试、节奏控制、结果判定、Cookie 罐 | `app/src/main/cpp/` |
| **Kotlin** | Compose 界面 + 一个 `transport()`（发 HTTP，因为 Android 只有平台层有 TLS） | `MainActivity.kt` / `HttpTransport.kt` |

`Native.runBatch(identities, path, count, prefix, suffix, intervalSec, dryRun, sendRealname, callback)`
把整批任务交给 C；C 通过 `Callback.transport` 发请求、`Callback.askCaptcha` 要验证码、
`Callback.onProgress` 回传每个账号的结果。Kotlin 端没有循环、没有重试、没有判定。

```
app/src/main/cpp/          ← 直接复用 ports/c 的实现
├── crypto_self.c           AES-256-CBC / DES-EDE3-ECB / MD5 / Base64（自带实现，不依赖 OpenSSL）
├── rules.c                 生成/校验、身份证 GB 11643
├── payload.c               form URL、隐藏域解析、unified 载荷组装（含 13 个剔除字段）、结果判定
├── agent.c                 批量编排：身份解析、账号生成、cookie 罐、两条通道、验证码重试、间隔
├── jni.c                   基础 JNI（生成/校验/加密/载荷/判定）
├── jni_agent.c             runBatch 的 JNI 桥（把 Callback 适配成 C 的 hooks）
├── gen4399.h / payload.h
└── CMakeLists.txt          → libgen4399.so
```

| Kotlin | 作用 |
|---|---|
| `Native.kt` | `loadLibrary("gen4399")` + external 声明 + `Callback` 接口 |
| `HttpTransport.kt` | 唯一非界面的 Kotlin 代码：把参数发出去、回传 `[状态码, Set-Cookie, body]` |
| `Rules.kt` | 校验用的薄封装（转发到 C，供界面提示） |
| `Model.kt` | `Identity` / `SubmitResult` 两个数据类 |
| `MainActivity.kt` | Compose UI（身份/设置/运行 + 验证码弹窗），不含任何流程逻辑 |

`libgen4399.so` 只有 32KB，`readelf` 显示无外部依赖（不链 OpenSSL、不链 libcurl）。

### 已验证（真机同款 .so）

从构建出的 APK 里提取 `lib/arm64-v8a/libgen4399.so`，用 ctypes 直接调用：

```
OK   encode4399('Abc12345','5c43e3')     = 0xfc88a0c93a204a36
OK   encode4399('hello world','abc')     = 0xd22da7b2be6ea575df93303f8204c05a
OK   encode4399('P@ss!','1234567890abcdef') = 0x9b5112a937ab4658
AES: C 加密 → Python decrypt_aes 解出「王五的密码123」
载荷: 9 个字段，fCaptcha / mainDivId 已剔除，password 为 AES 密文
JNI : Java_io_gen4399_app_Native_runBatch 符号存在
```

C 侧的编排逻辑还有一份**主机自测**（`ports/c/src/agent_selftest.c`）：
用假 transport 模拟「表单 → 验证码 → 成功」的服务端行为，验证重试与 dry-run：

```
captcha: 9 字节图片，回答 ABCD
progress: [1/1] rhy1yj0en5g0 -> success (ok=1) 注册成功（isAutoRegSuccess=true）
[OK] 编排跑通并判定 success
[OK] 验证码重试生效
[OK] dry-run 只发了一次 GET
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
