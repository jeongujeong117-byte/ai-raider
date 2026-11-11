"""Blackbox verification test suite for T-004 analysis result JSON contract and known concepts draft.

Validates the public contract of core.analysis_schema:
- AnalysisResult
- KnownConcepts
- load_known_concepts(path)
- AnalysisResult.validate_known_concepts(known) -> None
"""

from __future__ import annotations

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

import core.analysis_schema as schema
from core.analysis_schema import AnalysisResult, KnownConcepts, load_known_concepts
import core.store


def _build_valid_payload(**overrides) -> dict:
    base = {
        "schema_version": 1,
        "platform": "instagram",
        "post_id": "post-synth-001",
        "track": "standard",
        "status": "READY",
        "source_text": "Vision Transformer (ViT) fine-tuning guide with synthetic images.",
        "hold_reason": None,
        "summary": [
            "Vision Transformer fine-tuning tutorial.",
            "Covers synthetic dataset generation.",
            "Demonstrates practical optimization steps.",
        ],
        "category": "tutorial",
        "tags": {
            "technical_form": ["guide"],
            "practicality": ["high"],
            "difficulty": ["intermediate"],
        },
        "event_id": None,
        "evidence_terms": ["ViT", "Transformer", "fine-tuning"],
        "new_concepts_detected": ["ViT"],
        "concept_usage": ["ViT fine-tuning guide"],
        "actionable_idea": ["Train ViT on synthetic data"],
        "is_pure_noise": False,
    }
    base.update(overrides)
    return base


def _build_valid_hold_payload(**overrides) -> dict:
    base = {
        "schema_version": 1,
        "platform": "instagram",
        "post_id": "post-synth-hold",
        "track": "standard",
        "status": "HOLD",
        "source_text": "",
        "hold_reason": "Waiting for OCR completion",
        "summary": [],
        "category": "uncategorized",
        "tags": {
            "technical_form": [],
            "practicality": [],
            "difficulty": [],
        },
        "event_id": None,
        "evidence_terms": [],
        "new_concepts_detected": [],
        "concept_usage": [],
        "actionable_idea": [],
        "is_pure_noise": False,
    }
    base.update(overrides)
    return base


class AnalysisSchemaBlackboxTests(unittest.TestCase):
    """Adversarial blackbox tests for T-004 JSON contracts."""

    def test_01_module_import_and_public_api_surface(self):
        """Importing core.analysis_schema must have no disk/network side effects."""
        self.assertTrue(hasattr(schema, "AnalysisResult"))
        self.assertTrue(hasattr(schema, "KnownConcepts"))
        self.assertTrue(hasattr(schema, "load_known_concepts"))
        self.assertTrue(hasattr(schema, "SCHEMA_VERSION"))
        self.assertEqual(schema.SCHEMA_VERSION, 1)
        self.assertIn("gallery", schema.PLATFORMS)
        self.assertIn("instagram", schema.PLATFORMS)

    def test_02_schema_version_strict_int_rejection(self):
        """schema_version must strictly accept int 1, rejecting bool/float/str/other ints."""
        # 1 is valid
        valid = _build_valid_payload(schema_version=1)
        res = AnalysisResult.model_validate(valid)
        self.assertIs(type(res.schema_version), int)
        self.assertEqual(res.schema_version, 1)

        # bool True must be rejected (Python bool is subclass of int)
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_payload(schema_version=True))
        with self.assertRaises(ValidationError):
            raw = json.dumps(_build_valid_payload(schema_version=True))
            AnalysisResult.model_validate_json(raw)

        # bool False must be rejected
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_payload(schema_version=False))

        # float 1.0 must be rejected
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_payload(schema_version=1.0))
        with self.assertRaises(ValidationError):
            raw = json.dumps(_build_valid_payload(schema_version=1.0))
            AnalysisResult.model_validate_json(raw)

        # str "1" must be rejected
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_payload(schema_version="1"))
        with self.assertRaises(ValidationError):
            raw = json.dumps(_build_valid_payload(schema_version="1"))
            AnalysisResult.model_validate_json(raw)

        # Other integers must be rejected
        for bad_v in (0, 2, -1, 999):
            with self.subTest(bad_version=bad_v):
                with self.assertRaises(ValidationError):
                    AnalysisResult.model_validate(_build_valid_payload(schema_version=bad_v))

        # None must be rejected
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_payload(schema_version=None))

        # KnownConcepts schema_version strictness
        with self.assertRaises(ValidationError):
            KnownConcepts.model_validate({
                "schema_version": True,
                "provenance": "initial_synthetic_draft",
                "concepts": ["agent"],
            })
        with self.assertRaises(ValidationError):
            KnownConcepts.model_validate({
                "schema_version": 1.0,
                "provenance": "initial_synthetic_draft",
                "concepts": ["agent"],
            })

    def test_03_is_pure_noise_strict_bool_rejection(self):
        """is_pure_noise must strictly accept bool True/False, rejecting int/str/null."""
        payload_false = _build_valid_payload(is_pure_noise=False)
        self.assertIs(type(AnalysisResult.model_validate(payload_false).is_pure_noise), bool)

        # Empty analysis fields for pure_noise=True
        payload_true = _build_valid_payload(
            is_pure_noise=True,
            evidence_terms=[],
            new_concepts_detected=[],
            concept_usage=[],
            actionable_idea=[],
        )
        self.assertIs(type(AnalysisResult.model_validate(payload_true).is_pure_noise), bool)

        # Rejection of ints / strings / None
        for bad_bool in (1, 0, "true", "false", "True", "False", 1.0, None):
            with self.subTest(bad_bool=bad_bool):
                with self.assertRaises(ValidationError):
                    AnalysisResult.model_validate(_build_valid_payload(is_pure_noise=bad_bool))
                raw = json.dumps(_build_valid_payload(is_pure_noise=bad_bool))
                with self.assertRaises(ValidationError):
                    AnalysisResult.model_validate_json(raw)

    def test_04_extra_fields_forbidden(self):
        """extra='forbid' must reject extra keys at root and nested models."""
        # Extra key in root dict
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_payload(metrics={"likes": 10}))
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_payload(extra_field="disallowed"))

        # Extra key in JSON text
        raw_extra = json.dumps(_build_valid_payload(additional_property="rejected"))
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate_json(raw_extra)

        # Extra key in tags
        bad_tags = {
            "technical_form": ["guide"],
            "practicality": ["high"],
            "difficulty": ["intermediate"],
            "sentiment": ["positive"],
        }
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_payload(tags=bad_tags))

        # Extra key in KnownConcepts
        with self.assertRaises(ValidationError):
            KnownConcepts.model_validate({
                "schema_version": 1,
                "provenance": "initial_synthetic_draft",
                "concepts": ["agent"],
                "unknown_key": "val",
            })

    def test_05_missing_and_none_fields(self):
        """All 16 fields are required; only hold_reason and event_id are nullable."""
        required_fields = [
            "schema_version",
            "platform",
            "post_id",
            "track",
            "status",
            "source_text",
            "hold_reason",
            "summary",
            "category",
            "tags",
            "event_id",
            "evidence_terms",
            "new_concepts_detected",
            "concept_usage",
            "actionable_idea",
            "is_pure_noise",
        ]
        self.assertEqual(len(required_fields), 16)

        for field in required_fields:
            with self.subTest(missing_field=field):
                data = _build_valid_payload()
                del data[field]
                with self.assertRaises(ValidationError):
                    AnalysisResult.model_validate(data)

        # Test non-nullable fields cannot be None
        non_nullable_fields = [f for f in required_fields if f not in ("hold_reason", "event_id")]
        for field in non_nullable_fields:
            with self.subTest(none_field=field):
                data = _build_valid_payload(**{field: None})
                with self.assertRaises(ValidationError):
                    AnalysisResult.model_validate(data)

        # Nested tags missing or None fields
        for tag_key in ("technical_form", "practicality", "difficulty"):
            with self.subTest(missing_tag_key=tag_key):
                bad_tags = {
                    "technical_form": ["a"],
                    "practicality": ["b"],
                    "difficulty": ["c"],
                }
                del bad_tags[tag_key]
                with self.assertRaises(ValidationError):
                    AnalysisResult.model_validate(_build_valid_payload(tags=bad_tags))

            with self.subTest(none_tag_key=tag_key):
                bad_tags = {
                    "technical_form": ["a"],
                    "practicality": ["b"],
                    "difficulty": ["c"],
                }
                bad_tags[tag_key] = None
                with self.assertRaises(ValidationError):
                    AnalysisResult.model_validate(_build_valid_payload(tags=bad_tags))

    def test_06_platform_and_track_matrix(self):
        """7 platforms: gallery requires track 'gallery', others require track 'standard'."""
        standard_platforms = ["instagram", "x", "youtube", "news", "huggingface", "github"]
        for p in standard_platforms:
            # standard platform with track standard -> OK
            ok_payload = _build_valid_payload(platform=p, track="standard")
            res = AnalysisResult.model_validate(ok_payload)
            self.assertEqual(res.platform, p)
            self.assertEqual(res.track, "standard")

            # standard platform with track gallery -> Error
            with self.assertRaises(ValidationError):
                AnalysisResult.model_validate(_build_valid_payload(platform=p, track="gallery"))

        # gallery platform with track gallery -> OK
        gal_payload = _build_valid_payload(
            platform="gallery",
            track="gallery",
            summary=["Gallery single summary line."],
        )
        gal_res = AnalysisResult.model_validate(gal_payload)
        self.assertEqual(gal_res.platform, "gallery")
        self.assertEqual(gal_res.track, "gallery")

        # gallery platform with track standard -> Error
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_payload(platform="gallery", track="standard"))

        # Unsupported platform -> Error
        for bad_p in ("threads", "tiktok", "facebook", "web", ""):
            with self.subTest(bad_platform=bad_p):
                with self.assertRaises(ValidationError):
                    AnalysisResult.model_validate(_build_valid_payload(platform=bad_p))

        # Unsupported track -> Error
        for bad_t in ("custom", "standard_v2", ""):
            with self.subTest(bad_track=bad_t):
                with self.assertRaises(ValidationError):
                    AnalysisResult.model_validate(_build_valid_payload(track=bad_t))

    def test_07_ready_contract_standard_and_gallery(self):
        """READY: non-blank source_text, hold_reason=null; standard 3 lines, gallery 0~3 lines."""
        # Non-null hold_reason in READY -> Error
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_payload(hold_reason="Not allowed in READY"))

        # Blank source_text in READY -> Error
        for blank_src in ("", "   ", "\n\t"):
            with self.subTest(blank_src=blank_src):
                with self.assertRaises(ValidationError):
                    AnalysisResult.model_validate(_build_valid_payload(source_text=blank_src))

        # standard summary lines: exactly 3 required
        for bad_lines in (0, 1, 2, 4):
            with self.subTest(standard_lines=bad_lines):
                summary = [f"Line {i}" for i in range(bad_lines)]
                with self.assertRaises(ValidationError):
                    AnalysisResult.model_validate(_build_valid_payload(summary=summary))

        # standard summary with blank line among 3 lines -> Error
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_payload(summary=["Line 1", "  ", "Line 3"]))

        # gallery summary: 0, 1, 2, 3 lines allowed
        for valid_count in (0, 1, 2, 3):
            with self.subTest(gallery_lines=valid_count):
                summary = [f"Gallery line {i}" for i in range(valid_count)]
                gal = AnalysisResult.model_validate(_build_valid_payload(
                    platform="gallery",
                    track="gallery",
                    summary=summary,
                ))
                self.assertEqual(len(gal.summary), valid_count)

        # gallery summary > 3 lines -> Error
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_payload(
                platform="gallery",
                track="gallery",
                summary=["L1", "L2", "L3", "L4"],
            ))

    def test_08_hold_contract_standard_and_gallery(self):
        """HOLD: hold_reason required, 8 analysis collections empty, event_id=null, is_pure_noise=false."""
        hold_ok = AnalysisResult.model_validate(_build_valid_hold_payload())
        self.assertEqual(hold_ok.status, "HOLD")
        self.assertIsNotNone(hold_ok.hold_reason)
        self.assertIsNone(hold_ok.event_id)
        self.assertFalse(hold_ok.is_pure_noise)
        self.assertEqual(hold_ok.summary, [])

        # hold_reason cannot be None in HOLD
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_hold_payload(hold_reason=None))

        # hold_reason cannot be blank string in HOLD
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_hold_payload(hold_reason="   "))

        # event_id must be None in HOLD
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_hold_payload(event_id="evt-001"))

        # is_pure_noise cannot be True in HOLD
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_hold_payload(is_pure_noise=True))

        # Analysis fields must all be empty in HOLD
        non_empty_cases = [
            ("summary", ["Line 1"]),
            ("evidence_terms", ["ViT"]),
            ("new_concepts_detected", ["ViT"]),
            ("concept_usage", ["Usage"]),
            ("actionable_idea", ["Idea"]),
        ]
        for field, val in non_empty_cases:
            with self.subTest(non_empty_field=field):
                src = "ViT text" if "ViT" in val else ""
                with self.assertRaises(ValidationError):
                    AnalysisResult.model_validate(_build_valid_hold_payload(
                        source_text=src,
                        **{field: val},
                    ))

        # tags non-empty in HOLD -> Error
        for tag_key in ("technical_form", "practicality", "difficulty"):
            with self.subTest(non_empty_tag=tag_key):
                bad_tags = {
                    "technical_form": [],
                    "practicality": [],
                    "difficulty": [],
                }
                bad_tags[tag_key] = ["non_empty"]
                with self.assertRaises(ValidationError):
                    AnalysisResult.model_validate(_build_valid_hold_payload(tags=bad_tags))

        # gallery track HOLD
        gal_hold = AnalysisResult.model_validate(_build_valid_hold_payload(
            platform="gallery",
            track="gallery",
        ))
        self.assertEqual(gal_hold.track, "gallery")
        self.assertEqual(gal_hold.status, "HOLD")

    def test_09_pure_noise_contract(self):
        """is_pure_noise=true in READY requires empty evidence/new/usage/idea fields."""
        pure_noise_ok = _build_valid_payload(
            is_pure_noise=True,
            evidence_terms=[],
            new_concepts_detected=[],
            concept_usage=[],
            actionable_idea=[],
        )
        res = AnalysisResult.model_validate(pure_noise_ok)
        self.assertTrue(res.is_pure_noise)
        self.assertEqual(len(res.summary), 3)  # summary remains standard 3 lines

        # Violation: having evidence_terms when pure_noise=True
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_payload(
                is_pure_noise=True,
                evidence_terms=["ViT"],
                new_concepts_detected=[],
                concept_usage=[],
                actionable_idea=[],
            ))

        # Violation: having concept_usage when pure_noise=True
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_payload(
                is_pure_noise=True,
                evidence_terms=[],
                new_concepts_detected=[],
                concept_usage=["Some usage"],
                actionable_idea=[],
            ))

        # Violation: having actionable_idea when pure_noise=True
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_payload(
                is_pure_noise=True,
                evidence_terms=[],
                new_concepts_detected=[],
                concept_usage=[],
                actionable_idea=["Some idea"],
            ))

    def test_10_blank_strings_rejected_in_all_collections_and_scalars(self):
        """Any whitespace-only or empty string in collections or required string scalars must be rejected."""
        # Scalar fields
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_payload(post_id="   "))
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_payload(category="   "))
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_payload(event_id="   "))

        # Collections
        list_fields = [
            "summary",
            "evidence_terms",
            "new_concepts_detected",
            "concept_usage",
            "actionable_idea",
        ]
        for field in list_fields:
            with self.subTest(blank_in_list=field):
                data = _build_valid_payload()
                data[field] = ["valid_item", "   "]
                if field == "summary":
                    data[field] = ["line1", "line2", "   "]
                with self.assertRaises(ValidationError):
                    AnalysisResult.model_validate(data)

        # Tags collections
        for tag_k in ("technical_form", "practicality", "difficulty"):
            with self.subTest(blank_in_tag=tag_k):
                tags = {
                    "technical_form": ["a"],
                    "practicality": ["b"],
                    "difficulty": ["c"],
                }
                tags[tag_k] = ["   "]
                with self.assertRaises(ValidationError):
                    AnalysisResult.model_validate(_build_valid_payload(tags=tags))

    def test_11_evidence_terms_and_new_concepts_grounding(self):
        """Terms in evidence_terms and new_concepts_detected must exist in source_text (case-insensitive)."""
        src = "Transformer attention fine-tuning experiments."
        # Valid: casing variation is allowed because match is case-insensitive
        valid = _build_valid_payload(
            source_text=src,
            evidence_terms=["TRANSFORMER", "attention"],
            new_concepts_detected=["attention"],
        )
        res = AnalysisResult.model_validate(valid)
        self.assertIn("TRANSFORMER", res.evidence_terms)

        # Non-grounded evidence term -> Error
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_payload(
                source_text=src,
                evidence_terms=["diffusion"],  # not in src
                new_concepts_detected=[],
            ))

        # Non-grounded new concept -> Error
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_payload(
                source_text=src,
                evidence_terms=["Transformer", "diffusion"],
                new_concepts_detected=["diffusion"],
            ))

    def test_12_new_concepts_subset_of_evidence(self):
        """new_concepts_detected must be a subset of evidence_terms (case-insensitive)."""
        src = "Agent workflow with LoRA adapter and RAG retrieval."
        # Subset with casing difference: 'lora' matches 'LoRA'
        valid = _build_valid_payload(
            source_text=src,
            evidence_terms=["LoRA", "RAG"],
            new_concepts_detected=["lora"],
        )
        res = AnalysisResult.model_validate(valid)
        self.assertEqual(res.new_concepts_detected, ["lora"])

        # Not a subset: 'Agent' is in source_text but omitted from evidence_terms
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_payload(
                source_text=src,
                evidence_terms=["LoRA"],
                new_concepts_detected=["Agent"],
            ))

    def test_13_casefold_and_whitespace_duplicates_rejection(self):
        """Duplicates under strip().casefold() must be rejected in evidence_terms, new_concepts, and concepts."""
        src = "LoRA lora fine-tuning guide."
        # Casefold duplicate in evidence_terms
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_payload(
                source_text=src,
                evidence_terms=["LoRA", "lora"],
                new_concepts_detected=[],
            ))

        # Strip + casefold duplicate
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_payload(
                source_text=src,
                evidence_terms=[" LoRA ", "lora"],
                new_concepts_detected=[],
            ))

        # Duplicate in new_concepts_detected
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_payload(
                source_text=src,
                evidence_terms=["LoRA"],
                new_concepts_detected=["LoRA", "lora"],
            ))

        # Duplicate in KnownConcepts
        with self.assertRaises(ValidationError):
            KnownConcepts.model_validate({
                "schema_version": 1,
                "provenance": "initial_synthetic_draft",
                "concepts": ["LoRA", "lora"],
            })

    def test_14_original_string_immutability(self):
        """Output model must retain original string casing and content without mutation."""
        src = "   Transformer Attention Guide   "
        payload = _build_valid_payload(
            post_id=" Post-ID_001 ",
            source_text=src,
            category=" AI_Research ",
            evidence_terms=["Transformer", "Attention"],
            new_concepts_detected=["Attention"],
        )
        res = AnalysisResult.model_validate(payload)
        self.assertEqual(res.post_id, " Post-ID_001 ")
        self.assertEqual(res.category, " AI_Research ")
        self.assertEqual(res.evidence_terms[0], "Transformer")
        self.assertEqual(res.evidence_terms[1], "Attention")
        self.assertEqual(res.new_concepts_detected[0], "Attention")

    def test_15_validate_known_concepts(self):
        """validate_known_concepts raises ValueError if new_concepts_detected contains registered concepts."""
        known = KnownConcepts.model_validate({
            "schema_version": 1,
            "provenance": "initial_synthetic_draft",
            "concepts": ["transformer", "lora", "agent"],
        })

        src = "transformer agent with novel flash_attention mechanism."

        # Case 1: evidence_terms has known concepts ('transformer', 'agent'),
        # but new_concepts_detected ONLY has novel concept ('flash_attention') -> OK
        analysis_ok = AnalysisResult.model_validate(_build_valid_payload(
            source_text=src,
            evidence_terms=["transformer", "agent", "flash_attention"],
            new_concepts_detected=["flash_attention"],
        ))
        # Must succeed without error
        analysis_ok.validate_known_concepts(known)

        # Case 2: new_concepts_detected contains a known concept ('Transformer', case-insensitive) -> ValueError
        analysis_bad = AnalysisResult.model_validate(_build_valid_payload(
            source_text=src,
            evidence_terms=["transformer", "flash_attention"],
            new_concepts_detected=["Transformer"],  # in known
        ))
        with self.assertRaises(ValueError):
            analysis_bad.validate_known_concepts(known)

        # Case 3: whitespace in known or new concept matches under strip().casefold()
        analysis_ws = AnalysisResult.model_validate(_build_valid_payload(
            source_text=src,
            evidence_terms=["agent"],
            new_concepts_detected=[" Agent "],
        ))
        with self.assertRaises(ValueError):
            analysis_ws.validate_known_concepts(known)

    def test_16_known_concepts_model_validation(self):
        """KnownConcepts validation: version=1, provenance='initial_synthetic_draft', min_length=1."""
        valid_data = {
            "schema_version": 1,
            "provenance": "initial_synthetic_draft",
            "concepts": ["transformer", "vit"],
        }
        kc = KnownConcepts.model_validate(valid_data)
        self.assertEqual(kc.schema_version, 1)
        self.assertEqual(kc.provenance, "initial_synthetic_draft")
        self.assertEqual(len(kc.concepts), 2)

        # T-006: user_confirmed is now a valid provenance (user-approved D-013); other values stay rejected
        KnownConcepts.model_validate({**valid_data, "provenance": "user_confirmed"})
        for bad_prov in ("user_verified", "", None):
            with self.assertRaises(ValidationError):
                KnownConcepts.model_validate({
                    **valid_data,
                    "provenance": bad_prov,
                })

        # Empty concepts list
        with self.assertRaises(ValidationError):
            KnownConcepts.model_validate({
                **valid_data,
                "concepts": [],
            })

        # Blank string concept
        with self.assertRaises(ValidationError):
            KnownConcepts.model_validate({
                **valid_data,
                "concepts": ["valid", "   "],
            })

    def test_17_load_known_concepts_io_contract(self):
        """load_known_concepts reads specified file, does not create or overwrite files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # 1. Non-existent file raises FileNotFoundError and does NOT create file
            missing_file = tmppath / "missing.json"
            with self.assertRaises(FileNotFoundError):
                load_known_concepts(missing_file)
            self.assertFalse(missing_file.exists())

            # 2. Valid file loads correctly
            valid_file = tmppath / "valid.json"
            valid_payload = {
                "schema_version": 1,
                "provenance": "initial_synthetic_draft",
                "concepts": ["mamba", "rwkv"],
            }
            valid_file.write_text(json.dumps(valid_payload), encoding="utf-8")
            mtime_before = valid_file.stat().st_mtime_ns
            kc = load_known_concepts(valid_file)
            self.assertEqual(kc.concepts, ["mamba", "rwkv"])
            # Ensure file was not overwritten
            self.assertEqual(valid_file.stat().st_mtime_ns, mtime_before)

            # 3. Corrupted JSON raises ValidationError/ValueError
            corrupt_file = tmppath / "corrupt.json"
            corrupt_file.write_text('{"schema_version": 1, "concepts": [broken', encoding="utf-8")
            with self.assertRaises((ValidationError, ValueError)):
                load_known_concepts(corrupt_file)

            # 4. Schema violation raises ValidationError
            invalid_file = tmppath / "invalid.json"
            invalid_file.write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
            with self.assertRaises(ValidationError):
                load_known_concepts(invalid_file)

    def test_18_config_user_confirmed_and_gold_synthetic_independent(self):
        """T-006 revised contract (user-approved D-013): config is the user-confirmed 5 concepts;
        the synthetic 12 in gold_samples.json remain a separately valid model."""
        config_path = ROOT / "config" / "known_concepts.json"
        gold_path = ROOT / "tests" / "blackbox" / "fixtures" / "gold_samples.json"

        self.assertTrue(config_path.exists())
        self.assertTrue(gold_path.exists())

        kc = load_known_concepts(config_path)
        self.assertEqual(kc.schema_version, 1)
        self.assertEqual(kc.provenance, "user_confirmed")
        self.assertEqual(kc.concepts, ["환각", "프롬프트 엔지니어링", "컨텍스트 윈도우", "RAG", "임베딩"])
        self.assertEqual(set(kc.aliases), set(kc.concepts))

        with open(gold_path, "r", encoding="utf-8") as f:
            gold_data = json.load(f)
        gold_concepts = gold_data["known_concepts"]
        self.assertEqual(len(gold_concepts), 12)
        synth = KnownConcepts.model_validate({
            "schema_version": 1,
            "provenance": "initial_synthetic_draft",
            "concepts": gold_concepts,
        })
        self.assertEqual(set(synth.concepts), set(gold_concepts))

    def test_19_large_payload_unicode_and_casefold_edge_cases(self):
        """Large payload, Korean text, emojis, and German sharp S (ß / SS) casefold roundtrip."""
        large_korean = "인공지능 모델 훈련 가이드 " * 2000  # ~30,000 chars
        emoji_section = " 🚀 🤖 ⚡ 훈련 진행 "
        german_casefold_section = " GROßE SPRACHMODELLE "
        full_source = large_korean + emoji_section + german_casefold_section

        # "große" casefolds to "grosse", matching "GROßE"
        payload = _build_valid_payload(
            source_text=full_source,
            summary=[
                "대규모 한국어 인공지능 모델 가이드 요약 1",
                "이모지 및 특수문자 처리 요약 2 🚀",
                "Große Sprachmodelle casefold 검증 3",
            ],
            evidence_terms=["인공지능", "GROßE"],
            new_concepts_detected=["GROßE"],
        )

        res = AnalysisResult.model_validate(payload)
        self.assertEqual(len(res.source_text), len(full_source))

        # JSON text roundtrip
        json_str = res.model_dump_json()
        restored = AnalysisResult.model_validate_json(json_str)
        self.assertEqual(res, restored)

    def test_20_model_json_schema_completeness(self):
        """model_json_schema must declare additionalProperties=False and all required fields."""
        ar_schema = AnalysisResult.model_json_schema()
        self.assertEqual(ar_schema.get("additionalProperties"), False)
        required = ar_schema.get("required", [])
        self.assertEqual(len(required), 16)

        kc_schema = KnownConcepts.model_json_schema()
        self.assertEqual(kc_schema.get("additionalProperties"), False)
        kc_required = kc_schema.get("required", [])
        self.assertIn("schema_version", kc_required)
        self.assertIn("provenance", kc_required)
        self.assertIn("concepts", kc_required)

    def test_21_store_metrics_isolation_regression(self):
        """metrics remains outside AnalysisResult contract and preserves null/0 in Store."""
        # 1. metrics cannot be passed to AnalysisResult
        with self.assertRaises(ValidationError):
            AnalysisResult.model_validate(_build_valid_payload(metrics={"likes": 0}))

        # 2. Store preserves null and 0 metrics
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_store.db"
            store = core.store.Store(db_path)
            # Null likes
            store.save({
                "platform": "instagram",
                "post_id": "null-likes-001",
                "handle": "test_user",
                "url": "https://example.com/p/null-likes-001",
                "posted_at": "2026-08-10T00:00:00+00:00",
                "text": "Post with null likes",
                "metrics": {"likes": None, "comments": 5},
                "media": [],
                "raw": {},
            })
            # Zero likes
            store.save({
                "platform": "instagram",
                "post_id": "zero-likes-001",
                "handle": "test_user",
                "url": "https://example.com/p/zero-likes-001",
                "posted_at": "2026-08-10T01:00:00+00:00",
                "text": "Post with zero likes",
                "metrics": {"likes": 0, "comments": 2},
                "media": [],
                "raw": {},
            })

            rows = store.rows(platform="instagram")
            self.assertEqual(rows["total"], 2)

            post_null = next(r for r in rows["items"] if r["post_id"] == "null-likes-001")
            self.assertIsNone(post_null["metrics"]["likes"])

            post_zero = next(r for r in rows["items"] if r["post_id"] == "zero-likes-001")
            self.assertIs(type(post_zero["metrics"]["likes"]), int)
            self.assertEqual(post_zero["metrics"]["likes"], 0)
            self.assertIsNot(post_zero["metrics"]["likes"], False)


if __name__ == "__main__":
    unittest.main()
