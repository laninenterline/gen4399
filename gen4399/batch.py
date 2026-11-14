"""批量注册编排：一次跑多个身份，带节奏、去重、落盘与汇总。

和 ``gen4399 submit``（单身份）的区别：

* 每个身份独立 ``prepare → submit``，互相隔离（换代理 / 换 UA 由
  :class:`~gen4399.transport.TransportOptions` 负责）
* 身份之间按 ``interval + jitter`` 随机间隔，避免同一秒连发
* 已经成功注册过的身份（按身份证哈希）默认跳过，支持断点续跑
* 每个结果立即追加到账号文件，跑一半中断也不丢已建好的号

>>> from gen4399 import RegistrationProfile
>>> profiles = [RegistrationProfile("张三", "460206194611192084")]
>>> summary = run_batch(profiles, dry_run=True)      # doctest: +SKIP
>>> summary.success                                    # doctest: +SKIP
0
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

from .account import account_record, append_account, load_accounts
from .core import Gen4399Error
from .registration import prepare_registration
from .submit import SubmitResult, submit_registration

__all__ = ["BatchItem", "BatchSummary", "run_batch"]


@dataclass(frozen=True, repr=False)
class BatchItem:
    """一个身份的执行结果。"""

    index: int
    username: str
    kind: str
    ok: bool
    message: str
    elapsed: float = 0.0

    def __repr__(self) -> str:
        return (
            f"BatchItem(index={self.index}, username={self.username!r}, "
            f"kind={self.kind!r}, ok={self.ok!r})"
        )


@dataclass
class BatchSummary:
    """整批的汇总。"""

    items: list[BatchItem] = field(default_factory=list)
    skipped: int = 0
    aborted: bool = False
    elapsed: float = 0.0

    @property
    def total(self) -> int:
        return len(self.items) + self.skipped

    @property
    def success(self) -> int:
        return sum(1 for i in self.items if i.ok)

    @property
    def failed(self) -> int:
        """真正失败的数量（dry-run 不算失败）。"""
        return sum(1 for i in self.items if not i.ok and i.kind != "dry_run")

    def by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.items:
            counts[item.kind] = counts.get(item.kind, 0) + 1
        return counts

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "success": self.success,
            "failed": self.failed,
            "skipped": self.skipped,
            "aborted": self.aborted,
            "elapsed": round(self.elapsed, 2),
            "by_kind": self.by_kind(),
            "items": [
                {
                    "index": i.index,
                    "username": i.username,
                    "kind": i.kind,
                    "ok": i.ok,
                    "message": i.message,
                }
                for i in self.items
            ],
        }


def _already_done(output: str | None, idcard: str) -> bool:
    """账号文件里是否已有这个身份证的成功记录（用于断点续跑）。"""
    if not output:
        return False
    import hashlib

    digest = hashlib.sha256(idcard.encode("utf-8")).hexdigest()[:16]
    for record in load_accounts(output):
        if record.get("idcard_hash") == digest and record.get("ok"):
            return True
    return False


def run_batch(
    profiles,
    *,
    path: str = "unified",
    captcha=None,
    transport=None,
    interval: float = 30.0,
    jitter: float = 0.0,
    dry_run: bool = False,
    max_failures: int = 0,
    output: str | None = None,
    verify_login: bool = False,
    on_progress=None,
    stop_event=None,
    rng: random.Random | None = None,
) -> BatchSummary:
    """依次注册一批身份。

    Args:
        profiles: :class:`~gen4399.RegistrationProfile` 列表。
        path: ``web`` / ``unified``。
        captcha: 验证码识别回调。
        transport: 代理 / 随机 UA 配置。
        interval: 两个身份之间的基础间隔（秒），默认 30。
        jitter: 额外随机抖动（秒），实际等待 ``interval + U(0, jitter)``。
        dry_run: 只组装不提交。
        max_failures: 连续失败多少次就中止（0 表示不中止）。
        output: 账号文件；给了就把每条成功/unknown 记录追加进去。
        verify_login: 成功后立刻用登录接口复核。
        on_progress: 可选回调 ``(index, total, item) -> None``。
        stop_event: 可选 ``threading.Event``，置位后在下一个身份前停下。
        rng: 随机源（测试可注入）。

    Returns:
        :class:`BatchSummary`。
    """
    rng = rng or random
    summary = BatchSummary()
    started = time.monotonic()
    failures = 0

    for index, profile in enumerate(profiles, 1):
        if stop_event is not None and stop_event.is_set():
            summary.aborted = True
            break
        if _already_done(output, profile.idcard):
            summary.skipped += 1
            continue

        item_started = time.monotonic()
        try:
            bundle = prepare_registration(profile, path=path, transport=transport)
            result: SubmitResult = submit_registration(
                bundle,
                dry_run=dry_run,
                captcha=captcha,
                transport=transport,
            )
            item = BatchItem(
                index=index,
                username=bundle.username,
                kind=result.kind,
                ok=result.ok,
                message=result.message,
                elapsed=time.monotonic() - item_started,
            )
            if output and result.kind in ("success", "unknown"):
                try:
                    append_account(output, account_record(bundle, result))
                except OSError as exc:  # pragma: no cover - 磁盘问题
                    item = BatchItem(
                        index=index,
                        username=bundle.username,
                        kind=result.kind,
                        ok=result.ok,
                        message=f"{result.message}（写账号文件失败：{exc}）",
                        elapsed=item.elapsed,
                    )
            if verify_login and result.ok:
                from .login import login as do_login

                check = do_login(bundle.username, bundle.password)
                if not check.ok:
                    item = BatchItem(
                        index=index,
                        username=bundle.username,
                        kind="login_failed",
                        ok=False,
                        message=f"注册成功但登录复核失败：{check.message}",
                        elapsed=item.elapsed,
                    )
        except (Gen4399Error, TypeError, ValueError, OSError) as exc:
            item = BatchItem(
                index=index,
                username="?",
                kind="error",
                ok=False,
                message=str(exc),
                elapsed=time.monotonic() - item_started,
            )

        summary.items.append(item)
        if on_progress is not None:
            on_progress(index, len(profiles), item)

        failures = 0 if item.ok else failures + 1
        if max_failures and failures >= max_failures:
            summary.aborted = True
            break
        if index < len(profiles) and not dry_run:
            wait = interval + (rng.uniform(0, jitter) if jitter else 0.0)
            if wait > 0:
                time.sleep(wait)

    summary.elapsed = time.monotonic() - started
    return summary
