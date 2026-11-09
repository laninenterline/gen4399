package io.gen4399.app

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.InetSocketAddress
import java.net.Proxy
import java.net.URL

/**
 * 免费代理池：从公开列表抓一批，再用真实请求验证，只留下能通的。
 *
 * 免费代理存活率很低（通常 5%~20%），所以**必须验证**——不验证直接塞进池子
 * 只会让每个账号都超时失败。
 */
object FreeProxy {
    /**
     * 公开的免费代理列表（纯文本，一行一个 host:port）。
     * 同一份数据放了多个入口：GitHub 原始地址在国内常被挡，所以补 jsDelivr / ghproxy 镜像。
     */
    private val SOURCES = listOf(
        // TheSpeedX 列表：三种入口
        "https://cdn.jsdelivr.net/gh/TheSpeedX/PROXY-List@master/http.txt",
        "https://fastly.jsdelivr.net/gh/TheSpeedX/PROXY-List@master/http.txt",
        "https://ghproxy.net/https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        // monosans 列表
        "https://cdn.jsdelivr.net/gh/monosans/proxy-list@main/proxies/http.txt",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
        // 非 GitHub 来源
        "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000",
        "https://www.proxy-list.download/api/v1/get?type=http",
        "https://proxyspace.pro/http.txt",
    )

    /** 验证用目标：能连上 4399 才算能用 */
    private const val PROBE_URL = "https://u.4399.com/"
    private const val FETCH_TIMEOUT = 9_000
    private const val PROBE_TIMEOUT = 4_000
    /** 最多留多少个可用的就够了 */
    private const val MAX_KEEP = 25
    /** 最多验证多少个候选（免费代理大多已死，验证太多只会干等） */
    private const val MAX_CANDIDATES = 200
    private const val CONCURRENCY = 24
    /** 整个验证阶段的预算，超时就带着已找到的返回 */
    private const val VALIDATE_BUDGET_MS = 75_000L

    data class Result(val fetched: Int, val alive: List<String>)

    /** 抓取 + 验证；[onProgress] 用于界面反馈 */
    suspend fun refresh(onProgress: (String) -> Unit): Result = withContext(Dispatchers.IO) {
        onProgress("正在获取免费代理列表（${SOURCES.size} 个源，并发抓取）…")
        val raw = LinkedHashSet<String>()
        val perSource = coroutineScope {
            SOURCES.map { source -> async { runCatching { fetchSource(source) }.getOrDefault(emptyList()) } }
                .map { it.await() }
        }
        for (list in perSource) {
            raw += list
            if (raw.size >= 800) break
        }
        if (raw.isEmpty()) return@withContext Result(0, emptyList())

        val candidates = raw.take(MAX_CANDIDATES)
        onProgress("候选 ${raw.size} 个，验证前 ${candidates.size} 个（并发 $CONCURRENCY）…")

        val alive = ArrayList<String>()
        var checked = 0
        val deadline = System.currentTimeMillis() + VALIDATE_BUDGET_MS

        for (chunk in candidates.chunked(CONCURRENCY)) {
            if (alive.size >= MAX_KEEP || System.currentTimeMillis() > deadline) break
            coroutineScope {
                val results = chunk.map { candidate -> async { probe(candidate) } }.map { it.await() }
                chunk.forEachIndexed { index, candidate ->
                    checked++
                    if (results[index] && alive.size < MAX_KEEP) alive += candidate
                }
            }
            onProgress("验证中 $checked/${candidates.size}，已找到 ${alive.size} 个可用…")
        }

        onProgress("验证完成：${alive.size}/$checked 可用")
        Result(raw.size, alive)
    }

    private suspend fun fetchSource(url: String): List<String> = withContext(Dispatchers.IO) {
        val text = httpGet(url, FETCH_TIMEOUT)
        val normalized = Native.parseProxies(text) ?: return@withContext emptyList()
        val out = ArrayList<String>()
        for (line in normalized.lineSequence()) {
            val parts = line.split('\t')
            if (parts.size >= 3 && parts[0] == "http") out += "${parts[1]}:${parts[2]}"
        }
        out
    }

    private fun httpGet(url: String, timeoutMs: Int): String {
        val conn = URL(url).openConnection() as HttpURLConnection
        conn.connectTimeout = timeoutMs
        conn.readTimeout = timeoutMs
        conn.instanceFollowRedirects = true
        conn.setRequestProperty("User-Agent", "Mozilla/5.0")
        return conn.inputStream.use { input ->
            val buffer = ByteArray(64 * 1024)
            val out = java.io.ByteArrayOutputStream()
            var read: Int
            var total = 0
            while (true) {
                read = input.read(buffer)
                if (read <= 0) break
                total += read
                if (total > 4 * 1024 * 1024) break
                out.write(buffer, 0, read)
            }
            out.toString("UTF-8")
        }
    }

    /** 用这个代理请求一次 4399，能拿到响应就算活 */
    private fun probe(candidate: String): Boolean {
        val colon = candidate.lastIndexOf(':')
        if (colon <= 0) return false
        val host = candidate.substring(0, colon)
        val port = candidate.substring(colon + 1).toIntOrNull() ?: return false
        var conn: HttpURLConnection? = null
        return try {
            val proxy = Proxy(Proxy.Type.HTTP, InetSocketAddress(host, port))
            conn = URL(PROBE_URL).openConnection(proxy) as HttpURLConnection
            conn.connectTimeout = PROBE_TIMEOUT
            conn.readTimeout = PROBE_TIMEOUT
            conn.instanceFollowRedirects = false
            conn.setRequestProperty("User-Agent", "Mozilla/5.0")
            val status = conn.responseCode
            status in 200..399
        } catch (_: Exception) {
            false
        } finally {
            runCatching { conn?.disconnect() }
        }
    }
}
