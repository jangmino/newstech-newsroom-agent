# 강의 원고의 공식 출처

확인일 2026-10-05. 서비스의 제공 기능은 공식 문서, 우리 앱의 지원 범위는 코드와 승인된 ADR을 기준으로 구분했다. 링크는 PPTX 발표자 노트와 배포 자료에 옮긴다. 외부 도구의 요금·모델 버전·조직 계정 지원 여부는 이 자료로 보장하지 않는다.

| ID | 공식 자료 | 강의에 사용하는 범위 |
|---|---|---|
| O1 | [OpenDART 공시정보 API](https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS001) | 공시 검색·기업 정보·원문·고유번호 |
| O2 | [OpenDART 정기보고서 주요정보](https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS002) | 직원·임원·보수 정보, 원문 일부 추출이라는 한계 |
| O3 | [OpenDART 정기보고서 재무정보](https://opendart.fss.or.kr/guide/main.do?apiGrpCd=DS003) | 주요 계정·재무정보·원문 관련 제공 범위 |
| O4 | [OpenDART 공시검색 상세](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001) | 공시검색 조건. 회사 미지정 기간 제약을 모든 API의 공통 제약으로 설명하지 않기 |
| K1 | [KOSIS 통계자료 개발가이드](https://kosis.kr/openapi/devGuide/devGuide_0201List.do) | 자료 조회의 요청 변수·표·분류·항목·시점 |
| K2 | [KOSIS 공유서비스 매뉴얼](https://sso.kosis.kr/openapi/file/openApi_manual_v1.0.pdf) | 목록·자료·메타정보 등 서비스 개요. 한도 숫자는 해당 사용 방식의 최신 안내를 재확인 |
| G1 | [Cloud Run 개요](https://docs.cloud.google.com/run/docs/overview/what-is-cloud-run) | 관리형 애플리케이션 실행 환경. 실제 배포 구조는 저장소 ADR 기준 |
| G2 | [Gemini 구조화 출력](https://ai.google.dev/gemini-api/docs/structured-output) | JSON Schema 기반 응답 형식. 내용 검증과 구분 |
| M1 | [MCP 아키텍처](https://modelcontextprotocol.io/docs/learn/architecture) | 호스트·클라이언트·서버, tools·resources·prompts 연결 규약 |
| A1 | [Antigravity IDE](https://www.antigravity.google/docs/ide/overview/) | 에디터·터미널·브라우저를 사용하는 에이전트 개발 환경 |
| A2 | [Antigravity SDK](https://www.antigravity.google/docs/sdk/overview) | IDE와 구분되는 프로그래밍 가능한 에이전트 런타임 |
| F1 | [Google ADK 공식 문서](https://adk.dev/) | 에이전트·도구·워크플로·실행·평가 기능 |
| F2 | [LangGraph 개요](https://docs.langchain.com/oss/python/langgraph/overview) | 상태를 가진 실행 흐름, 지속 실행·사람 개입 |
| W1 | [Tiago Forte의 Second Brain 소개](https://fortelabs.com/blog/basboverview/) | CODE: 수집·정리·요약·활용 방법론 |
| W2 | [Andrej Karpathy의 LLM Wiki 원안](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) | 원자료와 파생 Wiki·관리 규칙을 나누는 패턴. 댓글의 외부 홍보·주장은 근거로 사용하지 않음 |

## 내부 검증과 디자인 근거

- [공식 저장 자료 구성](../INVESTIGATION_DATA.md): D/E 원문 10건과 접수번호·정정 대조.
- [사례 계약](../INVESTIGATION_WORKSHOP.md), [검증 상태](../INVESTIGATION_VALIDATION.md), [운영 후속 점검](../INVESTIGATION_FOLLOWUPS.md).
- [행사 대기 계약](../EVENT_QUEUE.md), [운영자 가이드](../OPERATOR_GUIDE.md).
- 프로그램 시각·제목: 사용자가 이번 요청에 첨부한 오후 일정 이미지.
- 디자인만 참조: `.inner_docs/NewsTech_뉴스룸_AI_에이전트_실습강의_초안.pptx` 34장, 16:9.

## 발표 문구에 적용한 판단

OpenDART와 KOSIS를 선택한 교육적 이유, 뉴스룸 담당자 역할 분담, 조별 사례 운영, 취재 지식 관리의 검토 절차는 공식 문서가 지정한 정책이 아니라 **현재 앱과 행사 목적에 맞춘 제안**이다. 공급자 기능 전체와 이번 앱에서 검증한 범위를 항상 분리해 설명한다.
