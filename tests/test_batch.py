"""批量注册编排（gen4399.batch）的离线测试。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gen4399.batch import BatchItem, BatchSummary, run_batch
from gen4399.forms import RegistrationProfile
from gen4399.submit import SubmitResult

ID_A = "460206194611192084"
ID_B = "110105198803121893"


def _profile(name="张三", idcard=ID_A):
    return RegistrationProfile(name, idcard)


def _bundle(username="abc12345"):
    return mock.Mock(username=username, password="pwd12345", idcard=ID_A,
                     masked_idcard=lambda: "110105********1893")


def _result(kind="success", ok=True, message="注册成功"):
    return SubmitResult(ok=ok, kind=kind, message=message, username="abc12345",
                        path="unified", app_id="u4399", endpoint="x")


class TestRunBatch(unittest.TestCase):
    def _run(self, profiles, results, **kwargs):
        calls = []

        def fake_prepare(profile, **kw):
            calls.append(profile)
            return _bundle(f"user{len(calls)}")

        seq = list(results)

        def fake_submit(bundle, **kw):
            return seq.pop(0)

        with mock.patch("gen4399.batch.prepare_registration", fake_prepare), \
             mock.patch("gen4399.batch.submit_registration", fake_submit):
            summary = run_batch(profiles, interval=0, **kwargs)
        return summary, calls

    def test_all_success(self):
        summary, calls = self._run([_profile(), _profile()], [_result(), _result()])
        self.assertEqual(summary.success, 2)
        self.assertEqual(summary.failed, 0)
        self.assertEqual(len(calls), 2)

    def test_mixed_results(self):
        summary, _ = self._run(
            [_profile(), _profile()],
            [_result(), _result(kind="rejected", ok=False, message="用户名已存在")],
        )
        self.assertEqual(summary.success, 1)
        self.assertEqual(summary.failed, 1)
        self.assertEqual(summary.by_kind(), {"success": 1, "rejected": 1})

    def test_dry_run_not_counted_as_failure(self):
        summary, _ = self._run(
            [_profile()], [_result(kind="dry_run", ok=False, message="dry")],
            dry_run=True,
        )
        self.assertEqual(summary.failed, 0)
        self.assertEqual(summary.by_kind(), {"dry_run": 1})

    def test_max_failures_aborts(self):
        profiles = [_profile() for _ in range(5)]
        results = [_result(kind="throttled", ok=False, message="限流")] * 3
        summary, calls = self._run(profiles, results, max_failures=2)
        self.assertTrue(summary.aborted)
        self.assertEqual(len(calls), 2)

    def test_stop_event(self):
        import threading

        event = threading.Event()
        event.set()
        summary, calls = self._run([_profile()], [_result()], stop_event=event)
        self.assertTrue(summary.aborted)
        self.assertEqual(calls, [])

    def test_output_and_skip_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "accounts.json")
            summary, _ = self._run([_profile()], [_result()], output=out)
            self.assertEqual(summary.success, 1)
            data = json.loads(Path(out).read_text())
            self.assertEqual(len(data), 1)
            self.assertIn("idcard_hash", data[0])

            summary2, calls2 = self._run(
                [_profile()], [], output=out
            )
            self.assertEqual(summary2.skipped, 1)
            self.assertEqual(calls2, [])

    def test_progress_callback(self):
        seen = []
        profiles = [_profile()]
        with mock.patch(
            "gen4399.batch.prepare_registration", return_value=_bundle()
        ), mock.patch(
            "gen4399.batch.submit_registration", return_value=_result()
        ):
            run_batch(
                profiles, interval=0,
                on_progress=lambda i, t, item: seen.append((i, t, item.ok)),
            )
        self.assertEqual(seen, [(1, 1, True)])

    def test_prepare_error_recorded(self):
        with mock.patch(
            "gen4399.batch.prepare_registration", side_effect=ValueError("坏参数")
        ):
            summary = run_batch([_profile()], interval=0)
        self.assertEqual(summary.items[0].kind, "error")
        self.assertIn("坏参数", summary.items[0].message)


class TestSummarySerialization(unittest.TestCase):
    def test_to_dict(self):
        summary = BatchSummary(
            items=[BatchItem(1, "u1", "success", True, "ok")], skipped=2
        )
        data = summary.to_dict()
        self.assertEqual(data["total"], 3)
        self.assertEqual(data["success"], 1)
        self.assertEqual(data["items"][0]["username"], "u1")

    def test_repr_hides_nothing_sensitive(self):
        item = BatchItem(1, "u1", "success", True, "ok")
        self.assertIn("BatchItem", repr(item))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
