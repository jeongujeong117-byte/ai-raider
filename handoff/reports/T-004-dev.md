# T-004 · 분석 결과 JSON 스키마 및 지식 사전 초안 — 구현 보고 (S1)

모델 claude-sonnet-5-5 / high. 브랜치 `jeongujeong117-byte/t-004-dev`.

## 변경 파일
`core/analysis_schema.py`(신규), `config/known_concepts.json`(신규), `tests/test_analysis_schema.py`(신규, 47개), `pyproject.toml`(직접 의존성 `pydantic>=2.7,<3` 한 항목), `uv.lock`(pydantic 직접 의존 2줄), 본 보고서. 그 외 변경 없음(기존 테스트/gold/Store/수집기/MCP/BOARD/DECISIONS 미변경).

## 공개 API
`core.analysis_schema`: `AnalysisResult`, `Tags`, `KnownConcepts`, `load_known_concepts(path)`, `AnalysisResult.validate_known_concepts(known)`.
- 모델은 `extra='forbid'`, `strict=True`. `schema_version`은 `Literal[1]`이 `True`/`1.0`을 통과시키는 것을 확인(실측)하여 정확한 `int`만 허용하는 BeforeValidator를 추가.
- 모든 문자열 목록 원소/식별 문자열은 공백 아님(값을 strip/변형하지 않고 거부만). `hold_reason`·`event_id`만 nullable.
- 용어 비교(중복·부분집합·원문 존재·사전 대조)는 `strip().casefold()` 키 사용. 출력값은 원본 그대로 유지.
- 원문 근거/부분집합/중복은 모델 검증이 항상 수행(HOLD 포함). 사전 대조는 `validate_known_concepts` 별도 호출.
- import 시 I/O 없음. `load_known_concepts`는 지정 파일을 읽기만 하며 FileNotFoundError / ValidationError(JSON 손상 포함)를 그대로 전파, 파일을 만들거나 쓰지 않음.

## 해석한 항목 (spec 문구 보강)
- spec이 목록 원소 비공백을 tags/summary 등 일부에만 명시했으나, evidence_terms·concept_usage·actionable_idea·summary(gallery 포함) 전부 공백 원소를 거부하도록 통일했다.
- 순수 잡담(is_pure_noise=true) READY에서 summary/tags는 제한하지 않았다(spec은 4개 필드만 비움을 요구).
- READY 판정에서 `source_text` 공백만 금지하며 글자 수 임계값은 두지 않았다.

## 의존성 근거
기존 `uv.lock`에 pydantic 2.14.3이 `mcp` extra의 간접 의존성으로만 있었다. 기본 설치(extra 없음)에서도 `core.analysis_schema`가 import되어야 하므로 직접 의존성 `pydantic>=2.7,<3`를 선언했다(v2 API 사용: ConfigDict, model_validator, AfterValidator/BeforeValidator). `uv lock` 결과 lock 변경은 `ai-raider` 패키지 항목의 pydantic 2줄뿐이며 버전 고정은 그대로 2.14.3.

## 검증 (명령 / 종료코드 / 수치)
| 명령 | rc | 결과 |
|---|---|---|
| 시작 전 `uv run python -m unittest discover -s tests` | 0 | 131 tests OK (skipped=11) |
| 시작 전 `uv run --extra processing --extra mcp python -m unittest discover -s tests` | 0 | 131 tests OK, skip 0 |
| 신규 `uv run python -m unittest tests.test_analysis_schema` | 0 | 47 tests OK |
| 완료 후 `uv run python -m unittest discover -s tests` | 0 | 178 tests OK, skip 표시 없음 |
| 완료 후 `uv run --extra processing --extra mcp python -m unittest discover -s tests` | 0 | 178 tests OK, skip 0 |
| `git diff --check` | 0 | CRLF 경고만 |

주의: 완료 후 기본 실행에서 skip이 0으로 표시된 것은, 시작 전 기본 실행(skipped=11) 이후 extra 포함 실행으로 같은 .venv에 extra 패키지가 남아 있었기 때문으로 추정한다(미확인). 즉 "extra 없는 환경에서 178 중 skip 수"는 이번에 새로 측정하지 못했다. 신규 47개는 extra에 의존하지 않는다(pydantic만 사용).

신규 테스트 범위: READY gallery/standard, HOLD(standard·gallery), 순수 잡담, JSON 왕복(dict·JSON 텍스트), model_json_schema 생성(additionalProperties=false, required 15개), 키 누락/추가/태그 키 오류, null 허용 범위, bool·문자열·float 강제 변환 거부(dict 및 JSON 텍스트 경로), 버전/플랫폼/track/status 오류, track-platform 불일치, 공백 문자열, summary 줄 수, HOLD 필수/금지 규칙, 원문에 없는 개념, 대소문자 부분 문자열, 대소문자 중복, 부분집합 위반, 순수 잡담 환각 4필드, 긴 한글(약 14만자)/이모지/`ß`↔`SS` casefold, 값 불변, 사전 등재 신개념 거부(별도 호출), 사전 모델 검증(빈 목록·중복·provenance·버전 bool), 임시 fixture 기반 load(정상·없는 파일·손상 JSON·계약 위반·디렉터리; 파일 미생성/내용 불변), config 초안.

## gold 대조
`config/known_concepts.json`의 concepts 12개 == `tests/blackbox/fixtures/gold_samples.json`의 `known_concepts` 집합(테스트 `test_config_loads_and_matches_gold`). provenance는 `initial_synthetic_draft`이며 사용자 실제 지식 확인으로 표현하지 않았다. gold의 `expected.analysis`는 부분 정답이므로 새 envelope로 파싱된다고 주장하지 않으며 파싱도 시도하지 않았다.

## 미검증
- 본문 충분성 임계값, LLM 분류 정확도, summary/concept_usage/actionable_idea 문장의 의미적 근거성은 스키마로 입증하지 않는다(후속 Evaluator).
- 갤러리 category 체계(프롬프트 설계)는 후속. category는 비공백 문자열만 검증.
- metrics는 계약에 포함하지 않았다.
- 실제 사용자 DB·.private는 읽지 않았고, 모든 데이터는 합성/임시 fixture다.
