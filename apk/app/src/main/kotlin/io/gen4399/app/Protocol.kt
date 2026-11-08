package io.gen4399.app

import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/** 注册结果 */
data class SubmitResult(
    val kind: String,
    val ok: Boolean,
    val message: String,
    val username: String,
    val password: String,
    val path: String,
)

/** 身份信息 */
data class Identity(val name: String, val idcard: String, val qq: String = "")

/**
 * 4399 注册协议。
 *
 * 加密、字段组装、响应判定全部走 C 库（[Native]），
 * 这里只负责 HTTP 传输与验证码交互。
 */
object Protocol {
    const val WEB_REG_URL = "https://web.4399.com/user/?_c=reg"
    const val WEB_CHECK_URL = "https://web.4399.com/user/?_c=login&_a=checkUser"
    const val WEB_CAPTCHA_URL = "https://web.4399.com/util/?_c=code&t=reg"
    const val UNIFIED_CAPTCHA_URL = "https://ptlogin.4399.com/ptlogin/captcha.do?captchaId="

    private const val UA =
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

    class Session(private val timeoutMs: Int = 15000, private val referer: String = "https://www.4399.com/") {
        private val cookies = LinkedHashMap<String, String>()

        private fun cookieHeader() = cookies.entries.joinToString("; ") { "${it.key}=${it.value}" }

        private fun store(conn: HttpURLConnection) {
            conn.headerFields?.forEach { (key, values) ->
                if (key.equals("Set-Cookie", ignoreCase = true)) {
                    for (line in values) {
                        val pair = line.substringBefore(';')
                        val idx = pair.indexOf('=')
                        if (idx > 0) cookies[pair.substring(0, idx).trim()] = pair.substring(idx + 1).trim()
                    }
                }
            }
        }

        fun get(url: String): Response = request(url, null)

        /** 直接发已经是 URL 编码的 body（由 C 侧组装） */
        fun postEncoded(url: String, encodedBody: String): Response = request(url, encodedBody)

        fun post(url: String, form: Map<String, String>): Response {
            val body = form.entries.joinToString("&") {
                URLEncoder.encode(it.key, "UTF-8") + "=" + URLEncoder.encode(it.value, "UTF-8")
            }
            return request(url, body)
        }

        private fun request(url: String, body: String?): Response {
            val conn = URL(url).openConnection() as HttpURLConnection
            conn.connectTimeout = timeoutMs
            conn.readTimeout = timeoutMs
            conn.instanceFollowRedirects = true
            conn.setRequestProperty("User-Agent", UA)
            conn.setRequestProperty("Referer", referer)
            conn.setRequestProperty("Accept-Language", "zh-CN,zh;q=0.9")
            conn.setRequestProperty("Cookie", cookieHeader())
            if (body != null) {
                conn.requestMethod = "POST"
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/x-www-form-urlencoded")
                conn.outputStream.use { it.write(body.toByteArray()) }
            }
            val status = conn.responseCode
            val stream = if (status in 200..399) conn.inputStream else conn.errorStream
            val bytes = stream?.readBytes() ?: ByteArray(0)
            store(conn)
            return Response(status, bytes)
        }
    }

    data class Response(val status: Int, val bytes: ByteArray) {
        val text: String get() = bytes.toString(Charsets.UTF_8)
    }

    suspend fun submit(
        identity: Identity,
        username: String,
        password: String,
        channel: String,
        dryRun: Boolean,
        askCaptcha: suspend (ByteArray) -> String?,
    ): SubmitResult = if (channel == "web") {
        submitWeb(identity, username, password, dryRun, askCaptcha)
    } else {
        submitUnified(identity, username, password, dryRun, askCaptcha)
    }

    private fun classify(path: String, status: Int, body: String): Pair<String, String> {
        val raw = Native.classify(path, status, body)
        val parts = raw.split('\t', limit = 2)
        return parts[0] to parts.getOrElse(1) { "" }
    }

    private suspend fun submitUnified(
        identity: Identity,
        username: String,
        password: String,
        dryRun: Boolean,
        askCaptcha: suspend (ByteArray) -> String?,
    ): SubmitResult {
        val session = Session()
        val url = Native.formUrl("u4399", 4)
        val page = session.get(url)
        if (page.status == 202 || page.text.contains("请稍后再试")) {
            return SubmitResult("throttled", false, "服务端限流（请稍后再试）", username, password, "unified")
        }
        val hidden = Native.parseHidden(page.text) ?: ""
        if (hidden.isBlank()) {
            return SubmitResult("unknown", false, "注册页没有隐藏域，可能是风控页", username, password, "unified")
        }
        val body = Native.buildUnifiedPayload(hidden, username, password, identity.name, identity.idcard, true)
            ?: return SubmitResult("error", false, "C 内核组装载荷失败", username, password, "unified")

        if (dryRun) {
            return SubmitResult("dry_run", false, "dry-run：未发送 POST（${body.count { it == '&' } + 1} 个字段）", username, password, "unified")
        }

        var response = session.postEncoded("https://ptlogin.4399.com/ptlogin/register.do", body)
        for (round in 0 until 3) {
            val (kind, _) = classify("unified", response.status, response.text)
            if (kind == "success") break
            if (kind != "captcha") break
            val captchaId = Regex("""captchaId=([A-Za-z0-9]+)""").find(response.text)?.groupValues?.get(1) ?: break
            val image = session.get(UNIFIED_CAPTCHA_URL + captchaId)
            val code = askCaptcha(image.bytes) ?: break
            if (code.isBlank()) break
            val hiddenNow = Native.parseHidden(response.text) ?: hidden
            val retry = Native.buildUnifiedPayload(hiddenNow, username, password, identity.name, identity.idcard, true)
                ?: break
            val withCode = "$retry&inputCaptcha=${URLEncoder.encode(code, "UTF-8")}&sessionId=$captchaId"
            response = session.postEncoded("https://ptlogin.4399.com/ptlogin/register.do", withCode)
        }
        val (kind, message) = classify("unified", response.status, response.text)
        return SubmitResult(kind, kind == "success", message, username, password, "unified")
    }

    private suspend fun submitWeb(
        identity: Identity,
        username: String,
        password: String,
        dryRun: Boolean,
        askCaptcha: suspend (ByteArray) -> String?,
    ): SubmitResult {
        val session = Session()
        val check = session.get("$WEB_CHECK_URL&user=${URLEncoder.encode(username, "UTF-8")}&jsoncallback=cb")
        val encryptCode = Regex(""""data"\s*:\s*"([^"]+)"""").find(check.text)?.groupValues?.get(1) ?: "5c43e3"

        val cipher = Native.encode4399(password, encryptCode)
            ?: return SubmitResult("error", false, "C 内核加密失败", username, password, "web")
        val payload = linkedMapOf(
            "cid" to "3000",
            "login_name" to username,
            "login_password" to cipher,
            "relogin_pwd" to cipher,
            "qq" to identity.qq,
            "true_name" to identity.name,
            "sfz" to identity.idcard,
            "encrypt" to "1",
        )
        if (dryRun) return SubmitResult("dry_run", false, "dry-run：未发送 POST（8 个字段）", username, password, "web")

        var response = session.post("$WEB_REG_URL&jsoncallback=cb", payload)
        for (round in 0 until 3) {
            val (kind, _) = classify("web", response.status, response.text)
            if (kind == "success") break
            if (kind != "captcha") break
            val image = session.get(WEB_CAPTCHA_URL)
            val answer = askCaptcha(image.bytes) ?: break
            if (answer.isBlank()) break
            response = session.post(
                "$WEB_REG_URL&jsoncallback=cb",
                LinkedHashMap(payload).apply { put("chk_code", answer) },
            )
        }
        val (kind, message) = classify("web", response.status, response.text)
        return SubmitResult(kind, kind == "success", message, username, password, "web")
    }
}
