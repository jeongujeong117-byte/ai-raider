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

## D-006 · 2026-11-11 · T-001 PASS 미수락 및 1차 반려

S2가 7c51734에 PASS를 보고했지만 테스트가 중단 후 fallback 호출 및 임의 reason 복원을 정상 결과로 고정하고 있었다. S0가 직접 재현하여 안전 중단과 고정 reason 계약 위반으로 판정했다. QA는 S0 수락을 대신하지 않는다. 기존 PASS를 FAIL로 정정하고 기대값을 올바르게 기록하도록 요청했다.

S1의 1차 반려 수정 커밋 140fcdf를 받았다. 모델은 Sonnet medium 유지(2회 반려 시 3회차 Opus high). QA는 최초 FAIL 이력을 보존한 뒤 동일 브랜치에서 수정본을 재검증한다. S0 제품 직접 수정은 없으며 최종 QA 전 병합하지 않는다.

## D-007 · 2026-11-11 · T-002 입력 계약 및 1차 반려

원본 1d65fa4에 대한 S2 PASS는 실제 MCP 경계에서 bool과 수치 문자열을 정수로 강제 변환한 동작을 허용하고 있었다. S0가 stdio로 재현하여 선언된 정수 계약 위반으로 미수락·1차 반려했다. 직접 API만 엄격해도 충분하지 않다. S1 수정 6a64b95는 StrictInt/StrictStr를 적용했고 S2 재검증 중이다. SQLite WAL reader의 sidecar 관리와 DB 본문·스키마 변경은 구분하며 최신 WAL 가시성을 유지한다.

## D-008 · 2026-11-11 · T-001 및 T-003 수락

T-001 수정 140fcdf/QA 0f0b8cb는 원본 FAIL 이력을 보존하고 기대값 완화 없이 PASS했다. S0가 재검증 후 develop에 병합했다. T-003은 URL hostname 검증·전체 기대값·지식 사전 기준안 연결 보완본 ff69a03을 재검증 후 수락·병합했다. 분석 정답은 초기 합성 기준안이며 실제 LLM 성능을 입증하지 않는다. 통합 상태에서 전체 98개 및 blackbox 30개 exit 0. T-001의 기존 수집기·대시보드·실제 Edge 연결은 아직 후속 통합이다.

## D-009 · 2026-11-12 · 복구 감사

T-002는 최종 수정 6a64b95/QA be22c81 PASS 후 c647843・b67a261로 이미 develop에 병합됐다. BOARD의 재검증 중 기록을 정정했다. failed Task task_6ee8fa23c2ad는 원본의 잘못된 PASS를 FAIL로 정정한 이력이며, 후속 task_1bfa2b9e91e2 completed로 해결되어 재시도 대상이 아니다.

모든 등록 Git 워크트리 12개의 status가 clean이다. 학습 Task task_fbff03cee131는 현재 completed/dispatch succeeded로 조회됐다. fc27059 문서 두 개를 검토했으나 T-003 69개/19개가 보완 전 수치라는 문구는 보완 후 QA 보고와 달라 정정을 요청한 뒤 수락한다. 첫 send는 consumer_fenced로 전달되지 않았고 run-use로 기존 Run 지휘관 연결을 복구했다.

orca account list에서 Antigravity 활성 계정 jeongujeong117@gmail.com을 확인했다. 계정 보관 파일은 읽지 않았다. T-004 QA 첫 응답/모델 정상 작동은 아직 확인 못 함이며 실제 QA 시작 시 검증한다. 과거 worker의 unverifiable liveness는 실행 중/종료 어느 쪽의 증거로도 쓰지 않는다.

## D-010 · 2026-11-12 · T-004의 경계

T-004는 Sonnet 5.5/high로 분석 JSON 계약과 합성 기반 지식 사전 초안을 만든다. READY/HOLD와 잡담 판정을 구분하고 원문 내 개념 근거 및 사전 대조를 명시한다. 기존 합성 gold를 사용자 지식이나 모델 정확도 증거로 승격하지 않는다. LLM 프롬프트/평가 설계・DB 이력・MCP 쓰기・수집기 연결은 별도 spec으로 분리한다.

학습 문서 정정 2164224를 확인해 47abdff로 수락・병합했다. 병합 후 전체 unittest 131개 OK, skip 없음, exit 0. T-004 개발 배정 조건을 충족했다. S3 후속 dispatch는 released 확인.

## D-011 · 2026-11-12 · T-004 개발 검토 및 QA 경계

651cb84 변경 6개는 허용 목록 안이고 개발 워크트리 clean. 47개 신규 테스트・全178개 통과는 S1 보고이며 아직 S0 최종 수락 아님. 모든 추출 목록의 공백 원소 거부는 의미 없는 항목 방지로 수락한다. extras 없는 완료 검증은 환경 잔존 여부가 불명확해 독립 QA에 실제 기본 설치 검증을 명시했다. QA 시작 시 새 Antigravity 첫 응답도 확인한다.

## D-012 · 2026-11-12 · Antigravity 새 계정 작업 응답 확인

account list에서 확인한 활성 계정 jeongujeong117@gmail.com으로 T-004 QA ctx_1c08dcaa27b0가 ready 시작됐고 첫 정상 작업 응답 msg_82057e3f6437을 받았다. 워커 자체 보고 모델은 Gemini 3.8 Flash (Medium)이며 현재 시작/첫 응답에 모델・계정 오류는 관측되지 않았다. 인증 보관 파일 접근 없이 확인했으며 전체 QA 성공 판정은 아직 아니다.
