"""Blackbox verification test suite for T-006: User-confirmed known concepts with aliases.

Independent validation of:
- Exact canonical 5 concepts and exact aliases in config/known_concepts.json
- Model validation of KnownConcepts (provenance, schema_version, concepts, aliases)
- Strip+casefold duplicate, collision, and cross-conflict attacks
- Strict int/bool coercion rejection and extra field forbidding
- validate_known_concepts rejection of both canonical and alias surface forms
- Allowance of unselected concepts (파인튜닝, MCP, LoRA, 양자화, 에이전트 하네스) and others
- Preservation of grounding and subset integrity rules
- Complete separation and preservation of synthetic gold 12 concepts
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

from pydantic import ValidationError

from core.analysis_schema import AnalysisResult, KnownConcepts, load_known_concepts

CONFIG_PATH = ROOT / "config" / "known_concepts.json"
GOLD_PATH = ROOT / "tests" / "blackbox" / "fixtures" / "gold_samples.json"

EXPECTED_CANONICAL = [
    "환각",
    "프롬프트 엔지니어링",
    "컨텍스트 윈도우",
    "RAG",
    "임베딩",
]

EXPECTED_ALIASES = {
    "환각": ["hallucination"],
    "프롬프트 엔지니어링": ["prompt engineering"],
    "컨텍스트 윈도우": ["context window"],
    "RAG": [
        "retrieval-augmented generation",
        "retrieval augmented generation",
        "검색 증강 생성",
    ],
    "임베딩": ["embedding", "embeddings"],
}

UNSELECTED_CONCEPTS = [
    "파인튜닝",
    "MCP",
    "LoRA",
    "양자화",
    "에이전트 하네스",
    "fine-tuning",
    "Model Context Protocol",
    "low-rank adaptation",
    "quantization",
    "agent harness",
]


def _build_analysis_result(
    source_text: str,
    evidence_terms: list[str],
    new_concepts_detected: list[str],
    **overrides,
) -> AnalysisResult:
    payload = {
        "schema_version": 1,
        "platform": "instagram",
        "post_id": "test-t006-001",
        "track": "standard",
        "status": "READY",
        "source_text": source_text,
        "hold_reason": None,
        "summary": ["첫째 줄 요약.", "둘째 줄 요약.", "셋째 줄 요약."],
        "category": "ai-research",
        "tags": {
            "technical_form": ["guide"],
            "practicality": ["high"],
            "difficulty": ["intermediate"],
        },
        "event_id": None,
        "evidence_terms": evidence_terms,
        "new_concepts_detected": new_concepts_detected,
        "concept_usage": [f"{t} 활용 예시" for t in evidence_terms],
        "actionable_idea": ["실무 적용 아이디어"],
        "is_pure_noise": False,
    }
    payload.update(overrides)
    return AnalysisResult.model_validate(payload)


def _base_known_dict(**overrides) -> dict:
    base = {
        "schema_version": 1,
        "provenance": "user_confirmed",
        "concepts": list(EXPECTED_CANONICAL),
        "aliases": copy.deepcopy(EXPECTED_ALIASES),
    }
    base.update(overrides)
    return base


class KnownConceptsBlackboxTests(unittest.TestCase):
    """Adversarial blackbox test suite for T-006 known concepts and aliases."""

    def test_01_canonical_config_exact_five_and_provenance(self):
        """config/known_concepts.json must have schema_version=1, provenance='user_confirmed',

        exactly 5 canonical concepts, and strictly defined aliases.
        """
        self.assertTrue(CONFIG_PATH.exists(), f"Config file not found at {CONFIG_PATH}")
        known = load_known_concepts(CONFIG_PATH)

        self.assertEqual(known.schema_version, 1)
        self.assertEqual(known.provenance, "user_confirmed")
        self.assertEqual(known.concepts, EXPECTED_CANONICAL)
        self.assertEqual(len(known.concepts), 5)
        self.assertEqual(known.aliases, EXPECTED_ALIASES)

        # Unselected concepts must NOT be present in concepts, aliases, or known_keys
        keys = known.known_keys()
        for term in UNSELECTED_CONCEPTS:
            self.assertNotIn(term, known.concepts)
            self.assertNotIn(term, known.aliases)
            self.assertNotIn(term.strip().casefold(), keys)

    def test_02_load_known_concepts_read_only_and_file_immutability(self):
        """load_known_concepts must be strictly read-only and never mutate files."""
        orig_bytes = CONFIG_PATH.read_bytes()
        orig_hash = hashlib.sha256(orig_bytes).hexdigest()

        kc = load_known_concepts(CONFIG_PATH)
        self.assertIsNotNone(kc)

        after_bytes = CONFIG_PATH.read_bytes()
        after_hash = hashlib.sha256(after_bytes).hexdigest()
        self.assertEqual(orig_hash, after_hash)

        # Non-existent file raises FileNotFoundError without creating file
        missing_path = ROOT / "config" / "non_existent_file_t006.json"
        self.assertFalse(missing_path.exists())
        with self.assertRaises(FileNotFoundError):
            load_known_concepts(missing_path)
        self.assertFalse(missing_path.exists())

        # Empty file and malformed JSON raise ValidationError / Decode error
        with tempfile.TemporaryDirectory() as tmpdir:
            empty_file = Path(tmpdir) / "empty.json"
            empty_file.write_text("", encoding="utf-8")
            with self.assertRaises(Exception):
                load_known_concepts(empty_file)

            malformed_file = Path(tmpdir) / "bad.json"
            malformed_file.write_text("{not valid json", encoding="utf-8")
            with self.assertRaises(Exception):
                load_known_concepts(malformed_file)

    def test_03_dict_and_json_roundtrip_unicode_immutability(self):
        """Dict model_validate and JSON model_validate_json must preserve exact casing and unicode."""
        d = _base_known_dict()
        m_from_dict = KnownConcepts.model_validate(d)
        json_str = m_from_dict.model_dump_json()
        m_from_json = KnownConcepts.model_validate_json(json_str)

        self.assertEqual(m_from_dict.concepts, m_from_json.concepts)
        self.assertEqual(m_from_dict.aliases, m_from_json.aliases)
        self.assertEqual(m_from_dict.provenance, m_from_json.provenance)

        # Original hangul and unicode surface preserved
        self.assertEqual(m_from_json.concepts[0], "환각")
        self.assertEqual(m_from_json.aliases["RAG"][2], "검색 증강 생성")

    def test_04_provenance_strictness_and_attack(self):
        """provenance accepts only 'user_confirmed' and 'initial_synthetic_draft'."""
        # Valid provenances
        for prov in ("user_confirmed", "initial_synthetic_draft"):
            kc = KnownConcepts.model_validate(_base_known_dict(provenance=prov))
            self.assertEqual(kc.provenance, prov)
            kc_json = KnownConcepts.model_validate_json(
                json.dumps(_base_known_dict(provenance=prov))
            )
            self.assertEqual(kc_json.provenance, prov)

        # Invalid provenances rejected in both dict and JSON
        bad_provenances = [
            "user_verified",
            "synthetic",
            "initial_synthetic",
            "confirmed",
            "draft",
            "",
            "   ",
            None,
            123,
            True,
            False,
        ]
        for bad in bad_provenances:
            with self.subTest(bad_provenance=bad):
                with self.assertRaises((ValidationError, ValueError)):
                    KnownConcepts.model_validate(_base_known_dict(provenance=bad))
                with self.assertRaises((ValidationError, ValueError)):
                    KnownConcepts.model_validate_json(
                        json.dumps(_base_known_dict(provenance=bad))
                    )

    def test_05_schema_version_strict_int_and_bool_coercion_attack(self):
        """schema_version must strictly accept int 1 and reject bool True/False, float, str."""
        valid = KnownConcepts.model_validate(_base_known_dict(schema_version=1))
        self.assertEqual(valid.schema_version, 1)

        bad_versions = [True, False, 1.0, 0, 2, -1, "1", "1.0", None]
        for bad in bad_versions:
            with self.subTest(bad_version=bad):
                with self.assertRaises((ValidationError, ValueError)):
                    KnownConcepts.model_validate(_base_known_dict(schema_version=bad))
                with self.assertRaises((ValidationError, ValueError)):
                    KnownConcepts.model_validate_json(
                        json.dumps(_base_known_dict(schema_version=bad))
                    )

    def test_06_concepts_list_attack_matrix(self):
        """concepts must be a non-empty list of non-blank unique strings (strip+casefold)."""
        # Empty concepts list rejected
        with self.assertRaises(ValidationError):
            KnownConcepts.model_validate(_base_known_dict(concepts=[]))

        # Blank / whitespace elements rejected
        for bad_elem in ("", "   ", "\t\r\n"):
            with self.subTest(bad_elem=repr(bad_elem)):
                with self.assertRaises(ValidationError):
                    KnownConcepts.model_validate(_base_known_dict(concepts=["환각", bad_elem]))

        # Non-string elements rejected
        for bad_type in (1, None, True, ["nested"], {"k": "v"}):
            with self.subTest(bad_type=bad_type):
                with self.assertRaises((ValidationError, TypeError)):
                    KnownConcepts.model_validate(_base_known_dict(concepts=["환각", bad_type]))

        # Duplicate attacks under strip+casefold
        dup_cases = [
            ["환각", "환각"],
            ["환각", " 환각 "],
            ["RAG", "rag"],
            ["RAG", " RAG "],
            ["ß", "SS"],
        ]
        for dups in dup_cases:
            with self.subTest(dups=dups):
                with self.assertRaises(ValueError):
                    KnownConcepts.model_validate(_base_known_dict(concepts=dups, aliases={}))

    def test_07_aliases_optional_backward_compatibility_and_extra_fields(self):
        """aliases defaults to {} when omitted (past synthetic draft JSON compatibility).

        extra fields must be strictly forbidden.
        """
        # Omitted aliases defaults to {}
        d = {
            "schema_version": 1,
            "provenance": "initial_synthetic_draft",
            "concepts": ["transformer", "agent"],
        }
        kc = KnownConcepts.model_validate(d)
        self.assertEqual(kc.aliases, {})

        # Explicit aliases={} accepted
        kc_explicit = KnownConcepts.model_validate({**d, "aliases": {}})
        self.assertEqual(kc_explicit.aliases, {})

        # Extra fields forbidden
        with self.assertRaises(ValidationError):
            KnownConcepts.model_validate({**d, "extra_field": "unwanted"})

        with self.assertRaises(ValidationError):
            KnownConcepts.model_validate_json(
                json.dumps({**d, "unknown_metadata": {"author": "admin"}})
            )

        # Non-dict aliases rejected
        for bad_aliases in ([], "invalid", 123, None, True):
            with self.subTest(bad_aliases=bad_aliases):
                with self.assertRaises(ValidationError):
                    KnownConcepts.model_validate(_base_known_dict(aliases=bad_aliases))

    def test_08_aliases_key_attack_matrix(self):
        """canonical key in aliases must strictly match an existing element in concepts."""
        base_concepts = ["환각", "RAG"]

        # Key not in concepts
        with self.assertRaises(ValueError):
            KnownConcepts.model_validate({
                "schema_version": 1,
                "provenance": "user_confirmed",
                "concepts": base_concepts,
                "aliases": {"LoRA": ["low-rank adaptation"]},
            })

        # Key casing differs from concept (e.g. 'rag' vs 'RAG')
        with self.assertRaises(ValueError):
            KnownConcepts.model_validate({
                "schema_version": 1,
                "provenance": "user_confirmed",
                "concepts": base_concepts,
                "aliases": {"rag": ["retrieval augmented generation"]},
            })

        # Key with whitespace padding
        with self.assertRaises(ValueError):
            KnownConcepts.model_validate({
                "schema_version": 1,
                "provenance": "user_confirmed",
                "concepts": base_concepts,
                "aliases": {" RAG ": ["retrieval augmented generation"]},
            })

        # Blank or empty key
        with self.assertRaises((ValidationError, ValueError)):
            KnownConcepts.model_validate({
                "schema_version": 1,
                "provenance": "user_confirmed",
                "concepts": base_concepts,
                "aliases": {"": ["x"]},
            })

    def test_09_aliases_value_attack_matrix(self):
        """aliases values must be a non-empty list of non-blank strict strings."""
        base_concepts = ["환각", "RAG"]

        # Value not a list
        for bad_val in ("str", 123, None, {"k": "v"}, True):
            with self.subTest(bad_val=bad_val):
                with self.assertRaises(ValidationError):
                    KnownConcepts.model_validate({
                        "schema_version": 1,
                        "provenance": "user_confirmed",
                        "concepts": base_concepts,
                        "aliases": {"RAG": bad_val},
                    })

        # Empty list rejected (S0 decision: meaningless entries rejected)
        with self.assertRaises(ValidationError):
            KnownConcepts.model_validate({
                "schema_version": 1,
                "provenance": "user_confirmed",
                "concepts": base_concepts,
                "aliases": {"RAG": []},
            })

        # Non-string element in list
        for bad_elem in (123, None, True, ["nested"]):
            with self.subTest(bad_elem=bad_elem):
                with self.assertRaises((ValidationError, TypeError)):
                    KnownConcepts.model_validate({
                        "schema_version": 1,
                        "provenance": "user_confirmed",
                        "concepts": base_concepts,
                        "aliases": {"RAG": [bad_elem]},
                    })

        # Blank or whitespace-only element in list
        for bad_str in ("", "   ", "\t\r\n"):
            with self.subTest(bad_str=repr(bad_str)):
                with self.assertRaises(ValidationError):
                    KnownConcepts.model_validate({
                        "schema_version": 1,
                        "provenance": "user_confirmed",
                        "concepts": base_concepts,
                        "aliases": {"RAG": [bad_str]},
                    })

    def test_10_aliases_collision_and_duplicate_matrix(self):
        """Aliases must not conflict with canonicals or duplicate within/across lists."""
        base_concepts = ["환각", "RAG"]

        conflict_cases = {
            "duplicate within same alias list": {
                "RAG": ["retrieval", "retrieval"]
            },
            "strip+casefold duplicate within same alias list": {
                "RAG": ["retrieval", " RETRIEVAL "]
            },
            "alias collides with own canonical": {
                "RAG": ["rag"]
            },
            "alias collides with own canonical with whitespace": {
                "RAG": [" RAG "]
            },
            "alias collides with another canonical": {
                "RAG": ["환각"]
            },
            "alias collides with another canonical casefolded": {
                "환각": ["rag"]
            },
            "cross-canonical alias duplicate": {
                "환각": ["common_term"],
                "RAG": ["common_term"],
            },
            "cross-canonical alias duplicate strip+casefold": {
                "환각": ["common_term"],
                "RAG": [" COMMON_TERM "],
            },
            "unicode sharp S casefold collision with alias": {
                "RAG": ["ß", "SS"]
            },
            "unicode sharp S cross-canonical collision": {
                "환각": ["ß"],
                "RAG": ["SS"],
            },
        }

        for name, bad_aliases in conflict_cases.items():
            with self.subTest(conflict_type=name):
                with self.assertRaises(ValueError):
                    KnownConcepts.model_validate({
                        "schema_version": 1,
                        "provenance": "user_confirmed",
                        "concepts": base_concepts,
                        "aliases": bad_aliases,
                    })

    def test_11_validate_known_concepts_canonical_and_alias_rejection(self):
        """validate_known_concepts must reject both canonical and alias surface forms,

        including casefold and whitespace variants, while preserving string immutability.
        """
        known = load_known_concepts(CONFIG_PATH)

        # 1. Canonical terms must be rejected
        for canonical in EXPECTED_CANONICAL:
            with self.subTest(canonical=canonical):
                res = _build_analysis_result(
                    source_text=f"문맥 속 {canonical} 설명입니다.",
                    evidence_terms=[canonical],
                    new_concepts_detected=[canonical],
                )
                with self.assertRaises(ValueError):
                    res.validate_known_concepts(known)
                # Output string immutability check
                self.assertEqual(res.new_concepts_detected, [canonical])

        # 2. Alias terms must be rejected
        all_aliases = [
            alias
            for alias_list in EXPECTED_ALIASES.values()
            for alias in alias_list
        ]
        for alias in all_aliases:
            with self.subTest(alias=alias):
                res = _build_analysis_result(
                    source_text=f"This post discusses {alias} in AI models.",
                    evidence_terms=[alias],
                    new_concepts_detected=[alias],
                )
                with self.assertRaises(ValueError):
                    res.validate_known_concepts(known)
                self.assertEqual(res.new_concepts_detected, [alias])

        # 3. Case and whitespace variants must be rejected
        variants = [
            "HALLUCINATION",
            "  hallucination  ",
            "rag",
            " RAG ",
            "Context Window",
            "EMBEDDING",
            "Embeddings",
            "검색 증강 생성",
            "  환각  ",
        ]
        for var in variants:
            with self.subTest(variant=var):
                res = _build_analysis_result(
                    source_text=f"Testing variant: {var} in source.",
                    evidence_terms=[var],
                    new_concepts_detected=[var],
                )
                with self.assertRaises(ValueError):
                    res.validate_known_concepts(known)
                self.assertEqual(res.new_concepts_detected, [var])

    def test_12_unselected_and_unregistered_concepts_allowed_as_new(self):
        """Unselected concepts (파인튜닝, MCP, LoRA, 양자화, 에이전트 하네스) and other

        unregistered terms with source grounding MUST be accepted as new concepts.
        """
        known = load_known_concepts(CONFIG_PATH)

        test_terms = list(UNSELECTED_CONCEPTS) + [
            "flash_attention",
            "MoE",
            "KV cache",
            "스펙큘레이티브 디코딩",
        ]

        for term in test_terms:
            with self.subTest(allowed_term=term):
                res = _build_analysis_result(
                    source_text=f"새로운 기술 소개: {term} 기법 분석.",
                    evidence_terms=[term],
                    new_concepts_detected=[term],
                )
                # validate_known_concepts must return None (not raise)
                self.assertIsNone(res.validate_known_concepts(known))

    def test_13_grounding_and_subset_integrity_preserved(self):
        """Terms in new_concepts_detected must exist in source_text and be a subset of evidence_terms.

        Known concepts present in evidence_terms only are valid.
        """
        known = load_known_concepts(CONFIG_PATH)

        # Term absent from source_text rejected by AnalysisResult model validation
        with self.assertRaises(ValueError):
            _build_analysis_result(
                source_text="이 문장에는 인공지능 언급만 있습니다.",
                evidence_terms=["양자화"],
                new_concepts_detected=["양자화"],
            )

        # Term in new_concepts_detected but not in evidence_terms rejected
        with self.assertRaises(ValueError):
            _build_analysis_result(
                source_text="양자화 기술 설명입니다.",
                evidence_terms=[],
                new_concepts_detected=["양자화"],
            )

        # Known concept in evidence_terms only is completely fine
        # e.g., source mentions hallucination and quantization; only quantization is new
        res = _build_analysis_result(
            source_text="hallucination 발생 시 양자화 모델의 거동 분석.",
            evidence_terms=["hallucination", "양자화"],
            new_concepts_detected=["양자화"],
        )
        self.assertIsNone(res.validate_known_concepts(known))
        self.assertEqual(res.evidence_terms, ["hallucination", "양자화"])
        self.assertEqual(res.new_concepts_detected, ["양자화"])

    def test_14_synthetic_gold_twelve_independent_preservation(self):
        """Synthetic gold standard 12 concepts in fixtures/gold_samples.json must remain

        strictly intact, separated from config, and functional under initial_synthetic_draft.
        """
        self.assertTrue(GOLD_PATH.exists())
        with open(GOLD_PATH, "r", encoding="utf-8") as f:
            gold_data = json.load(f)

        gold_concepts = gold_data["known_concepts"]
        self.assertEqual(len(gold_concepts), 12)
        expected_twelve = [
            "transformer", "lora", "agent", "ocr", "asr", "diffusion",
            "fine-tuning", "rag", "vector_db", "npu", "vit", "checkpoint"
        ]
        self.assertEqual(gold_concepts, expected_twelve)

        # Model instantiation with synthetic provenance
        synth_model = KnownConcepts.model_validate({
            "schema_version": 1,
            "provenance": "initial_synthetic_draft",
            "concepts": gold_concepts,
        })
        self.assertEqual(synth_model.aliases, {})

        # Under synthetic model: 'lora' is known (rejected as new), '환각' is unknown (allowed as new)
        res_lora = _build_analysis_result(
            source_text="LoRA 어댑터 튜닝 설명.",
            evidence_terms=["LoRA"],
            new_concepts_detected=["LoRA"],
        )
        with self.assertRaises(ValueError):
            res_lora.validate_known_concepts(synth_model)

        res_hallucination = _build_analysis_result(
            source_text="환각 현상 분석.",
            evidence_terms=["환각"],
            new_concepts_detected=["환각"],
        )
        self.assertIsNone(res_hallucination.validate_known_concepts(synth_model))

        # Under user config: '환각' is known (rejected as new), 'lora' is unknown (allowed as new)
        user_known = load_known_concepts(CONFIG_PATH)
        self.assertIsNone(res_lora.validate_known_concepts(user_known))
        with self.assertRaises(ValueError):
            res_hallucination.validate_known_concepts(user_known)

    def test_15_large_unicode_payload_and_stress_resistance(self):
        """Resilience against 20,000+ character Korean text, emojis, and unicode symbols."""
        known = load_known_concepts(CONFIG_PATH)

        repeated_body = "딥러닝 파인튜닝 양자화 기법 🚀🤖⚡ " * 500
        full_text = f"서두 요약: {repeated_body} 신기술: 스펙큘레이티브 디코딩 기법 소개."

        res = _build_analysis_result(
            source_text=full_text,
            evidence_terms=["스펙큘레이티브 디코딩"],
            new_concepts_detected=["스펙큘레이티브 디코딩"],
        )
        self.assertIsNone(res.validate_known_concepts(known))

        # JSON roundtrip of large AnalysisResult
        dumped = res.model_dump_json()
        loaded = AnalysisResult.model_validate_json(dumped)
        self.assertEqual(loaded.post_id, res.post_id)
        self.assertEqual(loaded.new_concepts_detected, ["스펙큘레이티브 디코딩"])


if __name__ == "__main__":
    unittest.main()
