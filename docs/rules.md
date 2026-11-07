# 4399 注册规则快照与维护

本库的规则来自 4399 前端 `validation.js` 与注册页提示，**不是官方文档**。
4399 可能随时改规则；这里记录快照与复核流程。

## 当前快照

| 项 | 值 |
|---|---|
| `RULES_VERSION` | `4399-2026-11` |
| 核对日期 | 2026-11-07 |
| 来源 | `web.4399.com/user/reg.php`、`u.4399.com/register.html`、`ptlogin.4399.com/ptlogin/regFrame.do` |

## 规则摘要

- 密码：6~20 位，仅 ASCII 字母数字；不能纯数字 / 纯小写 / 纯大写
- 用户名：6~20 位，仅 ASCII 字母数字；允许纯数字
- 真实姓名：2~30 位中文，或英文姓（空格分隔）
- 身份证：18 位，生日合法（1850~2050），GB 11643 校验码正确；4399 拒绝 15 位
- QQ：4~11 位数字（选填）

## 复核流程

```bash
python scripts/verify_rules.py
```

脚本会 GET 上述页面并检查关键字符串（`CheakPWD` / `CheakUsername` / `6~20` /
`字母和数字`）。退出码 0 = 全部命中；1 = 有关键字缺失（规则可能变了）；
2 = 网络错误。

> 只有 GET + 关键词搜索，不提交任何数据。

## 规则变化时怎么改

1. 打开注册页/`validation.js`，确认新规则；
2. 更新 `gen4399/core.py`（密码/用户名常量与 `validate*`）；
3. 更新 `gen4399/identity.py`（姓名/身份证/QQ 校验）；
4. 更新 `gen4399/forms.py`（字段定义）；
5. 更新 `gen4399/_rules.py` 的 `RULES_VERSION` / `RULES_CHECKED_AT`；
6. 补测试并更新本文件。
