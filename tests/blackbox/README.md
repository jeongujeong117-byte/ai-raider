# 블랙박스 통합 검증 및 평가 정답 데이터셋 (T-003)

본 디렉터리는 AI Raider 시스템의 외부 계약 준수, 경계 조건, 오류 격리 및 향후 분석 파이프라인 평가를 위한 합성 정답(Gold Standard) 데이터셋과 재실행 가능한 블랙박스 테스트 틀을 제공합니다.

실제 사용자 계정 정보, 세션 쿠키, 비공개 `.private` 토큰을 일절 참조하지 않으며, 모든 데이터는 RFC 2606 예약 도메인(`example.com`) 기반의 순수 합성 데이터(`provenance="synthetic"`)로 구성되어 있습니다.

> [!IMPORTANT]
> **검증 대상 명시**: 본 테스트 스위트의 카테고리, 근거 용어, 신개념 및 환각 검증은 **AI/LLM 모델의 런타임 추론 출력을 검증하는 것이 아닙니다**. 향후 분석 하네스가 신뢰할 수 있도록, **정답 데이터셋(`gold_samples.json`) 자체의 수작업 기준안이 원문 근거와 사전 정의(`known_concepts`)에 엄격히 부합하는지 내부 무결성과 일관성을 검증**하는 것입니다.

---

## 1. 정답 데이터셋 구조 (`fixtures/gold_samples.json`)

`fixtures/gold_samples.json`은 UTF-8 인코딩의 JSON 문서로, 최상위에 스키마 버전과 도메인 공통 개념 목록(`known_concepts`), 그리고 15개의 검증 사례(`samples`)를 정의합니다.

### 최상위 규격
```json
{
  "schema_version": 1,
  "known_concepts": ["transformer", "lora", "agent", "ocr", "asr", "diffusion", "fine-tuning", "rag", "vector_db", "npu", "vit", "checkpoint"],
  "samples": [...]
}
```

### 개별 샘플 필드 규격
- `id`: 샘플별 고유 식별자 (예: `sample-ig-null-likes`).
- `description`: 테스트 사례의 목적 및 검증 시나리오 설명.
- `provenance`: `"synthetic"` (합성 데이터 보증).
- `tags`: 플랫폼, 기능, 경계 조건을 식별하기 위한 태그 배열.
- `input`: `Store.save()`에 전달되는 표준 포스트 딕셔너리 (`platform`, `post_id`, `handle`, `url`, `posted_at`, `text`, `metrics`, `media`, `raw`). 대용량 테스트는 `repeat_spec`, 모의 오류 테스트는 `simulated_error` 메타데이터를 포함.
  - 모든 URL(포스트 URL 및 미디어 URL 전수)은 RFC 2606 예약 도메인(`example.com`, `example.org`, `example.net`)만 허용.
- `expected`: 공개 인터페이스를 통해 자동 검증 가능한 기대값.
  - `dedup_key`: 플랫폼별 고유 중복 키 (`{platform}:{post_id}`). 고유 `id`와 명확히 구분됨.
  - `preserve_null_metrics`: `metrics.likes`의 None 보존 여부 (0으로의 강제 변환 방지, boolean 타입 검사).
  - `expected_likes`: 기대되는 likes 수치 (`null` 또는 정수 int 타입, false 오인 방지).
  - `stored_text`: 저장소 저장 후 반환되어야 하는 텍스트.
  - `in_window`: 고정 평가 기간(`2026-08-09` ~ `2026-11-09` KST) 내 포함 여부 boolean.
  - `analysis`: 미래 분석 파이프라인 검증용 수작업 기준안.
    - `category`: 콘텐츠 분류 (예: `tutorial`, `model_release`, `hardware`, `code_repository`, `pure_noise`, `practical_experiment`, `unclassified_media`).
    - `evidence_terms`: 원문 본문/전사/OCR에서 직접 추출된 근거 어휘 배열.
    - `new_concepts_detected`: `known_concepts` 사전에 정의되지 않은 신규 기술 어휘 배열 (원문 근거 및 사전 비포함 동시 검증).
    - `applied_usage`: 잡담 속 기술 쓰임새/실습 아이디어가 원문에 있을 경우 명시.
    - `is_pure_noise`: 순수 잡담/무관 데이터 여부 (`true`/`false`).
    - `notes`: 분석 근거 메모.

---

## 2. 수록 정답 샘플 목록 및 기대값 근거

총 15개의 합성 사례가 수록되어 있으며 7개 지원 플랫폼 전체를 포괄합니다:

| 샘플 ID | 플랫폼 | 핵심 시나리오 | 기대값 근거 및 검증 포인트 |
|---|---|---|---|
| `sample-ig-null-likes` | instagram | `likes=None` 보존 | Instagram API 미제공 메트릭이 DB에 `None`으로 보존되는지 검증 (0 오염 방지) |
| `sample-ig-zero-likes` | instagram | `likes=0` 보존 | 실제 0개의 좋아요를 받은 포스트가 `0`으로 정상 저장되는지 검증 (`None`과 구분) |
| `sample-x-empty-text-media` | x | 빈 본문 + 미디어 첨부 | 캡션이 없는 미디어 전용 포스트가 `text=""` 및 미디어 목록 온전히 유지되는지 검증 |
| `sample-youtube-transcription` | youtube | 음성 전사(ASR) 데이터 | 자막/전사 텍스트가 `raw.transcript`에 유지되며 RAG/Vector DB 분석 근거로 활용 가능함을 검증 |
| `sample-news-ocr` | news | 이미지 인포그래픽 OCR | 본문 외 이미지 내 텍스트(`NPU ...`)가 OCR 메타데이터로 안전하게 유지됨을 검증; `Semiconductor` 신개념 검출 |
| `sample-boundary-before-kst` | gallery | 2026-08-09 00:00 KST 직전 (1초 전) | `2026-08-08T14:59:59+00:00` (UTC)로 `window()` 구간 `[begin, finish)` 바깥(`in_window=False`) 판정 |
| `sample-boundary-exact-kst` | gallery | 2026-08-09 00:00 KST 정각 | `2026-08-08T15:00:00+00:00` (UTC)로 `window()` 구간 시작점에 정확히 포함(`in_window=True`) 판정 |
| `sample-boundary-after-kst` | gallery | 2026-08-09 00:00 KST 직후 (1초 후) | `2026-08-08T15:00:01+00:00` (UTC)로 `window()` 구간 내부(`in_window=True`) 판정 |
| `sample-recollect-original` | huggingface | 동일 `(platform, post_id)` 재수집 1차 | Hugging Face 모델 1차 수집 (`post_id=hf-synth-009`, likes=15); `weights` 신개념 검출 |
| `sample-recollect-updated` | huggingface | 동일 `(platform, post_id)` 재수집 2차 | 동일 post_id로 재수집 시 DB 레코드 수 증가 없이 기존 레코드가 갱신(`likes=50`, 텍스트 업데이트)되는지 검증 |
| `sample-github-large-unicode` | github | 대용량 유니코드 본문 | JSON 파일 팽창을 막기 위해 `repeat_spec`으로 정의하고 테스트 실행 시 200회 반복(10,000자 이상, 이모지 포함) 확장 저장/조회 검증 |
| `sample-rate-limit-error` | x | Mock 429 레이트리밋 오류 | 비공개 토큰(`SECRET_API_KEY_NEVER_LEAK`)이 작업 오류 메시지에 노출되지 않고 마스킹되는지 검증 |
| `sample-chatter-with-tech-grounding` | gallery | 잡담 속 실제 기술 실습 | "라면 먹고 transformer 어텐션 실습"처럼 일상 잡담 속 기술 내용을 원문 근거(`transformer`, `어텐션`)에 연결; `어텐션` 신개념 검출 및 `applied_usage` 바인딩 |
| `sample-pure-chatter-noise` | gallery | 순수 일상 잡담 (노이즈) | 날씨/등산 등 기술과 무관한 글에서 환각으로 기술 키워드를 지어내지 않고 `is_pure_noise=True`, `evidence_terms=[]`로 분류 |
| `sample-x-new-concept-and-idea` | x | 신개념 및 실습 아이디어 | 잡담 속 신개념 `flash_attention`과 온디바이스 `agent` 적용 아이디어를 원문에 바인딩; `flash_attention` 신개념 검출 |

---

## 3. 실행 방법

### 전체 테스트 실행 (상위 tests 디렉터리)
`tests/blackbox/__init__.py`가 추가됨에 따라, 최상위 `discover -s tests` 실행 시 블랙박스 테스트(구조 7개 + 정답 샘플 12개)가 함께 자동 검색되어 실행됩니다.
```bash
uv run python -m unittest discover -s tests -v
```

### 블랙박스 전용 테스트 실행
```bash
uv run python -m unittest discover -s tests/blackbox -v
```

### T-000 구조 및 통합 테스트 개별 실행
```bash
uv run python -m unittest tests/blackbox/test_t000_structure.py -v
```

### T-003 합성 정답 샘플 테스트 개별 실행
```bash
uv run python -m unittest tests/blackbox/test_gold_samples.py -v
```

---

## 4. 현재 자동 검증 범위 vs 향후 하네스 검증 잔여

### 현재 자동 검증 범위 (PASS)
1. **스키마 및 계약 무결성**: 스키마 버전 1, 필수 키 존재 여부, 고유 sample ID 분리, 7개 플랫폼 전수 포함 확인.
2. **엄격한 URL 호스트 검증 및 부정 사례 방어**:
   - `urllib.parse.urlsplit` 기반으로 `input["url"]` 및 미디어 URL 전체를 검사하여 `example.com.evil.invalid`, `evil.com/?q=example.com` 등 서브스트링 우회 공격을 완전 차단.
3. **전체 샘플 기대값 일관성 대조**:
   - `expected_likes`, `preserve_null_metrics`, `stored_text`, `in_window`를 개별 하드코딩이 아닌 fixture 전체에 대해 `Store` 및 `raider.window` 공개 계약과 일괄 대조.
   - boolean `False`가 정수 `0`으로 오인 통과하지 않도록 엄격한 타입(`type is bool`, `type is int`) 검사 적용.
4. **저장소(Store) 보존 규격**:
   - `metrics.likes`의 `None`과 `0`의 독립적 저장 및 역직렬화 무결성.
   - 빈 본문(`text=""`)과 미디어 첨부물의 누락 없는 유지.
   - 동일 `(platform, post_id)` 재수집 시 primary key upsert를 통한 중복 방지 및 필드 갱신.
   - 대용량 유니코드 및 다국어 텍스트의 잘림(truncation) 없는 보존.
5. **수집 윈도우 KST 경계 검증**:
   - `raider.window("2026-08-09", "2026-11-09")` 호출 시 KST 기준 시작점(UTC `2026-08-08T15:00:00`) 1초 전, 정각, 1초 후의 정확한 반열린 구간(`[begin, finish)`) 판정.
6. **오류 격리 및 민감 정보 마스킹**:
   - 모의 레이트리밋(429) 예외 발생 시 작업 상태 `error` 전이 및 Bearer 토큰 마스킹.
7. **정답 기준안 내부 일관성 검증 (모델 출력 검증 아님)**:
   - `expected.analysis` 내 근거 키워드(`evidence_terms`)가 실제 원문/전사/OCR에 존재하는지 확인.
   - `known_concepts` 사전에 없는 어휘는 `new_concepts_detected`로 자동 분류되고, 사전에 있는 어휘는 제외되는지 검증.
   - 순수 잡담(`is_pure_noise=True`)에 환각 키워드가 할당되지 않았는지 확인.
   - 잡담 속 기술 쓰임새/실습 아이디어가 `applied_usage`로 원문 텍스트에 올바르게 연결되었는지 검증.

### 향후 하네스 검증 잔여 (미구현 분석 파이프라인 연계)
- **자연어/LLM 카테고리 분류기 하네스**: `expected.analysis.category` 및 `is_pure_noise` 판정 모델이 정답 데이터셋을 입력받아 분류 정확도(F1-score)를 산출하는 하네스는 현재 단계에서 구현되지 않았으며, 가짜 모의 함수로 성공을 위장하지 않았습니다.
- **실제 미디어 OCR 및 Whisper 음성 인식 모델 구동**: 합성 샘플에 수록된 `raw.transcript` 및 `media.ocr_text`는 기준값으로 검증되었으며, 실제 GPU/모델 추론을 통한 엔드투엔드 파이프라인 검증은 추후 하네스 연계 작업에서 수행됩니다.
