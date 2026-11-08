cmake_minimum_required(VERSION 3.22)
project(gen4399 C)

set(CMAKE_C_STANDARD 11)

add_library(gen4399 SHARED
    ./crypto_self.c
    ./rules.c
    ./payload.c
    ./matcher.c
    ./agent.c
    ./jni.c
    ./jni_agent.c
)

target_include_directories(gen4399 PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_options(gen4399 PRIVATE -O2 -Wall -DGEN4399_SELF_CRYPTO)
