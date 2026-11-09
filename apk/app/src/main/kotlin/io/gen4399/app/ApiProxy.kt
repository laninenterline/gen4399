package io.gen4399.app

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URL

/**
 * 从代理商的「提取链接」拉 IP。
 *
 * 兼容三种常见返回：
 *  1. JSON：`{"data":{"list":[{"server":"1.2.3.4:8080"}]}}`
 *  2. JSON：`{"ip":"1.2.3.4","port":8080}`
 *  3. 纯文本：一行一个 `1.2.3.4:8080`
 *
 * 如果填了认证（`账号:密码`），输出会拼成 `账号:密码@1.2.3.4:8080`，
 * 这样代理池那边不用再单独配一次账号。
 */
object ApiProxy {
    private val SERVER_FIELD = Regex("\"server\"\\s*:\\s*\"([^\"]+)\"")
    private val IP_PORT = Regex("(\\d{1,3}(?:\\.\\d{1,3}){3})\\s*[:\",]\\s*(\\d{2,5})")

    data class Result(val lines: List<String>, val raw: Int, val snippet: String)

    suspend fun pull(url: String, auth: String, limit: Int = 50): Result = withContext(Dispatchers.IO) {
        val normalized = when {
            url.startsWith("http://") || url.startsWith("https://") -> url
            else -> "https://$url"
        }
        val text = try {
            httpGet(normalized)
        } catch (first: Exception) {
            // 有的接口只开 http，https 握手会失败，回退一次
            if (normalized.startsWith("https://")) {
                httpGet("http://" + normalized.removePrefix("https://"))
            } else {
                throw first
            }
        }
        val found = LinkedHashSet<String>()

        for (match in SERVER_FIELD.findAll(text)) {
            val value = match.groupValues[1].trim()
            if (value.contains(':')) found += value
        }
        if (found.isEmpty()) {
            for (match in IP_PORT.findAll(text)) {
                found += "${match.groupValues[1]}:${match.groupValues[2]}"
            }
        }

        val prefix = auth.trim().takeIf { it.contains(':') }
        val lines = found.take(limit).map { server ->
            if (prefix != null) "$prefix@$server" else server
        }
        Result(
            lines = lines,
            raw = found.size,
            snippet = text.take(120).replace("\n", " "),
        )
    }

    private fun httpGet(url: String): String {
        val conn = URL(url).openConnection() as HttpURLConnection
        conn.connectTimeout = 15_000
        conn.readTimeout = 15_000
        conn.instanceFollowRedirects = true
        conn.setRequestProperty("User-Agent", "Mozilla/5.0")
        val status = conn.responseCode
        if (status !in 200..299) {
            val body = runCatching {
                (conn.errorStream?.bufferedReader()?.use { it.readText() } ?: "").take(120)
            }.getOrDefault("")
            throw java.io.IOException("HTTP $status ${conn.responseMessage ?: ""} $body".trim())
        }
        return conn.inputStream.use { input ->
            val out = java.io.ByteArrayOutputStream()
            val buffer = ByteArray(32 * 1024)
            var total = 0
            while (true) {
                val read = input.read(buffer)
                if (read <= 0) break
                total += read
                if (total > 2 * 1024 * 1024) break
                out.write(buffer, 0, read)
            }
            out.toString("UTF-8")
        } ?: ""
    }
}
