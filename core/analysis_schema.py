"""분석 결과 JSON 계약(버전 1)과 지식 사전 모델.

일반 분석(standard)과 갤러리 분석(gallery)이 공유하는 검증 계약만 정의한다.
LLM 호출, 분석 저장, 사건 묶기는 이 모듈의 책임이 아니다.
import 시 파일 읽기/쓰기/네트워크 작업은 없다. 파일 접근은 load_known_concepts 호출 시에만
호출자가 지정한 경로를 읽기 전용으로 연다.

검증하는 것:
- 필드 집합/타입(엄격 모드, extra='forbid'), track/status 조합, summary 줄 수.
- evidence_terms / new_concepts_detected의 원문(source_text) 존재, 중복, 부분집합 관계.
- HOLD와 순수 잡담(is_pure_noise)의 상호 배타 규칙.

검증하지 않는 것(후속 Evaluator 책임): 본문 충분성 임계값, 분류 정확도,
summary / concept_usage / actionable_idea 문장 전체의 의미적 근거성.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, model_validator

SCHEMA_VERSION = 1
PLATFORMS = ("instagram", "x", "youtube", "news", "huggingface", "github", "gallery")
STANDARD_SUMMARY_LINES = 3
GALLERY_SUMMARY_MAX_LINES = 3


def _non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


def _term_key(value: str) -> str:
    """사전/중복/부분집합 비교용 키. 출력값 자체는 바꾸지 않는다."""
    return value.strip().casefold()


def _exact_int(value: object) -> object:
    # Literal[1]은 True(==1)나 1.0도 통과시키므로 정확한 int만 허용한다.
    if type(value) is not int:
        raise ValueError("must be an integer (bool/float/str not accepted)")
    return value


NonBlankStr = Annotated[str, AfterValidator(_non_blank)]
StrList = list[NonBlankStr]
Version1 = Annotated[Literal[1], BeforeValidator(_exact_int)]

_STRICT = ConfigDict(extra="forbid", strict=True)


class Tags(BaseModel):
    model_config = _STRICT

    technical_form: StrList
    practicality: StrList
    difficulty: StrList


class AnalysisResult(BaseModel):
    """분석 결과 v1. 모든 필드는 필수이며 null은 hold_reason/event_id에서만 허용된다."""

    model_config = _STRICT

    schema_version: Version1
    platform: Literal["instagram", "x", "youtube", "news", "huggingface", "github", "gallery"]
    post_id: NonBlankStr
    track: Literal["standard", "gallery"]
    status: Literal["READY", "HOLD"]
    source_text: str
    hold_reason: NonBlankStr | None
    summary: StrList
    category: NonBlankStr
    tags: Tags
    event_id: NonBlankStr | None
    evidence_terms: StrList
    new_concepts_detected: StrList
    concept_usage: StrList
    actionable_idea: StrList
    is_pure_noise: bool

    @model_validator(mode="after")
    def _check_contract(self) -> "AnalysisResult":
        # track <-> platform
        if self.platform == "gallery":
            if self.track != "gallery":
                raise ValueError("platform 'gallery' requires track 'gallery'")
        elif self.track != "standard":
            raise ValueError("non-gallery platforms require track 'standard'")

        # 용어 중복/원문 존재/부분집합 (status와 무관하게 항상 검사)
        evidence_keys = self._unique_keys("evidence_terms", self.evidence_terms)
        new_keys = self._unique_keys("new_concepts_detected", self.new_concepts_detected)
        folded_source = self.source_text.casefold()
        for name, terms in (
            ("evidence_terms", self.evidence_terms),
            ("new_concepts_detected", self.new_concepts_detected),
        ):
            for term in terms:
                if _term_key(term) not in folded_source:
                    raise ValueError(f"{name} term {term!r} not found in source_text")
        if not set(new_keys) <= set(evidence_keys):
            raise ValueError("new_concepts_detected must be a subset of evidence_terms")

        analysis_fields_empty = not (
            self.summary
            or self.tags.technical_form
            or self.tags.practicality
            or self.tags.difficulty
            or self.evidence_terms
            or self.new_concepts_detected
            or self.concept_usage
            or self.actionable_idea
        )

        if self.status == "HOLD":
            if self.hold_reason is None:
                raise ValueError("HOLD requires hold_reason")
            if not analysis_fields_empty:
                raise ValueError("HOLD requires empty analysis fields")
            if self.event_id is not None:
                raise ValueError("HOLD requires event_id=null")
            if self.is_pure_noise:
                raise ValueError("HOLD must not be marked is_pure_noise")
            return self

        # READY
        if self.hold_reason is not None:
            raise ValueError("READY requires hold_reason=null")
        if not self.source_text.strip():
            raise ValueError("READY requires non-blank source_text")
        if self.track == "standard":
            if len(self.summary) != STANDARD_SUMMARY_LINES:
                raise ValueError("READY standard requires exactly 3 summary lines")
        elif len(self.summary) > GALLERY_SUMMARY_MAX_LINES:
            raise ValueError("READY gallery allows at most 3 summary lines")
        if self.is_pure_noise and (
            self.evidence_terms
            or self.new_concepts_detected
            or self.concept_usage
            or self.actionable_idea
        ):
            raise ValueError("is_pure_noise requires empty evidence/concept/usage/idea fields")
        return self

    @staticmethod
    def _unique_keys(name: str, terms: list[str]) -> list[str]:
        keys = [_term_key(t) for t in terms]
        if len(set(keys)) != len(keys):
            raise ValueError(f"{name} must not contain duplicates (case-insensitive)")
        return keys

    def validate_known_concepts(self, known: "KnownConcepts") -> None:
        """new_concepts_detected에 사전 등재 용어가 있으면 ValueError.

        원문 근거 검증(모델 검증)과 별도 호출이다. 출력값은 변경하지 않는다.
        """
        known_keys = {_term_key(c) for c in known.concepts}
        already_known = [t for t in self.new_concepts_detected if _term_key(t) in known_keys]
        if already_known:
            raise ValueError(f"new_concepts_detected contains known concepts: {already_known}")


class KnownConcepts(BaseModel):
    model_config = _STRICT

    schema_version: Version1
    provenance: Literal["initial_synthetic_draft"]
    concepts: Annotated[StrList, Field(min_length=1)]

    @model_validator(mode="after")
    def _no_duplicates(self) -> "KnownConcepts":
        keys = [_term_key(c) for c in self.concepts]
        if len(set(keys)) != len(keys):
            raise ValueError("concepts must not contain duplicates (strip+casefold)")
        return self


def load_known_concepts(path: str | Path) -> KnownConcepts:
    """지정한 파일만 읽어 KnownConcepts를 반환한다. 오류는 숨기지 않고 그대로 전파한다.

    없는 파일은 FileNotFoundError, 손상 JSON/계약 위반은 pydantic ValidationError(ValueError).
    파일을 만들거나 덮어쓰지 않는다.
    """
    text = Path(path).read_text(encoding="utf-8")
    return KnownConcepts.model_validate_json(text)
