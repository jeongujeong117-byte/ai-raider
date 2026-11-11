"""Blackbox verification test suite for synthetic gold standard samples."""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

import core.common
import core.store
import raider

FIXTURE_PATH = ROOT / "tests" / "blackbox" / "fixtures" / "gold_samples.json"


class GoldSamplesBlackboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
            cls.fixture_data = json.load(f)
        cls.samples = cls.fixture_data["samples"]
        cls.samples_by_id = {s["id"]: s for s in cls.samples}

    def test_01_schema_conformance_and_identifiers(self):
        """Fixture adheres to schema version 1, has >=12 samples with unique IDs, synthetic provenance, and example.com URLs."""
        self.assertEqual(self.fixture_data.get("schema_version"), 1)
        self.assertIsInstance(self.fixture_data.get("known_concepts"), list)
        self.assertGreater(len(self.fixture_data["known_concepts"]), 0)

        self.assertGreaterEqual(len(self.samples), 12)
        seen_ids = set()

        for s in self.samples:
            s_id = s["id"]
            self.assertNotIn(s_id, seen_ids, f"Duplicate sample id: {s_id}")
            seen_ids.add(s_id)

            self.assertTrue(s["description"].strip())
            self.assertEqual(s["provenance"], "synthetic")
            self.assertIsInstance(s["tags"], list)
            self.assertGreater(len(s["tags"]), 0)

            # Contract check for input dict
            inp = s["input"]
            for required_field in ("platform", "post_id", "handle", "url", "posted_at", "text", "metrics", "media", "raw"):
                self.assertIn(required_field, inp, f"Missing {required_field} in input for {s_id}")

            # Verify only reserved example URLs are used
            self.assertIn("example.com", inp["url"])

            # Verify dedup_key separation
            exp = s["expected"]
            self.assertIn("dedup_key", exp)
            expected_dedup = f"{inp['platform']}:{inp['post_id']}"
            self.assertEqual(exp["dedup_key"], expected_dedup)
            self.assertNotEqual(s_id, exp["dedup_key"], f"Sample id should distinguish itself from dedup_key: {s_id}")

    def test_02_all_seven_platforms_present(self):
        """All 7 target platforms are represented in the gold samples."""
        required_platforms = {"instagram", "x", "youtube", "news", "gallery", "huggingface", "github"}
        present_platforms = {s["input"]["platform"] for s in self.samples}
        self.assertEqual(required_platforms, present_platforms)

    def test_03_store_null_vs_zero_metrics(self):
        """Store preserves metrics likes=None without coercing to 0, and preserves likes=0 without coercing to None."""
        sample_null = self.samples_by_id["sample-ig-null-likes"]
        sample_zero = self.samples_by_id["sample-ig-zero-likes"]

        with tempfile.TemporaryDirectory() as td:
            st = core.store.Store(Path(td) / "test.sqlite")
            st.save(sample_null["input"])
            st.save(sample_zero["input"])

            rows = st.rows(platform="instagram")
            self.assertEqual(rows["total"], 2)

            item_null = next(r for r in rows["items"] if r["post_id"] == sample_null["input"]["post_id"])
            item_zero = next(r for r in rows["items"] if r["post_id"] == sample_zero["input"]["post_id"])

            self.assertIsNone(item_null["metrics"]["likes"])
            self.assertNotEqual(item_null["metrics"]["likes"], 0)

            self.assertEqual(item_zero["metrics"]["likes"], 0)
            self.assertIsNotNone(item_zero["metrics"]["likes"])

    def test_04_store_empty_text_with_media(self):
        """Store preserves empty caption text while retaining media attachments."""
        sample = self.samples_by_id["sample-x-empty-text-media"]

        with tempfile.TemporaryDirectory() as td:
            st = core.store.Store(Path(td) / "test.sqlite")
            st.save(sample["input"])

            rows = st.rows(platform="x")
            self.assertEqual(rows["total"], 1)
            item = rows["items"][0]

            self.assertEqual(item["text"], "")
            self.assertEqual(item["text"], sample["expected"]["stored_text"])
            self.assertEqual(len(item["media"]), 1)
            self.assertEqual(item["media"][0]["kind"], "image")

    def test_05_store_recollect_deduplication_and_update(self):
        """Identical (platform, post_id) across separate sample entries updates existing row without duplicate record."""
        orig = self.samples_by_id["sample-recollect-original"]
        updated = self.samples_by_id["sample-recollect-updated"]

        self.assertNotEqual(orig["id"], updated["id"])
        self.assertEqual(orig["expected"]["dedup_key"], updated["expected"]["dedup_key"])

        with tempfile.TemporaryDirectory() as td:
            st = core.store.Store(Path(td) / "test.sqlite")

            # First crawl
            st.save(orig["input"])
            res1 = st.rows(platform="huggingface")
            self.assertEqual(res1["total"], 1)
            self.assertEqual(res1["items"][0]["text"], orig["expected"]["stored_text"])
            self.assertEqual(res1["items"][0]["metrics"]["likes"], 15)

            # Re-collection crawl with updated payload
            st.save(updated["input"])
            res2 = st.rows(platform="huggingface")
            self.assertEqual(res2["total"], 1, "Deduplication must prevent duplicate row creation")
            self.assertEqual(res2["items"][0]["text"], updated["expected"]["stored_text"])
            self.assertEqual(res2["items"][0]["metrics"]["likes"], 50)

    def test_06_large_unicode_payload_expansion(self):
        """Large unicode payload expanded via repeat_spec stores and retrieves without truncation or corruption."""
        sample = self.samples_by_id["sample-github-large-unicode"]
        repeat_spec = sample["input"]["repeat_spec"]

        expanded_text = repeat_spec["base_text"] * repeat_spec["repeat_count"]
        self.assertGreaterEqual(len(expanded_text), sample["expected"]["expanded_min_length"])

        post_payload = dict(sample["input"])
        post_payload["text"] = expanded_text

        with tempfile.TemporaryDirectory() as td:
            st = core.store.Store(Path(td) / "test.sqlite")
            st.save(post_payload)

            res = st.rows(platform="github")
            self.assertEqual(res["total"], 1)
            item = res["items"][0]

            self.assertEqual(len(item["text"]), len(expanded_text))
            self.assertEqual(item["text"], expanded_text)
            self.assertIn("🚀", item["text"])
            self.assertIn("유니코드", item["text"])

    def test_07_kst_window_boundary_classification(self):
        """Samples at 2026-08-09 00:00 KST boundary (1s before, exact, 1s after) evaluate accurately against raider.window."""
        fixed_now = datetime(2026, 11, 11, 0, 0, 0, tzinfo=timezone.utc)
        with patch("raider.now", return_value=fixed_now):
            begin, finish = raider.window("2026-08-09", "2026-11-09")

            # 2026-08-09 00:00:00 KST is 2026-08-08 15:00:00 UTC
            self.assertEqual(begin.isoformat(), "2026-08-08T15:00:00+00:00")

            sample_before = self.samples_by_id["sample-boundary-before-kst"]
            sample_exact = self.samples_by_id["sample-boundary-exact-kst"]
            sample_after = self.samples_by_id["sample-boundary-after-kst"]

            dt_before = datetime.fromisoformat(sample_before["input"]["posted_at"])
            dt_exact = datetime.fromisoformat(sample_exact["input"]["posted_at"])
            dt_after = datetime.fromisoformat(sample_after["input"]["posted_at"])

            in_window_before = (begin <= dt_before < finish)
            in_window_exact = (begin <= dt_exact < finish)
            in_window_after = (begin <= dt_after < finish)

            self.assertEqual(in_window_before, sample_before["expected"]["in_window"])
            self.assertFalse(in_window_before, "1 second before window start must evaluate to False")

            self.assertEqual(in_window_exact, sample_exact["expected"]["in_window"])
            self.assertTrue(in_window_exact, "Exact window start boundary must evaluate to True")

            self.assertEqual(in_window_after, sample_after["expected"]["in_window"])
            self.assertTrue(in_window_after, "1 second after window start must evaluate to True")

    def test_08_mock_collector_rate_limit_error_masking(self):
        """Rate limit error simulation masks sensitive credentials from recorded task status."""
        sample = self.samples_by_id["sample-rate-limit-error"]
        sim_err = sample["input"]["simulated_error"]

        with tempfile.TemporaryDirectory() as td:
            st = raider.Store(Path(td) / "test.sqlite")
            runner = raider.Runner(st)

            begin = datetime(2026, 9, 15, 0, 0, 0, tzinfo=timezone.utc)
            finish = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
            run_id = st.create_run([{"platform": sample["input"]["platform"], "handle": sample["input"]["handle"]}], begin, finish)

            async def fake_x_collector(task, b, f, stop):
                raise RuntimeError(sim_err["raw_message"])
                yield {}  # generator

            with patch("raider.x_posts", fake_x_collector):
                runner.work(run_id)

            tasks = st.tasks(run_id)
            self.assertEqual(len(tasks), 1)
            task = tasks[0]

            self.assertEqual(task["state"], sample["expected"]["error_state"])
            self.assertNotIn(sample["expected"]["redact_token"], task["message"])
            self.assertIn("RuntimeError", task["message"])

    def test_09_future_analysis_ground_truth_contract(self):
        """expected.analysis ground truth contracts link evidence strictly to source text without hallucinating tech in chatter."""
        known_concepts = set(self.fixture_data["known_concepts"])

        for s in self.samples:
            analysis = s["expected"].get("analysis")
            self.assertIsNotNone(analysis, f"Sample {s['id']} must define expected.analysis")
            self.assertIn("category", analysis)
            self.assertIn("evidence_terms", analysis)
            self.assertIn("is_pure_noise", analysis)

            evidence = analysis["evidence_terms"]
            if analysis["is_pure_noise"]:
                self.assertEqual(evidence, [], f"Pure noise sample {s['id']} must not claim evidence terms")
            else:
                inp_text = s["input"]["text"]
                raw_transcript = s["input"].get("raw", {}).get("transcript", "")
                media_ocr = " ".join(m.get("ocr_text", "") for m in s["input"].get("media", []))
                combined = f"{inp_text} {raw_transcript} {media_ocr}".lower()

                for term in evidence:
                    self.assertIn(term.lower(), combined,
                                  f"Evidence term '{term}' in {s['id']} must be grounded in source text, transcript, or OCR")

        # Specific checks on chatter samples
        chatter_with_tech = self.samples_by_id["sample-chatter-with-tech-grounding"]
        self.assertFalse(chatter_with_tech["expected"]["analysis"]["is_pure_noise"])
        self.assertIn("transformer", chatter_with_tech["expected"]["analysis"]["evidence_terms"])

        pure_noise = self.samples_by_id["sample-pure-chatter-noise"]
        self.assertTrue(pure_noise["expected"]["analysis"]["is_pure_noise"])
        self.assertEqual(pure_noise["expected"]["analysis"]["evidence_terms"], [])

    def test_10_media_ocr_and_transcription_fixtures(self):
        """Samples containing transcription and OCR data retain media details through Store interface."""
        yt_sample = self.samples_by_id["sample-youtube-transcription"]
        news_sample = self.samples_by_id["sample-news-ocr"]

        with tempfile.TemporaryDirectory() as td:
            st = core.store.Store(Path(td) / "test.sqlite")
            st.save(yt_sample["input"])
            st.save(news_sample["input"])

            yt_row = st.rows(platform="youtube")["items"][0]
            news_row = st.rows(platform="news")["items"][0]

            self.assertIn("transcript", yt_row["raw"])
            self.assertIn("RAG", yt_row["raw"]["transcript"])
            self.assertEqual(yt_row["media"][0]["kind"], "video")

            self.assertEqual(len(news_row["media"]), 1)
            self.assertIn("ocr_text", news_row["media"][0])
            self.assertIn("NPU", news_row["media"][0]["ocr_text"])


if __name__ == "__main__":
    unittest.main()
