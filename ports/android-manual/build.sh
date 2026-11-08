#!/data/data/com.termux/files/usr/bin/bash
# 不依赖 Android Studio / Gradle 的本地构建。
# 需要：javac、d8、aapt2、apksigner、keytool（Termux 都有），以及一个 android.jar。
set -e
cd "$(dirname "$0")"

OUT=build
APK_NAME=gen4399-webui.apk
ANDROID_JAR="${ANDROID_JAR:-$HOME/bjg/re_work/tools/aurora_probe/build/android.jar}"

mkdir -p "$OUT"
if [ ! -f "$ANDROID_JAR" ]; then
  echo "错误：找不到 android.jar（用 ANDROID_JAR=/path/to/android.jar 指定）" >&2
  exit 1
fi

echo "[1/6] javac"
rm -rf "$OUT/classes" && mkdir -p "$OUT/classes"
javac --release 8 -nowarn -cp "$ANDROID_JAR" -d "$OUT/classes" \
  $(find app/src/main/java -name "*.java") 2>&1 | grep -v "bootstrap class path" || true

echo "[2/6] d8"
rm -rf "$OUT/dex" && mkdir -p "$OUT/dex"
d8 --min-api 21 --lib "$ANDROID_JAR" --output "$OUT/dex" \
  $(find "$OUT/classes" -name "*.class")

echo "[3/6] aapt2 compile + link"
rm -f "$OUT/res.zip" "$OUT/base.apk"
aapt2 compile --dir app/src/main/res -o "$OUT/res.zip"
aapt2 link -o "$OUT/base.apk" -I "$ANDROID_JAR" \
  --manifest app/src/main/AndroidManifest.xml \
  -A app/src/main/assets \
  "$OUT/res.zip" \
  --min-sdk-version 21 --target-sdk-version 22 \
  --version-code 1 --version-name 3.8.0

echo "[4/6] package"
python3 - "$OUT" <<'PY'
import sys, zipfile
out = sys.argv[1]
with zipfile.ZipFile(f"{out}/base.apk") as zin, \
     zipfile.ZipFile(f"{out}/unsigned.apk", "w") as zout:
    for item in zin.infolist():
        zout.writestr(item, zin.read(item.filename))
    for name in ("classes.dex",):
        zout.write(f"{out}/dex/{name}", name, compress_type=zipfile.ZIP_DEFLATED)
print("packed")
PY

echo "[5/6] zipalign"
if command -v zipalign >/dev/null 2>&1; then
  zipalign -f 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"
else
  cp "$OUT/unsigned.apk" "$OUT/aligned.apk"
fi

echo "[6/6] sign"
if [ ! -f "$OUT/debug.keystore" ]; then
  keytool -genkeypair -keystore "$OUT/debug.keystore" -storepass android -keypass android \
    -alias gen4399 -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=gen4399" >/dev/null 2>&1
fi
apksigner sign --ks "$OUT/debug.keystore" --ks-pass pass:android --key-pass pass:android \
  --out "$APK_NAME" "$OUT/aligned.apk"
apksigner verify --print-certs "$APK_NAME" | head -2
echo "OK -> $(pwd)/$APK_NAME"
