package io.gen4399.app

/**
 * libgen4399.so 的 JNI 绑定 —— 协议内核（加密、规则、载荷、判定）全在 C 里。
 * Kotlin 侧只负责界面和 HTTP 传输。
 */
object Native {
    init {
        System.loadLibrary("gen4399")
    }

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
    external fun parseHidden(html: String): String      // "name\tvalue\n..."
    external fun buildUnifiedPayload(
        hidden: String,
        username: String,
        password: String,
        realname: String,
        idcard: String,
        sendRealname: Boolean,
    ): String?                                          // 已 URL 编码的 body

    external fun classify(path: String, status: Int, body: String): String  // "kind\tmessage"
}
