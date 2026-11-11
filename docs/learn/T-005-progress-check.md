# T-005 학습: 읽기 전용 진행감독 CLI (`tools/progress_check.py`)

대상: 기초를 마치고 중급에 막 들어선 비전공자. 기준: develop `92ec6e3`(T-005 개발 3a38765 + QA b4400b7, 병합 c3984b9), `tools/progress_check.py`, `handoff/specs/T-005.md`, `handoff/reports/T-005-dev.md`, `handoff/reviews/T-005-qa.md`, BOARD, DECISIONS D-016~D-021. 먼저 `T-001-supervisor.md`를 읽으면 "감시"의 뜻이 쉽습니다. 근거를 읽지 못한 부분은 **확인 안 됨**으로 적었습니다.

## 1. 무슨 문제를 푸는가

여러 AI 워커가 동시에 일하면 사람이 쓰는 기록(`handoff/BOARD.md`)과 실제 상태(Git, Orca)가 어긋나기 쉽습니다. 예를 들어 BOARD는 "병합 완료"인데 그 커밋이 `develop`에 없거나, 작업은 이미 통합됐는데 BOARD에는 "진행 중"으로 남을 수 있습니다. T-005 도구는 이 **불일치를 찾아 보고만** 합니다.

이 도구가 **하지 않는 것**: 워커 자동 중지·재시작, 병합, 작업 배정, 수정, 네트워크 호출. "문제 발견 → 알림"까지만이고 조치는 사람(S0/S4)이 합니다.

## 2. 왜 읽기 전용 CLI인가

- 감독 도구가 직접 고치기 시작하면 감독 도구 자체의 오판이 사고가 됩니다. 읽기만 하면 최악이 "잘못된 경고"입니다.
- CLI(명령줄)는 어디서든 같은 방식으로 실행하고, 종료 코드·JSON으로 다른 도구가 결과를 이어받기 쉽습니다.
- 대상은 코드와 기록 파일, Git, Orca 목록뿐입니다. 비밀 파일·사용자 DB·미디어·계정 파일·실제 SNS 수집·원격 push는 다루지 않습니다.

## 3. 안전 장치: `shell=False`와 허용목록

```python
subprocess.run(argv, shell=False, stdin=DEVNULL, stdout=PIPE, stderr=DEVNULL, timeout=...)
```

- **`shell=False`**: 명령을 문자열이 아니라 `["git", "-C", 경로, ...]` 같은 목록으로 넘깁니다. 셸이 `;`, `&&`, `$` 같은 문자를 해석하지 않아 명령 주입 위험이 줄어듭니다.
- **허용목록(allowlist)**: 실행 직전에 `validate_git_args`/`validate_orca_args`가 검사합니다. 허용: git은 `worktree list --porcelain`, `status --porcelain`, `rev-parse`, `merge-base --is-ancestor`, `for-each-ref refs/heads` 정도, orca는 `orchestration task-list|worker-list --run <id> --json`뿐. `push`, `commit`, `merge`, `worker-stop` 등은 **실행하지 않고** `denied`가 됩니다.
- 실행파일 이름에 셸 메타문자가 있으면 거부하고, Windows에서 `.cmd`는 같은 폴더 `.exe`만 씁니다.
- 원시 stderr는 버리고 `status`+`returncode`의 고정 문구만 출력합니다(비밀이 섞일 수 있어서).
- 명령별 timeout 기본 15초. 출력이 4MiB를 넘으면 버립니다. **주의: 이것은 명령이 끝난 뒤 크기를 검사하는 방식이며, 실행 중 메모리를 실시간으로 제한하는 장치가 아닙니다.**

## 4. 무엇을 어떻게 비교하나

### BOARD "현재 표"만 읽기
BOARD의 첫 `| ID |` 표(현재 주 작업표)만 파싱하고, 아래의 역사 절은 무시합니다. 역사 문장에 "진행 중"이 있어도 현재 상태로 오인하지 않기 위해서입니다. `T-xxx` 행만 대상이며 학습/S4/별도 행은 제외합니다.

### Git ancestry (조상 여부)
"병합 완료" 행의 상태·브랜치 칸에서 7~40자 커밋 해시를 뽑아 `git merge-base --is-ancestor <커밋> develop`으로 묻습니다. 종료코드 0이면 조상(=통합됨), 1이면 아님, 그 밖이면 판단 불가(unknown)입니다.

- 모두 조상 → 정상. 모두 조상 아님 → `MERGED_NOT_ANCESTOR`(error). 일부만 → `MERGED_PARTIAL_ANCESTOR`(warning, squash 병합 가능성은 판정 못 함).
- 해시가 없거나 해석 안 되면 **허위 오류 대신 unknown**.
- 브랜치 이름만으로는 통합 증거가 아닙니다(막 만든 브랜치도 조상이라서).

### 그 밖의 점검
| 코드 | 심각도 | 의미 |
|---|---|---|
| OPEN_BUT_INTEGRATED | warning | BOARD는 진행/대기인데 기록된 개발·QA 커밋 2개 이상이 모두 develop에 통합됨 |
| REJECTION_COUNT_HIGH | warning | 반려 횟수 2회 이상 |
| WORKTREE_DIRTY | warning | 미커밋 변경 있음(건수만 보고, 파일 본문은 안 읽음) |
| WORKER_RETAINED_AFTER_COMPLETION | warning | 완료된 워커의 화면이 남아 있음 |
| WORKER_LIVENESS_UNVERIFIABLE | info | 생존 확인 불가(멈춤/사망으로 판정하지 않음) |
| TASK_FAILED_HISTORY / WORKER_FAILED_HISTORY | info | failed 이력(재시도 권고 아님) |
| MASTER_DIFFERS_FROM_BASELINE | info | 로컬 master가 `0be384f`와 다름(승인 여부 판정 안 함) |

**failed 이력은 최종 실패가 아닙니다.** 예: T-002의 failed Task `task_6ee8fa23c2ad`는 "잘못된 PASS를 FAIL로 정정"한 기록이고, 뒤의 재검증 Task가 completed로 해결했습니다(DECISIONS D-009). 도구는 같은 T-ID의 completed Task가 있으면 "정정 이력으로 **추정**(단정 아님)", 없으면 unknown으로 표시하며, 자동으로 재시도·중지하지 않습니다.

## 5. 출력과 종료 코드

JSON 구조: `{schema_version:1, observed_at, repo, run_id, findings:[{code,severity,task_id,summary,evidence}], checks:[{name,status,detail}]}`. severity는 info/warning/error, check status는 ok/unknown/error.

| 종료 코드 | 뜻 |
|---|---|
| 0 | 점검 완료, warning/error 없음 |
| 1 | 불일치·경고 발견 (정상적인 산출물이며 도구 실패가 아님) |
| 2 | 필수 소스(git, BOARD, orca 목록) 사용 불가·잘못된 인자·파싱 실패 |

- **warning**: 사람이 한번 봐야 할 불일치. **unknown**: "문제 없음"이 아니라 "이 도구는 판단할 근거가 없음". info와 unknown check는 종료 코드에 영향 없음.
- 실패를 정상(0)으로 숨기지 않는 것이 핵심입니다.

### 실제 사용 예 (이 문서 작성 시 1회 실행, 읽기 전용)
```
python tools/progress_check.py --run run_548a284d59da          # 사람용 텍스트
python tools/progress_check.py --run run_548a284d59da --json   # 기계용
echo $?                                                         # 종료 코드 (Git Bash 기준)
```
출력 앞부분(발췌, 수치는 그 시각 상태이며 계속 변함):
```
progress_check run=run_548a284d59da repo=...\t-005-learn observed_at=2026-11-11T16:38:14...
findings: 22
  [warning] REJECTION_COUNT_HIGH task=T-005: 반려 횟수 2회 (2회 이상) evidence={"rejections": 2}
  [info] TASK_FAILED_HISTORY task=T-002: failed Task 이력(재시도 권고 아님; 최종 작업 실패와 구분) ...
  [info] WORKER_LIVENESS_UNVERIFIABLE task=T-005: 워커 liveness 검증 불가(멈춤/사망으로 판정하지 않음) ...
```
종료 코드는 1이었습니다. 경고(반려 2회 등)를 발견한 것이므로 도구 실패가 아닙니다.

## 6. 관측 한도와 S4의 역할

자료만으로 **증거가 없어** 항상 unknown인 것:

- 시작 후 응답 없음·오래 멈춤(시간만으로 실패를 단정하지 않음)
- **테스트 수 감소**
- **원격 push 여부**(네트워크 호출 금지)
- master 변경이 **승인된 것인지**(변경 감지만 하고 승인 판정은 안 함)
- worker-list가 100건을 넘을 때 나머지(첫 100건만 확인)
- Linux 실행: `orca-ide`/`orca-dev` 기본값은 **mock 단위 테스트로만** 확인했고 실제 Linux 실행은 확인 안 됨.

그래서 **S4(사람형 감사)**가 필요합니다. S4는 실제 Git/Orca/테스트 근거로 BOARD 서술의 사실관계, QA 보고 타당성, 커밋 범위 위반, 워커 화면 내용 등을 읽고 확인하며, 확인 못 한 것은 "확인 못 함"으로 남깁니다(D-016). 이 도구는 S4의 일을 대체하지 않고 **기계가 싸게 할 수 있는 일부**를 맡습니다.

## 7. 왜 표준 라이브러리(stdlib)만 썼나

사용한 것: `argparse`, `subprocess`, `json`, `re`, `pathlib`, `shutil`, `dataclasses`, `datetime`.

| | 장점 | 단점 |
|---|---|---|
| stdlib만 | 설치 의존성 0, 어디서나 실행, 공급망 위험 없음 | 표 파싱·인자 처리를 직접 짜야 함, 코드가 다소 김 |
| 대안: `click`/`typer` | CLI 작성이 짧고 편함 | 의존성 추가(이번 spec은 의존성 추가 금지) |
| 대안: `GitPython`/`pygit2` | git 객체를 파이썬으로 직접 다룸 | 의존성·읽기 전용 보장이 어려움. git 명령 허용목록이 더 단순하고 검증 쉬움 |
| 대안: Markdown 파서 | 표 파싱이 견고 | 의존성. 여기선 "첫 표만" 읽는 단순 규칙으로 충분 |

단점 하나: BOARD 표 형식이 바뀌면(열 수 등) 파싱 실패로 exit 2가 되므로 도구와 BOARD 형식이 같이 관리돼야 합니다.

## 8. 개발 이력과 "타입 검사"가 필요했던 이유

| 시점 | 사건 |
|---|---|
| `0b7b045` | S1 원본. S2 QA가 PASS(`7e1e5be`)를 보고했으나 **S0가 미수락** |
| S0 재현 | Orca JSON을 `tasks=[{"id": [], "title": "T-005"}]`처럼 손상시키면 `check_orca`에서 `TypeError`(리스트는 dict 키 불가)로 비정상 종료 — 기대는 "파싱 실패 안전 출력 + exit 2" |
| `d0fa3ed` | QA가 PASS를 FAIL로 정정하고 **RED 회귀 테스트** 추가 |
| `be09b34` | S1 수정: `_validate_items`로 id/status/title 등 **실제 쓰는 필드의 타입**을 경계에서 검증, 위반 시 고정 오류 + exit 2 |
| QA `76ab0b5` | 수정본 PASS(그 시점 QA 브랜치 184개 통과) |
| 통합 `67c8961` | 통합 전체 284개 중 1 error/1 failure: BOARD의 `・`가 Windows cp949 stdout에서 `UnicodeEncodeError`(2차 반려) |
| `3a38765`/QA `b4400b7` | Opus high 3차 수정: JSON은 `ensure_ascii=True`, 텍스트는 `write_safe()`. 최종 PASS, 병합 `c3984b9` |

**타입 검사가 필요한 이유**: 도구는 외부 프로그램(Orca)의 출력을 믿고 읽습니다. 기대와 다른 모양(손상·버전 차이)이 오면 도구가 알 수 없는 예외로 죽거나, 더 나쁘게는 조용히 잘못된 결과를 냅니다. "입력 경계에서 모양과 타입을 확인하고, 틀리면 고정된 안전 오류로 멈춘다"는 원칙입니다. 이 사고는 RED(먼저 실패하는 테스트) → 수정 → GREEN 순서로 이력을 지우지 않고 보존했습니다. 2회 반려로 3차는 Opus high로 승격됐습니다.

참고: 이 `failed` QA Task들은 "도구에 결함을 증명한 정정 기록"이지 최종 제품 실패가 아닙니다.

## 9. 테스트 수 구분 (섞지 마세요)

| 구분 | 수치 | 출처 |
|---|---|---|
| T-005 독립 브랜치(수정 be09b34 시점 QA 브랜치) | 184개 | BOARD, QA 보고 |
| T-005 독립 브랜치 개발 보고(3a38765) | 174개 | 개발 보고(참고) |
| QA 최종 브랜치 | 194개 | QA 보고, BOARD |
| **현재 통합(develop, 최신 BOARD)** | **294개, skip 0, exit 0** | BOARD/D-021 (extras 포함) |
| 통합 실패(수정 전 이력) | 284개 중 1 error/1 failure | 보존된 이력 |

브랜치마다 포함된 작업이 달라 서로 다른 집합입니다. 단순 비교나 합산은 하지 마세요. 이 문서 작성에서는 제품 테스트를 다시 실행하지 않았습니다.

## 10. 서술형 문제

1. 이 도구가 "읽기 전용"이어야 하는 이유와, 이를 코드 수준에서 지키는 두 가지 장치(`shell=False` 외 하나)를 설명하세요.
2. 종료 코드 1을 받았을 때 "도구가 고장 났다"고 결론 내면 왜 틀린지, 종료 코드 2와 구분해 설명하세요. 또 `unknown`과 `ok`의 차이를 예(테스트 수 감소, 원격 push)로 드세요.
3. T-005 원본 `0b7b045`의 `TypeError` 사고와 `UnicodeEncodeError` 사고에서 각각 어떤 입력이 원인이었고, 왜 "타입 검사"와 "출력 인코딩 처리"가 필요한지 설명하세요. failed Task가 있다고 T-005가 실패한 제품이라고 보면 안 되는 이유도 쓰세요.

## 11. 모범 답안

1. 감독 도구가 직접 고치거나 중지하면 도구의 오판이 곧 사고가 되므로, 최악의 결과를 "잘못된 경고"로 제한하려고 읽기 전용으로 만듭니다. 두 번째 장치는 허용목록입니다. 실행 직전에 git/orca 하위 명령을 읽기 전용 목록과 대조해 push·commit·merge·worker-stop 등은 실행 없이 `denied` 처리합니다. 추가로 stderr 폐기, 타임아웃, 출력 크기 검사가 있으나 4MiB는 실행 후 검사이지 실시간 메모리 제한이 아닙니다.
2. 종료 코드 1은 점검을 끝까지 했고 경고·불일치를 발견했다는 정상 산출물입니다(예: 반려 2회). 종료 코드 2는 git·BOARD·orca 같은 필수 소스를 못 쓰거나 인자·파싱이 잘못돼 점검 자체를 신뢰할 수 없다는 뜻입니다. `ok`는 확인해 문제없음, `unknown`은 이 도구가 판단할 증거가 없음입니다. 테스트 수 감소와 원격 push 여부는 허용 자료로 볼 수 없으므로 항상 unknown이고, "없다"는 뜻이 아니라 S4 등 사람이 확인할 몫입니다.
3. 첫 사고는 Orca 응답의 task `id`가 리스트(`[]`)인 손상 입력이었습니다. dict 키로 쓰려다 `TypeError`가 났고, 해결은 실제 쓰는 필드의 타입을 입력 경계에서 검증해 고정 오류와 exit 2로 처리하는 것(`be09b34`)이었습니다. 두 번째는 BOARD의 `・`(U+30FB)가 Windows cp949 stdout에서 인코딩되지 않은 것이었고, JSON은 `ensure_ascii=True`로, 텍스트는 표현 불가 문자만 `\uXXXX`로 치환하는 `write_safe`로 해결했습니다(`3a38765`). 외부 입력과 외부 출력 환경은 통제할 수 없으니 두 경계 모두 방어해야 합니다. failed Task는 결함을 입증한 정정 기록이고 같은 T-ID의 후속 Task가 completed로 해결했으며 최종은 PASS·병합(`c3984b9`)이므로 최종 제품 실패가 아닙니다.
