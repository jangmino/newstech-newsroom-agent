# ADR 0004: Gemini 질문 해석과 mock 자료 조회 분리

- 상태: 승인된 다음 단계의 구현 결정
- 날짜: 2026-09-16

## 결정

기존 두 질문 유형의 해석에만 Gemini 어댑터를 연결합니다. 기본값은 모의 규칙이며,
참가자가 Gemini를 선택하고 서버의 `GEMINI_PLANNER_ENABLED=true`와
`LIVE_API_ENABLED=true`가 모두 설정된 경우에만 모델 호출을 허용합니다.
OpenDART·KOSIS 조회, 계산 입력값, 일반 응답 예시·브리핑은 기존 mock을 유지합니다.
화면은 질문의 외부 전송 여부와 자료가 가상이라는 점을 별도로 표시합니다.

`/plan`에 선택적 `interpretation_method`를 추가하고 성공 응답에 실제 해석 방식과
모델명을 표시합니다. `/execute`와 `/analyze` 요청·응답 계약은 유지합니다.
승인 후에는 Gemini를 다시 호출하지 않습니다. 서버의 자료원 범위 검사와 조건 검증,
명시적 참가자 승인, 사람 검토 필요 상태를 유지합니다.

SDK `generate_content`의 JSON Schema 출력을 사용하며 자동 함수 호출·검색·도구를
주지 않습니다. 질문은 사용자 콘텐츠로, 고정 해석 규칙은 별도 system instruction으로
전달합니다. 모델 출력은 기존 엄격한 계약 검증을 다시 거칩니다. 현재 질문 유형을
벗어난 자유 질의나 복수 자료원 분석으로 범위를 넓히지 않습니다.

기존 `gemini-3.8-flash` 모델 기본값을 유지합니다. 모델명은 서버 설정으로 관리합니다.
요청당 한 번 호출하며 자동 재시도·자동 fallback은 없습니다. 기본 20초 HTTP 타임아웃,
2,048 출력 토큰, 프로세스당 분당 30건·동시 8건 제한을 둡니다. 실패한 시도도 분당 한도에
포함하고 원래 질문·응답·키·공급자 예외를 로그나 공개 오류에 넣지 않습니다.

## 검증과 한계

실제 SDK 직렬화와 응답 처리를 `httpx.MockTransport`로 검사합니다. 자동 테스트에서는
외부 호출·환경 파일·실제 자격증명을 금지합니다. 이 구현 작업에서도 실제 호출을
활성화하지 않습니다. 실제 응답 품질·계정 접근·모델 가용성 검증은 별도 소규모 확인입니다.
JSON 형식 준수만으로 질문 이해나 사실의 정확성을 보증하지 않습니다.

프로세스 내부 호출 제한은 개발 단계의 비용·중복 호출 방어입니다. 여러 인스턴스의
공유 한도·인증·행사 부하 시험·운영 로그는 M3 범위로 남깁니다.

## 근거

- [Google Gen AI Python SDK](https://googleapis.github.io/python-genai/): `generate_content`, JSON Schema, HTTP 옵션.
- [Gemini 구조화 출력](https://ai.google.dev/gemini-api/docs/structured-output): JSON 형식과 애플리케이션 검증.
- [Gemini 모델 목록](https://ai.google.dev/gemini-api/docs/models): 모델명 확인.

문서와 설치된 `google-genai 1.75.0`을 확인했습니다. 실제 API와의 호환성은 별도 실행 검증이 필요합니다.
