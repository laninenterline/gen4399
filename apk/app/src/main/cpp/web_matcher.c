/* web（150×45）验证码自动识别：移植自 gen4399/captcha_web.py 的骨架 + chamfer 方案。
 *
 * 流程：二值化（RGB 均值 < 190）→ 列投影切 4 段（多则合并、少则按墨量最少处切）
 *      → Zhang-Suen 细化 → 归一化 24×32 → 与字库做 chamfer 最近邻（含 ±1 平移变体）。
 * 字库来自 102 个标注样本（web_captcha_bank.h），留一法字符准确率约 92.9%。
 */
#include "gen4399.h"
#include "web_captcha_bank.h"

#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define W_THR 190
#define GW 24
#define GH 32
#define MAX_PTS 512
#define MAX_SPANS 64

/* 打包字母表：与 Python 的 _PACK 一致 */
static const char PACK[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
static int8_t g_pack_index[128];
static int g_pack_ready = 0;

typedef struct { uint8_t x, y; } point;

static void ensure_pack(void)
{
    if (g_pack_ready) return;
    memset(g_pack_index, -1, sizeof(g_pack_index));
    for (int i = 0; i < 64; i++) g_pack_index[(unsigned char)PACK[i]] = (int8_t)i;
    g_pack_ready = 1;
}

static int unpack(const char *text, point *out, int max)
{
    int count = 0;
    for (const char *p = text; p[0] && p[1] && count < max; p += 2) {
        int x = g_pack_index[(unsigned char)p[0]];
        int y = g_pack_index[(unsigned char)p[1]];
        if (x < 0 || y < 0) continue;
        out[count].x = (uint8_t)x;
        out[count].y = (uint8_t)y;
        count++;
    }
    return count;
}

/* ---------------- 二值化 ---------------- */

typedef struct {
    int width, height;
    uint8_t *ink;      /* width*height，1 = 墨 */
} bitmap;

static void bitmap_free(bitmap *b) { free(b->ink); b->ink = NULL; }

static int bitmap_from_argb(const uint32_t *argb, int width, int height, bitmap *out)
{
    if (!argb || width <= 0 || height <= 0) return 0;
    uint8_t *ink = calloc((size_t)width * (size_t)height, 1);
    if (!ink) return 0;
    for (int y = 0; y < height; y++) {
        for (int x = 0; x < width; x++) {
            uint32_t px = argb[y * width + x];
            int r = (px >> 16) & 0xFF, g = (px >> 8) & 0xFF, b = px & 0xFF;
            if ((r + g + b) / 3 < W_THR) ink[y * width + x] = 1;
        }
    }
    out->width = width;
    out->height = height;
    out->ink = ink;
    return 1;
}

/* ---------------- 切分 ---------------- */

typedef struct { int x0, x1; } span;

static int build_spans(const bitmap *b, span *spans, int max)
{
    int count = 0;
    int start = -1;
    for (int x = 0; x < b->width; x++) {
        int has = 0;
        for (int y = 0; y < b->height; y++) {
            if (b->ink[y * b->width + x]) { has = 1; break; }
        }
        if (has && start < 0) start = x;
        else if (!has && start >= 0) {
            if (count < max) spans[count++] = (span){start, x - 1};
            start = -1;
        }
    }
    if (start >= 0 && count < max) spans[count++] = (span){start, b->width - 1};

    /* 间隙 ≤2 的合并 */
    int merged = 0;
    for (int i = 0; i < count; i++) {
        if (merged && spans[i].x0 - spans[merged - 1].x1 <= 2) {
            spans[merged - 1].x1 = spans[i].x1;
        } else {
            spans[merged++] = spans[i];
        }
    }
    return merged;
}

static int column_ink(const bitmap *b, int x)
{
    int count = 0;
    for (int y = 0; y < b->height; y++) count += b->ink[y * b->width + x] ? 1 : 0;
    return count;
}

/** 强制整理成 4 段：多了合并间隙最小的，少了在墨量最少的列切开 */
static int force_four(const bitmap *b, span *spans, int count)
{
    while (count > 4) {
        int best = 0, best_gap = 1 << 30;
        for (int i = 0; i + 1 < count; i++) {
            int gap = spans[i + 1].x0 - spans[i].x1;
            if (gap < best_gap) { best_gap = gap; best = i; }
        }
        spans[best].x1 = spans[best + 1].x1;
        memmove(&spans[best + 1], &spans[best + 2], sizeof(span) * (size_t)(count - best - 2));
        count--;
    }
    while (count < 4 && count > 0) {
        int widest = 0;
        for (int i = 1; i < count; i++) {
            if (spans[i].x1 - spans[i].x0 > spans[widest].x1 - spans[widest].x0) widest = i;
        }
        int a = spans[widest].x0, bb = spans[widest].x1;
        if (bb - a < 4) break;
        int lo = a + 2, hi = bb - 2;
        int cut = (lo + hi) / 2;
        if (hi >= lo) {
            int best_ink = 1 << 30;
            for (int x = lo; x <= hi; x++) {
                int v = column_ink(b, x);
                if (v < best_ink) { best_ink = v; cut = x; }
            }
        }
        spans[widest] = (span){a, cut};
        memmove(&spans[widest + 2], &spans[widest + 1], sizeof(span) * (size_t)(count - widest - 1));
        spans[widest + 1] = (span){cut + 1, bb};
        count++;
    }
    return count;
}

/* ---------------- 细化（Zhang-Suen） ---------------- */

static int thin(uint8_t *sub, int w, int h, int max_iter)
{
    for (int iter = 0; iter < max_iter; iter++) {
        int changed = 0;
        for (int step = 0; step < 2; step++) {
            int *marks = malloc(sizeof(int) * (size_t)(w * h));
            if (!marks) return changed;
            int mark_count = 0;
            for (int y = 1; y + 1 < h; y++) {
                for (int x = 1; x + 1 < w; x++) {
                    if (!sub[y * w + x]) continue;
                    int p[8] = {
                        sub[(y - 1) * w + x], sub[(y - 1) * w + x + 1],
                        sub[y * w + x + 1], sub[(y + 1) * w + x + 1],
                        sub[(y + 1) * w + x], sub[(y + 1) * w + x - 1],
                        sub[y * w + x - 1], sub[(y - 1) * w + x - 1],
                    };
                    int total = 0;
                    for (int i = 0; i < 8; i++) total += p[i];
                    if (total < 2 || total > 6) continue;
                    int transitions = 0;
                    for (int i = 0; i < 8; i++) {
                        if (p[i] == 0 && p[(i + 1) % 8] == 1) transitions++;
                    }
                    if (transitions != 1) continue;
                    int p2 = p[0], p4 = p[2], p6 = p[4], p8 = p[6];
                    if (step == 0) {
                        if (p2 && p4 && p6) continue;
                        if (p4 && p6 && p8) continue;
                    } else {
                        if (p2 && p4 && p8) continue;
                        if (p2 && p6 && p8) continue;
                    }
                    marks[mark_count++] = y * w + x;
                }
            }
            for (int i = 0; i < mark_count; i++) {
                sub[marks[i]] = 0;
                changed = 1;
            }
            free(marks);
        }
        if (!changed) break;
    }
    return 1;
}

/* ---------------- 归一化 ---------------- */

static int normalize_glyph(const bitmap *b, int x0, int x1, point *out, int max)
{
    int y0 = -1, y1 = -1;
    for (int y = 0; y < b->height; y++) {
        int has = 0;
        for (int x = x0; x <= x1; x++) {
            if (b->ink[y * b->width + x]) { has = 1; break; }
        }
        if (has) { if (y0 < 0) y0 = y; y1 = y; }
    }
    if (y0 < 0) return 0;

    int w = x1 - x0 + 1, h = y1 - y0 + 1;
    uint8_t *sub = calloc((size_t)w * (size_t)h, 1);
    if (!sub) return 0;
    for (int y = 0; y < h; y++) {
        for (int x = 0; x < w; x++) {
            sub[y * w + x] = b->ink[(y0 + y) * b->width + (x0 + x)];
        }
    }
    thin(sub, w, h, 40);

    int xmin = w, xmax = -1, ymin = h, ymax = -1;
    for (int y = 0; y < h; y++) {
        for (int x = 0; x < w; x++) {
            if (!sub[y * w + x]) continue;
            if (x < xmin) xmin = x;
            if (x > xmax) xmax = x;
            if (y < ymin) ymin = y;
            if (y > ymax) ymax = y;
        }
    }
    if (xmax < 0) { free(sub); return 0; }

    int gw = xmax - xmin, gh = ymax - ymin;
    if (gw < 1) gw = 1;
    if (gh < 1) gh = 1;

    uint8_t seen[GH][GW];
    memset(seen, 0, sizeof(seen));
    for (int y = 0; y < h; y++) {
        for (int x = 0; x < w; x++) {
            if (!sub[y * w + x]) continue;
            int nx = (x - xmin) * GW / gw;
            int ny = (y - ymin) * GH / gh;
            if (nx < 0) nx = 0;
            if (nx >= GW) nx = GW - 1;
            if (ny < 0) ny = 0;
            if (ny >= GH) ny = GH - 1;
            seen[ny][nx] = 1;
        }
    }
    free(sub);

    int count = 0;
    for (int y = 0; y < GH && count < max; y++) {
        for (int x = 0; x < GW && count < max; x++) {
            if (seen[y][x]) {
                out[count].x = (uint8_t)x;
                out[count].y = (uint8_t)y;
                count++;
            }
        }
    }
    return count;
}

/* ---------------- chamfer ---------------- */

static void distance_map(const point *pts, int count, int16_t *map)
{
    for (int i = 0; i < GW * GH; i++) map[i] = 30000;
    for (int i = 0; i < count; i++) map[pts[i].y * GW + pts[i].x] = 0;

    for (int y = 0; y < GH; y++) {
        for (int x = 0; x < GW; x++) {
            int idx = y * GW + x;
            int best = map[idx];
            if (x > 0 && map[idx - 1] + 1 < best) best = map[idx - 1] + 1;
            if (y > 0 && map[idx - GW] + 1 < best) best = map[idx - GW] + 1;
            map[idx] = (int16_t)best;
        }
    }
    for (int y = GH - 1; y >= 0; y--) {
        for (int x = GW - 1; x >= 0; x--) {
            int idx = y * GW + x;
            int best = map[idx];
            if (x + 1 < GW && map[idx + 1] + 1 < best) best = map[idx + 1] + 1;
            if (y + 1 < GH && map[idx + GW] + 1 < best) best = map[idx + GW] + 1;
            map[idx] = (int16_t)best;
        }
    }
}

static float chamfer(const point *pts, int count, const int16_t *map)
{
    if (count <= 0) return 99.0f;
    int total = 0;
    for (int i = 0; i < count; i++) total += map[pts[i].y * GW + pts[i].x];
    return (float)total / (float)count;
}

/* ---------------- 自学习字库（用户运行时确认过的样本） ---------------- */

#define DYN_MAX_CHARS 128
#define DYN_MAX_PER_CHAR 64
#define DYN_MAX_PTS 512

typedef struct {
    char ch;
    int count;                              /* 已有样本数 */
    point samples[DYN_MAX_PER_CHAR][DYN_MAX_PTS];
    int lengths[DYN_MAX_PER_CHAR];
} dyn_entry;

static dyn_entry g_dyn[DYN_MAX_CHARS];
static int g_dyn_count = 0;

static dyn_entry *dyn_find(char ch)
{
    for (int i = 0; i < g_dyn_count; i++) {
        if (g_dyn[i].ch == ch) return &g_dyn[i];
    }
    if (g_dyn_count >= DYN_MAX_CHARS) return NULL;
    dyn_entry *entry = &g_dyn[g_dyn_count++];
    memset(entry, 0, sizeof(*entry));
    entry->ch = ch;
    return entry;
}

int g4399_web_bank_count(void)
{
    int total = 0;
    for (int i = 0; i < g_dyn_count; i++) total += g_dyn[i].count;
    return total;
}

int g4399_web_bank_add(char ch, const point *points, int count)
{
    if (!points || count <= 0 || count > DYN_MAX_PTS) return 0;
    dyn_entry *entry = dyn_find(ch);
    if (!entry) return 0;
    if (entry->count >= DYN_MAX_PER_CHAR) return 0;   /* 单字样本上限，避免无限膨胀 */
    memcpy(entry->samples[entry->count], points, sizeof(point) * (size_t)count);
    entry->lengths[entry->count] = count;
    entry->count++;
    return 1;
}

/** 存盘：每行 `字符\t打包点集` */
int g4399_web_bank_save(const char *path)
{
    if (!path) return 0;
    ensure_pack();
    FILE *fp = fopen(path, "w");
    if (!fp) return 0;
    int written = 0;
    for (int i = 0; i < g_dyn_count; i++) {
        for (int j = 0; j < g_dyn[i].count; j++) {
            fprintf(fp, "%c\t", g_dyn[i].ch);
            for (int k = 0; k < g_dyn[i].lengths[j]; k++) {
                fputc(PACK[g_dyn[i].samples[j][k].x & 63], fp);
                fputc(PACK[g_dyn[i].samples[j][k].y & 63], fp);
            }
            fputc('\n', fp);
            written++;
        }
    }
    fclose(fp);
    return written;
}

int g4399_web_bank_load(const char *path)
{
    if (!path) return 0;
    ensure_pack();
    FILE *fp = fopen(path, "r");
    if (!fp) return 0;
    char line[4096];
    int loaded = 0;
    while (fgets(line, sizeof(line), fp)) {
        size_t len = strlen(line);
        while (len && (line[len - 1] == '\n' || line[len - 1] == '\r')) line[--len] = '\0';
        if (len < 3 || line[1] != '\t') continue;
        point pts[DYN_MAX_PTS];
        int count = unpack(line + 2, pts, DYN_MAX_PTS);
        if (count > 0 && g4399_web_bank_add(line[0], pts, count)) loaded++;
    }
    fclose(fp);
    return loaded;
}

static const int SHIFT_X[5] = {0, 1, -1, 0, 0};
static const int SHIFT_Y[5] = {0, 0, 0, 1, -1};

/** 与字库做最近邻；返回最可能的字符，距离写入 *best_distance */
static char match_glyph(const point *query, int query_count, float *best_distance)
{
    ensure_pack();
    int16_t query_map[GW * GH];
    distance_map(query, query_count, query_map);

    char best_ch = '?';
    float best = 99.0f;

    for (int c = 0; c < WEB_BANK_CHARS + g_dyn_count; c++) {
        const char *sample_text = NULL;
        const point *dyn_points = NULL;
        int dyn_count = 0;
        char entry_ch = '?';
        int samples = 0;

        if (c < WEB_BANK_CHARS) {
            entry_ch = web_bank[c].ch;
            samples = web_bank[c].count;
        } else {
            const dyn_entry *d = &g_dyn[c - WEB_BANK_CHARS];
            entry_ch = d->ch;
            samples = d->count;
        }

        for (int s = 0; s < samples; s++) {
            point base[MAX_PTS];
            int base_count = 0;
            if (c < WEB_BANK_CHARS) {
                sample_text = web_bank[c].samples[s];
                base_count = unpack(sample_text, base, MAX_PTS);
            } else {
                const dyn_entry *d = &g_dyn[c - WEB_BANK_CHARS];
                dyn_points = d->samples[s];
                dyn_count = d->lengths[s];
                base_count = dyn_count;
                memcpy(base, dyn_points, sizeof(point) * (size_t)dyn_count);
            }
            if (base_count <= 0) continue;
            for (int v = 0; v < 5; v++) {
                point variant[MAX_PTS];
                int count = 0;
                for (int i = 0; i < base_count; i++) {
                    int x = base[i].x + SHIFT_X[v];
                    int y = base[i].y + SHIFT_Y[v];
                    if (x < 0) x = 0;
                    if (x >= GW) x = GW - 1;
                    if (y < 0) y = 0;
                    if (y >= GH) y = GH - 1;
                    variant[count].x = (uint8_t)x;
                    variant[count].y = (uint8_t)y;
                    count++;
                }
                int16_t variant_map[GW * GH];
                distance_map(variant, count, variant_map);
                /* 与 Python 一致：variant→查询的距离图 + 查询→variant 的距离图 */
                float d = (chamfer(variant, count, query_map) +
                           chamfer(query, query_count, variant_map)) / 2.0f;
                if (d < best) { best = d; best_ch = entry_ch; }
            }
        }
    }
    if (best_distance) *best_distance = best;
    return best_ch;
}

/**
 * 用一张**已被服务端确认正确**的验证码来扩充字库。
 * code 必须是 4 个字符；返回实际加入的字形数（0~4）。
 */
int g4399_learn_web(const uint32_t *argb, int width, int height, const char *code)
{
    if (!argb || !code || strlen(code) != 4) return 0;
    if (width != 150 || height != 45) return 0;

    bitmap bmp;
    if (!bitmap_from_argb(argb, width, height, &bmp)) return 0;

    span spans[MAX_SPANS];
    int count = build_spans(&bmp, spans, MAX_SPANS);
    count = force_four(&bmp, spans, count);
    if (count != 4) { bitmap_free(&bmp); return 0; }

    int added = 0;
    for (int i = 0; i < 4; i++) {
        point glyph[MAX_PTS];
        int glyph_count = normalize_glyph(&bmp, spans[i].x0, spans[i].x1, glyph, MAX_PTS);
        if (glyph_count <= 0) continue;
        if (g4399_web_bank_add(code[i], glyph, glyph_count)) added++;
    }
    bitmap_free(&bmp);
    return added;
}

/**
 * 识别 150×45 的 ARGB 图；成功返回 1 并写 out（4 字符），信心不足返回 0。
 * max_distance / min_margin 与 Python 版一致：4.2 / 0.2
 */
int g4399_recognize_web(const uint32_t *argb, int width, int height, char *out)
{
    if (!argb || !out || width != 150 || height != 45) return 0;

    bitmap bmp;
    if (!bitmap_from_argb(argb, width, height, &bmp)) return 0;

    span spans[MAX_SPANS];
    int count = build_spans(&bmp, spans, MAX_SPANS);
    count = force_four(&bmp, spans, count);
    if (count != 4) { bitmap_free(&bmp); return 0; }

    char result[8] = {0};
    int sure = 1;
    for (int i = 0; i < 4; i++) {
        point glyph[MAX_PTS];
        int glyph_count = normalize_glyph(&bmp, spans[i].x0, spans[i].x1, glyph, MAX_PTS);
        if (glyph_count <= 0) { sure = 0; result[i] = '?'; continue; }
        float distance = 99.0f;
        char ch = match_glyph(glyph, glyph_count, &distance);
        result[i] = ch;
        if (distance > 4.2f) sure = 0;
    }
    bitmap_free(&bmp);

    if (!sure || strchr(result, '?') != NULL) return 0;
    memcpy(out, result, 5);
    return 1;
}
