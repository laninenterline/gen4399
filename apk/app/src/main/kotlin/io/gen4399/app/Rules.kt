package io.gen4399.app

import java.security.SecureRandom

/** 密码/用户名生成与校验、身份信息校验（与 Python 版规则一致）。 */
object Rules {
    const val CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    const val MIN_LENGTH = 6
    const val MAX_LENGTH = 20
    const val USERNAME_CHARSET = "abcdefghijklmnopqrstuvwxyz0123456789"

    private val random = SecureRandom()
    private val ALNUM = Regex("^[A-Za-z0-9]+$")
    private val DIGITS = Regex("^[0-9]+$")
    private val LOWER = Regex("^[a-z]+$")
    private val UPPER = Regex("^[A-Z]+$")
    private val IDCARD = Regex("^[0-9]{17}[0-9Xx]$")
    private val QQ = Regex("^[0-9]{4,11}$")
    private val WEIGHTS = intArrayOf(7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
    private const val CHECK = "10X98765432"

    private fun pick(charset: String, length: Int): String {
        val sb = StringBuilder(length)
        repeat(length) { sb.append(charset[random.nextInt(charset.length)]) }
        return sb.toString()
    }

    fun generatePassword(length: Int = 16): String {
        require(length in MIN_LENGTH..MAX_LENGTH) { "长度必须是 $MIN_LENGTH~$MAX_LENGTH" }
        repeat(1000) {
            val candidate = pick(CHARSET, length)
            if (validatePassword(candidate).isEmpty()) return candidate
        }
        error("生成失败")
    }

    fun generateUsername(length: Int = 12, prefix: String = "", suffix: String = ""): String {
        require(length in MIN_LENGTH..MAX_LENGTH) { "用户名长度必须是 $MIN_LENGTH~$MAX_LENGTH" }
        require(prefix.length + suffix.length <= length) { "前后缀总长度不能超过用户名长度" }
        val middle = length - prefix.length - suffix.length
        return prefix + pick(USERNAME_CHARSET, middle) + suffix
    }

    fun validatePassword(password: String): List<String> {
        val out = mutableListOf<String>()
        if (password.length !in MIN_LENGTH..MAX_LENGTH) out += "长度必须为 $MIN_LENGTH~$MAX_LENGTH 个字符，当前 ${password.length}"
        if (!ALNUM.matches(password)) out += "只允许使用字母和数字"
        if (DIGITS.matches(password)) out += "不能使用纯数字"
        if (LOWER.matches(password)) out += "不能使用纯小写字母"
        if (UPPER.matches(password)) out += "不能使用纯大写字母"
        return out
    }

    fun validateUsername(username: String): List<String> {
        val out = mutableListOf<String>()
        if (username.length !in MIN_LENGTH..MAX_LENGTH) out += "用户名长度必须为 $MIN_LENGTH~$MAX_LENGTH 个字符，当前 ${username.length}"
        if (!ALNUM.matches(username)) out += "用户名只允许使用字母和数字"
        return out
    }

    fun validateIdcard(idcard: String): List<String> {
        val s = idcard.trim().uppercase()
        if (!IDCARD.matches(s)) return listOf("身份证号格式不正确（应为 18 位数字，末位可为 X）")
        val out = mutableListOf<String>()
        val year = s.substring(6, 10).toIntOrNull() ?: 0
        val month = s.substring(10, 12).toIntOrNull() ?: 0
        val day = s.substring(12, 14).toIntOrNull() ?: 0
        val valid = year in 1850..2050 && month in 1..12 && day in 1..31
        if (!valid) out += "身份证号中的出生日期不合法"
        var total = 0
        for (i in 0 until 17) total += (s[i] - '0') * WEIGHTS[i]
        if (CHECK[total % 11] != s[17]) out += "身份证号校验码不正确，请核对"
        return out
    }

    fun validateRealname(name: String): List<String> {
        val out = mutableListOf<String>()
        val trimmed = name.trim()
        if (trimmed.length < 2 || trimmed.length > 30) out += "姓名长度必须为 2~30 个字符"
        if (trimmed.any { it.isDigit() }) out += "姓名不能包含数字"
        if (trimmed != name) out += "姓名首尾不能有空白"
        return out
    }

    fun validateQq(qq: String): List<String> {
        val value = qq.trim()
        if (value.isEmpty()) return emptyList()
        return if (QQ.matches(value)) emptyList() else listOf("QQ 号无效（应为 4~11 位数字）")
    }

    fun maskIdcard(idcard: String): String =
        if (idcard.length == 18) idcard.substring(0, 6) + "*".repeat(8) + idcard.substring(14) else "*".repeat(idcard.length)
}
