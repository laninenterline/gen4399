// 4399 表单加密：CryptoJS 口令模式 AES-256-CBC + web 路径 DES/3DES-ECB。
//
// 这两个算法只是为了「和 4399 页面 JS 互操作」——4399 的口令 `lzYW5qaXVqa`
// 就写在前端 JS 里，不构成任何机密性保护。

import crypto from 'node:crypto';

/** 4399 注册页前端硬编码的 CryptoJS 口令（公开可查） */
export const PASSPHRASE = 'lzYW5qaXVqa';
const SALTED = Buffer.from('Salted__', 'ascii');

// encodeURIComponent 不转义的字符（与 JS 内置实现一致）
const URI_SAFE = /^[A-Za-z0-9\-_.!~*'()]$/;

function encodeUriComponent(str) {
  let out = '';
  for (const ch of str) {
    if (URI_SAFE.test(ch)) {
      out += ch;
      continue;
    }
    for (const byte of Buffer.from(ch, 'utf8')) {
      out += '%' + byte.toString(16).toUpperCase().padStart(2, '0');
    }
  }
  return out;
}

/** EVP_BytesToKey（MD5）：CryptoJS 口令模式用的 key/iv 派生 */
function evpBytesToKey(password, salt, keyLen, ivLen) {
  const chunks = [];
  let previous = Buffer.alloc(0);
  let total = 0;
  while (total < keyLen + ivLen) {
    const hash = crypto.createHash('md5');
    hash.update(previous);
    hash.update(password);
    hash.update(salt);
    previous = hash.digest();
    chunks.push(previous);
    total += previous.length;
  }
  const material = Buffer.concat(chunks);
  return { key: material.subarray(0, keyLen), iv: material.subarray(keyLen, keyLen + ivLen) };
}

/**
 * CryptoJS 口令模式加密：`Base64("Salted__" + salt + AES-256-CBC)`。
 * @param {string} plaintext
 * @param {string|Buffer} passphrase
 * @returns {string} Base64
 */
export function encryptAes(plaintext, passphrase = PASSPHRASE) {
  if (typeof plaintext !== 'string') throw new TypeError('plaintext 必须是 string');
  const password = Buffer.isBuffer(passphrase) ? passphrase : Buffer.from(String(passphrase), 'utf8');
  const salt = crypto.randomBytes(8);
  const { key, iv } = evpBytesToKey(password, salt, 32, 16);
  const cipher = crypto.createCipheriv('aes-256-cbc', key, iv);
  const body = Buffer.concat([cipher.update(Buffer.from(plaintext, 'utf8')), cipher.final()]);
  return Buffer.concat([SALTED, salt, body]).toString('base64');
}

/**
 * 解开 CryptoJS 口令模式的密文（主要给测试/排错用）。
 * @param {string} ciphertext Base64
 * @param {string|Buffer} passphrase
 * @returns {string} 明文
 */
export function decryptAes(ciphertext, passphrase = PASSPHRASE) {
  const raw = Buffer.from(ciphertext, 'base64');
  if (raw.subarray(0, 8).toString('ascii') !== 'Salted__') {
    throw new Error('不是 CryptoJS「Salted__」格式');
  }
  const salt = raw.subarray(8, 16);
  const password = Buffer.isBuffer(passphrase) ? passphrase : Buffer.from(String(passphrase), 'utf8');
  const { key, iv } = evpBytesToKey(password, salt, 32, 16);
  const decipher = crypto.createDecipheriv('aes-256-cbc', key, iv);
  const body = Buffer.concat([decipher.update(raw.subarray(16)), decipher.final()]);
  return body.toString('utf8');
}

/** 把 JS 里的口令字符串转成 DES/3DES key（NUL 补齐到 8 或 24 字节） */
function prepareKey(key) {
  if (typeof key !== 'string') throw new TypeError('key 必须是 string');
  if (!key) throw new Error('key 不能为空');
  const raw = Buffer.from(key, 'ascii');
  if (raw.length <= 8) return Buffer.concat([raw, Buffer.alloc(8 - raw.length)]);
  return Buffer.concat([raw.subarray(0, 24), Buffer.alloc(Math.max(0, 24 - raw.length))]);
}

/**
 * 复刻 4399 web 注册页的 `encode_4399(value, key)`。
 *
 * 算法：`encodeURIComponent` → NUL 补齐到 8 的倍数 → DES-ECB（key > 8 时用 3DES-EDE）
 * → `"0x" + 小写 hex`。
 *
 * 注：OpenSSL 3 关掉了单 DES，这里用「同一把 key 重复三遍的三重 DES」等价实现。
 * @param {string} value
 * @param {string} key checkUser 下发的 encryptCode
 * @returns {string}
 */
export function encode4399(value, key) {
  if (typeof value !== 'string') throw new TypeError('value 必须是 string');
  const encoded = Buffer.from(encodeUriComponent(value), 'ascii');
  if (encoded.length === 0) return '0x';

  const rawKey = prepareKey(key);
  const tripleKey = rawKey.length === 24
    ? rawKey
    : Buffer.concat([rawKey, rawKey, rawKey]);   // K1=K2=K3 退化回单 DES

  const padLen = (8 - (encoded.length % 8)) % 8;
  const padded = Buffer.concat([encoded, Buffer.alloc(padLen)]);

  const cipher = crypto.createCipheriv('des-ede3', tripleKey, null);
  cipher.setAutoPadding(false);                   // Python 侧是手工补 NUL，不用 PKCS#7
  const out = Buffer.concat([cipher.update(padded), cipher.final()]);
  return '0x' + out.toString('hex');
}
