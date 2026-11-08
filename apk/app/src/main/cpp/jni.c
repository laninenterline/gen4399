/* Android JNI 桥：把 gen4399 的 C 实现暴露给 Kotlin（io.gen4399.app.Native）。 */
#include <stdio.h>
#include "gen4399.h"
#include "payload.h"

#include <jni.h>
#include <stdlib.h>
#include <string.h>

static jstring to_java(JNIEnv *env, char *value)
{
    if (!value) return NULL;
    jstring result = (*env)->NewStringUTF(env, value);
    free(value);
    return result;
}

static const char *to_c(JNIEnv *env, jstring value)
{
    return value == NULL ? NULL : (*env)->GetStringUTFChars(env, value, NULL);
}

static void release_c(JNIEnv *env, jstring value, const char *chars)
{
    if (value != NULL && chars != NULL) (*env)->ReleaseStringUTFChars(env, value, chars);
}

JNIEXPORT jstring JNICALL
Java_io_gen4399_app_Native_generatePassword(JNIEnv *env, jobject thiz, jint length)
{
    (void)thiz;
    return to_java(env, g4399_generate_password((int)length));
}

JNIEXPORT jstring JNICALL
Java_io_gen4399_app_Native_generateUsername(JNIEnv *env, jobject thiz, jint length)
{
    (void)thiz;
    return to_java(env, g4399_generate_username((int)length));
}

JNIEXPORT jstring JNICALL
Java_io_gen4399_app_Native_checkPassword(JNIEnv *env, jobject thiz, jstring value)
{
    (void)thiz;
    const char *text = to_c(env, value);
    const char *reason = g4399_check_password(text);
    release_c(env, value, text);
    return reason ? (*env)->NewStringUTF(env, reason) : NULL;
}

JNIEXPORT jstring JNICALL
Java_io_gen4399_app_Native_checkUsername(JNIEnv *env, jobject thiz, jstring value)
{
    (void)thiz;
    const char *text = to_c(env, value);
    const char *reason = g4399_check_username(text);
    release_c(env, value, text);
    return reason ? (*env)->NewStringUTF(env, reason) : NULL;
}

JNIEXPORT jstring JNICALL
Java_io_gen4399_app_Native_checkIdcard(JNIEnv *env, jobject thiz, jstring value)
{
    (void)thiz;
    const char *text = to_c(env, value);
    const char *reason = g4399_check_idcard(text);
    release_c(env, value, text);
    return reason ? (*env)->NewStringUTF(env, reason) : NULL;
}

JNIEXPORT jstring JNICALL
Java_io_gen4399_app_Native_checkRealname(JNIEnv *env, jobject thiz, jstring value)
{
    (void)thiz;
    const char *text = to_c(env, value);
    const char *reason = g4399_check_realname(text);
    release_c(env, value, text);
    return reason ? (*env)->NewStringUTF(env, reason) : NULL;
}

JNIEXPORT jstring JNICALL
Java_io_gen4399_app_Native_maskIdcard(JNIEnv *env, jobject thiz, jstring value)
{
    (void)thiz;
    const char *text = to_c(env, value);
    char masked[24];
    g4399_mask_idcard(text, masked, sizeof(masked));
    release_c(env, value, text);
    return (*env)->NewStringUTF(env, masked);
}

JNIEXPORT jstring JNICALL
Java_io_gen4399_app_Native_aesEncrypt(JNIEnv *env, jobject thiz, jstring plaintext)
{
    (void)thiz;
    const char *text = to_c(env, plaintext);
    jstring result = to_java(env, g4399_aes_encrypt(text, NULL));
    release_c(env, plaintext, text);
    return result;
}

JNIEXPORT jstring JNICALL
Java_io_gen4399_app_Native_encode4399(JNIEnv *env, jobject thiz, jstring value, jstring key)
{
    (void)thiz;
    const char *text = to_c(env, value);
    const char *k = to_c(env, key);
    jstring result = to_java(env, g4399_encode_4399(text, k));
    release_c(env, value, text);
    release_c(env, key, k);
    return result;
}

JNIEXPORT jstring JNICALL
Java_io_gen4399_app_Native_formUrl(JNIEnv *env, jobject thiz, jstring appId, jint level)
{
    (void)thiz;
    const char *app = to_c(env, appId);
    jstring result = to_java(env, g4399_form_url(app, (int)level));
    release_c(env, appId, app);
    return result;
}

JNIEXPORT jstring JNICALL
Java_io_gen4399_app_Native_parseHidden(JNIEnv *env, jobject thiz, jstring html)
{
    (void)thiz;
    const char *text = to_c(env, html);
    jstring result = to_java(env, g4399_parse_hidden(text));
    release_c(env, html, text);
    return result;
}

JNIEXPORT jstring JNICALL
Java_io_gen4399_app_Native_buildUnifiedPayload(JNIEnv *env, jobject thiz, jstring hidden,
                                               jstring username, jstring password,
                                               jstring realname, jstring idcard,
                                               jboolean sendRealname)
{
    (void)thiz;
    const char *h = to_c(env, hidden);
    const char *u = to_c(env, username);
    const char *p = to_c(env, password);
    const char *r = to_c(env, realname);
    const char *i = to_c(env, idcard);
    char *body = g4399_build_unified_payload(h, u, p, r, i, sendRealname ? 1 : 0, NULL, NULL);
    jstring result = to_java(env, body);
    release_c(env, hidden, h);
    release_c(env, username, u);
    release_c(env, password, p);
    release_c(env, realname, r);
    release_c(env, idcard, i);
    return result;
}

JNIEXPORT jstring JNICALL
Java_io_gen4399_app_Native_classify(JNIEnv *env, jobject thiz, jstring path, jint status, jstring body)
{
    (void)thiz;
    const char *p = to_c(env, path);
    const char *b = to_c(env, body);
    char kind[32], message[512];
    g4399_classify(p, (int)status, b, kind, sizeof(kind), message, sizeof(message));
    release_c(env, path, p);
    release_c(env, body, b);
    char combined[600];
    snprintf(combined, sizeof(combined), "%s\t%s", kind, message);
    return (*env)->NewStringUTF(env, combined);
}

JNIEXPORT jstring JNICALL
Java_io_gen4399_app_Native_recognizeUnified(JNIEnv *env, jobject thiz, jintArray pixels,
                                            jint width, jint height)
{
    (void)thiz;
    if (pixels == NULL) return NULL;
    jsize length = (*env)->GetArrayLength(env, pixels);
    if (length < width * height || width != 60 || height != 30) return NULL;

    jint *raw = (*env)->GetIntArrayElements(env, pixels, NULL);
    if (raw == NULL) return NULL;
    char out[8] = {0};
    int ok = g4399_recognize_unified((const uint32_t *)raw, (int)width, (int)height, out);
    (*env)->ReleaseIntArrayElements(env, pixels, raw, JNI_ABORT);
    if (!ok) return NULL;
    return (*env)->NewStringUTF(env, out);
}

JNIEXPORT jstring JNICALL
Java_io_gen4399_app_Native_recognizeWeb(JNIEnv *env, jobject thiz, jintArray pixels,
                                        jint width, jint height)
{
    (void)thiz;
    if (pixels == NULL) return NULL;
    jsize length = (*env)->GetArrayLength(env, pixels);
    if (length < width * height || width != 150 || height != 45) return NULL;

    jint *raw = (*env)->GetIntArrayElements(env, pixels, NULL);
    if (raw == NULL) return NULL;
    char out[8] = {0};
    int ok = g4399_recognize_web((const uint32_t *)raw, (int)width, (int)height, out);
    (*env)->ReleaseIntArrayElements(env, pixels, raw, JNI_ABORT);
    if (!ok) return NULL;
    return (*env)->NewStringUTF(env, out);
}

JNIEXPORT jstring JNICALL
Java_io_gen4399_app_Native_randomUserAgent(JNIEnv *env, jobject thiz)
{
    (void)thiz;
    char buffer[256] = {0};
    g4399_random_user_agent(buffer, sizeof(buffer));
    return (*env)->NewStringUTF(env, buffer);
}
