# T-001 · 수집기 상태 감시 기반 (Supervisor) 학습 문서

> 근거: `handoff/specs/T-001.md`, `handoff/reports/T-001-dev.md`, `handoff/reviews/T-001-qa.md`, `handoff/DECISIONS.md`(D-006, D-008), `agents/base_supervisor.py`, `tests/test_supervisor.py`, `tests/blackbox/test_t001_supervisor.py`.
> 수치 기준: 개발 최종 `140fcdf`, QA `0f0b8cb`. 테스트 수는 **각 수락 시점 보고 기준**이다(개발 시점 전체 68개·blackbox 7개, QA 시점 blackbox 18개, S0 병합 후 develop 전체 98개·blackbox 30개 exit 0). 이 문서 작성 중 테스트를 다시 돌리지 않았다.

## 1. 어떤 문제를 푸는가
SNS·뉴스 수집기는 자주 막힌다. "요청이 너무 많다(429)", "로그인이 끊겼다", "사이트가 차단했다" 같은 상황이다. 수집기마다 제각각 처리하면 (a) 무한 재시도로 계정이 더 막히거나, (b) 오류 메시지에 쿠키·토큰이 섞여 기록되거나, (c) 지금 어떤 상태인지 알 수 없게 된다.
T-001은 이를 한곳에서 다루는 **공통 상태 감시기(`Supervisor`)**를 만든다.

## 2. 무엇이 구현됐나 (`agents/base_supervisor.py`)
**네 가지 상태** (`HealthState`): `HEALTHY`(정상), `RATE_LIMITED`(요청 제한), `SESSION_EXPIRED`(세션 만료), `BLOCKED_FALLBACK`(차단됨, 우회 모드). 다섯 번째 상태는 금지다.

**공개 예외**: `RateLimited(retry_after=60)`, `SessionExpired`, `Blocked`, `SupervisorStopped`. `retry_after`는 유한한 0 이상 숫자만 허용하고 `bool`·`nan`·`inf`·음수·문자열은 `ValueError`.

**`Supervisor(source, state_path=None, *, clock=None)`** 와 `run(operation, *, stop=None, fallback=None, max_retries=3)`:

| 상황 | 동작 |
|---|---|
| operation 성공 | `HEALTHY`, `retry_at=None`, reason `ok` |
| `RateLimited` | `RATE_LIMITED` 기록(`retry_at = clock()+retry_after`) → `stop.wait(retry_after)` 대기 → 최대 `max_retries`번 **추가** 재시도. 한도 초과 시 예외를 그대로 올리고 상태 유지 |
| stop 신호 | 시작 전이든 대기 중이든 `SupervisorStopped`, 이후 operation 호출 없음 |
| `SessionExpired` | `SESSION_EXPIRED` 기록 후 **즉시 다시 올림**(재시도·우회 없음) |
| `Blocked` | `BLOCKED_FALLBACK` 기록. fallback이 있으면 **딱 한 번** 실행해 결과 반환(성공해도 상태는 `BLOCKED_FALLBACK` 유지 = "우회 중" 표시). 없거나 실패하면 예외 |
| 일반 예외 | 재시도 없이 올림. 상태는 그대로 두고 reason만 `operation_error` |

- `snapshot()`은 `source, state, updated_at, retry_at, reason` 다섯 키의 dict. reason은 고정 코드 10개(`init, ok, rate_limited, session_expired, blocked, fallback_used, fallback_error, fallback_rate_limited, fallback_session_expired, operation_error`)뿐이라 원시 예외 메시지·쿠키·토큰이 들어갈 수 없다.
- **원자 JSON 상태 기록**: `state_path`를 주면 상태가 바뀔 때마다 `_save()`가 같은 폴더에 임시 파일을 쓰고(`tempfile.mkstemp`, `fsync`) `os.replace`로 교체한다. 쓰는 도중 꺼져도 "반쯤 쓴 파일"이 남지 않는다. 실패하면 임시 파일을 지우고 예외를 숨기지 않는다.
- **복원**: `_load()`는 키 집합·source 일치·상태값·숫자형·reason 허용 목록을 모두 검사하고, 어긋나면 내용을 출력하지 않는 `ValueError("invalid supervisor state file")`를 올리며 **원본 파일을 덮어쓰지 않는다**.
- **source별 전용 파일 전제**: 한 소스(예: x)의 상태 파일을 다른 소스가 같이 쓰지 않는다. 같은 `state_path`를 여러 인스턴스·프로세스가 동시에 쓰는 경우의 동기화는 보장하지 않는다(보고서 "확인 못 한 부분"). 한 소스의 제한이 다른 소스를 막지 않도록 인스턴스를 소스마다 따로 둔다.

짧은 예(보고서의 API 예시 기반):
```python
from agents.base_supervisor import Supervisor, RateLimited
sup = Supervisor("x", state_path="tmp/x.json")
result = sup.run(collect, stop=event, fallback=edge_fallback, max_retries=3)
sup.snapshot()   # {"source": "x", "state": "HEALTHY", ...}
```

## 3. 왜 이런 구조인가
- **주입(injection)**: `clock`, `stop`, `fallback`, `operation`을 밖에서 넣는다. 테스트에서 가짜 시계·가짜 Event를 넣으면 실제로 기다리지 않고 검증할 수 있다. import·생성만으로 스레드·수집·브라우저가 시작되지 않는다.
- **fallback은 "연결 지점"일 뿐**: 나중에 Edge 브라우저 우회를 callback으로 꽂을 자리다. 지금은 실제 브라우저를 띄우지 않는다.
- **세션 만료는 재시도·우회 금지**: 로그인 끊김을 자동으로 우회하면 보안·약관 문제가 되므로 사람이 개입하도록 즉시 알린다.
- **재시도는 한정**: 무한 루프는 차단을 악화시킨다.

## 4. 사용한 라이브러리/stdlib 와 선택의 장단점
모두 표준 라이브러리다(외부 의존성 추가 없음, `pyproject.toml`·`uv.lock` 미변경).

| 모듈 | 코드에서의 역할 | 장점 | 단점 / 대안 |
|---|---|---|---|
| `enum.Enum` (`str` 혼합) | `HealthState` | 오타 방지, JSON에 문자열로 바로 저장 | 상태 전이 규칙 자체는 강제하지 못함 → 상태 머신 라이브러리 |
| `threading.Event` / `RLock` | stop 신호, 상태 갱신 잠금 | `Event.wait(초)`는 대기 도중 깨울 수 있어 `time.sleep`보다 중단에 유리 | 같은 프로세스 안에서만 유효. 다중 프로세스는 파일 잠금 필요 |
| `time.time` | 기본 clock | 단순 | 시스템 시간 조정에 흔들림. 다만 저장용 epoch 값이라 단조 시계는 부적합 |
| `json`, `tempfile`, `os.replace` | 원자 저장 | 외부 DB 없이 단순, 사람이 읽을 수 있음 | 프로세스 간 동시 쓰기 보호 없음 → SQLite, 파일 잠금 라이브러리 |
| `math.isfinite` | `nan`/`inf` 거부 | 잘못된 대기 시간을 초기에 차단 | — |
| 재시도 라이브러리(예: tenacity) | **사용 안 함** | 기능 풍부 | 의존성 추가 필요. 맞춤 규칙(stop 중단, fallback 한 번)은 직접 구현이 단순해서 선택(이 선택 이유는 코드에서 확인 안 됨, 필자의 해석) |

## 5. 검증 이력: 최초 PASS는 왜 수락되지 않았나
1. S1이 `7c51734`를 제출(전체 66개, blackbox 7개 통과 보고).
2. 독립 QA(S2)가 이 커밋에 **PASS**를 보고했다.
3. S0(총괄)가 직접 재현해 **미수락**했다(`DECISIONS.md` D-006). 이유: 테스트의 **기대값이 잘못**되어 있었다. "stop을 건 뒤 Blocked가 나도 fallback이 실행됨", "상태 파일에 적힌 임의 reason이 그대로 복원·노출됨"을 *정상 결과*로 고정해 두었기 때문이다. 스펙은 중단 후 fallback 금지, 고정 reason만 허용을 요구한다. 통과했다고 해서 계약이 맞는 것은 아니다.
4. QA가 PASS를 FAIL로 정정하되 **원본 FAIL 이력과 재현 명령을 보존**했다(`handoff/reviews/T-001-qa.md`).
5. S1의 1차 반려 수정 `140fcdf`: (a) `except Blocked:` 안에서 fallback 직전에 `stop.is_set()`을 다시 검사해 `SupervisorStopped`를 올림, (b) `_REASONS` 고정 집합과 `_load()` 검증 추가, 회귀 테스트 2개 추가(`tests/test_supervisor.py` 총 18개).
6. QA는 기대값을 완화하지 않고 같은 브랜치에서 재검증해 PASS(`0f0b8cb`, blackbox 18개). S0가 다시 실행해 develop에 병합했고(D-008) 통합 상태에서 전체 98개·blackbox 30개 exit 0.

## 6. 아직 되어 있지 않은 것 (중요)
- 이 모듈은 **독립된 기반 코드**다. 실제 수집기(`agents/*`)·대시보드·Edge 연결에는 **아직 연결되지 않았다**. 따라서 "수집 중 자동으로 우회가 동작한다"는 것은 사실이 아니다. 후속 통합 작업이다.
- 실제 sleep·네트워크·로그인 계정·Edge 프로세스는 검증되지 않았고 mock으로만 확인됐다. Windows 외 OS, 다중 프로세스 동시 쓰기는 미검증.

## 7. 서술형 문제와 모범 답안
**문제 1.** `SessionExpired`를 왜 재시도하거나 fallback으로 우회하지 않고 즉시 다시 올리는가?
> 모범 답안: 세션 만료는 몇 번 다시 해도 해결되지 않고, 자동 우회는 보안·약관 위험이 있어 사람이 로그인을 갱신해야 하기 때문이다. 상태를 `SESSION_EXPIRED`로 기록해 원인을 알리고 즉시 중단하는 것이 계약이다.

**문제 2.** 최초 QA PASS를 S0가 받아들이지 않은 이유와, 수정 후 재검증에서 지킨 원칙은?
> 모범 답안: 테스트의 기대값이 스펙과 반대로(중단 후 fallback 실행, 임의 reason 복원) 쓰여 있어 테스트가 통과해도 계약은 위반이었다. 수정 `140fcdf`(fallback 직전 stop 재검사, 고정 reason 검증)를 받은 뒤 QA는 원본 FAIL 이력을 지우지 않고, 기대값을 느슨하게 바꾸지 않은 채 재검증했다.

**문제 3.** 상태 파일을 `os.replace`로 저장하고 source별 전용 파일을 쓰는 이유는? 한계는?
> 모범 답안: 임시 파일에 완성본을 쓴 뒤 교체하므로 중간에 꺼져도 깨진 JSON이 남지 않고, source마다 파일을 분리하면 한 소스의 상태가 다른 소스에 영향을 주지 않는다. 한계는 같은 파일을 여러 인스턴스·프로세스가 동시에 쓸 때의 동기화를 보장하지 않는다는 점(코드에 파일 잠금 없음)이며, 실제 수집기 연결도 아직 없다.
