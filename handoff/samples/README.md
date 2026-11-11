# 샘플 선택 기록

2026-11-12. 분석 연습용으로 뽑은 실제 게시물 샘플의 **ID 목록과 선택 기준**이다. 게시물 본문·반응 수치는 공개 저장소에 올리지 않기 위해 이 폴더에 두지 않았다.

## 이 샘플의 성격

- **평가용 정답이 아니다.** 사람이 "AI 소식인가/아닌가"를 표시한 적이 없다. 답글, 영어 잡담, 내용 없는 글이 섞여 있다.
- 용도는 형식 확인과 분석 연습이다. 평가용 정답 만들기는 Phase 2 명세에서 따로 정한다(ROADMAP 참조).

## 파일

| 파일 | 내용 |
|---|---|
| `sample_x_ids.json` | X 300건. `post_id`, `handle`, `posted_at`만 기록 |
| `sample_instagram_ids.json` | Instagram 74건(해당 DB의 Instagram 전체). 같은 3개 필드 |
| `source-db-info.json` | 뽑은 원본 DB의 경로·크기·건수·기간·복사본 SHA-256, 샘플 ID가 원본에 없는 건수(0) |

## 선택 기준

| 플랫폼 | 모집단 | 선택 방법 |
|---|---|---|
| X | `posts` 테이블의 `platform='x'` 전체 20,659건 | 파이썬 `random.seed(7)` 후 `random.sample(rows, 300)`. 행 순서는 `ORDER BY` 없는 조회 결과라 **순서에 의존하므로 재현하려면 시드 대신 이 ID 목록을 쓴다** |
| Instagram | `platform='instagram'` 전체 74건 | 전부 |

필터(답글 제외, 언어, 기간 등)는 적용하지 않았다. X 샘플 300건에는 답글(`@`로 시작)이 섞여 있다.

## 원본 DB (읽기 전용으로만 사용)

- 위치: `C:\Users\jeong\Documents\ai-raider\data\raider.sqlite` — 이 PC의 사용자 작업 폴더. 수정하지 않았다.
- 복사 시점에 원본과 복사본의 크기가 같았다(125,575,168바이트). 원본 마지막 수정은 2026-11-10 20:15(UTC) 이후 변화 없음.
- 행 수: X 20,659 · Instagram 74 · 뉴스 50. X 기간 2026-08-09 ~ 2026-11-10.

## 다음 세션에서 같은 샘플을 다시 만드는 법

1. 원본 DB의 크기와 행 수를 `source-db-info.json`과 비교한다. 다르면 원본이 바뀐 것이므로 사용자에게 알린다.
2. 원본을 **복사해서 읽기 전용(`mode=ro`)으로** 연다.
3. 두 ID 파일의 `(platform, post_id)`로 `posts`에서 해당 행을 조회한다. 본문은 `data/reference-samples/`(Git 제외)에 저장한다.
4. 실계정 로그인, `.private/`, 세션·쿠키는 사용하지 않는다. Instagram은 `feedback_required`로 차단된 상태이므로 재수집하지 않는다.

관련 기록: `handoff/TEMP-ARTIFACTS.md`, `handoff/DECISIONS.md` D-011·D-012, `handoff/analysis-scripts/qual.py`(추출 코드).
