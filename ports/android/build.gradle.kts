// AGP 9 起内置 Kotlin 支持（不再需要 org.jetbrains.kotlin.android 插件）。
// AGP 9.4.0 内置的 KGP 是 2.2.10；这里把整条 Kotlin 工具链强制对齐到 2.4.20，
// 否则 app/build.gradle 里 kotlin { compilerVersion = '2.4.20' } 会报
// 「Build Tools API Version Mismatch」（impl 2.4.20 vs KGP 2.2.10）。
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
}
