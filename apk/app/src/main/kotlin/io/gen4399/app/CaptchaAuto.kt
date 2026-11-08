package io.gen4399.app

import android.graphics.Bitmap
import android.graphics.BitmapFactory

/**
 * 验证码自动识别：图片解码用平台 API，识别算法在 C（`matcher.c`）。
 *
 * 目前覆盖 unified 的 60×30 验证码（25 个字形模板 + 包含判据，上游报 100%）。
 * web 的 150×45 字形完全不同，仍需人工/字库。
 */
object CaptchaAuto {
    private const val UNIFIED_W = 60
    private const val UNIFIED_H = 30

    fun solveUnified(image: ByteArray): String? {
        return runCatching {
            val options = BitmapFactory.Options().apply {
                inPreferredConfig = Bitmap.Config.ARGB_8888
            }
            val bitmap = BitmapFactory.decodeByteArray(image, 0, image.size, options) ?: return null
            if (bitmap.width != UNIFIED_W || bitmap.height != UNIFIED_H) return null
            val pixels = IntArray(UNIFIED_W * UNIFIED_H)
            bitmap.getPixels(pixels, 0, UNIFIED_W, 0, 0, UNIFIED_W, UNIFIED_H)
            val code = Native.recognizeUnified(pixels, UNIFIED_W, UNIFIED_H)
            if (code != null && code.length == 4 && '?' !in code) code else null
        }.getOrNull()
    }
}
