# GitHub 에이전트 구현 기록

2026-11-10 / v0.4

PyGithub 2.10.0 공식 REST API 래퍼를 선택했다. github3.py도 비교했으며 기존 Python 앱의 검색·릴리스·저장소 타입 통합에 PyGithub를 사용했다. 파일 스냅샷은 codeload ZIP으로 내려받고 실행하지 않는다.

- [PyGithub 소개](https://pygithub.readthedocs.io/en/stable/introduction.html)
- [github3.py](https://github.com/sigmavirus24/github3.py)
- [GitHub 검색 제한](https://docs.github.com/en/rest/search/search)
- [소스 아카이브 범위](https://docs.github.com/en/repositories/working-with-files/using-files/downloading-source-code-archives)
- [요청 제한](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)

검색·직접 지정·재관측, 한국시간 일별 스타 기록, 컴퓨팅/실무 분류 초안과 수동 수정, SKILL.md 확인, 저장소별 파일·문서·릴리스 묶음, 요청 제한 중단·재개를 구현했다. 기존 인기에는 생성일 제한을 적용하지 않는다. 최근 생성과 최근 스타 증가를 구분한다. 최근 증가량은 과거 기록을 추측하지 않고 관측 이후 계산한다.

실제 검증: anthropics/skills 기본 브랜치 ZIP 약 4.4MB와 파일 446개 저장 및 SKILL.md 탐지. topic:ai-agents 스타순 상위 1건 검색과 메타데이터·README·릴리스 조회 성공. 수집 시점의 원문 응답으로 저장한 것이며 순위·스타 수는 변할 수 있다. 광범위 수집은 미실행.

38개 단위 테스트 및 소셜/GitHub HTTP 통합 검사, 두 화면 JavaScript 문법 검사를 통과했다. README에 상한·누락 범위·토큰 설정·실행 방법을 기록했다.
