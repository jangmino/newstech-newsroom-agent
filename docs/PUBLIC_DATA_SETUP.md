# 공공데이터 활용 준비

## 공통 원칙

- 참가자는 API 키를 만들거나 입력하지 않습니다.
- 모든 키는 백엔드에서만 사용합니다.
- 공식 API의 응답을 공통 내부 형식으로 정규화합니다.
- 원자료, 단위, 조회 조건, 조회 시각과 계산식을 결과에 남깁니다.
- API의 성공 응답과 올바른 해석을 동일시하지 않습니다.
- 자동 테스트와 기본 개발은 fixture 또는 mock transport를 사용합니다.

## OpenDART

준비 사항:

1. [OpenDART 인증키 신청](https://opendart.fss.or.kr/uss/umt/EgovMberInsertView.do)
2. [개발가이드](https://opendart.fss.or.kr/guide/main.do)에서 사용할 API와 오류 코드를 확인
3. 회사명 대신 고유번호를 안정적으로 찾기 위한 기업 고유번호 자료 준비
4. 연결·별도, 연간·분기, 누계·당기 기준을 실습 시나리오에서 고정
5. 정정공시 처리 방식을 정하고 검증된 응답을 fixture로 저장

OpenDART는 일반적으로 요청이 20,000건 이상일 때 사용한도 초과 오류를 안내하지만 계정별 제한이 다를 수 있다고 명시합니다. 행사 전 실제 키의 제한을 확인하고, 회사 정보와 반복 조회 결과를 캐시합니다.

초기 어댑터는 `apps/api/src/newsroom_agent/providers/opendart.py`에 있습니다.

## KOSIS

준비 사항:

1. KOSIS 회원 가입
2. [OpenAPI 통합활용 신청](https://kosis.kr/openapi/index/index.jsp?serviceCD=2)
3. 사용할 통계표, 기관코드, 항목코드, 분류코드와 기간을 미리 확정
4. 통계표의 단위, 주기, 잠정치, 분류 변경과 주석 확인
5. 행사 질문에 필요한 응답을 fixture로 저장

KOSIS 개발가이드는 회원당 인증키 1개가 발급된다고 안내합니다. 2026년 공지에는 HTTPS 전환과 분당 호출 제한이 안내되어 있으므로 정확한 현재 제한을 계정과 공지에서 확인해야 합니다. 키 하나를 참가자 브라우저에 공유하지 말고 서버에서 호출량을 통제합니다.

초기 어댑터는 `apps/api/src/newsroom_agent/providers/kosis.py`에 있습니다.

## Gemini

로컬 개발에서는 `.env`의 `GEMINI_API_KEY`를 사용할 수 있습니다. Google은 2026년 9월부터 표준 키를 거부하는 전환 일정을 안내했으므로 새 프로젝트에서는 제한된 인증키 또는 서비스 계정에 연결된 인증 방식을 사용하고 현재 키 유형을 확인합니다.

Google은 브라우저에 키를 노출하지 말고 백엔드에서 호출하며, 운영 환경에서는 Secret Manager 같은 비밀 저장소를 사용할 것을 권장합니다.

관련 문서:

- [Gemini API 키](https://ai.google.dev/gemini-api/docs/api-key)
- [Gemini API 시작하기](https://ai.google.dev/gemini-api/docs/get-started)
- [Cloud Run의 Secret Manager 사용](https://docs.cloud.google.com/run/docs/configuring/services/secrets)

## 행사 전 검증할 것

- [ ] 실제 두 질문의 모든 코드와 파라미터 고정
- [ ] 단위와 계산 결과를 사람이 별도로 검산
- [ ] 원자료와 브리핑의 값 일치 확인
- [ ] API별 성공·무자료·한도 초과·지연 응답 fixture 준비
- [ ] 키가 로그와 오류 메시지에 노출되지 않는지 확인
- [ ] 30명 동시 실행 부하 시험
- [ ] live → snapshot 전환 리허설
