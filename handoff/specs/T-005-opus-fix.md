# T-005 · 2차 반려 후 3차 수정

S1 claude-opus-5-5/high. 같은 t-005-dev 워크트리에서 기존 be09b34를 보존하고 이어 수정한다. 사용자 모델 정책상 두 번 반려 후 승격이다. 이번에도 FAIL이면 사람 검토 필요로 중단한다. 제품은 S0가 직접 수정하지 않는다.

허용: tools/progress_check.py, tests/test_progress_check.py, handoff/reports/T-005-dev.md만. 기존 읽기 전용/출력/exit/unknown/JSON 타입 검사 계약은 유지한다.

S0 통합67c8961에서 extras 전체284개 중1error/1failure. 원인은 Windows cp949 stdout. subprocess.run([sys.executable,'tools/progress_check.py','--run','run_548a284d59da','--json'],capture_output=True,text=True)를 uv Python3.14로 실행하면 rc1/stdout빈문자열, print(json.dumps(...ensure_ascii=False...))에서 UnicodeEncodeError '\u30fb'가 발생한다. 현재 BOARD의 진행 상태 '・'를 findings evidence.board_status에 넣는 OPEN_BUT_INTEGRATED 경고가 유발했다. QA브랜치184개 통과는 통합231+53개 조합에서 이 출력이 없던 조건이다.

기본stdout뿐 아니라 PYTHONIOENCODING=cp949:strict/UTF8환경 모두에서 JSON을계약대로출력하고 원문을파싱후보존해야 한다. 텍스트모드도현재스트림인코딩으로표현불가문자때문에traceback/rc1로깨지지않게한다. Unicode/emoji/한글/BOARD상태/브랜치이름 포함 독립회귀. 인코딩 강제 또는JSON ASCII이스케이프 등 선택은호환성근거를보고하며터미널/파이프양쪽고려. 단순errors=ignore로정보유실/테스트기대완화/환경변수설정만으로우회금지. 부모테스트의text=True decoding도고려하고 실제CLI subprocess경계로증명하라.

별도 현재통합조건을읽기전용으로확인하되 develop을S1이병합하지말고 필요한임시Git/BOARDfixture로재현. 기존원본TypeError회귀도유지. 기본/processing+mcp 전체회귀와실제현재repo Run을시점별수치로보고. 이전T005독립브랜치184개와develop284개를혼동금지. 허용파일커밋후worker_done, QA전수락없음.

비밀/DB/실수집/계정파일/master병합/push금지. 다른AI연락금지, 설계변경/범위확대는ask.
