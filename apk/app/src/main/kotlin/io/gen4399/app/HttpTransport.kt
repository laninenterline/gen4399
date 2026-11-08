package io.gen4399.app

import java.net.HttpURLConnection
import java.net.InetSocketAddress
import java.net.Proxy
import java.net.URL

/**
 * 唯一留在 Kotlin 的「非界面」代码：把一组 HTTP 参数发出去、把响应原样回传。
 *
 * 这里额外负责两件平台相关的事：
 *  1. **随机 UA** —— UA 由 C 生成（`Native.randomUserAgent()`），每个请求换一条；
 *  2. **代理池** —— 每个账号开始时切一个代理（`beginAccount()`），
 *     账号内的所有请求（表单 / 提交 / 验证码）都走同一个出口。
 */
object HttpTransport {
    data class ProxySpec(val host: String, val port: Int, val user: String?, val pass: String?)

    private val proxies = ArrayList<ProxySpec>()
    private var strategy = "round-robin"
    private var index = 0
    private var current: ProxySpec? = null
    private var userAgent: String = DEFAULT_UA

    private const val DEFAULT_UA =
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

    /** 解析 `host:port`、`http://host:port`、`user:pass@host:port` */
    fun parseProxies(text: String): List<ProxySpec> {
        val out = ArrayList<ProxySpec>()
        for (raw in text.lineSequence()) {
            val line = raw.trim()
            if (line.isEmpty() || line.startsWith("#")) continue
            var rest = line
            if (rest.startsWith("http://")) rest = rest.removePrefix("http://")
            if (rest.startsWith("https://")) rest = rest.removePrefix("https://")
            rest = rest.trimEnd('/')
            var user: String? = null
            var pass: String? = null
            val at = rest.lastIndexOf('@')
            if (at >= 0) {
                val auth = rest.substring(0, at)
                rest = rest.substring(at + 1)
                val colon = auth.indexOf(':')
                if (colon >= 0) {
                    user = auth.substring(0, colon)
                    pass = auth.substring(colon + 1)
                } else {
                    user = auth
                }
            }
            val colon = rest.lastIndexOf(':')
            if (colon <= 0) continue
            val host = rest.substring(0, colon)
            val port = rest.substring(colon + 1).toIntOrNull() ?: continue
            if (host.isEmpty() || port !in 1..65535) continue
            out += ProxySpec(host, port, user, pass)
        }
        return out
    }

    fun configure(proxyText: String, proxyStrategy: String, ua: String? = null) {
        proxies.clear()
        proxies += parseProxies(proxyText)
        strategy = proxyStrategy
        index = 0
        current = if (proxies.isEmpty()) null else proxies[0]
        userAgent = ua ?: DEFAULT_UA
    }

    fun proxyCount(): Int = proxies.size

    /** 每个账号开始时调用：换一条 UA、切一个代理 */
    fun beginAccount() {
        userAgent = runCatching { Native.randomUserAgent() }.getOrNull() ?: DEFAULT_UA
        if (proxies.isEmpty()) {
            current = null
            return
        }
        current = when (strategy) {
            "random" -> proxies[kotlin.random.Random.nextInt(proxies.size)]
            else -> {
                val pick = proxies[index % proxies.size]
                index += 1
                pick
            }
        }
    }

    fun currentProxyLabel(): String = current?.let { "${it.host}:${it.port}" } ?: "直连"

    private fun open(url: String, timeoutMs: Int): HttpURLConnection {
        val spec = current
        val connection = if (spec == null) {
            URL(url).openConnection()
        } else {
            URL(url).openConnection(Proxy(Proxy.Type.HTTP, InetSocketAddress(spec.host, spec.port)))
        }
        connection as HttpURLConnection
        connection.connectTimeout = timeoutMs
        connection.readTimeout = timeoutMs
        connection.instanceFollowRedirects = true
        connection.setRequestProperty("User-Agent", userAgent)
        spec?.let { proxy ->
            if (proxy.user != null) {
                val token = "${proxy.user}:${proxy.pass ?: ""}"
                val encoded = android.util.Base64.encodeToString(
                    token.toByteArray(), android.util.Base64.NO_WRAP
                )
                connection.setRequestProperty("Proxy-Authorization", "Basic $encoded")
            }
        }
        return connection
    }

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
            val conn = open(url, timeoutMs)
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
            val conn = open(url, timeoutMs)
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
