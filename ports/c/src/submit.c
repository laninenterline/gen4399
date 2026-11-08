/* 注册（unified / web）与登录。 */
#include "gen4399.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define UNIFIED_URL "https://ptlogin.4399.com/ptlogin/register.do"
#define REG_FRAME_URL "https://ptlogin.4399.com/ptlogin/regFrame.do"
#define WEB_REG_URL "https://web.4399.com/user/?_c=reg"
#define WEB_CHECK_URL "https://web.4399.com/user/?_c=login&_a=checkUser"
#define LOGIN_URL "https://ptlogin.4399.com/ptlogin/login.do?v=1"

/* 回传会让服务端改走空白「4399提示」页的隐藏域 */
static const char *DROP_FIELDS[] = {
    "crossDomainUrl", "mainDivId", "showRegInfo", "includeFcmInfo", "expandFcmInput",
    "fcmFakeValidate", "realnameValidate", "userNameLabel", "iframeId",
    "email", "reg_eula_agree", "autoLogin", "fCaptcha", NULL,
};

static const char *LOGIN_COOKIES[] = {
    "Pauth", "Pauths", "Uauth", "Xauth", "Puser", "Pnick", "Qnick",
    "user_4399", "ck_accname", "ptusertype", NULL,
};

/* ---------- 小工具 ---------- */

typedef struct {
    char *data;
    size_t len;
    size_t cap;
} sbuf;

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

static void sbuf_free(sbuf *b) { free(b->data); b->data = NULL; b->len = b->cap = 0; }

static char *xml_unescape(const char *src, size_t len)
{
    char *out = malloc(len + 1);
    if (!out) return NULL;
    size_t pos = 0;
    for (size_t i = 0; i < len; i++) {
        if (src[i] == '&' && i + 4 < len && strncmp(src + i, "&amp;", 5) == 0) {
            out[pos++] = '&'; i += 4;
        } else if (src[i] == '&' && i + 5 < len && strncmp(src + i, "&quot;", 6) == 0) {
            out[pos++] = '"'; i += 5;
        } else if (src[i] == '&' && i + 3 < len && strncmp(src + i, "&#39;", 5) == 0) {
            out[pos++] = '\''; i += 4;
        } else {
            out[pos++] = src[i];
        }
    }
    out[pos] = '\0';
    return out;
}

static int is_form_safe(int c)
{
    return isalnum(c) || c == '-' || c == '_' || c == '.' || c == '~';
}

/* application/x-www-form-urlencoded（空格变 +，其余 %XX） */
static void sbuf_add_encoded(sbuf *b, const char *value)
{
    static const char hex[] = "0123456789ABCDEF";
    char pair[4];
    for (const unsigned char *p = (const unsigned char *)value; *p; p++) {
        if (is_form_safe(*p)) {
            char one[2] = {(char)*p, '\0'};
            sbuf_add(b, one);
        } else if (*p == ' ') {
            sbuf_add(b, "+");
        } else {
            pair[0] = '%';
            pair[1] = hex[(*p >> 4) & 0xF];
            pair[2] = hex[*p & 0xF];
            pair[3] = '\0';
            sbuf_add(b, pair);
        }
    }
}

/* ---------- 表单解析 ---------- */

typedef struct {
    char name[64];
    char value[1024];
} form_field;

typedef struct {
    form_field fields[64];
    int count;
    char action[512];
    char sec[8];
} form_snapshot;

static void extract_attr(const char *tag, const char *attr, char *out, size_t out_len)
{
    out[0] = '\0';
    char pattern[32];
    snprintf(pattern, sizeof(pattern), "%s=", attr);
    const char *p = tag;
    while ((p = strstr(p, pattern)) != NULL) {
        const char *q = p + strlen(pattern);
        char quote = *q;
        if (quote != '"' && quote != '\'') { p = q; continue; }
        const char *start = q + 1;
        const char *end = strchr(start, quote);
        if (!end) return;
        size_t n = (size_t)(end - start);
        if (n >= out_len) n = out_len - 1;
        memcpy(out, start, n);
        out[n] = '\0';
        return;
    }
}

static void parse_form(const char *body, form_snapshot *form)
{
    memset(form, 0, sizeof(*form));
    snprintf(form->action, sizeof(form->action), "%s", UNIFIED_URL);
    const char *form_tag = strstr(body, "<form");
    if (form_tag) {
        const char *tag_end = strchr(form_tag, '>');
        if (tag_end) {
            char *tag = strndup(form_tag, (size_t)(tag_end - form_tag) + 1);
            char action[512] = {0};
            extract_attr(tag, "action", action, sizeof(action));
            if (action[0]) {
                char *decoded = xml_unescape(action, strlen(action));
                if (decoded) {
                    if (strncmp(decoded, "//", 2) == 0)
                        snprintf(form->action, sizeof(form->action), "https:%s", decoded);
                    else if (decoded[0] == '/')
                        snprintf(form->action, sizeof(form->action),
                                 "https://ptlogin.4399.com%s", decoded);
                    else
                        snprintf(form->action, sizeof(form->action), "%s", decoded);
                    free(decoded);
                }
            }
            free(tag);
        }
    }

    const char *p = body;
    while ((p = strstr(p, "<input")) != NULL) {
        const char *end = strchr(p, '>');
        if (!end) break;
        char *tag = strndup(p, (size_t)(end - p) + 1);
        char type[32] = {0}, name[64] = {0}, value[1024] = {0};
        extract_attr(tag, "type", type, sizeof(type));
        extract_attr(tag, "name", name, sizeof(name));
        extract_attr(tag, "value", value, sizeof(value));
        free(tag);
        if (strcasecmp(type, "hidden") == 0 && name[0] && form->count < 64) {
            snprintf(form->fields[form->count].name, 64, "%s", name);
            char *decoded = xml_unescape(value, strlen(value));
            snprintf(form->fields[form->count].value, 1024, "%s", decoded ? decoded : "");
            free(decoded);
            form->count++;
        }
        p = end + 1;
    }

    for (int i = 0; i < form->count; i++) {
        if (strcmp(form->fields[i].name, "sec") == 0) {
            snprintf(form->sec, sizeof(form->sec), "%s", form->fields[i].value);
            break;
        }
    }
    if (!form->sec[0]) snprintf(form->sec, sizeof(form->sec), "1");
}

static int is_dropped(const char *name)
{
    for (int i = 0; DROP_FIELDS[i]; i++) {
        if (strcmp(DROP_FIELDS[i], name) == 0) return 1;
    }
    return 0;
}

/* ---------- 响应判定 ---------- */

static void extract_msg(const char *body, char *out, size_t out_len)
{
    out[0] = '\0';
    const char *msg = strstr(body, "id=\"Msg\"");
    if (!msg) msg = strstr(body, "id='Msg'");
    if (!msg) return;
    const char *start = strchr(msg, '>');
    if (!start) return;
    start++;
    const char *end = strstr(start, "</div>");
    if (!end) return;
    size_t n = (size_t)(end - start);
    if (n >= out_len) n = out_len - 1;
    size_t pos = 0;
    for (size_t i = 0; i < n && pos + 1 < out_len; i++) {
        if (start[i] == '<') { while (i < n && start[i] != '>') i++; continue; }
        if (!isspace((unsigned char)start[i]) || (pos && out[pos - 1] != ' ')) out[pos++] = start[i];
    }
    out[pos] = '\0';
    while (pos && isspace((unsigned char)out[pos - 1])) out[--pos] = '\0';
}

static void set_result(g4399_submit_result *r, const char *kind, int ok, const char *message)
{
    snprintf(r->kind, sizeof(r->kind), "%s", kind);
    r->ok = ok;
    snprintf(r->message, sizeof(r->message), "%s", message);
}

/* ---------- 提交 ---------- */

static int submit_unified(const g4399_submit_options *o, g4399_submit_result *r)
{
    sbuf url;
    sbuf_init(&url);
    sbuf_add(&url, REG_FRAME_URL "?regMode=reg_normal&postLoginHandler=refreshParent"
             "&displayMode=&bizId=&redirectUrl=&css=&appId=");
    sbuf_add(&url, o->app_id ? o->app_id : "u4399");
    char tail[256];
    snprintf(tail, sizeof(tail),
             "&gameId=&noEmail=false&regIdcard=true&autoLogin=false&cid=&aid=&ref="
             "&level=%d&mainDivId=popup_reg_div&includeFcmInfo=false&externalLogin=qq"
             "&fcmFakeValidate=false&expandFcmInput=false&userNameLabel=&userNameTip="
             "&welcomeTip=&v=%ld",
             o->level > 0 ? o->level : 4, (long)time(NULL) * 1000);
    sbuf_add(&url, tail);

    g4399_session *session = g4399_session_new(o->timeout);
    if (!session) { sbuf_free(&url); return -1; }

    char *page = NULL;
    size_t page_len = 0;
    if (g4399_http_get(session, url.data, &page, &page_len) != 0) {
        g4399_session_free(session); sbuf_free(&url); return -1;
    }
    if (strstr(page, "请稍后再试")) {
        set_result(r, "throttled", 0, "服务端限流（请稍后再试），请过一会儿再试");
        free(page); g4399_session_free(session); sbuf_free(&url);
        return 0;
    }

    form_snapshot form;
    parse_form(page, &form);
    free(page);
    if (form.count == 0) {
        set_result(r, "unknown", 0, "注册页没有隐藏域，可能是风控页");
        g4399_session_free(session); sbuf_free(&url);
        return 0;
    }

    /* 组装 payload：隐藏域（剔除名单除外） + 账号密码 + 实名 */
    sbuf payload;
    sbuf_init(&payload);
    char *encrypted[4] = {0};
    int field_count = 0, encrypted_count = 0;
    int sec = strcmp(form.sec, "1") == 0;

    for (int i = 0; i < form.count; i++) {
        if (is_dropped(form.fields[i].name)) continue;
        if (field_count++) sbuf_add(&payload, "&");
        sbuf_add_encoded(&payload, form.fields[i].name);
        sbuf_add(&payload, "=");
        sbuf_add_encoded(&payload, form.fields[i].value);
    }

    struct { const char *name; const char *value; int secret; } extra[] = {
        {"username", o->username, 0},
        {"password", o->password, 1},
        {"passwordveri", o->password, 1},
        {"realname", o->realname ? o->realname : "", o->send_realname},
        {"idcard", o->idcard ? o->idcard : "", o->send_realname},
    };
    if (!o->send_realname) extra[3].secret = 0;   /* 关掉实名时两个都不加 */

    for (size_t i = 0; i < sizeof(extra) / sizeof(extra[0]); i++) {
        if (!o->send_realname && (strcmp(extra[i].name, "realname") == 0 ||
                                  strcmp(extra[i].name, "idcard") == 0)) continue;
        if (field_count++) sbuf_add(&payload, "&");
        sbuf_add_encoded(&payload, extra[i].name);
        sbuf_add(&payload, "=");
        if (extra[i].secret && sec) {
            char *cipher = g4399_aes_encrypt(extra[i].value, NULL);
            if (cipher) {
                sbuf_add_encoded(&payload, cipher);
                if (encrypted_count < 4) encrypted[encrypted_count] = cipher;
                encrypted_count++;
                if (encrypted_count > 4) free(cipher);
                continue;
            }
        }
        sbuf_add_encoded(&payload, extra[i].value);
    }

    r->field_count = field_count;
    r->encrypted_count = encrypted_count;
    snprintf(r->kind, sizeof(r->kind), "%s", "dry_run");
    r->ok = 0;
    snprintf(r->message, sizeof(r->message),
             "%s", o->dry_run ? "dry-run：未发送注册 POST" : "");

    if (!o->dry_run) {
        g4399_session_set_referer(session, url.data);
        char *body = NULL;
        size_t body_len = 0;
        if (g4399_http_post(session, form.action, payload.data, NULL, &body, &body_len) != 0) {
            set_result(r, "error", 0, "注册 POST 失败");
        } else if (strstr(body, "isAutoRegSuccess = true") || strstr(body, "自动注册成功")) {
            set_result(r, "success", 1, "注册成功（页面返回 isAutoRegSuccess=true）");
        } else if (strstr(body, "请稍后再试")) {
            set_result(r, "throttled", 0, "服务端限流（请稍后再试）");
        } else if (strstr(body, "inputCaptcha")) {
            set_result(r, "captcha", 0, "服务端要求图形验证码（inputCaptcha），C 版未内置识别");
        } else {
            char msg[256];
            extract_msg(body, msg, sizeof(msg));
            if (msg[0]) set_result(r, "rejected", 0, msg);
            else set_result(r, "unknown", 0, "无法判定注册结果");
        }
        free(body);
    }

    for (int i = 0; i < 4; i++) free(encrypted[i]);
    sbuf_free(&payload);
    g4399_session_free(session);
    sbuf_free(&url);
    return 0;
}

static int submit_web(const g4399_submit_options *o, g4399_submit_result *r)
{
    g4399_session *session = g4399_session_new(o->timeout);
    if (!session) return -1;

    sbuf check;
    sbuf_init(&check);
    sbuf_add(&check, WEB_CHECK_URL "&user=");
    sbuf_add_encoded(&check, o->username);
    sbuf_add(&check, "&jsoncallback=cb");

    char *check_body = NULL;
    size_t check_len = 0;
    char encrypt_code[64] = "5c43e3";
    if (g4399_http_get(session, check.data, &check_body, &check_len) == 0) {
        const char *data = strstr(check_body, "\"data\"");
        if (data) {
            const char *colon = strchr(data, ':');
            if (colon) {
                const char *start = strchr(colon, '"');
                if (start) {
                    const char *end = strchr(start + 1, '"');
                    if (end && (size_t)(end - start - 1) < sizeof(encrypt_code)) {
                        memcpy(encrypt_code, start + 1, (size_t)(end - start - 1));
                        encrypt_code[end - start - 1] = '\0';
                    }
                }
            }
        }
    }
    free(check_body);
    sbuf_free(&check);

    char *pwd_cipher = g4399_encode_4399(o->password, encrypt_code);
    if (!pwd_cipher) { g4399_session_free(session); return -1; }

    sbuf payload;
    sbuf_init(&payload);
    sbuf_add(&payload, "cid=3000&login_name=");
    sbuf_add_encoded(&payload, o->username);
    sbuf_add(&payload, "&login_password=");
    sbuf_add_encoded(&payload, pwd_cipher);
    sbuf_add(&payload, "&relogin_pwd=");
    sbuf_add_encoded(&payload, pwd_cipher);
    sbuf_add(&payload, "&qq=");
    sbuf_add_encoded(&payload, o->qq ? o->qq : "");
    sbuf_add(&payload, "&true_name=");
    sbuf_add_encoded(&payload, o->realname ? o->realname : "");
    sbuf_add(&payload, "&sfz=");
    sbuf_add_encoded(&payload, o->idcard ? o->idcard : "");
    sbuf_add(&payload, "&encrypt=1");

    r->field_count = 8;
    r->encrypted_count = 2;
    if (o->dry_run) {
        set_result(r, "dry_run", 0, "dry-run：未发送注册 POST");
    } else {
        char *body = NULL;
        size_t body_len = 0;
        if (g4399_http_post(session, WEB_REG_URL "&jsoncallback=cb",
                            payload.data, NULL, &body, &body_len) != 0) {
            set_result(r, "error", 0, "注册 POST 失败");
        } else if (strstr(body, "\"state\":true")) {
            set_result(r, "success", 1, "注册成功（state=true）");
        } else if (strstr(body, "\"code\":200")) {
            set_result(r, "captcha", 0, "服务端要求图形验证码（code=200），C 版未内置识别");
        } else if (strstr(body, "请稍后再试")) {
            set_result(r, "throttled", 0, "服务端限流");
        } else {
            set_result(r, "rejected", 0, "注册被拒绝（响应非 state=true）");
        }
        free(body);
    }

    free(pwd_cipher);
    sbuf_free(&payload);
    g4399_session_free(session);
    return 0;
}

int g4399_submit(const g4399_submit_options *o, g4399_submit_result *r)
{
    if (!o || !r) return -1;
    memset(r, 0, sizeof(*r));
    if (!o->username || !o->password) return -1;
    if (!o->path || strcmp(o->path, "unified") == 0) return submit_unified(o, r);
    if (strcmp(o->path, "web") == 0) return submit_web(o, r);
    return -1;
}

int g4399_login(const char *username, const char *password, long timeout,
                g4399_login_result *result)
{
    if (!username || !password || !result) return -1;
    memset(result, 0, sizeof(*result));

    char *cipher = g4399_aes_encrypt(password, NULL);
    if (!cipher) return -1;

    sbuf body;
    sbuf_init(&body);
    sbuf_add(&body, "appId=u4399&username=");
    sbuf_add_encoded(&body, username);
    sbuf_add(&body, "&password=");
    sbuf_add_encoded(&body, cipher);
    sbuf_add(&body, "&sec=1");

    g4399_session *session = g4399_session_new(timeout);
    if (!session) { free(cipher); sbuf_free(&body); return -1; }

    char *response = NULL;
    size_t response_len = 0;
    int rc = g4399_http_post(session, LOGIN_URL, body.data, NULL, &response, &response_len);
    if (getenv("GEN4399_DEBUG")) {
        fprintf(stderr, "[debug] login rc=%d len=%zu\n", rc, response_len);
        if (response) fprintf(stderr, "[debug] body[:300]=%.300s\n", response);
    }
    free(cipher);
    sbuf_free(&body);
    if (rc != 0) { g4399_session_free(session); return -1; }

    /* 登录成功的判据：会话里出现 Pauth / Uauth 之类的登录 Cookie */
    int cookie_count = 0;
    for (int i = 0; LOGIN_COOKIES[i]; i++) {
        if (g4399_session_has_cookie(session, LOGIN_COOKIES[i])) cookie_count++;
    }
    result->cookie_count = cookie_count;
    if (strstr(response, "请稍后再试")) {
        snprintf(result->kind, sizeof(result->kind), "throttled");
        snprintf(result->message, sizeof(result->message), "登录被限流（请稍后再试）");
        result->ok = 0;
        free(response);
        g4399_session_free(session);
        return 0;
    }
    if (cookie_count > 0) {
        snprintf(result->kind, sizeof(result->kind), "success");
        snprintf(result->message, sizeof(result->message), "登录成功");
        result->ok = 1;
    } else {
        char msg[256];
        extract_msg(response, msg, sizeof(msg));
        if (msg[0]) {
            snprintf(result->kind, sizeof(result->kind), "rejected");
            snprintf(result->message, sizeof(result->message), "%s", msg);
        } else {
            snprintf(result->kind, sizeof(result->kind), "unknown");
            snprintf(result->message, sizeof(result->message), "无法判定登录结果");
        }
        result->ok = 0;
    }
    free(response);
    g4399_session_free(session);
    return 0;
}
