// Node 版自测：node --test
import test from 'node:test';
import assert from 'node:assert/strict';

import { encode4399, encryptAes, decryptAes, PASSPHRASE } from './crypto.mjs';
import * as rules from './rules.mjs';
import * as identity from './identity.mjs';
import { buildUnifiedPayload, parseForm, UNIFIED_DROP_FIELDS } from './client.mjs';

test('encode4399 与 Python 版逐字节一致', () => {
  // 夹具由 gen4399/_des.py 生成
  assert.equal(encode4399('Abc12345', '5c43e3'), '0xfc88a0c93a204a36');
  assert.equal(encode4399('hello world', 'abc'), '0xd22da7b2be6ea575df93303f8204c05a');
  assert.equal(encode4399('P@ss!', '1234567890abcdef'), '0x9b5112a937ab4658');
});

test('AES 加解密往返', () => {
  const cipher = encryptAes('王五的密码123');
  assert.ok(cipher.startsWith('U2FsdGVkX1'), '应为 Salted__ 前缀');
  assert.equal(decryptAes(cipher), '王五的密码123');
  assert.equal(decryptAes(encryptAes('abc', PASSPHRASE)), 'abc');
});

test('每次加密的 salt 不同', () => {
  assert.notEqual(encryptAes('same'), encryptAes('same'));
});

test('密码规则', () => {
  assert.deepEqual(rules.validatePassword('Abc12345'), []);
  assert.deepEqual(rules.validatePassword('abc').map((v) => v.code), ['length', 'all_lower']);
  assert.deepEqual(rules.validatePassword('12345678').map((v) => v.code), ['all_digits']);
  assert.deepEqual(rules.validatePassword('abcdefgh').map((v) => v.code), ['all_lower']);
  assert.deepEqual(rules.validatePassword('ABCDEFGH').map((v) => v.code), ['all_upper']);
  assert.deepEqual(rules.validatePassword('abc123!@').map((v) => v.code), ['charset']);
});

test('用户名规则允许纯数字', () => {
  assert.deepEqual(rules.validateUsername('12345678'), []);
  assert.deepEqual(rules.validateUsername('ab').map((v) => v.code), ['length']);
  assert.deepEqual(rules.validateUsername('abc_12345').map((v) => v.code), ['charset']);
});

test('生成的密码一定合规', () => {
  for (let i = 0; i < 50; i += 1) {
    const password = rules.generatePassword(12);
    assert.equal(password.length, 12);
    assert.deepEqual(rules.validatePassword(password), []);
  }
});

test('生成用户名支持前后缀', () => {
  const name = rules.generateUsername(12, 'ab', '99');
  assert.equal(name.length, 12);
  assert.ok(name.startsWith('ab'));
  assert.ok(name.endsWith('99'));
});

test('身份证校验', () => {
  assert.deepEqual(identity.validateIdcard('110105198803121893'), []);
  assert.deepEqual(identity.validateIdcard('460206194611192084'), []);
  assert.deepEqual(identity.validateIdcard('110105198803121892').map((v) => v.code), ['checksum']);
  assert.deepEqual(identity.validateIdcard('123').map((v) => v.code), ['format']);
  assert.equal(identity.maskIdcard('110105198803121893'), '110105********1893');
});

test('unified 载荷：剔除隐藏域 + 加密 4 个字段', () => {
  const form = {
    action: 'https://ptlogin.4399.com/ptlogin/register.do',
    sec: '1',
    hidden: {
      appId: 'u4399', level: '4', regMode: 'reg_normal', sessionId: 'abc',
      fCaptcha: '', mainDivId: 'popup_reg_div', reg_eula_agree: 'on',
    },
  };
  const { payload, encrypted } = buildUnifiedPayload({
    username: 'user1234', password: 'Abc12345',
    realname: '王五', idcard: '110105198803121893', form,
  });
  assert.equal(UNIFIED_DROP_FIELDS.size, 13);
  for (const dropped of ['fCaptcha', 'mainDivId', 'reg_eula_agree']) {
    assert.ok(!(dropped in payload), `${dropped} 应被剔除`);
  }
  assert.deepEqual(encrypted, ['password', 'passwordveri', 'realname', 'idcard']);
  assert.ok(payload.password.startsWith('U2FsdGVkX1'));
  assert.equal(decryptAes(payload.password), 'Abc12345');
  assert.equal(decryptAes(payload.realname), '王五');
});

test('关掉实名时不带 realname/idcard', () => {
  const form = { action: 'x', sec: '0', hidden: { appId: 'u4399' } };
  const { payload, encrypted } = buildUnifiedPayload({
    username: 'u', password: 'p', realname: 'r', idcard: 'i', form, sendRealname: false,
  });
  assert.ok(!('realname' in payload));
  assert.ok(!('idcard' in payload));
  assert.deepEqual(encrypted, []);
});

test('解析注册页表单', () => {
  const html = `<form id="f" action="/ptlogin/register.do?x=1" method="post">
    <input type="hidden" name="appId" value="u4399" />
    <input type='hidden' name='sec' value='1' />
    <input type="hidden" name="mainDivId" value="popup_reg_div" />
    <input type="text" name="username" value="" />
  </form>`;
  const form = parseForm(html, 'https://ptlogin.4399.com/ptlogin/register.do?v=1');
  assert.equal(form.hidden.appId, 'u4399');
  assert.equal(form.sec, '1');
  assert.equal(form.action, 'https://ptlogin.4399.com/ptlogin/register.do?x=1');
  assert.ok(!('username' in form.hidden));
});
