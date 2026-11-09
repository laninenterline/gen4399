package io.gen4399.app

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.sync.Semaphore
import kotlinx.coroutines.sync.withPermit
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.InetSocketAddress
import java.net.Proxy
import java.net.URL

/** 代理可达性检测：真发一次请求，能拿到响应的才算可用。 */
object ProxyProbe {
    private const val PROBE_URL = "https://u.4399.com/"
    private const val TIMEOUT = 6_000

    data class Outcome(val line: String, val alive: Boolean, val millis: Long)

    /** 逐条测，返回每条的结果（保持输入顺序） */
    suspend fun testAll(
        lines: List<String>,
        concurrency: Int = 16,
        onProgress: (String) -> Unit = {},
    ): List<Outcome> = withContext(Dispatchers.IO) {
        if (lines.isEmpty()) return@withContext emptyList()
        val semaphore = Semaphore(concurrency)
        var done = 0
        val total = lines.size
        val results = arrayOfNulls<Outcome>(total)
        coroutineScope {
            lines.forEachIndexed { index, line ->
                async {
                    semaphore.withPermit {
                        val outcome = one(line)
                        results[index] = outcome
                        synchronized(this@coroutineScope) {
                            done++
                            if (done % 5 == 0 || done == total) onProgress("可达性检测 $done/$total")
                        }
                    }
                }
            }
        }
        results.filterNotNull()
    }

    fun parse(line: String): HttpTransport.ProxySpec? =
        HttpTransport.parseProxies(line).firstOrNull()

    private fun one(line: String): Outcome {
        val spec = parse(line) ?: return Outcome(line, false, 0)
        val started = System.currentTimeMillis()
        var conn: HttpURLConnection? = null
        val alive = try {
            val proxy = Proxy(spec.type, InetSocketAddress(spec.host, spec.port))
            conn = URL(PROBE_URL).openConnection(proxy) as HttpURLConnection
            conn.connectTimeout = TIMEOUT
            conn.readTimeout = TIMEOUT
            conn.instanceFollowRedirects = false
            conn.setRequestProperty("User-Agent", "Mozilla/5.0")
            if (spec.user != null && spec.type == Proxy.Type.HTTP) {
                val token = "${spec.user}:${spec.pass ?: ""}"
                val encoded = android.util.Base64.encodeToString(
                    token.toByteArray(), android.util.Base64.NO_WRAP
                )
                conn.setRequestProperty("Proxy-Authorization", "Basic $encoded")
            }
            conn.responseCode in 200..399
        } catch (_: Exception) {
            false
        } finally {
            runCatching { conn?.disconnect() }
        }
        return Outcome(line, alive, System.currentTimeMillis() - started)
    }
}
