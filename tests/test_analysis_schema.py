import copy
import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from core.analysis_schema import (
    AnalysisResult,
    KnownConcepts,
    load_known_concepts,
)

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "known_concepts.json"
GOLD = ROOT / "tests" / "blackbox" / "fixtures" / "gold_samples.json"

TAGS_EMPTY = {"technical_form": [], "practicality": [], "difficulty": []}


def gallery_ready():
    return {
        "schema_version": 1,
        "platform": "gallery",
        "post_id": "g-1",
        "track": "gallery",
        "status": "READY",
        "source_text": "transformer 어텐션 실습",
        "hold_reason": None,
        "summary": [],
        "category": "practical_experiment",
        "tags": copy.deepcopy(TAGS_EMPTY),
        "event_id": None,
        "evidence_terms": ["transformer", "어텐션"],
        "new_concepts_detected": ["어텐션"],
        "concept_usage": ["어텐션 실습"],
        "actionable_idea": [],
        "is_pure_noise": False,
    }


def standard_ready():
    d = gallery_ready()
    d.update(
        platform="x",
        post_id="1900000000000000001",
        track="standard",
        source_text="LoRA fine-tuning 으로 Diffusion 모델을 튜닝하는 방법",
        summary=["첫째 줄", "둘째 줄", "셋째 줄"],
        category="technique",
        tags={"technical_form": ["tutorial"], "practicality": ["high"], "difficulty": ["medium"]},
        event_id="evt-1",
        evidence_terms=["LoRA", "fine-tuning", "Diffusion"],
        new_concepts_detected=[],
        concept_usage=["LoRA로 튜닝"],
        actionable_idea=["작은 데이터로 시도"],
    )
    return d


def hold():
    d = gallery_ready()
    d.update(
        source_text="",
        status="HOLD",
        hold_reason="본문 없음, OCR 대기",
        evidence_terms=[],
        new_concepts_detected=[],
        concept_usage=[],
    )
    return d


class V:
    """검증 보조."""

    @staticmethod
    def ok(case, data):
        return AnalysisResult.model_validate(data)

    @staticmethod
    def bad(case, data):
        with case.assertRaises(ValueError):  # ValidationError는 ValueError 하위
            AnalysisResult.model_validate(data)


class ValidResultTests(unittest.TestCase):
    def test_ready_gallery(self):
        r = V.ok(self, gallery_ready())
        self.assertEqual(r.new_concepts_detected, ["어텐션"])
        self.assertIsNone(r.event_id)

    def test_ready_standard(self):
        r = V.ok(self, standard_ready())
        self.assertEqual(len(r.summary), 3)

    def test_gallery_summary_0_to_3(self):
        for n in range(4):
            d = gallery_ready()
            d["summary"] = [f"l{i}" for i in range(n)]
            V.ok(self, d)
        d = gallery_ready()
        d["summary"] = ["a", "b", "c", "d"]
        V.bad(self, d)

    def test_hold(self):
        r = V.ok(self, hold())
        self.assertEqual(r.status, "HOLD")
        self.assertFalse(r.is_pure_noise)

    def test_hold_standard_track(self):
        d = hold()
        d.update(platform="youtube", track="standard")
        V.ok(self, d)

    def test_pure_noise_ready(self):
        d = standard_ready()
        d.update(
            is_pure_noise=True,
            evidence_terms=[],
            new_concepts_detected=[],
            concept_usage=[],
            actionable_idea=[],
        )
        V.ok(self, d)

    def test_json_roundtrip(self):
        for d in (gallery_ready(), standard_ready(), hold()):
            r = AnalysisResult.model_validate(d)
            text = r.model_dump_json()
            self.assertEqual(AnalysisResult.model_validate_json(text), r)
            self.assertEqual(json.loads(text), d)
            # 단순 dict 왕복도 동일
            self.assertEqual(AnalysisResult.model_validate(r.model_dump()), r)

    def test_json_schema_generation(self):
        schema = AnalysisResult.model_json_schema()
        self.assertEqual(schema["additionalProperties"], False)
        self.assertEqual(set(schema["required"]), set(gallery_ready()))
        json.dumps(schema)
        json.dumps(KnownConcepts.model_json_schema())

    def test_all_platforms_with_matching_track(self):
        for p in ("instagram", "x", "youtube", "news", "huggingface", "github"):
            d = standard_ready()
            d["platform"] = p
            V.ok(self, d)


class StrictShapeTests(unittest.TestCase):
    def test_missing_key(self):
        for k in gallery_ready():
            d = gallery_ready()
            del d[k]
            with self.subTest(k=k):
                V.bad(self, d)

    def test_extra_key(self):
        d = gallery_ready()
        d["metrics"] = {"likes": 0}
        V.bad(self, d)
        d = gallery_ready()
        d["tags"]["extra"] = []
        V.bad(self, d)

    def test_missing_tag_key(self):
        d = gallery_ready()
        del d["tags"]["difficulty"]
        V.bad(self, d)

    def test_null_only_allowed_for_hold_reason_and_event_id(self):
        for k in gallery_ready():
            if k in ("hold_reason", "event_id"):
                continue
            d = gallery_ready()
            d[k] = None
            with self.subTest(k=k):
                V.bad(self, d)

    def test_no_bool_or_string_coercion(self):
        for k, v in [
            ("is_pure_noise", "false"),
            ("is_pure_noise", 0),
            ("is_pure_noise", None),
            ("schema_version", True),
            ("schema_version", "1"),
            ("schema_version", 1.0),
            ("post_id", 123),
            ("source_text", 5),
            ("summary", "abc"),
            ("evidence_terms", "transformer"),
            ("category", True),
        ]:
            d = gallery_ready()
            d[k] = v
            with self.subTest(k=k, v=v):
                V.bad(self, d)

    def test_no_coercion_from_json_text(self):
        for k, v in [("is_pure_noise", "false"), ("schema_version", True), ("schema_version", "1")]:
            d = gallery_ready()
            d[k] = v
            with self.subTest(k=k, v=v):
                with self.assertRaises(ValueError):
                    AnalysisResult.model_validate_json(json.dumps(d))

    def test_non_string_list_items(self):
        d = gallery_ready()
        d["concept_usage"] = [1]
        V.bad(self, d)
        d = gallery_ready()
        d["tags"]["difficulty"] = [None]
        V.bad(self, d)

    def test_bad_version_platform_track_status(self):
        for k, v in [
            ("schema_version", 2),
            ("schema_version", 0),
            ("platform", "tiktok"),
            ("platform", "Instagram"),
            ("track", "other"),
            ("status", "ready"),
            ("status", "DONE"),
        ]:
            d = gallery_ready()
            d[k] = v
            with self.subTest(k=k, v=v):
                V.bad(self, d)

    def test_track_platform_mismatch(self):
        d = gallery_ready()
        d["track"] = "standard"
        V.bad(self, d)
        d = standard_ready()
        d["track"] = "gallery"
        V.bad(self, d)

    def test_blank_strings(self):
        for k in ("post_id", "category"):
            for blank in ("", "   ", "\n\t"):
                d = gallery_ready()
                d[k] = blank
                with self.subTest(k=k, blank=blank):
                    V.bad(self, d)
        for k in ("hold_reason", "event_id"):
            d = hold() if k == "hold_reason" else gallery_ready()
            d[k] = "  "
            with self.subTest(k=k):
                V.bad(self, d)
        for k in ("summary", "evidence_terms", "concept_usage", "actionable_idea"):
            d = gallery_ready()
            d[k] = [" "]
            with self.subTest(k=k):
                V.bad(self, d)
        d = gallery_ready()
        d["tags"]["technical_form"] = [""]
        V.bad(self, d)

    def test_empty_source_text_is_schema_valid_for_hold_only(self):
        V.ok(self, hold())
        d = gallery_ready()
        d.update(source_text="", evidence_terms=[], new_concepts_detected=[])
        V.bad(self, d)
        d["source_text"] = "  \n "
        V.bad(self, d)


class ContractRuleTests(unittest.TestCase):
    def test_standard_requires_exactly_three_summary_lines(self):
        for lines in ([], ["a"], ["a", "b"], ["a", "b", "c", "d"], ["a", "b", " "]):
            d = standard_ready()
            d["summary"] = lines
            with self.subTest(n=len(lines)):
                V.bad(self, d)

    def test_ready_requires_null_hold_reason(self):
        d = gallery_ready()
        d["hold_reason"] = "why"
        V.bad(self, d)

    def test_hold_requires_reason(self):
        d = hold()
        d["hold_reason"] = None
        V.bad(self, d)

    def test_hold_requires_empty_analysis_fields(self):
        mutations = {
            "summary": ["a"],
            "evidence_terms": ["x"],
            "new_concepts_detected": ["x"],
            "concept_usage": ["u"],
            "actionable_idea": ["i"],
        }
        for k, v in mutations.items():
            d = hold()
            d["source_text"] = "x"
            d[k] = v
            with self.subTest(k=k):
                V.bad(self, d)
        for k in ("technical_form", "practicality", "difficulty"):
            d = hold()
            d["tags"][k] = ["t"]
            with self.subTest(tag=k):
                V.bad(self, d)

    def test_hold_event_id_and_noise(self):
        d = hold()
        d["event_id"] = "evt"
        V.bad(self, d)
        d = hold()
        d["is_pure_noise"] = True
        V.bad(self, d)

    def test_evidence_not_in_source(self):
        d = gallery_ready()
        d["evidence_terms"] = ["transformer", "없는단어"]
        V.bad(self, d)
        d = gallery_ready()
        d["new_concepts_detected"] = ["없는단어"]
        d["evidence_terms"] = ["transformer", "없는단어"]
        V.bad(self, d)

    def test_case_insensitive_substring(self):
        d = gallery_ready()
        d["source_text"] = "Transformer 어텐션 실습"
        d["evidence_terms"] = ["TRANSFORMER", "어텐션"]
        r = V.ok(self, d)
        self.assertEqual(r.evidence_terms[0], "TRANSFORMER")  # 변조 없음
        d = gallery_ready()
        d["evidence_terms"] = ["former", "어텐"]  # 부분 문자열 허용
        d["new_concepts_detected"] = ["어텐"]
        V.ok(self, d)

    def test_duplicates_case_insensitive(self):
        d = gallery_ready()
        d["source_text"] = "Transformer transformer"
        d["evidence_terms"] = ["Transformer", "transformer"]
        d["new_concepts_detected"] = []
        V.bad(self, d)
        d = gallery_ready()
        d["new_concepts_detected"] = ["어텐션", "어텐션"]
        V.bad(self, d)

    def test_new_concepts_subset_of_evidence(self):
        d = gallery_ready()
        d["evidence_terms"] = ["transformer"]
        d["new_concepts_detected"] = ["어텐션"]
        V.bad(self, d)
        d = gallery_ready()
        d["new_concepts_detected"] = ["ATTENTION".lower()]
        V.bad(self, d)
        # 대소문자만 다른 부분집합은 허용
        d = gallery_ready()
        d["source_text"] = "Transformer"
        d["evidence_terms"] = ["Transformer"]
        d["new_concepts_detected"] = ["TRANSFORMER"]
        V.ok(self, d)

    def test_not_every_evidence_term_must_be_new(self):
        r = V.ok(self, gallery_ready())
        self.assertEqual(len(r.evidence_terms), 2)
        self.assertEqual(len(r.new_concepts_detected), 1)

    def test_pure_noise_hallucination_rejected(self):
        for k, v in {
            "evidence_terms": ["transformer"],
            "new_concepts_detected": ["어텐션"],
            "concept_usage": ["u"],
            "actionable_idea": ["i"],
        }.items():
            d = gallery_ready()
            d.update(is_pure_noise=True, evidence_terms=[], new_concepts_detected=[], concept_usage=[])
            d[k] = v
            if k == "new_concepts_detected":
                d["evidence_terms"] = ["어텐션"]
            with self.subTest(k=k):
                V.bad(self, d)

    def test_long_korean_emoji_and_unicode(self):
        long_text = "가나다라마바사 " * 20000 + "🔥 어텐션 🚀 Straße"
        d = gallery_ready()
        d.update(
            source_text=long_text,
            evidence_terms=["어텐션", "🔥", "STRASSE", "🚀"],
            new_concepts_detected=["어텐션", "🚀"],
            concept_usage=["🔥 어텐션 🚀"],
        )
        r = V.ok(self, d)
        self.assertEqual(AnalysisResult.model_validate_json(r.model_dump_json()), r)
        self.assertEqual(r.source_text, long_text)

    def test_strip_does_not_mutate_output(self):
        d = gallery_ready()
        d["evidence_terms"] = [" transformer ", "어텐션"]
        d["new_concepts_detected"] = []
        r = V.ok(self, d)
        self.assertEqual(r.evidence_terms[0], " transformer ")

    def test_gallery_example_from_spec(self):
        r = V.ok(self, gallery_ready())
        self.assertEqual(r.category, "practical_experiment")
        self.assertEqual(r.concept_usage, ["어텐션 실습"])


class KnownConceptsTests(unittest.TestCase):
    def kc(self, concepts, **over):
        d = {"schema_version": 1, "provenance": "initial_synthetic_draft", "concepts": concepts}
        d.update(over)
        return d

    def test_known_concept_rejected_by_separate_call(self):
        known = KnownConcepts.model_validate(self.kc(["Transformer", "LoRA"]))
        d = gallery_ready()
        d["new_concepts_detected"] = ["TRANSFORMER"]
        r = V.ok(self, d)  # 모델 검증 자체는 통과
        with self.assertRaises(ValueError):
            r.validate_known_concepts(known)
        # strip+casefold 비교, 원문 출력값 불변
        self.assertEqual(r.new_concepts_detected, ["TRANSFORMER"])

    def test_known_concept_whitespace_and_case(self):
        known = KnownConcepts.model_validate(self.kc(["  Fine-Tuning "]))
        d = gallery_ready()
        d.update(
            source_text="fine-tuning 실습",
            evidence_terms=["FINE-TUNING"],
            new_concepts_detected=["FINE-TUNING"],
        )
        with self.assertRaises(ValueError):
            V.ok(self, d).validate_known_concepts(known)

    def test_unknown_new_concept_passes(self):
        known = KnownConcepts.model_validate(self.kc(["transformer", "lora"]))
        self.assertIsNone(V.ok(self, gallery_ready()).validate_known_concepts(known))

    def test_evidence_may_contain_known_concepts(self):
        known = KnownConcepts.model_validate(self.kc(["transformer"]))
        r = V.ok(self, gallery_ready())  # evidence에 transformer 포함
        r.validate_known_concepts(known)

    def test_known_concepts_validation(self):
        KnownConcepts.model_validate(self.kc(["a"]))
        for bad in (
            self.kc([]),
            self.kc([" "]),
            self.kc(["a", "A"]),
            self.kc(["a", " a "]),
            self.kc(["ß", "SS"]),
            self.kc([1]),
            self.kc(["a"], schema_version=2),
            self.kc(["a"], schema_version=True),
            self.kc(["a"], provenance="user_verified"),
            self.kc(["a"], extra=1),
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    KnownConcepts.model_validate(bad)
        d = self.kc(["a"])
        del d["provenance"]
        with self.assertRaises(ValueError):
            KnownConcepts.model_validate(d)


class LoadKnownConceptsTests(unittest.TestCase):
    def test_load_valid_unicode(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "k.json"
            data = {"schema_version": 1, "provenance": "initial_synthetic_draft", "concepts": ["어텐션", "🔥", "LoRA"]}
            p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            before = p.read_bytes()
            k = load_known_concepts(p)
            self.assertEqual(k.concepts, ["어텐션", "🔥", "LoRA"])
            self.assertEqual(p.read_bytes(), before)
            self.assertEqual([x.name for x in Path(tmp).iterdir()], ["k.json"])
            load_known_concepts(str(p))  # str 경로도 허용

    def test_missing_file_not_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "nope.json"
            with self.assertRaises(FileNotFoundError):
                load_known_concepts(p)
            self.assertFalse(p.exists())
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_corrupt_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "k.json"
            p.write_text("{not json", encoding="utf-8")
            before = p.read_bytes()
            with self.assertRaises(ValueError):
                load_known_concepts(p)
            self.assertEqual(p.read_bytes(), before)

    def test_validation_error_surfaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "k.json"
            p.write_text(
                json.dumps({"schema_version": 1, "provenance": "initial_synthetic_draft", "concepts": []}),
                encoding="utf-8",
            )
            with self.assertRaises(ValidationError):
                load_known_concepts(p)
            p.write_text("[]", encoding="utf-8")
            with self.assertRaises(ValidationError):
                load_known_concepts(p)

    def test_directory_path_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(OSError):
                load_known_concepts(tmp)


class ConfigDraftTests(unittest.TestCase):
    """T-006: 실제 config는 사용자 확정 5개(+aliases). 합성 12개는 gold fixture에서 별도 검증."""

    USER_CONCEPTS = ["환각", "프롬프트 엔지니어링", "컨텍스트 윈도우", "RAG", "임베딩"]

    def test_config_is_user_confirmed_five(self):
        known = load_known_concepts(CONFIG)
        self.assertEqual(known.provenance, "user_confirmed")
        self.assertEqual(known.concepts, self.USER_CONCEPTS)
        self.assertEqual(set(known.aliases), set(self.USER_CONCEPTS))

    def test_synthetic_gold_twelve_still_valid_model(self):
        gold = json.loads(GOLD.read_text(encoding="utf-8"))
        known = KnownConcepts.model_validate(
            {"schema_version": 1, "provenance": "initial_synthetic_draft", "concepts": gold["known_concepts"]}
        )
        self.assertEqual(len(known.concepts), 12)
        self.assertEqual(known.aliases, {})

    def test_config_known_term_rejected_as_new(self):
        known = load_known_concepts(CONFIG)
        d = gallery_ready()
        d.update(
            source_text="RAG 어텐션",
            evidence_terms=["RAG", "어텐션"],
            new_concepts_detected=["RAG"],
        )
        with self.assertRaises(ValueError):
            V.ok(self, d).validate_known_concepts(known)

    def test_import_has_no_side_effects(self):
        import importlib
        import sys

        sys.modules.pop("core.analysis_schema", None)
        importlib.import_module("core.analysis_schema")


if __name__ == "__main__":
    unittest.main()
