"""账号记录：把一次注册结果追加到本地 JSON 文件（默认 0600）。

`make_account.py` 用的就是这里的函数；写在库里是为了让「跑一次拿一个号」的
行为可以被脚本之外的调用方复用。

文件格式是一个 JSON 数组，每条形如::

    {"created_at": "...", "path": "unified", "username": "...",
     "password": "...", "kind": "success", "ok": true, "message": "...",
     "endpoint": "...", "http_status": 200, "idcard_masked": "110105********1893"}

注意：里面含**明文密码**，文件权限固定 0600。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from .registration import RegistrationBundle
from .submit import SubmitResult

__all__ = ["account_record", "append_account", "load_accounts"]


def account_record(
    bundle: RegistrationBundle,
    result: SubmitResult,
    *,
    created_at: str | None = None,
) -> dict:
    """把 ``bundle + result`` 组成一条可落盘的账号记录。"""
    return {
        "created_at": created_at
        or datetime.now().astimezone().isoformat(timespec="seconds"),
        "path": result.path,
        "username": bundle.username,
        "password": bundle.password,
        "kind": result.kind,
        "ok": result.ok,
        "message": result.message,
        "endpoint": result.endpoint,
        "http_status": result.http_status,
        "idcard_masked": bundle.masked_idcard(),
    }


def load_accounts(path: "str | os.PathLike[str]") -> list[dict]:
    """读取已有账号文件；不存在或损坏时返回空列表。"""
    file_path = Path(path)
    if not file_path.exists():
        return []
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, dict):
        return [data]
    return data if isinstance(data, list) else []


def append_account(
    path: "str | os.PathLike[str]",
    record: dict,
    *,
    warn=None,
) -> Path:
    """把 ``record`` 追加进 JSON 数组，原子写入并保持 0600。

    Args:
        path: 目标文件。
        record: :func:`account_record` 产出的字典。
        warn: 文件不是合法 JSON 时的提示回调（默认写 stderr）。

    Returns:
        实际写入的路径。
    """
    file_path = Path(path)
    existing = load_accounts(file_path)
    if file_path.exists() and not existing:
        message = f"# 警告：{file_path} 不是合法 JSON，将覆盖写入"
        if warn is not None:
            warn(message)
        else:
            print(message, file=__import__("sys").stderr)
    existing.append(record)

    tmp = file_path.with_name(file_path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(
            fd,
            json.dumps(existing, ensure_ascii=False, indent=2).encode("utf-8"),
        )
    finally:
        os.close(fd)
    os.replace(tmp, file_path)
    try:
        os.chmod(file_path, 0o600)
    except OSError:  # pragma: no cover - 非 POSIX
        pass
    return file_path
