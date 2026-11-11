# T-006-dev 보고서 · 사용자 지식 5개 및 합성 사전 분리

브랜치: jeongujeong117-byte/t-006-dev (S1 sonnet-5-5/medium). master 병합/push 없음. 별도 QA 전 병합 금지.

## 개정 이유와 계약 변경 (사용자 승인 D-013)
- 이전 계약(T-004): config = provenance `initial_synthetic_draft`, 합성 12개(gold fixture 동등).
- 새 계약: config = schema_version 1, provenance `user_confirmed`, concepts 정확히 5개
  [환각, 프롬프트 엔지니어링, 컨텍스트 윈도우, RAG, 임베딩] + aliases.
- 이는 사용자 승인된 계약 변경이며 기존 타입/근거 공격 테스트를 완화한 것이 아니다.

## 변경 파일
- core/analysis_schema.py: KnownConcepts.provenance = Literal[initial_synthetic_draft, user_confirmed];
  `aliases: dict[str, list[str]]`(기본 {}); canonical key는 concepts 기존 원소만, alias 비공백 strict str,
  빈 리스트 거부, canonical/alias 전체에서 strip+casefold 중복/충돌 거부; `known_keys()` 추가;
  validate_known_concepts는 canonical+alias 모두 new_concepts_detected에서 거부(출력값/원문 검증 불변).
  빈 concepts 거부·version/strict/extra 금지 유지.
- config/known_concepts.json: 정확한 5개 + 지정 aliases. 파인튜닝/MCP/LoRA/양자화/에이전트 하네스 및 영문 표현 미등재.
- tests/test_analysis_schema.py: ConfigDraftTests의 gold 동등 테스트를 5개+provenance/aliases 검사로 교체, 합성12 유효성은 gold fixture를 직접 읽어 별도 모델로 유지.
- tests/blackbox/test_t004_analysis_schema.py: test_18(gold 동등 → 새 계약 + 합성12 독립 유지)과 test_16의 "user_confirmed는 잘못된 provenance" 한 건만 새 계약으로 갱신(다른 잘못된 provenance는 계속 거부). 다른 공격 테스트 변경 없음.
- tests/test_known_concepts_user.py (신규, 17개): 정확한 5개/aliases, JSON 왕복, 파일 읽기 전용,
  canonical/동의표기(대소문자·공백 포함) new 거부 및 출력값 불변, 미선택·기타 개념 허용, 원문 없는 개념 거부,
  synthetic12 독립 보존, alias 잘못된 key/type/공백/중복/충돌 거부, 빈 concepts 거부 유지.
- gold_samples.json 미변경.

## 명령/결과
- 기준(HEAD export): `uv run --extra processing python -m unittest discover -s tests` → 199 tests, OK (skipped=11), rc 0.
- 완료: 같은 명령 → 216 tests, OK (skipped=11), rc 0. (+17, skip 증가 없음)
- 중간에 test_16 1건 실패(옛 가정) → 위 개정으로 해결 후 재실행 통과.
- `git diff --check` rc 0 (CRLF 변환 경고만).

## 미검증/한계
- 사전 검사만 구현; 자동 후보 추출은 구현되지 않았다. 한국어 뜻풀이/LLM/새 분석 필드 없음(T-011/T-012).
- aliases는 빈 리스트 값을 거부하도록 했다(스펙에 명시 없음, 보수적 선택).
- `uv sync` 별도 extras 회귀는 `--extra processing`으로 위 한 번 실행했다.
