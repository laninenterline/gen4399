# gen4399 WebUI · Android 外壳

注册逻辑跑在 **Termux 里的 Python 服务**上（`python -m gen4399.webui`），
这个 APK 只是把那个网页装进 WebView —— 连不上时弹框让你改服务器地址。

```
app/src/main/AndroidManifest.xml
app/src/main/java/io/gen4399/webui/MainActivity.java
build.sh              # 不依赖 Gradle/Android Studio 的本地构建
gen4399-webui.apk     # 构建产物（12.7KB，已签名）
```

## 构建

需要 `javac`、`d8`、`aapt2`、`apksigner`、`keytool` 和一个 `android.jar`：

```bash
cd ports/android
ANDROID_JAR=/path/to/android.jar ./build.sh
```

默认会去找 `~/bjg/re_work/tools/aurora_probe/build/android.jar`。

## 安装与使用

1. 手机装 [Termux]，把 `lead-workspace` 放进去，执行：
   ```bash
   cd lead-workspace && python -m gen4399.webui --port 8765
   ```
2. 安装 `gen4399-webui.apk`，打开即可看到 WebUI。
3. 连不上时（比如端口改了）会弹框，改成 `http://127.0.0.1:8765/` 后重连。

## 说明

- `minSdkVersion 21` / `targetSdkVersion 22`：手里这个 `android.jar` 是旧版框架，
  没有 `android:usesCleartextTraffic` 属性；target 22 时默认就允许明文 HTTP，
  所以 WebView 能直接访问 `127.0.0.1`。私有分发够用，上架商店则不行。
- 没有用 `@JavascriptInterface`（API 17+ 才有），改用原生菜单 + 对话框设置地址。
- 页面里的“真实提交”需要服务端未加 `--dry-run-only`。
