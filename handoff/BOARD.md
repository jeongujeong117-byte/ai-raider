# 작업 현황

| ID | 제목 | 담당 | 상태 | 브랜치 | 반려 횟수 |
|---|---|---|---|---|---|
| T-000 | core/agents 구조 분리 및 기존 동작 유지 | S1 Sonnet medium → S2 Antigravity → S3 Sonnet low | PASS·develop 병합 완료, S3 문서 수락 | develop (개발 c4783ac, QA ccec489, 문서 39a088f) | 0 |
| T-001 | 수집기 상태 4종 및 감시 | S1-A Sonnet medium → S2 Antigravity | S2 독립 검증 중 | jeongujeong117-byte/t-001-dev | 0 |
| T-002 | 조회 전용 MCP 도구 | S1-B Sonnet medium → S2 Antigravity | S2 독립 검증 중 | jeongujeong117-byte/t-002-dev | 0 |
| T-003 | 정답 샘플 및 블랙박스 검증 틀 | S2 Antigravity | 작성·검증 중 | jeongujeong117-byte/t-003-qa | 0 |
| T-004 | 분석 JSON 스키마 및 지식 사전 초안 | S1 | T-001/T-002 완료 대기 | 미정 | 0 |
| 별도 | Instagram·X 실계정 1개 수집 검증 | 사용자 직접 | 사용자 수행 영역 | 해당 없음 | 0 |

## 운영

동시 워커 최대 4개. T-000은 단독 개발한다. 이후 S1 병렬 작업은 허용 파일이 겹치지 않을 때만 최대 2개다.
## T-000 배정 기록

- 명세 커밋: `e6ef996` (develop)
- Run: `run_548a284d59da`
- Task: `task_6264df5edbf9`
- S1 dispatch: `ctx_8d1667c5e8bd`
- 에이전트/모델: `claude` / `claude-opus-5-5`
- 자식 워크트리: `C:/Users/jeong/orca/workspaces/my-project/t-000-dev`
- 시작 영수증: `ready` (structured worker, keptOpen=true)
- 다음 단계: S1 결과 수신 → 허용 파일·증거 확인 → 개발 브랜치 기반 S2 Antigravity 검증 배정. 결과는 Orca 알림으로 수신한다.

## 모델 변경 기록

사용자 정책에 따라 기존 Opus dispatch ctx_8d1667c5e8bd는 stopped 확인. 기존 변경(루트 8개 파일 수정, 미추적 agents/core)은 보존했다. 재시작 모델은 claude-sonnet-5-5 / medium이며 같은 Task·워크트리를 사용한다. 모델 변경은 레드팀 반려 횟수에 포함하지 않는다.

- 새 dispatch: `ctx_9c29c2f7c788` (`--retry-of ctx_8d1667c5e8bd`)
- 시작 영수증: ready, model=`claude-sonnet-5-5`, effort=`medium`
- 정책·인계 명세 커밋: `02ed07c`. 제품 변경을 보존한 채 개발 브랜치에 fast-forward 반영했다.
- 최신 spec 우선 및 기존 변경을 확인하고 이어서 진행하라는 지시를 새 dispatch에 send했다.

## S1 완료 증거

- 개발 커밋: `c4783ac`, 보고서: `handoff/reports/T-000-dev.md` (개발 브랜치)
- 변경 파일 25개는 허용 목록 안이며 기존 tests 변경 없음, 개발 워크트리 clean 확인.
- S1 보고: 기준/변경 후 unittest 각 50개 OK, HTTP smoke·CLI help·모듈 import·wheel 구성·diff check exit 0.
- 실계정 수집은 미검증(금지). console entrypoint 실행·실제 serve/브라우저 화면 검증은 S2에 확인 요청.
- S2 명세: `handoff/specs/T-000-qa.md`. 아직 PASS 및 develop 제품 병합 아님.

## S2 배정 기록

- Task: `task_9978288124b6`, dispatch: `ctx_2f5582e7c789`
- 검증 기반: 개발 브랜치 `jeongujeong117-byte/t-000-dev`의 `c4783ac`
- 자식 워크트리: `C:/Users/jeong/orca/workspaces/my-project/t-000-qa`
- 모델/effort: 사용자 정책 예외에 따라 Antigravity 자체 기본 설정.
- 시작 영수증 ready. Windows에서 Antigravity structured chat 미지원으로 Orca가 terminal worker로 시작함. 제어는 orchestration만 사용한다.

## T-000 수락 및 통합

- S2 PASS: 개발 c4783ac 검증, QA ccec489. 기존 50개+새 블랙박스 7개, HTTP smoke, wheel 콘솔 엔트리포인트, Orca 브라우저 3개 화면 검증 보고 확인.
- S0가 QA 워크트리에서 50+7개를 재실행하고, 개발/QA 브랜치를 develop에 병합한 뒤 다시 50+7개 전체 통과를 확인했다.
- 실제 SNS 수집 및 실엔진 OCR/GPU는 미검증. master 병합/push 없음.
- 다음 명세: T-001/T-002/T-003 병렬, T-000-learn(S3).

## 병렬 배정 기록

| 작업 | Task | Dispatch | 모델 / effort | 워크트리 |
|---|---|---|---|---|
| T-001 | task_223b4dfa826d | ctx_01f428a01dc8 | claude-sonnet-5-5 / medium | t-001-dev |
| T-002 | task_d8afd68ee98a | ctx_6e5b64cccdf3 | claude-sonnet-5-5 / medium | t-002-dev |
| T-003 | task_5c9f157dcdf6 | ctx_58f43d40615d | Antigravity 자체 설정 | t-003-qa |
| T-000 S3 | task_52e790216fee | ctx_27a2331b1591 | claude-sonnet-5-5 / low | t-000-learn |

모두 develop/a7746db 기반 자식 워크트리에서 ready 확인. 4개 동시 워커, S1 2개는 허용 파일 비중복. 이전 T-000 S1은 already_released, S2는 released 확인. S3 브랜치는 jeongujeong117-byte/t-000-learn. 결과는 Orca 메시지로 수신한다.

## 후속 수신

- T-000 학습 문서: 39a088f 수락. 첫 보고의 마이그레이션·OCR 사유·시점 표현은 S0 요청으로 수정 후 확인. follow-up dispatch ctx_8e9cb742cb62, Task task_d3ba05853903.
- T-001 개발: 7c51734, 허용 3개 파일만 변경 및 clean 확인. 기존 50→66개 회귀 및 블랙박스 7개 통과 보고. 실제 수집기/대시보드/Edge 연결·동일 state_path 동시 작성은 범위 밖. 독립 QA는 handoff/specs/T-001-qa.md 기준.
- T-000 문서 develop 병합 완료, S3 수정 dispatch ctx_8e9cb742cb62 released 확인.
- T-001 S2: Task task_be8cf1f42bc1, dispatch ctx_fd2a8ce7cfb5, t-001-qa 자식 워크트리, 개발 브랜치 7c51734 기반 ready. Antigravity 자체 기본 모델/effort 사용. 중단과 fallback 경계 및 저장 파일 오염도 검증 요청.
- T-002 S1: 1d65fa4,허용 5개 파일만 변경 및 clean 확인. 보고서상 67개 테스트(신규 17개) 및 실제 SDK stdio/쓰기 없음/패키지 검증 통과. optional extra 미설치 시 서버 전용 신규 4개 skip, 필수 MCP 검증은 extra 설치 후 수행됨. WAL sidecar는 미검증이므로 독립 QA 요청.
- T-002 S2: Task task_d4517095d4da, dispatch ctx_d7fc5fcb1e19, t-002-qa 자식 워크트리, 개발 브랜치 1d65fa4 기반 ready. Antigravity 자체 모델/effort. handoff/specs/T-002-qa.md 기준.
