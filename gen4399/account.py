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

__all__ = [
    "account_record",
    "append_account",
    "load_accounts",
    "dedupe_accounts",
    "accounts_to_csv",
    "accounts_to_jsonl",
    "account_stats",
]


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


def dedupe_accounts(records: list[dict]) -> tuple[list[dict], int]:
    """按 ``(username, password)`` 去重，保留最早的一条。

    Returns:
        ``(去重后的列表, 被去掉的条数)``。
    """
    seen: set[tuple] = set()
    out: list[dict] = []
    for record in records:
        key = (record.get("username"), record.get("password"))
        if key in seen:
            continue
        seen.add(key)
        out.append(record)
    return out, len(records) - len(out)


def _public(record: dict, *, include_secrets: bool) -> dict:
    """去掉敏感字段（密码）后的记录副本。"""
    if include_secrets:
        return dict(record)
    item = dict(record)
    password = item.pop("password", None)
    item["password_masked"] = (
        "*" * len(password) if isinstance(password, str) and password else ""
    )
    return item


_CSV_FIELDS = (
    "created_at", "path", "username", "password", "password_masked",
    "kind", "ok", "message", "endpoint", "http_status", "idcard_masked",
)


def accounts_to_csv(
    records: list[dict], *, include_secrets: bool = False
) -> str:
    """把账号记录渲染成 CSV 文本（默认把密码打码）。"""
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for record in records:
        writer.writerow(_public(record, include_secrets=include_secrets))
    return buffer.getvalue()


def accounts_to_jsonl(
    records: list[dict], *, include_secrets: bool = False
) -> str:
    """把账号记录渲染成 JSON Lines 文本（默认把密码打码）。"""
    return "\n".join(
        json.dumps(_public(r, include_secrets=include_secrets), ensure_ascii=False)
        for r in records
    ) + ("\n" if records else "")


def account_stats(records: list[dict]) -> dict:
    """汇总：总数、按 kind / path 分组、成功数。"""
    by_kind: dict[str, int] = {}
    by_path: dict[str, int] = {}
    for record in records:
        kind = str(record.get("kind") or "?")
        path = str(record.get("path") or "?")
        by_kind[kind] = by_kind.get(kind, 0) + 1
        by_path[path] = by_path.get(path, 0) + 1
    return {
        "total": len(records),
        "ok": sum(1 for r in records if r.get("ok")),
        "by_kind": by_kind,
        "by_path": by_path,
    }
