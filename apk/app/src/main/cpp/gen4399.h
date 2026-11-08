/* gen4399 C 版：4399 注册工具的核心 API。
 *
 * 依赖：OpenSSL（AES/DES/MD5/Base64）、libcurl（HTTP）。
 * 仅用于本人账号；submit 默认 dry-run，只有显式传 yes 才发 POST。
 */
#ifndef GEN4399_H
#define GEN4399_H

#include <stddef.h>
#include <stdint.h>

/* ---------- 规则 ---------- */
#define G4399_PWD_MIN 6
#define G4399_PWD_MAX 20
#define G4399_PWD_DEFAULT 16
#define G4399_NAME_MIN 6
#define G4399_NAME_MAX 20
#define G4399_NAME_DEFAULT 12

#define G4399_PWD_CHARSET "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
#define G4399_NAME_CHARSET "abcdefghijklmnopqrstuvwxyz0123456789"

/** 生成密码/用户名，返回 malloc 的字符串（调用方 free） */
char *g4399_generate_password(int length);
char *g4399_generate_username(int length);

/** 校验：返回 0 表示合规；否则返回 strerror 风格的说明指针（静态字符串） */
const char *g4399_check_password(const char *password);
const char *g4399_check_username(const char *username);
const char *g4399_check_realname(const char *realname);
const char *g4399_check_idcard(const char *idcard);
const char *g4399_check_qq(const char *qq);

/** 生成一条随机浏览器 UA，写入 out（建议 256 字节） */
void g4399_random_user_agent(char *out, size_t out_len);

/** 身份证打码写入 buf（至少 19 字节） */
void g4399_mask_idcard(const char *idcard, char *buf, size_t buflen);

/* ---------- 加密 ---------- */
/** CryptoJS 口令模式 AES-256-CBC；返回 malloc 的 Base64（调用方 free），失败返回 NULL */
char *g4399_aes_encrypt(const char *plaintext, const char *passphrase);

/** 复刻 encode_4399：DES/3DES-ECB + "0x" hex；返回 malloc 字符串或 NULL */
char *g4399_encode_4399(const char *value, const char *key);

/* ---------- 验证码识别（unified 60×30） ---------- */
/** 传 60×30 的 ARGB 像素，成功时 out 写入 4 个字符；返回 1 成功 */
int g4399_recognize_unified(const uint32_t *argb, int width, int height, char *out);

/* ---------- 验证码识别（web 150×45） ---------- */
/** 传 150×45 的 ARGB 像素，成功时 out 写入 4 个字符；返回 1 成功 */
int g4399_recognize_web(const uint32_t *argb, int width, int height, char *out);

/* ---------- HTTP ---------- */
typedef struct g4399_session g4399_session;

g4399_session *g4399_session_new(long timeout_seconds);
void g4399_session_free(g4399_session *session);
void g4399_session_set_referer(g4399_session *session, const char *referer);

/** 会话里是否存在某个 Cookie（用于判断登录态） */
int g4399_session_has_cookie(g4399_session *session, const char *name);

/** GET/POST；返回 0 成功。响应体写入 *out（malloc，调用方 free），长度写入 *out_len */
int g4399_http_get(g4399_session *session, const char *url, char **out, size_t *out_len);
int g4399_http_post(g4399_session *session, const char *url, const char *body,
                    const char *content_type, char **out, size_t *out_len);

/* ---------- 注册 / 登录 ---------- */
typedef struct {
    const char *path;      /* "unified" / "web" */
    const char *username;
    const char *password;
    const char *realname;
    const char *idcard;
    const char *qq;
    const char *app_id;    /* NULL -> u4399 */
    int level;             /* <=0 -> 4 */
    long timeout;
    int dry_run;           /* 非 0 = 不发 POST */
    int send_realname;     /* 0 = unified 不带实名 */
} g4399_submit_options;

typedef struct {
    char kind[16];         /* success/rejected/captcha/throttled/unknown/dry_run */
    int ok;
    char message[512];
    int field_count;
    int encrypted_count;
} g4399_submit_result;

int g4399_submit(const g4399_submit_options *options, g4399_submit_result *result);

typedef struct {
    int ok;
    char kind[16];
    char message[256];
    int cookie_count;
} g4399_login_result;

int g4399_login(const char *username, const char *password, long timeout,
                g4399_login_result *result);

#endif /* GEN4399_H */
