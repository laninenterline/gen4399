/* JNI：把 Kotlin 的 Callback 适配成 C 侧的 hooks，并把 runBatch 暴露出去。 */
#include "agent.h"
#include "gen4399.h"
#include "payload.h"

#include <jni.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    JNIEnv *env;
    jobject callback;
    jmethodID transport;
    jmethodID progress;
    jmethodID captcha;
    jmethodID fetch_binary;
    jmethodID account_start;
} jni_ctx;

static const char *to_c(JNIEnv *env, jstring value)
{
    return value == NULL ? NULL : (*env)->GetStringUTFChars(env, value, NULL);
}

static void release_c(JNIEnv *env, jstring value, const char *chars)
{
    if (value != NULL && chars != NULL) (*env)->ReleaseStringUTFChars(env, value, chars);
}

/* transport → "status|cookies|body" */
static char *jni_transport(void *ctx, const char *url, const char *method,
                           const char *content_type, const char *body,
                           const char *cookie_header, const char *referer)
{
    jni_ctx *j = (jni_ctx *)ctx;
    JNIEnv *env = j->env;
    jstring j_url = (*env)->NewStringUTF(env, url);
    jstring j_method = (*env)->NewStringUTF(env, method ? method : "GET");
    jstring j_type = (*env)->NewStringUTF(env, content_type ? content_type : "");
    jstring j_body = (*env)->NewStringUTF(env, body ? body : "");
    jstring j_cookie = (*env)->NewStringUTF(env, cookie_header ? cookie_header : "");
    jstring j_referer = (*env)->NewStringUTF(env, referer ? referer : "");

    jobjectArray array = (jobjectArray)(*env)->CallObjectMethod(
        env, j->callback, j->transport, j_url, j_method, j_type, j_body, j_cookie, j_referer);

    (*env)->DeleteLocalRef(env, j_url);
    (*env)->DeleteLocalRef(env, j_method);
    (*env)->DeleteLocalRef(env, j_type);
    (*env)->DeleteLocalRef(env, j_body);
    (*env)->DeleteLocalRef(env, j_cookie);
    (*env)->DeleteLocalRef(env, j_referer);

    if (array == NULL || (*env)->ExceptionCheck(env)) {
        if ((*env)->ExceptionCheck(env)) (*env)->ExceptionClear(env);
        return NULL;
    }

    jsize count = (*env)->GetArrayLength(env, array);
    const char *parts[3] = {"0", "", ""};
    char *owned[3] = {NULL, NULL, NULL};
    for (jsize i = 0; i < count && i < 3; i++) {
        jstring item = (jstring)(*env)->GetObjectArrayElement(env, array, i);
        owned[i] = item ? strdup((*env)->GetStringUTFChars(env, item, NULL)) : strdup("");
        if (item) {
            const char *chars = (*env)->GetStringUTFChars(env, item, NULL);
            if (chars) (*env)->ReleaseStringUTFChars(env, item, chars);
            (*env)->DeleteLocalRef(env, item);
        }
        parts[i] = owned[i];
    }
    (*env)->DeleteLocalRef(env, array);

    size_t total = strlen(parts[0]) + strlen(parts[1]) + strlen(parts[2]) + 3;
    char *joined = malloc(total);
    if (joined) snprintf(joined, total, "%s|%s|%s", parts[0], parts[1], parts[2]);
    for (int i = 0; i < 3; i++) free(owned[i]);
    return joined;
}

static void jni_progress(void *ctx, int index, int total, const char *username,
                         const char *password, const char *kind, int ok,
                         const char *message)
{
    jni_ctx *j = (jni_ctx *)ctx;
    JNIEnv *env = j->env;
    jstring j_user = (*env)->NewStringUTF(env, username ? username : "");
    jstring j_pass = (*env)->NewStringUTF(env, password ? password : "");
    jstring j_kind = (*env)->NewStringUTF(env, kind ? kind : "");
    jstring j_msg = (*env)->NewStringUTF(env, message ? message : "");
    (*env)->CallVoidMethod(env, j->callback, j->progress, index, total, j_user, j_pass,
                           j_kind, ok ? JNI_TRUE : JNI_FALSE, j_msg);
    (*env)->DeleteLocalRef(env, j_user);
    (*env)->DeleteLocalRef(env, j_pass);
    (*env)->DeleteLocalRef(env, j_kind);
    (*env)->DeleteLocalRef(env, j_msg);
    if ((*env)->ExceptionCheck(env)) (*env)->ExceptionClear(env);
}

static unsigned char *jni_fetch_binary(void *ctx, const char *url,
                                       const char *cookie_header, const char *referer,
                                       int *length, int *status)
{
    jni_ctx *j = (jni_ctx *)ctx;
    JNIEnv *env = j->env;
    *length = 0;
    *status = 0;
    if (!j->fetch_binary) return NULL;

    jstring j_url = (*env)->NewStringUTF(env, url);
    jstring j_cookie = (*env)->NewStringUTF(env, cookie_header ? cookie_header : "");
    jstring j_referer = (*env)->NewStringUTF(env, referer ? referer : "");
    jobjectArray array = (jobjectArray)(*env)->CallObjectMethod(
        env, j->callback, j->fetch_binary, j_url, j_cookie, j_referer);
    (*env)->DeleteLocalRef(env, j_url);
    (*env)->DeleteLocalRef(env, j_cookie);
    (*env)->DeleteLocalRef(env, j_referer);

    if (array == NULL || (*env)->ExceptionCheck(env)) {
        if ((*env)->ExceptionCheck(env)) (*env)->ExceptionClear(env);
        return NULL;
    }

    jstring j_status = (jstring)(*env)->GetObjectArrayElement(env, array, 0);
    jbyteArray j_bytes = (jbyteArray)(*env)->GetObjectArrayElement(env, array, 1);
    if (j_status) {
        const char *chars = (*env)->GetStringUTFChars(env, j_status, NULL);
        if (chars) { *status = atoi(chars); (*env)->ReleaseStringUTFChars(env, j_status, chars); }
        (*env)->DeleteLocalRef(env, j_status);
    }
    unsigned char *buffer = NULL;
    if (j_bytes) {
        jsize size = (*env)->GetArrayLength(env, j_bytes);
        if (size > 0) {
            buffer = malloc((size_t)size);
            if (buffer) {
                (*env)->GetByteArrayRegion(env, j_bytes, 0, size, (jbyte *)buffer);
                *length = (int)size;
            }
        }
        (*env)->DeleteLocalRef(env, j_bytes);
    }
    (*env)->DeleteLocalRef(env, array);
    return buffer;
}

static void jni_account_start(void *ctx, int index)
{
    jni_ctx *j = (jni_ctx *)ctx;
    JNIEnv *env = j->env;
    if (!j->account_start) return;
    (*env)->CallVoidMethod(env, j->callback, j->account_start, index);
    if ((*env)->ExceptionCheck(env)) (*env)->ExceptionClear(env);
}

static char *jni_captcha(void *ctx, const unsigned char *image, int length)
{
    jni_ctx *j = (jni_ctx *)ctx;
    JNIEnv *env = j->env;
    jbyteArray bytes = (*env)->NewByteArray(env, length);
    if (bytes == NULL) return NULL;
    (*env)->SetByteArrayRegion(env, bytes, 0, length, (const jbyte *)image);

    jstring answer = (jstring)(*env)->CallObjectMethod(env, j->callback, j->captcha, bytes);
    (*env)->DeleteLocalRef(env, bytes);
    if (answer == NULL || (*env)->ExceptionCheck(env)) {
        if ((*env)->ExceptionCheck(env)) (*env)->ExceptionClear(env);
        return NULL;
    }
    const char *chars = (*env)->GetStringUTFChars(env, answer, NULL);
    char *copy = chars ? strdup(chars) : NULL;
    if (chars) (*env)->ReleaseStringUTFChars(env, answer, chars);
    (*env)->DeleteLocalRef(env, answer);
    return copy;
}

JNIEXPORT jint JNICALL
Java_io_gen4399_app_Native_runBatch(JNIEnv *env, jobject thiz, jstring identities,
                                    jstring path, jint count, jstring prefix,
                                    jstring suffix, jint intervalSec, jboolean dryRun,
                                    jboolean sendRealname, jboolean randomize,
                                    jobject callback)
{
    (void)thiz;
    if (callback == NULL) return -1;

    jclass cls = (*env)->GetObjectClass(env, callback);
    jni_ctx ctx;
    ctx.env = env;
    ctx.callback = callback;
    ctx.transport = (*env)->GetMethodID(env, cls, "transport",
        "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)[Ljava/lang/String;");
    ctx.progress = (*env)->GetMethodID(env, cls, "onProgress",
        "(IILjava/lang/String;Ljava/lang/String;Ljava/lang/String;ZLjava/lang/String;)V");
    ctx.captcha = (*env)->GetMethodID(env, cls, "askCaptcha", "([B)Ljava/lang/String;");
    ctx.fetch_binary = (*env)->GetMethodID(env, cls, "fetchBinary",
        "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;)[Ljava/lang/Object;");
    ctx.account_start = (*env)->GetMethodID(env, cls, "onAccountStart", "(I)V");
    if (!ctx.transport || !ctx.progress || !ctx.captcha || !ctx.fetch_binary || !ctx.account_start) return -1;

    const char *c_ids = to_c(env, identities);
    const char *c_path = to_c(env, path);
    const char *c_prefix = to_c(env, prefix);
    const char *c_suffix = to_c(env, suffix);

    g4399_agent_config config;
    memset(&config, 0, sizeof(config));
    config.path = c_path;
    config.count = (int)count;
    config.prefix = c_prefix;
    config.suffix = c_suffix;
    config.interval_sec = (int)intervalSec;
    config.dry_run = dryRun ? 1 : 0;
    config.send_realname = sendRealname ? 1 : 0;
    config.randomize = randomize ? 1 : 0;
    config.app_id = "u4399";
    config.level = 4;

    g4399_agent_hooks hooks;
    hooks.ctx = &ctx;
    hooks.transport = jni_transport;
    hooks.progress = jni_progress;
    hooks.fetch_binary = jni_fetch_binary;
    hooks.captcha = jni_captcha;
    hooks.account_start = jni_account_start;
    hooks.log = NULL;

    jint result = (jint)g4399_agent_run(c_ids, &config, &hooks);

    release_c(env, identities, c_ids);
    release_c(env, path, c_path);
    release_c(env, prefix, c_prefix);
    release_c(env, suffix, c_suffix);
    (*env)->DeleteLocalRef(env, cls);
    return result;
}
