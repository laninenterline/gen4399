/* 基于 libcurl 的极简 HTTP 会话（自动维护 Cookie）。 */
#include "gen4399.h"

#include <curl/curl.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

struct g4399_session {
    CURL *curl;
    struct curl_slist *headers;
    long timeout;
};

static int g_curl_ready = 0;

typedef struct {
    char *data;
    size_t len;
} http_buffer;

static size_t write_cb(char *data, size_t size, size_t nmemb, void *userdata)
{
    size_t len = size * nmemb;
    http_buffer *buffer = (http_buffer *)userdata;
    char *grown = realloc(buffer->data, buffer->len + len + 1);
    if (!grown) return 0;
    memcpy(grown + buffer->len, data, len);
    buffer->len += len;
    grown[buffer->len] = '\0';
    buffer->data = grown;
    return len;
}

g4399_session *g4399_session_new(long timeout_seconds)
{
    if (!g_curl_ready) {
        if (curl_global_init(CURL_GLOBAL_DEFAULT) != CURLE_OK) return NULL;
        g_curl_ready = 1;
    }
    g4399_session *session = calloc(1, sizeof(*session));
    if (!session) return NULL;
    session->curl = curl_easy_init();
    if (!session->curl) { free(session); return NULL; }
    session->timeout = timeout_seconds > 0 ? timeout_seconds : 15;
    session->headers = curl_slist_append(NULL, "Accept: */*");
    session->headers = curl_slist_append(session->headers, "Accept-Language: zh-CN,zh;q=0.9");
    session->headers = curl_slist_append(
        session->headers, "Content-Type: application/x-www-form-urlencoded");
    session->headers = curl_slist_append(session->headers, "Origin: https://ptlogin.4399.com");
    curl_easy_setopt(session->curl, CURLOPT_COOKIEFILE, "");      /* 启用 Cookie 引擎 */
    curl_easy_setopt(session->curl, CURLOPT_FOLLOWLOCATION, 1L);
    /* 4399 对 HTTP/2 的 POST 会直接回「请稍后再试」，强制走 1.1 */
    curl_easy_setopt(session->curl, CURLOPT_HTTP_VERSION, CURL_HTTP_VERSION_1_1);
    curl_easy_setopt(session->curl, CURLOPT_TIMEOUT, session->timeout);
    curl_easy_setopt(session->curl, CURLOPT_REFERER, "https://ptlogin.4399.com/");
    curl_easy_setopt(session->curl, CURLOPT_USERAGENT,
                     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36");
    return session;
}

void g4399_session_free(g4399_session *session)
{
    if (!session) return;
    if (session->headers) curl_slist_free_all(session->headers);
    if (session->curl) curl_easy_cleanup(session->curl);
    free(session);
}

void g4399_session_set_referer(g4399_session *session, const char *referer)
{
    if (!session) return;
    curl_easy_setopt(session->curl, CURLOPT_REFERER, referer);
}

static int perform(g4399_session *session, const char *url,
                   const char *body, const char *content_type,
                   char **out, size_t *out_len)
{
    if (!session || !url || !out) return -1;
    http_buffer buffer = {0};
    buffer.data = calloc(1, 1);
    if (!buffer.data) return -1;

    (void)content_type;   /* 本库只发 form-urlencoded，Content-Type 固定在会话头里 */

    curl_easy_setopt(session->curl, CURLOPT_URL, url);
    curl_easy_setopt(session->curl, CURLOPT_HTTPHEADER, session->headers);
    curl_easy_setopt(session->curl, CURLOPT_WRITEFUNCTION, write_cb);
    curl_easy_setopt(session->curl, CURLOPT_WRITEDATA, &buffer);

    if (body) {
        curl_easy_setopt(session->curl, CURLOPT_POST, 1L);
        curl_easy_setopt(session->curl, CURLOPT_POSTFIELDS, body);
    } else {
        curl_easy_setopt(session->curl, CURLOPT_HTTPGET, 1L);
    }

    CURLcode code = curl_easy_perform(session->curl);
    if (code != CURLE_OK) {
        free(buffer.data);
        return -1;
    }
    *out = buffer.data;
    if (out_len) *out_len = buffer.len;
    return 0;
}

int g4399_http_get(g4399_session *session, const char *url, char **out, size_t *out_len)
{
    return perform(session, url, NULL, NULL, out, out_len);
}

int g4399_http_post(g4399_session *session, const char *url, const char *body,
                    const char *content_type, char **out, size_t *out_len)
{
    return perform(session, url, body, content_type ? content_type
                   : "application/x-www-form-urlencoded", out, out_len);
}

int g4399_session_has_cookie(g4399_session *session, const char *name)
{
    if (!session || !name) return 0;
    struct curl_slist *cookies = NULL;
    if (curl_easy_getinfo(session->curl, CURLINFO_COOKIELIST, &cookies) != CURLE_OK) return 0;
    int found = 0;
    for (struct curl_slist *item = cookies; item && !found; item = item->next) {
        /* 每行格式：domain<TAB>flag<TAB>path<TAB>secure<TAB>expiry<TAB>name<TAB>value */
        const char *cursor = item->data;
        int tabs = 0;
        while (*cursor) {
            if (*cursor == '\t' && ++tabs == 5) {
                cursor++;
                size_t len = strlen(name);
                if (strncmp(cursor, name, len) == 0 && (cursor[len] == '\t' || cursor[len] == '\0')) {
                    found = 1;
                }
                break;
            }
            cursor++;
        }
    }
    curl_slist_free_all(cookies);
    return found;
}
