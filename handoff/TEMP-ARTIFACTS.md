# 임시 폴더 산출물 기록

2026-11-12 · 작성: 사용자 대화 세션(Claude Sonnet 5.5). 이 문서는 BOARD·DECISIONS와 별개의 보존 기록이다.

작업 중 세션 임시 폴더(`C:\Users\jeong\AppData\Local\Temp\claude\f23deedcd8b576ee\07218a01-f0fe-417d-8e45-1b542f6b3629\scratchpad`)에 만든 파일이 있다. 임시 폴더는 정리되면 사라질 수 있으므로 아래와 같이 옮겼다. `DECISIONS.md` D-011·D-012가 가리키는 임시 경로(`...\scratchpad\drive-sample\ref\sample_x.json` 등)는 이 표의 새 위치로 읽는다.

## 1. 지시서 (Git에 포함)

| 원래 파일 | 새 위치 | 내용 |
|---|---|---|
| `S0-codex-brief.md` | `handoff/briefs/S0-codex-brief.md` | 최초 S0 지휘관 브리핑(`ROLES.md`의 원본) |
| `S0-model-policy.md` | `handoff/briefs/S0-model-policy.md` | 단계별 모델·effort 정책, 승격 규칙 |
| `S0-resume-brief.md` | `handoff/briefs/S0-resume-brief.md` | 전원 차단 후 재개 지시, 복구 사실 |
| `S0-decisions-2026-11-12.md` | `handoff/briefs/S0-decisions-2026-11-12.md` | D-011(X 답글)·D-012(실데이터)·D-013(지식 사전), 진행감독관, ROADMAP 지시 |

## 2. 분석 스크립트 (Git에 포함, 모두 읽기 전용)

`handoff/analysis-scripts/`

| 파일 | 하는 일 |
|---|---|
| `drive_list.py` | Drive 공개 폴더 목록 읽기(내려받지 않음). 큰 폴더에서는 시간이 오래 걸려 최상위만 보는 방식으로 대체했다 |
| `chk.py` | `catalog.csv` 건강 검사(중복·빈 값·날짜 형식·깨진 글자) |
| `schema.py`, `probe.py` | SQLite 구조 확인, Instagram·X 행 품질 확인(`mode=ro`) |
| `qual.py` | X·Instagram 품질 검사와 샘플 추출 |
| `reply.py` | X 답글 연결 필드와 중복 답글 측정(D-011의 근거) |

DB는 항상 복사본을 읽기 전용으로 열었다. 원본(`C:\Users\jeong\Documents\ai-raider\data\raider.sqlite`)은 수정하지 않았다.

## 3. 실제 데이터 샘플 (Git 제외 — `data/`는 .gitignore)

**실제 게시물 본문이 들어 있어 공개 저장소(PUBLIC)에 올리지 않는다.** 위치는 이 워크트리 기준 `data/reference-samples/`이며, 워크트리를 삭제하면 함께 사라진다. 무결성 확인용 SHA-256 앞 16자리를 적는다.

| 파일 | 내용 | SHA-256(앞 16자) |
|---|---|---|
| `data/reference-samples/sample_x.json` | X 무작위 300건(전체 20,659건 중) | `b529d0ed03c46be6` |
| `data/reference-samples/sample_instagram.json` | Instagram 전체 74건 | `a95b0f7dc6fa2478` |
| `data/reference-samples/drive-metadata/catalog.csv` | Drive 수집분 목록 62,418건(갤러리·HF·뉴스·YouTube) | `6cfaf0b2f5b164e7` |
| `data/reference-samples/drive-metadata/summary.json` | 출처별 건수·기간 | `28cfbd1b642f9ff4` |
| `data/reference-samples/drive-metadata/collection-status.json` | `closed_partial` 상태, 수집 오류 | `87794ebb078e61c1` |

### 3-1. 샘플 선택 기록 (Git에 포함)

위 샘플은 본문이 Git 밖에 있으므로, **무엇을 골랐는지**를 `handoff/samples/`에 따로 기록했다(ID·선택 기준·원본 DB 정보, 본문 없음). 이 샘플은 평가용 정답이 아니다. 같은 샘플을 다시 만드는 절차는 `handoff/samples/README.md`를 따른다.

## 4. 보존하지 않은 것

| 파일 | 이유 |
|---|---|
| `scratchpad/db-copy/raider.sqlite`(약 125MB) | 사용자 원본 DB의 복사본. 필요하면 원본에서 다시 복사한다 |
| Drive `raider.sqlite`(3.9GB), `github.sqlite`(3.5GB) | 내려받은 적 없음. Drive 폴더에만 있다 |
| `.private/`, 세션·쿠키·토큰·계정 보관 파일 | 읽거나 복사하지 않았다 |

## 5. 알려진 사실 (샘플 기준, 2026-11-12 측정)

- X 20,659건 / Instagram 74건 / 뉴스 50건(로컬 DB). 갤러리 30,727 · Hugging Face 29,087 · 뉴스 2,603 · YouTube 1(Drive 카탈로그).
- X 답글 7,694건(37%) 중 부모 ID 보유 7,676건, 부모가 수집 DB에 있는 것은 133건.
- 정규화 본문이 같은 답글은 27묶음(합치면 57행 감소).
- Instagram은 `feedback_required`로 차단된 상태 — 재수집 금지(D-012).
- Drive 수집은 `closed_partial`이며 완전한 과거 수집을 보증하지 않는다. 갤러리 오류 32건·Hugging Face 문서 복구 대기 155건이 남아 있다.
