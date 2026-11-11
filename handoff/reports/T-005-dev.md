# T-005 개발 보고 · 읽기 전용 진행감독 CLI

S1 Claude Sonnet 5.5 / medium. 브랜치 `jeongujeong117-byte/t-005-dev`. 변경 파일: `tools/progress_check.py`, `tests/test_progress_check.py`, 본 보고서 (3개, 모두 허용 목록). stdlib 전용.

## 사용법
```
python tools/progress_check.py --run <run_id> [--repo <path>] [--orca-command <exe>] [--json] [--timeout 15]
```
- repo 기본: 스크립트의 저장소 루트. 상대/절대 경로 모두 resolve 후 디렉터리·git 저장소 검증.
- orca-command 기본: `ORCA_CLI_COMMAND` → Windows `orca` / 그 외 `orca-ide`(`ORCA_DEV_REPO_ROOT` 설정 시 `orca-dev`). 실행파일 하나로만 취급(셸 메타문자 거부). Windows에서 `.cmd/.bat`로 해석되면 같은 폴더의 `.exe` 진입점을 사용하고, 없으면 실행하지 않는다.
- exit 0 점검 완료·warning/error 없음, 1 warning/error 발견, 2 필수 소스(git, BOARD, orca task/worker-list) 불가·파싱 실패·잘못된 인자.
- stdout만 결과(JSON `{schema_version:1, observed_at, repo, run_id, findings, checks}` 또는 동일 내용 텍스트). 원시 stderr/오류 문자열은 버리고 `status`+`returncode` 고정 문구만 출력. info finding과 unknown check는 exit에 영향 없음.

## 안전 설계
- `subprocess.run(shell=False, stdin=DEVNULL, stderr=DEVNULL)`, 명령별 timeout(기본 15초), 출력 4MiB 한도(초과 시 폐기).
- 실행 직전 allowlist 검증(`validate_git_args`/`validate_orca_args`): git은 `worktree list --porcelain`, `status --porcelain`(`--no-optional-locks`), `rev-parse --git-dir`, `rev-parse --verify --quiet <rev>`, `merge-base --is-ancestor`, `for-each-ref refs/heads`만; orca는 `orchestration task-list|worker-list --run <id> --json [--limit 100]`만. push/commit/merge/fetch/worker-stop 등은 실행 없이 `denied`.
- 파일 본문·비밀·사용자 DB·원격 네트워크 접근 없음. dirty는 항목 수만 보고(파일명 미노출).

## 검출 항목
| 코드 | 심각도 | 조건 |
|---|---|---|
| MERGED_NOT_ANCESTOR | error | 첫 작업표의 '병합 완료' 행 근거 커밋이 모두 해석되나 develop 조상이 아님 |
| MERGED_PARTIAL_ANCESTOR | warning | 일부만 조상(squash/대체 가능성 판정 불가) |
| OPEN_BUT_INTEGRATED | warning | 진행/대기 행에 개발·QA 커밋 2개 이상이 명시되고 모두 develop 조상 |
| REJECTION_COUNT_HIGH | warning | 반려 횟수 ≥ 2 |
| WORKTREE_DIRTY | warning | 등록 worktree의 status --porcelain 비어있지 않음 |
| WORKER_RETAINED_AFTER_COMPLETION | warning | state succeeded/completed 이면서 terminalState retained |
| WORKER_LIVENESS_UNVERIFIABLE | info | liveness=unverifiable (check는 unknown, 멈춤/사망 판정 안 함) |
| TASK_FAILED_HISTORY / WORKER_FAILED_HISTORY | info | failed 이력(재시도 권고 안 함). 같은 T-ID의 completed Task가 있으면 check ok(정정 이력 추정), 없으면 unknown |
| MASTER_DIFFERS_FROM_BASELINE | info | 로컬 master가 0be384f와 다를 때(승인 여부 판정 안 함) |

- BOARD는 첫 `| ID |` 표(현재 주 작업표)만 읽는다. 이후 절·표(역사)는 무시. T-xxx 행만 대상(학습/S4/별도 제외).
- Task 제목 T-ID는 `(?<![0-9A-Za-z-])T-\d{3}(?![0-9A-Za-z])` 경계, 제목에 서로 다른 ID가 정확히 하나일 때만 매핑(복수/없음은 null).
- 커밋 근거는 상태·브랜치 열의 7~40자 hex(숫자·a-f 각 1자 이상). 해석 불가/모호/develop 없음은 unknown이며 오류를 만들지 않는다. 브랜치 이름만으로는 통합 증거로 보지 않는다(막 만든 브랜치도 조상이므로).

## 자동화 한계 / S4 사람형 감사 필요 범위
항상 unknown으로 보고: 시작 후 응답 없음·오래 멈춤(`stall_detection`), 테스트 수 감소(`test_count_regression`), push 여부(`master_push`, 네트워크 금지), master 변경의 승인 여부. 또한 BOARD 서술(본문 절)의 사실관계, QA 보고서 내용 타당성, 커밋 내용·범위 위반, 워커 화면 실제 내용, squash 병합, worker-list 100건 초과(nextCursor 미추적, unknown)는 S4 감사 몫이다. 출력 한도는 실행 후 폐기 방식(스트리밍 중단 아님).

## 검증 증거
| 명령 | rc | 결과 |
|---|---|---|
| `uv run python -m unittest discover -s tests` (시작 전) | 0 | 131개 OK, skipped=11 (기존과 동일) |
| `python -m unittest tests.test_progress_check` | 0 | 33개 OK |
| `uv run python -m unittest discover -s tests` (완료 후) | 0 | 164개 OK (131+33), skipped=11 |
| `python tools/progress_check.py --run run_548a284d59da` (실제 repo/Run 스모크) | 1 | 예상 산출물: findings 15 (warning 3: WORKTREE_DIRTY 2[t-004-qa, 작업 중인 t-005-dev], WORKER_RETAINED 1; info 12), checks 50 (ok 35, unknown 15). 병합 완료 T-000~T-003 근거 커밋 모두 develop 조상, master=0be384f |
| `--repo <없는 경로>` | 2 | stdout 비어 있음 |

신규 테스트 33개: BOARD 파싱/역사 절 무시, 통합·미통합·부분·해석불가·근거없음, 진행행 통합 불일치/증거 부족/브랜치명만, 반려 2회, clean/dirty(파일명 미노출), retained+unverifiable, failed 이력, malformed JSON·timeout·nonzero·CLI 부재·git 부재·BOARD 부재/손상, JSON 스키마·텍스트 모드·인자 오류 exit 2, shell=False·stderr 폐기·오류 매핑, allowlist 허용/거부(실행 안 됨 확인), 실제 임시 git fixture(ancestry 및 dirty) 1건. 기존 테스트 수정·skip 없음.

## 미확인
Windows `.cmd`→`.exe` 해석은 이 환경(orca.exe 존재)에서만 실행 확인. Linux `orca-ide`/`orca-dev` 기본값은 단위 테스트(mock)만. 실제 live worker 멈춤·테스트 감소 판정은 미구현(위 한계). S2 독립 QA 전 병합 금지.

## 1차 반려 수정 (S0 재현: task id가 list → TypeError)
- 원인: `_orca_json`이 `items`가 dict 리스트인지만 확인하고 id/title 등 실제 소비 필드의 타입은 검증하지 않아 `title_by_id` dict 키에서 unhashable TypeError.
- 수정(`tools/progress_check.py`): 소비 경계에서 검증. 최상위가 dict·`ok is True`·`result` dict·`result[key]` list of dict·각 항목 필드 타입(tasks: `id` 비어있지 않은 str 필수, `status`/`title` str|None; workers: `dispatchId` 필수 str, `taskId/state/liveness/terminalState/outcome` str|None)·`nextCursor` str|None. 위반 시 `orca <sub> JSON 파싱 실패` 고정 오류 + exit 2. 추가 안전망으로 `check_orca` 예기치 못한 예외도 `orca_internal` 고정 오류(exit 2)로 처리, traceback/원시 메시지 미출력. shell=False·읽기 전용 allowlist·unknown 계약은 변경 없음.
- 테스트 +2(총 신규 35개): S0 재현 payload 포함 task/worker 잘못된 타입 21종(최상위 list/scalar/None, result/key/items/필드 타입)이 모두 exit 2 + 파싱 실패 check + 유효 JSON 출력(traceback 없음), 예외 격납 시 `secret` 문자열 미출력. 정상 입력 exit 0 유지.

### 재검증 증거
| 명령 | rc | 결과 |
|---|---|---|
| `python -m unittest tests.test_progress_check` | 0 | 35개 OK |
| `uv run python -m unittest discover -s tests` | 0 | 166개 OK, **skipped=11 (전부 `optional extra 'mcp' not installed`, MCP stdio 테스트 포함)** |
| `uv run --extra mcp --extra processing python -m unittest discover -s tests` | 0 | 166개 OK, **skip 0** (MCP stdio 테스트 실제 실행) |
| 실제 CLI: `progress_check.py --run run_548a284d59da --json` | 1 | findings 15, checks 55 (경고 exit 1은 예상 산출물) |
| 실제 CLI: `--run run_doesnotexist` | 2 | orca task-list 실패(returncode=1)를 `orca_task_list` error로 고정 문구 보고, 원시 오류 없음 |
| 실제 CLI: `--orca-command nonexistent-orca-xyz` | 2 | CLI 부재 error 고정 문구 |
