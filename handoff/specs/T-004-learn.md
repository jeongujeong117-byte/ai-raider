# T-004 · 병합 후 학습 문서

S3 Claude Sonnet5.5/low. 비전공자 사용자(기초 완료・중급 초입)에게 한국어로 설명한다. 허용 파일 `docs/learn/T-004-analysis-schema.md` 하나뿐. 제품/테스트/handoff 수정 금지.

T-004 spec, core/analysis_schema.py, 개발 보고, QA a5d63c2 및 S0 최신 BOARD/DECISIONS를 읽고 JSON 계약/pydantic strict와 Literal bool 함정, READY/HOLD와 순수잡담 차이, 원문 근거 검사/사전 대조 별도 호출, 의존성, 장단점/대안, 파일과 공개 API 예시를 설명한다. 마지막 서술형3문제와 모범답안. 수치는 시점/브랜치를 구분하고 합산 금지. 모르는 것은 확인 안 됨으로 적는다.

T-004 합성12개는 사용자 지식이 아니다. 실제 사용자 기지식5개 확정과 후속 T-006 config/alias 변경이 진행 예정임을 명시한다. 현재 코드로 LLM 성능/자연어 전체 의미/한국어 뜻풀이 생성이 검증됐다고 쓰지 않는다. gold 검증과 실제 분석 모델 검증을 구분한다.

문서 사실 대조/git diff --check 후 허용 파일만 커밋, worker_done으로 커밋/미검증 반환. 문서만 작성하므로 제품 테스트 재실행 불필요. .private/사용자DB/인증보관 파일 접근/실수집/master/push 금지. 다른 AI 연락 금지.
