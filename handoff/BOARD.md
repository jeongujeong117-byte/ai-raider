# 작업 현황

| ID | 제목 | 담당 | 상태 | 브랜치 | 반려 횟수 |
|---|---|---|---|---|---|
| T-000 | core/agents 구조 분리 및 기존 동작 유지 | S1 Sonnet medium → S2 Antigravity → S3 Sonnet low | PASS·develop 병합 완료, S3 문서 수락 | develop (개발 c4783ac, QA ccec489, 문서 39a088f) | 0 |
| T-001 | 수집기 상태 4종 및 감시 | S1-A Sonnet medium → S2 Antigravity | 수정본 PASS·develop 병합 완료 | develop (개발 140fcdf, QA 0f0b8cb) | 1 |
| T-002 | 조회 전용 MCP 도구 | S1-B Sonnet medium → S2 Antigravity | 수정본 PASS·develop 병합 완료 | develop (개발 6a64b95, QA be22c81, 병합 c647843/b67a261) | 1 |
| T-003 | 정답 샘플 및 블랙박스 검증 틀 | S2 Antigravity | 보완 수락·develop 병합 완료 | develop (ff69a03) | 0 |
| T-004 | 분석 JSON 스키마 및 합성 사전 기반 | S1 Sonnet high → S2 Antigravity | PASS・develop 병합 완료 | develop (개발 651cb84, QA a5d63c2, 병합 df7c360) | 0 |
| 학습 T-001/T-003 | 병합 후 학습 문서 2개 | S3 Sonnet low | 2164224 정정 수락·develop 병합 47abdff | jeongujeong117-byte/t-001-003-learn | 해당 없음 |
| T-005 | 읽기 전용 진행감독 CLI | S1 Opus high(3차) → S2 Antigravity | 통합 회귀 cp949 출력 실패・2차 반려, 수락 보류 | develop에 67c8961 통합됐으나 검증 실패, 수정 t-005-dev | 2 |
| T-006 | 사용자 확정 지식5개 및 합성 사전 분리 | S1 Sonnet medium | PASS・develop 병합 완료 | develop (개발 283d62e, QA 298ece3, 병합 38f911b) | 0 |
| S4 | 읽기 전용 진행감독관 1차 점검 | Sonnet low | 3차 감사 수락・로그 병합 완료 | jeongujeong117-byte/s4-audit | 해당 없음 |
| 별도 | Instagram·X 수집 | 사용자 결정 | X 재크롤링 금지・Instagram 차단으로 재수집/재연결 금지 | 해당 없음 | 0 |

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
- T-003 1차 커밋 `97178b6`. 보고서 14개 합성 사례/10개 신규 테스트, 전체 67개 및 블랙박스 17개 통과. 허용 5개 파일만 변경, clean 확인.
- T-003 S0 수락 보완: URL hostname 검증, fixture 전체 기대값 검증, 지식 사전과 신개념 기준안 연결, 초기 분석 정답과 모델 성능 검증의 구분을 send로 요청. S1 레드팀 반려가 아닌 S2 산출물 수락 보완이므로 S1 승격 횟수와 무관. 아직 develop 미병합.
- T-003 보완 Task task_95e9eb7d8090 / dispatch ctx_badfc7406e20, 동일 워크트리·Antigravity 자체 설정으로 ready 확인.
- T-001: S2의 7c51734 PASS는 S0가 미수락. stop 후 fallback 실행, 복원된 임의 reason 노출을 임시 입력으로 직접 재현해 1차 반려. QA 정정 Task task_f96d2d5a539c / dispatch ctx_c96c105bd2f0, S1 수정 Task task_ca9aabb4ff9d / dispatch ctx_90cd73058b26.
- T-001 수정 140fcdf 도착: 중단 직전 검사·고정 reason 복원 검증, 신규 회귀 2개 추가(개발 전체 68개+블랙박스 7개 통과 보고). S0가 diff 확인 후 QA에 최초 FAIL 증거 보존 및 같은 브랜치에서 140fcdf 재검증을 send. 아직 develop 미병합.

## 최신 수락 및 재검증

- T-002 원본 1d65fa4의 QA PASS 미수락. S0 실제 stdio 재현으로 bool/수치 문자열 coercion 확인 후 1차 반려. S2 정정 FAIL e443091, 수정 S1 6a64b95(StrictInt/StrictStr와 실제 SDK 회귀) 도착.
- T-002 S1 보완 Task task_429cdad2bf17 / dispatch ctx_35631755d212 완료. S2 정정 Task task_6ee8fa23c2ad / dispatch ctx_fd31bc95174d FAIL 보고 후, 재검증 Task task_1bfa2b9e91e2 / dispatch ctx_c64264f2869c 진행 중.
- T-001 QA 최초 FAIL 0f58417, 수정본 PASS 0f0b8cb 수신. 후속 Task task_3c6f23087de7 / dispatch ctx_011cad965adc worker_done succeeded 확인. startup 관측 지연 알림은 있었으나 실제 작업 진행 및 최종 보고 확인, 중복 시작하지 않음.
- T-003 ff69a03 수락: 15개 합성 사례·12개 신규 테스트. S0가 전체 69개/blackbox 19개 재실행 후 develop 병합, 병합 뒤 동일 검증 통과.
- T-001 S0가 QA 워크트리에서 전체 68개/blackbox 18개 재실행 후 개발·QA를 develop 병합. T-003 포함 develop 전체 98개/blackbox 30개 모두 exit 0.
- S3 T-001/T-003 설명 명세: handoff/specs/T-001-T-003-learn.md. T-004는 T-002 수락·병합까지 대기.

## 2026-11-12 전원 차단 후 감사

- 전체 12개 등록 Git 워크트리 status --short 출력 없음(clean). develop HEAD b67a261. master 변경 없음.
- T-002는 c647843 및 b67a261로 이미 통합됐고 be22c81 최종 PASS를 확인했다. 위 표의 재검증 중 표기를 정정했다.
- Run run_548a284d59da task-list에서 학습 Task task_fbff03cee131도 completed, dispatch ctx_253771f3d032는 succeeded다. 재개 지시 작성 당시 dispatched 상태와 달라졌다. 이전 작업이 계속 실행 중이라고 해석하지 않는다.
- failed Task task_6ee8fa23c2ad는 최초 PASS를 FAIL로 정정한 이력이다. 후속 task_1bfa2b9e91e2 completed로 해결됐으므로 재시도하지 않는다.
- fc27059 변경은 지정 docs/learn 문서 두 개뿐. T-003 머리말의 69개/19개가 '보완 전'이라는 설명은 QA 보고서와 달라 수락 보류한다.
- 첫 send는 consumer_fenced로 거절됨(전달 안 됨). run-use --id run_548a284d59da 성공으로 현재 지휘관 연결을 복구했다. 중복 워커를 시작하지 않았다.

## 학습 문서 수락 및 T-004 재개

- S3 후속 task_3941bb91684d / ctx_93879c6888f1: 2164224의 테스트 시점 정정 확인, 47abdff로 develop 병합.
- 병합 후 uv run python -m unittest discover -s tests: 131개 OK, skip 없음, exit 0. MCP stdio 검증 포함.
- S3 후속 dispatch released/processAction=closed_agent_terminal 확인.
- T-004 Task task_719ebd078b96 / dispatch ctx_6f941cb32864: t-004-dev, claude-sonnet-5-5/high, structured ready 확인. S1 결과 후 S2 QA에서 새 Antigravity 계정 첫 응답 확인 예정.
- T-004 S2 Task task_0297815ac152 / dispatch ctx_1c08dcaa27b0: Antigravity terminal ready. 첫 정상 응답 msg_82057e3f6437 수신, 자체 보고 모델 Gemini 3.8 Flash (Medium). 최종 QA 결과 대기.

## 추가 지시 병행 배정

- S4 Task task_6d128e5073dd / dispatch ctx_1318677b4450: Sonnet5.5/low, s4-audit, ready.
- T-005 Task task_02b2e5b96fea / dispatch ctx_ad2fdbb728f9: Sonnet5.5/medium, t-005-dev, ready. T-004 허용 파일과 비중복.
- T-004 QA ctx_1c08dcaa27b0 유지, 중단/재시작 없음. 완료된 S1 ctx_6f941cb32864는 released/processAction=closed_agent_terminal 확인.
- S4 1차 5cf6389 수락・로그 develop 병합. 관측 당시 BOARD 배정 지연은 e75dae0에서 해결. t-004-qa 미추적 테스트는 QA 진행 중 산출물로 최종 보고 시 확인. T-002 완료 retained/unverifiable은 worker-show 재확인, 생존 불명으로 자동 종료하지 않음. T-001 QA 합산 혼동 가능성은 과거 보고 이슈로 분리하며 현재 전체131개와 합산하지 않음.
- 사용자 D-013 지식 답변 수신: 실제 기지식5개 확정. T-006에서 config 갱신, T-011/T-012에서 신개념 쉬운 한국어 뜻풀이 구현. T-004 QA 계약/프로세스는 유지.

## T-004 수락 및 T-005 QA 전환

- T-004 QA a5d63c2 허용2개 파일만 변경・clean. 기본199개 OK(skip11), extras199개 OK(skip0)는 QA 보고. S0가 QA 브랜치 extras199개 재실행 exit0, df7c360 병합 후 동일199개/skip0/exit0 확인(12.408초).
- T-004/T-005 완료 워커 released 확인. T-005 0b7b045 허용3개 변경・clean, S1 164개(skip11) 보고는 T-004 미포함 브랜치 수치.
- T-006의 config/초기config검사 변경은 사용자 승인 계약 갱신이다. 신개념 뜻풀이 생성은 후속 T-011/T-012에 유지.
- T-005 QA task_0e2cfe1de9ce/ctx_ae2e726c53aa Antigravity ready; T-006 task_714f8a289523/ctx_a9b2e5230be3 Sonnet medium ready.
- S4 수락 후 감사 task_d4dac40903cb/ctx_ea53cdf69f50 reopened ready(기존 Sonnet low); T-004 학습 task_e3575183518b/ctx_824fa565aabf Sonnet low ready. 실행 작업4개 이내.
- S4 2차5dbbd32 수락: T-004 통합/199개 정합, 로컬 master 변경/반려2회/수치감소 없음. T-005 미병합은 QA중 정상이며 오류로 취급하지 않음. 학습 starting 관측은 이후 ready/live/working 및 완료 보고로 해소. T-002 과거 retained/unverifiable 생존은 여전히 확인 못 함.
- T-004 학습49bef5d 수락・develop 병합. 개발보고 필수필드15개 표기와 코드/QA16개 불일치를 문서에서 명시, 코드16개가 기준. 합성12개/T-006 사용자5개/미검증 LLM 경계를 확인. S4와 S3 완료 dispatch released 확인.
- T-006 283d62e 허용6개만 변경・clean. 사용자5개/alias config 및 합성gold 불변 확인. S1은 processing216개/skip11, MCP포함 필수회귀 미실행이므로 QA에 명시. 신규모듈16개+기존모듈1개 증가=총17개 증가, 보고서의 신규17개 표현과 구분.
- T-006 QA task_116fedbd0567 / ctx_a5f9e0a1ce7a, Antigravity t-006-qa ready. T-005 QA와 병행하며 결과 전 병합하지 않음.
- T-006 298ece3 허용2개/clean 확인. QA 기본231개 skip11/전체extras231개 skip0 보고. S0 QA브랜치231개 및38f911b 통합후231개를 extras포함 재실행, OK/skip0/exit0(10.148초).
- T-005 QA7e1e5be는 미수락. S0 read-only probe로 tasks=[{id:[],title:T-005}] 주입 시 check_orca에서 UNHANDLED TypeError 재현. 기대: 파싱실패 안전출력/exit2. 타입오염 필드/최상위 JSON을 검증하도록 S1 1차반려・S2 FAIL정정 요청.
- T-005 QA FAIL정정 task_ccb6cab3e1ce/ctx_859106d12f87 ready; S1수정 task_39014f228445/ctx_8201f28c7b3a ready(Sonnet medium 유지).
- T-006 후 S4감사 task_08392a858784/ctx_b96446366377 ready, S3문서갱신 task_095896887719/ctx_382d54a8897c ready. 총4개작업 한도내.
- S4 3차51c7e30 수락・develop 병합. 사용자config5개/alias와 합성gold12개 불변을 코드/파일로 확인, T-006 통합 및231개 수치 정합. T-005 수정중/구브랜치 수치는 통합미완료 정상이며 최종 회귀별도필요. 과거T-002 생존과원격push는확인못함 유지. S4 dispatch released확인.
- T-005 be09b34 허용3파일/clean, S1 기본166개 skip11/extras166개 skip0 보고. 타입검사/catchall diff확인, 원본FAIL정정수신뒤재검증요청예정. 수정완료S1 released.
- T-006 학습6f02b04 허용docs2개를수락・병합, 현재사용자5개/alias와T004합성12개역사구분, 자동추출/뜻풀이는후속명시. S3 released. 문서통합으로제품회귀재실행없음, 직전제품231개증거유지.
- T-005 원본FAIL task_ccb6cab3e1ce/ctx_859106d12f87 outcome failed는의도된결함이력, d0fa3ed RED확인. 자동후속task_021b937ec611/ctx_1382f85450d1가이미working이므로중복시작하지않고해당dispatch에be09b34재검증지시전달. 반려횟수1유지.
- T-005 후속ctx_1382f85450d1에turn_start_unobserved/start_unknown 알림수신. worker-show는live/working, worker-read에서git show be09b34/merge실행을관측, QA브랜치45eebba로수정병합확인. 실제진행증거있어중복시작/재전송/중단없음. 최종worker_done대기.
- T-005 QA76ab0b5 및S0 QA브랜치184개/skip0/exit0 확인후67c8961 통합. 통합전체284개는1error/1failure로exit1. 실제CLI프로브도cp949 UnicodeEncodeError(BOARD '・')/rc1/stdout0 재현. 통합수락보류, 2차반려・3차Opus high수정승격. master/push없음.
- Opus재시작 --retry-of ctx_8201f28c7b3a는task_not_startable로시작전거절(이전Dispatch는completed). dispatch-show/worker-show로succeeded・released・exited확인후같은Task task_39014f228445를ready로열어동일t-005-dev에Opus5.5/high ctx_f3470b5bdb1a ready. 반려2회횟수는유지,회피/새Task없음. 최신T-005-opus-fix명세를send로우선전달.
- QA2차정정은ctx_1382f85450d1에send요청. 최종수락보류이며Opus3차도FAIL이면사람검토필요중단.
