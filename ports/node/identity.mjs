// 身份信息校验：真实姓名 / 身份证号 / QQ（与 Python 版 gen4399.identity 对齐）。

const IDCARD_RE = /^[0-9]{17}[0-9Xx]$/;
const QQ_RE = /^[0-9]{4,11}$/;
const WEIGHTS = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2];
const CHECK = ['1', '0', 'X', '9', '8', '7', '6', '5', '4', '3', '2'];

/** 姓名：2~30 个字符，不能含数字/控制字符 */
export function validateRealname(name) {
  if (typeof name !== 'string') throw new TypeError('realname 必须是 string');
  const trimmed = name.trim();
  const out = [];
  if (trimmed.length < 2 || trimmed.length > 30) {
    out.push({ code: 'length', message: '姓名长度必须为 2~30 个字符' });
  }
  if (/[0-9]/.test(trimmed)) out.push({ code: 'charset', message: '姓名不能包含数字' });
  if (trimmed !== name) out.push({ code: 'whitespace', message: '姓名首尾不能有空白' });
  return out;
}

function validBirthday(y, m, d) {
  if (y < 1850 || y > 2050 || m < 1 || m > 12 || d < 1 || d > 31) return false;
  const date = new Date(Date.UTC(y, m - 1, d));
  return date.getUTCFullYear() === y && date.getUTCMonth() === m - 1 && date.getUTCDate() === d;
}

/** 身份证号：18 位 + 出生日期合法 + GB 11643 校验码正确 */
export function validateIdcard(idcard) {
  if (typeof idcard !== 'string') throw new TypeError('idcard 必须是 string');
  const s = idcard.trim().toUpperCase();
  const out = [];
  if (!IDCARD_RE.test(s)) {
    return [{ code: 'format', message: '身份证号格式不正确（应为 18 位数字，末位可为 X）' }];
  }
  const y = Number(s.slice(6, 10));
  const m = Number(s.slice(10, 12));
  const d = Number(s.slice(12, 14));
  if (!validBirthday(y, m, d)) out.push({ code: 'birthday', message: '身份证号中的出生日期不合法' });
  let total = 0;
  for (let i = 0; i < 17; i += 1) total += Number(s[i]) * WEIGHTS[i];
  if (CHECK[total % 11] !== s[17]) {
    out.push({ code: 'checksum', message: '身份证号校验码不正确，请核对' });
  }
  return out;
}

/** QQ：4~11 位数字，空串视为未填 */
export function validateQq(qq) {
  if (typeof qq !== 'string') throw new TypeError('qq 必须是 string');
  const value = qq.trim();
  if (!value) return [];
  return QQ_RE.test(value) ? [] : [{ code: 'format', message: 'QQ 号无效（应为 4~11 位数字）' }];
}

/** 一次性校验整份身份信息 */
export function validateProfile({ realname, idcard, qq = '' }) {
  return {
    realname: validateRealname(realname),
    idcard: validateIdcard(idcard),
    qq: validateQq(qq),
  };
}

/** 打码：110105********1893 */
export function maskIdcard(idcard) {
  const s = String(idcard);
  if (s.length !== 18) return '*'.repeat(s.length);
  return s.slice(0, 6) + '*'.repeat(8) + s.slice(14);
}
