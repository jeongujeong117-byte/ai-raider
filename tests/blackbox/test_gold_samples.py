"""Blackbox verification test suite for synthetic gold standard samples."""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

import core.common
import core.store
import raider

FIXTURE_PATH = ROOT / "tests" / "blackbox" / "fixtures" / "gold_samples.json"

RESERVED_EXAMPLE_DOMAINS = {"example.com", "example.org", "example.net"}


def is_valid_reserved_example_url(url: str) -> bool:
    """Validate that a URL strictly uses an RFC 2606 reserved example domain.

    Rejects substring bypasses such as example.com.evil.invalid or evil.com/?q=example.com.
    """
    if not isinstance(url, str) or not url.strip():
        return False
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return False
    hostname = parts.hostname
    if not hostname:
        return False
    hostname = hostname.lower()
    return hostname in RESERVED_EXAMPLE_DOMAINS or any(
        hostname.endswith("." + base) for base in RESERVED_EXAMPLE_DOMAINS
    )


class GoldSamplesBlackboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
            cls.fixture_data = json.load(f)
        cls.samples = cls.fixture_data["samples"]
        cls.samples_by_id = {s["id"]: s for s in cls.samples}
        cls.known_concepts = set(cls.fixture_data["known_concepts"])

    def test_01_schema_conformance_and_identifiers(self):
        """Fixture adheres to schema version 1, has >=12 samples with unique IDs, synthetic provenance, and valid reserved URLs."""
        self.assertEqual(self.fixture_data.get("schema_version"), 1)
        self.assertIsInstance(self.fixture_data.get("known_concepts"), list)
        self.assertGreater(len(self.known_concepts), 0)

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

            inp = s["input"]
            for required_field in ("platform", "post_id", "handle", "url", "posted_at", "text", "metrics", "media", "raw"):
                self.assertIn(required_field, inp, f"Missing {required_field} in input for {s_id}")

            # Strict reserved example URL validation for post URL and all media URLs
            self.assertTrue(
                is_valid_reserved_example_url(inp["url"]),
                f"Post URL {inp['url']} in sample {s_id} is not a valid reserved example domain URL"
            )
            for m in inp.get("media", []):
                if "url" in m:
                    self.assertTrue(
                        is_valid_reserved_example_url(m["url"]),
                        f"Media URL {m['url']} in sample {s_id} is not a valid reserved example domain URL"
                    )

            # Verify dedup_key separation
            exp = s["expected"]
            self.assertIn("dedup_key", exp)
            expected_dedup = f"{inp['platform']}:{inp['post_id']}"
            self.assertEqual(exp["dedup_key"], expected_dedup)
            self.assertNotEqual(s_id, exp["dedup_key"], f"Sample id should distinguish itself from dedup_key: {s_id}")

    def test_02_reserved_url_validator_and_negative_cases(self):
        """URL validation allows RFC 2606 domains and rejects substring/query bypasses."""
        valid_urls = [
            "https://example.com/post/1",
            "http://example.com",
            "https://sub.example.com/media.jpg",
            "https://api.example.org/feed",
            "http://cdn.example.net/video.mp4",
        ]
        for url in valid_urls:
            self.assertTrue(is_valid_reserved_example_url(url), f"Expected valid: {url}")

        invalid_urls = [
            "https://example.com.evil.invalid/path",
            "https://evil.com/?target=example.com",
            "https://notexample.com/feed",
            "https://fake-example.com/asset",
            "http://user:pass@attacker.com#example.com",
            "ftp://example.com/file",
            "javascript:alert('xss')",
            "",
            None,
        ]
        for url in invalid_urls:
            self.assertFalse(is_valid_reserved_example_url(url), f"Expected invalid: {url}")

    def test_03_all_seven_platforms_present(self):
        """All 7 target platforms are represented in the gold samples."""
        required_platforms = {"instagram", "x", "youtube", "news", "gallery", "huggingface", "github"}
        present_platforms = {s["input"]["platform"] for s in self.samples}
        self.assertEqual(required_platforms, present_platforms)

    def test_04_all_samples_expected_contract_consistency(self):
        """All samples with declared expected values (preserve_null_metrics, expected_likes, stored_text, in_window) are strictly verified across fixture."""
        fixed_now = datetime(2026, 11, 11, 0, 0, 0, tzinfo=timezone.utc)
        with patch("raider.now", return_value=fixed_now):
            begin, finish = raider.window("2026-08-09", "2026-11-09")

        # 1. Verify in_window across all samples with type checks
        for s in self.samples:
            exp = s["expected"]
            if "in_window" in exp:
                self.assertIs(type(exp["in_window"]), bool, f"in_window in {s['id']} must be bool")
                dt = datetime.fromisoformat(s["input"]["posted_at"])
                computed_in_window = (begin <= dt < finish)
                self.assertEqual(
                    computed_in_window,
                    exp["in_window"],
                    f"Sample {s['id']} in_window mismatch: computed={computed_in_window}, expected={exp['in_window']}"
                )

        # 2. Verify Store contracts across all standard samples (excluding special scale/error/recollect-updated)
        standard_samples = [
            s for s in self.samples
            if "repeat_spec" not in s["input"]
            and "simulated_error" not in s["input"]
            and not s["expected"].get("overwrites_previous", False)
        ]
        self.assertGreaterEqual(len(standard_samples), 10)

        with tempfile.TemporaryDirectory() as td:
            st = core.store.Store(Path(td) / "test.sqlite")
            for s in standard_samples:
                st.save(s["input"])

            for s in standard_samples:
                inp = s["input"]
                exp = s["expected"]
                s_id = s["id"]

                rows = st.rows(platform=inp["platform"])
                matches = [r for r in rows["items"] if r["post_id"] == inp["post_id"]]
                self.assertEqual(len(matches), 1, f"Expected exactly 1 row for {s_id}")
                row = matches[0]

                # stored_text check
                if "stored_text" in exp:
                    self.assertIs(type(exp["stored_text"]), str)
                    self.assertIs(type(row["text"]), str)
                    self.assertEqual(row["text"], exp["stored_text"], f"stored_text mismatch in {s_id}")

                # preserve_null_metrics and expected_likes check
                if "preserve_null_metrics" in exp:
                    self.assertIs(type(exp["preserve_null_metrics"]), bool)
                    likes_val = row["metrics"].get("likes")

                    if exp["preserve_null_metrics"]:
                        self.assertIsNone(likes_val, f"Likes must be None in {s_id}")
                        self.assertIsNone(exp.get("expected_likes"), f"expected_likes must be None when preserve_null_metrics is True in {s_id}")
                    else:
                        self.assertIsNotNone(likes_val, f"Likes must not be None in {s_id}")
                        self.assertIsNot(likes_val, False, f"Likes in {s_id} must not be False")
                        expected_likes = exp.get("expected_likes")
                        self.assertIs(type(expected_likes), int, f"expected_likes must be int in {s_id}")
                        self.assertIsNot(expected_likes, False, f"expected_likes must not be boolean False in {s_id}")
                        self.assertEqual(likes_val, expected_likes, f"Likes mismatch in {s_id}")

                # dedup_key match
                self.assertEqual(f"{row['platform']}:{row['post_id']}", exp["dedup_key"])

    def test_05_store_null_vs_zero_metrics(self):
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
            self.assertIsNot(item_zero["metrics"]["likes"], False)

    def test_06_store_empty_text_with_media(self):
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

    def test_07_store_recollect_deduplication_and_update(self):
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

    def test_08_large_unicode_payload_expansion(self):
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

    def test_09_kst_window_boundary_classification(self):
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

    def test_10_mock_collector_rate_limit_error_masking(self):
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
                yield {}

            with patch("raider.x_posts", fake_x_collector):
                runner.work(run_id)

            tasks = st.tasks(run_id)
            self.assertEqual(len(tasks), 1)
            task = tasks[0]

            self.assertEqual(task["state"], sample["expected"]["error_state"])
            self.assertNotIn(sample["expected"]["redact_token"], task["message"])
            self.assertIn("RuntimeError", task["message"])

    def test_11_future_analysis_ground_truth_and_known_concepts_consistency(self):
        """expected.analysis ground truth contracts link evidence strictly to source text, verify new_concepts_detected against known_concepts, and bind applied usage."""
        for s in self.samples:
            analysis = s["expected"].get("analysis")
            self.assertIsNotNone(analysis, f"Sample {s['id']} must define expected.analysis")
            self.assertIn("category", analysis)
            self.assertIn("evidence_terms", analysis)
            self.assertIn("new_concepts_detected", analysis)
            self.assertIn("is_pure_noise", analysis)

            evidence = analysis["evidence_terms"]
            new_detected = analysis["new_concepts_detected"]

            if analysis["is_pure_noise"]:
                self.assertEqual(evidence, [], f"Pure noise sample {s['id']} must not claim evidence terms")
                self.assertEqual(new_detected, [], f"Pure noise sample {s['id']} must not claim new concepts")
            else:
                inp_text = s["input"]["text"]
                raw_transcript = s["input"].get("raw", {}).get("transcript", "")
                media_ocr = " ".join(m.get("ocr_text", "") for m in s["input"].get("media", []))
                combined = f"{inp_text} {raw_transcript} {media_ocr}".lower()

                # Verify all evidence terms are grounded in source text/transcript/OCR
                for term in evidence:
                    self.assertIn(term.lower(), combined,
                                  f"Evidence term '{term}' in {s['id']} must be grounded in source text, transcript, or OCR")

                    # Verify known_concepts non-membership consistency
                    if term.lower() in self.known_concepts:
                        self.assertNotIn(
                            term, new_detected,
                            f"Term '{term}' in {s['id']} is in known_concepts, must not be in new_concepts_detected"
                        )
                    else:
                        self.assertIn(
                            term, new_detected,
                            f"Term '{term}' in {s['id']} is not in known_concepts, must be listed in new_concepts_detected"
                        )

                # Verify each new_concept_detected is actually in evidence_terms and NOT in known_concepts
                for new_concept in new_detected:
                    self.assertIn(new_concept, evidence, f"New concept '{new_concept}' in {s['id']} must be part of evidence_terms")
                    self.assertNotIn(
                        new_concept.lower(), self.known_concepts,
                        f"New concept '{new_concept}' in {s['id']} must not exist in known_concepts dictionary"
                    )

            # Check applied_usage binding when present (e.g. practical ideas in chatter)
            applied_usage = analysis.get("applied_usage")
            if applied_usage:
                self.assertFalse(analysis["is_pure_noise"], f"Applied usage sample {s['id']} cannot be pure noise")
                self.assertIsInstance(applied_usage, str)
                self.assertGreater(len(applied_usage.strip()), 0)
                # Verify that key terms from applied_usage are grounded in the source text
                grounded_word_found = any(word.lower() in inp_text.lower() for word in applied_usage.split() if len(word) > 1)
                self.assertTrue(grounded_word_found, f"Applied usage '{applied_usage}' in {s['id']} must be grounded in source text")

        # Specific sanity checks on known vs new concepts
        chatter_tech = self.samples_by_id["sample-chatter-with-tech-grounding"]
        self.assertIn("transformer", chatter_tech["expected"]["analysis"]["evidence_terms"])
        self.assertIn("어텐션", chatter_tech["expected"]["analysis"]["new_concepts_detected"])
        self.assertEqual(chatter_tech["expected"]["analysis"]["applied_usage"], "transformer 어텐션 메커니즘 코드를 실습")

        idea_sample = self.samples_by_id["sample-x-new-concept-and-idea"]
        self.assertIn("flash_attention", idea_sample["expected"]["analysis"]["new_concepts_detected"])
        self.assertIn("agent", idea_sample["expected"]["analysis"]["evidence_terms"])
        self.assertNotIn("agent", idea_sample["expected"]["analysis"]["new_concepts_detected"])

        pure_noise = self.samples_by_id["sample-pure-chatter-noise"]
        self.assertTrue(pure_noise["expected"]["analysis"]["is_pure_noise"])
        self.assertEqual(pure_noise["expected"]["analysis"]["new_concepts_detected"], [])

    def test_12_media_ocr_and_transcription_fixtures(self):
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
