# gen4399 WebUI · Android（Kotlin / Gradle）

注册逻辑跑在 **Termux 里的 Python 服务**上（`python -m gen4399.webui`），
这个 APK 只是把那个页面装进 WebView —— 连不上时弹框让你改服务器地址。

## 工具链（全部在 proot Ubuntu 里）

| 组件 | 版本 | 位置 |
|---|---|---|
| Gradle | **9.7.0** | `/opt/gradle-9.7.0/gradle-9.7.0/bin/gradle` |
| JDK | 21 | `/usr/lib/jvm/java-21-openjdk-arm64` |
| AGP | **9.4.0** | Gradle 缓存（离线可用） |
| Kotlin | **2.4.20** | 通过 `kotlin { compilerVersion }` 指定 |
| Android SDK | **37**（`/root/android-sdk`，platforms/android-37） | `local.properties` |
| aapt2 | `36.1.0` | `/root/android-sdk/build-tools/36.1.0/aapt2`（box64 包装） |

## 构建

```bash
proot-distro login ubuntu -- bash -lc '
  cd /data/data/com.termux/files/home/lead-workspace/ports/android &&
  export JAVA_HOME=/usr/lib/jvm/java-21-openjdk-arm64 &&
  /opt/gradle-9.7.0/gradle-9.7.0/bin/gradle assembleDebug --no-daemon
'
# 产物：app/build/outputs/apk/debug/app-debug.apk
```

构建要点（都写进配置里了）：

- `gradle.properties` → `android.aapt2FromMavenOverride=/root/android-sdk/build-tools/36.1.0/aapt2`
  （本机 aapt2 是 box64 跑的 x86_64 二进制，不能让 AGP 去 Maven 下载）
- `local.properties` → `sdk.dir=/root/android-sdk`
- **AGP 9 内置 Kotlin**：不能再加 `org.jetbrains.kotlin.android` 插件（会被拒绝）
- **Kotlin 2.4.20**：`app/build.gradle` 里 `kotlin { compilerVersion = '2.4.20' }`。
  该属性是 Kotlin 的 experimental API，Kotlin DSL 需要 opt-in，所以 app 模块用 Groovy DSL；
  同时根 `build.gradle.kts` 把整条 Kotlin 工具链强制对齐到 2.4.20
  （AGP 9.4.0 自带的 KGP 是 2.2.10，不对齐会报 Build Tools API Version Mismatch）

## 验证

```
package: io.gen4399.webui  versionName 3.9.0
compileSdkVersion 37  minSdkVersion 23  targetSdkVersion 37
uses-permission: android.permission.INTERNET
签名：Android Debug（可直接安装）
```

aapt2 启动时会打印一行 `BOX64: Symbol nftw not found`——box64 转译时的无害告警，构建继续。

## 与 `../android-manual/` 的区别

那边是**不用 Gradle** 的手工构建（javac + d8 + aapt2 + apksigner，Java 版，12KB），
适合没有 Android SDK / 网络的环境；这边是标准 Gradle 工程（Kotlin 版）。
两份代码功能一致，任选其一即可。
