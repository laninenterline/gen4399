/* 密码/用户名生成与校验、身份信息校验。 */
#include "gen4399.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static int is_alnum(int c) { return isalnum((unsigned char)c) != 0; }
static int is_digit(int c) { return c >= '0' && c <= '9'; }
static int is_lower(int c) { return c >= 'a' && c <= 'z'; }
static int is_upper(int c) { return c >= 'A' && c <= 'Z'; }

static void seed_rng(void)
{
    static int seeded = 0;
    if (!seeded) {
        FILE *urandom = fopen("/dev/urandom", "rb");
        unsigned int value = 0;
        if (urandom) {
            if (fread(&value, sizeof(value), 1, urandom) != 1) value = 0;
            fclose(urandom);
        }
        srand(value ^ (unsigned int)time(NULL));
        seeded = 1;
    }
}

/* 拒绝采样：避免 rand()%n 的取模偏置 */
static char pick_char(const char *charset, size_t size)
{
    int limit = 256 - (256 % (int)size);
    for (;;) {
        int value = rand() & 0xFF;
        if (value < limit) return charset[value % (int)size];
    }
}

static char *generate(const char *charset, int length)
{
    seed_rng();
    char *out = malloc((size_t)length + 1);
    if (!out) return NULL;
    size_t size = strlen(charset);
    for (int i = 0; i < length; i++) out[i] = pick_char(charset, size);
    out[length] = '\0';
    return out;
}

char *g4399_generate_password(int length)
{
    if (length < G4399_PWD_MIN || length > G4399_PWD_MAX) return NULL;
    for (int attempt = 0; attempt < 1000; attempt++) {
        char *candidate = generate(G4399_PWD_CHARSET, length);
        if (!candidate) return NULL;
        if (!g4399_check_password(candidate)) return candidate;
        free(candidate);
    }
    return NULL;
}

char *g4399_generate_username(int length)
{
    if (length < G4399_NAME_MIN || length > G4399_NAME_MAX) return NULL;
    return generate(G4399_NAME_CHARSET, length);
}

const char *g4399_check_password(const char *password)
{
    if (!password) return "密码不能为空";
    size_t n = strlen(password);
    if (n < G4399_PWD_MIN || n > G4399_PWD_MAX) return "长度必须为 6~20 个字符";
    int has_digit = 0, has_lower = 0, has_upper = 0, other = 0;
    for (size_t i = 0; i < n; i++) {
        int c = (unsigned char)password[i];
        if (!is_alnum(c)) { other = 1; break; }
        if (is_digit(c)) has_digit = 1;
        else if (is_lower(c)) has_lower = 1;
        else if (is_upper(c)) has_upper = 1;
    }
    if (other) return "只允许使用字母和数字";
    if (has_digit && !has_lower && !has_upper) return "不能使用纯数字";
    if (has_lower && !has_digit && !has_upper) return "不能使用纯小写字母";
    if (has_upper && !has_digit && !has_lower) return "不能使用纯大写字母";
    return NULL;
}

const char *g4399_check_username(const char *username)
{
    if (!username) return "用户名不能为空";
    size_t n = strlen(username);
    if (n < G4399_NAME_MIN || n > G4399_NAME_MAX) return "用户名长度必须为 6~20 个字符";
    for (size_t i = 0; i < n; i++) {
        if (!is_alnum(username[i])) return "用户名只允许使用字母和数字";
    }
    return NULL;
}

const char *g4399_check_realname(const char *realname)
{
    if (!realname) return "姓名不能为空";
    size_t n = strlen(realname);
    if (n < 3 || n > 90) return "姓名长度不合法（2~30 个字符）";  /* UTF-8 中文 3 字节 */
    for (size_t i = 0; i < n; i++) {
        if (is_digit(realname[i])) return "姓名不能包含数字";
    }
    return NULL;
}

static int valid_birthday(int y, int m, int d)
{
    static const int days[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
    if (y < 1850 || y > 2050 || m < 1 || m > 12 || d < 1) return 0;
    int limit = days[m - 1];
    if (m == 2 && ((y % 4 == 0 && y % 100 != 0) || y % 400 == 0)) limit = 29;
    return d <= limit;
}

const char *g4399_check_idcard(const char *idcard)
{
    if (!idcard) return "身份证号不能为空";
    size_t n = strlen(idcard);
    if (n != 18) return "身份证号格式不正确（应为 18 位数字，末位可为 X）";
    static const int weights[17] = {7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2};
    static const char checks[] = "10X98765432";
    int total = 0;
    for (int i = 0; i < 17; i++) {
        if (!is_digit(idcard[i])) return "身份证号格式不正确（应为 18 位数字，末位可为 X）";
        total += (idcard[i] - '0') * weights[i];
    }
    char last = (char)toupper((unsigned char)idcard[17]);
    if (!is_digit(last) && last != 'X') return "身份证号格式不正确（应为 18 位数字，末位可为 X）";

    char year[5] = {idcard[6], idcard[7], idcard[8], idcard[9], '\0'};
    char month[3] = {idcard[10], idcard[11], '\0'};
    char day[3] = {idcard[12], idcard[13], '\0'};
    if (!valid_birthday(atoi(year), atoi(month), atoi(day))) return "身份证号中的出生日期不合法";
    if (checks[total % 11] != last) return "身份证号校验码不正确，请核对";
    return NULL;
}

const char *g4399_check_qq(const char *qq)
{
    if (!qq || !*qq) return NULL;   /* 选填 */
    size_t n = strlen(qq);
    if (n < 4 || n > 11) return "QQ 号无效（应为 4~11 位数字）";
    for (size_t i = 0; i < n; i++) {
        if (!is_digit(qq[i])) return "QQ 号无效（应为 4~11 位数字）";
    }
    return NULL;
}

void g4399_mask_idcard(const char *idcard, char *buf, size_t buflen)
{
    if (!idcard || buflen < 19) { if (buf && buflen) buf[0] = '\0'; return; }
    size_t n = strlen(idcard);
    if (n != 18) {
        size_t i = 0;
        for (; i < n && i + 1 < buflen; i++) buf[i] = '*';
        buf[i] = '\0';
        return;
    }
    memcpy(buf, idcard, 6);
    for (int i = 0; i < 8; i++) buf[6 + i] = '*';
    memcpy(buf + 14, idcard + 14, 4);
    buf[18] = '\0';
}

/* ---------------- 随机 User-Agent ---------------- */

static const char *UA_TEMPLATES[] = {
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/%d.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/%d.0.0.0 Safari/537.36 Edg/%d.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/%d.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/%d.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:%d.0) Gecko/20100101 Firefox/%d.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/%d.0 Safari/605.1.15",
};

void g4399_random_user_agent(char *out, size_t out_len)
{
    if (!out || out_len == 0) return;
    seed_rng();
    int index = rand() % (int)(sizeof(UA_TEMPLATES) / sizeof(UA_TEMPLATES[0]));
    int major = 120 + rand() % 14;          /* 120~133 */
    int safari = 16 + rand() % 3;           /* 16~18 */
    if (index == 4) {
        snprintf(out, out_len, UA_TEMPLATES[index], major, major);
    } else if (index == 5) {
        snprintf(out, out_len, UA_TEMPLATES[index], safari);
    } else if (index == 1) {
        snprintf(out, out_len, UA_TEMPLATES[index], major, major);
    } else {
        snprintf(out, out_len, UA_TEMPLATES[index], major);
    }
}
