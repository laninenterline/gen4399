/* 批量注册编排（全部在 C 里）：身份解析、账号生成、载荷组装、验证码重试、
 * 节奏控制、结果汇总。Kotlin 只提供「HTTP 传输」和「界面回调」两件事。 */
#ifndef GEN4399_AGENT_H
#define GEN4399_AGENT_H

#include <stddef.h>

typedef struct {
    const char *path;          /* "unified" / "web" */
    int count;                 /* 0 = 全部 */
    const char *prefix;
    const char *suffix;
    int interval_sec;
    int dry_run;
    int send_realname;
    int randomize;             /* 非 0 = 随机挑选身份（避免总是用前几条，可能已被用尽） */
    const char *app_id;
    int level;
} g4399_agent_config;

/* 由 JNI 层实现并填入：C 侧只依赖函数指针 */
typedef struct {
    void *ctx;
    /* 发一次 HTTP：返回 malloc 的 "status|cookie1\u001fcookie2\u001f...|body" */
    char *(*transport)(void *ctx, const char *url, const char *method,
                       const char *content_type, const char *body,
                       const char *cookie_header, const char *referer);
    /* 一个账号跑完（成功/失败都调用） */
    void (*progress)(void *ctx, int index, int total, const char *username,
                     const char *password, const char *kind, int ok,
                     const char *message);
    /* 抓二进制（验证码图片）：返回 malloc 的缓冲，长度写入 *length，HTTP 码写入 *status */
    unsigned char *(*fetch_binary)(void *ctx, const char *url, const char *cookie_header,
                                   const char *referer, int *length, int *status);
    /* 需要人工识别验证码：返回 malloc 的 4 位字符，NULL 表示放弃 */
    char *(*captcha)(void *ctx, const unsigned char *image, int length);
    /* 日志 */
    void (*log)(void *ctx, const char *line);
} g4399_agent_hooks;

/* 跑完返回成功数；出错返回 -1。identities 每行 name|idcard[|qq] */
int g4399_agent_run(const char *identities, const g4399_agent_config *config,
                    const g4399_agent_hooks *hooks);

#endif /* GEN4399_AGENT_H */
