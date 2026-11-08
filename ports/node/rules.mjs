// 密码 / 用户名的生成与校验（与 Python 版 gen4399.core 对齐）。

import crypto from 'node:crypto';

export const CHARSET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789';
export const MIN_LENGTH = 6;
export const MAX_LENGTH = 20;
export const DEFAULT_LENGTH = 16;

export const USERNAME_CHARSET = 'abcdefghijklmnopqrstuvwxyz0123456789';
export const USERNAME_MIN_LENGTH = 6;
export const USERNAME_MAX_LENGTH = 20;
export const DEFAULT_USERNAME_LENGTH = 12;

const ALNUM = /^[A-Za-z0-9]+$/;
const DIGITS = /^[0-9]+$/;
const LOWER = /^[a-z]+$/;
const UPPER = /^[A-Z]+$/;

function pick(charset, length) {
  const bytes = crypto.randomBytes(length * 2);
  let out = '';
  let i = 0;
  while (out.length < length) {
    if (i >= bytes.length) return pick(charset, length); // 极少见，重来
    const b = bytes[i++];
    if (b >= 256 - (256 % charset.length)) continue;   // 拒绝采样，避免取模偏置
    out += charset[b % charset.length];
  }
  return out;
}

/** 生成一个符合 4399 规则的密码 */
export function generatePassword(length = DEFAULT_LENGTH, charset = CHARSET) {
  if (!Number.isInteger(length) || length < MIN_LENGTH || length > MAX_LENGTH) {
    throw new RangeError(`长度必须是 ${MIN_LENGTH}~${MAX_LENGTH} 的整数`);
  }
  if (!charset || [...charset].some((c) => !CHARSET.includes(c))) {
    throw new Error('字符集只能包含 ASCII 字母和数字');
  }
  if (!/[0-9]/.test(charset) || !/[A-Za-z]/.test(charset)) {
    throw new Error('字符集必须同时包含数字和字母，否则生成的密码必然违规');
  }
  for (let attempt = 0; attempt < 1000; attempt += 1) {
    const candidate = pick(charset, length);
    if (validatePassword(candidate).length === 0) return candidate;
  }
  throw new Error('生成失败：字符集太小，凑不出合规密码');
}

/** 生成一个用户名（默认小写字母 + 数字） */
export function generateUsername(length = DEFAULT_USERNAME_LENGTH, prefix = '', suffix = '') {
  const total = length;
  if (!Number.isInteger(total) || total < USERNAME_MIN_LENGTH || total > USERNAME_MAX_LENGTH) {
    throw new RangeError(`用户名长度必须是 ${USERNAME_MIN_LENGTH}~${USERNAME_MAX_LENGTH}`);
  }
  if ((prefix && !ALNUM.test(prefix)) || (suffix && !ALNUM.test(suffix))) {
    throw new Error('前后缀只能包含字母和数字');
  }
  if (prefix.length + suffix.length > total) {
    throw new Error('前后缀总长度不能超过用户名长度');
  }
  const middle = total - prefix.length - suffix.length;
  return prefix + (middle > 0 ? pick(USERNAME_CHARSET, middle) : '') + suffix;
}

/** 校验密码，返回违规列表（空数组 = 合规） */
export function validatePassword(password) {
  if (typeof password !== 'string') throw new TypeError('password 必须是 string');
  const out = [];
  const n = password.length;
  if (n < MIN_LENGTH || n > MAX_LENGTH) {
    out.push({ code: 'length', message: `长度必须为 ${MIN_LENGTH}~${MAX_LENGTH} 个字符，当前 ${n}` });
  }
  if (!ALNUM.test(password)) out.push({ code: 'charset', message: '只允许使用字母和数字' });
  if (DIGITS.test(password)) out.push({ code: 'all_digits', message: '不能使用纯数字' });
  if (LOWER.test(password)) out.push({ code: 'all_lower', message: '不能使用纯小写字母' });
  if (UPPER.test(password)) out.push({ code: 'all_upper', message: '不能使用纯大写字母' });
  return out;
}

/** 校验用户名（比密码宽松：允许纯数字） */
export function validateUsername(username) {
  if (typeof username !== 'string') throw new TypeError('username 必须是 string');
  const out = [];
  const n = username.length;
  if (n < USERNAME_MIN_LENGTH || n > USERNAME_MAX_LENGTH) {
    out.push({
      code: 'length',
      message: `用户名长度必须为 ${USERNAME_MIN_LENGTH}~${USERNAME_MAX_LENGTH} 个字符，当前 ${n}`,
    });
  }
  if (!ALNUM.test(username)) out.push({ code: 'charset', message: '用户名只允许使用字母和数字' });
  return out;
}

/** 生成时的理论熵（bit） */
export function entropyBits(length, charsetSize = CHARSET.length) {
  return length * Math.log2(charsetSize);
}
