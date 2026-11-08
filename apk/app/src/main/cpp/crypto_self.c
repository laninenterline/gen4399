/* 自带实现的 MD5 / AES-256-CBC / DES-EDE3-ECB / Base64 编码。
 *
 * 为什么要有这份：Android 版 libgen4399.so 不能依赖 OpenSSL
 * （NDK 里没有预编译的 libcrypto），所以用 -DGEN4399_SELF_CRYPTO 切到本文件。
 * 只实现「加密」方向，够构造 4399 表单字段用。
 */
#include "gen4399.h"

#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

/* ============================ MD5 ============================ */

typedef struct {
    uint32_t state[4];
    uint64_t bits;
    unsigned char buffer[64];
} md5_ctx;

static const uint32_t MD5_K[64] = {
    0xd76aa478, 0xe8c7b756, 0x242070db, 0xc1bdceee, 0xf57c0faf, 0x4787c62a,
    0xa8304613, 0xfd469501, 0x698098d8, 0x8b44f7af, 0xffff5bb1, 0x895cd7be,
    0x6b901122, 0xfd987193, 0xa679438e, 0x49b40821, 0xf61e2562, 0xc040b340,
    0x265e5a51, 0xe9b6c7aa, 0xd62f105d, 0x02441453, 0xd8a1e681, 0xe7d3fbc8,
    0x21e1cde6, 0xc33707d6, 0xf4d50d87, 0x455a14ed, 0xa9e3e905, 0xfcefa3f8,
    0x676f02d9, 0x8d2a4c8a, 0xfffa3942, 0x8771f681, 0x6d9d6122, 0xfde5380c,
    0xa4beea44, 0x4bdecfa9, 0xf6bb4b60, 0xbebfbc70, 0x289b7ec6, 0xeaa127fa,
    0xd4ef3085, 0x04881d05, 0xd9d4d039, 0xe6db99e5, 0x1fa27cf8, 0xc4ac5665,
    0xf4292244, 0x432aff97, 0xab9423a7, 0xfc93a039, 0x655b59c3, 0x8f0ccc92,
    0xffeff47d, 0x85845dd1, 0x6fa87e4f, 0xfe2ce6e0, 0xa3014314, 0x4e0811a1,
    0xf7537e82, 0xbd3af235, 0x2ad7d2bb, 0xeb86d391,
};
static const int MD5_S[64] = {
    7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22,
    5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20,
    4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23,
    6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21,
};

static uint32_t rotl32(uint32_t x, int c) { return (x << c) | (x >> (32 - c)); }

static void md5_transform(uint32_t state[4], const unsigned char block[64])
{
    uint32_t m[16];
    for (int i = 0; i < 16; i++) {
        m[i] = (uint32_t)block[i * 4] | ((uint32_t)block[i * 4 + 1] << 8) |
               ((uint32_t)block[i * 4 + 2] << 16) | ((uint32_t)block[i * 4 + 3] << 24);
    }
    uint32_t a = state[0], b = state[1], c = state[2], d = state[3];
    for (int i = 0; i < 64; i++) {
        uint32_t f;
        int g;
        if (i < 16) { f = (b & c) | (~b & d); g = i; }
        else if (i < 32) { f = (d & b) | (~d & c); g = (5 * i + 1) % 16; }
        else if (i < 48) { f = b ^ c ^ d; g = (3 * i + 5) % 16; }
        else { f = c ^ (b | ~d); g = (7 * i) % 16; }
        uint32_t tmp = d;
        d = c;
        c = b;
        b = b + rotl32(a + f + MD5_K[i] + m[g], MD5_S[i]);
        a = tmp;
    }
    state[0] += a; state[1] += b; state[2] += c; state[3] += d;
}

static void md5_init(md5_ctx *ctx)
{
    ctx->state[0] = 0x67452301;
    ctx->state[1] = 0xefcdab89;
    ctx->state[2] = 0x98badcfe;
    ctx->state[3] = 0x10325476;
    ctx->bits = 0;
}

static void md5_update(md5_ctx *ctx, const unsigned char *data, size_t len)
{
    size_t index = (size_t)((ctx->bits >> 3) & 0x3F);
    ctx->bits += (uint64_t)len << 3;
    size_t part = 64 - index;
    size_t i = 0;
    if (len >= part) {
        memcpy(ctx->buffer + index, data, part);
        md5_transform(ctx->state, ctx->buffer);
        for (i = part; i + 63 < len; i += 64) md5_transform(ctx->state, data + i);
        index = 0;
    }
    memcpy(ctx->buffer + index, data + i, len - i);
}

static void md5_final(md5_ctx *ctx, unsigned char out[16])
{
    static const unsigned char padding[64] = {0x80};
    unsigned char length[8];
    uint64_t bits = ctx->bits;
    for (int i = 0; i < 8; i++) length[i] = (unsigned char)((bits >> (8 * i)) & 0xFF);
    size_t index = (size_t)((ctx->bits >> 3) & 0x3F);
    size_t pad = (index < 56) ? (56 - index) : (120 - index);
    md5_update(ctx, padding, pad);
    md5_update(ctx, length, 8);
    for (int i = 0; i < 4; i++) {
        out[i * 4] = (unsigned char)(ctx->state[i] & 0xFF);
        out[i * 4 + 1] = (unsigned char)((ctx->state[i] >> 8) & 0xFF);
        out[i * 4 + 2] = (unsigned char)((ctx->state[i] >> 16) & 0xFF);
        out[i * 4 + 3] = (unsigned char)((ctx->state[i] >> 24) & 0xFF);
    }
}

/* ============================ AES-256 ============================ */

static const unsigned char SBOX[256] = {
    0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
    0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
    0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
    0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
    0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
    0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
    0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
    0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
    0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
    0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
    0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
    0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
    0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
    0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
    0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
    0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16,
};
static const unsigned char RCON[11] = {0x00,0x01,0x02,0x04,0x08,0x10,0x20,0x40,0x80,0x1b,0x36};

static void aes256_expand(const unsigned char key[32], unsigned char roundKey[240])
{
    memcpy(roundKey, key, 32);
    int bytes = 32;
    int rcon = 1;
    unsigned char temp[4];
    while (bytes < 240) {
        memcpy(temp, roundKey + bytes - 4, 4);
        if (bytes % 32 == 0) {
            unsigned char first = temp[0];
            temp[0] = SBOX[temp[1]] ^ RCON[rcon++];
            temp[1] = SBOX[temp[2]];
            temp[2] = SBOX[temp[3]];
            temp[3] = SBOX[first];
        } else if (bytes % 32 == 16) {
            for (int i = 0; i < 4; i++) temp[i] = SBOX[temp[i]];
        }
        for (int i = 0; i < 4; i++) {
            roundKey[bytes] = roundKey[bytes - 32] ^ temp[i];
            bytes++;
        }
    }
}

static void add_round_key(unsigned char *state, const unsigned char *roundKey)
{
    for (int i = 0; i < 16; i++) state[i] ^= roundKey[i];
}

static void sub_bytes(unsigned char *state)
{
    for (int i = 0; i < 16; i++) state[i] = SBOX[state[i]];
}

static void shift_rows(unsigned char *s)
{
    unsigned char t;
    t = s[1]; s[1] = s[5]; s[5] = s[9]; s[9] = s[13]; s[13] = t;
    t = s[2]; s[2] = s[10]; s[10] = t;
    t = s[6]; s[6] = s[14]; s[14] = t;
    t = s[15]; s[15] = s[11]; s[11] = s[7]; s[7] = s[3]; s[3] = t;
}

static unsigned char xtime(unsigned char x) { return (unsigned char)((x << 1) ^ ((x >> 7) * 0x1b)); }

static void mix_columns(unsigned char *s)
{
    for (int i = 0; i < 4; i++) {
        unsigned char *col = s + i * 4;
        unsigned char a0 = col[0], a1 = col[1], a2 = col[2], a3 = col[3];
        unsigned char t = a0 ^ a1 ^ a2 ^ a3;
        unsigned char u = a0;
        col[0] ^= t ^ xtime(a0 ^ a1);
        col[1] ^= t ^ xtime(a1 ^ a2);
        col[2] ^= t ^ xtime(a2 ^ a3);
        col[3] ^= t ^ xtime(a3 ^ u);
    }
}

static void aes256_encrypt_block(const unsigned char roundKey[240], const unsigned char in[16], unsigned char out[16])
{
    unsigned char state[16];
    memcpy(state, in, 16);
    add_round_key(state, roundKey);
    for (int round = 1; round < 14; round++) {
        sub_bytes(state);
        shift_rows(state);
        mix_columns(state);
        add_round_key(state, roundKey + round * 16);
    }
    sub_bytes(state);
    shift_rows(state);
    add_round_key(state, roundKey + 14 * 16);
    memcpy(out, state, 16);
}

/* ============================ DES / 3DES ============================ */

static const int IP[64] = {
    58,50,42,34,26,18,10,2,60,52,44,36,28,20,12,4,62,54,46,38,30,22,14,6,
    64,56,48,40,32,24,16,8,57,49,41,33,25,17,9,1,59,51,43,35,27,19,11,3,
    61,53,45,37,29,21,13,5,63,55,47,39,31,23,15,7,
};
static const int FP[64] = {
    40,8,48,16,56,24,64,32,39,7,47,15,55,23,63,31,38,6,46,14,54,22,62,30,
    37,5,45,13,53,21,61,29,36,4,44,12,52,20,60,28,35,3,43,11,51,19,59,27,
    34,2,42,10,50,18,58,26,33,1,41,9,49,17,57,25,
};
static const int E[48] = {
    32,1,2,3,4,5,4,5,6,7,8,9,8,9,10,11,12,13,12,13,14,15,16,17,
    16,17,18,19,20,21,20,21,22,23,24,25,24,25,26,27,28,29,28,29,30,31,32,1,
};
static const int P[32] = {
    16,7,20,21,29,12,28,17,1,15,23,26,5,18,31,10,2,8,24,14,32,27,3,9,19,13,30,6,22,11,4,25,
};
static const int PC1[56] = {
    57,49,41,33,25,17,9,1,58,50,42,34,26,18,10,2,59,51,43,35,27,19,11,3,
    60,52,44,36,63,55,47,39,31,23,15,7,62,54,46,38,30,22,14,6,61,53,45,37,
    29,21,13,5,28,20,12,4,
};
static const int PC2[48] = {
    14,17,11,24,1,5,3,28,15,6,21,10,23,19,12,4,26,8,16,7,27,20,13,2,
    41,52,31,37,47,55,30,40,51,45,33,48,44,49,39,56,34,53,46,42,50,36,29,32,
};
static const int SHIFTS[16] = {1,1,2,2,2,2,2,2,1,2,2,2,2,2,2,1};
static const unsigned char SBOX_DES[8][64] = {
    {14,4,13,1,2,15,11,8,3,10,6,12,5,9,0,7,0,15,7,4,14,2,13,1,10,6,12,11,9,5,3,8,
     4,1,14,8,13,6,2,11,15,12,9,7,3,10,5,0,15,12,8,2,4,9,1,7,5,11,3,14,10,0,6,13},
    {15,1,8,14,6,11,3,4,9,7,2,13,12,0,5,10,3,13,4,7,15,2,8,14,12,0,1,10,6,9,11,5,
     0,14,7,11,10,4,13,1,5,8,12,6,9,3,2,15,13,8,10,1,3,15,4,2,11,6,7,12,0,5,14,9},
    {10,0,9,14,6,3,15,5,1,13,12,7,11,4,2,8,13,7,0,9,3,4,6,10,2,8,5,14,12,11,15,1,
     13,6,4,9,8,15,3,0,11,1,2,12,5,10,14,7,1,10,13,0,6,9,8,7,4,15,14,3,11,5,2,12},
    {7,13,14,3,0,6,9,10,1,2,8,5,11,12,4,15,13,8,11,5,6,15,0,3,4,7,2,12,1,10,14,9,
     10,6,9,0,12,11,7,13,15,1,3,14,5,2,8,4,3,15,0,6,10,1,13,8,9,4,5,11,12,7,2,14},
    {2,12,4,1,7,10,11,6,8,5,3,15,13,0,14,9,14,11,2,12,4,7,13,1,5,0,15,10,3,9,8,6,
     4,2,1,11,10,13,7,8,15,9,12,5,6,3,0,14,11,8,12,7,1,14,2,13,6,15,0,9,10,4,5,3},
    {12,1,10,15,9,2,6,8,0,13,3,4,14,7,5,11,10,15,4,2,7,12,9,5,6,1,13,14,0,11,3,8,
     9,14,15,5,2,8,12,3,7,0,4,10,1,13,11,6,4,3,2,12,9,5,15,10,11,14,1,7,6,0,8,13},
    {4,11,2,14,15,0,8,13,3,12,9,7,5,10,6,1,13,0,11,7,4,9,1,10,14,3,5,12,2,15,8,6,
     1,4,11,13,12,3,7,14,10,15,6,8,0,5,9,2,6,11,13,8,1,4,10,7,9,5,0,15,14,2,3,12},
    {13,2,8,4,6,15,11,1,10,9,3,14,5,0,12,7,1,15,13,8,10,3,7,4,12,5,6,11,0,14,9,2,
     7,11,4,1,9,12,14,2,0,6,10,13,15,3,5,8,2,1,14,7,4,10,8,13,15,12,9,0,3,5,6,11},
};

typedef struct { uint32_t k[32][2]; } des_key;

static uint64_t permute(uint64_t value, const int *table, int out_bits)
{
    uint64_t out = 0;
    for (int i = 0; i < out_bits; i++) {
        out = (out << 1) | ((value >> (64 - table[i])) & 1ULL);
    }
    return out;
}

static uint32_t rot28(uint32_t v, int n) { return ((v << n) | (v >> (28 - n))) & 0x0FFFFFFF; }

static void des_init(const unsigned char key[8], des_key *ks)
{
    uint64_t k = 0;
    for (int i = 0; i < 8; i++) k = (k << 8) | key[i];
    uint64_t pc1 = permute(k, PC1, 56);
    uint32_t c = (uint32_t)((pc1 >> 28) & 0x0FFFFFFF);
    uint32_t d = (uint32_t)(pc1 & 0x0FFFFFFF);
    for (int round = 0; round < 16; round++) {
        c = rot28(c, SHIFTS[round]);
        d = rot28(d, SHIFTS[round]);
        uint64_t cd = ((uint64_t)c << 28) | d;
        uint64_t sub = permute(cd << 8, PC2, 48);
        ks->k[round][0] = (uint32_t)(sub >> 24);
        ks->k[round][1] = (uint32_t)(sub & 0xFFFFFF);
    }
}

static uint32_t f_func(uint32_t r, uint32_t k0, uint32_t k1)
{
    uint64_t block = ((uint64_t)r) << 32;
    uint64_t expanded = permute(block, E, 48);
    uint64_t key = ((uint64_t)k0 << 24) | k1;
    uint64_t x = expanded ^ key;
    uint32_t out = 0;
    for (int i = 0; i < 8; i++) {
        int shift = 42 - i * 6;
        int six = (int)((x >> shift) & 0x3F);
        int row = ((six >> 4) & 0x2) | (six & 0x1);
        int col = (six >> 1) & 0xF;
        out = (out << 4) | SBOX_DES[i][row * 16 + col];
    }
    return (uint32_t)permute((uint64_t)out << 32, P, 32);
}

static void des_encrypt_block(const des_key *ks, const unsigned char in[8], unsigned char out[8])
{
    uint64_t block = 0;
    for (int i = 0; i < 8; i++) block = (block << 8) | in[i];
    block = permute(block, IP, 64);
    uint32_t l = (uint32_t)(block >> 32), r = (uint32_t)(block & 0xFFFFFFFF);
    for (int round = 0; round < 16; round++) {
        uint32_t next = l ^ f_func(r, ks->k[round][0], ks->k[round][1]);
        l = r;
        r = next;
    }
    block = permute((((uint64_t)r) << 32) | l, FP, 64);
    for (int i = 0; i < 8; i++) out[i] = (unsigned char)((block >> (56 - i * 8)) & 0xFF);
}

/** DES 解密：与加密同样的结构，子密钥逆序 */
static void des_decrypt_block(const des_key *ks, const unsigned char in[8], unsigned char out[8])
{
    uint64_t block = 0;
    for (int i = 0; i < 8; i++) block = (block << 8) | in[i];
    block = permute(block, IP, 64);
    uint32_t l = (uint32_t)(block >> 32), r = (uint32_t)(block & 0xFFFFFFFF);
    for (int round = 15; round >= 0; round--) {
        uint32_t next = l ^ f_func(r, ks->k[round][0], ks->k[round][1]);
        l = r;
        r = next;
    }
    block = permute((((uint64_t)r) << 32) | l, FP, 64);
    for (int i = 0; i < 8; i++) out[i] = (unsigned char)((block >> (56 - i * 8)) & 0xFF);
}

/** 3DES-EDE：E(k1) → D(k2) → E(k3) */
static void desede_encrypt_block(const des_key *k1, const des_key *k2, const des_key *k3,
                                 const unsigned char in[8], unsigned char out[8])
{
    unsigned char tmp[8];
    des_encrypt_block(k1, in, tmp);
    des_decrypt_block(k2, tmp, tmp);
    des_encrypt_block(k3, tmp, out);
}

/* ============================ 工具 ============================ */

static void evp_bytes_to_key(const unsigned char *password, size_t password_len,
                             const unsigned char *salt, size_t salt_len,
                             unsigned char *key, int key_len, unsigned char *iv, int iv_len)
{
    unsigned char material[64];
    size_t material_len = 0;
    unsigned char prev[16];
    size_t prev_len = 0;
    int have = 0;
    while ((int)material_len < key_len + iv_len) {
        md5_ctx ctx;
        md5_init(&ctx);
        if (have) md5_update(&ctx, prev, prev_len);
        md5_update(&ctx, password, password_len);
        md5_update(&ctx, salt, salt_len);
        md5_final(&ctx, prev);
        prev_len = 16;
        have = 1;
        memcpy(material + material_len, prev, 16);
        material_len += 16;
    }
    memcpy(key, material, (size_t)key_len);
    memcpy(iv, material + key_len, (size_t)iv_len);
}

static const char B64[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

static char *base64_encode(const unsigned char *data, size_t len)
{
    size_t out_len = 4 * ((len + 2) / 3);
    char *out = malloc(out_len + 1);
    if (!out) return NULL;
    size_t i = 0, j = 0;
    while (i + 2 < len) {
        uint32_t triple = (data[i] << 16) | (data[i + 1] << 8) | data[i + 2];
        out[j++] = B64[(triple >> 18) & 0x3F];
        out[j++] = B64[(triple >> 12) & 0x3F];
        out[j++] = B64[(triple >> 6) & 0x3F];
        out[j++] = B64[triple & 0x3F];
        i += 3;
    }
    if (i < len) {
        uint32_t triple = data[i] << 16;
        int rem = (int)(len - i);
        if (rem == 2) triple |= data[i + 1] << 8;
        out[j++] = B64[(triple >> 18) & 0x3F];
        out[j++] = B64[(triple >> 12) & 0x3F];
        out[j++] = (rem == 2) ? B64[(triple >> 6) & 0x3F] : '=';
        out[j++] = '=';
    }
    out[j] = '\0';
    return out;
}

/* ============================ 对外接口 ============================ */

char *g4399_aes_encrypt(const char *plaintext, const char *passphrase)
{
    if (!plaintext) return NULL;
    if (!passphrase) passphrase = "lzYW5qaXVqa";

    unsigned char salt[8];
    FILE *urandom = fopen("/dev/urandom", "rb");
    if (!urandom || fread(salt, 1, 8, urandom) != 8) {
        if (urandom) fclose(urandom);
        return NULL;
    }
    fclose(urandom);

    unsigned char key[32], iv[16];
    evp_bytes_to_key((const unsigned char *)passphrase, strlen(passphrase), salt, 8, key, 32, iv, 16);

    size_t pt_len = strlen(plaintext);
    size_t padded_len = (pt_len / 16 + 1) * 16;
    unsigned char *padded = calloc(padded_len, 1);
    if (!padded) return NULL;
    memcpy(padded, plaintext, pt_len);
    unsigned char pad = (unsigned char)(padded_len - pt_len);
    memset(padded + pt_len, pad, pad);

    unsigned char roundKey[240];
    aes256_expand(key, roundKey);

    unsigned char *out = malloc(16 + padded_len);
    if (!out) { free(padded); return NULL; }
    memcpy(out, "Salted__", 8);
    memcpy(out + 8, salt, 8);

    unsigned char prev[16];
    memcpy(prev, iv, 16);
    for (size_t off = 0; off < padded_len; off += 16) {
        unsigned char block[16];
        for (int i = 0; i < 16; i++) block[i] = padded[off + i] ^ prev[i];
        aes256_encrypt_block(roundKey, block, out + 16 + off);
        memcpy(prev, out + 16 + off, 16);
    }
    free(padded);

    char *encoded = base64_encode(out, 16 + padded_len);
    free(out);
    return encoded;
}

char *g4399_encode_4399(const char *value, const char *key)
{
    if (!value || !key || !*key) return NULL;

    /* encodeURIComponent 语义 */
    size_t len = strlen(value);
    char *escaped = malloc(len * 3 + 1);
    if (!escaped) return NULL;
    static const char hex[] = "0123456789ABCDEF";
    size_t pos = 0;
    for (size_t i = 0; i < len; i++) {
        unsigned char c = (unsigned char)value[i];
        int safe = (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
                   (c >= '0' && c <= '9') || c == '-' || c == '_' || c == '.' ||
                   c == '!' || c == '~' || c == '*' || c == '\'' || c == '(' || c == ')';
        if (safe) {
            escaped[pos++] = (char)c;
        } else {
            escaped[pos++] = '%';
            escaped[pos++] = hex[(c >> 4) & 0xF];
            escaped[pos++] = hex[c & 0xF];
        }
    }
    escaped[pos] = '\0';
    if (pos == 0) { free(escaped); return strdup("0x"); }

    unsigned char des_key_bytes[24];
    memset(des_key_bytes, 0, sizeof(des_key_bytes));
    size_t key_len = strlen(key);
    if (key_len <= 8) {
        memcpy(des_key_bytes, key, key_len);
        memcpy(des_key_bytes + 8, des_key_bytes, 8);
        memcpy(des_key_bytes + 16, des_key_bytes, 8);
    } else {
        memcpy(des_key_bytes, key, key_len > 24 ? 24 : key_len);
    }

    des_key k1, k2, k3;
    des_init(des_key_bytes, &k1);
    des_init(des_key_bytes + 8, &k2);
    des_init(des_key_bytes + 16, &k3);

    size_t padded_len = (pos + 7) / 8 * 8;
    unsigned char *cipher = calloc(padded_len, 1);
    if (!cipher) { free(escaped); return NULL; }
    for (size_t off = 0; off < padded_len; off += 8) {
        unsigned char block[8] = {0};
        size_t n = (pos - off < 8) ? (pos - off) : 8;
        if (off < pos) memcpy(block, escaped + off, n);
        if (key_len <= 8) {
            des_encrypt_block(&k1, block, cipher + off);          /* 单 DES */
        } else {
            desede_encrypt_block(&k1, &k2, &k3, block, cipher + off);
        }
    }
    free(escaped);

    static const char hex_lower[] = "0123456789abcdef";
    char *hex_out = malloc(padded_len * 2 + 3);
    if (!hex_out) { free(cipher); return NULL; }
    hex_out[0] = '0';
    hex_out[1] = 'x';
    for (size_t i = 0; i < padded_len; i++) {
        hex_out[2 + i * 2] = hex_lower[(cipher[i] >> 4) & 0xF];
        hex_out[3 + i * 2] = hex_lower[cipher[i] & 0xF];
    }
    hex_out[2 + padded_len * 2] = '\0';
    free(cipher);
    return hex_out;
}
