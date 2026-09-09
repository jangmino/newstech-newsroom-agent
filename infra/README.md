# GCP staging 준비

현재 파일은 배포 준비용이며 자동 배포를 실행하지 않습니다.

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
