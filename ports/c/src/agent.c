/* 批量注册编排：全部业务逻辑在这里，Kotlin 只做展示与 HTTP 传输。 */
#include "agent.h"
#include "gen4399.h"
#include "payload.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* 身份数量硬上限：25MB 的 sfz.txt 可能有上百万行，这里兜底防止内存爆掉 */
#define MAX_IDENTITIES 5000

#define UNIFIED_REGISTER_URL "https://ptlogin.4399.com/ptlogin/register.do"
#define UNIFIED_CAPTCHA_URL "https://ptlogin.4399.com/ptlogin/captcha.do?captchaId="
#define WEB_REG_URL "https://web.4399.com/user/?_c=reg&jsoncallback=cb"
#define WEB_CHECK_URL "https://web.4399.com/user/?_c=login&_a=checkUser"
#define WEB_CAPTCHA_URL "https://web.4399.com/util/?_c=code&t=reg"

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
} http_result;

static http_result do_request(const g4399_agent_hooks *hooks, cookie_jar *jar,
                              const char *url, const char *method,
                              const char *content_type, const char *body)
{
    http_result result = {0, NULL};
    char *cookie_header = jar_header(jar);
    char *raw = hooks->transport(hooks->ctx, url, method, content_type,
                                 body ? body : "", cookie_header);
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
    free(raw);
    return result;
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
    http_result probe = do_request(hooks, jar, check.data, "GET", NULL, NULL);
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
                                      "application/x-www-form-urlencoded", payload.data);
    for (int round = 0; round < 3 && response.body; round++) {
        classify_into("web", response.status, response.body, result->kind, sizeof(result->kind),
                      result->message, sizeof(result->message));
        if (strcmp(result->kind, "captcha") != 0) break;

        http_result image = do_request(hooks, jar, WEB_CAPTCHA_URL, "GET", NULL, NULL);
        if (!image.body) break;
        char *code = hooks->captcha(hooks->ctx, (const unsigned char *)image.body, (int)strlen(image.body));
        free(image.body);
        if (!code || !*code) { free(code); break; }

        sbuf retry;
        sbuf_init(&retry);
        sbuf_add(&retry, payload.data);
        sbuf_add(&retry, "&chk_code=");
        sbuf_add_encoded(&retry, code);
        free(code);
        free(response.body);
        response = do_request(hooks, jar, WEB_REG_URL, "POST",
                              "application/x-www-form-urlencoded", retry.data);
        free(retry.data);
    }
    if (response.body) {
        classify_into("web", response.status, response.body, result->kind, sizeof(result->kind),
                      result->message, sizeof(result->message));
    }
    free(response.body);
    free(payload.data);
    result->ok = strcmp(result->kind, "success") == 0;
}

static void run_unified(const g4399_agent_hooks *hooks, cookie_jar *jar, const identity *who,
                        const char *username, const char *password, const g4399_agent_config *config,
                        account_result *result)
{
    char *form_url = g4399_form_url(config->app_id, config->level);
    http_result page = do_request(hooks, jar, form_url, "GET", NULL, NULL);
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
                                      "application/x-www-form-urlencoded", body);
    for (int round = 0; round < 3 && response.body; round++) {
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
        http_result image = do_request(hooks, jar, image_url.data, "GET", NULL, NULL);
        free(image_url.data);
        if (!image.body) { free(captcha_id); break; }
        char *code = hooks->captcha(hooks->ctx, (const unsigned char *)image.body, (int)strlen(image.body));
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
                              "application/x-www-form-urlencoded", with_code.data);
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

    for (int index = 0; index < target; index++) {
        identity *who = &items[index];
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

        if (config->path && strcmp(config->path, "web") == 0) {
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

        if (index + 1 < target && config->interval_sec > 0) {
            sleep((unsigned int)config->interval_sec);
        }
    }

    for (int i = 0; i < total; i++) {
        free(items[i].name);
        free(items[i].idcard);
        free(items[i].qq);
    }
    free(items);
    return success;
}
