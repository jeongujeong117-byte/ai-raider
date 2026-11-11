"""Blackbox independent verification tests for T-001 (Collector Health Supervisor).

Verifies the public contract of HealthState, exceptions, Supervisor lifecycle,
retry limits, abort/stop signals, fallback mechanisms, secret masking, and
atomic state persistence without relying on internal implementation details.
"""
from __future__ import annotations

import json
import math
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from agents.base_supervisor import (
    Blocked,
    HealthState,
    RateLimited,
    SessionExpired,
    Supervisor,
    SupervisorStopped,
)


class MockStopEvent:
    """threading.Event compatible mock for deterministic stop/wait control."""

    def __init__(self, preset: bool = False, set_after_waits: int | None = None):
        self._set = preset
        self._set_after_waits = set_after_waits
        self.waits: list[float | None] = []

    def is_set(self) -> bool:
        return self._set

    def set(self) -> None:
        self._set = True

    def wait(self, timeout: float | None = None) -> bool:
        self.waits.append(timeout)
        if self._set_after_waits is not None and len(self.waits) >= self._set_after_waits:
            self._set = True
        return self._set


def constant_clock(fixed_epoch: float = 1700000000.0):
    current = [fixed_epoch]

    def _clock() -> float:
        return current[0]

    _clock.advance = lambda sec: current.__setitem__(0, current[0] + sec)  # type: ignore[attr-defined]
    _clock.set = lambda val: current.__setitem__(0, val)  # type: ignore[attr-defined]
    return _clock


def make_call_sequence(*items):
    """Returns a callable that yields consecutive return values or raises exceptions."""
    calls: list[int] = []

    def _op():
        idx = len(calls)
        calls.append(1)
        item = items[min(idx, len(items) - 1)]
        if isinstance(item, BaseException):
            raise item
        return item

    _op.calls = calls
    return _op


class BlackboxSupervisorTests(unittest.TestCase):
    """Independent blackbox attack tests against Supervisor contract."""

    # ------------------------------------------------------------------
    # 1. State Enum and Public Exceptions
    # ------------------------------------------------------------------
    def test_01_health_state_enum_exact_members(self):
        """HealthState has exactly 4 states: HEALTHY, RATE_LIMITED, SESSION_EXPIRED, BLOCKED_FALLBACK."""
        expected = ["HEALTHY", "RATE_LIMITED", "SESSION_EXPIRED", "BLOCKED_FALLBACK"]
        self.assertEqual([s.value for s in HealthState], expected)
        self.assertEqual(len(HealthState), 4)
        for name in expected:
            state = HealthState(name)
            self.assertIsInstance(state, str)
            self.assertIsInstance(state, HealthState)

        # Exception hierarchy
        self.assertTrue(issubclass(RateLimited, Exception))
        self.assertTrue(issubclass(SessionExpired, Exception))
        self.assertTrue(issubclass(Blocked, Exception))
        self.assertTrue(issubclass(SupervisorStopped, Exception))

    # ------------------------------------------------------------------
    # 2. RateLimited validation boundary attacks
    # ------------------------------------------------------------------
    def test_02_rate_limited_retry_after_validation(self):
        """RateLimited accepts only finite numbers >= 0, rejecting bools, NaN, Inf, negatives, strings."""
        # Default value is 60.0
        self.assertEqual(RateLimited().retry_after, 60.0)
        self.assertEqual(RateLimited(0).retry_after, 0.0)
        self.assertEqual(RateLimited(0.5).retry_after, 0.5)
        self.assertEqual(RateLimited(300).retry_after, 300.0)

        # Invalid values must raise ValueError
        invalid_values = [
            -1,
            -0.0001,
            -math.inf,
            math.nan,
            math.inf,
            True,   # bool is an instance of int in Python, must be explicitly rejected
            False,
            "60",
            "0",
            None,
            [],
            {},
        ]
        for bad in invalid_values:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    RateLimited(bad)

    # ------------------------------------------------------------------
    # 3. Supervisor initialization and no-side-effect contract
    # ------------------------------------------------------------------
    def test_03_supervisor_init_validation_and_no_side_effects(self):
        """Supervisor rejects empty or non-string source and produces valid snapshot without side-effects."""
        for bad_source in ("", "   ", "\t\n", None, 123, []):
            with self.subTest(bad_source=bad_source):
                with self.assertRaises(ValueError):
                    Supervisor(bad_source)

        active_threads_before = threading.active_count()
        clock = constant_clock(1700000000.0)
        sup = Supervisor("instagram", clock=clock)

        # No background threads must be spawned on creation
        self.assertEqual(threading.active_count(), active_threads_before)

        snap = sup.snapshot()
        self.assertEqual(snap["source"], "instagram")
        self.assertEqual(snap["state"], "HEALTHY")
        self.assertEqual(snap["updated_at"], 1700000000.0)
        self.assertIsNone(snap["retry_at"])
        self.assertEqual(snap["reason"], "init")

        # Snapshot must be JSON serializable
        serialized = json.dumps(snap)
        deserialized = json.loads(serialized)
        self.assertEqual(deserialized, snap)

    # ------------------------------------------------------------------
    # 4. Normal operation execution and state transition
    # ------------------------------------------------------------------
    def test_04_run_normal_success(self):
        """Successful operation returns result directly and transitions supervisor to HEALTHY / ok."""
        clock = constant_clock(100.0)
        sup = Supervisor("x", clock=clock)
        result = sup.run(lambda: {"status": "success", "count": 10})
        self.assertEqual(result, {"status": "success", "count": 10})

        snap = sup.snapshot()
        self.assertEqual(snap["state"], "HEALTHY")
        self.assertEqual(snap["reason"], "ok")
        self.assertIsNone(snap["retry_at"])

    # ------------------------------------------------------------------
    # 5. RateLimited retry limits and validation
    # ------------------------------------------------------------------
    def test_05_rate_limited_retry_bounds_and_invalid_max_retries(self):
        """RateLimited is retried up to max_retries with abortable wait, bounded without infinite loop."""
        sup = Supervisor("x")

        # Validation of max_retries: must be int >= 0, excluding bool
        for bad_retries in (True, False, -1, -5, 1.5, "3", None, []):
            with self.subTest(bad_retries=bad_retries):
                with self.assertRaises(ValueError):
                    sup.run(lambda: 1, max_retries=bad_retries)

        # max_retries = 0: fails immediately on 1st attempt, 0 waits, 1 total call
        clock = constant_clock(1000.0)
        sup0 = Supervisor("x", clock=clock)
        stop0 = MockStopEvent()
        op0 = make_call_sequence(RateLimited(30))
        with self.assertRaises(RateLimited):
            sup0.run(op0, stop=stop0, max_retries=0)
        self.assertEqual(len(op0.calls), 1)
        self.assertEqual(stop0.waits, [])
        self.assertEqual(sup0.snapshot()["state"], "RATE_LIMITED")
        self.assertEqual(sup0.snapshot()["retry_at"], 1030.0)

        # max_retries = 3: initial call + 3 retries = 4 calls total, 3 waits
        clock3 = constant_clock(2000.0)
        sup3 = Supervisor("x", clock=clock3)
        stop3 = MockStopEvent()
        op3 = make_call_sequence(RateLimited(15))
        with self.assertRaises(RateLimited):
            sup3.run(op3, stop=stop3, max_retries=3)
        self.assertEqual(len(op3.calls), 4)
        self.assertEqual(stop3.waits, [15.0, 15.0, 15.0])
        self.assertEqual(sup3.snapshot()["state"], "RATE_LIMITED")
        self.assertEqual(sup3.snapshot()["retry_at"], 2015.0)

        # Recovery on retry: fails 2 times, recovers on 3rd attempt
        clock_rec = constant_clock(3000.0)
        sup_rec = Supervisor("x", clock=clock_rec)
        stop_rec = MockStopEvent()
        op_rec = make_call_sequence(RateLimited(20), RateLimited(20), "recovered_data")
        res = sup_rec.run(op_rec, stop=stop_rec, max_retries=3)
        self.assertEqual(res, "recovered_data")
        self.assertEqual(len(op_rec.calls), 3)
        self.assertEqual(stop_rec.waits, [20.0, 20.0])
        self.assertEqual(sup_rec.snapshot()["state"], "HEALTHY")
        self.assertIsNone(sup_rec.snapshot()["retry_at"])
        self.assertEqual(sup_rec.snapshot()["reason"], "ok")

    # ------------------------------------------------------------------
    # 6. Stop signal semantics and Blocked fallback contrast
    # ------------------------------------------------------------------
    def test_06_stop_semantics_and_blocked_fallback_contrast(self):
        """Stop signal aborts before start, during wait, and contrasts behavior with Blocked."""
        clock = constant_clock(500.0)
        sup = Supervisor("x", clock=clock)

        # Preset stop: aborts immediately without invoking operation
        stop_preset = MockStopEvent(preset=True)
        op_never = make_call_sequence("ok")
        with self.assertRaises(SupervisorStopped):
            sup.run(op_never, stop=stop_preset)
        self.assertEqual(len(op_never.calls), 0)

        # Stop signaled during wait: raises SupervisorStopped, no further operation calls
        stop_mid = MockStopEvent(set_after_waits=1)
        op_mid = make_call_sequence(RateLimited(10), "ok")
        with self.assertRaises(SupervisorStopped):
            sup.run(op_mid, stop=stop_mid, max_retries=3)
        self.assertEqual(len(op_mid.calls), 1)

        # Operation directly raising SupervisorStopped: propagates as SupervisorStopped
        with self.assertRaises(SupervisorStopped):
            sup.run(make_call_sequence(SupervisorStopped()))

        # Stop during operation raising Blocked must abort immediately:
        # Must raise SupervisorStopped and MUST NOT execute fallback (fallback calls == 0)
        stop_contrast = MockStopEvent()
        fallback_invocations: list[int] = []

        def op_blocked_with_stop():
            stop_contrast.set()
            raise Blocked("Cloudflare challenge encountered")

        def fallback_target():
            fallback_invocations.append(1)
            return "fallback_result"

        with self.assertRaises(SupervisorStopped):
            sup.run(op_blocked_with_stop, stop=stop_contrast, fallback=fallback_target)
        self.assertEqual(fallback_invocations, [])
        self.assertTrue(stop_contrast.is_set())

    # ------------------------------------------------------------------
    # 7. SessionExpired immediate halt
    # ------------------------------------------------------------------
    def test_07_session_expired_halts_without_retry_or_fallback(self):
        """SessionExpired must immediately halt, without retry or fallback attempts."""
        clock = constant_clock(700.0)
        sup = Supervisor("x", clock=clock)
        stop = MockStopEvent()
        fb = make_call_sequence("fb")
        op = make_call_sequence(SessionExpired("SYNTHETIC_SESSION_COOKIE_EXPIRED"))

        with self.assertRaises(SessionExpired):
            sup.run(op, stop=stop, fallback=fb, max_retries=3)

        self.assertEqual(len(op.calls), 1)
        self.assertEqual(len(fb.calls), 0)
        self.assertEqual(stop.waits, [])
        self.assertEqual(sup.snapshot()["state"], "SESSION_EXPIRED")
        self.assertEqual(sup.snapshot()["reason"], "session_expired")

    # ------------------------------------------------------------------
    # 8. Blocked and fallback matrix
    # ------------------------------------------------------------------
    def test_08_blocked_and_fallback_execution_matrix(self):
        """Blocked invokes fallback once, keeps BLOCKED_FALLBACK on success, and handles fallback errors."""
        clock = constant_clock(800.0)
        sup = Supervisor("x", clock=clock)

        # Without fallback: raises Blocked directly, state becomes BLOCKED_FALLBACK
        with self.assertRaises(Blocked):
            sup.run(make_call_sequence(Blocked()))
        self.assertEqual(sup.snapshot()["state"], "BLOCKED_FALLBACK")
        self.assertEqual(sup.snapshot()["reason"], "blocked")

        # Successful fallback: returns result, remains in BLOCKED_FALLBACK mode
        fb_ok = make_call_sequence("edge_browser_content")
        op_blk = make_call_sequence(Blocked())
        res = sup.run(op_blk, fallback=fb_ok)
        self.assertEqual(res, "edge_browser_content")
        self.assertEqual(len(op_blk.calls), 1)
        self.assertEqual(len(fb_ok.calls), 1)
        self.assertEqual(sup.snapshot()["state"], "BLOCKED_FALLBACK")
        self.assertEqual(sup.snapshot()["reason"], "fallback_used")

        # Fallback raises generic exception: propagates, state BLOCKED_FALLBACK / fallback_error
        fb_err = make_call_sequence(RuntimeError("SYNTHETIC_FALLBACK_FAIL"))
        with self.assertRaises(RuntimeError):
            sup.run(make_call_sequence(Blocked()), fallback=fb_err)
        self.assertEqual(len(fb_err.calls), 1)
        self.assertEqual(sup.snapshot()["state"], "BLOCKED_FALLBACK")
        self.assertEqual(sup.snapshot()["reason"], "fallback_error")

        # Fallback raises RateLimited: transitions to RATE_LIMITED, no retry
        stop_fb_rate = MockStopEvent()
        fb_rate = make_call_sequence(RateLimited(40))
        with self.assertRaises(RateLimited):
            sup.run(make_call_sequence(Blocked()), stop=stop_fb_rate, fallback=fb_rate)
        self.assertEqual(len(fb_rate.calls), 1)
        self.assertEqual(stop_fb_rate.waits, [])
        self.assertEqual(sup.snapshot()["state"], "RATE_LIMITED")
        self.assertEqual(sup.snapshot()["reason"], "fallback_rate_limited")
        self.assertEqual(sup.snapshot()["retry_at"], 840.0)

        # Fallback raises SessionExpired: transitions to SESSION_EXPIRED, no retry
        fb_sess = make_call_sequence(SessionExpired())
        with self.assertRaises(SessionExpired):
            sup.run(make_call_sequence(Blocked()), fallback=fb_sess)
        self.assertEqual(len(fb_sess.calls), 1)
        self.assertEqual(sup.snapshot()["state"], "SESSION_EXPIRED")
        self.assertEqual(sup.snapshot()["reason"], "fallback_session_expired")

    # ------------------------------------------------------------------
    # 9. Generic exception and secret masking
    # ------------------------------------------------------------------
    def test_09_generic_exception_no_retry_and_secret_redaction(self):
        """Generic exceptions propagate without retry; raw secret tokens are not stored in snapshot/disk."""
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir, "test_secrets.json")
            sup = Supervisor("sec_source", state_path=state_file, clock=constant_clock(900.0))

            synthetic_secret = "SYNTHETIC_API_TOKEN_XYZ987654321_DO_NOT_LEAK"
            op = make_call_sequence(ValueError(f"Invalid auth: bearer={synthetic_secret}"))

            with self.assertRaises(ValueError) as ctx:
                sup.run(op)
            self.assertIn(synthetic_secret, str(ctx.exception))
            self.assertEqual(len(op.calls), 1)

            # Snapshot must use fixed code and exclude synthetic secret
            snap = sup.snapshot()
            self.assertEqual(snap["reason"], "operation_error")
            self.assertEqual(snap["state"], "HEALTHY")  # State remains unchanged
            serialized_snap = json.dumps(snap)
            self.assertNotIn(synthetic_secret, serialized_snap)

            # Saved disk file must not contain synthetic secret
            file_content = state_file.read_text(encoding="utf-8")
            self.assertNotIn(synthetic_secret, file_content)

    # ------------------------------------------------------------------
    # 10. Persistence roundtrip, corruption attacks, and source isolation
    # ------------------------------------------------------------------
    def test_10_persistence_roundtrip_corruption_attacks_and_source_isolation(self):
        """Atomic persistence preserves state, isolates sources, and safely rejects corrupted files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            file_a = Path(temp_dir, "source_a.json")
            file_b = Path(temp_dir, "source_b.json")

            sup_a = Supervisor("source_a", file_a, clock=constant_clock(100.0))
            sup_b = Supervisor("source_b", file_b, clock=constant_clock(100.0))

            # Trigger RateLimited on source_a
            stop = MockStopEvent()
            with self.assertRaises(RateLimited):
                sup_a.run(make_call_sequence(RateLimited(50)), stop=stop, max_retries=0)

            # Source isolation: source_b must remain completely HEALTHY
            self.assertEqual(sup_a.snapshot()["state"], "RATE_LIMITED")
            self.assertEqual(sup_b.snapshot()["state"], "HEALTHY")
            self.assertEqual(sup_b.run(lambda: "b_ok"), "b_ok")
            self.assertEqual(sup_b.snapshot()["state"], "HEALTHY")

            # Restore source_a from file
            sup_a_restored = Supervisor("source_a", file_a, clock=constant_clock(200.0))
            self.assertEqual(sup_a_restored.snapshot()["state"], "RATE_LIMITED")
            self.assertEqual(sup_a_restored.snapshot()["retry_at"], 150.0)
            self.assertEqual(sup_a_restored.snapshot()["reason"], "rate_limited")

            # Corruption attacks: file must not be overwritten when invalid
            valid_payload = file_a.read_text(encoding="utf-8")

            corrupt_payloads = [
                "{broken json",
                "[]",
                "\"string payload\"",
                json.dumps({"source": "source_a"}),  # missing keys
                json.dumps({
                    "source": "source_a",
                    "state": "HEALTHY",
                    "updated_at": 100.0,
                    "retry_at": None,
                    "reason": "ok",
                    "unexpected_key": "injected",
                }),  # extra keys
                json.dumps({
                    "source": "mismatched_source",
                    "state": "HEALTHY",
                    "updated_at": 100.0,
                    "retry_at": None,
                    "reason": "ok",
                }),  # source mismatch
                json.dumps({
                    "source": "source_a",
                    "state": "INVALID_STATE_5",
                    "updated_at": 100.0,
                    "retry_at": None,
                    "reason": "ok",
                }),  # invalid health state
                json.dumps({
                    "source": "source_a",
                    "state": "HEALTHY",
                    "updated_at": "not_a_number",
                    "retry_at": None,
                    "reason": "ok",
                }),  # string updated_at
                json.dumps({
                    "source": "source_a",
                    "state": "HEALTHY",
                    "updated_at": True,
                    "retry_at": None,
                    "reason": "ok",
                }),  # bool updated_at
                json.dumps({
                    "source": "source_a",
                    "state": "HEALTHY",
                    "updated_at": 100.0,
                    "retry_at": "not_a_number",
                    "reason": "ok",
                }),  # string retry_at
                json.dumps({
                    "source": "source_a",
                    "state": "HEALTHY",
                    "updated_at": 100.0,
                    "retry_at": True,
                    "reason": "ok",
                }),  # bool retry_at
                json.dumps({
                    "source": "source_a",
                    "state": "HEALTHY",
                    "updated_at": 100.0,
                    "retry_at": None,
                    "reason": None,
                }),  # non-string reason
                json.dumps({
                    "source": "source_a",
                    "state": "HEALTHY",
                    "updated_at": 100.0,
                    "retry_at": None,
                    "reason": 12345,
                }),  # numeric reason
            ]

            for idx, bad in enumerate(corrupt_payloads):
                with self.subTest(idx=idx):
                    file_a.write_text(bad, encoding="utf-8")
                    with self.assertRaises(ValueError) as cm:
                        Supervisor("source_a", file_a)
                    # Safe error: error message must not echo sensitive path or contents
                    self.assertNotIn(bad, str(cm.exception))
                    # File on disk must remain unchanged (not overwritten with default/init)
                    self.assertEqual(file_a.read_text(encoding="utf-8"), bad)

            # Restore original valid file
            file_a.write_text(valid_payload, encoding="utf-8")

            # Contract verification: arbitrary unapproved reason in state file must be rejected
            # Restoring a state file with an arbitrary reason code must raise ValueError and not overwrite file
            synthetic_unapproved_reason = "SYNTHETIC_UNAPPROVED_REASON"
            secret_reason_payload = json.dumps({
                "source": "source_a",
                "state": "HEALTHY",
                "updated_at": 100.0,
                "retry_at": None,
                "reason": synthetic_unapproved_reason,
            })
            file_a.write_text(secret_reason_payload, encoding="utf-8")
            with self.assertRaises(ValueError) as cm:
                Supervisor("source_a", file_a, clock=constant_clock(300.0))
            self.assertNotIn(synthetic_unapproved_reason, str(cm.exception))
            # Disk file must remain untouched
            self.assertEqual(file_a.read_text(encoding="utf-8"), secret_reason_payload)

    # ------------------------------------------------------------------
    # 11. Atomic replace failure clean up
    # ------------------------------------------------------------------
    def test_11_save_failure_cleans_temporary_files_and_raises(self):
        """Failure during atomic replace does not leave lingering temporary files and raises exception."""
        with tempfile.TemporaryDirectory() as temp_dir:
            state_file = Path(temp_dir, "test_atomic.json")
            sup = Supervisor("test_atomic", state_path=state_file, clock=constant_clock(100.0))

            with mock.patch("agents.base_supervisor.os.replace", side_effect=OSError("Disk write failed")):
                with self.assertRaises(OSError):
                    sup.run(lambda: "ok")

            # Must not leave any temporary (.tmp) files
            files_in_dir = list(Path(temp_dir).iterdir())
            tmp_files = [f for f in files_in_dir if f.name.endswith(".tmp")]
            self.assertEqual(tmp_files, [])


if __name__ == "__main__":
    unittest.main()
