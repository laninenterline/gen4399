cmake_minimum_required(VERSION 3.22)
project(gen4399 C)

set(CMAKE_C_STANDARD 11)

add_library(gen4399 SHARED
    src/crypto_self.c
    src/rules.c
    src/payload.c
    src/jni.c
)

target_include_directories(gen4399 PRIVATE include)
target_compile_options(gen4399 PRIVATE -O2 -Wall -DGEN4399_SELF_CRYPTO)
