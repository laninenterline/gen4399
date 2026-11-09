/* 批量注册编排：全部业务逻辑在这里，Kotlin 只做展示与 HTTP 传输。 */
#include "agent.h"
#include "gen4399.h"
#include "payload.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <time.h>
#include <stdint.h>

/* 身份数量硬上限：25MB 的 sfz.txt 可能有上百万行，这里兜底防止内存爆掉 */
#define MAX_IDENTITIES 5000

#define UNIFIED_REGISTER_URL "https://ptlogin.4399.com/ptlogin/register.do"
#define UNIFIED_CAPTCHA_URL "https://ptlogin.4399.com/ptlogin/captcha.do?captchaId="
#define WEB_REG_URL "https://web.4399.com/user/?_c=reg&jsoncallback=cb"
#define WEB_CHECK_URL "https://web.4399.com/user/?_c=login&_a=checkUser"
#define WEB_CAPTCHA_URL "https://web.4399.com/util/?_c=code&t=reg"
#define WEB_VERIFY_URL "https://web.4399.com/user/?_c=reg&_a=verifyCode"
#define LOGIN_URL "https://ptlogin.4399.com/ptlogin/login.do?v=1"
#define HOME_URL "https://u.4399.com/"

typedef struct { char *data; size_t len; size_t cap; } sbuf;

static void sbuf_init(sbuf *b) { b->data = calloc(1, 1); b->len = 0; b->cap = 1; }
static void sbuf_add(sbuf *b, const char *text)
{
    size_t n = strlen(text);
    if (b->len + n + 1 > b->cap) {
        size_t cap = b->cap ? b->cap : 64;
        while (cap < b->len + n + 1) cap *= 2;
        char *grown = realloc(b->data, cap);
        if (!grown) return;
        b->data = grown;
        b->cap = cap;
    }
    memcpy(b->data + b->len, text, n + 1);
    b->len += n;
}
static void sbuf_add_encoded(sbuf *b, const char *value)
{
    static const char hex[] = "0123456789ABCDEF";
    char tri[4];
    for (const unsigned char *p = (const unsigned char *)value; p && *p; p++) {
        if (isalnum(*p) || *p == '-' || *p == '_' || *p == '.' || *p == '~') {
            char one[2] = {(char)*p, '\0'};
            sbuf_add(b, one);
        } else if (*p == ' ') {
            sbuf_add(b, "+");
        } else {
            tri[0] = '%'; tri[1] = hex[(*p >> 4) & 0xF]; tri[2] = hex[*p & 0xF]; tri[3] = '\0';
            sbuf_add(b, tri);
        }
    }
}
static char *sbuf_take(sbuf *b) { char *data = b->data; b->data = NULL; b->len = b->cap = 0; return data; }

/* ---------------- Cookie 罐 ---------------- */

typedef struct { char *name; char *value; } cookie;
typedef struct { cookie *items; int count; } cookie_jar;

static void jar_set(cookie_jar *jar, const char *name, const char *value)
{
    for (int i = 0; i < jar->count; i++) {
        if (strcmp(jar->items[i].name, name) == 0) {
            free(jar->items[i].value);
            jar->items[i].value = strdup(value);
            return;
        }
    }
    jar->items = realloc(jar->items, sizeof(cookie) * (size_t)(jar->count + 1));
    jar->items[jar->count].name = strdup(name);
    jar->items[jar->count].value = strdup(value);
    jar->count++;
}

static void jar_update(cookie_jar *jar, const char *set_cookie_lines)
{
    if (!set_cookie_lines) return;
    const char *p = set_cookie_lines;
    while (*p) {
        const char *line_end = strchr(p, '\x1f');
        size_t len = line_end ? (size_t)(line_end - p) : strlen(p);
        if (len) {
            const char *semi = memchr(p, ';', len);
            size_t pair_len = semi ? (size_t)(semi - p) : len;
            const char *eq = memchr(p, '=', pair_len);
            if (eq) {
                char *name = strndup(p, (size_t)(eq - p));
                char *value = strndup(eq + 1, pair_len - (size_t)(eq - p) - 1);
                jar_set(jar, name, value);
                free(name);
                free(value);
            }
        }
        if (!line_end) break;
        p = line_end + 1;
    }
}

static int jar_has(cookie_jar *jar, const char *name)
{
    for (int i = 0; i < jar->count; i++) {
        if (strcmp(jar->items[i].name, name) == 0) return 1;
    }
    return 0;
}

static char *jar_header(cookie_jar *jar)
{
    if (jar->count == 0) return strdup("");
    sbuf b;
    sbuf_init(&b);
    for (int i = 0; i < jar->count; i++) {
        if (i) sbuf_add(&b, "; ");
        sbuf_add(&b, jar->items[i].name);
        sbuf_add(&b, "=");
        sbuf_add(&b, jar->items[i].value);
    }
    return sbuf_take(&b);
}

static void jar_free(cookie_jar *jar)
{
    for (int i = 0; i < jar->count; i++) {
        free(jar->items[i].name);
        free(jar->items[i].value);
    }
    free(jar->items);
}

/* ---------------- 一次请求 ---------------- */

typedef struct {
    int status;
    char *body;
    int body_length;   /* 二进制时为字节数；文本时为 0（用 strlen） */
} http_result;

static http_result do_request(const g4399_agent_hooks *hooks, cookie_jar *jar,
                              const char *url, const char *method,
                              const char *content_type, const char *body,
                              const char *referer)
{
    http_result result = {0, NULL, 0};
    char *cookie_header = jar_header(jar);
    char *raw = hooks->transport(hooks->ctx, url, method, content_type,
                                 body ? body : "", cookie_header,
                                 referer ? referer : "https://www.4399.com/");
    free(cookie_header);
    if (!raw) return result;

    /* 格式：status|cookies\u001f...|body */
    char *first = strchr(raw, '|');
    if (!first) { free(raw); return result; }
    result.status = atoi(raw);
    char *second = strchr(first + 1, '|');
    if (!second) { free(raw); return result; }
    *second = '\0';
    jar_update(jar, first + 1);
    result.body = strdup(second + 1);
    result.body_length = 0;
    free(raw);
    return result;
}

/* 抓验证码图片：走 fetch_binary，避免二进制被当成 UTF-8 文本破坏 */
static http_result fetch_image(const g4399_agent_hooks *hooks, cookie_jar *jar,
                               const char *url, const char *referer)
{
    http_result result = {0, NULL, 0};
    if (!hooks->fetch_binary) return result;
    char *cookie_header = jar_header(jar);
    int length = 0, status = 0;
    unsigned char *data = hooks->fetch_binary(hooks->ctx, url, cookie_header,
                                              referer ? referer : "https://www.4399.com/",
                                              &length, &status);
    free(cookie_header);
    result.status = status;
    if (!data || length <= 0) {
        free(data);
        result.status = status;
        result.body = strdup("（验证码图片为空）");
        result.body_length = 0;
        return result;
    }
    result.body = (char *)data;
    result.body_length = length;
    return result;
}

/* ---------------- 工具 ---------------- */

/** 把 JSON 里的 \uXXXX 转义解成 UTF-8，便于界面直接读 */
static void decode_unicode_escapes(const char *in, char *out, size_t out_len)
{
    if (!out || out_len == 0) return;
    size_t pos = 0;
    for (const char *p = in; p && *p && pos + 5 < out_len; ) {
        if (p[0] == '\\' && p[1] == 'u' && isxdigit((unsigned char)p[2]) &&
            isxdigit((unsigned char)p[3]) && isxdigit((unsigned char)p[4]) &&
            isxdigit((unsigned char)p[5])) {
            char hex[5] = {p[2], p[3], p[4], p[5], 0};
            unsigned int code = (unsigned int)strtoul(hex, NULL, 16);
            if (code < 0x80) {
                out[pos++] = (char)code;
            } else if (code < 0x800) {
                out[pos++] = (char)(0xC0 | (code >> 6));
                out[pos++] = (char)(0x80 | (code & 0x3F));
            } else {
                out[pos++] = (char)(0xE0 | (code >> 12));
                out[pos++] = (char)(0x80 | ((code >> 6) & 0x3F));
                out[pos++] = (char)(0x80 | (code & 0x3F));
            }
            p += 6;
        } else {
            out[pos++] = *p++;
        }
    }
    out[pos] = '\0';
}

/** 失败时把用的是哪张身份证带上，方便判断是不是这张已用尽 */
static void append_masked_idcard(const char *idcard, char *message, size_t message_len)
{
    char masked[24] = {0};
    g4399_mask_idcard(idcard, masked, sizeof(masked));
    if (!masked[0]) return;
    size_t len = strlen(message);
    if (len + 32 >= message_len) return;
    snprintf(message + len, message_len - len, "（身份 %s）", masked);
}

/* ---------------- 注册后验证 ---------------- */

/** 从页面里抠出 <div id="Msg"> 的文本（payload.c 里的同名函数是 static） */
static void extract_msg_local(const char *body, char *out, size_t out_len)
{
    out[0] = '\0';
    if (!body) return;
    const char *msg = strstr(body, "id=\"Msg\"");
    if (!msg) msg = strstr(body, "id='Msg'");
    if (!msg) return;
    const char *start = strchr(msg, '>');
    if (!start) return;
    start++;
    const char *end = strstr(start, "</div>");
    if (!end) return;
    size_t pos = 0;
    for (const char *p = start; p < end && pos + 1 < out_len; p++) {
        if (*p == '<') { while (p < end && *p != '>') p++; continue; }
        out[pos++] = *p;
    }
    out[pos] = '\0';
    while (pos && isspace((unsigned char)out[pos - 1])) out[--pos] = '\0';
}

/**
 * 用刚注册的账号密码真登录一次，确认号确实建好了。
 * 返回 1 = 能登录；0 = 明确不行（不存在/密码错）；-1 = 无法判断（网络/限流）。
 */
static int verify_by_login(const g4399_agent_hooks *hooks, const char *username,
                           const char *password, char *reason, size_t reason_len)
{
    if (reason && reason_len) reason[0] = '\0';

    char *cipher = g4399_aes_encrypt(password, NULL);
    if (!cipher) return -1;

    sbuf body;
    sbuf_init(&body);
    sbuf_add(&body, "appId=u4399&username=");
    sbuf_add_encoded(&body, username);
    sbuf_add(&body, "&password=");
    sbuf_add_encoded(&body, cipher);
    sbuf_add(&body, "&sec=1");
    free(cipher);

    cookie_jar jar = {0};
    http_result response = do_request(hooks, &jar, LOGIN_URL, "POST",
                                      "application/x-www-form-urlencoded", body.data,
                                      "https://ptlogin.4399.com/");
    free(body.data);

    int verdict = -1;
    if (jar_has(&jar, "Pauth") || jar_has(&jar, "Uauth") || jar_has(&jar, "Xauth")) {
        verdict = 1;
        if (reason && reason_len) snprintf(reason, reason_len, "登录成功");
    } else if (response.body && strstr(response.body, "请稍后再试")) {
        verdict = -1;
        if (reason && reason_len) snprintf(reason, reason_len, "登录校验被限流");
    } else if (response.body && (strstr(response.body, "密码错误") ||
                                 strstr(response.body, "用户不存在") ||
                                 strstr(response.body, "不存在"))) {
        verdict = 0;
        char msg[128];
        extract_msg_local(response.body, msg, sizeof(msg));
        if (reason && reason_len) snprintf(reason, reason_len, "%s", msg[0] ? msg : "登录被拒");
    }
    free(response.body);
    jar_free(&jar);
    return verdict;
}

/* ---------------- 身份解析 ---------------- */

typedef struct { char *name; char *idcard; char *qq; } identity;

static char *trim(char *text)
{
    while (*text && isspace((unsigned char)*text)) text++;
    char *end = text + strlen(text);
    while (end > text && isspace((unsigned char)end[-1])) *--end = '\0';
    return text;
}

static int parse_identities(const char *text, identity **out)
{
    int count = 0;
    identity *items = NULL;
    char *copy = strdup(text ? text : "");
    char *line = copy;
    while (line && *line) {
        char *eol = strchr(line, '\n');
        if (eol) *eol = '\0';
        char *entry = trim(line);
        if (count >= MAX_IDENTITIES) break;
        if (*entry && *entry != '#') {
            char *first = strchr(entry, '|');
            if (!first && (first = strchr(entry, ',')) == NULL) { /* 跳过 */ }
            if (first) {
                *first = '\0';
                char *second = strchr(first + 1, '|');
                if (!second) second = strchr(first + 1, ',');
                char *third = NULL;
                if (second) { *second = '\0'; third = strchr(second + 1, '|'); }
                items = realloc(items, sizeof(identity) * (size_t)(count + 1));
                items[count].name = strdup(trim(entry));
                items[count].idcard = strdup(trim(first + 1));
                items[count].qq = strdup(third ? trim(third + 1) : (second ? trim(second + 1) : ""));
                count++;
            }
        }
        if (!eol) break;
        line = eol + 1;
    }
    free(copy);
    *out = items;
    return count;
}

/* ---------------- web 路径 ---------------- */

static char *extract_json_string(const char *body, const char *key)
{
    if (!body) return NULL;
    char pattern[64];
    snprintf(pattern, sizeof(pattern), "\"%s\"", key);
    const char *p = strstr(body, pattern);
    if (!p) return NULL;
    p = strchr(p + strlen(pattern), ':');
    if (!p) return NULL;
    p = strchr(p, '"');
    if (!p) return NULL;
    const char *end = strchr(p + 1, '"');
    if (!end) return NULL;
    return strndup(p + 1, (size_t)(end - p - 1));
}

static void classify_into(const char *path, int status, const char *body,
                          char *kind, size_t kind_len, char *message, size_t message_len)
{
    g4399_classify(path, status, body, kind, kind_len, message, message_len);
}

/* ---------------- 单账号 ---------------- */

typedef struct {
    char kind[32];
    char message[512];
    int ok;
    char *username;
    char *password;
} account_result;

static void run_web(const g4399_agent_hooks *hooks, cookie_jar *jar, const identity *who,
                    const char *username, const char *password, int dry_run,
                    account_result *result)
{
    sbuf check;
    sbuf_init(&check);
    sbuf_add(&check, WEB_CHECK_URL "&user=");
    sbuf_add_encoded(&check, username);
    sbuf_add(&check, "&jsoncallback=cb");
    http_result probe = do_request(hooks, jar, check.data, "GET", NULL, NULL,
                                   "https://web.4399.com/user/reg.php");
    free(check.data);

    char *encrypt_code = extract_json_string(probe.body, "data");
    if (!encrypt_code || !*encrypt_code) {
        free(encrypt_code);
        encrypt_code = strdup("5c43e3");
    }
    free(probe.body);

    char *cipher = g4399_encode_4399(password, encrypt_code);
    free(encrypt_code);
    if (!cipher) {
        snprintf(result->kind, sizeof(result->kind), "error");
        snprintf(result->message, sizeof(result->message), "DES 加密失败");
        return;
    }

    sbuf payload;
    sbuf_init(&payload);
    sbuf_add(&payload, "cid=3000&login_name=");
    sbuf_add_encoded(&payload, username);
    sbuf_add(&payload, "&login_password=");
    sbuf_add_encoded(&payload, cipher);
    sbuf_add(&payload, "&relogin_pwd=");
    sbuf_add_encoded(&payload, cipher);
    sbuf_add(&payload, "&qq=");
    sbuf_add_encoded(&payload, who->qq ? who->qq : "");
    sbuf_add(&payload, "&true_name=");
    sbuf_add_encoded(&payload, who->name);
    sbuf_add(&payload, "&sfz=");
    sbuf_add_encoded(&payload, who->idcard);
    sbuf_add(&payload, "&encrypt=1");
    free(cipher);

    if (dry_run) {
        snprintf(result->kind, sizeof(result->kind), "dry_run");
        snprintf(result->message, sizeof(result->message), "dry-run：未发送 POST（8 个字段）");
        free(payload.data);
        return;
    }

    http_result response = do_request(hooks, jar, WEB_REG_URL, "POST",
                                      "application/x-www-form-urlencoded", payload.data,
                                      "https://web.4399.com/user/reg.php");
    for (int round = 0; round < 5 && response.body; round++) {
        classify_into("web", response.status, response.body, result->kind, sizeof(result->kind),
                      result->message, sizeof(result->message));
        if (strcmp(result->kind, "captcha") != 0) break;

        http_result image = fetch_image(hooks, jar, WEB_CAPTCHA_URL,
                                        "https://web.4399.com/user/reg.php");
        if (!image.body) break;
        int image_len = image.body_length > 0 ? image.body_length : (int)strlen(image.body ? image.body : "");
        char *code = hooks->captcha(hooks->ctx, (const unsigned char *)image.body, image_len);
        free(image.body);
        if (!code || !*code) { free(code); break; }

        /* 先 verifyCode 确认这次识别对不对，不对就重新取图 */
        sbuf verify;
        sbuf_init(&verify);
        sbuf_add(&verify, WEB_VERIFY_URL "&jsoncallback=cb&code=");
        sbuf_add_encoded(&verify, code);
        {
            char suffix[32];
            snprintf(suffix, sizeof(suffix), "&_=%lld", (long long)time(NULL) * 1000);
            sbuf_add(&verify, suffix);
        }
        http_result verified = do_request(hooks, jar, verify.data, "GET", NULL, NULL,
                                          "https://web.4399.com/user/reg.php");
        free(verify.data);
        int passed = verified.body && strstr(verified.body, "\"state\":true") != NULL;
        free(verified.body);
        if (hooks->captcha_feedback) hooks->captcha_feedback(hooks->ctx, code, passed);
        if (!passed) {
            free(code);
            continue;
        }

        sbuf retry;
        sbuf_init(&retry);
        sbuf_add(&retry, payload.data);
        sbuf_add(&retry, "&chk_code=");
        sbuf_add_encoded(&retry, code);
        free(code);
        free(response.body);
        response = do_request(hooks, jar, WEB_REG_URL, "POST",
                              "application/x-www-form-urlencoded", retry.data,
                              "https://web.4399.com/user/reg.php");
        free(retry.data);
    }
    if (response.body) {
        classify_into("web", response.status, response.body, result->kind, sizeof(result->kind),
                      result->message, sizeof(result->message));
        char decoded[256];
        decode_unicode_escapes(result->message, decoded, sizeof(decoded));
        snprintf(result->message, sizeof(result->message), "%s", decoded);
    }
    free(response.body);
    free(payload.data);
    result->ok = strcmp(result->kind, "success") == 0;
    if (!result->ok) {
        append_masked_idcard(who->idcard, result->message, sizeof(result->message));
    }

    /* 响应说成功还不够：真登录一次确认号确实建好了 */
    if (result->ok) {
        char reason[128] = {0};
        int verdict = verify_by_login(hooks, username, password, reason, sizeof(reason));
        if (verdict == 0) {
            snprintf(result->kind, sizeof(result->kind), "unverified");
            snprintf(result->message, sizeof(result->message),
                     "注册响应成功，但登录验证失败：%s", reason);
            result->ok = 0;
        } else if (verdict == 1) {
            snprintf(result->message, sizeof(result->message),
                     "%s（已用登录验证：密码可登录）", result->message);
        } else {
            snprintf(result->message, sizeof(result->message),
                     "%s（登录验证未完成：%s）", result->message, reason[0] ? reason : "网络/限流");
        }
    }
}

static void run_unified(const g4399_agent_hooks *hooks, cookie_jar *jar, const identity *who,
                        const char *username, const char *password, const g4399_agent_config *config,
                        account_result *result)
{
    char *form_url = g4399_form_url(config->app_id, config->level);
    char form_url_keep[512];
    snprintf(form_url_keep, sizeof(form_url_keep), "%s", form_url);
    http_result page = do_request(hooks, jar, form_url, "GET", NULL, NULL,
                                  "https://u.4399.com/register.html");
    free(form_url);
    int page_status = page.status;
    size_t page_len = page.body ? strlen(page.body) : 0;
    char *page_body_copy = page.body ? strdup(page.body) : NULL;

    if (!page.body || page.status == 202 || strstr(page.body, "请稍后再试")) {
        snprintf(result->kind, sizeof(result->kind), "throttled");
        snprintf(result->message, sizeof(result->message), "服务端限流（请稍后再试）");
        free(page.body);
        return;
    }
    char *hidden = g4399_parse_hidden(page.body);
    free(page.body);
    page.body = NULL;
    if (!hidden || !*hidden) {
        char snippet[96] = {0};
        const char *source = page_body_copy ? page_body_copy : "";
        for (int i = 0; i < 60 && source[i]; i++) {
            snippet[i] = (source[i] == '\n' || source[i] == '\r') ? ' ' : source[i];
        }
        snprintf(result->kind, sizeof(result->kind), "unknown");
        snprintf(result->message, sizeof(result->message),
                 "注册页没有隐藏域（HTTP %d，响应 %zu 字节）：%s", page_status, page_len, snippet);
        free(hidden);
        free(page_body_copy);
        return;
    }
    free(page_body_copy);

    char *body = g4399_build_unified_payload(hidden, username, password, who->name, who->idcard,
                                             config->send_realname, NULL, NULL);
    if (!body) {
        snprintf(result->kind, sizeof(result->kind), "error");
        snprintf(result->message, sizeof(result->message), "载荷组装失败");
        free(hidden);
        return;
    }
    if (config->dry_run) {
        int fields = 1;
        for (const char *p = body; *p; p++) if (*p == '&') fields++;
        snprintf(result->kind, sizeof(result->kind), "dry_run");
        snprintf(result->message, sizeof(result->message), "dry-run：未发送 POST（%d 个字段）", fields);
        free(body);
        free(hidden);
        return;
    }

    http_result response = do_request(hooks, jar, UNIFIED_REGISTER_URL, "POST",
                                      "application/x-www-form-urlencoded", body, form_url_keep);
    for (int round = 0; round < 5 && response.body; round++) {
        classify_into("unified", response.status, response.body, result->kind, sizeof(result->kind),
                      result->message, sizeof(result->message));
        if (strcmp(result->kind, "captcha") != 0) break;

        const char *marker = strstr(response.body, "captchaId=");
        if (!marker) break;
        const char *value = marker + strlen("captchaId=");
        size_t len = 0;
        while (isalnum((unsigned char)value[len])) len++;
        char *captcha_id = strndup(value, len);

        sbuf image_url;
        sbuf_init(&image_url);
        sbuf_add(&image_url, UNIFIED_CAPTCHA_URL);
        sbuf_add(&image_url, captcha_id);
        http_result image = fetch_image(hooks, jar, image_url.data, form_url_keep);
        free(image_url.data);
        if (!image.body) { free(captcha_id); break; }
        int image_len = image.body_length > 0 ? image.body_length : (int)strlen(image.body ? image.body : "");
        char *code = hooks->captcha(hooks->ctx, (const unsigned char *)image.body, image_len);
        free(image.body);
        if (!code || !*code) { free(code); free(captcha_id); break; }

        char *fresh_hidden = g4399_parse_hidden(response.body);
        char *retry = g4399_build_unified_payload(fresh_hidden ? fresh_hidden : hidden,
                                                  username, password, who->name, who->idcard,
                                                  config->send_realname, NULL, NULL);
        free(fresh_hidden);
        free(response.body);
        if (!retry) { free(code); free(captcha_id); break; }

        sbuf with_code;
        sbuf_init(&with_code);
        sbuf_add(&with_code, retry);
        sbuf_add(&with_code, "&inputCaptcha=");
        sbuf_add_encoded(&with_code, code);
        sbuf_add(&with_code, "&sessionId=");
        sbuf_add_encoded(&with_code, captcha_id);
        free(code);
        free(captcha_id);
        free(retry);
        response = do_request(hooks, jar, UNIFIED_REGISTER_URL, "POST",
                              "application/x-www-form-urlencoded", with_code.data,
                              form_url_keep);
        free(with_code.data);
    }
    if (response.body) {
        classify_into("unified", response.status, response.body, result->kind, sizeof(result->kind),
                      result->message, sizeof(result->message));
    }
    free(response.body);
    free(body);
    free(hidden);
    result->ok = strcmp(result->kind, "success") == 0;
    if (!result->ok) {
        append_masked_idcard(who->idcard, result->message, sizeof(result->message));
    }

    if (result->ok) {
        char reason[128] = {0};
        int verdict = verify_by_login(hooks, username, password, reason, sizeof(reason));
        if (verdict == 0) {
            snprintf(result->kind, sizeof(result->kind), "unverified");
            snprintf(result->message, sizeof(result->message),
                     "注册响应成功，但登录验证失败：%s", reason);
            result->ok = 0;
        } else if (verdict == 1) {
            snprintf(result->message, sizeof(result->message),
                     "%s（已用登录验证：密码可登录）", result->message);
        } else {
            snprintf(result->message, sizeof(result->message),
                     "%s（登录验证未完成：%s）", result->message, reason[0] ? reason : "网络/限流");
        }
    }
}

/* ---------------- 批量入口 ---------------- */

int g4399_agent_run(const char *identities, const g4399_agent_config *config,
                    const g4399_agent_hooks *hooks)
{
    if (!config || !hooks || !hooks->transport || !hooks->progress) return -1;

    identity *items = NULL;
    int total = parse_identities(identities, &items);
    if (total <= 0) { free(items); return 0; }

    int target = (config->count > 0 && config->count < total) ? config->count : total;
    int success = 0;

    /* 身份顺序：默认按文件顺序，randomize 时打乱（每个号挑一个没用过的） */
    int *order = malloc(sizeof(int) * (size_t)total);
    if (!order) return -1;
    for (int i = 0; i < total; i++) order[i] = i;
    if (config->randomize) {
        unsigned int seed = (unsigned int)time(NULL) ^ (unsigned int)(uintptr_t)identities;
        FILE *urandom = fopen("/dev/urandom", "rb");
        if (urandom) {
            unsigned int value = 0;
            if (fread(&value, sizeof(value), 1, urandom) == 1) seed ^= value;
            fclose(urandom);
        }
        srand(seed);
        for (int i = total - 1; i > 0; i--) {
            int j = rand() % (i + 1);
            int tmp = order[i];
            order[i] = order[j];
            order[j] = tmp;
        }
    }

    for (int step = 0; step < target; step++) {
        int index = order[step];
        identity *who = &items[index];
        if (hooks->account_start) hooks->account_start(hooks->ctx, step + 1);
        cookie_jar jar = {0};
        account_result result = {0};

        int name_len = 12;
        char *username = g4399_generate_username(name_len);
        char *password = g4399_generate_password(16);
        if (!username || !password) {
            free(username); free(password);
            continue;
        }

        /* 前后缀：前缀/后缀 + 中间随机段，总长 12 */
        if ((config->prefix && *config->prefix) || (config->suffix && *config->suffix)) {
            size_t pre = config->prefix ? strlen(config->prefix) : 0;
            size_t suf = config->suffix ? strlen(config->suffix) : 0;
            int middle = name_len - (int)pre - (int)suf;
            char *tail = middle > 0 ? g4399_generate_username(middle) : NULL;
            sbuf b;
            sbuf_init(&b);
            if (config->prefix) sbuf_add(&b, config->prefix);
            if (tail) sbuf_add(&b, tail);
            if (config->suffix) sbuf_add(&b, config->suffix);
            free(tail);
            free(username);
            username = sbuf_take(&b);
        }

        /* 通道：unified / web / mixed（每个账号随机挑一条） */
        const char *chosen = config->path ? config->path : "unified";
        if (strcmp(chosen, "mixed") == 0) {
            chosen = (rand() % 2 == 0) ? "unified" : "web";
        }
        if (strcmp(chosen, "web") == 0) {
            run_web(hooks, &jar, who, username, password, config->dry_run, &result);
        } else {
            run_unified(hooks, &jar, who, username, password, config, &result);
        }

        if (hooks->progress) {
            hooks->progress(hooks->ctx, index + 1, target, username, password,
                            result.kind, result.ok, result.message);
        }
        if (result.ok) success++;

        free(username);
        free(password);
        jar_free(&jar);

        if (step + 1 < target && config->interval_sec > 0) {
            sleep((unsigned int)config->interval_sec);
        }
    }

    free(order);
    for (int i = 0; i < total; i++) {
        free(items[i].name);
        free(items[i].idcard);
        free(items[i].qq);
    }
    free(items);
    return success;
}
