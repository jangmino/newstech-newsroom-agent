# GCP stage

배포 파일은 자원을 자동 생성하지 않습니다. [배포 절차](../docs/STAGE_DEPLOYMENT.md)의
공개 로컬 설정과 검토한 명령을 사용합니다. 사용자 승인에 따라 기관 계정이 준비될 때까지
개인 전용 프로젝트의 임시 stage로 먼저 검증하고 기관 환경을 새로 만들어 교체합니다.
[ADR 0015](../docs/decisions/0015-temporary-personal-stage.md)를 따릅니다.
공식 저장 자료 JSON은 백엔드 패키지 안에 포함되어 기존 Dockerfile의 `COPY apps/api/src`와
패키지 설치로 제공됩니다. 별도 파일 서버·볼륨·DB는 필요하지 않습니다.
사용은 `FALLBACK_SNAPSHOT_ENABLED`와 참가자의 명시적 선택·재승인을 따릅니다.
행사 접근코드 검사를 구현했으며 stage/event에서는 `APP_ENV`를 명시하고
`WORKSHOP_ACCESS_CODE`를 해당 환경의 Secret Manager에서 주입해야 합니다. 미설정·잘못된 값은
실습 API를 차단합니다. `/health`와 입장용 UI는 공개이며 HTTPS가 필요합니다.
첫 개인 stage는 공급자 키 없이 mock·공식 저장 자료로 검증합니다.
2026-09-17 배포와 소규모 확인을 마쳤습니다. [검증 기록](../docs/STAGE_SMOKE_TEST.md)을 참고합니다.
Docker 실행 명령은 원문 URL 쿼리를 남기는 Uvicorn access log를 끕니다.
앱은 요청 ID·고정 경로 분류·상태·시간·실패 코드만 stdout JSON으로 출력합니다.
플랫폼이 수집하는 별도 요청 로그·보관·IAM 정책은 stage에서 검증해야 합니다.
[애플리케이션 로그 계약](../docs/REQUEST_LOGGING.md)을 참고하십시오.
[읽기 전용 운영 상태](../docs/OPERATIONS_STATUS.md)에서 외부 호출 없이 설정·저장 파일·
프로세스별 한도를 확인할 수 있습니다. 실제 연결 검사나 기관 자원/비밀정보 설정은 하지 않습니다.

## 권장 구성

- Cloud Run: 단일 웹 서비스
- Vertex AI 또는 기관 소유 Gemini API 인증키
- Secret Manager: `GEMINI_API_KEY`, `OPENDART_API_KEY`, `KOSIS_API_KEY`, `WORKSHOP_ACCESS_CODE`
- Cloud Logging/Monitoring: 오류율, 지연, 요청량 확인
- Budget alerts: 비용 경고

## 배포 파일

- `Dockerfile`: 정적 UI와 API 단일 이미지, lockfile 고정 설치.
- `cloudbuild.yaml`: 지정한 빌드 서비스 계정으로 AMD64 이미지 빌드·저장.
- `stage.env.yaml`: 비밀 값이 없는 첫 stage 공개 설정, live 모두 꺼짐.
- `stage-config.example.json`: 계정·프로젝트·자원 이름과 Secret 버전의 형식 예시.
- `stage-config.local.json`: 실제 개인/기관 식별자, Git·빌드 업로드 제외.
- `../scripts/stage.py`: 필요한 소스만 패키징하고 명령을 출력, gcloud 자동 실행 없음.

## 기관으로부터 받아야 할 정보

- GCP 프로젝트 ID와 결제 연결 확인
- 배포 대상 리전
- Cloud Run 배포 권한
- 서비스 계정 사용 권한
- Secret Manager 접근 권한
- Vertex AI 사용 여부와 모델 접근 권한
- Gemini·OpenDART·KOSIS의 기관 소유 인증정보
- API 할당량과 상향 승인 담당자

구체적인 역할은 [환경 문서](../docs/ENVIRONMENTS.md)를 따릅니다. 기관 계정을 받으면
동일 스크립트와 설정을 사용하되 기관 IAM·Secret·결제·로그 정책을 새로 적용합니다.
