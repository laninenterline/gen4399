package io.gen4399.app

import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.spec.IvParameterSpec
import javax.crypto.spec.SecretKeySpec

/**
 * 4399 表单加密：CryptoJS 口令模式 AES-256-CBC + web 路径 encode_4399。
 *
 * 口令 `lzYW5qaXVqa` 就写在前端 JS 里，只用于协议互操作，不构成机密性保护。
 */
object Crypto {
    const val PASSPHRASE = "lzYW5qaXVqa"
    private val random = SecureRandom()

    /** EVP_BytesToKey(MD5)：CryptoJS/OpenSSL 口令模式的 key/iv 派生 */
    private fun evpBytesToKey(password: ByteArray, salt: ByteArray, keyLen: Int, ivLen: Int): Pair<ByteArray, ByteArray> {
        var previous = ByteArray(0)
        val material = ArrayList<Byte>()
        while (material.size < keyLen + ivLen) {
            val md = MessageDigest.getInstance("MD5")
            md.update(previous)
            md.update(password)
            md.update(salt)
            previous = md.digest()
            material.addAll(previous.toList())
        }
        val bytes = material.toByteArray()
        return bytes.copyOfRange(0, keyLen) to bytes.copyOfRange(keyLen, keyLen + ivLen)
    }

    /** Base64("Salted__" + salt + AES-256-CBC(明文)) */
    fun encryptAes(plaintext: String, passphrase: String = PASSPHRASE): String {
        val salt = ByteArray(8).also { random.nextBytes(it) }
        val (key, iv) = evpBytesToKey(passphrase.toByteArray(), salt, 32, 16)
        val cipher = Cipher.getInstance("AES/CBC/PKCS5Padding")
        cipher.init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"), IvParameterSpec(iv))
        val body = cipher.doFinal(plaintext.toByteArray(Charsets.UTF_8))
        val out = "Salted__".toByteArray() + salt + body
        return Base64.getEncoder().encodeToString(out)
    }

    fun decryptAes(ciphertext: String, passphrase: String = PASSPHRASE): String {
        val raw = Base64.getDecoder().decode(ciphertext)
        require(raw.size > 16 && String(raw, 0, 8) == "Salted__") { "不是 CryptoJS Salted__ 格式" }
        val salt = raw.copyOfRange(8, 16)
        val (key, iv) = evpBytesToKey(passphrase.toByteArray(), salt, 32, 16)
        val cipher = Cipher.getInstance("AES/CBC/PKCS5Padding")
        cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), IvParameterSpec(iv))
        return String(cipher.doFinal(raw.copyOfRange(16, raw.size)), Charsets.UTF_8)
    }

    /** encodeURIComponent 语义：字母数字和 - _ . ! ~ * ' ( ) 之外全部 %XX */
    private fun uriComponent(value: String): String {
        val safe = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.!~*'()"
        val sb = StringBuilder()
        for (byte in value.toByteArray(Charsets.UTF_8)) {
            val ch = byte.toInt() and 0xFF
            if (ch < 0x80 && safe.indexOf(ch.toChar()) >= 0) {
                sb.append(ch.toChar())
            } else {
                sb.append('%').append(String.format("%02X", ch))
            }
        }
        return sb.toString()
    }

    private fun prepareKey(key: String): ByteArray {
        val raw = key.toByteArray(Charsets.US_ASCII)
        return if (raw.size <= 8) {
            raw + ByteArray(8 - raw.size)
        } else {
            raw.copyOfRange(0, minOf(24, raw.size)) + ByteArray(maxOf(0, 24 - raw.size))
        }
    }

    /**
     * 复刻 encode_4399(value, key)：encodeURIComponent → NUL 补齐 → DES-ECB → "0x" + hex。
     * OpenSSL / JCE 里单 DES 也能用，这里用 DESede（K1=K2=K3）与 Node/C 版保持一致。
     */
    fun encode4399(value: String, key: String): String {
        require(key.isNotEmpty()) { "key 不能为空" }
        val encoded = uriComponent(value).toByteArray(Charsets.US_ASCII)
        if (encoded.isEmpty()) return "0x"
        val rawKey = prepareKey(key)
        val tripleKey = if (rawKey.size == 24) rawKey else rawKey + rawKey + rawKey
        val padLen = (8 - encoded.size % 8) % 8
        val padded = encoded + ByteArray(padLen)
        val cipher = Cipher.getInstance("DESede/ECB/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, SecretKeySpec(tripleKey, "DESede"))
        val out = cipher.doFinal(padded)
        return "0x" + out.joinToString("") { String.format("%02x", it) }
    }
}
