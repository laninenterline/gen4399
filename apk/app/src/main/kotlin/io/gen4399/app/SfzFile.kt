package io.gen4399.app

import android.content.Context
import android.net.Uri
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.nio.charset.Charset

/**
 * 流式读取 sfz.txt —— 大文件分批读、支持断点续跑。
 *
 * 每次只取 [limit] 条有效身份，并给出下一批的起始字节偏移（[Page.nextOffset]）。
 * 25MB 的文本不会整份进内存，也不会塞进输入框。
 */
object SfzFile {
    private const val PREVIEW_LINES = 100
    private const val MAX_LINE = 4096

    data class Page(
        val identities: List<Identity>,
        val preview: String,
        val stats: ImportStats,
        /** 下一批的起始字节偏移 */
        val nextOffset: Long,
        /** 是否已读到文件末尾 */
        val eof: Boolean,
    )

    /** 从 [startOffset] 开始取一页身份 */
    fun loadPage(context: Context, uri: Uri, startOffset: Long, limit: Int): Page {
        val charset = detectCharset(context, uri)
        val identities = ArrayList<Identity>(minOf(limit, 256))
        val preview = StringBuilder()
        var lines = 0
        var valid = 0
        var previewLines = 0
        var nextOffset = startOffset
        var eof = true

        context.contentResolver.openInputStream(uri)?.use { stream ->
            skipFully(stream, startOffset)
            val reader = ByteLineReader(stream)
            while (true) {
                val lineStart = startOffset + reader.position
                val bytes = reader.readLine() ?: break
                lines++
                val line = String(bytes, charset).take(MAX_LINE).trim()
                if (line.isEmpty() || line.startsWith("#")) continue
                val parts = line.split('|', ',').map { it.trim() }
                if (parts.size < 2 || parts[0].isEmpty() || parts[1].isEmpty()) continue
                if (identities.size >= limit) {
                    // 这一行留给下一批：偏移回退到行首（只是数值，不碰流）
                    nextOffset = lineStart
                    eof = false
                    break
                }
                valid++
                identities += Identity(parts[0], parts[1], parts.getOrElse(2) { "" })
                if (previewLines < PREVIEW_LINES) {
                    if (preview.isNotEmpty()) preview.append('\n')
                    preview.append(line)
                    previewLines++
                }
            }
            if (eof) nextOffset = startOffset + reader.position
        }

        return Page(
            identities = identities,
            preview = preview.toString(),
            stats = ImportStats(
                lines = lines,
                valid = valid,
                kept = identities.size,
                encoding = if (charset == Charsets.UTF_8) "" else charset.name(),
            ),
            nextOffset = nextOffset,
            eof = eof,
        )
    }

    private fun skipFully(stream: InputStream, offset: Long) {
        var remaining = offset
        val buffer = ByteArray(64 * 1024)
        while (remaining > 0) {
            val read = stream.read(buffer, 0, minOf(remaining, buffer.size.toLong()).toInt())
            if (read <= 0) break
            remaining -= read
        }
    }

    /** 先按 UTF-8 读一小段，出现替换字符就按 GB18030 */
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

    /** 逐行读字节；[position] 始终等于「已消费的字节数」 */
    private class ByteLineReader(private val stream: InputStream, bufferSize: Int = 64 * 1024) {
        private val buffer = ByteArray(bufferSize)
        private var pos = 0
        private var available = 0
        private val line = ByteArrayOutputStream(256)

        var position: Long = 0L
            private set

        fun readLine(): ByteArray? {
            line.reset()
            var sawAny = false
            while (true) {
                if (pos >= available) {
                    available = stream.read(buffer)
                    pos = 0
                    if (available <= 0) {
                        available = 0
                        return if (!sawAny) null else trimCr(line.toByteArray())
                    }
                }
                val byte = buffer[pos++]
                position++
                sawAny = true
                if (byte == '\n'.code.toByte()) return trimCr(line.toByteArray())
                line.write(byte.toInt())
            }
        }

        private fun trimCr(bytes: ByteArray): ByteArray =
            if (bytes.isNotEmpty() && bytes[bytes.size - 1] == '\r'.code.toByte()) bytes.copyOf(bytes.size - 1) else bytes
    }
}
