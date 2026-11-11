# T-001-dev 보고서

모델: claude-sonnet-5-5 (medium)

## API 예시
```python
from agents.base_supervisor import Supervisor, RateLimited, SessionExpired, Blocked, SupervisorStopped
sup = Supervisor("x", state_path="tmp/x.json")   # source별 전용 파일, 없으면 메모리만
result = sup.run(collect, stop=event, fallback=edge_fallback, max_retries=3)
sup.snapshot()  # {source,state,updated_at,retry_at,reason}
```

## 변경 파일
- agents/base_supervisor.py (신규)
- tests/test_supervisor.py (신규, 16 tests)
- handoff/reports/T-001-dev.md

## 명령 · 종료 코드
| 명령 | 변경 전 | 변경 후 |
|---|---|---|
| `uv run python -m unittest discover -s tests -v` | exit 0, 50 tests | exit 0, 66 tests |
| `uv run python -m unittest discover -s tests/blackbox -v` | exit 0 | exit 0, 7 tests |
| `git diff --check` | - | exit 0 (커밋 전 확인) |

## reason 코드
init, ok, rate_limited, session_expired, blocked, fallback_used, fallback_error, fallback_rate_limited, fallback_session_expired, operation_error.

## 확인 못 한 부분
- 실제 수집기·대시보드·Edge 연결 없음(주입 지점만). 실제 sleep/네트워크 미사용, mock Event/clock만 검증.
- 일반 예외는 상태를 바꾸지 않고 reason만 operation_error로 기록(상태 유지).
- 다중 프로세스 동시 쓰기, 디스크 가득 참 등 실환경 저장 실패는 mock(os.replace 실패)으로만 검증.
- 같은 state_path를 서로 다른 인스턴스가 공유하는 경우의 동기화는 보장하지 않음(source별 전용 파일 전제).
- Windows 외 OS 미검증.

## 범위 밖 필요 사항
기존 수집기/대시보드에 Supervisor 연결, Edge fallback 구현은 후속 통합 작업.
