"""T-006: 사용자 확정 기지식 5개, aliases, 합성 12개 분리 검증. 합성/임시 fixture만 사용."""

import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from core.analysis_schema import AnalysisResult, KnownConcepts, load_known_concepts

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "known_concepts.json"
GOLD = ROOT / "tests" / "blackbox" / "fixtures" / "gold_samples.json"

FIVE = ["환각", "프롬프트 엔지니어링", "컨텍스트 윈도우", "RAG", "임베딩"]
EXPECTED_ALIASES = {
    "환각": ["hallucination"],
    "프롬프트 엔지니어링": ["prompt engineering"],
    "컨텍스트 윈도우": ["context window"],
    "RAG": ["retrieval-augmented generation", "retrieval augmented generation", "검색 증강 생성"],
    "임베딩": ["embedding", "embeddings"],
}


def result(source_text, evidence, new):
    return AnalysisResult.model_validate({
        "schema_version": 1, "platform": "gallery", "post_id": "g-1", "track": "gallery",
        "status": "READY", "source_text": source_text, "hold_reason": None, "summary": [],
        "category": "practical_experiment",
        "tags": {"technical_form": [], "practicality": [], "difficulty": []},
        "event_id": None, "evidence_terms": evidence, "new_concepts_detected": new,
        "concept_usage": [], "actionable_idea": [], "is_pure_noise": False,
    })


def kc(**over):
    d = {"schema_version": 1, "provenance": "user_confirmed",
         "concepts": ["RAG", "임베딩"], "aliases": {"RAG": ["retrieval augmented generation"]}}
    d.update(over)
    return d


class UserConfigTests(unittest.TestCase):
    def test_exact_five_and_aliases(self):
        known = load_known_concepts(CONFIG)
        self.assertEqual(known.schema_version, 1)
        self.assertEqual(known.provenance, "user_confirmed")
        self.assertEqual(known.concepts, FIVE)
        self.assertEqual(known.aliases, EXPECTED_ALIASES)

    def test_roundtrip(self):
        known = load_known_concepts(CONFIG)
        self.assertEqual(KnownConcepts.model_validate_json(known.model_dump_json()), known)
        self.assertEqual(KnownConcepts.model_validate(json.loads(known.model_dump_json())), known)

    def test_load_is_read_only(self):
        before = CONFIG.read_bytes()
        mtime = CONFIG.stat().st_mtime_ns
        load_known_concepts(CONFIG)
        self.assertEqual(CONFIG.read_bytes(), before)
        self.assertEqual(CONFIG.stat().st_mtime_ns, mtime)
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "k.json"
            p.write_bytes(before)
            load_known_concepts(p)
            self.assertEqual([x.name for x in Path(tmp).iterdir()], ["k.json"])
            self.assertEqual(p.read_bytes(), before)


class NewConceptRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.known = load_known_concepts(CONFIG)

    def test_canonical_and_alias_rejected(self):
        terms = list(FIVE) + [a for v in EXPECTED_ALIASES.values() for a in v]
        terms += ["rag", "Hallucination", "  Embeddings ", "CONTEXT WINDOW", "Retrieval-Augmented Generation"]
        for t in terms:
            with self.subTest(term=t):
                r = result(f"{t.strip()} 설명", [t], [t])
                with self.assertRaises(ValueError):
                    r.validate_known_concepts(self.known)
                self.assertEqual(r.new_concepts_detected, [t])  # 출력값 불변

    def test_unselected_and_other_concepts_allowed(self):
        for t in ["파인튜닝", "MCP", "LoRA", "양자화", "에이전트 하네스", "fine-tuning",
                  "Model Context Protocol", "low-rank adaptation", "quantization",
                  "agent harness", "flash_attention"]:
            with self.subTest(term=t):
                r = result(f"{t} 설명", [t], [t])
                self.assertIsNone(r.validate_known_concepts(self.known))

    def test_unselected_not_in_known_keys(self):
        keys = self.known.known_keys()
        for t in ["파인튜닝", "mcp", "lora", "양자화", "에이전트 하네스", "fine-tuning",
                  "model context protocol", "low-rank adaptation", "quantization", "agent harness"]:
            self.assertNotIn(t, keys)

    def test_term_absent_from_source_rejected(self):
        with self.assertRaises(ValueError):
            result("전혀 다른 문장", ["양자화"], ["양자화"])

    def test_new_must_be_subset_of_evidence(self):
        with self.assertRaises(ValueError):
            result("양자화 설명", [], ["양자화"])

    def test_alias_in_evidence_only_is_fine(self):
        r = result("hallucination 과 양자화", ["hallucination", "양자화"], ["양자화"])
        self.assertIsNone(r.validate_known_concepts(self.known))


class SyntheticPreservedTests(unittest.TestCase):
    def test_gold_twelve_independent_model(self):
        gold = json.loads(GOLD.read_text(encoding="utf-8"))
        self.assertEqual(len(gold["known_concepts"]), 12)
        k = KnownConcepts.model_validate({
            "schema_version": 1, "provenance": "initial_synthetic_draft",
            "concepts": gold["known_concepts"]})
        self.assertEqual(k.aliases, {})
        with self.assertRaises(ValueError):
            result("lora 설명", ["lora"], ["lora"]).validate_known_concepts(k)
        self.assertIsNone(result("환각 설명", ["환각"], ["환각"]).validate_known_concepts(k))

    def test_empty_concepts_still_rejected(self):
        with self.assertRaises(ValidationError):
            KnownConcepts.model_validate(kc(concepts=[], aliases={}))


class AliasValidationTests(unittest.TestCase):
    def test_valid(self):
        k = KnownConcepts.model_validate(kc())
        self.assertEqual(k.aliases, {"RAG": ["retrieval augmented generation"]})
        self.assertEqual(KnownConcepts.model_validate(kc(aliases={})).aliases, {})

    def test_invalid(self):
        bad_cases = {
            "unknown key": {"LoRA": ["x"]},
            "key case differs": {"rag": ["x"]},
            "key blank": {" ": ["x"]},
            "value not list": {"RAG": "x"},
            "value int": {"RAG": 1},
            "empty list": {"RAG": []},
            "alias non-str": {"RAG": [1]},
            "alias blank": {"RAG": [" "]},
            "alias empty": {"RAG": [""]},
            "alias None": {"RAG": [None]},
            "dup in list": {"RAG": ["x", "X"]},
            "dup strip": {"RAG": ["x", " x "]},
            "same as own canonical": {"RAG": ["rag"]},
            "other canonical": {"RAG": ["임베딩"]},
            "cross dup": {"RAG": ["x"], "임베딩": ["X "]},
            "casefold ss": {"RAG": ["ß", "SS"]},
        }
        for name, aliases in bad_cases.items():
            with self.subTest(name):
                with self.assertRaises(ValueError):
                    KnownConcepts.model_validate(kc(aliases=aliases))

    def test_aliases_not_dict_and_extra_key(self):
        for bad in (["x"], "x", None, 1):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    KnownConcepts.model_validate(kc(aliases=bad))
        with self.assertRaises(ValueError):
            KnownConcepts.model_validate(kc(extra=1))

    def test_provenance_and_version_still_strict(self):
        for over in ({"provenance": "other"}, {"schema_version": 2}, {"schema_version": True}):
            with self.subTest(over=over):
                with self.assertRaises(ValueError):
                    KnownConcepts.model_validate(kc(**over))
        self.assertEqual(
            KnownConcepts.model_validate(kc(provenance="initial_synthetic_draft")).provenance,
            "initial_synthetic_draft")

    def test_load_rejects_bad_alias_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "k.json"
            p.write_text(json.dumps(kc(aliases={"nope": ["x"]})), encoding="utf-8")
            with self.assertRaises(ValidationError):
                load_known_concepts(p)


if __name__ == "__main__":
    unittest.main()
