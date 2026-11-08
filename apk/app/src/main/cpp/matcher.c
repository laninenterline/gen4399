/* unified（60×30）验证码自动识别：移植自 guiwow1337/4399-captcha 的 matcher.c（MIT）。
 *
 * 判据是「包含」而不是相关/IoU：
 *   1. (R+G+B)/3 < 170 记为墨；
 *   2. 25 个手扣字形模板在 4 个槽位窗口内滑动，允许滑出图外；
 *   3. 每槽位取「溢出最少」的模板（溢出相同取墨量少的），界内墨需 ≥ 模板墨量的 60%。
 */
#include "gen4399.h"
#include "captcha_templates.h"

#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define IMAGE_WIDTH 60
#define IMAGE_HEIGHT 30
#define PADY 16
#define PADX 16
#define THRESHOLD 170
#define IMG_MASK ((UINT64_C(1) << IMAGE_WIDTH) - 1)

typedef struct {
    char ch;
    int need;
    int clo[4];
    int chi[4];
    uint64_t rows[IMAGE_HEIGHT];   /* 按 dy 聚合后的行掩码 */
    int row_dy[IMAGE_HEIGHT];
    int row_count;
} built_template;

static built_template g_built[G4399_TEMPLATE_COUNT];
static int g_built_ready = 0;

static void ensure_built(void)
{
    if (g_built_ready) return;
    for (int i = 0; i < G4399_TEMPLATE_COUNT; i++) {
        const g4399_template *t = &g4399_templates[i];
        built_template *b = &g_built[i];
        b->ch = t->ch;
        b->need = t->need;
        memcpy(b->clo, t->clo, sizeof(b->clo));
        memcpy(b->chi, t->chi, sizeof(b->chi));
        memset(b->rows, 0, sizeof(b->rows));
        b->row_count = 0;
        for (int j = 0; j < t->nink; j++) {
            int dy = g4399_ink_off[t->off + 2 * j];
            int dx = g4399_ink_off[t->off + 2 * j + 1];
            if (dy < 0 || dy >= IMAGE_HEIGHT || dx < 0 || dx >= IMAGE_WIDTH) continue;
            b->rows[dy] |= (UINT64_C(1) << dx);
        }
        for (int dy = 0; dy < IMAGE_HEIGHT; dy++) {
            if (b->rows[dy]) {
                b->row_dy[b->row_count] = dy;
                b->rows[b->row_count] = b->rows[dy];   /* 紧凑存储 */
                b->row_count++;
            }
        }
    }
    g_built_ready = 1;
}

static int popcount64(uint64_t v)
{
    int count = 0;
    while (v) { v &= v - 1; count++; }
    return count;
}

/**
 * 识别一张 60×30 的 ARGB 图，结果写入 out（至少 5 字节）。
 * 返回 1 成功，0 表示尺寸不对 / 没识别出 4 个字符。
 */
int g4399_recognize_unified(const uint32_t *argb, int width, int height, char *out)
{
    if (!argb || !out) return 0;
    if (width != IMAGE_WIDTH || height != IMAGE_HEIGHT) return 0;
    ensure_built();

    uint64_t ink[IMAGE_HEIGHT];
    for (int y = 0; y < IMAGE_HEIGHT; y++) {
        uint64_t bits = 0;
        for (int x = 0; x < IMAGE_WIDTH; x++) {
            uint32_t px = argb[y * width + x];
            int r = (px >> 16) & 0xFF;
            int g = (px >> 8) & 0xFF;
            int b = px & 0xFF;
            if ((r + g + b) / 3 < THRESHOLD) bits |= (UINT64_C(1) << x);
        }
        ink[y] = bits;
    }

    int matched = 0;
    for (int slot = 0; slot < 4; slot++) {
        int best_vio = 1 << 30;
        int best_ink = -1;
        char best_ch = '?';
        for (int ti = 0; ti < G4399_TEMPLATE_COUNT; ti++) {
            const built_template *t = &g_built[ti];
            for (int anchor_r = 0; anchor_r < IMAGE_HEIGHT + PADY; anchor_r++) {
                int iy0 = anchor_r - PADY;
                for (int anchor_c = t->clo[slot]; anchor_c <= t->chi[slot]; anchor_c++) {
                    int ix0 = anchor_c - PADX;
                    int vio = 0, ov = 0, too_much = 0;
                    for (int k = 0; k < t->row_count; k++) {
                        int iy = iy0 + t->row_dy[k];
                        if (iy < 0 || iy >= IMAGE_HEIGHT) continue;
                        uint64_t mask = t->rows[k];
                        uint64_t shifted = (ix0 >= 0) ? ((mask << ix0) & IMG_MASK)
                                                      : (mask >> (-ix0));
                        if (!shifted) continue;
                        ov += popcount64(shifted);
                        vio += popcount64(shifted & ~ink[iy] & IMG_MASK);
                        if (vio > best_vio) { too_much = 1; break; }
                    }
                    if (too_much || ov < t->need) continue;
                    if (vio < best_vio || (vio == best_vio && t->row_count < best_ink)) {
                        best_vio = vio;
                        best_ink = t->row_count;
                        best_ch = t->ch;
                    }
                }
            }
        }
        out[slot] = best_ch;
        if (best_ch != '?') matched++;
    }
    out[4] = '\0';
    return matched == 4;
}
