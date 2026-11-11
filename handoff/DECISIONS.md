# 설계·운영 결정

## D-001 · 2026-11-11 · 통합 및 권한

기준 커밋은 master의 `0be384f`이며 S0 작업 브랜치는 이미 `develop`이다. 브리핑을 원본 바이트 그대로 ROLES.md에 복사했다. S0 수정은 handoff/에 한정한다. master 병합과 원격 push는 별도 사용자 승인 전 수행하지 않는다.

## D-002 · 2026-11-11 · T-000의 경계

기획 7장의 첫 기반 작업으로 저장소·공통 처리와 수집기를 분리한다. 이번 작업에서 DB 스키마, 수집 정책, UI/HTTP 계약, 의존성 버전은 바꾸지 않는다. 루트 모듈은 기존 외부 import와 테스트 patch 지점을 보존하는 호환 계층으로 남길 수 있다. 실제 구현은 core/agents에 두고 중복 복사하지 않는다. 기존 테스트는 그대로 유지한다.

기존에는 instagram/x 수집 함수, 공통 SourceAgent 및 네 Extractor, GithubAgent가 있으므로 이를 분리한다. 새 상태 감시·새 수집 CLI 옵션·MCP·AI 분석은 후속 작업이며 T-000에 섞지 않는다. 독립 모듈 import가 앱 서버나 수집을 자동 시작하지 않아야 한다.

## D-003 · 2026-11-11 · 검증과 병합

S1은 기준·완료 회귀 결과와 로컬 HTTP smoke 결과를 보고한다. S2는 개발 브랜치에서 별도 검증하고 PASS/FAIL 증거를 제출한다. S0는 PASS를 확인한 뒤 전체 회귀를 재실행하고 develop에 병합한다. 실제 Instagram·X 접근은 어떤 검증에도 포함하지 않는다.

## D-004 · 2026-11-11 · 사용자 모델 정책 변경

사용자가 제공한 S0-model-policy.md 전체를 ROLES의 팀 구성 아래 모델 정책으로 추가했다. 기존 역할 프롬프트의 모델 표기보다 이 정책이 우선한다. S1 기본은 Sonnet medium, T-004는 Sonnet high, Phase 2 프롬프트/판정 설계 및 Phase 3 역공학 설계는 Opus high, S3는 Sonnet low다. Antigravity는 자체 모델 설정을 사용한다. 그 외 모든 워커 시작은 model과 effort를 명시하고 spec 머리말에도 기록한다. 표에 없는 설계 판단이 큰 새 작업에 Opus를 쓰려면 먼저 사용자에게 묻는다.

레드팀 2회 반려 시 같은 워크트리에서 retry-of로 Opus high로 승격하고 3회차도 FAIL이면 중단하여 '사람 검토 필요'로 보고한다. 이 규칙이 이전 '3회 초과' 규칙을 대체한다.

T-000 Opus dispatch ctx_8d1667c5e8bd를 사용자 지시로 worker-stop했고 stopped/processAction=closed_agent_terminal을 확인했다. 구현 커밋은 없고 루트 8개 파일 수정 및 미추적 agents/core를 확인했다. 변경은 보존하고 같은 Task·워크트리에서 Sonnet medium으로 재시작한다.

## D-005 · 2026-11-11 · T-000 수락과 병렬 작업 경계

개발 c4783ac와 QA ccec489의 PASS 증거를 확인하고 S0 재검증(회귀 50개+블랙박스 7개) 후 develop에 병합했다. 병합 뒤 동일 전체 테스트도 통과했다. S3는 Sonnet low로 병합 결과 설명만 작성한다.

T-001은 agents/base_supervisor.py에 주입형 상태 감시·제한된 재시도·상태 기록 기반을 구축한다. 기존 수집기와 대시보드 연결은 후속 통합으로 분리하여 T-002와 수정 파일을 공유하지 않는다. 실제 Edge 우회는 이번에 실행/구현하지 않고 callback으로 연결 지점만 제공한다.

T-002는 SQLite mode=ro 기반 stdio MCP 조회만 제공한다. AI 분석과 OCR processing은 구분한다. 현재 분석 이력이 없으면 모두 미분석이며, 미래 post_analyses(platform,post_id) 이력이 있으면 해당 쌍을 제외하는 읽기 계약만 정의한다. 테이블을 생성하지 않는다. MCP 의존성/패키지 설정 수정은 T-002 전용이다.

T-003은 합성 gold dataset과 블랙박스 틀만 소유한다. 미래 분석 정답은 기준안으로 표시하고 미구현 하네스의 성공을 주장하지 않는다. S1-A/S1-B는 최대 2개이며 S2/S3를 합쳐 동시 워커 4개 한도다.
