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

/** 4399 注册协议（unified / web），只依赖 java.net。 */
object Protocol {
    const val UNIFIED_URL = "https://ptlogin.4399.com/ptlogin/register.do"
    const val WEB_REG_URL = "https://web.4399.com/user/?_c=reg"
    const val WEB_CHECK_URL = "https://web.4399.com/user/?_c=login&_a=checkUser"
    const val WEB_CAPTCHA_URL = "https://web.4399.com/util/?_c=code&t=reg"
    const val UNIFIED_CAPTCHA_URL = "https://ptlogin.4399.com/ptlogin/captcha.do?captchaId="

    private const val UA =
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

    /** 回传会让服务端改走空白「4399提示」页的隐藏域 */
    val DROP_FIELDS = setOf(
        "crossDomainUrl", "mainDivId", "showRegInfo", "includeFcmInfo", "expandFcmInput",
        "fcmFakeValidate", "realnameValidate", "userNameLabel", "iframeId",
        "email", "reg_eula_agree", "autoLogin", "fCaptcha",
    )

    /** 极简 Cookie 会话 */
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

        fun get(url: String): HttpResponse = request(url, null)

        fun post(url: String, form: Map<String, String>): HttpResponse {
            val body = form.entries.joinToString("&") {
                URLEncoder.encode(it.key, "UTF-8") + "=" + URLEncoder.encode(it.value, "UTF-8")
            }
            return request(url, body)
        }

        private fun request(url: String, body: String?): HttpResponse {
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
            return HttpResponse(status, bytes)
        }
    }

    data class HttpResponse(val status: Int, val bytes: ByteArray) {
        val text: String get() = bytes.toString(Charsets.UTF_8)
    }

    private fun formUrl(appId: String, level: Int): String {
        val params = linkedMapOf(
            "regMode" to "reg_normal", "postLoginHandler" to "refreshParent", "displayMode" to "",
            "bizId" to "", "redirectUrl" to "", "css" to "", "appId" to appId, "gameId" to "",
            "noEmail" to "false", "regIdcard" to "true", "autoLogin" to "false", "cid" to "",
            "aid" to "", "ref" to "", "level" to level.toString(), "mainDivId" to "popup_reg_div",
            "includeFcmInfo" to "false", "externalLogin" to "qq", "fcmFakeValidate" to "false",
            "expandFcmInput" to "false", "userNameLabel" to "", "userNameTip" to "",
            "welcomeTip" to "", "v" to System.currentTimeMillis().toString(),
        )
        return UNIFIED_URL + "?" + params.entries.joinToString("&") { "${it.key}=${it.value}" }
    }

    private val HIDDEN_INPUT = Regex("""<input\b[^>]*>""", RegexOption.IGNORE_CASE)
    private val NAME_ATTR = Regex("""name\s*=\s*["']([^"']+)["']""", RegexOption.IGNORE_CASE)
    private val VALUE_ATTR = Regex("""value\s*=\s*["']([^"']*)["']""", RegexOption.IGNORE_CASE)
    private val TYPE_ATTR = Regex("""type\s*=\s*["']([^"']+)["']""", RegexOption.IGNORE_CASE)
    private val ACTION_ATTR = Regex("""<form\b[^>]*action\s*=\s*["']([^"']+)["']""", RegexOption.IGNORE_CASE)

    fun parseHidden(body: String): Map<String, String> {
        val out = LinkedHashMap<String, String>()
        for (tag in HIDDEN_INPUT.findAll(body)) {
            val text = tag.value
            val type = TYPE_ATTR.find(text)?.groupValues?.get(1)?.lowercase()
            if (type != "hidden") continue
            val name = NAME_ATTR.find(text)?.groupValues?.get(1) ?: continue
            val value = VALUE_ATTR.find(text)?.groupValues?.get(1) ?: ""
            out[name] = value.replace("&amp;", "&")
        }
        return out
    }

    fun formAction(body: String): String {
        val raw = ACTION_ATTR.find(body)?.groupValues?.get(1)?.replace("&amp;", "&") ?: return UNIFIED_URL
        return when {
            raw.startsWith("//") -> "https:$raw"
            raw.startsWith("/") -> "https://ptlogin.4399.com$raw"
            else -> raw
        }
    }

    private fun msgOf(body: String): String =
        Regex("""<div\b[^>]*id\s*=\s*["']Msg["'][^>]*>(.*?)</div>""", setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL))
            .find(body)?.groupValues?.get(1)?.replace(Regex("<[^>]+>"), "")?.trim() ?: ""

    /**
     * 提交一次注册。
     * @param askCaptcha 需要图形验证码时调用：入参图片字节，返回用户输入的 4 位；返回 null 表示放弃
     */
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

    private suspend fun submitUnified(
        identity: Identity,
        username: String,
        password: String,
        dryRun: Boolean,
        askCaptcha: suspend (ByteArray) -> String?,
    ): SubmitResult {
        val session = Session()
        val url = formUrl("u4399", 4)
        val page = session.get(url)
        if (page.status == 202 || page.text.contains("请稍后再试")) {
            return SubmitResult("throttled", false, "服务端限流（请稍后再试）", username, password, "unified")
        }
        val hidden = parseHidden(page.text)
        if (hidden.isEmpty()) {
            return SubmitResult("unknown", false, "注册页没有隐藏域，可能是风控页", username, password, "unified")
        }
        val action = formAction(page.text)
        val sec = (hidden["sec"] ?: "1").ifBlank { "1" }

        val payload = LinkedHashMap<String, String>()
        hidden.forEach { (k, v) -> if (k !in DROP_FIELDS) payload[k] = v }
        payload["username"] = username
        payload["password"] = password
        payload["passwordveri"] = password
        payload["realname"] = identity.name
        payload["idcard"] = identity.idcard
        payload["appId"] = "u4399"
        payload["level"] = "4"
        payload.putIfAbsent("regMode", "reg_normal")
        payload["sec"] = sec

        if (sec == "1") {
            for (name in listOf("password", "passwordveri", "realname", "idcard")) {
                payload[name]?.let { payload[name] = Crypto.encryptAes(it) }
            }
        }
        if (dryRun) return SubmitResult("dry_run", false, "dry-run：未发送 POST（${payload.size} 个字段）", username, password, "unified")

        var response = session.post(action, payload)
        var body = response.text
        for (round in 0 until 3) {
            if (body.contains("isAutoRegSuccess = true") || body.contains("自动注册成功")) break
            if (!body.contains("inputCaptcha")) break
            val captchaId = Regex("""captchaId=([A-Za-z0-9]+)""").find(body)?.groupValues?.get(1) ?: break
            val image = session.get(UNIFIED_CAPTCHA_URL + captchaId)
            val code = askCaptcha(image.bytes) ?: break
            if (code.isBlank()) break
            val retry = LinkedHashMap(payload)
            parseHidden(body).forEach { (k, v) -> retry[k] = v }
            retry["inputCaptcha"] = code
            retry["sessionId"] = captchaId
            response = session.post(action, retry)
            body = response.text
        }
        return when {
            body.contains("isAutoRegSuccess = true") || body.contains("自动注册成功") ->
                SubmitResult("success", true, "注册成功", username, password, "unified")
            body.contains("请稍后再试") ->
                SubmitResult("throttled", false, "服务端限流", username, password, "unified")
            body.contains("inputCaptcha") ->
                SubmitResult("captcha", false, "服务端要求图形验证码", username, password, "unified")
            msgOf(body).isNotEmpty() ->
                SubmitResult("rejected", false, msgOf(body), username, password, "unified")
            else ->
                SubmitResult("unknown", false, "无法判定注册结果", username, password, "unified")
        }
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

        val payload = linkedMapOf(
            "cid" to "3000",
            "login_name" to username,
            "login_password" to Crypto.encode4399(password, encryptCode),
            "relogin_pwd" to Crypto.encode4399(password, encryptCode),
            "qq" to identity.qq,
            "true_name" to identity.name,
            "sfz" to identity.idcard,
            "encrypt" to "1",
        )
        if (dryRun) return SubmitResult("dry_run", false, "dry-run：未发送 POST（8 个字段）", username, password, "web")

        var response = session.post("$WEB_REG_URL&jsoncallback=cb", payload)
        for (round in 0 until 3) {
            val state = Regex(""""state"\s*:\s*(true|false)""").find(response.text)?.groupValues?.get(1)
            if (state == "true") break
            val code = Regex(""""code"\s*:\s*(\d+)""").find(response.text)?.groupValues?.get(1)
            if (code != "200") break
            val image = session.get(WEB_CAPTCHA_URL)
            val answer = askCaptcha(image.bytes) ?: break
            if (answer.isBlank()) break
            response = session.post("$WEB_REG_URL&jsoncallback=cb", LinkedHashMap(payload).apply { put("chk_code", answer) })
        }
        val state = Regex(""""state"\s*:\s*(true|false)""").find(response.text)?.groupValues?.get(1)
        return when {
            state == "true" -> SubmitResult("success", true, "注册成功", username, password, "web")
            response.text.contains("请稍后再试") -> SubmitResult("throttled", false, "服务端限流", username, password, "web")
            response.status == 202 -> SubmitResult("throttled", false, "服务端限流（202）", username, password, "web")
            else -> SubmitResult("rejected", false, msgOf(response.text).ifBlank { "注册被拒绝" }, username, password, "web")
        }
    }
}
