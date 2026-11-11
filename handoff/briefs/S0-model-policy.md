# 단계별 모델 지정 (사용자 지시, 2026-11-11)

이 내용을 `handoff/ROLES.md`의 "팀 구성" 아래에 "모델 정책" 섹션으로 추가하고, `handoff/DECISIONS.md`에 기록하고, 커밋한다.
워커를 시작할 때 **항상 `--model`과 `--effort`를 명시**한다(Antigravity는 자체 설정 모델 사용). spec 머리말에도 사용 모델을 적는다.

## 기본값

| 세션 | 모델 | effort |
|---|---|---|
| S0 지휘관 | Codex (현재 설정 유지) | — |
| S1 개발 (기본) | `claude-sonnet-5-5` | `medium` |
| S1 개발 (설계 판단이 큰 작업) | `claude-opus-5-5` | `high` |
| S2 레드팀 | Antigravity 기본 모델 | — |
| S3 튜터 | `claude-sonnet-5-5` | `low` |

## 작업별 지정

| 단계 | 작업 | 담당 | 모델 | effort |
|---|---|---|---|---|
| Phase 1 | T-000 코드 이동(core/, agents/) | S1 | claude-sonnet-5-5 | medium |
| Phase 1 | T-001 base_supervisor 상태 4종 | S1 | claude-sonnet-5-5 | medium |
| Phase 1 | T-002 raider_mcp.py 조회 도구 | S1 | claude-sonnet-5-5 | medium |
| Phase 1 | T-003 정답 샘플 + 블랙박스 틀 | S2 | Antigravity | — |
| Phase 1 | T-004 분석 결과 JSON 스키마, known_concepts.json | S1 | claude-sonnet-5-5 | high |
| Phase 2 | 갤러리 사금 채취·사건 묶기 **프롬프트/판정 기준 설계** | S1 | claude-opus-5-5 | high |
| Phase 2 | 위 하네스 **구현** | S1 | claude-sonnet-5-5 | medium |
| Phase 3 | 템플릿 역공학 **설계**(카드뉴스 이미지 구조 분석) | S1 | claude-opus-5-5 | high |
| Phase 3 | 템플릿 역공학·콘텐츠 스튜디오 **구현** | S1 | claude-sonnet-5-5 | medium |
| Phase 4 | 보수팀 블랙박스 검문소 | S2 | Antigravity | — |
| Phase 4 | MCP 서버 확장 | S1 | claude-sonnet-5-5 | medium |
| 전 단계 | 병합 후 설명 문서 | S3 | claude-sonnet-5-5 | low |

## 승격 규칙

- 같은 작업이 레드팀에서 **2회 반려**되면 3회차는 `claude-opus-5-5` / `high`로 재시작한다(`--retry-of`, 같은 워크트리).
- 3회차도 FAIL이면 기존 규칙대로 멈추고 사용자에게 "사람 검토 필요"로 보고한다.
- 표에 없는 새 작업은 기본값(Sonnet medium)으로 하고, 설계 판단이 크다고 보면 사용자에게 Opus 사용을 먼저 묻는다.

## 지금 바로 할 일

1. 현재 T-000 워커(Claude Opus, dispatch `ctx_8d1667c5e8bd`)를 `orca skills get orchestration --reference references/recovery-and-cleanup.md`의 절차대로 중지한다.
2. 워크트리 `t-000-dev`의 `git status`와 커밋을 확인한다. Opus가 남긴 변경이 있으면 버리지 말고, 새 워커 spec에 "기존 변경을 확인하고 이어서 진행"이라고 적는다.
3. T-000을 같은 워크트리에서 `--agent claude --model claude-sonnet-5-5 --effort medium`으로 다시 시작한다.
4. BOARD.md에 모델 변경을 기록하고, 사용자에게 결과를 보고한다.
