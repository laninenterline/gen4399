package io.gen4399.app

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URL

/** 查当前出口 IP：代理商的 API 白名单要填这个地址。 */
object NetInfo {
    private val ECHO = listOf(
        "https://api.ipify.org",
        "https://api64.ipify.org",
        "https://ip.sb",
        "https://myip.ipip.net",
        "https://ifconfig.me/ip",
    )

    suspend fun currentIp(): String? = withContext(Dispatchers.IO) {
        for (endpoint in ECHO) {
            val value = runCatching { fetch(endpoint) }.getOrNull() ?: continue
            val ip = Regex("(\\d{1,3}(?:\\.\\d{1,3}){3})").find(value)?.value
            if (ip != null) return@withContext ip
            val v6 = Regex("([0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{0,4}){2,7})").find(value)?.value
            if (v6 != null && v6.contains(':')) return@withContext v6
        }
        null
    }

    private fun fetch(endpoint: String): String {
        val conn = URL(endpoint).openConnection() as HttpURLConnection
        conn.connectTimeout = 8_000
        conn.readTimeout = 8_000
        conn.setRequestProperty("User-Agent", "Mozilla/5.0")
        return conn.inputStream.use { it.bufferedReader().use { reader -> reader.readText() } }
    }
}
