"""Blackbox integration and regression tests for T-000 core/agents reorganization."""
import asyncio
import gc
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

import core.common
import core.media_store
import core.post_processing
import core.source_manager
import core.source_tools
import core.store
import agents
import agents.gallery_agent
import agents.github_agent
import agents.huggingface_agent
import agents.instagram_agent
import agents.news_agent
import agents.source_agents
import agents.x_agent
import agents.youtube_agent

import github_agent
import media_store
import post_processing
import raider
import source_agents
import source_manager
import source_tools


class BlackboxStructureTests(unittest.TestCase):
    def test_01_standalone_imports_and_alias_identity(self):
        """core/ and agents/ submodules are independently importable and root wrappers are exact aliases."""
        self.assertIs(source_manager, core.source_manager)
        self.assertIs(source_tools, core.source_tools)
        self.assertIs(source_agents, agents.source_agents)
        self.assertIs(github_agent, agents.github_agent)
        self.assertIs(media_store, core.media_store)
        self.assertIs(post_processing, core.post_processing)

        # Check re-exports on raider
        self.assertTrue(issubclass(raider.Store, core.store.Store))
        self.assertIs(raider.Registry, core.source_manager.Registry)
        self.assertIs(raider.Processor, core.post_processing.Processor)
        self.assertIs(raider.SourceAgent, agents.source_agents.SourceAgent)
        self.assertIs(raider.GithubAgent, agents.github_agent.GithubAgent)
        self.assertIs(raider.ROOT, core.common.ROOT)
        self.assertIs(raider.DATA, core.common.DATA)
        self.assertIs(raider.PRIVATE, core.common.PRIVATE)
        self.assertIs(raider.Cancelled, agents.Cancelled)

        # Monkeypatch on alias affects underlying module
        with patch.object(source_agents, "ADAPTERS", dict(source_agents.ADAPTERS)):
            source_agents.ADAPTERS["__test_dummy__"] = True
            self.assertIn("__test_dummy__", agents.source_agents.ADAPTERS)

    def test_02_root_and_paths_integrity(self):
        """ROOT points to the repository root and resource directories exist under ROOT, not inside core/."""
        self.assertEqual(core.common.ROOT.resolve(), ROOT.resolve())
        self.assertTrue((core.common.ROOT / "web" / "index.html").is_file())
        self.assertTrue((core.common.ROOT / "web" / "sources.html").is_file())
        self.assertTrue((core.common.ROOT / "web" / "github.html").is_file())
        self.assertTrue((core.common.ROOT / "config" / "sources.json").is_file())
        self.assertFalse((core.common.ROOT / "core" / "web").exists())
        self.assertFalse((core.common.ROOT / "core" / "config").exists())

    def test_03_store_interface_and_fixture_null_preservation(self):
        """Store provides all required methods; empty text and null metrics are preserved across re-saves."""
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test.sqlite"
            st = core.store.Store(db_path)

            # Contract methods presence
            for method in ("connect", "save", "create_run", "tasks", "task", "run_state", "rows"):
                self.assertTrue(callable(getattr(st, method, None)), f"Missing method {method}")

            fixture = dict(
                platform="instagram",
                post_id="fixture",
                handle="test",
                url="https://example.com/p",
                posted_at="2026-08-08T15:00:00+00:00",
                text="",
                metrics={"likes": None},
                media=[],
                raw={},
            )

            # First save
            st.save(fixture)
            res1 = st.rows()
            self.assertEqual(res1["total"], 1)
            self.assertEqual(len(res1["items"]), 1)
            item1 = res1["items"][0]
            self.assertEqual(item1["text"], "")
            self.assertIsNone(item1["metrics"]["likes"])
            self.assertNotEqual(item1["metrics"]["likes"], 0)

            # Re-save identical post
            st.save(fixture)
            res2 = st.rows()
            self.assertEqual(res2["total"], 1)
            item2 = res2["items"][0]
            self.assertEqual(item2["text"], "")
            self.assertIsNone(item2["metrics"]["likes"])
            self.assertNotEqual(item2["metrics"]["likes"], 0)

    def test_04_window_kst_boundaries(self):
        """window('2026-08-09','2026-11-09') with now=2026-11-11 UTC yields exact UTC boundaries."""
        fixed_now = datetime(2026, 11, 11, 0, 0, 0, tzinfo=timezone.utc)
        with patch("raider.now", return_value=fixed_now):
            begin, finish = raider.window("2026-08-09", "2026-11-09")

            expected_begin = datetime(2026, 8, 8, 15, 0, 0, tzinfo=timezone.utc)
            expected_finish = datetime(2026, 11, 9, 15, 0, 0, tzinfo=timezone.utc)
            self.assertEqual(begin, expected_begin)
            self.assertEqual(finish, expected_finish)
            self.assertEqual(begin.isoformat(), "2026-08-08T15:00:00+00:00")
            self.assertEqual(finish.isoformat(), "2026-11-09T15:00:00+00:00")

            # Boundary membership checks: [begin, finish)
            one_sec = timedelta(seconds=1)
            # Before begin
            self.assertFalse(begin <= (expected_begin - one_sec) < finish)
            # Exactly at begin
            self.assertTrue(begin <= expected_begin < finish)
            # Just before finish
            self.assertTrue(begin <= (expected_finish - one_sec) < finish)
            # Exactly at finish
            self.assertFalse(begin <= expected_finish < finish)
            # After finish
            self.assertFalse(begin <= (expected_finish + one_sec) < finish)

            # Invalid range raises ValueError
            with self.assertRaises(ValueError):
                raider.window("2026-11-10", "2026-11-09")

    def test_05_resume_deduplication_and_skip_completed(self):
        """Interrupted run skips completed tasks on resume and re-fetching posts does not cause duplicates."""
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "raider.sqlite"
            st = raider.Store(db_path)
            runner = raider.Runner(st)

            begin = datetime(2026, 8, 8, 15, 0, 0, tzinfo=timezone.utc)
            finish = datetime(2026, 8, 10, 15, 0, 0, tzinfo=timezone.utc)
            accounts = [
                {"platform": "instagram", "handle": "acc1"},
                {"platform": "instagram", "handle": "acc2"},
            ]
            run_id = st.create_run(accounts, begin, finish)
            tasks = st.tasks(run_id)
            self.assertEqual(len(tasks), 2)

            task1, task2 = tasks[0], tasks[1]

            # Simulate task1 already finished (queried) with 1 post
            st.save(dict(
                platform=task1["platform"],
                post_id="p1",
                handle=task1["handle"],
                url="https://example.com/p1",
                posted_at="2026-08-09T00:00:00+00:00",
                text="acc1 post",
                metrics={},
                media=[],
                raw={},
            ))
            st.task(task1, "queried", 1, "completed earlier")

            # Mock instagram generator to track which tasks are run
            executed_tasks = []
            def fake_instagram(task, b, f, stop):
                executed_tasks.append(task["handle"])
                # Also yield p1 again to test deduplication across tasks
                yield dict(
                    platform=task["platform"],
                    post_id="p1",
                    handle=task["handle"],
                    url="https://example.com/p1",
                    posted_at="2026-08-09T00:00:00+00:00",
                    text="acc1 post re-collected",
                    metrics={},
                    media=[],
                    raw={},
                )
                yield dict(
                    platform=task["platform"],
                    post_id="p2",
                    handle=task["handle"],
                    url="https://example.com/p2",
                    posted_at="2026-08-09T01:00:00+00:00",
                    text="acc2 post",
                    metrics={},
                    media=[],
                    raw={},
                )

            with patch("raider.instagram", fake_instagram):
                runner.work(run_id)

            # Task 1 was skipped because it was already 'queried'
            self.assertNotIn("acc1", executed_tasks)
            self.assertIn("acc2", executed_tasks)

            # Verify deduplication: p1 was re-collected, total posts must be 2 (p1 and p2), not 3
            res = st.rows()
            self.assertEqual(res["total"], 2)
            ids = {r["post_id"] for r in res["items"]}
            self.assertEqual(ids, {"p1", "p2"})

    def test_06_mock_error_and_rate_limit_redaction(self):
        """Mock collector rate limit / error records safe status without leaking sensitive credentials."""
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "raider.sqlite"
            st = raider.Store(db_path)
            runner = raider.Runner(st)

            begin = datetime(2026, 8, 8, 15, 0, 0, tzinfo=timezone.utc)
            finish = datetime(2026, 8, 10, 15, 0, 0, tzinfo=timezone.utc)
            accounts = [{"platform": "instagram", "handle": "leak_test"}]
            run_id = st.create_run(accounts, begin, finish)

            SECRET_TOKEN = "SUPER_SECRET_SESSION_TOKEN_XYZ987"
            def error_instagram(task, b, f, stop):
                raise RuntimeError(f"Rate limited 429: bearer {SECRET_TOKEN}")

            with patch("raider.instagram", error_instagram):
                runner.work(run_id)

            tasks = st.tasks(run_id)
            self.assertEqual(len(tasks), 1)
            t = tasks[0]
            self.assertEqual(t["state"], "error")
            # Must NOT contain the secret token
            self.assertNotIn(SECRET_TOKEN, t["message"])
            self.assertIn("RuntimeError", t["message"])

    def test_07_large_payload_and_scale(self):
        """Large text and multi-post volume are stored and retrieved without truncation."""
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "raider.sqlite"
            st = core.store.Store(db_path)

            # Generate large body: 50,000 characters
            large_text = ("AI Raider Blackbox Scale Test Payload Line with unicode 한국어 테스트 \n" * 1000)
            text_size = len(large_text)
            self.assertGreater(text_size, 50000)

            post_count = 100
            start_time = time.perf_counter()

            for i in range(post_count):
                st.save(dict(
                    platform="instagram",
                    post_id=f"large_post_{i:04d}",
                    handle="scale_tester",
                    url=f"https://example.com/p/{i}",
                    posted_at="2026-08-08T15:00:00+00:00",
                    text=large_text if i % 10 == 0 else f"Short text {i}",
                    metrics={"likes": i * 10},
                    media=[],
                    raw={"index": i, "extra": "x" * 500},
                ))

            save_duration = time.perf_counter() - start_time

            # Query all posts
            query_start = time.perf_counter()
            res = st.rows(limit=post_count + 10)
            query_duration = time.perf_counter() - query_start

            self.assertEqual(res["total"], post_count)
            self.assertEqual(len(res["items"]), post_count)

            # Verify large post intact without truncation
            large_items = [item for item in res["items"] if item["post_id"] == "large_post_0000"]
            self.assertEqual(len(large_items), 1)
            self.assertEqual(len(large_items[0]["text"]), text_size)
            self.assertEqual(large_items[0]["text"], large_text)

            print(f"\n[Scale Test Benchmark] {post_count} posts ({text_size} chars per large post): "
                  f"save={save_duration:.3f}s, query={query_duration:.3f}s")


if __name__ == "__main__":
    unittest.main()
