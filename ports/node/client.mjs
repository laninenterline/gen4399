// 4399 注册 / 登录的 HTTP 客户端（零依赖，用 Node 内置 fetch + 手写 Cookie 罐）。

import { encode4399, encryptAes } from './crypto.mjs';
import { validateIdcard, validateRealname } from './identity.mjs';
import { validatePassword as vp, validateUsername } from './rules.mjs';

export const APP_ID = 'u4399';
export const REG_FRAME_URL = 'https://ptlogin.4399.com/ptlogin/regFrame.do';
export const REGISTER_URL = 'https://ptlogin.4399.com/ptlogin/register.do';
export const WEB_REG_API = 'https://web.4399.com/user/?_c=reg';
export const WEB_CHECK_USER_API = 'https://web.4399.com/user/?_c=login&_a=checkUser';
export const WEB_CAPTCHA_API = 'https://web.4399.com/util/?_c=code&t=reg';
export const LOGIN_URL = 'https://ptlogin.4399.com/ptlogin/login.do?v=1';

/** 实测回传会让服务端改走空白「4399提示」页的隐藏域 */
export const UNIFIED_DROP_FIELDS = new Set([
  'crossDomainUrl', 'mainDivId', 'showRegInfo', 'includeFcmInfo', 'expandFcmInput',
  'fcmFakeValidate', 'realnameValidate', 'userNameLabel', 'iframeId',
  'email', 'reg_eula_agree', 'autoLogin', 'fCaptcha',
]);

const LOGIN_COOKIE_NAMES = ['Pauth', 'Pauths', 'Uauth', 'Xauth', 'Puser', 'Pnick', 'Qnick', 'user_4399', 'ck_accname', 'ptusertype'];

/** 极简 Cookie 罐：只保留 name=value，够注册/登录用 */
export class Session {
  constructor({ timeout = 15, userAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36', referer = 'https://www.4399.com/' } = {}) {
    this.timeout = timeout;
    this.userAgent = userAgent;
    this.referer = referer;
    this.cookies = new Map();
    this.extraHeaders = {};
  }

  cookieHeader() {
    return [...this.cookies].map(([k, v]) => `${k}=${v}`).join('; ');
  }

  storeCookies(response) {
    const raw = typeof response.headers.getSetCookie === 'function'
      ? response.headers.getSetCookie()
      : (response.headers.get('set-cookie') ? [response.headers.get('set-cookie')] : []);
    for (const line of raw) {
      const [pair] = line.split(';');
      const eq = pair.indexOf('=');
      if (eq > 0) this.cookies.set(pair.slice(0, eq).trim(), pair.slice(eq + 1).trim());
    }
  }

  async request(url, { method = 'GET', body = null, headers = {} } = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout * 1000);
    try {
      const response = await fetch(url, {
        method,
        body,
        redirect: 'follow',
        signal: controller.signal,
        headers: {
          'User-Agent': this.userAgent,
          Referer: this.referer,
          'Accept-Language': 'zh-CN,zh;q=0.9',
          Cookie: this.cookieHeader(),
          ...this.extraHeaders,
          ...headers,
        },
      });
      this.storeCookies(response);
      const text = await response.text();
      return { status: response.status, body: text, url: response.url };
    } finally {
      clearTimeout(timer);
    }
  }

  get(url) {
    return this.request(url);
  }

  post(url, form) {
    return this.request(url, {
      method: 'POST',
      body: new URLSearchParams(form).toString(),
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });
  }
}

function decodeEntities(text) {
  return text
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>').replace(/&amp;/g, '&').replace(/&nbsp;/g, ' ');
}

/** 解析注册页表单：隐藏域 + action + sec */
export function parseForm(body, baseUrl = REGISTER_URL) {
  const hidden = {};
  const formMatch = body.match(/<form\b[^>]*action\s*=\s*["']([^"']+)["'][^>]*>/i);
  let action = formMatch
    ? decodeEntities(formMatch[1]).replace(/&amp;/g, '&')
    : REGISTER_URL;
  if (action.startsWith('//')) action = `https:${action}`;
  else if (action.startsWith('/')) action = new URL(action, baseUrl).toString();
  const inputRe = /<input\b[^>]*>/gi;
  for (const tag of body.match(inputRe) ?? []) {
    const name = tag.match(/name\s*=\s*["']([^"']+)["']/i);
    const value = tag.match(/value\s*=\s*["']([^"']*)["']/i);
    const type = tag.match(/type\s*=\s*["']([^"']+)["']/i);
    if (name && type && type[1].toLowerCase() === 'hidden') {
      hidden[name[1]] = value ? decodeEntities(value[1]) : '';
    }
  }
  const sec = (hidden.sec ?? '1').trim() || '1';
  return { action, hidden, sec };
}

function formUrl(appId, level) {
  const params = new URLSearchParams({
    regMode: 'reg_normal', postLoginHandler: 'refreshParent', displayMode: '',
    bizId: '', redirectUrl: '', css: '', appId, gameId: '', noEmail: 'false',
    regIdcard: 'true', autoLogin: 'false', cid: '', aid: '', ref: '',
    level: String(level), mainDivId: 'popup_reg_div', includeFcmInfo: 'false',
    externalLogin: 'qq', fcmFakeValidate: 'false', expandFcmInput: 'false',
    userNameLabel: '', userNameTip: '', welcomeTip: '',
    v: String(Date.now()),
  });
  return `${REG_FRAME_URL}?${params}`;
}

function parseJsonp(body) {
  const match = body.match(/^[^(]*\((.*)\)\s*;?\s*$/s);
  if (!match) throw new Error('不是 JSONP');
  return JSON.parse(match[1]);
}

/** 组装 unified 路径的提交字段（不含网络） */
export function buildUnifiedPayload({ username, password, realname, idcard, appId = APP_ID, level = 4, form, sendRealname = true }) {
  const payload = {};
  for (const [k, v] of Object.entries(form.hidden)) {
    if (!UNIFIED_DROP_FIELDS.has(k)) payload[k] = v;
  }
  Object.assign(payload, { username, password, passwordveri: password });
  if (sendRealname) {
    payload.realname = realname;
    payload.idcard = idcard;
  } else {
    delete payload.realname;
    delete payload.idcard;
  }
  payload.appId = appId;
  payload.level = String(level);
  payload.regMode = payload.regMode ?? 'reg_normal';
  payload.sec = form.sec || payload.sec || '1';

  const encrypted = [];
  if (payload.sec === '1') {
    for (const name of ['password', 'passwordveri', 'realname', 'idcard']) {
      if (payload[name] !== undefined) {
        payload[name] = encryptAes(payload[name]);
        encrypted.push(name);
      }
    }
  }
  return { payload, encrypted };
}

/** 提交注册（unified / web），返回 {kind, ok, message, ...} */
export async function submitRegistration({
  path = 'unified', username, password, realname, idcard, qq = '',
  appId = APP_ID, level = 4, timeout = 15, dryRun = false, captcha = null,
  captchaAttempts = 3, sendRealname = true,
}) {
  const bad = [...vp(password), ...validateUsername(username)];
  if (!dryRun && bad.length) throw new Error(`参数不合规：${bad.map((v) => v.message).join('；')}`);
  if (!dryRun && (validateRealname(realname).length || validateIdcard(idcard).length)) {
    throw new Error('身份信息不合规');
  }

  const session = new Session({ timeout });
  if (path === 'web') {
    return submitWeb({ session, username, password, realname, idcard, qq, dryRun, captcha, captchaAttempts });
  }
  return submitUnified({ session, username, password, realname, idcard, appId, level, dryRun, captcha, captchaAttempts, sendRealname });
}

async function submitUnified({ session, username, password, realname, idcard, appId, level, dryRun, captcha, captchaAttempts, sendRealname }) {
  const url = formUrl(appId, level);
  const page = await session.get(url);
  if (page.status === 202 || /请稍后再试/.test(page.body)) {
    return {
      kind: 'throttled', ok: false,
      message: `服务端限流（HTTP ${page.status}），请稍后再试`,
      endpoint: REGISTER_URL, fieldNames: [], encrypted: [],
    };
  }
  const form = parseForm(page.body, url);
  if (Object.keys(form.hidden).length === 0) {
    const excerpt = page.body.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 80);
    return {
      kind: 'unknown', ok: false,
      message: `注册页没有隐藏域（HTTP ${page.status}），可能是风控页：${excerpt}`,
      endpoint: url, fieldNames: [], encrypted: [],
    };
  }
  const { payload, encrypted } = buildUnifiedPayload({ username, password, realname, idcard, appId, level, form, sendRealname });
  if (process.env.GEN4399_DEBUG) {
    console.error(`[debug] form hidden=${Object.keys(form.hidden).length} action=${form.action}`);
  }

  if (dryRun) {
    return { kind: 'dry_run', ok: false, dryRun: true, message: 'dry-run：未发送注册 POST', endpoint: form.action, fieldNames: Object.keys(payload), encrypted };
  }

  session.referer = url;
  session.extraHeaders = { Origin: 'https://ptlogin.4399.com', 'Sec-Fetch-Site': 'same-origin' };
  let response = await session.post(form.action, payload);
  let body = response.body;

  for (let round = 0; round < captchaAttempts; round += 1) {
    if (/isAutoRegSuccess\s*=\s*true/i.test(body) || /自动注册成功/.test(body)) {
      return { kind: 'success', ok: true, message: '注册成功（页面返回 isAutoRegSuccess=true）', endpoint: form.action, fieldNames: Object.keys(payload), encrypted };
    }
    if (!/inputCaptcha/.test(body)) break;
    if (!captcha) {
      return { kind: 'captcha', ok: false, message: '服务端要求图形验证码（inputCaptcha）：请传 captcha 回调', endpoint: form.action, fieldNames: Object.keys(payload), encrypted };
    }
    const captchaId = (body.match(/captchaId=([A-Za-z0-9]+)/) ?? [])[1];
    const image = await session.get(`https://ptlogin.4399.com/ptlogin/captcha.do?captchaId=${captchaId}`);
    const code = String(await captcha(Buffer.from(image.body, 'binary')) ?? '').trim();
    if (!code) continue;
    const retry = { ...payload };
    const fields = parseForm(body, form.action);
    Object.assign(retry, fields.hidden);
    retry.inputCaptcha = code;
    retry.sessionId = captchaId ?? retry.sessionId;
    response = await session.post(form.action, retry);
    body = response.body;
  }

  if (/isAutoRegSuccess\s*=\s*true/i.test(body) || /自动注册成功/.test(body)) {
    return { kind: 'success', ok: true, message: '注册成功', endpoint: form.action, fieldNames: Object.keys(payload), encrypted };
  }
  const msg = body.match(/<div\b[^>]*id\s*=\s*["']Msg["'][^>]*>(.*?)<\/div>/is);
  const text = msg ? msg[1].replace(/<[^>]+>/g, '').trim() : '';
  if (response.status === 202 || /请稍后再试/.test(body)) {
    return { kind: 'throttled', ok: false, message: `服务端限流（HTTP ${response.status}）`, endpoint: form.action, fieldNames: Object.keys(payload), encrypted };
  }
  return { kind: text ? 'rejected' : 'unknown', ok: false, message: text || '无法判定注册结果', endpoint: form.action, fieldNames: Object.keys(payload), encrypted };
}

async function submitWeb({ session, username, password, realname, idcard, qq, dryRun, captcha, captchaAttempts }) {
  const checkUrl = `${WEB_CHECK_USER_API}&user=${encodeURIComponent(username)}&jsoncallback=cb`;
  const check = await session.get(checkUrl);
  let encryptCode = '5c43e3';
  try {
    const data = parseJsonp(check.body);
    if (data && data.data) encryptCode = String(data.data);
  } catch {
    /* 解析不了就用默认码，后面服务端会拒绝 */
  }

  const payload = {
    cid: '3000',
    login_name: username,
    login_password: encode4399(password, encryptCode),
    relogin_pwd: encode4399(password, encryptCode),
    qq: qq || '',
    true_name: realname,
    sfz: idcard,
    encrypt: '1',
  };
  const encrypted = ['login_password', 'relogin_pwd'];

  if (dryRun) {
    return { kind: 'dry_run', ok: false, dryRun: true, message: 'dry-run：未发送注册 POST', endpoint: WEB_REG_API, fieldNames: Object.keys(payload), encrypted };
  }

  session.referer = 'https://web.4399.com/user/reg.php';
  let response = await session.post(`${WEB_REG_API}&jsoncallback=cb`, payload);
  for (let round = 0; round < captchaAttempts; round += 1) {
    let data = null;
    try { data = parseJsonp(response.body); } catch { /* ignore */ }
    if (data && data.state) {
      return { kind: 'success', ok: true, message: String(data.msg || '注册成功'), endpoint: WEB_REG_API, fieldNames: Object.keys(payload), encrypted };
    }
    if (!data || data.code !== 200) break;
    if (!captcha) {
      return { kind: 'captcha', ok: false, message: '服务端要求图形验证码（code=200）：请传 captcha 回调', endpoint: WEB_REG_API, fieldNames: Object.keys(payload), encrypted };
    }
    const image = await session.get(WEB_CAPTCHA_API);
    const code = String(await captcha(Buffer.from(image.body, 'binary')) ?? '').trim();
    if (!code) continue;
    response = await session.post(`${WEB_REG_API}&jsoncallback=cb`, { ...payload, chk_code: code });
  }
  let data = null;
  try { data = parseJsonp(response.body); } catch { /* ignore */ }
  if (data && data.state) {
    return { kind: 'success', ok: true, message: String(data.msg || '注册成功'), endpoint: WEB_REG_API, fieldNames: Object.keys(payload), encrypted };
  }
  if (response.status === 202 || /请稍后再试/.test(response.body)) {
    return { kind: 'throttled', ok: false, message: '服务端限流（HTTP 202）', endpoint: WEB_REG_API, fieldNames: Object.keys(payload), encrypted };
  }
  return { kind: data ? 'rejected' : 'unknown', ok: false, message: data ? String(data.msg || '注册失败') : '无法判定注册结果', endpoint: WEB_REG_API, fieldNames: Object.keys(payload), encrypted };
}

/** 登录：账号密码换登录 Cookie */
export async function login(username, password, { appId = APP_ID, timeout = 15 } = {}) {
  const session = new Session({ timeout });
  const response = await session.post(LOGIN_URL, {
    appId, username, password: encryptAes(password), sec: '1',
  });
  const cookies = LOGIN_COOKIE_NAMES.filter((name) => session.cookies.has(name));
  if (cookies.length) {
    return { ok: true, kind: 'success', username, cookies, message: `登录成功（${cookies.length} 个登录 Cookie）` };
  }
  const msg = response.body.match(/<div\b[^>]*id\s*=\s*["']Msg["'][^>]*>(.*?)<\/div>/is);
  const text = msg ? msg[1].replace(/<[^>]+>/g, '').trim() : '';
  if (/验证码/.test(text)) return { ok: false, kind: 'captcha', username, cookies: [], message: text };
  if (text) return { ok: false, kind: 'rejected', username, cookies: [], message: text };
  return { ok: false, kind: 'unknown', username, cookies: [], message: '无法判定登录结果' };
}

