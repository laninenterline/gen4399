package io.gen4399.app

/**
 * 规则校验的入口 —— 实现全部在 libgen4399.so（C），这里只是薄封装。
 */
object Rules {
    const val MIN_LENGTH = 6
    const val MAX_LENGTH = 20

    fun generatePassword(length: Int = 16): String = Native.generatePassword(length)

    fun generateUsername(length: Int = 12): String = Native.generateUsername(length)

    /** 生成带前后缀的用户名（前后缀本身由 C 侧长度校验保证合法） */
    fun generateUsername(length: Int, prefix: String, suffix: String): String {
        val middle = length - prefix.length - suffix.length
        require(middle >= 0) { "前后缀总长度不能超过用户名长度" }
        val body = if (middle > 0) Native.generateUsername(middle) else ""
        return prefix + body + suffix
    }

    fun validatePassword(password: String): List<String> =
        Native.checkPassword(password)?.let { listOf(it) } ?: emptyList()

    fun validateUsername(username: String): List<String> =
        Native.checkUsername(username)?.let { listOf(it) } ?: emptyList()

    fun validateIdcard(idcard: String): List<String> =
        Native.checkIdcard(idcard)?.let { listOf(it) } ?: emptyList()

    fun validateRealname(name: String): List<String> =
        Native.checkRealname(name)?.let { listOf(it) } ?: emptyList()

    fun maskIdcard(idcard: String): String = Native.maskIdcard(idcard)
}
