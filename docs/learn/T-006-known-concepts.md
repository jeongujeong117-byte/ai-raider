# T-006 학습: 사용자 확정 지식 5개와 동의 표기(alias)

대상: 기초를 마치고 중급에 막 들어선 비전공자. 기준: develop `38f911b`(T-006 개발 283d62e + QA 298ece3 통합), `core/analysis_schema.py`, `config/known_concepts.json`, `handoff/specs/T-006.md`, `handoff/reviews/T-006-qa.md`, DECISIONS D-015/D-019. 먼저 `T-004-analysis-schema.md`를 읽으면 좋습니다.

## 1. 무엇이 바뀌었나 (이전 → 현재)

| | T-004 시점(역사) | 현재(T-006 이후) |
|---|---|---|
| config 내용 | 합성 12개(transformer, lora, agent, ocr, asr, diffusion, fine-tuning, rag, vector_db, npu, vit, checkpoint) | 사용자 확정 5개 |
| provenance | `initial_synthetic_draft` | `user_confirmed` |
| aliases | 없음 | 있음(기본값 `{}`) |
| 합성 12개 | config 그 자체 | `tests/blackbox/fixtures/gold_samples.json`에 **그대로 보존**, 테스트용 |

합성 12개는 처음부터 사용자 지식이 아니었습니다. 사용자가 직접 "설명할 수 있다"고 고른 것은 **환각, 프롬프트 엔지니어링, 컨텍스트 윈도우, RAG, 임베딩** 5개입니다(수준 판단: 기초 완료, 중급 초입). 이 변경은 사용자가 승인한 계약 변경이며, 기존 타입·근거 공격 테스트를 느슨하게 한 것이 아닙니다(QA 확인).

## 2. canonical과 alias

- **canonical(대표 표기)**: `concepts`에 적힌 이름. 예: `RAG`.
- **alias(동의 표기)**: 같은 개념의 다른 표기. 현재 config:
  - 환각 → hallucination
  - 프롬프트 엔지니어링 → prompt engineering
  - 컨텍스트 윈도우 → context window
  - RAG → retrieval-augmented generation, retrieval augmented generation, 검색 증강 생성
  - 임베딩 → embedding, embeddings

규칙(코드로 강제): alias의 키는 `concepts`에 있는 이름이어야 하고, alias 목록은 비어 있으면 안 되며, 공백뿐인 값 금지. `strip().casefold()`(앞뒤 공백 제거+대소문자 통일) 기준으로 canonical끼리·alias끼리·서로 간에 겹치거나 충돌하면 거부합니다. aliases를 생략하면 `{}`라서 옛 형식 JSON도 읽힙니다. alias는 **같은 5개 개념의 표기만** 늘리며 사용자 지식을 넓히지 않습니다.

## 3. 원문 검사와 사전 대조는 여전히 별도 호출

1. 모델 검증(객체 생성 시): `evidence_terms`/`new_concepts_detected`가 `source_text`에 실제로 있는지, 중복·부분집합 규칙. 원문에 **나온 그대로의 표면형**을 검사하며 값은 바꾸지 않습니다.
2. 사전 대조(직접 호출): `result.validate_known_concepts(known)`. 이제 `known.known_keys()`(canonical+alias 전부)로 비교하므로, 원문에 `Hallucination`이나 ` EMBEDDINGS `가 나와도 "이미 아는 것"이라 신개념으로 올리면 `ValueError`입니다(QA에서 대소문자·공백 변형도 못 빠져나감을 확인).

`evidence_terms`(근거 단어)에는 아는 단어를 넣어도 됩니다. 막는 것은 아는 단어를 **신개념으로** 올리는 것뿐입니다.

## 4. 미선택 5개와 그 밖의 개념은 신개념 후보로 허용

사용자가 고르지 않은 **파인튜닝, MCP, LoRA, 양자화, 에이전트 하네스**(및 fine-tuning, Model Context Protocol, low-rank adaptation, quantization, agent harness 같은 표기)는 사전에 넣지 않았습니다. 그래서 원문에 근거가 있으면 `new_concepts_detected`에 올릴 수 있고 사전 대조도 통과합니다. 사전에 없는 다른 용어(예: KV cache)도 같습니다. 원문에 없는 개념은 여전히 거부됩니다.

## 5. 합성 gold 12개는 왜 남겼나

합성 12개는 테스트 자료로 유용합니다. 그래서 gold fixture에 두고, 테스트가 이를 `initial_synthetic_draft` 모델로 **별도로** 읽습니다. QA의 직교 확인: 합성 모델에서는 `lora`가 기지식·`환각`이 신개념, 사용자 모델에서는 반대입니다. 두 사전은 섞이지 않습니다.

## 6. 아직 없는 것 (후속)

- **자동 신개념 후보 추출**: 지금은 "이미 알려진 단어가 신개념에 섞이지 않았나" 검사만 합니다. 원문에서 후보를 뽑는 기능은 T-011/T-012 예정입니다.
- **쉬운 한국어 뜻풀이 생성**: 후속 T-011/T-012. 뜻풀이를 사용자 기지식으로 자동 등록하지 않는다는 방침(D-015)만 정해졌습니다.
- 실제 분석 모델(LLM)이 이 계약에 맞는 JSON을 내는지, 분류 정확도, 문장 의미는 **확인 안 됨**. 현재 검증은 합성/임시 데이터의 **계약(gold 포함) 검증**이지 실제 분석 모델 검증이 아닙니다.
- 사용자 지식이 늘면 config를 어떻게 갱신하는지의 운영 절차: 확인 안 됨.

## 7. 테스트 수 (시점별, 합산 금지)

| 시점/브랜치 | 수치 | 출처 |
|---|---|---|
| T-004 완료 기준(aa08b38) | 199개 | T-006 QA |
| T-006 개발 283d62e | 216개(+17, 기본 환경 skip 11) | 개발 보고 |
| T-006 QA 브랜치 | 231개: 기본 환경 skip 11, extras 포함 skip 0 | QA 보고 |
| 통합 38f911b 전후 | 231개, skip 0, exit 0 | D-019(S0 확인) |

개발 보고는 신규 단위 파일을 17개로 적었으나 QA 실측은 16개(+기존 파일 1개 증가)입니다. 위 수치는 각각 그 시점의 전체 합계이며 서로 더하지 않습니다. 이 문서 작성 중 테스트는 재실행하지 않았습니다.

## 8. 코드 예시

```python
from core.analysis_schema import load_known_concepts

known = load_known_concepts("config/known_concepts.json")
known.provenance          # "user_confirmed"
"hallucination" in known.known_keys()   # True (alias)
result.validate_known_concepts(known)   # new_concepts_detected에 환각/hallucination 등이 있으면 ValueError
```

## 서술형 문제

1. canonical과 alias의 차이를 쓰고, 원문에 `Embeddings`가 나왔을 때 이를 신개념으로 올리면 왜 거부되는지 설명하세요.
2. T-004 시점의 합성 12개와 현재 사용자 5개는 무엇이 다르며, 합성 12개를 지우지 않고 남긴 이유는 무엇인가요?
3. 이번 변경 후에도 아직 되지 않는 것(후속 작업) 두 가지와, 현재 테스트가 입증하지 않는 것 한 가지를 쓰세요.

## 모범답안

1. canonical은 `concepts`의 대표 이름(예: 임베딩), alias는 같은 개념의 다른 표기(embedding, embeddings)입니다. `validate_known_concepts`가 canonical+alias 전체를 `strip().casefold()`로 비교하므로 `Embeddings`는 이미 아는 개념의 표기로 판정돼 `ValueError`가 납니다. 단 근거 단어(`evidence_terms`)로는 쓸 수 있습니다.
2. 합성 12개는 사용자가 고른 지식이 아닌 테스트용 초안(`initial_synthetic_draft`)이고, 현재 5개는 사용자가 확정한 지식(`user_confirmed`)입니다. 합성 12개는 gold fixture에 보존해 별도 모델로 검증하는 용도로 남겼고, 두 사전은 서로 섞이지 않습니다(예: `lora`는 합성에선 기지식, 사용자 사전에선 신개념 후보).
3. 후속: 원문에서 신개념 후보를 자동 추출하는 기능, 쉬운 한국어 뜻풀이 생성(둘 다 T-011/T-012 예정). 입증 안 된 것: 실제 LLM이 계약에 맞는 JSON을 안정적으로 내는지, 분류 정확도, 문장 전체의 의미 근거성 중 하나.
