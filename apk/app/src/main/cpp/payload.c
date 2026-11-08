/* 纯逻辑部分：表单地址、隐藏域解析、unified 载荷组装、响应判定。
 * 不依赖网络库，命令行（libcurl）和 Android JNI 共用这一份。 */
#include "gen4399.h"
#include "payload.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static const char *DROP_FIELDS[] = {
    "crossDomainUrl", "mainDivId", "showRegInfo", "includeFcmInfo", "expandFcmInput",
    "fcmFakeValidate", "realnameValidate", "userNameLabel", "iframeId",
    "email", "reg_eula_agree", "autoLogin", "fCaptcha", NULL,
};

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

static int is_form_safe(int c)
{
    return isalnum(c) || c == '-' || c == '_' || c == '.' || c == '~';
}

static void sbuf_add_encoded(sbuf *b, const char *value)
{
    static const char hex[] = "0123456789ABCDEF";
    char tri[4];
    for (const unsigned char *p = (const unsigned char *)value; p && *p; p++) {
        if (is_form_safe(*p)) {
            char one[2] = {(char)*p, '\0'};
            sbuf_add(b, one);
        } else if (*p == ' ') {
            sbuf_add(b, "+");
        } else {
            tri[0] = '%';
            tri[1] = hex[(*p >> 4) & 0xF];
            tri[2] = hex[*p & 0xF];
            tri[3] = '\0';
            sbuf_add(b, tri);
        }
    }
}

static int is_dropped(const char *name)
{
    for (int i = 0; DROP_FIELDS[i]; i++) {
        if (strcmp(DROP_FIELDS[i], name) == 0) return 1;
    }
    return 0;
}

void g4399_free(char *ptr) { free(ptr); }

char *g4399_form_url(const char *app_id, int level)
{
    sbuf b;
    sbuf_init(&b);
    sbuf_add(&b, "https://ptlogin.4399.com/ptlogin/regFrame.do?regMode=reg_normal"
                 "&postLoginHandler=refreshParent&displayMode=&bizId=&redirectUrl=&css=&appId=");
    sbuf_add_encoded(&b, app_id ? app_id : "u4399");
    char tail[256];
    snprintf(tail, sizeof(tail),
             "&gameId=&noEmail=false&regIdcard=true&autoLogin=false&cid=&aid=&ref="
             "&level=%d&mainDivId=popup_reg_div&includeFcmInfo=false&externalLogin=qq"
             "&fcmFakeValidate=false&expandFcmInput=false&userNameLabel=&userNameTip="
             "&welcomeTip=&v=%ld",
             level > 0 ? level : 4, (long)time(NULL) * 1000);
    sbuf_add(&b, tail);
    return b.data;
}

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

char *g4399_parse_hidden(const char *html)
{
    if (!html) return NULL;
    sbuf b;
    sbuf_init(&b);
    int first = 1;
    const char *p = html;
    while ((p = strstr(p, "<input")) != NULL) {
        const char *end = strchr(p, '>');
        if (!end) break;
        size_t tag_len = (size_t)(end - p) + 1;
        char *tag = strndup(p, tag_len);
        char type[32] = {0}, name[64] = {0}, value[1024] = {0};
        extract_attr(tag, "type", type, sizeof(type));
        extract_attr(tag, "name", name, sizeof(name));
        extract_attr(tag, "value", value, sizeof(value));
        free(tag);
        if (strcasecmp(type, "hidden") == 0 && name[0]) {
            if (!first) sbuf_add(&b, "\n");
            first = 0;
            sbuf_add(&b, name);
            sbuf_add(&b, "\t");
            sbuf_add(&b, value);
        }
        p = end + 1;
    }
    return b.data;
}

/** 从 "name\tvalue\n..." 里取某个值；没有返回空串 */
static void hidden_lookup(const char *pairs, const char *name, char *out, size_t out_len)
{
    out[0] = '\0';
    if (!pairs) return;
    size_t name_len = strlen(name);
    const char *line = pairs;
    while (*line) {
        const char *eol = strchr(line, '\n');
        size_t len = eol ? (size_t)(eol - line) : strlen(line);
        if (len > name_len && strncmp(line, name, name_len) == 0 && line[name_len] == '\t') {
            size_t vlen = len - name_len - 1;
            if (vlen >= out_len) vlen = out_len - 1;
            memcpy(out, line + name_len + 1, vlen);
            out[vlen] = '\0';
            return;
        }
        if (!eol) break;
        line = eol + 1;
    }
}

char *g4399_build_unified_payload(const char *hidden_pairs, const char *username,
                                  const char *password, const char *realname,
                                  const char *idcard, int send_realname,
                                  int *field_count, int *encrypted_count)
{
    if (!username || !password) return NULL;
    sbuf body;
    sbuf_init(&body);
    int fields = 0, encrypted = 0;

    char sec[8] = {0};
    hidden_lookup(hidden_pairs, "sec", sec, sizeof(sec));
    int use_sec = sec[0] == '\0' || strcmp(sec, "1") == 0;

    /* 1) 隐藏域（剔除黑名单） */
    if (hidden_pairs) {
        const char *line = hidden_pairs;
        while (*line) {
            const char *eol = strchr(line, '\n');
            size_t len = eol ? (size_t)(eol - line) : strlen(line);
            char *pair = strndup(line, len);
            char *tab = strchr(pair, '\t');
            if (tab) {
                *tab = '\0';
                if (!is_dropped(pair)) {
                    if (fields++) sbuf_add(&body, "&");
                    sbuf_add_encoded(&body, pair);
                    sbuf_add(&body, "=");
                    sbuf_add_encoded(&body, tab + 1);
                }
            }
            free(pair);
            if (!eol) break;
            line = eol + 1;
        }
    }

    /* 2) 账号 / 密码 / 实名 */
    struct { const char *name; const char *value; int secret; } extra[] = {
        {"username", username, 0},
        {"password", password, 1},
        {"passwordveri", password, 1},
        {"realname", realname, 1},
        {"idcard", idcard, 1},
    };
    for (size_t i = 0; i < sizeof(extra) / sizeof(extra[0]); i++) {
        int is_identity = strcmp(extra[i].name, "realname") == 0 || strcmp(extra[i].name, "idcard") == 0;
        if (is_identity && !send_realname) continue;
        if (is_identity && (!extra[i].value || !extra[i].value[0])) continue;
        if (fields++) sbuf_add(&body, "&");
        sbuf_add_encoded(&body, extra[i].name);
        sbuf_add(&body, "=");
        if (extra[i].secret && use_sec) {
            char *cipher = g4399_aes_encrypt(extra[i].value, NULL);
            if (cipher) {
                sbuf_add_encoded(&body, cipher);
                encrypted++;
                free(cipher);
                continue;
            }
        }
        sbuf_add_encoded(&body, extra[i].value);
    }

    /* 3) 固定字段 */
    if (fields++) sbuf_add(&body, "&");
    sbuf_add(&body, "appId=u4399&level=4");
    if (strstr(hidden_pairs ? hidden_pairs : "", "regMode\t") == NULL) {
        sbuf_add(&body, "&regMode=reg_normal");
    }
    if (sec[0]) {
        sbuf_add(&body, "&sec=");
        sbuf_add(&body, sec);
    }

    if (field_count) *field_count = fields + 2;
    if (encrypted_count) *encrypted_count = encrypted;
    return body.data;
}

static void extract_msg(const char *body, char *out, size_t out_len)
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

void g4399_classify(const char *path, int status, const char *body,
                    char *kind, size_t kind_len, char *message, size_t message_len)
{
    snprintf(kind, kind_len, "unknown");
    snprintf(message, message_len, "无法判定注册结果");
    if (!body) return;

    if (strstr(body, "请稍后再试") || status == 202) {
        snprintf(kind, kind_len, "throttled");
        snprintf(message, message_len, "服务端限流（请稍后再试）");
        return;
    }

    int is_web = path && strcmp(path, "web") == 0;
    if (is_web) {
        if (strstr(body, "\"state\":true")) {
            snprintf(kind, kind_len, "success");
            snprintf(message, message_len, "注册成功（state=true）");
        } else if (strstr(body, "\"code\":200")) {
            snprintf(kind, kind_len, "captcha");
            snprintf(message, message_len, "服务端要求图形验证码（code=200）");
        } else {
            char snippet[80];
            size_t i = 0;
            for (const char *p = body; *p && i + 1 < sizeof(snippet) && i < 60; p++) {
                snippet[i++] = (*p == '\n' || *p == '\r' || *p == '\t') ? ' ' : *p;
            }
            snippet[i] = '\0';
            snprintf(kind, kind_len, "rejected");
            snprintf(message, message_len, "注册被拒绝（HTTP %d，%zu 字节）：%s",
                     status, strlen(body), snippet);
        }
        return;
    }

    if (strstr(body, "isAutoRegSuccess = true") || strstr(body, "自动注册成功")) {
        snprintf(kind, kind_len, "success");
        snprintf(message, message_len, "注册成功（isAutoRegSuccess=true）");
    } else if (strstr(body, "inputCaptcha")) {
        snprintf(kind, kind_len, "captcha");
        snprintf(message, message_len, "服务端要求图形验证码（inputCaptcha）");
    } else {
        char msg[256];
        extract_msg(body, msg, sizeof(msg));
        if (msg[0]) {
            snprintf(kind, kind_len, "rejected");
            snprintf(message, message_len, "%s", msg);
        } else {
            /* 拿不到 #Msg 时给点线索：状态码 + 响应片段 */
            char snippet[80];
            size_t i = 0;
            for (const char *p = body; *p && i + 1 < sizeof(snippet) && i < 60; p++) {
                snippet[i++] = (*p == '\n' || *p == '\r' || *p == '\t') ? ' ' : *p;
            }
            snippet[i] = '\0';
            snprintf(kind, kind_len, "unknown");
            snprintf(message, message_len, "无法判定（HTTP %d，%zu 字节）：%s",
                     status, strlen(body), snippet);
        }
    }
}
