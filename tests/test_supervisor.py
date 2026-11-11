import json
import tempfile
import threading
import unittest
from unittest import mock
from pathlib import Path

from agents.base_supervisor import (
    Blocked,
    HealthState,
    RateLimited,
    SessionExpired,
    Supervisor,
    SupervisorStopped,
)


class FakeStop:
    """Event-compatible stub: records waits, never really sleeps."""

    def __init__(self, set_on_wait=None, preset=False):
        self.waits = []
        self._set = preset
        self._set_on_wait = set_on_wait

    def is_set(self):
        return self._set

    def wait(self, seconds=None):
        self.waits.append(seconds)
        if self._set_on_wait is not None and len(self.waits) >= self._set_on_wait:
            self._set = True
        return self._set


def clock_at(t=1000.0):
    return lambda: t


def seq(*items):
    """operation returning/raising items in order; counts calls."""
    calls = []

    def op():
        i = len(calls)
        calls.append(1)
        item = items[min(i, len(items) - 1)]
        if isinstance(item, BaseException):
            raise item
        return item

    op.calls = calls
    return op


class SupervisorTests(unittest.TestCase):
    def test_states_exact(self):
        self.assertEqual(
            [s.value for s in HealthState],
            ["HEALTHY", "RATE_LIMITED", "SESSION_EXPIRED", "BLOCKED_FALLBACK"],
        )

    def test_init_and_validation(self):
        s = Supervisor("x", clock=clock_at())
        snap = s.snapshot()
        json.dumps(snap)
        self.assertEqual(snap["state"], "HEALTHY")
        self.assertIsNone(snap["retry_at"])
        for bad in ("", "  ", None, 3):
            with self.assertRaises(ValueError):
                Supervisor(bad)
        for bad in (-1, float("nan"), float("inf"), True, "5"):
            with self.assertRaises(ValueError):
                RateLimited(bad)
        self.assertEqual(RateLimited().retry_after, 60)
        for bad in (-1, True, 1.5, "1"):
            with self.assertRaises(ValueError):
                s.run(lambda: 1, max_retries=bad)

    def test_success(self):
        s = Supervisor("x", clock=clock_at())
        self.assertEqual(s.run(lambda: 42), 42)
        self.assertEqual(s.snapshot()["state"], "HEALTHY")

    def test_rate_limited_recovers(self):
        s = Supervisor("x", clock=clock_at(1000))
        stop = FakeStop()
        op = seq(RateLimited(30), "ok")
        self.assertEqual(s.run(op, stop=stop), "ok")
        self.assertEqual(stop.waits, [30.0])
        self.assertEqual(s.snapshot()["state"], "HEALTHY")
        self.assertIsNone(s.snapshot()["retry_at"])

    def test_rate_limited_records_retry_at_and_limit(self):
        s = Supervisor("x", clock=clock_at(1000))
        stop = FakeStop()
        op = seq(RateLimited(30))
        with self.assertRaises(RateLimited):
            s.run(op, stop=stop, max_retries=3)
        self.assertEqual(len(op.calls), 4)
        self.assertEqual(len(stop.waits), 3)
        snap = s.snapshot()
        self.assertEqual(snap["state"], "RATE_LIMITED")
        self.assertEqual(snap["retry_at"], 1030.0)

    def test_max_retries_zero(self):
        s = Supervisor("x", clock=clock_at())
        stop = FakeStop()
        op = seq(RateLimited(1))
        with self.assertRaises(RateLimited):
            s.run(op, stop=stop, max_retries=0)
        self.assertEqual(len(op.calls), 1)
        self.assertEqual(stop.waits, [])
        self.assertEqual(s.snapshot()["state"], "RATE_LIMITED")

    def test_stop_before_start(self):
        s = Supervisor("x", clock=clock_at())
        op = seq("ok")
        with self.assertRaises(SupervisorStopped):
            s.run(op, stop=FakeStop(preset=True))
        self.assertEqual(op.calls, [])
        ev = threading.Event()
        ev.set()
        with self.assertRaises(SupervisorStopped):
            s.run(op, stop=ev)
        self.assertEqual(op.calls, [])

    def test_stop_during_wait(self):
        s = Supervisor("x", clock=clock_at())
        stop = FakeStop(set_on_wait=1)
        op = seq(RateLimited(5), "ok")
        with self.assertRaises(SupervisorStopped):
            s.run(op, stop=stop)
        self.assertEqual(len(op.calls), 1)

    def test_session_expired_no_retry(self):
        s = Supervisor("x", clock=clock_at())
        stop = FakeStop()
        fb = seq("fb")
        op = seq(SessionExpired("cookie=SECRET"))
        with self.assertRaises(SessionExpired):
            s.run(op, stop=stop, fallback=fb)
        self.assertEqual(len(op.calls), 1)
        self.assertEqual(fb.calls, [])
        self.assertEqual(stop.waits, [])
        self.assertEqual(s.snapshot()["state"], "SESSION_EXPIRED")

    def test_blocked_fallback_once(self):
        s = Supervisor("x", clock=clock_at())
        fb = seq("fb")
        op = seq(Blocked())
        self.assertEqual(s.run(op, fallback=fb), "fb")
        self.assertEqual(len(op.calls), 1)
        self.assertEqual(len(fb.calls), 1)
        self.assertEqual(s.snapshot()["state"], "BLOCKED_FALLBACK")

    def test_blocked_without_or_failing_fallback(self):
        s = Supervisor("x", clock=clock_at())
        with self.assertRaises(Blocked):
            s.run(seq(Blocked()))
        self.assertEqual(s.snapshot()["state"], "BLOCKED_FALLBACK")
        fb = seq(RuntimeError("token=SECRET"))
        with self.assertRaises(RuntimeError):
            s.run(seq(Blocked()), fallback=fb)
        self.assertEqual(len(fb.calls), 1)
        self.assertEqual(s.snapshot()["state"], "BLOCKED_FALLBACK")
        self.assertNotIn("SECRET", json.dumps(s.snapshot()))

    def test_fallback_rate_limited_and_session(self):
        stop = FakeStop()
        s = Supervisor("x", clock=clock_at(10))
        fb = seq(RateLimited(5))
        with self.assertRaises(RateLimited):
            s.run(seq(Blocked()), stop=stop, fallback=fb)
        self.assertEqual(len(fb.calls), 1)
        self.assertEqual(stop.waits, [])
        self.assertEqual(s.snapshot()["state"], "RATE_LIMITED")
        self.assertEqual(s.snapshot()["retry_at"], 15.0)
        fb2 = seq(SessionExpired())
        with self.assertRaises(SessionExpired):
            s.run(seq(Blocked()), fallback=fb2)
        self.assertEqual(len(fb2.calls), 1)
        self.assertEqual(s.snapshot()["state"], "SESSION_EXPIRED")

    def test_generic_error_no_retry_no_secret(self):
        s = Supervisor("x", clock=clock_at())
        op = seq(ValueError("password=SECRET"))
        with self.assertRaises(ValueError):
            s.run(op)
        self.assertEqual(len(op.calls), 1)
        snap = s.snapshot()
        self.assertEqual(snap["reason"], "operation_error")
        self.assertNotIn("SECRET", json.dumps(snap))
        self.assertIn(snap["state"], {x.value for x in HealthState})

    def test_persistence_roundtrip_and_isolation(self):
        with tempfile.TemporaryDirectory() as d:
            pa, pb = Path(d, "a.json"), Path(d, "b.json")
            a = Supervisor("a", pa, clock=clock_at(100))
            b = Supervisor("b", pb, clock=clock_at(100))
            with self.assertRaises(SessionExpired):
                a.run(seq(SessionExpired("secret-token")))
            self.assertEqual(b.snapshot()["state"], "HEALTHY")
            self.assertEqual(b.run(lambda: 1), 1)
            a2 = Supervisor("a", pa, clock=clock_at(200))
            self.assertEqual(a2.snapshot()["state"], "SESSION_EXPIRED")
            self.assertEqual(a2.snapshot(), json.loads(pa.read_text("utf-8")))
            self.assertNotIn("secret-token", pa.read_text("utf-8"))
            self.assertEqual(sorted(p.name for p in Path(d).iterdir()), ["a.json", "b.json"])

    def test_corrupt_and_mismatch_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "s.json")
            Supervisor("a", p, clock=clock_at()).run(lambda: 1)
            with self.assertRaises(ValueError) as cm:
                Supervisor("other", p)
            self.assertNotIn(str(p), str(cm.exception))
            good = p.read_text("utf-8")
            self.assertEqual(p.read_text("utf-8"), good)
            for bad in ("{not json", "[]", json.dumps({"source": "a"}),
                        json.dumps({"source": "a", "state": "WEIRD", "updated_at": 1,
                                    "retry_at": None, "reason": "x"})):
                p.write_text(bad, encoding="utf-8")
                with self.assertRaises(ValueError):
                    Supervisor("a", p)
                self.assertEqual(p.read_text("utf-8"), bad)

    def test_stop_set_by_operation_skips_fallback(self):
        s = Supervisor("x", clock=clock_at())
        ev = threading.Event()
        fb = seq("fb")

        def op():
            ev.set()
            raise Blocked()

        with self.assertRaises(SupervisorStopped):
            s.run(op, stop=ev, fallback=fb)
        self.assertEqual(fb.calls, [])

    def test_unknown_reason_rejected_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "s.json")
            bad = json.dumps({"source": "a", "state": "HEALTHY", "updated_at": 1,
                              "retry_at": None, "reason": "token=SECRET"})
            p.write_text(bad, encoding="utf-8")
            with self.assertRaises(ValueError) as cm:
                Supervisor("a", p)
            self.assertNotIn("SECRET", str(cm.exception))
            self.assertEqual(p.read_text("utf-8"), bad)

    def test_save_failure_not_hidden_and_tmp_cleaned(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "s.json")
            s = Supervisor("a", p, clock=clock_at())
            with mock.patch("agents.base_supervisor.os.replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    s.run(lambda: 1)
            self.assertEqual(list(Path(d).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
