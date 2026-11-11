# T-005 · 병합 후 진행감독 CLI 학습 문서

S3 Claude Sonnet5.5/low. 허용 `docs/learn/T-005-progress-check.md` 하나만 작성. 코드/테스트/handoff 수정 금지. 사용자 기초 완료・중급 초입 수준에 맞춰 한국어 설명. 제품 테스트 재실행 불필요.

최신 develop의 도구/spec/개발보고/QA/BOARD/DECISIONS를 읽고 무슨 문제를 푸는지, 왜 읽기전용 CLI인지, subprocess shell=False/허용목록, Git ancestry/BOARD 현재표, JSON/exit0・1・2, warning/unknown 의미, 관측한도와 S4 역할을 설명한다. 실제 사용 명령과 출력의 짧은 예, stdlib 선택・장단점・대안 포함. 마지막 서술형3문제/모범답안.

원본0b7b045 PASS미수락→손상ID TypeError RED d0fa3ed→수정be09b34/QA76ab0b5 PASS 이력과 타입검사의 필요성을 설명한다. failed 정정Task를 최종제품실패로 오인하거나 자동중지/재시작하는 도구라고 쓰지 않는다. 출력4MiB는실행후검사이며실시간메모리제한아님. Linux실행은mock만확인. 원격push/승인여부/응답없음/테스트감소는unknown. 테스트수는T005독립브랜치184개와현재통합수치를최신BOARD로구분한다. 추측은확인안됨으로표기.

비밀/사용자DB/미디어/계정파일/실수집/원격push 금지. 지정문서만커밋, diffcheck와미검증을worker_done으로반환. 다른AI연락금지.
