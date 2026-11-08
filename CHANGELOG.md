# Changelog

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [3.3.0] - 2026-11-08

### 改进

- **web 验证码种子字库扩到 61 个样本**（28 个字符类别、244 个字形），
  留一法字符准确率 **85% → 88%**（单轮整码约 60%，3 轮约 94%）。
- 新增 `benchmark()` / `gen4399 captcha bench DIR`：对已标注目录做留一法评估，
  用来衡量字库质量（`--json` 可机读）。

### 说明

- 3D 实心块字形仍是主要误差源：这类字形的骨架形状与描边字体差异大，
  且人工标注时难以看准，故一直未纳入种子字库。实战中它们会走
  `--captcha-prompt` 分支，并由 `feedback` 逐步补充。

## [3.2.0] - 2026-11-08

### 新增

- **批量注册编排**（`gen4399.batch.run_batch` / CLI `gen4399 batch`）：
  - 每个身份独立 `prepare → submit`，代理/UA 由 `TransportOptions` 隔离
  - 身份之间按 `--interval + --jitter` 随机间隔（默认 30s）
  - `--max-failures N` 连续失败即中止；`--verify-login` 注册后自动登录复核
  - **断点续跑**：账号记录新增 `idcard_hash`，已成功的身份默认跳过
  - 结果继续追加到账号文件（0600），跑一半中断也不丢已建好的号
  - 汇总：总数/成功/失败/按 kind 分组/用时，支持 `--json`
- **web 验证码标注工具**（CLI `gen4399 captcha label` / `captcha solve`）：
  批量标注目录里的样本直接写进字库，`solve` 用来单独试一张。

### 改进

- web 验证码种子字库从 33 个样本扩到 **47 个**，留一法字符准确率
  **80% → 85%**（单轮整码约 52%，3 轮约 89%）。

### 测试

- 新增 `tests/test_batch.py`（10）与 `tests/test_cli_batch_captcha.py`（7）；
  773 passed。

## [3.1.0] - 2026-11-08

### 新增

- **web 验证码自学习识别**（`gen4399.captcha_web` / `--captcha-learn`）：
  - 切字：列投影 + 强制 4 段（3D 块状字形常和相邻字符粘连，按「墨量最少处」切开）
  - 特征：Zhang-Suen 骨架化 → 归一化 24×32 → chamfer 距离最近邻（±1 像素平移增强）
  - 自学习：服务端 `verifyCode` 判定通过后，把 4 个字形连同答案写进字库
    （默认 `~/.gen4399/web_captcha_bank.json`）
  - 随库附带 33 个已标注样本的种子字库（33KB），开箱即用
  - 实测（留一法）：**字符准确率 80%**（26 个样本时是 73%，切字修复后又多救回 7 个样本）

- `--captcha-learn [BANK]` 已接入 CLI 与 `make_account.py`；识别器带
  `feedback(image, code, accepted)`，注册流程在验证码通过时会自动喂样本。

### 说明

- 3D 实心块字形目前在种子里样本偏少，是主要误差来源；标注入更多样本即可提升。
- 拿不准时（最近邻距离过大或前两名差距太小）会退到 `--captcha-prompt` 或给最佳猜测。

## [3.0.0] - 2026-11-08

### 新增

- **`configure()`**（`gen4399.config`）：运行期配置的稳定入口。
  `configure(unified_send_realname=False)` 会让 unified 不再提交姓名/身份证
  （`encrypted_fields` 从 4 个变 2 个）；`current_config()` 读回当前值。
  2.x 的模块属性写法 `gen4399.submit.UNIFIED_SEND_REALNAME = False` 仍然有效。

### 重构（包结构）

- **`gen4399/submit.py` → `gen4399/submit/` 包**：
  - `submit/web.py`：web 路径（DES + JSONP + 验证码重提交）
  - `submit/unified.py`：unified 路径（AES + 表单页 + 验证码重提交）
  - `submit/_common.py`：账号复核、登录 Cookie 名、JSONP 回调、参数校验
  - `submit/__init__.py`：常量、`_build_payload`（保留 `UNIFIED_SEND_REALNAME`
    这个模块级开关，因为测试与文档都靠它）、`submit_registration` 编排、对外再导出

  对外名字全部保留：`gen4399.submit.submit_registration` / `SubmitResult` /
  `UNIFIED_DROP_FIELDS` / `_submit_web` / `_http` 等旧引用照常工作；
  只有私有符号的实际定义位置变了（`_verify_account` → `submit._common.verify_account`）。

### 测试

- 新增 `tests/test_config.py`（5 例，含「开关真的改变加密字段数」的端到端断言）；
  737 passed，覆盖率维持 ~95%。

## [2.10.0] - 2026-11-08

### 新增

- **登录能力**（`gen4399.login`）：`login(username, password)` 走
  `POST /ptlogin/login.do?v=1`，body 只发 `appId/username/password(AES)/sec=1`，
  成功时拿回 `Pauth/Uauth/Xauth/...` 一组登录 Cookie；失败返回
  `LoginResult(kind="rejected", message="密码错误")`。CLI 加了
  `gen4399 login <账号> [--password]`（不给密码则交互输入、不回显）。
- `make_account.py --verify-login`：注册成功后立刻登录一次，确认「号真的能用」，
  结果写进 `--json` 输出的 `login` 字段。
- **限流自动退避**：`submit_registration(..., throttle_retries=1, throttle_backoff=20)`
  遇到 `kind="throttled"`（服务端 202 +「请稍后再试」）会自动等待重试，指数退避
  （20s → 40s …）；这类响应确定没建号，重试是安全的。传 `throttle_retries=0` 关闭。
- **代理健康检查**：`TransportOptions(verify_proxy=True)` / CLI `--proxy-check`，
  建会话前先 GET 探活 `https://www.4399.com/`，坏代理自动换下一个；
  代理池全不可用时抛 `ProxyError`。

### 实测

- `login("vjjglf4d7jv1", ...)` → `success`，8 个登录 Cookie；
  错密码 → `rejected`「密码错误」。
- `make_account.py --verify-login` 一次跑通：注册账号 `h6hm1cihpviu` 后登录复核 OK。

## [2.9.0] - 2026-11-08

### 变更（公共 API 收敛）

- **顶层 `__all__` 收敛到核心 34 个**（生成/校验、身份、编排、提交、远程、传输、
  `__version__`）。其余名字仍然可以 `from gen4399 import X` 显式导入（2.x 完全兼容），
  但不再出现在 `from gen4399 import *` 里，也不再作为公共契约承诺。
  按域导入请走 `gen4399.forms / identity / remote / submit / captcha / constants /
  transport / proxy / ua`。
- `fetch_suggested_username()` 的重试现在**复用同一个会话**（同一个代理 / Cookie），
  不再每次重试都新建连接、换出口 IP。

### 测试

- 新增顶层 API 契约测试（`__all__` 可解析、无重复、`import *` 与之一致、
  高级名字仍可显式导入）；695 passed。

## [2.8.0] - 2026-11-08

### 新增

- **粘性代理**：`TransportOptions(sticky=True)` / `--proxy-sticky`。默认每次
  `new_session()` 轮换代理，导致「查重」和「提交」落在两个 IP；打开 sticky 后
  整个注册流程固定用一个代理，`reset_sticky()` 可手动换。
- **`gen4399.account`**：`account_record()` / `append_account()` / `load_accounts()`，
  把「跑一次拿一个号」的落盘逻辑从 `scripts/make_account.py` 提到库里（原子写入、
  0600、损坏文件容错），脚本因此减到 395 行。
- `SubmitResult.proxy`：记录本次实际使用的代理（**已打码**，`http://***@host:port`），
  `to_dict()` 同步输出，便于排查「哪个 IP 被风控」。
- 验证码连续失败时，消息里会提示「识别模板可能已过期，改用人工/外部 OCR」。

### 修复

- `ProxyPool.next()` 加锁，多线程轮换不再跳号/重复。
- `fetch_suggested_usernames(with_availability=True)` 复用同一个会话（同一个代理），
  不再每个名字换一次 IP。

### 重构（内部）

- `submit.py` 1183 → 857 行：结果类型与文本工具拆到 `_submit_types.py`，
  分类器拆到 `_submit_classify.py`；`gen4399.submit` 保持全部旧名字可用
  （含 `UNIFIED_SEND_REALNAME` 这个运行期开关，测试与文档口径不变）。
- README 914 → 837 行：协议细节统一指向 `docs/submit.md`，FAQ 挪到 `docs/faq.md`。

### 测试

- 690 passed（新增 account / sticky / 线程安全 / mask_proxy 等 11 例）。

## [2.7.0] - 2026-11-08

### 新增

- **代理池**（`gen4399.proxy.ProxyPool`）：一行一个代理，支持 `#` 注释、
  `host:port` 自动补 `http://`、`round-robin` / `random` 两种轮换策略。
  用于规避 4399 的单 IP 注册频率限制（实测同 IP 连续注册会进入 202 风控）。
- **随机 User-Agent**（`gen4399.ua.random_user_agent()`）：按 Chrome / Edge /
  Firefox / Safari × Windows / macOS / Linux 的真实格式生成，不含 `Headless`
  等爬虫标记，版本号落在近两年稳定区间。
- **`TransportOptions`**（`gen4399.transport`）：把「超时 / 代理 / 代理池 /
  随机 UA / 重试策略」打包成一个参数，传给
  `submit_registration(..., transport=...)`、`prepare_registration(...)`、
  `check_username(...)` 即可，不必改一堆签名。
- CLI / `make_account.py` 新增 `--proxy URL`、`--proxy-file FILE`、
  `--proxy-strategy {round-robin,random}`、`--random-ua`。

- `gen4399.transport.build_transport(...)`：把「代理 URL / 代理文件 / 策略 / 随机 UA」
  拼成 `TransportOptions`，CLI 与 `make_account.py` 共用同一份实现。
- **代理不再漏在最关键的几步**：`prepare_registration()` / `generate_available_username()`
  / `fetch_suggested_username(s)` 现在都接受并透传 `transport`，查重与提交走同一个代理，
  不会出现「提交走代理、查重裸奔」的情况。
- `submit_registration()` 会校验 `transport` 类型（传错直接 `TypeError`）。

### 说明

- 只支持 HTTP(S) 代理；SOCKS 需要额外依赖，未纳入（保持零运行时依赖）。
- 代理会把 PII 交给第三方（AES 口令公开，等同明文），见 SECURITY.md。
- 代理只影响 lib 自己发起的请求；`--proxy` 与 `--proxy-file` 同时给时以池为准
  （`TransportOptions` 会直接拒绝两者同时出现，CLI 里池优先）。

### 实测

- `make_account.py --form-path unified --random-ua --captcha-matcher`：
  随机 UA + 内置识别器一次通过，账号 `vjjglf4d7jv1`。

## [2.6.0] - 2026-11-08

### 新增

- **内置验证码识别器**（`matcher_captcha_solver()` / `--captcha-matcher`）：移植
  [guiwow1337/4399-captcha](https://github.com/guiwow1337/4399-captcha)（MIT）的
  `matcher.c`，专解 4399 的 60×30 四位验证码。alg：灰度 `<170` 二值化 →
  25 个手扣字形模板在 4 个槽位窗口内滑动（允许滑出图外）→ 「溢出最少」判据。
  模板数据 vendored 在 `gen4399/_captcha_templates.py`。纯标准库实现，
  解码用本机 ImageMagick（`magick`/`convert`），单张约 0.3 s。
- `auto_captcha_solver()` 现在按 **内置识别器 → 外部 OCR（tesseract）→ 人工输入**
  的顺序回退。
- CLI / `make_account.py` 新增 `--captcha-matcher`。

### 修复（协议，关键）

- **unified 验证码字段名**：服务端重渲染的验证码页里同时有 `inputCaptcha`（可见
  输入框）和 `fCaptcha`（手机验证码弹窗模板），**校验的是 `inputCaptcha`**。
  之前只发 `fCaptcha`，所以永远是「验证码错误」。
- 重提交时用页面 hidden 里的 `sessionId`（即本次 captchaId）覆盖旧值。

### 实测

- unified 图形验证码全链路跑通：`注册成功（第 1 轮图形验证码后通过）`，
  账号 `15iekvk41am5`，`verified=True`。

## [2.5.0] - 2026-11-08

### 新增

- **注册后自动复核**：`submit_registration(..., verify=True)`（默认开）在成功后会
  用同一会话（带 `Pauth` 等 Cookie）GET `https://u.4399.com/`，页面里出现用户名
  即 `SubmitResult.verified=True`；明确落到未登录页返回 `False`；网络失败/页面结构
  不符返回 `None`（不下结论）。复核是尽力而为，任何异常都不会影响提交结果。
- **限流识别**：服务端返回 `202` + 「请稍后再试~」时，`SubmitResult.kind="throttled"`
  （`ok=False`），message 提示等几分钟再试、批量时用 `--min-interval`。这种响应
  可以确定**没有建号**，因此 `make_account.py` 不会写 `accounts.json`。
- **`auto_captcha_solver()` / `--captcha-auto`**：自动挑识别方式——本机装了
  `tesseract` 就用它（PNG 走 stdin、结果走 stdout），否则退回人工输入；
  `--captcha-cmd` 仍可指定任意识别命令。库依旧不内置验证码破解。

### 新增（API 分层）

- `gen4399.identity.load_profiles_auto()`：UTF-8-SIG → GB18030 自动回退读身份文件
  （CLI 与 `scripts/make_account.py` 原先各写一遍，现共用）。

- 新增 `gen4399.constants`：规则版本、长度限制、端点 URL、`UNIFIED_DROP_FIELDS` /
  `UNIFIED_SEND_REALNAME` / `ENCRYPTED_FIELDS` 等常量的**完整**出口（顶层保持兼容）。
- 新增 `gen4399.captcha`：`CaptchaSolver` / `CaptchaSolverError` / `prompt|command|auto_captcha_solver`
  / `save_captcha_images` / `make_solver` 的公开别名（实现仍在 `_captcha`）。
- `gen4399.forms` / `identity` / `remote` / `submit` 本就是模块，README 新增「API 分层」
  一节说明「核心三个名字 + 按域取细节」。
- 顶层补导出 `WEB_CHECK_USER_API`。

### 修复（协议对齐）

- **表单 POST 的 `Content-Type` 改为浏览器同款**：`application/x-www-form-urlencoded`
  （不再带 `; charset=UTF-8`）。
- **unified 的 POST 补齐浏览器头**：`Referer` 改为 regFrame 自身，并带
  `Origin: https://ptlogin.4399.com` 与 `Sec-Fetch-*`（新增
  `RemoteSession.extra_headers`）。
- 说明：这两项是按「与浏览器逐字对齐」做的纠正，**并不解决 `202` 伪限流**——
  受控实验（同参数 6 连发）显示 `202` 是间歇性的（5 次验证码页 / 1 次 202），
  换 charset 与换 GET 头都不改变比例。`kind="throttled"` 仍按限流处理。

### 重构（内部，无 API 变化）

- 提交层：4 处 `SubmitResult(...)` 组装合并成 `_dry_run_result()` / `_final_result()`
  两个工厂，登录 Cookie 计算抽成 `_present_login_cookies()`；以后加字段不会再漏改。
- `CaptchaSolver` 只在 `gen4399._captcha` 定义一次，`submit` 侧改为导入别名。
- CLI：legacy 解析器改用 `_add_captcha_opts()` / `_add_remote_opts()` / `_add_io_opts()`，
  与子命令解析器共享同一份选项定义（少 20 行重复）。
- `SubmitResult.__repr__` 补 `captcha_attempts` / `verified`；web 路径 Referer 改为
  `https://web.4399.com/user/reg.php`（与浏览器一致）。

### 新增（人工识别更可用）

- `prompt_captcha_solver(zoom=N)` / CLI `--captcha-zoom N`：落盘前用本机
  ImageMagick 把验证码放大（灰度 + Lanczos）。4399 的 unified 验证码只有 60×30，
  放大 6~8 倍后人才看得清；没有 ImageMagick 时自动退回原图（不报错）。

### 变更

- `SubmitResult` 增加 `verified` 字段（`to_dict()` 同步输出）。
- `SubmitKind` 增加 `throttled`；CLI 遇到限流会在结果下多打一行重试提示。
- `gen4399._captcha.make_solver()` 增加 `auto=` 参数，优先级
  `command > auto > prompt`。
- `__version__ = "2.5.0"`。

## [2.4.0] - 2026-11-08

### 新增

- **unified 路径图形验证码**（`fCaptcha`）：服务端风控把 `register.do` 的响应重渲染成
  带验证码的表单时（`<div id="Msg">验证码错误`、`inputCaptcha`、
  `captcha.do?captchaId=…`），`submit_registration(..., captcha=...)` 会自动
  「取图 → 识别 → 带 `fCaptcha` 重提交」，最多 `captcha_attempts` 轮；
  识别结果写入 `SubmitResult.captcha_attempts`。未传回调时返回 `kind="captcha"`
  并提示传 `captcha=`。重提交会用响应页表单的新隐藏域做基线，密码密文沿用首次 payload。

### 修复

- **unified 路径空白「4399提示」页**：把 `regFrame.do` 的隐藏域原样回传时，
  `POST /ptlogin/register.do` 会稳定返回 `info_page` 空壳（无 `<div id="Msg">`、
  无登录 Cookie，注册不发生）——**根因是这些字段，不是风控封 IP**。
  新增 `gen4399.submit.UNIFIED_DROP_FIELDS`（`frozenset`，13 个字段）并在
  `_build_payload()` 中剔除；同一套数据可正常建号，实际提交 23 个字段（含实名）。
- **unified 成功页回显明文密码**：成功页可见文本含「…用户名：… 密码：…」，
  `_redact_text()` 在解析前把密码/身份证/姓名替换为 `***`，不会进入
  `SubmitResult.message` / `to_dict()` / CLI/JSON 输出。
- 登录 Cookie 名单补 `Qnick`、`ptusertype`（`SubmitResult.login_cookies` 可见）。

### 新增

- `gen4399.submit.UNIFIED_DROP_FIELDS`（`frozenset`，可导入）：unified 必须从
  hidden 基线中剔除的 13 个字段——布局/防沉迷/前端开关 9 个
  （`crossDomainUrl`、`mainDivId`、`showRegInfo`、`includeFcmInfo`、`expandFcmInput`、
  `fcmFakeValidate`、`realnameValidate`、`userNameLabel`、`iframeId`）+ 协议开关 4 个
  （`email`、`reg_eula_agree`、`autoLogin`、`fCaptcha`）。**`realname`/`idcard` 不在其中**：
  它们作为本库显式写入的字段参与提交。
- `gen4399.submit.UNIFIED_SEND_REALNAME`（默认 `True`）：默认**一起提交实名信息**，
  `realname`/`idcard` 与密码同样 AES 加密；设为 `False` 则只发用户名/密码。
  运行期修改需改模块属性（`gen4399.submit.UNIFIED_SEND_REALNAME = False`）。
- 实测记录（2026-11-08）：unified 两种形态都建号成功——含实名 `abnsm4uw2s77`
  （23 字段 / 4 个 AES 字段）、不含实名 `abkeq7xvesft`（21 字段 / 2 个 AES 字段）。
  成功页约 4 KB，`msnger.emit("isAutoRegSuccess",true)`，下发
  `Pauth`/`Uauth`/`Xauth`/`Puser`/`Pnick`/`Qnick`/`ck_accname`/`ptusertype`。

### 变更（可能影响调用方）

- unified 默认提交 23 个字段；`encrypted_fields == ("password", "passwordveri",
  "realname", "idcard")`，`field_names` 为 23 个。
- unified 默认不再发送 `email`/`reg_eula_agree`/`autoLogin`/`fCaptcha` 及 9 个布局类
  hidden（这些与实名一起回传会触发空白提示页）；`realname`/`idcard` **会发送**并 AES 加密。
  想建「不实名」账号时把 `UNIFIED_SEND_REALNAME` 设为 `False`。
- `__version__ = "2.4.0"`；仍为**零运行时依赖**。

### 文档

- README、`docs/submit.md`、`docs/rules.md`、`docs/project-overview.md`、SECURITY.md
  全面改写 unified 结论：从「空白风控页不可用」改为「剔除 13 个隐藏域后已实测建号」；
  补充字段清单（23 个/13 个）、`UNIFIED_SEND_REALNAME` 默认提交实名、脱敏成功页样本、
  两条路径均已实测的成功判定。
- 收敛「同一身份证只能注册一个账号」的断言：实测是已绑定身份证再次注册被拒
  （`msg="姓名身份证不匹配"`），该文案无法区分「已绑定」与「实名不通过」。

### 安全

- **unified 默认提交实名信息**（`UNIFIED_SEND_REALNAME=True`）：姓名/身份证与密码一起
  AES-256-CBC 加密（4 个字段），传输走 HTTPS；不想上传时把开关设为 `False`。
- `unified` 成功页会回显明文密码，库在解析前替换为 `***`；结果对象/日志/JSON 不含明文。
- 图形验证码仍只按协议交给调用方识别，本库不内置破解；注册 POST 仍单次不重试。

## [2.3.0] - 2026-11-08

### 新增

- **web 路径图形验证码流程**（`web.4399.com` 用户中心，实测建号成功）：
  - 首次 `POST /user/?_c=reg` 返回 `{"state":false,"code":200,"msg":"注册异常，需校验验证码"}`
    时，按协议继续：`GET /util/?_c=code&t=reg` 取 `image/png`（绑定 `WEBSESSION`）→
    调调用方识别 → `GET /user/?_c=reg&_a=verifyCode&code=<code>`
    （`{"state":true}` 通过）→ `POST /user/?_c=reg` 额外带 `chk_code=<code>` 重提交。
  - 成功响应：`{"state":true,"code":300,"msg":"","validateState":"2","toUrl":"/hall.html"}`，
    并下发 `Puser`/`Pauth`/`Pauths`/`Pnick`/`ck_accname` 登录 Cookie。
  - `submit_registration()` 新增 `captcha: Callable[[bytes], str] | None = None`
    （入参为验证码 PNG 原始字节）与 `captcha_attempts: int = 3`（必须 >= 1，
    每轮重新取图）；**库不内置验证码破解/OCR**，识别由调用方实现。
  - `SubmitResult` 新增 `captcha_attempts`（实际轮次，`to_dict()` 同步输出）。
  - 新增顶层常量 `WEB_CAPTCHA_API`、`WEB_VERIFY_CODE_API`（`WEB_REG_API` 一并导出）。
  - 新增 `gen4399/_captcha.py`：`prompt_captcha_solver()`（保存图片 + 人工输入）、
    `command_captcha_solver()`（PNG 走 stdin、结果走 stdout 的外部命令）、
    `save_captcha_images()`（识别前落盘）、`make_solver()`、`CaptchaSolverError`
    （命令超时/非 0 退出）。纯标准库，不新增运行时依赖。
  - CLI `gen4399 submit`、legacy `--submit` 与 `scripts/make_account.py` 新增
    `--captcha-prompt` / `--captcha-cmd CMD` / `--captcha-dir DIR` / `--captcha-attempts N`；
    `--captcha-dir` 单独使用不会识别（只配合前两者落盘）。
    不传验证码参数时，web 遇到 `code=200` 直接以 `kind="captcha"` 结束（退出码 1）；
    外部识别命令失败退出码 2；成功输出多一行「验证码轮次: N」。
- `gen4399 submit` 子命令新增 `--show-pii`：注册成功后在终端打印刚生成的密码
  （默认不打印；`--json` 仍脱敏），避免「号建好了但没记下密码」。
- 实测记录（2026-11-08）：web 路径完整走通图形验证码并**真实创建账号成功**；
  `SubmitResult.captcha_attempts` 为真实轮次。

### 修复

- `HttpResponse` 新增 `raw: bytes`（响应体原始字节）与 `is_binary` 属性：
  图形验证码是 `image/png`，此前只能拿到 UTF-8 解码后的 `body`，二进制内容会被替换成
  `U+FFFD`，无法交给 OCR。图片类响应现在用 `response.raw`。
- 健壮性：识别回调返回空串时跳过 `verifyCode`、直接换图重试（不把空验证码发去校验）；
  该轮仍计入 `captcha_attempts`。

### 文档

- README 与 `docs/submit.md` 重写 web 路径章节：4 步验证码协议、字段表补 `chk_code`、
  `verifyCode` 语义、`code=200`（图形验证码）与 `code=360`（手机验证码）区分、
  脱敏实测样本、CLI/API 用法、`CaptchaSolverError` 与退出码。
- 更新实测状态表述：「web 成功响应未实测」改为「web 已实测建号成功（2026-11-08）」；
  `unified` 仍未实测，并新增已知限制：`POST register.do` 实测返回空白「4399提示」
  `info_page`（无 `#Msg`、无登录 Cookie，`oauthValidation.js` / `fingerprint2` 风控页），
  纯 HTTP 无法判定结果（归 `unknown`）。
- 明确写出：图形验证码必须由调用方提供识别回调，库不内置破解；
  已用于实名绑定的身份证再次注册会被服务端拒绝（实测 `msg="姓名身份证不匹配"`，
  `kind="rejected"`；该文案无法区分「已绑定」与「实名不通过」，不据此断言一证一号）。
- `docs/rules.md` 与 `docs/project-overview.md` 同步 2.3.0 增量。

### 变更（可能影响调用方）

- `__version__ = "2.3.0"`；仍为**零运行时依赖**（验证码辅助模块只用标准库）。
- `SubmitResult` 新增字段 `captcha_attempts`（默认 `0`），位置在 `elapsed` 前；
  用位置参数构造 `SubmitResult` 的调用方需注意。
- `HttpResponse` 新增字段 `raw`（默认 `b""`）与只读属性 `is_binary`。
- CLI `submit` 的成功输出新增一行「验证码轮次: N」（`captcha_attempts > 0` 时）。

### 安全

- 验证码识别回调完全由调用方提供（人工/外部 OCR），本库**不内置破解、不绕过风控**；
  `--captcha-cmd` 经 `shell=True` 执行，命令串需自行保证可信。
- `--captcha-prompt` / `--captcha-dir` 会把验证码图片写到磁盘（0600），注意清理。
- 仅限本人真实身份（已绑定过 4399 的身份证再次注册会被拒）；注册 POST 仍**单次不重试**，
  验证码重提交只在 `verifyCode` 通过后发生，最多 `captcha_attempts` 轮。

## [2.2.0] - 2026-11-07

### 新增

- **web 路径真实提交**（`https://web.4399.com/user/reg.php`）：
  - `submit_registration()` 现在接受 `bundle.path in {"web", "unified"}`。
    web 流程：`GET user/?_c=login&_a=checkUser` 取 `encryptCode`（JSONP）→
    页面同款 `encode_4399()` 加密 `login_password` / `relogin_pwd` →
    `POST user/?_c=reg`（JSONP 响应）→ 按 `{state, code, msg, validateState}`
    判定（`state=true` → success；`code=200/360` → captcha；`msg` → rejected）。
  - 新增 `gen4399/_des.py`：纯标准库 DES/3DES-EDE-ECB + `encode_4399()`
    （`encodeURIComponent` + NUL 零填充 + `"0x"` hex），与站点 `action.js`
    的真实 JS 向量（node 提取）及 pycryptodome 交叉验证；不新增运行时依赖。
  - CLI `gen4399 submit --form-path web|unified`（默认 unified）；
    legacy `--submit` 默认走 web（2.1.0 时 web 会报错）。
  - 新增 `tests/test_des.py`；`tests/test_submit.py` / `tests/test_cli.py`
    增加 web 路径的 payload、DES 加密、JSONP 判定、退出码覆盖。
  - 新增 `scripts/make_account.py`：每次运行读取身份 → 准备 → 提交并追加保存
    账号到 `accounts.json`（默认 dry-run，`--yes` 才真实提交；单次运行只处理一个身份）。
    身份文件中的无效行默认跳过并打印行号（`--strict` 遇错即停），`--index N`
    选择第 N 条有效身份；编码自动 UTF-8-SIG → GB18030 回退。
  - 新增诊断能力：`submit_registration(..., on_response=...)` 回调；脚本
    `--diagnose` 保存 4399 注册响应（status/URL/可见文本/常见原因 + 脱敏 HTML，
    0600），并识别 4399「4399提示」风控/JS 验证页（oauthValidation/fingerprint2）。
    不改变提交/判定行为，不绕过验证码/风控。
- 文档：`docs/submit.md` 增加 web 协议/字段/DES/判定/PII 对比章节；
  README、`docs/rules.md`、`docs/project-overview.md`、SECURITY 同步。

### 变更

- `SubmitResult.path` 现在为 `web` / `unified`；web 的 `app_id` 返回空串（不适用），
  `app_id` / `level` 参数仅 unified 使用。
- `SubmitResult.encrypted_fields`：web 为 `login_password`/`relogin_pwd`（DES），
  unified 仍为 4 个字段（AES）。
- **web 路径的 PII 处理弱于 unified**：只有密码用 DES；`true_name`/`sfz` 是明文
  放在 HTTPS POST body（浏览器原流程是 JSONP GET 放 query，本库改用 POST body
  降低 URL 日志泄露风险）。
- 两条路径的注册 POST 均**单次不重试**；`retry_policy` 只作用于 GET。
- dry-run 均只 GET：unified 拉 `regFrame.do`，web 取 `encryptCode`（只带用户名）。
- **CLI 默认身份文件**：未指定任何身份来源（无 `--profile-file`，也无
  `--realname/--idcard/--qq`）时，自动读取当前目录下的 `sfz.txt`；文件不存在则
  退出码 2 并提示。`gen4399 profile check --profile-file` 改为可选（默认同上）。
  身份文件编码默认 UTF-8-SIG，解码失败自动回退 GB18030（兼容 GBK），可用
  `--profile-encoding` 覆盖；`sfz.txt` / `accounts.json` 加入 `.gitignore`。
- `__version__ = "2.2.0"`；仍为**零运行时依赖**（AES/DES 均为纯标准库实现）。

### 安全

- web dry-run 不发送姓名/身份证；真实提交才发送，且仅发往 4399 官方端点。
- 成功判定仍是启发式：web 的 `state=true` 成功响应**未实测**（只实测了
  非法用户名被拒 `state=false, code=100`），请以登录 `https://u.4399.com/` 为准。

## [2.1.0] - 2026-11-07

### 新增

- **真实 POST 提交（仅 `unified` 路径）**：
  - `submit_registration(bundle, *, app_id="u4399", level=4, timeout=10.0,
    dry_run=False, retry_policy=None)` → `SubmitResult`
    （`kind` = `success` / `rejected` / `captcha` / `unknown` / `dry_run`）；
    `SubmitError` 表示参数/路径不合法。CLI 侧默认 dry-run。
  - CLI 新增 `submit` 子命令：`gen4399 submit --realname … --idcard …`
    默认 dry-run，加 `--yes` 才真实提交；支持 `--form-path unified`（默认）、
    `--app-id`、`--level`、`--json`、`--output`；legacy 模式新增
    `--submit` / `--yes` / `--app-id` / `--level`。退出码 0/1/2。
  - 提交流程：GET `regFrame.do`（会话 Cookie + 表单 hidden 域）→ 解析
    `<form action>` / `sec` → `sec=1` 时 AES 加密
    `password` / `passwordveri` / `realname` / `idcard` → POST `register.do` →
    解析 `<div id="Msg">` / `isAutoRegSuccess` / 登录 Cookie / 跳转。
  - `gen4399/_aes.py`：CryptoJS 兼容的 AES-256-CBC
    （`EVP_BytesToKey(MD5, 8B salt)` + PKCS#7 + `Salted__` 格式），
    **纯标准库**实现；附 `decrypt_aes()` 用于互操作验证。
  - `gen4399/remote/_http.py`：`RemoteSession`（CookieJar 会话；GET 可重试、
    POST 单次）、`HttpResponse`、`RegFormSnapshot`、`parse_registration_form()`。
  - `gen4399/__init__.py` 导出 `submit_registration` / `SubmitResult` / `SubmitError`；
    新增 `docs/submit.md`（协议、字段、AES、判定规则、未验证项）。
  - `RegistrationBundle.as_text()` 尾注改为「手动填表；或用 submit 提交（需 --yes）」。

### 变更（可能影响调用方）

- **库不会自动提交**：`prepare_registration()` 仍只准备数据；真实提交必须显式
  调用 `submit_registration()`（API 默认 `dry_run=False`，调用即提交；CLI 默认
  dry-run，必须加 `--yes`）。
- **（2.1.0 行为）只支持 `unified`**：`bundle.path == "web"` 提交抛 `SubmitError`
  （2.2.0 起 web 路径已支持，见上）。
- **POST 不自动重试**（超时 / 5xx / 429 直接抛错），避免服务端已建号却重复提交；
  `retry_policy` 只作用于 GET 注册表单。
- `SubmitResult` 的 `repr()` / `to_dict()` 已脱敏：不含明文密码/身份证/Cookie 值，
  `final_url` 去掉 query/fragment。
- **不新增运行时依赖**：AES 由 `_aes.py` 用标准库自实现。

### 安全

- 库不会自动提交（CLI 默认 dry-run）；dry-run 只 GET 表单（不发 POST、不发送 PII）。
- 真实提交的 PII 只发往 4399 官方端点 `ptlogin.4399.com`；`sec=1` 时先 AES 加密，
  但该口令公开在前端 JS 中，**不提供机密性保护**。
- 仅限本人真实身份、遵守 4399 用户协议、禁止批量注册他人账号
  （CLI 多身份时在 stderr 警告）。
- **成功判定为推断**：4399 `register.do` 的成功响应未经实测（研究过程未创建真实账号），
  `success` 为启发式判定；请以登录 `https://u.4399.com/` 为准。
- 不绕过验证码/风控；`captcha` 时需人工处理。

## [2.0.0] - 2026-11-07

### 新增

- **2.0 子命令 CLI**：`generate` / `check` / `account` / `fetch` / `available` /
  `form` / `prepare` / `profile check` / `rules` / `version`；旧 flag 模式保留兼容。
- 全局增强：`--json`、`--offline`、`--output DIR`（0600 文件）、
  `--password-length`、`--retries` / `--retry-delay` / `--max-total-timeout`、
  `--min-interval`、`-v/--verbose`。
- `RetryPolicy`：指数退避 + 抖动 + 单次封顶 + 总 deadline + 优先 `Retry-After`；
  远程错误对象带 `url` / `status` / `retry_after`。
- `check_username(validate_input=True)` 本地预校验，明显非法名称不再发请求。
- `fetch_suggested_usernames(with_availability=True)` 返回可用性对象。
- `Account.to_dict()/save()`、`RegistrationBundle.to_dict()/save()`；
  落盘默认 0600 且打码。
- `generate*` / `generate_username*` 支持 `charset=` 自定义字符集。
- 身份文件增强：stdin（`--profile-file -`）、表头自动跳过、默认去重、
  `errors="skip"`、权限过宽警告、行号错误。
- `--rules-version` + `gen4399/_rules.py` + `scripts/verify_rules.py` 规则冒烟检查。
- `docs/rules.md`、`SECURITY.md`、`CONTRIBUTING.md`、`.pre-commit-config.yaml`、
  property-based 测试（hypothesis，可选）。
- `validate_fixed_part` 成为公开主名（`check_fixed_part` 保留别名）。
- `gen4399/identity.py` 从 `forms.py` 拆出（身份对象/字段校验/txt 读取）；
  `gen4399/remote.py` 拆成 `remote/_http.py`（传输/重试）+ `remote/_api.py`（业务）。

### 变更（可能影响调用方）

- **Python 最低版本 3.10**（3.8/3.9 已 EOL）。
- CLI 的 `-n` 继续兼容旧语义，但推荐改用 `--password-length` / `--username-length`。
- CLI `--show-pii` 会额外打印明文警告。
- 远程默认重试策略改为 `RetryPolicy`（fetch 外层 4 次、HTTP 层 2 次、带总超时能力）。
- 身份文件默认按身份证去重（可用 `dedupe=False` 关闭）。
- 测试/覆盖率门槛 90%；CI 增加 mypy（观察项）与 build/twine 检查。

## [1.10.0] - 2026-11-07

### 新增

- `load_profiles(path)`：从 txt 批量读取身份信息，返回逐行校验过的
  `RegistrationProfile` 列表；支持空行 / `#` 注释 / UTF-8 BOM / 全角竖线 `｜`。
- `parse_profile_line(line)`：解析单行身份信息，
  格式 `真实姓名|身份证号[|QQ]`（2~3 列）。
- CLI 新增 `--profile-file FILE`：`--prepare` / `--build-form` / `--check-form`
  均可用，且支持**多行批量**（每个身份输出一段，带 `# 身份 i/n` 标号）。
- 身份文件任一行不合法时整体报错，错误信息带行号；文件不存在/不可读时
  统一退出码 2，不再出现 traceback。

### 变更

- `--profile-file` 与 `--realname/--idcard` 互斥（同时使用会报错退出码 2）。

## [1.9.0] - 2026-11-07

### 修复

- `check_username()` 不再把空响应 / HTML 错误页静默当成"用户名已被注册"：
  无法识别的响应现在抛 `RemoteParseError`。
- `UsernameAvailability` 新增 `kind` 字段，区分为
  `available` / `taken` / `invalid` / `unknown`。
- `_parse_suggested_username()` 不再依赖属性顺序与引号样式
  （`value` 写在 `id` 前、单引号、跨行属性都能正确解析），
  改为“先定位整个 `<input>` 标签、再取 `value` 属性”的实现。
- `fetch_suggested_usernames(unique=True)` 现在会凑满请求数量；
  凑不满时抛 `RemoteError`，不再静默少返回。
- `generate_account()` 对显式传入的 `username` 增加本地规则校验
  （即使 `verify_username=False`），不再返回非法用户名。
- `validate_qq()` 先 `strip()`，修复尾部 `\n` 能混过校验的问题。
- CLI `--fetch-username` 补齐异常兜底：非法 `count` / 前后缀不再抛 traceback，
  统一返回退出码 2。
- CLI `--entropy` 现在与 `generate` 一致地校验 6~20 长度范围。

### 新增

- `generate_many()` / `generate_usernames()` 新增 `unique=True` 选项，
  保证批量结果互不相同。
- `check_fixed_part()` 成为公开 API（`_check_fixed_part` 保留为兼容别名）。
- CLI 新增 `--timeout SECONDS`。
- `Account` / `RegistrationBundle` 的 `repr()` 会打码密码（和身份证号），
  可安全写日志；`Account.masked()` 返回打码副本。
- `RegistrationBundle.fields` 改为只读 `MappingProxyType`；
  `masked_fields()` 同时打码 QQ。
- 顶层导出 `DEFAULT_USER_AGENT`。

### 变更（可能影响调用方）

- `--account` 的 `-n` 现在只控制密码长度，用户名长度改用 `--username-length`
  （与 `--prepare` 语义统一）。
- 远程请求增加有限重试（超时 / 5xx / 429），退避带 ±25% 抖动并封顶 60s。
- 响应体读取上限 512 KiB。
- 版本号改为单一来源：`pyproject.toml` 动态读取 `gen4399.__version__`。
- 新增 `LICENSE`（MIT）、`CHANGELOG.md`、`.gitignore`、CI、ruff/mypy/pytest/coverage 配置。

## [1.8.1] - 2026-11-07

- 初始版本：密码/用户名生成与校验、4399 远程接口封装、注册表单本地校验、
  `prepare_registration()` 一键准备注册数据、CLI。
