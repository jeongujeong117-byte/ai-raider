# 작업 현황

| ID | 제목 | 담당 | 상태 | 브랜치 | 반려 횟수 |
|---|---|---|---|---|---|
| T-000 | core/agents 구조 분리 및 기존 동작 유지 | S1 Sonnet medium → S2 Antigravity | S1 완료·S2 검증 배정 준비 | jeongujeong117-byte/t-000-dev | 0 |
| T-001 | 수집기 상태 4종 및 감시 | S1-A | T-000 PASS·병합 대기 | 미정 | 0 |
| T-002 | 조회 전용 MCP 도구 | S1-B | T-000 PASS·병합 대기 | 미정 | 0 |
| T-003 | 정답 샘플 및 블랙박스 검증 틀 | S2 | T-000 PASS·병합 대기 | 미정 | 0 |
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
