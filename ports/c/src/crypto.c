/* AES-256-CBC（CryptoJS 口令模式）与 encode_4399（DES/3DES-ECB）。 */
#include "gen4399.h"

#include <openssl/evp.h>
#include <openssl/md5.h>
#include <openssl/rand.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>

#define SALT_LEN 8
#define SALTED_PREFIX "Salted__"

/* EVP_BytesToKey（MD5）：CryptoJS/OpenSSL 口令模式的 key/iv 派生 */
static void evp_bytes_to_key(const unsigned char *password, size_t password_len,
                             const unsigned char *salt, size_t salt_len,
                             unsigned char *key, int key_len,
                             unsigned char *iv, int iv_len)
{
    unsigned char prev[MD5_DIGEST_LENGTH];
    size_t prev_len = 0;
    int have = 0;
    size_t offset = 0;
    int total = key_len + iv_len;
    unsigned char material[64];
    size_t material_len = 0;

    while ((int)material_len < total) {
        unsigned char digest[MD5_DIGEST_LENGTH];
        EVP_MD_CTX *ctx = EVP_MD_CTX_new();
        EVP_DigestInit_ex(ctx, EVP_md5(), NULL);
        if (have) EVP_DigestUpdate(ctx, prev, prev_len);
        EVP_DigestUpdate(ctx, password, password_len);
        EVP_DigestUpdate(ctx, salt, salt_len);
        EVP_DigestFinal_ex(ctx, digest, NULL);
        EVP_MD_CTX_free(ctx);
        memcpy(prev, digest, MD5_DIGEST_LENGTH);
        prev_len = MD5_DIGEST_LENGTH;
        have = 1;
        memcpy(material + material_len, digest, MD5_DIGEST_LENGTH);
        material_len += MD5_DIGEST_LENGTH;
    }
    memcpy(key, material + offset, (size_t)key_len);
    offset += (size_t)key_len;
    memcpy(iv, material + offset, (size_t)iv_len);
}

char *g4399_aes_encrypt(const char *plaintext, const char *passphrase)
{
    if (!plaintext) return NULL;
    if (!passphrase) passphrase = "lzYW5qaXVqa";

    unsigned char salt[SALT_LEN];
    if (RAND_bytes(salt, SALT_LEN) != 1) return NULL;

    unsigned char key[32], iv[16];
    evp_bytes_to_key((const unsigned char *)passphrase, strlen(passphrase),
                     salt, SALT_LEN, key, sizeof(key), iv, sizeof(iv));

    EVP_CIPHER_CTX *ctx = EVP_CIPHER_CTX_new();
    if (!ctx) return NULL;
    size_t pt_len = strlen(plaintext);
    unsigned char *out = malloc(pt_len + 32 + SALT_LEN + 8);
    if (!out) { EVP_CIPHER_CTX_free(ctx); return NULL; }

    memcpy(out, SALTED_PREFIX, 8);
    memcpy(out + 8, salt, SALT_LEN);

    int len = 0, total = 0;
    if (EVP_EncryptInit_ex(ctx, EVP_aes_256_cbc(), NULL, key, iv) != 1 ||
        EVP_EncryptUpdate(ctx, out + 8 + SALT_LEN, &len,
                          (const unsigned char *)plaintext, (int)pt_len) != 1) {
        free(out); EVP_CIPHER_CTX_free(ctx); return NULL;
    }
    total = len;
    if (EVP_EncryptFinal_ex(ctx, out + 8 + SALT_LEN + total, &len) != 1) {
        free(out); EVP_CIPHER_CTX_free(ctx); return NULL;
    }
    total += len;
    EVP_CIPHER_CTX_free(ctx);

    size_t raw_len = 8 + SALT_LEN + (size_t)total;
    char *b64 = malloc(4 * ((raw_len + 2) / 3) + 4);
    if (!b64) { free(out); return NULL; }
    EVP_EncodeBlock((unsigned char *)b64, out, (int)raw_len);
    free(out);
    return b64;
}

/* encodeURIComponent：字母数字 + - _ . ! ~ * ' ( ) 不转义，其余 %XX（UTF-8 字节） */
static char *uri_component(const char *value)
{
    size_t len = strlen(value);
    char *out = malloc(len * 9 + 1);
    if (!out) return NULL;
    size_t pos = 0;
    for (size_t i = 0; i < len; i++) {
        unsigned char c = (unsigned char)value[i];
        int safe = (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
                   (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.' ||
                   c == '!' || c == '~' || c == '*' || c == '\'' || c == '(' || c == ')';
        if (safe) {
            out[pos++] = (char)c;
        } else {
            static const char hex[] = "0123456789ABCDEF";
            out[pos++] = '%';
            out[pos++] = hex[(c >> 4) & 0xF];
            out[pos++] = hex[c & 0xF];
        }
    }
    out[pos] = '\0';
    return out;
}

char *g4399_encode_4399(const char *value, const char *key)
{
    if (!value || !key || !*key) return NULL;
    char *encoded = uri_component(value);
    if (!encoded) return NULL;
    size_t enc_len = strlen(encoded);
    if (enc_len == 0) { free(encoded); return strdup("0x"); }

    size_t key_len = strlen(key);
    unsigned char des_key[24];
    memset(des_key, 0, sizeof(des_key));
    if (key_len <= 8) {
        memcpy(des_key, key, key_len);
        memcpy(des_key + 8, des_key, 8);    /* K1=K2=K3，退化回单 DES */
        memcpy(des_key + 16, des_key, 8);
    } else {
        memcpy(des_key, key, key_len > 24 ? 24 : key_len);
    }

    size_t padded_len = (enc_len + 7) / 8 * 8;
    unsigned char *padded = calloc(padded_len, 1);
    if (!padded) { free(encoded); return NULL; }
    memcpy(padded, encoded, enc_len);
    free(encoded);

    unsigned char *cipher = malloc(padded_len + 16);
    if (!cipher) { free(padded); return NULL; }
    EVP_CIPHER_CTX *ctx = EVP_CIPHER_CTX_new();
    if (!ctx) { free(padded); free(cipher); return NULL; }
    int len = 0, total = 0;
    if (EVP_EncryptInit_ex(ctx, EVP_des_ede3_ecb(), NULL, des_key, NULL) != 1 ||
        EVP_CIPHER_CTX_set_padding(ctx, 0) != 1 ||
        EVP_EncryptUpdate(ctx, cipher, &len, padded, (int)padded_len) != 1) {
        EVP_CIPHER_CTX_free(ctx); free(padded); free(cipher); return NULL;
    }
    total = len;
    EVP_EncryptFinal_ex(ctx, cipher + total, &len);
    total += len;
    EVP_CIPHER_CTX_free(ctx);
    free(padded);

    char *hex = malloc((size_t)total * 2 + 3);
    if (!hex) { free(cipher); return NULL; }
    hex[0] = '0';
    hex[1] = 'x';
    static const char digits[] = "0123456789abcdef";
    for (int i = 0; i < total; i++) {
        hex[2 + i * 2] = digits[(cipher[i] >> 4) & 0xF];
        hex[3 + i * 2] = digits[cipher[i] & 0xF];
    }
    hex[2 + total * 2] = '\0';
    free(cipher);
    return hex;
}
