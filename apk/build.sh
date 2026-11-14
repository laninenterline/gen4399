#!/usr/bin/env bash
# 本机构建脚本：顺带处理 Termux/proot 下 aapt2 需要指定路径的问题。
# CI 上直接用 `gradle assembleRelease` 即可，不需要这个脚本。
set -euo pipefail
cd "$(dirname "$0")"

AAPT2="${AAPT2_PATH:-/root/android-sdk/build-tools/36.1.0/aapt2}"
ARGS=(assembleRelease --console=plain)

if [ -x "$AAPT2" ]; then
    ARGS+=("-Pandroid.aapt2FromMavenOverride=$AAPT2")
fi

exec "${GRADLE_BIN:-gradle}" "${ARGS[@]}" "$@"
