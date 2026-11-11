# T-002 · 게시물 조회 전용 MCP — 구현 보고 (S1)

모델 claude-sonnet-5-5 / medium. 브랜치 `jeongujeong117-byte/t-002-dev`.

## 변경 파일
`raider_mcp.py`(신규), `pyproject.toml`(extra `mcp = ["mcp>=1.2,<2"]`, py-module `raider_mcp`, script `ai-raider-mcp`), `uv.lock`, `tests/test_raider_mcp.py`(신규 17개), 본 보고서.

## SDK 근거
- 설치 버전 `mcp 1.30.0` (`uv run python -c "importlib.metadata.version('mcp')"`).
- 설치된 소스(`mcp/server/fastmcp`, `mcp/types.py`)에서 시그니처 확인: `FastMCP.tool(name, description, annotations: ToolAnnotations)`, `FastMCP.run(transport='stdio')`, `ToolAnnotations(readOnlyHint, destructiveHint, idempotentHint, openWorldHint)`. 설치 소스를 직접 확인했으며 웹 문서는 조회하지 않았다.
- 클라이언트 검증은 SDK의 `mcp.client.stdio.stdio_client` + `ClientSession`.

## 도구 입출력
- `list_posts(platform="", handle="", offset=0, limit=100)` → `{total, items[]}` (정렬 posted_at DESC, platform ASC, post_id DESC).
- `get_post(platform, post_id)` → post dict 또는 null (SDK가 `{"result": ...}`로 감쌈).
- `list_unanalyzed(...)` → 위와 동일 형식. `post_analyses`가 없으면 전부 미분석, 있으면 (platform,post_id) 쌍 제외, 필수 열 없으면 `ReaderError`. `processing`은 무시.
- 모든 도구 readOnlyHint=true, destructiveHint=false. 오류는 고정 메시지(`database query failed`, `stored post contains invalid JSON` 등)로 변환, SQL/절대경로 미노출(테스트 확인).
- 읽기: `file:...?mode=ro` URI + `PRAGMA query_only=ON`, 요청마다 연결 후 close. Store 미사용.

## 검증 (명령 / 종료코드 / 테스트 수)
| 명령 | rc | 결과 |
|---|---|---|
| 변경 전 `uv run python -m unittest discover -s tests` | 0 | 50 tests OK |
| 변경 전 `... discover -s tests/blackbox` | 0 | OK |
| 변경 후 `uv run --extra processing --extra mcp python -m unittest discover -s tests` | 0 | 67 tests OK (신규 17 포함) |
| 변경 후 blackbox discover | 0 | OK |
| mcp extra 없이 (`uv sync --extra processing`) 전체 discover | 0 | 67 tests, skipped=4 (서버 stdio 테스트 4개만 skip, `import raider_mcp` 성공) |
| `uv run --extra mcp python raider_mcp.py --help` | 0 | 사용법 출력 |
| wheel 빌드 | 0 | `raider_mcp.py` 포함, entry point `ai-raider-mcp = raider_mcp:main` |
| `git diff --check` | 0 | CRLF 경고만 |

신규 테스트가 다루는 것: 빈 목록, 단건 없음, 같은 ID 다른 플랫폼, 페이지/total/정렬, None·빈 문자열·300k 대용량 raw 보존, SQL 인젝션 필터(리터럴 처리), 잘못된 입력(bool/범위/타입), 미분석 테이블 없음/있음/오염(열 누락)/processing 무시, 손상 JSON, posts 테이블 없는 DB, 없는 DB(생성 안 됨), 쓰기 시도 차단.
실제 SDK client가 임시 서버를 stdio로 기동하여 initialize/list_tools(3개, 이름·annotation)/call_tool 6건(정상·null·오류)을 검증. 원시 stdio 테스트에서 stdout은 JSON-RPC 2줄만 출력되고 종료 후 추가 출력 없음(SDK 로그는 stderr).

## 쓰기 없음 증거
요청 전후 sha256·mtime_ns·sqlite_master 테이블 목록 동일(MCP 호출 후, 및 post_analyses 없는 경우 list_unanalyzed 후). 없는 DB는 `FileNotFoundError`/서버 종료 코드 2이며 파일 미생성(테스트). 연결 수준에서 `DELETE` 시도가 sqlite 오류로 거부됨.

## 확인 못 한 부분
- 실제 사용자 DB·.private는 의도적으로 읽지 않았다(임시 fixture만 사용).
- 실제 외부 MCP 클라이언트(Claude Desktop 등) 등록/연동은 범위 밖이라 미검증.
- WAL 모드 DB를 mode=ro로 열 때 -shm 파일 생성 여부는 미검증(fixture는 기본 journal).
- Windows만 실행. 서버 stderr에 SDK 요청 로그("Processing request ...")가 출력됨(경로/비밀 없음).
- `post_analyses` 실제 스키마는 아직 없어 (platform,post_id) 읽기 계약만 가정.

## 범위 밖 필요 사항
`post_analyses` 스키마/저장 경로(향후 task), MCP 클라이언트 등록 문서.

## 1차 반려 대응 (QA 39ebef9 / S0 stdio 재현)
- 원인: FastMCP/Pydantic lax 모드가 `limit=true`, `"2"`, `offset=false` 등을 `int`로 강제 변환해 `PostReader` 검증 전에 통과시킴.
- 수정: `raider_mcp.py` 도구 시그니처를 `pydantic.StrictInt`(limit/offset) / `StrictStr`(platform/handle/post_id)로 변경(import는 `create_server` 내부라 mcp 미설치 import 동작 유지). `PostReader`의 `_int/_str` 검증은 이중 방어로 유지.
- 회귀 테스트 `test_strict_argument_types_over_stdio`(실제 SDK stdio): list_posts/list_unanalyzed의 limit·offset에 bool/수치 문자열/float/null, 필터에 int/bool/null/list, get_post 식별자에 int/bool/null → 모두 `isError=true`(26건); 정상 int·문자열 3건은 `isError=false`.
- 수정 전 동일 입력 `limit=true`/`"2"`/`offset=false`가 성공했음은 S0·QA가 재현(QA test_04).
- `mode=ro` URI 유지(immutable 미사용, WAL/최신 데이터 가시성 유지). S2 테스트 미수정.
- 재검증: 신규 포함 `tests` 68 tests rc0; 이 워크트리 `tests/blackbox` 7 tests rc0; mcp extra 없이 `import raider_mcp` 성공, 전체 OK (skipped=5, 서버 stdio 테스트); `git diff --check` rc0.
- 주의: QA 브랜치의 블랙박스 test_04(강제 변환 현상 기록)는 이 수정 후 기대값이 바뀔 수 있으며, 본 브랜치에는 포함되지 않아 그 병합본에서 실행해 보지 못했다.
