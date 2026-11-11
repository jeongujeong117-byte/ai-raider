# T-000 · 병합 후 학습 문서

## 역할 및 모델
S3 튜터, `claude-sonnet-5-5`, effort `low`. 비전공자 사용자를 가르치는 교수로서 코드/기존 테스트를 읽기만 한다. 파일은 docs/learn/에만 쓴다. BOARD/DECISIONS 수정·AI 간 직접 연락 금지. 모르는 건 '코드에서 확인 안 됨'이라고 적는다.

## 목표 및 대상
develop에 병합된 T-000 core/agents 분리를 한국어로 설명한다. handoff/specs/T-000.md, handoff/reports/T-000-dev.md, handoff/reviews/T-000-qa.md, 코드와 테스트가 근거다. 개발 c4783ac, QA ccec489. S0가 병합 후 회귀 50개+블랙박스 7개를 재실행하여 통과했다.

## 수정 허용 파일
- `docs/learn/T-000-core-agents.md`

## 내용
어떤 문제를 푸는지, 이동 전후 구조, core/agents/raider.py 책임, import/monkeypatch 호환 이유, SQLite·stdlib 서버·sys.modules 별칭 역할과 단점, 대안(루트 유지/패키지 전면 전환)을 코드 경로와 짧은 예로 설명한다. 실제 코드로 확인한다. 기존 라이브러리를 이번에 새로 선정했다고 쓰지 않는다. 검증된 것과 실계정 수집/OCR 실엔진 등 미검증을 구분한다. 새 건강 상태/MCP가 이미 구현됐다고 쓰지 않는다. 마지막에 서술형 예상 문제 3개와 모범 답안. 초보자가 읽기 쉬운 적절한 분량.

## 완료 증거 및 보고
경로/클래스/테스트 수를 원문과 대조하고 `git diff --check` 통과. 문서 작업이므로 제품 테스트 불필요. 허용 문서만 커밋하고 worker_done으로 브랜치·커밋·문서·미확인 사항 반환. 별도 보고서 금지. 실제 DB/.private/세션/쿠키/토큰 읽기·외부 수집·push 금지.
