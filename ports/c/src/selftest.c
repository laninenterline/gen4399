/* 自实现加密（GEN4399_SELF_CRYPTO）的夹具自测 */
#include "gen4399.h"
#include "payload.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(void)
{
    const char *cases[][3] = {
        {"Abc12345", "5c43e3", "0xfc88a0c93a204a36"},
        {"hello world", "abc", "0xd22da7b2be6ea575df93303f8204c05a"},
        {"P@ss!", "1234567890abcdef", "0x9b5112a937ab4658"},
    };
    int failures = 0;
    for (int i = 0; i < 3; i++) {
        char *got = g4399_encode_4399(cases[i][0], cases[i][1]);
        int ok = got && strcmp(got, cases[i][2]) == 0;
        printf("[%s] self encode4399(%s) = %s\n", ok ? "OK" : "FAIL", cases[i][0], got ? got : "(null)");
        if (!ok) failures++;
        free(got);
    }

    char *aes = g4399_aes_encrypt("plain", NULL);
    int aes_ok = aes && strncmp(aes, "U2FsdGVkX1", 10) == 0;
    printf("[%s] self AES 输出 Salted__ 前缀\n", aes_ok ? "OK" : "FAIL");
    if (!aes_ok) failures++;
    free(aes);

    const char *hidden = "appId\tu4399\nsec\t1\nmainDivId\tx\nfCaptcha\t\n";
    int fields = 0, encrypted = 0;
    char *body = g4399_build_unified_payload(hidden, "user1", "Abc12345", "王五",
                                             "110105198803121893", 1, &fields, &encrypted);
    int payload_ok = body && !strstr(body, "fCaptcha") && !strstr(body, "mainDivId") && encrypted == 4;
    printf("[%s] self 载荷剔除隐藏域且加密 4 个字段（fields=%d）\n", payload_ok ? "OK" : "FAIL", fields);
    if (!payload_ok) failures++;
    free(body);

    char kind[32], message[256];
    g4399_classify("unified", 200, "var x;isAutoRegSuccess = true;", kind, sizeof(kind), message, sizeof(message));
    printf("[%s] self 判定 success\n", strcmp(kind, "success") == 0 ? "OK" : "FAIL");
    if (strcmp(kind, "success") != 0) failures++;

    printf("%s\n", failures ? "自测失败" : "自测通过");
    return failures ? 1 : 0;
}
