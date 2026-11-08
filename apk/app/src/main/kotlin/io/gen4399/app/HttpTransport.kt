package io.gen4399.app

import java.net.HttpURLConnection
import java.net.URL

/**
 * 唯一留在 Kotlin 的「非界面」代码：把一组 HTTP 参数发出去，回传原始结果。
 * 没有业务判断——Cookie 由 C 侧维护，传进来的 cookieHeader 只负责带上。
 */
object HttpTransport {
    private const val UA =
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

    fun send(
        url: String,
        method: String,
        contentType: String,
        body: String,
        cookieHeader: String,
        referer: String,
        timeoutMs: Int = 15000,
    ): Array<String> {
        var status = 0
        var payload = ""
        val cookies = StringBuilder()
        try {
            val conn = URL(url).openConnection() as HttpURLConnection
            conn.connectTimeout = timeoutMs
            conn.readTimeout = timeoutMs
            conn.instanceFollowRedirects = true
            conn.setRequestProperty("User-Agent", UA)
            conn.setRequestProperty("Referer", referer.ifEmpty { "https://www.4399.com/" })
            conn.setRequestProperty("Accept-Language", "zh-CN,zh;q=0.9")
            conn.setRequestProperty("Cookie", cookieHeader)
            if (method == "POST" || body.isNotEmpty()) {
                conn.requestMethod = "POST"
                conn.doOutput = true
                conn.setRequestProperty(
                    "Content-Type",
                    contentType.ifEmpty { "application/x-www-form-urlencoded" },
                )
                conn.outputStream.use { it.write(body.toByteArray()) }
            }
            status = conn.responseCode
            conn.headerFields?.forEach { (key, values) ->
                if (key.equals("Set-Cookie", ignoreCase = true)) {
                    for (line in values) {
                        if (cookies.isNotEmpty()) cookies.append('\u001f')
                        cookies.append(line.substringBefore(';'))
                    }
                }
            }
            val stream = if (status in 200..399) conn.inputStream else conn.errorStream
            payload = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
        } catch (error: Exception) {
            status = 0
            payload = "transport-error: ${error.message}"
        }
        return arrayOf(status.toString(), cookies.toString(), payload)
    }

    /** 抓二进制（验证码图片）：不能按文本读，否则 PNG 会被 UTF-8 解码破坏 */
    fun fetchBytes(url: String, cookieHeader: String, referer: String, timeoutMs: Int = 15000): Array<Any> {
        var status = 0
        var bytes = ByteArray(0)
        try {
            val conn = URL(url).openConnection() as HttpURLConnection
            conn.connectTimeout = timeoutMs
            conn.readTimeout = timeoutMs
            conn.instanceFollowRedirects = true
            conn.setRequestProperty("User-Agent", UA)
            conn.setRequestProperty("Referer", referer.ifEmpty { "https://www.4399.com/" })
            conn.setRequestProperty("Cookie", cookieHeader)
            status = conn.responseCode
            val stream = if (status in 200..399) conn.inputStream else conn.errorStream
            bytes = stream?.use { it.readBytes() } ?: ByteArray(0)
        } catch (error: Exception) {
            status = 0
            bytes = ByteArray(0)
        }
        return arrayOf(status.toString(), bytes)
    }
}
