# T-003 · 합성 gold dataset 과 블랙박스 검증 틀 학습 문서

> 근거: `handoff/specs/T-003.md`, `handoff/reviews/T-003-qa.md`, `handoff/DECISIONS.md`(D-008), `tests/blackbox/README.md`, `tests/blackbox/fixtures/gold_samples.json`, `tests/blackbox/test_gold_samples.py`.
> 수치 기준: 수락 최종 커밋 `ff69a03`. **15개 합성 사례, 신규 12개 테스트**는 그 시점 기준이다. QA 리뷰의 69개/blackbox 19개는 보완 전 시점 수치이고, S0 병합 후 develop 전체 98개·blackbox 30개 exit 0 이다. 이후 수정되면 숫자는 달라질 수 있다. 이 문서 작성 중 테스트는 재실행하지 않았다.

## 1. 어떤 문제를 푸는가
수집·저장·분석 시스템은 "대충 잘 되는 것 같다"로는 검증이 안 된다. 특히 *값이 없음(None)* 과 *0*, 시간대 경계, 중복 저장처럼 실수하기 쉬운 지점에 **정답이 정해진 작은 예제 모음(gold dataset)** 이 있어야 이후 변경이 회귀를 만들었는지 알 수 있다. T-003은 실제 계정·실제 게시물 없이, 직접 만든 **합성 데이터** 15개와 이를 확인하는 테스트 틀을 만든다.

## 2. 구조: 왜 JSON + unittest 인가
- `tests/blackbox/fixtures/gold_samples.json`: `schema_version`, `known_concepts`(12개 용어 사전), `samples`(15개). 각 sample은 `id`, `provenance="synthetic"`, `tags`, `input`(저장소에 넣을 게시물), `expected`(기대값).
- `tests/blackbox/test_gold_samples.py`: `GoldSamplesBlackboxTests`의 `test_01`~`test_12`. 저장소(`core.store.Store`)와 `raider.window` 같은 **공개 인터페이스만** 호출하는 블랙박스 방식(내부 구현을 몰라도 계약만 확인).
- 데이터와 검증 코드를 분리했기 때문에 정답표만 고쳐도 되고, 비개발자도 JSON을 읽어 의도를 확인할 수 있다.

## 3. 핵심 개념
**sample id 와 dedup_key 는 다르다.** `id`(예: `sample-ig-null-likes`)는 정답표 안의 사례 이름이고, `dedup_key`(예: `instagram:ig-synth-001`)는 저장소의 중복 판단 키 `{platform}:{post_id}`(코드: `core/store.py`의 `ON CONFLICT(platform,post_id)`)다. 재수집 사례인 `sample-recollect-original`/`-updated`는 id는 둘이지만 dedup_key는 같아서, 두 번 저장해도 레코드가 1개이고 값은 최신으로 갱신되는지 `test_07`이 확인한다.

**None 과 0 구분.** `sample-ig-null-likes`(likes=`None`: 값을 알 수 없음)와 `sample-ig-zero-likes`(likes=`0`: 실제 0개)를 따로 둔다. 둘이 섞이면 "좋아요 0개"라는 거짓 통계가 생긴다. 테스트(`test_05`)는 `type is int`, `assertIsNot(val, False)`처럼 엄격히 비교해 `False==0` 같은 파이썬 함정도 막는다.

**KST 경계.** 사용자 날짜는 한국 시간(KST)이고 내부는 UTC다. `raider.window("2026-08-09", "2026-11-09")`의 시작점은 UTC `2026-08-08T15:00:00`. 1초 전(`14:59:59`)은 구간 밖, 정각과 1초 후는 구간 안으로 기대값을 둔 세 사례가 `test_09`에서 확인된다(반열린 구간 `[begin, finish)`).

**예약 예시 호스트.** 모든 URL(게시물·미디어 전부)은 RFC 2606 예약 도메인(`example.com/.org/.net`과 그 하위)만 쓴다. 실제 사이트로 나갈 일이 없고 실존 계정과 혼동되지 않는다. `test_02`의 검증기는 문자열 포함 검사가 아니라 `urllib.parse.urlsplit(...).hostname`을 보고, `example.com.evil.invalid`, `notexample.com`, `javascript:` 같은 우회 시도를 거부한다.

**합성 근거와 known_concepts.** `expected.analysis`는 사람이 손으로 쓴 **미래 분석기용 정답 기준안**이다: `category`, `evidence_terms`(원문·전사·OCR에 실제로 있는 단어), `new_concepts_detected`(`known_concepts`에 없는 새 용어), `is_pure_noise` 등. `known_concepts`는 이 테스트용 초기 기준 사전이지 **사용자의 지식 사전 자체가 아니다**.

## 4. "저장소 검증"과 "분석 정답 일관성 검증"의 차이
| 구분 | 무엇을 확인 | 실제 코드와 비교? |
|---|---|---|
| 저장소·시간 계약(`test_04`~`test_10`) | `Store`가 None/0, 빈 본문, 중복, 긴 유니코드, KST 경계, 오류 마스킹을 실제로 지키는지 | **예**: 실제 `Store`·`raider.window`를 호출 |
| 분석 정답 일관성(`test_11`) | 정답표 안에서 `evidence_terms`가 원문에 실제로 있고, 사전에 없는 용어만 `new_concepts_detected`에 있고, 순수 잡담은 근거가 비었는지 | **아니오**: 아직 분석기·LLM이 코드에 없다. 정답표 자기 자신의 모순 여부만 확인 |

따라서 이 테스트는 **모델의 분류·환각 억제 성능을 검증한 것이 아니다.** 나중에 분석기를 만들면 이 정답표를 입력으로 삼아 비교하게 되며, 그때 비로소 성능 측정이 가능하다(그 분석기의 존재는 코드에서 확인 안 됨). 정답표(gold 기준안)는 S0 승인으로 **개정할 수 있는 초기 기준**이다.

## 5. 사용한 도구와 선택
| 도구 | 역할 | 장단점/대안 |
|---|---|---|
| `unittest`(stdlib) | 테스트 실행(`discover -s tests`) | 의존성 없음·기존 테스트와 일관 / pytest보다 문법이 길다 |
| `json` | 정답표 로드 | 사람이 읽기 쉬움 / 주석 불가 → YAML |
| `urllib.parse.urlsplit` | 호스트 정확 비교 | 부분 문자열 우회 방지 |
| `tempfile`, `unittest.mock.patch` | 임시 DB·모의 오류 사용, 실제 DB 미사용 | 격리 쉬움 / mock이 현실과 다를 수 있음 |
| `datetime`/`timezone` | KST·UTC 경계 계산 | — |
| 대용량 `repeat_spec` | JSON 팽창 방지, 테스트에서 10,000자 이상으로 확장 | 파일이 작음 / 데이터가 코드에 의존 |

## 6. 한계
실제 외부 수집·로그인 세션·LLM 추론은 쓰지 않았다(미검증). 15개 사례는 경계 위주 최소 집합이라 실제 데이터 분포를 대표하지 않는다. 7개 플랫폼을 모두 포함한다고 QA가 확인했지만 플랫폼별 심층 동작은 이 테스트의 범위가 아니다.

## 7. 서술형 문제와 모범 답안
**문제 1.** `id` 와 `dedup_key` 가 따로 있는 이유를, 재수집 사례로 설명하라.
> 모범 답안: `id`는 정답표의 사례 이름이고 `dedup_key`는 저장소가 같은 게시물인지 판단하는 `{platform}:{post_id}`다. `sample-recollect-original`과 `-updated`는 id가 달라도 dedup_key가 같아, 두 번 저장해도 레코드가 1개로 유지되고 값만 갱신되어야 함을 확인한다.

**문제 2.** `likes=None` 과 `likes=0` 을 따로 검증하는 이유와, 테스트가 `0 == False` 를 조심하는 이유는?
> 모범 답안: None은 "알 수 없음", 0은 "실제로 0개"라서 섞이면 통계가 왜곡된다. 파이썬에서 `False == 0`이 참이므로 `type is int` 등으로 타입까지 엄격히 비교해야 잘못된 통과를 막는다.

**문제 3.** `test_11` 이 통과했다면 "분석 모델이 잘 분류한다"고 말할 수 있는가?
> 모범 답안: 없다. `test_11`은 정답표 자체가 원문 근거와 `known_concepts`에 모순 없는지만 검사하고, 모델 출력은 평가하지 않는다(현재 코드에 분석기 없음). 실제 성능은 분석기가 생긴 뒤 이 정답표와 비교해야 알 수 있으며, 정답표 자체도 S0 승인으로 개정될 수 있다.
