# T-000 DEV 보고서

모델: claude-sonnet-5-5 (effort medium). 이전 Opus 실행의 미커밋 변경(루트 8개 파일 + 미추적 core/, agents/)을 인계받아 diff 검토·검증 후 커밋했다. reset/clean 없음.

## 결과
완료. 저장소/미디어/후처리/소스 도구·관리자는 `core/`, 플랫폼별 수집은 `agents/`로 분리했고 루트 모듈은 호환 별칭(`sys.modules[__name__] = 구현 모듈`)만 남겼다. 로직 복사본 없음. 기존 테스트 50개 전부 통과, 기존 테스트 파일 변경 없음.

## 변경 파일
- 수정: raider.py, source_manager.py, source_tools.py, source_agents.py, github_agent.py, media_store.py, post_processing.py, pyproject.toml(`packages = ["core", "agents"]` 한 줄)
- 신규: core/{__init__,common,store,media_store,post_processing,source_manager,source_tools}.py, agents/{__init__,instagram_agent,x_agent,youtube_agent,news_agent,gallery_agent,huggingface_agent,github_agent,source_agents}.py
- 신규: handoff/reports/T-000-dev.md

## 이동 대응표
| 기존 | 새 위치 |
|---|---|
| raider.Store | core/store.Store (raider.Store는 DB 기본 경로=raider.DATA, 분류 계정=raider.accounts()를 연결하는 얇은 하위 클래스) |
| raider.ROOT/DATA/PRIVATE/UTC/KST/now | core/common.py (ROOT=저장소 루트) 를 raider가 재노출 |
| raider.instagram | agents/instagram_agent.instagram (raider.instagram은 raider.PRIVATE를 넘기는 위임 generator) |
| raider.x_posts | agents/x_agent.x_posts (동일 방식 위임) |
| raider.Cancelled | agents/__init__.Cancelled |
| media_store.py | core/media_store.py |
| post_processing.py | core/post_processing.py |
| source_manager.py | core/source_manager.py |
| source_tools.py | core/source_tools.py |
| github_agent.py | agents/github_agent.py |
| source_agents.py (SourceAgent, ADAPTERS, KINDS, 날짜/post 도우미) | agents/source_agents.py |
| Youtube/News/Gallery/HuggingFace Extractor | agents/{youtube,news,gallery,huggingface}_agent.py (source_agents에서 재노출) |
| Runner, HTTP 서버, main | raider.py 유지 |

## 실행 명령·종료 코드·테스트 수
| 명령 | 시점 | exit | 결과 |
|---|---|---|---|
| `uv sync --extra processing` | 변경 후(환경 기설치) | 0 | Checked 73 packages |
| 기준 unittest (HEAD 02ed07c를 임시 worktree로 추출, 같은 venv python) | 변경 전 | 0 | Ran 50 tests OK |
| `uv run python -m unittest discover -s tests -v` | 변경 후 | 0 | Ran 50 tests OK |
| `uv run python tests/smoke_http.py` | 변경 후 | 0 | PASS (임시 저장소·가짜 수집기) |
| `uv run python raider.py --help` | 변경 후 | 0 | 기존 서브커맨드 표시 |
| 7개 agents + core 3개 import 명령 | 변경 후 | 0 | OK |
| `uv build --wheel` (임시 출력 폴더) | 변경 후 | 0 | wheel에 core/*, agents/* 전체 및 루트 7개 모듈 포함 확인. build/·egg-info 삭제, 미커밋 |
| `git diff --check` | 변경 후 | 0 | 경고는 LF→CRLF 안내뿐 |

## 호환 검증
기존 tests 전체가 수정 없이 통과(raider.ROOT/DATA/PRIVATE/now/instagram 및 source_agents/github_agent/media_store 등 monkeypatch 지점 포함). 루트 별칭은 같은 모듈 객체를 반환하므로 monkeypatch가 구현에 직접 적용된다. smoke_http로 HTTP 경로·CSRF·재개·분류·처리/내보내기 경로 확인. 순환 import 없음(import 명령 통과).

## 확인 못 한 부분
- 실제 Instagram/X/외부 네트워크 수집은 실행하지 않았다(금지). instagram_agent/x_agent의 실계정 동작은 미검증이며 코드 이동 diff 검토로만 확인했다.
- `uv sync` 변경 전 기준 실행은 하지 않았다(환경이 이미 동기화되어 있어 변경 후에 실행). 기준 테스트는 HEAD 추출본을 같은 venv로 실행.
- `uv run python raider.py serve` 실제 기동·`ai-raider` 콘솔 스크립트 설치 실행은 하지 않았다(smoke_http의 서버 기동으로 대체). wheel 엔트리포인트 메타데이터는 열어보지 않았다.
- 한글 콘솔 출력이 Git Bash에서 깨져 보였는데 인코딩 표시 문제로 추정, 미조사.
- 이전 Opus 실행의 자체 검증 기록은 없어 신뢰하지 않고 위 항목을 새로 실행했다.
- `handoff/specs`, ROLES는 읽기만 했고 MCP/Windows 외 OS는 검증하지 않았다.

## 범위 밖 필요 사항
없음(기존 결함 발견 없음).
