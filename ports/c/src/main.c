/* gen4399（C 版）命令行。 */
#include "gen4399.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void usage(void)
{
    puts("gen4399 (c) — 4399 注册工具\n"
         "\n"
         "用法:\n"
         "  gen4399 generate [-n 16] [-c 1] [--username]\n"
         "  gen4399 check password|username <值>\n"
         "  gen4399 idcard <18 位号码>\n"
         "  gen4399 encode4399 <明文> <encryptCode>\n"
         "  gen4399 aes <明文>\n"
         "  gen4399 fields\n"
         "  gen4399 submit <用户名> <密码> --realname 姓名 --idcard 号码\n"
         "                  [--path unified|web] [--dry-run|--yes]\n"
         "  gen4399 login <用户名> --password 密码\n"
         "  gen4399 selftest\n"
         "\n"
         "说明: submit 默认 dry-run，只有加 --yes 才会真正发送注册 POST。");
}

static const char *value_of(int argc, char **argv, const char *flag)
{
    for (int i = 0; i < argc - 1; i++) {
        if (strcmp(argv[i], flag) == 0) return argv[i + 1];
    }
    return NULL;
}

static int has_flag(int argc, char **argv, const char *flag)
{
    for (int i = 0; i < argc; i++) {
        if (strcmp(argv[i], flag) == 0) return 1;
    }
    return 0;
}

static int cmd_generate(int argc, char **argv)
{
    int length = 16, count = 1, username = has_flag(argc, argv, "--username");
    const char *n = value_of(argc, argv, "-n");
    const char *c = value_of(argc, argv, "-c");
    if (n) length = atoi(n);
    if (c) count = atoi(c);
    for (int i = 0; i < count; i++) {
        char *value = username ? g4399_generate_username(length)
                               : g4399_generate_password(length);
        if (!value) {
            fprintf(stderr, "错误：长度不合法（密码 6~20，用户名 6~20）\n");
            return 2;
        }
        printf("%s\n", value);
        free(value);
    }
    return 0;
}

static int cmd_check(int argc, char **argv)
{
    if (argc < 2) { fprintf(stderr, "用法: check password|username <值>\n"); return 2; }
    const char *reason = strcmp(argv[0], "password") == 0
        ? g4399_check_password(argv[1]) : g4399_check_username(argv[1]);
    if (!reason) { printf("OK: %s 合规\n", argv[0]); return 0; }
    printf("FAIL: %s → %s\n", argv[0], reason);
    return 1;
}

static int cmd_idcard(int argc, char **argv)
{
    if (argc < 1) { fprintf(stderr, "用法: idcard <18 位号码>\n"); return 2; }
    const char *reason = g4399_check_idcard(argv[0]);
    if (!reason) {
        char masked[24];
        g4399_mask_idcard(argv[0], masked, sizeof(masked));
        printf("OK: %s 通过校验\n", masked);
        return 0;
    }
    printf("FAIL: %s\n", reason);
    return 1;
}

static int cmd_encode4399(int argc, char **argv)
{
    if (argc < 2) { fprintf(stderr, "用法: encode4399 <明文> <encryptCode>\n"); return 2; }
    char *hex = g4399_encode_4399(argv[0], argv[1]);
    if (!hex) { fprintf(stderr, "错误：加密失败\n"); return 2; }
    printf("%s\n", hex);
    free(hex);
    return 0;
}

static int cmd_aes(int argc, char **argv)
{
    if (argc < 1) { fprintf(stderr, "用法: aes <明文>\n"); return 2; }
    char *cipher = g4399_aes_encrypt(argv[0], NULL);
    if (!cipher) { fprintf(stderr, "错误：加密失败\n"); return 2; }
    printf("%s\n", cipher);
    free(cipher);
    return 0;
}

static int cmd_fields(void)
{
    puts("web 字段: cid login_name login_password relogin_pwd qq true_name sfz encrypt");
    puts("unified 基础字段: appId regMode level username password passwordveri sessionId sec");
    puts("unified 实名: realname idcard（AES-256-CBC）");
    puts("unified 剔除字段(13): crossDomainUrl mainDivId showRegInfo includeFcmInfo "
         "expandFcmInput fcmFakeValidate realnameValidate userNameLabel iframeId "
         "email reg_eula_agree autoLogin fCaptcha");
    return 0;
}

static int cmd_submit(int argc, char **argv)
{
    if (argc < 2) { usage(); return 2; }
    g4399_submit_options options;
    memset(&options, 0, sizeof(options));
    options.username = argv[0];
    options.password = argv[1];
    options.realname = value_of(argc, argv, "--realname");
    options.idcard = value_of(argc, argv, "--idcard");
    options.qq = value_of(argc, argv, "--qq");
    options.path = value_of(argc, argv, "--path");
    options.app_id = value_of(argc, argv, "--app-id");
    options.level = 4;
    options.timeout = 15;
    options.send_realname = !has_flag(argc, argv, "--no-realname");
    options.dry_run = !has_flag(argc, argv, "--yes") || has_flag(argc, argv, "--dry-run");

    if (!options.realname || !options.idcard) {
        fprintf(stderr, "错误：需要 --realname 与 --idcard\n");
        return 2;
    }
    if (options.dry_run) {
        puts("# DRY-RUN：未加 --yes，不会真正提交（加 --yes 才发送 POST）");
    } else {
        puts("# 警告：即将真实提交 4399 注册请求；只应使用本人真实身份，并遵守 4399 用户协议。");
    }

    g4399_submit_result result;
    if (g4399_submit(&options, &result) != 0) {
        fprintf(stderr, "错误：提交失败（网络或参数问题）\n");
        return 2;
    }
    printf("结果: %s（ok=%d）\n  说明: %s\n", result.kind, result.ok, result.message);
    if (result.field_count) {
        printf("  字段: %d 个，加密 %d 个\n", result.field_count, result.encrypted_count);
    }
    return result.ok ? 0 : 1;
}

static int cmd_login(int argc, char **argv)
{
    if (argc < 1) { usage(); return 2; }
    const char *password = value_of(argc, argv, "--password");
    if (!password) { fprintf(stderr, "错误：需要 --password\n"); return 2; }
    g4399_login_result result;
    if (g4399_login(argv[0], password, 15, &result) != 0) {
        fprintf(stderr, "错误：登录请求失败\n");
        return 2;
    }
    if (result.ok) {
        printf("OK: %s 登录成功\n", argv[0]);
        return 0;
    }
    printf("FAIL[%s]: %s\n", result.kind, result.message);
    return 1;
}

static int cmd_selftest(void)
{
    struct { const char *value, *key, *expect; } cases[] = {
        {"Abc12345", "5c43e3", "0xfc88a0c93a204a36"},
        {"hello world", "abc", "0xd22da7b2be6ea575df93303f8204c05a"},
        {"P@ss!", "1234567890abcdef", "0x9b5112a937ab4658"},
    };
    int failures = 0;
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        char *got = g4399_encode_4399(cases[i].value, cases[i].key);
        int ok = got && strcmp(got, cases[i].expect) == 0;
        printf("[%s] encode4399(%s) = %s\n", ok ? "OK" : "FAIL", cases[i].value,
               got ? got : "(null)");
        if (!ok) failures++;
        free(got);
    }
    const char *bad = g4399_check_idcard("110105198803121892");
    printf("[%s] 身份证校验码错误能被发现\n", bad ? "OK" : "FAIL");
    if (!bad) failures++;
    const char *good = g4399_check_idcard("110105198803121893");
    printf("[%s] 合法身份证通过\n", good ? "FAIL" : "OK");
    if (good) failures++;
    char *password = g4399_generate_password(12);
    printf("[%s] 生成的密码合规（%s）\n",
           password && !g4399_check_password(password) ? "OK" : "FAIL",
           password ? password : "(null)");
    if (!password || g4399_check_password(password)) failures++;
    free(password);
    printf("%s\n", failures ? "自测失败" : "自测通过");
    return failures ? 1 : 0;
}

int main(int argc, char **argv)
{
    if (argc < 2) { usage(); return 0; }
    const char *command = argv[1];
    int rest_argc = argc - 2;
    char **rest = argv + 2;

    if (strcmp(command, "generate") == 0) return cmd_generate(rest_argc, rest);
    if (strcmp(command, "check") == 0) return cmd_check(rest_argc, rest);
    if (strcmp(command, "idcard") == 0) return cmd_idcard(rest_argc, rest);
    if (strcmp(command, "encode4399") == 0) return cmd_encode4399(rest_argc, rest);
    if (strcmp(command, "aes") == 0) return cmd_aes(rest_argc, rest);
    if (strcmp(command, "fields") == 0) return cmd_fields();
    if (strcmp(command, "submit") == 0) return cmd_submit(rest_argc, rest);
    if (strcmp(command, "login") == 0) return cmd_login(rest_argc, rest);
    if (strcmp(command, "selftest") == 0) return cmd_selftest();
    if (strcmp(command, "-h") == 0 || strcmp(command, "--help") == 0) { usage(); return 0; }
    fprintf(stderr, "未知命令: %s\n", command);
    usage();
    return 2;
}
