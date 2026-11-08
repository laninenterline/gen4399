package io.gen4399.app

/**
 * libgen4399.so 的 JNI 绑定。
 *
 * 除了界面，**所有逻辑**都在 C 里：账号生成、加密、表单解析、载荷组装、
 * 注册流程、验证码重试、节奏控制、结果判定。
 * Kotlin 只提供两件事：
 *   1. [Callback.transport] —— 发 HTTP（TLS 只有平台层有，C 侧没有可链接的 TLS 库）
 *   2. [Callback.askCaptcha] / [Callback.onProgress] —— 给界面用
 */
object Native {
    init {
        System.loadLibrary("gen4399")
    }

    /** 批量注册的回调；由 Kotlin 侧的界面实现 */
    interface Callback {
        /** 发一次请求，返回 [状态码, Set-Cookie 行（\u001f 分隔）, 响应体] */
        fun transport(
            url: String,
            method: String,
            contentType: String,
            body: String,
            cookieHeader: String,
            referer: String,
        ): Array<String>

        /** 抓二进制（验证码图片），返回 [状态码(String), ByteArray] */
        fun fetchBinary(url: String, cookieHeader: String, referer: String): Array<Any>

        /** 一个账号跑完（成功失败都会回调） */
        fun onProgress(
            index: Int,
            total: Int,
            username: String,
            password: String,
            kind: String,
            ok: Boolean,
            message: String,
        )

        /** 需要人工识别验证码；返回 4 位字符，null 表示跳过 */
        fun askCaptcha(image: ByteArray): String?
    }

    /**
     * 跑一批注册；返回成功数（负数表示出错）。
     * 会阻塞当前线程，调用方应放在 IO 线程。
     */
    external fun runBatch(
        identities: String,
        path: String,
        count: Int,
        prefix: String,
        suffix: String,
        intervalSec: Int,
        dryRun: Boolean,
        sendRealname: Boolean,
        callback: Callback,
    ): Int

    external fun generatePassword(length: Int): String
    external fun generateUsername(length: Int): String

    external fun checkPassword(value: String): String?
    external fun checkUsername(value: String): String?
    external fun checkIdcard(value: String): String?
    external fun checkRealname(value: String): String?
    external fun maskIdcard(value: String): String

    external fun aesEncrypt(plaintext: String): String
    external fun encode4399(value: String, key: String): String?

    external fun formUrl(appId: String, level: Int): String
    external fun parseHidden(html: String): String
    external fun buildUnifiedPayload(
        hidden: String,
        username: String,
        password: String,
        realname: String,
        idcard: String,
        sendRealname: Boolean,
    ): String?

    external fun classify(path: String, status: Int, body: String): String

    /** unified 60×30 验证码识别：传 ARGB 像素，成功返回 4 个字符 */
    external fun recognizeUnified(pixels: IntArray, width: Int, height: Int): String?
}
