#!/usr/bin/env node
// gen4399（Node 版）命令行：生成 / 校验 / 字段 / 提交 / 登录。

import { parseArgs } from 'node:util';
import * as rules from './rules.mjs';
import * as identity from './identity.mjs';
import * as client from './client.mjs';

const HELP = `gen4399 (node) — 4399 注册工具

用法:
  gen4399 generate [-n 16] [-c 1] [--username]
  gen4399 check password <值>
  gen4399 check username <值>
  gen4399 idcard <号码>
  gen4399 fields [web|unified]
  gen4399 submit <用户名> <密码> --realname 姓名 --idcard 号码 [--path unified|web] [--dry-run|--yes]
  gen4399 login <用户名> --password 密码

说明: submit 默认 dry-run，只有加 --yes 才会真正发送注册 POST。
`;

function out(text) { process.stdout.write(text + '\n'); }

function cmdGenerate(args) {
  const { values } = parseArgs({
    args,
    options: {
      length: { type: 'string', short: 'n', default: '16' },
      count: { type: 'string', short: 'c', default: '1' },
      username: { type: 'boolean', default: false },
    },
  });
  const length = Number(values.length);
  const count = Number(values.count);
  for (let i = 0; i < count; i += 1) {
    if (values.username) {
      const name = rules.generateUsername(length);
      out(name);
      if (count === 1) {
        const bad = rules.validateUsername(name);
        out(bad.length ? `  不合规: ${bad.map((v) => v.message).join('；')}` : '  合规：长度/字符集都满足 4399 规则');
      }
    } else {
      const password = rules.generatePassword(length);
      out(password);
      if (count === 1) {
        out(`  熵 ≈ ${rules.entropyBits(length).toFixed(1)} bit`);
      }
    }
  }
  return 0;
}

function cmdCheck(args) {
  const [kind, value] = args;
  if (!kind || value === undefined) { out('用法: check password|username <值>'); return 2; }
  const violations = kind === 'password' ? rules.validatePassword(value) : rules.validateUsername(value);
  if (violations.length === 0) { out(`OK: ${kind} 合规`); return 0; }
  out(`FAIL: ${kind} 有 ${violations.length} 处不合规`);
  for (const v of violations) out(`  [${v.code}] ${v.message}`);
  return 1;
}

function cmdIdcard(args) {
  const value = args[0];
  if (!value) { out('用法: idcard <18 位号码>'); return 2; }
  const violations = identity.validateIdcard(value);
  if (violations.length === 0) { out(`OK: ${identity.maskIdcard(value)} 通过校验`); return 0; }
  out('FAIL:');
  for (const v of violations) out(`  [${v.code}] ${v.message}`);
  return 1;
}

function cmdFields(args) {
  const path = args[0] ?? 'unified';
  if (path === 'web') {
    out('web 字段: cid login_name login_password relogin_pwd qq true_name sfz encrypt');
  } else if (path === 'unified') {
    out('unified 基础字段: appId regMode level username password passwordveri sessionId sec');
    out('unified 实名: realname idcard（AES-256-CBC）');
    out(`unified 剔除字段（${client.UNIFIED_DROP_FIELDS.size} 个）: ${[...client.UNIFIED_DROP_FIELDS].join(' ')}`);
  } else {
    out('用法: fields [web|unified]');
    return 2;
  }
  return 0;
}

async function cmdSubmit(args) {
  const { values, positionals } = parseArgs({
    args,
    allowPositionals: true,
    options: {
      realname: { type: 'string' },
      idcard: { type: 'string' },
      qq: { type: 'string', default: '' },
      path: { type: 'string', default: 'unified' },
      'dry-run': { type: 'boolean', default: false },
      yes: { type: 'boolean', default: false },
      'app-id': { type: 'string', default: client.APP_ID },
      timeout: { type: 'string', default: '15' },
      'verify-code': { type: 'string' },
    },
  });
  const [username, password] = positionals;
  if (!username || !password || !values.realname || !values.idcard) {
    out('用法: submit <用户名> <密码> --realname 姓名 --idcard 号码 [--path unified|web] [--dry-run|--yes]');
    return 2;
  }
  const dryRun = !values.yes || values['dry-run'];
  if (!dryRun) {
    out('# 警告：即将真实提交 4399 注册请求；只应使用本人真实身份，并遵守 4399 用户协议。');
  } else {
    out('# DRY-RUN：未加 --yes，不会真正提交（加 --yes 才发送 POST）');
  }
  const captcha = values['verify-code'] ? async () => values['verify-code'] : null;
  try {
    const result = await client.submitRegistration({
      path: values.path,
      username,
      password,
      realname: values.realname,
      idcard: values.idcard,
      qq: values.qq,
      appId: values['app-id'],
      timeout: Number(values.timeout),
      dryRun,
      captcha,
    });
    out(`结果: ${result.kind}（ok=${result.ok}）`);
    out(`  说明: ${result.message}`);
    if (result.fieldNames) out(`  字段: ${result.fieldNames.length} 个，加密 ${result.encrypted.length} 个`);
    if (result.endpoint) out(`  端点: ${result.endpoint}`);
    return result.ok ? 0 : 1;
  } catch (error) {
    out(`错误：${error.message}`);
    return 2;
  }
}

async function cmdLogin(args) {
  const { values, positionals } = parseArgs({
    args,
    allowPositionals: true,
    options: {
      password: { type: 'string' },
      timeout: { type: 'string', default: '15' },
    },
  });
  const [username] = positionals;
  if (!username || !values.password) { out('用法: login <用户名> --password 密码'); return 2; }
  try {
    const result = await client.login(username, values.password, { timeout: Number(values.timeout) });
    if (result.ok) {
      out(`OK: ${username} 登录成功（${result.cookies.length} 个登录 Cookie）`);
      return 0;
    }
    out(`FAIL[${result.kind}]: ${result.message}`);
    return 1;
  } catch (error) {
    out(`错误：${error.message}`);
    return 2;
  }
}

async function main(argv) {
  const [command, ...rest] = argv;
  switch (command) {
    case undefined:
    case '-h':
    case '--help':
    case 'help':
      out(HELP);
      return 0;
    case 'generate': return cmdGenerate(rest);
    case 'check': return cmdCheck(rest);
    case 'idcard': return cmdIdcard(rest);
    case 'fields': return cmdFields(rest);
    case 'submit': return cmdSubmit(rest);
    case 'login': return cmdLogin(rest);
    default:
      out(`未知命令: ${command}`);
      out(HELP);
      return 2;
  }
}

main(process.argv.slice(2)).then((code) => process.exit(code));
