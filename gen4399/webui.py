"""本地 WebUI：在浏览器里配置并跑批量注册，导入 sfz.txt、导出账号。

只依赖标准库；默认只监听 ``127.0.0.1``，不要去公网暴露。

    python -m gen4399.webui                 # http://127.0.0.1:8765
    python -m gen4399.webui --port 9000 --host 127.0.0.1
    gen4399 webui --open                    # 启动并尝试打开浏览器

页面能力：导入身份 → 设定数量/前后缀/通道/间隔/验证码 → 运行（后台线程）→
实时进度 → 导出 CSV/JSON。web 验证码模式下会弹图让人填。
"""

from __future__ import annotations

import base64
import csv
import io
import json
import os
import queue
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .account import account_record, append_account, load_accounts
from .batch import run_batch
from .core import Gen4399Error
from .identity import RegistrationProfile, load_profiles_auto
from .login import login as do_login

__all__ = ["serve", "main"]

_STATE_LOCK = threading.Lock()


class _Task:
    """一次批量任务的状态（单例，服务端同一时间只跑一个）。"""

    def __init__(self) -> None:
        self.thread: threading.Thread | None = None
        self.stop = threading.Event()
        self.running = False
        self.total = 0
        self.finished = 0
        self.success = 0
        self.failed = 0
        self.skipped = 0
        self.started_at = 0.0
        self.finished_at = 0.0
        self.error = ""
        self.items: list[dict] = []
        self.logs: list[str] = []

    def snapshot(self) -> dict:
        return {
            "running": self.running,
            "total": self.total,
            "finished": self.finished,
            "success": self.success,
            "failed": self.failed,
            "skipped": self.skipped,
            "elapsed": round((self.finished_at or time.time()) - self.started_at, 1)
            if self.started_at
            else 0,
            "error": self.error,
            "items": self.items[-200:],
            "logs": self.logs[-200:],
        }

    def log(self, text: str) -> None:
        with _STATE_LOCK:
            self.logs.append(f"{time.strftime('%H:%M:%S')} {text}")
            del self.logs[:-500]


class _WebCaptcha:
    """在浏览器里弹图识别的验证码回调（调用方线程会阻塞等待）。"""

    def __init__(self) -> None:
        self.pending: dict | None = None
        self.answer: str | None = None
        self.event = threading.Event()
        self.lock = threading.Lock()

    def __call__(self, image: bytes) -> str:
        with self.lock:
            self.pending = {
                "image": base64.b64encode(image).decode("ascii"),
                "at": time.time(),
            }
            self.answer = None
            self.event.clear()
        self.event.wait(timeout=180)
        with self.lock:
            answer = self.answer or ""
            self.pending = None
        return answer

    def submit(self, code: str) -> bool:
        with self.lock:
            if self.pending is None:
                return False
            self.answer = code
        self.event.set()
        return True

    def snapshot(self) -> dict | None:
        with self.lock:
            return self.pending


TASK = _Task()
CAPTCHA = _WebCaptcha()


def _parse_profiles(text: str) -> list[RegistrationProfile]:
    """把 sfz.txt 文本解析成身份列表（支持 姓名|身份证[|QQ]）。"""
    tmp = Path(os.environ.get("TMPDIR", "/tmp")) / f"gen4399-webui-{os.getpid()}.txt"
    tmp.write_text(text, encoding="utf-8")
    try:
        result = load_profiles_auto(tmp)
        profiles = getattr(result, "profiles", result)
        return list(profiles)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


def _make_captcha(mode: str):
    from ._captcha import matcher_captcha_solver
    from .captcha_web import learning_captcha_solver

    if mode == "matcher":
        return matcher_captcha_solver()
    if mode == "learn":
        return learning_captcha_solver()
    if mode == "human":
        return CAPTCHA
    return None


def _run_task(
    profiles: list[RegistrationProfile],
    *,
    path: str,
    count: int,
    interval: float,
    jitter: float,
    captcha_mode: str,
    dry_run: bool,
    output: str,
    verify_login: bool,
) -> None:
    task = TASK
    task.total = min(count, len(profiles)) if count else len(profiles)
    captcha = _make_captcha(captcha_mode)

    def progress(index: int, total: int, item) -> None:
        with _STATE_LOCK:
            task.finished = index
            task.success += 1 if item.ok else 0
            task.failed += 0 if item.ok else 1
            task.items.append(
                {
                    "index": index,
                    "username": item.username,
                    "kind": item.kind,
                    "ok": item.ok,
                    "message": item.message[:200],
                }
            )
        task.log(f"[{index}/{total}] {item.username} {item.kind}")

    try:
        selected = profiles[:count] if count else profiles
        summary = run_batch(
            selected,
            path=path,
            captcha=captcha,
            interval=interval,
            jitter=jitter,
            dry_run=dry_run,
            output=output,
            verify_login=verify_login,
            on_progress=progress,
            stop_event=task.stop,
        )
        with _STATE_LOCK:
            task.skipped = summary.skipped
            task.success = summary.success
            task.failed = summary.failed
        task.log(f"完成：成功 {summary.success}，失败 {summary.failed}，跳过 {summary.skipped}")
    except Gen4399Error as exc:
        with _STATE_LOCK:
            task.error = str(exc)
        task.log(f"错误：{exc}")
    finally:
        with _STATE_LOCK:
            task.running = False
            task.finished_at = time.time()


PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>gen4399 WebUI</title>
<style>
:root{--bg:#0f1115;--panel:#171a21;--line:#262b36;--fg:#e6e8ee;--dim:#8b93a7;--ok:#3fb950;--bad:#f85149;--acc:#4c8dff}
*{box-sizing:border-box}
body{margin:0;font:14px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--fg)}
header{padding:14px 18px;border-bottom:1px solid var(--line);display:flex;gap:12px;align-items:center;flex-wrap:wrap}
header h1{font-size:16px;margin:0;font-weight:600}
.badge{font-size:12px;color:var(--dim);border:1px solid var(--line);padding:2px 8px;border-radius:999px}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:14px;padding:14px}
section{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}
section h2{font-size:13px;margin:0 0 10px;color:var(--dim);font-weight:600;letter-spacing:.04em}
label{display:block;font-size:12px;color:var(--dim);margin:8px 0 4px}
input,select,textarea,button{font:inherit;color:var(--fg);background:#0c0e13;border:1px solid var(--line);border-radius:8px;padding:8px 10px;width:100%}
textarea{min-height:96px;font-family:ui-monospace,monospace;font-size:12px}
button{cursor:pointer;background:var(--acc);border-color:var(--acc);color:#fff;font-weight:600}
button.ghost{background:transparent;border-color:var(--line);color:var(--fg)}
button:disabled{opacity:.5;cursor:not-allowed}
.row{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.actions{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}
.bar{height:8px;background:#0c0e13;border-radius:999px;overflow:hidden;margin:10px 0}
.bar>i{display:block;height:100%;width:0;background:var(--ok);transition:width .3s}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{text-align:left;padding:5px 6px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--dim);font-weight:600}
.ok{color:var(--ok)}.bad{color:var(--bad)}
#log{max-height:180px;overflow:auto;font-family:ui-monospace,monospace;font-size:12px;color:var(--dim);white-space:pre-wrap}
#capbox{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);place-items:center;padding:20px}
#capbox.on{display:grid}
#capbox .card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px;max-width:420px;width:100%}
#capbox img{width:100%;background:#fff;border-radius:8px;margin-bottom:10px}
</style></head>
<body>
<header>
  <h1>gen4399 WebUI</h1>
  <span class="badge" id="ver">__VERSION__</span>
  <span class="badge" id="state">空闲</span>
  <button class="ghost" style="width:auto;margin-left:auto" onclick="health()">健康检查</button>
</header>
<main>
  <section>
    <h2>1 · 身份（sfz.txt）</h2>
    <label>粘贴内容（每行 <code>姓名|身份证[|QQ]</code>）</label>
    <textarea id="sfz" placeholder="张三|110105198803121893"></textarea>
    <div class="actions">
      <button class="ghost" onclick="document.getElementById('file').click()">导入文件</button>
      <input type="file" id="file" accept=".txt,.csv,text/plain" style="display:none" onchange="pickFile(this)">
      <button class="ghost" onclick="parseSfz()">解析</button>
      <span class="badge" id="sfzcount">未解析</span>
    </div>
  </section>

  <section>
    <h2>2 · 生成设置</h2>
    <div class="row">
      <div><label>数量</label><input id="count" type="number" min="1" value="1"></div>
      <div><label>通道</label>
        <select id="path"><option value="unified">unified（ptlogin）</option><option value="web">web</option></select>
      </div>
    </div>
    <div class="row">
      <div><label>用户名前缀</label><input id="prefix" placeholder="可空"></div>
      <div><label>用户名后缀</label><input id="suffix" placeholder="可空"></div>
    </div>
    <div class="row">
      <div><label>间隔（秒）</label><input id="interval" type="number" min="0" value="20"></div>
      <div><label>随机抖动（秒）</label><input id="jitter" type="number" min="0" value="10"></div>
    </div>
    <div class="row">
      <div><label>验证码</label>
        <select id="captcha">
          <option value="matcher">内置模板（unified 60×30）</option>
          <option value="learn">自学习字库（web 150×45）</option>
          <option value="human">浏览器人工识别</option>
          <option value="">不处理（遇到就记 captcha）</option>
        </select>
      </div>
      <div><label>模式</label>
        <select id="mode"><option value="dry">dry-run（不提交）</option><option value="real">真实提交</option></select>
      </div>
    </div>
    <label><input type="checkbox" id="verifyLogin" style="width:auto"> 注册后登录复核</label>
    <div class="actions">
      <button id="runBtn" onclick="startTask()">开始</button>
      <button class="ghost" onclick="stopTask()">停止</button>
    </div>
  </section>

  <section style="grid-column:1/-1">
    <h2>3 · 进度</h2>
    <div class="bar"><i id="progress"></i></div>
    <div class="badge" id="stat">等待开始</div>
    <div id="log"></div>
  </section>

  <section style="grid-column:1/-1">
    <h2>4 · 结果</h2>
    <div class="actions" style="margin:0 0 10px">
      <button class="ghost" onclick="exportAs('csv')">导出 CSV</button>
      <button class="ghost" onclick="exportAs('json')">导出 JSON</button>
      <button class="ghost" onclick="loadAccounts()">刷新</button>
    </div>
    <table><thead><tr><th>#</th><th>账号</th><th>结果</th><th>说明</th></tr></thead>
    <tbody id="items"></tbody></table>
  </section>
</main>

<div id="capbox"><div class="card">
  <h2 style="color:var(--fg)">请输入验证码</h2>
  <img id="capimg" alt="captcha">
  <input id="capinput" placeholder="4 位字符" autocomplete="off">
  <div class="actions"><button onclick="submitCaptcha()">提交</button></div>
</div></div>

<script>
const $ = (id) => document.getElementById(id);
let parsedCount = 0, pollTimer = null, capTimer = null;

async function api(path, body) {
  const res = await fetch(path, body ? {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
  } : {});
  return res.json();
}

async function health() {
  const info = await api('/api/health');
  $('ver').textContent = info.version;
  $('state').textContent = info.running ? '运行中' : '空闲';
}

function pickFile(input) {
  const file = input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => { $('sfz').value = reader.result; parseSfz(); };
  reader.readAsText(file, 'utf-8');
}

async function parseSfz() {
  const text = $('sfz').value.trim();
  if (!text) { $('sfzcount').textContent = '未解析'; return; }
  const data = await api('/api/parse', {sfz: text});
  parsedCount = data.count;
  $('sfzcount').textContent = data.count ? `${data.count} 条（${data.invalid} 条无效）` : '解析失败';
  if (data.errors?.length) $('log').textContent = data.errors.slice(0, 5).join('\\n');
}

async function startTask() {
  if (!parsedCount) await parseSfz();
  const payload = {
    sfz: $('sfz').value,
    count: Number($('count').value) || 0,
    prefix: $('prefix').value.trim(),
    suffix: $('suffix').value.trim(),
    path: $('path').value,
    interval: Number($('interval').value) || 0,
    jitter: Number($('jitter').value) || 0,
    captcha: $('captcha').value,
    dry_run: $('mode').value === 'dry',
    verify_login: $('verifyLogin').checked,
  };
  if (!payload.dry_run && !confirm('将真实提交注册请求，确认继续？')) return;
  const res = await api('/api/run', payload);
  if (!res.ok) { alert(res.error || '启动失败'); return; }
  $('runBtn').disabled = true;
  $('items').innerHTML = '';
  poll();
  pollTimer = setInterval(poll, 1000);
  capTimer = setInterval(checkCaptcha, 1200);
}

async function stopTask() { await api('/api/stop', {}); }

async function poll() {
  const s = await api('/api/status');
  const pct = s.total ? Math.round(s.finished / s.total * 100) : 0;
  $('progress').style.width = pct + '%';
  $('state').textContent = s.running ? '运行中' : (s.error ? '出错' : '空闲');
  $('stat').textContent = `总数 ${s.total} · 完成 ${s.finished} · 成功 ${s.success} · 失败 ${s.failed} · 跳过 ${s.skipped} · ${s.elapsed}s`;
  if (s.items) {
    $('items').innerHTML = s.items.map(i =>
      `<tr><td>${i.index}</td><td>${i.username}</td>
       <td class="${i.ok ? 'ok' : 'bad'}">${i.kind}</td><td>${i.message || ''}</td></tr>`).join('');
  }
  if (s.logs) $('log').textContent = s.logs.join('\\n');
  if (!s.running) {
    $('runBtn').disabled = false;
    clearInterval(pollTimer); clearInterval(capTimer); pollTimer = capTimer = null;
  }
}

async function checkCaptcha() {
  const c = await api('/api/captcha');
  const box = $('capbox');
  if (c && c.image) {
    if (!box.classList.contains('on')) {
      $('capimg').src = 'data:image/png;base64,' + c.image;
      $('capinput').value = '';
      box.classList.add('on');
      $('capinput').focus();
    }
  } else {
    box.classList.remove('on');
  }
}

async function submitCaptcha() {
  const code = $('capinput').value.trim();
  if (!code) return;
  await api('/api/captcha', {code});
  $('capbox').classList.remove('on');
}

async function loadAccounts() {
  const data = await api('/api/accounts');
  $('items').innerHTML = (data.items || []).slice(-200).map((a, i) =>
    `<tr><td>${i + 1}</td><td>${a.username || ''}</td>
     <td class="${a.ok ? 'ok' : 'bad'}">${a.kind || ''}</td><td>${a.created_at || ''}</td></tr>`).join('');
}

function exportAs(format) {
  window.location = `/api/export?format=${format}`;
}

health(); loadAccounts();
</script>
</body></html>
"""


class _Handler(BaseHTTPRequestHandler):
    server_version = f"gen4399-webui/{__version__}"
    accounts_path = "accounts.json"
    dry_run_only = False

    # ---- 基础工具 ----
    def log_message(self, fmt: str, *args) -> None:  # 安静一点
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, status: int = 200) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    # ---- 路由 ----
    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            html = PAGE.replace("__VERSION__", f"v{__version__}")
            self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/health":
            self._json({"ok": True, "version": __version__, "running": TASK.running})
            return
        if path == "/api/status":
            self._json(TASK.snapshot())
            return
        if path == "/api/captcha":
            self._json(CAPTCHA.snapshot() or {})
            return
        if path == "/api/accounts":
            records = load_accounts(self.accounts_path)
            self._json({"items": records})
            return
        if path == "/api/export":
            self._export()
            return
        self._send(404, b"not found", "text/plain")

    def _export(self) -> None:
        from urllib.parse import parse_qs, urlparse

        query = parse_qs(urlparse(self.path).query)
        fmt = (query.get("format") or ["csv"])[0]
        records = load_accounts(self.accounts_path)
        if fmt == "json":
            body = json.dumps(records, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition", 'attachment; filename="accounts.json"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        buffer = io.StringIO()
        fields = ["created_at", "path", "username", "password", "kind", "ok",
                  "message", "endpoint", "http_status", "idcard_masked"]
        writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow(record)
        body = buffer.getvalue().encode("utf-8-sig")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", 'attachment; filename="accounts.csv"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        payload = self._body()

        if path == "/api/parse":
            text = str(payload.get("sfz") or "")
            try:
                profiles = _parse_profiles(text)
            except (Gen4399Error, OSError, ValueError) as exc:
                self._json({"count": 0, "invalid": 0, "errors": [str(exc)]})
                return
            self._json({"count": len(profiles), "invalid": 0, "errors": []})
            return

        if path == "/api/run":
            self._start(payload)
            return

        if path == "/api/stop":
            TASK.stop.set()
            self._json({"ok": True})
            return

        if path == "/api/captcha":
            code = str(payload.get("code") or "").strip()
            self._json({"ok": CAPTCHA.submit(code)})
            return

        self._send(404, b"not found", "text/plain")

    def _start(self, payload: dict) -> None:
        if TASK.running:
            self._json({"ok": False, "error": "已有任务在跑"}, 409)
            return
        text = str(payload.get("sfz") or "")
        try:
            profiles = _parse_profiles(text)
        except (Gen4399Error, OSError, ValueError) as exc:
            self._json({"ok": False, "error": f"身份解析失败：{exc}"}, 400)
            return
        if not profiles:
            self._json({"ok": False, "error": "没有可用身份"}, 400)
            return

        dry_run = bool(payload.get("dry_run", True))
        if self.dry_run_only and not dry_run:
            self._json({"ok": False, "error": "服务以 --dry-run-only 启动，不允许真实提交"}, 403)
            return

        with _STATE_LOCK:
            TASK.thread = None
            TASK.stop.clear()
            TASK.running = True
            TASK.total = int(payload.get("count") or len(profiles))
            TASK.finished = 0
            TASK.success = 0
            TASK.failed = 0
            TASK.skipped = 0
            TASK.started_at = time.time()
            TASK.finished_at = 0.0
            TASK.error = ""
            TASK.items = []
            TASK.logs = []

        thread = threading.Thread(
            target=_run_task,
            args=(profiles,),
            kwargs={
                "path": str(payload.get("path") or "unified"),
                "count": int(payload.get("count") or 0),
                "interval": float(payload.get("interval") or 0),
                "jitter": float(payload.get("jitter") or 0),
                "captcha_mode": str(payload.get("captcha") or ""),
                "dry_run": dry_run,
                "output": self.accounts_path,
                "verify_login": bool(payload.get("verify_login")),
            },
            daemon=True,
        )
        TASK.thread = thread
        thread.start()
        self._json({"ok": True})


def serve(host: str = "127.0.0.1", port: int = 8765, *,
          accounts: str = "accounts.json", dry_run_only: bool = False) -> None:
    """启动 WebUI（阻塞）。"""
    _Handler.accounts_path = accounts
    _Handler.dry_run_only = dry_run_only
    httpd = ThreadingHTTPServer((host, port), _Handler)
    print(f"gen4399 WebUI v{__version__} → http://{host}:{port}/")
    print(f"账号文件：{Path(accounts).resolve()}；只监听 {host}，不要暴露到公网")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="gen4399 webui", description="gen4399 本地 WebUI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--accounts", default="accounts.json", help="账号文件路径")
    parser.add_argument("--dry-run-only", action="store_true", help="禁止真实提交（演示用）")
    parser.add_argument("--open", action="store_true", help="启动后尝试打开浏览器")
    args = parser.parse_args(argv)

    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(f"http://{args.host}:{args.port}/")).start()
    serve(args.host, args.port, accounts=args.accounts, dry_run_only=args.dry_run_only)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
