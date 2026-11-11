# T-004 학습: 분석 결과 "계약서"(JSON 스키마)와 지식 사전

대상: 기초를 마치고 중급에 막 들어선 비전공자. 기준 코드: `core/analysis_schema.py`(이 브랜치 시점, 189줄). 읽은 자료: T-004 spec, 개발 보고(`handoff/reports/T-004-dev.md`), QA 보고(a5d63c2), `handoff/BOARD.md`, `handoff/DECISIONS.md`.

## 0. 먼저 알아둘 경계 (가장 중요)

- T-004의 지식 사전 `config/known_concepts.json`에 든 12개(transformer, lora, agent …)는 **합성 초안**(`provenance: initial_synthetic_draft`)입니다. **사용자가 아는 개념이 아닙니다.**
- 사용자 답변(DECISIONS D-015 확정 절)으로 **실제 기지식 5개**가 확정됐습니다: 환각, 프롬프트 엔지니어링, 컨텍스트 윈도우, RAG, 임베딩. 수준은 "기초 완료, 중급 초입".
- 이 5개를 config에 반영하고 alias(영문 표기 등)를 다루는 일은 **후속 T-006에서 진행 예정**입니다. 이 브랜치의 config는 아직 합성 12개입니다(T-006 반영 여부는 이 문서 작성 시점에 확인 안 됨).
- "신개념에 쉬운 한국어 뜻풀이를 붙이는 기능"은 후속 T-011/T-012 예정입니다. **지금 코드에는 뜻풀이 생성이 없습니다.**
- 이 코드가 증명하는 것은 "JSON의 모양과 내부 규칙이 맞는가"뿐입니다. **LLM 성능, 자연어 전체의 의미, 한국어 뜻풀이 품질은 검증된 바 없습니다.**

## 1. JSON 계약이란?

LLM이 분석 결과를 내놓으면 "이런 칸이 있고, 이런 값만 넣을 수 있다"는 **계약서**와 대조해 검사합니다. 계약에 어긋나면 저장 전에 거부합니다. 그 계약서가 `AnalysisResult`(버전 1)입니다.

주요 칸: `schema_version`, `platform`, `post_id`, `track`, `status`, `source_text`, `hold_reason`, `summary`, `category`, `tags`, `event_id`, `evidence_terms`, `new_concepts_detected`, `concept_usage`, `actionable_idea`, `is_pure_noise`. 코드상 필수 칸은 16개입니다(개발 보고는 "15개", QA는 "16개"라고 적어 서로 다름. 코드를 세면 16).

- `null`이 허용되는 칸은 `hold_reason`, `event_id` 둘뿐.
- 모르는 칸(`extra`)이 끼면 거부(`extra="forbid"`).
- 플랫폼 7종 중 `gallery`는 `track="gallery"`, 나머지 6종은 `track="standard"`만 가능.

## 2. pydantic strict와 "Literal bool 함정"

**pydantic**은 JSON 모양을 검사하는 파이썬 라이브러리입니다. 기본값은 너그러워서 `"1"`을 숫자 1로, `"true"`를 참으로 바꿔주기도 합니다(강제 변환). 계약 검사에서는 위험하므로 `strict=True`로 끕니다.

함정: 파이썬에서 `True == 1`이고 `1.0 == 1`입니다. 그래서 "값이 1이어야 함"(`Literal[1]`)이라고만 써도 `True`나 `1.0`이 통과합니다. 개발자는 이를 **실측으로 확인**했고, `_exact_int`가 `type(value) is int`인 경우만 허용하도록 막았습니다(`schema_version`, 사전의 `schema_version`). `is_pure_noise`는 strict bool이라 `1`, `"true"`가 거부됩니다(QA 블랙박스로 확인).

## 3. READY / HOLD, 그리고 순수 잡담(is_pure_noise)

| | 뜻 | 규칙 |
|---|---|---|
| READY | 분석 완료 | `hold_reason=null`, 원문이 공백뿐이면 안 됨. standard는 요약 정확히 3줄, gallery는 0~3줄 |
| HOLD | **분석 보류**(예: 본문이 비었고 OCR 대기) | `hold_reason` 필수, 분석 칸 8개(요약·태그 3종·근거 단어·신개념·활용·아이디어) 모두 비움, `event_id=null`, `is_pure_noise=false` |
| 순수 잡담 | 분석은 했는데 **배울 개념이 없는 글** | `is_pure_noise=true`는 READY에서만. 근거 단어·신개념·활용·아이디어 4칸이 비어야 함 |

핵심 차이: HOLD는 "아직 판단 못 함", 순수 잡담은 "판단했더니 잡담". 그래서 HOLD에 `is_pure_noise=true`를 쓰면 거부합니다. 또 잡담이라고 하면서 근거 단어를 지어내는 "환각"도 막습니다.

## 4. 원문 근거 검사와 사전 대조는 "별도 호출"

1. **모델 검증**(객체를 만들 때 자동): `evidence_terms`, `new_concepts_detected`의 각 단어가 `source_text`에 대소문자 무시로 실제 들어 있는지, 중복 없는지, `new_concepts_detected ⊆ evidence_terms`인지. HOLD여도 항상 검사합니다.
2. **사전 대조**(직접 호출): `result.validate_known_concepts(known)`. 신개념 목록에 이미 사전에 있는 단어가 있으면 `ValueError`.

왜 분리? 원문 검사는 결과 하나만으로 가능하지만, 사전 대조는 "누구의 사전인가"가 필요해 바깥에서 주입해야 하기 때문입니다. 근거 단어가 모두 신개념일 필요는 없습니다(아는 단어도 근거가 될 수 있음). 비교는 `strip().casefold()`로 하되 출력 문자열은 바꾸지 않습니다.

## 5. 의존성

`pydantic>=2.7,<3`을 **직접 의존성**으로 선언했습니다. 원래 lock에 pydantic 2.14.3이 있었지만 `mcp` 선택 패키지의 간접 의존성이라, 선택 패키지 없이 설치해도 이 모듈이 import되도록 직접 선언했습니다(개발 보고). lock 변경은 `ai-raider` 항목 2줄입니다.

## 6. 장단점과 대안

- 장점: 잘못된 모양을 저장 전에 일찍 막음, `model_json_schema()`로 스키마 문서 자동 생성, 오류 메시지가 구체적.
- 단점: 형식만 검증합니다. 요약이 사실인지, 분류가 맞는지, `concept_usage` 문장 전체가 원문에 근거하는지는 모릅니다(spec상 후속 Evaluator 책임). 글자 수 임계값도 없음. 부분 문자열 검사라 짧은 단어가 우연히 다른 단어 안에 들어 있어도 통과할 수 있음(이 점은 테스트로 확인 안 됨).
- 대안(이 프로젝트가 채택하지 않음): 직접 `dict`를 if문으로 검사(코드가 길고 오류 쉬움), `dataclass`+수동 검증, JSON Schema 라이브러리 단독 사용(교차 규칙 표현이 어려움). 다만 이들과 실제 비교 실험은 하지 않았습니다.

## 7. 파일과 공개 API 예시

- `core/analysis_schema.py`: 모델·검증기. import만으로 파일 읽기/쓰기/네트워크 없음.
- `config/known_concepts.json`: 현재 합성 12개 초안(T-006에서 사용자 5개로 교체 예정).
- `tests/test_analysis_schema.py`(S1 단위 47개), `tests/blackbox/test_t004_analysis_schema.py`(S2 블랙박스 21개).

```python
from core.analysis_schema import AnalysisResult, load_known_concepts

known = load_known_concepts("config/known_concepts.json")  # 없는 파일/깨진 JSON은 예외 그대로
result = AnalysisResult.model_validate_json(json_text)      # 모양·원문근거 검사(실패 시 ValidationError)
result.validate_known_concepts(known)                       # 별도 호출: 이미 아는 단어를 신개념으로 썼나
```

spec 예시(READY gallery): `source_text='transformer 어텐션 실습'`, `evidence_terms=['transformer','어텐션']`, `new_concepts_detected=['어텐션']` → 원문에 있고 부분집합이라 통과, 단 합성 사전에 `어텐션`이 없어야 사전 대조도 통과.

## 8. 숫자는 시점마다 다릅니다 (합산하지 마세요)

| 시점/브랜치 | 수치 | 출처 |
|---|---|---|
| 개발 브랜치 t-004-dev, 시작 전 | 131개 | 개발 보고 |
| 개발 브랜치, 완료 후 | 178개 (신규 47) | 개발 보고 |
| QA 브랜치 | 199개(기본 환경 skip 11, extras 포함 skip 0) | QA 보고 |
| 병합 df7c360 이후 | 199개, skip 0 | BOARD(S0 재실행) |

각 줄은 서로 다른 시점의 전체 합계이며 더하면 안 됩니다. T-005의 164개는 T-004가 합쳐지지 않은 다른 브랜치 수치입니다. 이 문서 작성 중에는 테스트를 다시 돌리지 않았습니다.

## 9. 지금까지 검증된 것 / 아닌 것

- 검증됨(보고 기준): 모양·타입·교차 규칙이 합성 테스트 데이터에서 의도대로 동작.
- gold 검증: 합성 gold 샘플의 `known_concepts`와 config 초안의 집합 일치. gold의 `expected.analysis`는 부분 정답이라 새 JSON 틀로 파싱된다고 주장하지 않음.
- **확인 안 됨**: 실제 분석 모델(LLM)이 이 틀에 맞는 JSON을 안정적으로 내는지, 분류 정확도, 문장 의미 근거성, 한국어 뜻풀이 품질, 사용자 5개 반영 후 동작.

## 서술형 문제

1. `schema_version`에 `True`가 들어오면 왜 `Literal[1]`만으로는 부족하고, 이 코드는 어떻게 막았나요?
2. HOLD와 순수 잡담의 차이를 설명하고, 각각 `is_pure_noise`와 분석 칸이 어떻게 되어야 하는지 쓰세요.
3. 원문 근거 검사와 사전 대조를 왜 따로 호출하나요? 또 이 둘이 통과해도 확인되지 않는 것 두 가지를 쓰세요.

## 모범답안

1. 파이썬에서 `True == 1`, `1.0 == 1`이라 `Literal[1]`이 이를 통과시킵니다(개발자가 실측). 그래서 `_exact_int`가 `type(value) is int`일 때만 허용하도록 BeforeValidator를 붙였습니다. bool·float·숫자 문자열 모두 거부됩니다.
2. HOLD는 아직 분석하지 못한 보류(예: 본문 비고 OCR 대기)로 `hold_reason` 필수, 분석 칸 전부 비움, `event_id=null`, `is_pure_noise=false`여야 합니다. 순수 잡담은 READY로 분석을 마쳤으나 배울 개념이 없는 글로 `is_pure_noise=true`이고 근거 단어·신개념·활용·아이디어 4칸이 비어야 합니다(요약·태그는 허용).
3. 원문 검사는 결과 하나로 판단되지만 사전 대조는 외부 사전(누구의 지식인지)이 있어야 해서 `validate_known_concepts(known)`로 분리했습니다. 통과해도 확인 안 되는 것: 요약·`concept_usage` 같은 문장 전체의 의미적 근거성, 실제 LLM의 분류 정확도·한국어 뜻풀이 품질(그 밖에 현재 사전이 합성 12개라 사용자 실제 지식 5개 기준 동작도 T-006 전까지 확인 안 됨).
