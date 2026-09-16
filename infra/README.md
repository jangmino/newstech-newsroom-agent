# GCP staging 준비

현재 파일은 배포 준비용이며 자동 배포를 실행하지 않습니다.
공식 저장 자료 JSON은 백엔드 패키지 안에 포함되어 기존 Dockerfile의 `COPY apps/api/src`와
패키지 설치로 제공됩니다. 별도 파일 서버·볼륨·DB는 필요하지 않습니다.
사용은 `FALLBACK_SNAPSHOT_ENABLED`와 참가자의 명시적 선택·재승인을 따릅니다.
행사 접근코드 검사를 구현했으며 stage/event에서는 `APP_ENV`를 명시하고
`WORKSHOP_ACCESS_CODE`를 기관 Secret Manager에서 주입해야 합니다. 미설정·잘못된 값은
실습 API를 차단합니다. `/health`와 입장용 UI는 공개이며 HTTPS가 필요합니다.
실제 Secret Manager 구성·Cloud Run 배포는 아직 실행하지 않았습니다.
Docker 실행 명령은 원문 URL 쿼리를 남기는 Uvicorn access log를 끕니다.
앱은 요청 ID·고정 경로 분류·상태·시간·실패 코드만 stdout JSON으로 출력합니다.
플랫폼이 수집하는 별도 요청 로그·보관·IAM 정책은 stage에서 검증해야 합니다.
[애플리케이션 로그 계약](../docs/REQUEST_LOGGING.md)을 참고하십시오.

## 권장 구성

- Cloud Run: 단일 웹 서비스
- Vertex AI 또는 기관 소유 Gemini API 인증키
- Secret Manager: `GEMINI_API_KEY`, `OPENDART_API_KEY`, `KOSIS_API_KEY`, `WORKSHOP_ACCESS_CODE`
- Cloud Logging/Monitoring: 오류율, 지연, 요청량 확인
- Budget alerts: 비용 경고

## 기관으로부터 받아야 할 정보

- GCP 프로젝트 ID와 결제 연결 확인
- 배포 대상 리전
- Cloud Run 배포 권한
- 서비스 계정 사용 권한
- Secret Manager 접근 권한
- Vertex AI 사용 여부와 모델 접근 권한
- Gemini·OpenDART·KOSIS의 기관 소유 인증정보
- API 할당량과 상향 승인 담당자

구체적인 역할은 `docs/ENVIRONMENTS.md`를 따릅니다. 실제 배포 명령은 프로젝트와 IAM이 확정된 뒤 작성합니다.
