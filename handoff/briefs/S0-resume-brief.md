# S0 지휘관 재개 지시 (전원 차단 후 복구)

너는 AI Raider의 S0 지휘관(Codex)이다. 컴퓨터 전원이 꺼져 네 이전 세션이 끊겼다. 이 워크트리(`s0-codex`, 브랜치 `develop`)에서 이어서 일한다.
먼저 `handoff/ROLES.md`, `handoff/AGENTS.md`, `handoff/BOARD.md`, `handoff/DECISIONS.md`를 읽고 `orca skills get orchestration`을 다시 읽어라.
기존 규칙(모델 정책, 반려 3회 제한, master 병합·push는 사용자 승인 후에만, 제품 코드는 직접 수정하지 않음)은 그대로다.

## 복구 사실 (사용자 측에서 확인·처리한 것)

- 설명 문서 워커(Task `task_fbff03cee131`, dispatch `ctx_253771f3d032`)가 문서 2개를 쓰고 커밋(`fc27059`)한 직후 끊겨 worker_done을 보내지 못했다.
  브랜치 참조 파일이 깨져 있어서 `jeongujeong117-byte/t-001-003-learn`을 `fc27059`로 복구했다(부모 5dbdfac, 변경은 docs/learn 문서 2개뿐, git fsck 정상). 아직 수락·병합 전이다.
- Antigravity 계정이 새로 바뀌었다. Orca에는 `jeongujeong117@gmail.com`(active)로 등록돼 있다. 이 계정으로 워커가 정상 시작·응답하는지는 아직 검증되지 않았다.
- BOARD.md의 T-002 줄은 "QA 재검증 중"으로 되어 있으나, git log상 T-002는 이미 develop에 병합됐다(c647843, b67a261). 기록을 현실에 맞게 정정하라.
- Orca 오케스트레이션 상태: Run `run_548a284d59da`의 task 중 `task_fbff03cee131`만 dispatched로 남아 있다. `task_6ee8fa23c2ad`(failed)는 의도된 FAIL 정정 기록이고 이후 재검증이 성공했으므로 재시도하지 말고 DECISIONS에 설명만 남겨라.

## 할 일 (순서대로)

1. **상태 감사**: `git log`, 각 워크트리 `git status`, `orchestration task-list`, `worker-list`를 대조해 BOARD와 실제가 다른 곳을 정리하고 `handoff/BOARD.md`를 정정한다(너만 수정 가능).
2. **학습 문서 수락**: `fc27059`의 두 문서가 spec(`handoff/specs/T-001-T-003-learn.md`)과 사실관계(테스트 수치 시점, 근거 파일)에 맞는지 읽고 확인한다. 이상이 있으면 해당 dispatch에 `send`로 수정 요청, 없으면 develop에 병합한다. 병합 뒤 전체 테스트(`uv run python -m unittest discover -s tests`)를 재실행해 exit 0을 확인한다.
3. **Antigravity 연결 확인**: 다음 S2 작업(T-004 QA)을 시작할 때, 첫 응답이 정상으로 돌아오는지, 모델/계정 오류 없이 시작되는지를 확인해 DECISIONS.md에 한 줄 기록한다. 실패하면 중복 시작하지 말고 `failedStage`와 원문 오류를 사용자에게 보고하라.
   Antigravity 워커에게 인증·키링·계정 보관 파일에 접근하거나 복호화하라고 시키지 않는다. 계정은 Orca의 `orca account list`로만 확인한다.
4. **T-004 시작**: T-002가 병합됐으므로 차단이 풀렸다. `handoff/specs/T-004.md`를 작성(분석 결과 JSON 스키마(pydantic), `config/known_concepts.json` 초안; 모델 정책상 Sonnet 5.5 / high)하고 S1 워커로 시작한다.
5. **전체 과정 점검 보고**: 아래 "사용자 질문"에 답하는 형태로 `handoff/STATUS-2026-11-12.md`를 작성해 커밋하고 사용자에게 요약 보고한다.

## 사용자 질문 (STATUS 문서에서 답할 것)

꺼지기 전에 하던 작업들이 여전히 수행되고 있는가, 그리고 계획서 7장 전체 과정에서 어떤 단계를 더해야 하는가?
- 작업별(T-000~T-004, 학습 문서) 현재 상태와 근거 커밋을 표로.
- Phase 1~4 중 완료/진행/미착수와, 계획서에는 있지만 아직 spec이 없는 항목.
- 보강이 필요한 곳(예: 실계정 검증, 평가용 정답 샘플의 실제 데이터 연결, 답글 필터 기준, 반응 지표 None/0 처리)과 재개 순서 제안.
- 확인하지 못한 것은 "확인 못 함"으로 구분해 적는다.

## 제한

- master 병합, GitHub push 금지(사용자 승인 필요).
- `.private/`, 세션·쿠키·토큰·계정 보관 파일을 읽거나 출력하거나 커밋하지 않는다.
- 실제 Instagram·X 로그인 수집은 실행하지 않는다.
