# T-000 학습 문서: core / agents 분리

대상: 코딩을 처음 배우는 분. 근거: `handoff/specs/T-000.md`, `handoff/reports/T-000-dev.md`, `handoff/reviews/T-000-qa.md`, 실제 코드와 테스트(개발 커밋 c4783ac, QA 커밋 ccec489).

## 1. 어떤 문제를 풀었나

이전에는 저장소 코드, 미디어 다운로드, 7개 정보원 수집 코드가 저장소 루트에 한데 섞여 있었다. 서랍 하나에 가위, 서류, 공구가 같이 들어 있는 상태와 비슷하다. 이후 작업(T-001 이후)이 여러 개 동시에 진행되려면 "공용 도구"와 "정보원별 수집기"를 나눠야 한다. 그런데 **동작은 하나도 바뀌면 안 된다**는 조건이 붙었다. 이번 작업은 "기능 추가"가 아니라 "정리 이사"다.

## 2. 이동 전후 구조

| 이동 전(루트) | 이동 후 |
|---|---|
| raider.py 안의 Store | `core/store.py` (`core.store.Store`) |
| media_store.py, post_processing.py, source_manager.py, source_tools.py | `core/` 아래 같은 이름 |
| raider.py 안의 Instagram/X 수집 | `agents/instagram_agent.py`, `agents/x_agent.py` |
| source_agents.py 안의 YouTube/뉴스/갤러리/HuggingFace | `agents/youtube_agent.py`, `news_agent.py`, `gallery_agent.py`, `huggingface_agent.py` |
| github_agent.py | `agents/github_agent.py` |
| source_agents.py의 공통 `SourceAgent`, 날짜/post 도우미 | `agents/source_agents.py` |
| 경로·시간 도우미 | `core/common.py` (ROOT, DATA, PRIVATE, KST, now) |

루트의 `source_manager.py`, `source_tools.py`, `media_store.py`, `post_processing.py`, `github_agent.py`, `source_agents.py`는 짧은 "안내판" 파일로 남았다. 줄 수는 `core/` 7개 파일 합계와 `agents/` 9개 파일 합계가 모두 이 구조를 보여 준다(core 7개, agents 9개는 QA가 wheel에서 확인).

## 3. 루트 `raider.py`의 책임

`raider.py`는 여전히 실행 진입점이다. 남은 책임:

- HTTP 서버(`serve`, 표준 라이브러리 `ThreadingHTTPServer`)와 `main`(CLI).
- 수집 실행 관리자 `Runner`(중단/재개 포함).
- 날짜 창 계산 `window`, `months_ago`.
- 호환용 얇은 래퍼: `Store`(기본 DB 경로를 `raider.DATA`로 연결), `instagram`, `x_posts`(`raider.PRIVATE`를 넘겨 주는 위임).

`uv run python raider.py serve`와 `ai-raider = raider:main`(`pyproject.toml`) 계약은 유지됐다.

## 4. 왜 import와 monkeypatch 호환이 중요했나

기존 테스트 50개는 `import source_agents`처럼 옛 이름으로 불러오고, 테스트 중에 `raider.now`, `raider.PRIVATE` 같은 값을 **임시로 바꿔치기(monkeypatch)** 한다. 그런데 "기존 테스트를 고쳐서 해결하지 않는다"는 규칙이었다. 그래서 두 장치를 썼다.

1. **`sys.modules` 별칭**. 루트 파일 전체 내용이 사실상 이것이다.
   ```python
   from core import media_store as _implementation
   sys.modules[__name__] = _implementation
   ```
   `import media_store`를 하면 `core.media_store`와 **같은 객체**가 돌아온다. 복사본이 아니므로, 루트 이름에 한 monkeypatch가 진짜 구현에 그대로 적용된다. QA의 `test_01`이 `is` 동일성으로 확인했다.
2. **위임 래퍼(raider.py)**. 예: `raider.instagram`이 `private=PRIVATE`를 넘겨 `agents.instagram_agent.instagram`을 호출한다. 테스트가 `raider.PRIVATE`를 바꾸면 그 값이 실제로 쓰인다.

또 `core/common.py`의 `ROOT`는 `parent.parent`(저장소 루트)다. 파일이 `core/`로 이동했는데 `parent`만 쓰면 데이터 폴더가 `core/data`로 잘못 잡힌다. QA `test_02`가 이를 확인한다.

## 5. SQLite, stdlib 서버, sys.modules 별칭: 역할과 단점

| 요소 | 역할 | 단점 |
|---|---|---|
| SQLite (`core/store.py`, `sqlite3`) | 게시물·실행·작업·처리 상태를 파일 한 개에 저장. `posts` 등 테이블, 같은 post는 키로 덮어써 중복을 막는다. | 동시에 많은 쓰기에는 약함(연결 timeout 30초 설정). 스키마 변경 도구(마이그레이션)는 이번 범위 밖이라 없음. |
| 표준 라이브러리 서버 (`ThreadingHTTPServer`) | 외부 패키지 없이 로컬 웹 화면과 API 제공. | 인증·성능·라우팅 기능이 최소. 127.0.0.1(자기 컴퓨터) 전용 사용이 전제. |
| `sys.modules` 별칭 | 옛 import 이름을 복사 없이 유지. | 마법처럼 보여 초보자가 읽기 어렵고, IDE 자동완성/정적 분석이 약해질 수 있다(이 판단은 일반적 특성이며 이 프로젝트에서 측정한 것은 아님). 언젠가 걷어내는 작업이 필요. |

이 문서는 새 라이브러리를 선정했다는 뜻이 아니다. 위 SQLite와 서버는 이번 작업 전부터 쓰던 것을 옮긴 것이다.

## 6. 대안은 무엇이었나

- **루트 유지(안 나눔)**: 가장 안전하지만 파일이 계속 커지고 병렬 작업이 서로 충돌한다.
- **패키지로 전면 전환**(루트 파일 삭제, 모든 import를 `core.x`로 변경): 구조는 깔끔하지만 기존 테스트와 monkeypatch 지점을 모두 고쳐야 해서 "동작 보존" 확인이 어렵다.
- **선택한 방식**: 새 패키지로 나누되 루트에는 별칭만 남기는 중간 길. 위험은 작고, 정리는 나중에 단계적으로 가능하다.

## 7. 검증된 것과 아닌 것

검증됨(문서에 적힌 실행 기록 기준):
- 기존 단위 테스트 **50개** 통과(병합 후 S0 재실행 포함), QA 블랙박스 **7개** 통과.
- `tests/smoke_http.py`(임시 저장소+가짜 수집기), `raider.py --help`, 모듈 개별 import, wheel 포함 내역, 임시 환경에서 `ai-raider --help` 통과.
- 저장 시 `likes=None`, 빈 본문 보존, KST 날짜 경계, 중단 후 재개 중복 방지, 오류 메시지의 비밀 제거(가짜 토큰 사용).

미검증:
- Instagram/X **실계정** 수집(금지되어 가짜 세션으로만 시험).
- OCR 등 **실엔진/GPU** 실행(QA 보고서상 mock으로 인터페이스만 확인).
- 실제 외부 네트워크 수집 전반.
- 이 문서 작성자는 코드를 읽기만 했고 테스트를 직접 재실행하지 않았다. 숫자는 보고서·테스트 파일의 `def test` 개수(14+8+8+12+8=50, 블랙박스 7)와 대조했다.
- 새 건강 상태(상태 4종)나 MCP는 **아직 구현되지 않았다**(spec의 범위 밖). Phase 1 이후 과제다.

## 8. 예상 문제 (서술형)

**문제 1.** 루트의 `media_store.py`를 복사본이 아니라 `sys.modules` 별칭으로 만든 이유를 설명하라.

모범 답안: 기존 테스트가 `media_store.<이름>`을 monkeypatch한다. 복사본이면 바꿔치기가 진짜 구현에 닿지 않아 테스트가 어긋난다. 별칭은 `core.media_store`와 같은 모듈 객체를 돌려주므로 루트 이름의 변경이 구현에 즉시 적용되고, 로직 중복도 없다. 테스트를 고치지 않고 동작을 보존할 수 있다.

**문제 2.** `core/common.py`에서 `ROOT`가 `Path(__file__).resolve().parent.parent`인 이유는?

모범 답안: 이 파일은 `core/` 안에 있으므로 `parent`는 `core/` 폴더이고 `parent.parent`가 저장소 루트다. 파일을 옮긴 뒤에도 `data/`, `.private/`, `web/`, `config/`를 루트 기준으로 찾아야 하기 때문이다. 틀리면 데이터가 `core/` 아래에 생기는 오류가 난다. QA `test_02`가 이를 검증한다.

**문제 3.** 이번 병합에서 "검증됐다"고 말할 수 있는 것과 없는 것을 구분하고, 이유를 말하라.

모범 답안: 가짜 수집기·임시 저장소로 한 50개 단위 테스트, 7개 블랙박스, HTTP 스모크, 패키징은 통과했으므로 "구조 이동 후에도 기존 동작이 유지된다"고 말할 수 있다. Instagram/X 실계정 수집과 OCR 실엔진은 보안 지침상 실행하지 않았으므로 미검증이다. 건강 상태나 MCP는 아직 구현되지 않았다.
