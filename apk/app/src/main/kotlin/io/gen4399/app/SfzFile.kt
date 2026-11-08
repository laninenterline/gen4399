package io.gen4399.app

import android.content.Context
import android.net.Uri
import java.io.BufferedReader
import java.io.InputStreamReader
import java.nio.charset.Charset

/**
 * 流式读取 sfz.txt —— 大文件不整份读进内存。
 *
 * 逐行解析、只保留前 [limit] 条有效身份，并返回一个**有界**的预览文本给输入框
 * （25MB 的文本塞进 Compose 的 TextField 会直接把 App 拖死）。
 */
object SfzFile {
    /** 预览最多给输入框多少行 */
    private const val PREVIEW_LINES = 100

    /** 单行最长多少字符（防止异常长行） */
    private const val MAX_LINE = 4096

    data class Outcome(
        val identities: List<Identity>,
        val preview: String,
        val stats: ImportStats,
    )

    fun load(context: Context, uri: Uri, limit: Int): Outcome {
        val charset = detectCharset(context, uri)
        val identities = ArrayList<Identity>(minOf(limit, 256))
        val preview = StringBuilder()
        var lines = 0
        var valid = 0

        context.contentResolver.openInputStream(uri)?.use { stream ->
            BufferedReader(InputStreamReader(stream, charset), 64 * 1024).use { reader ->
                while (true) {
                    val raw = reader.readLine() ?: break
                    lines++
                    val line = raw.take(MAX_LINE).trim()
                    if (line.isEmpty() || line.startsWith("#")) continue
                    val parts = line.split('|', ',').map { it.trim() }
                    if (parts.size < 2 || parts[0].isEmpty() || parts[1].isEmpty()) continue
                    valid++
                    if (identities.size < limit) {
                        identities += Identity(parts[0], parts[1], parts.getOrElse(2) { "" })
                        if (preview.lines().count() <= PREVIEW_LINES) {
                            if (preview.isNotEmpty()) preview.append('\n')
                            preview.append(line)
                        }
                    }
                }
            }
        }

        return Outcome(
            identities = identities,
            preview = preview.toString(),
            stats = ImportStats(
                lines = lines,
                valid = valid,
                kept = identities.size,
                encoding = if (charset == Charsets.UTF_8) "" else charset.name(),
            ),
        )
    }

    /** 先按 UTF-8 读一小段，出现替换字符就按 GB18030 再读 */
    private fun detectCharset(context: Context, uri: Uri): Charset {
        val sample = ByteArray(64 * 1024)
        var read = 0
        context.contentResolver.openInputStream(uri)?.use { stream ->
            read = stream.read(sample)
        }
        if (read <= 0) return Charsets.UTF_8
        val asUtf8 = String(sample, 0, read, Charsets.UTF_8)
        return if (asUtf8.contains('\uFFFD')) Charset.forName("GB18030") else Charsets.UTF_8
    }
}
