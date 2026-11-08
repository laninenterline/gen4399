# gen4399 WebUI · 前端

React 19 + TypeScript + Vite + Tailwind CSS 4 的单页应用；后端是 `gen4399/webui.py`
（Python 标准库 http.server，提供 `/api/*` 与静态托管）。

## 开发

```bash
# 终端 1：后端（8765）
python -m gen4399.webui

# 终端 2：前端开发服务器（5173，/api 自动代理到 8765）
cd web && npm install && npm run dev
```

## 构建与部署

```bash
cd web && npm run build     # 产物在 web/dist
python -m gen4399.webui     # 后端会自动托管 web/dist，SPA 路由回落到 index.html
```

`web/dist` 不存在时后端会退回内置的简化页面（仅用于兜底），并在启动日志里提示。

## 结构

```
src/
├── api.ts                  类型化 API 客户端（/api/health、/api/parse、/api/run、…）
├── App.tsx                 页面骨架 + 轮询状态 + 验证码弹窗调度
└── components/
    ├── IdentityPanel.tsx   sfz.txt 粘贴 / 导入 / 解析结果
    ├── SettingsPanel.tsx   数量、通道、前后缀、间隔、验证码模式、dry-run
    ├── RunPanel.tsx        开始/停止、进度条、日志
    ├── ResultsPanel.tsx    逐条结果 + CSV/JSON 导出
    ├── CaptchaModal.tsx    浏览器内弹图识别验证码
    └── ui.tsx              Card / Button / Field / Input / Badge 等基础组件
```

## 为什么后端是 Python 标准库

注册协议、验证码识别、代理池都在 Python 侧，前端只做展示与交互。
本机 Python 3.14 (Termux/aarch64) 装不上 FastAPI 的轮子（PyPI 无匹配版本），
所以后端继续用标准库实现同一套 JSON API —— 接口契约不变，将来换成
FastAPI/Starlette 只需替换 `gen4399/webui.py` 的 HTTP 层。

## 环境变量

| 变量 | 作用 |
|---|---|
| `GEN4399_WEB_DIST` | 指定前端构建产物目录（默认 `<repo>/web/dist`） |
