// 根构建脚本：只声明插件版本。
// AGP 9.4.0 内置 Kotlin 支持，整条 Kotlin 工具链强制对齐到 2.4.20
// （AGP 自带的 KGP 是 2.2.10，不对齐会报 Build Tools API Version Mismatch）。
buildscript {
    configurations.all {
        resolutionStrategy.eachDependency {
            if (requested.group == "org.jetbrains.kotlin") {
                useVersion("2.4.20")
            }
        }
    }
}

plugins {
    id("com.android.application") version "9.4.0" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.4.20" apply false
}
