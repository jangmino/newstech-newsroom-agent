# 환경과 책임 전환

## Local

목적은 빠른 개발과 소규모 검증입니다.

- 소유자: 개발자 개인
- 기본 모드: `PUBLIC_DATA_MODE=mock`, `LIVE_API_ENABLED=false`
- 비밀정보: 로컬 `.env`
- Gemini: 개인 프로젝트의 인증키로 제한적 시험 가능
- OpenDART/KOSIS: 개인 키로 필요한 최소 호출만 수행
- 과금 경고와 사용량 제한을 개인 프로젝트에서 설정

## Stage

목적은 실제 행사와 같은 조건의 리허설과 부하 시험입니다.

- 소유자: 건국대학교 또는 주최 측
- 배포: 기관 GCP 프로젝트의 Cloud Run
- Gemini: 기관 프로젝트의 Gemini API 인증키 또는 Vertex AI
- 공공데이터: 기관·주최 측 담당자 명의 OpenDART/KOSIS 키
- 비밀정보: Secret Manager
- 필수 확인: 결제, 모델 접근, API 활성화, 할당량, 로그 열람, 장애 담당자
- 개인 키를 stage에 복사하지 않음

## Event

목적은 약 30명의 참가자가 동시에 사용하는 워크숍 운영입니다.

- stage에서 검증된 동일 이미지를 사용합니다.
- 행사 직전 기능 추가를 하지 않습니다.
- 요청 속도 제한, 캐시, 모니터링과 snapshot fallback을 켭니다.
- 외부 API 장애 시 진행자가 즉시 fallback으로 전환할 수 있어야 합니다.
- 행사 종료 후 서비스 공개 여부, 로그 보존, 키 폐기 일정을 주최 측이 결정합니다.

## 건국대학교·주최 측 제공 체크리스트

- [ ] 기관 GCP 프로젝트 ID
- [ ] 결제 계정 연결과 예산 경고
- [ ] Cloud Run·Cloud Build·Artifact Registry 사용 승인
- [ ] Vertex AI 또는 Gemini API 사용 방식 확정
- [ ] 개발자에게 필요한 최소 IAM 권한과 만료 시점
- [ ] 런타임 서비스 계정
- [ ] Secret Manager secret 생성 및 접근 권한
- [ ] 기관 소유 OpenDART 인증키
- [ ] 기관 소유 KOSIS 인증키
- [ ] 각 API 할당량 확인 및 상향 담당자
- [ ] 행사 당일 운영·장애 의사결정 담당자
- [ ] 행사 후 서비스·로그·키 처리 방침

## 초기 권한 논의 기준

권한은 기관 정책에 맞춰 최소화합니다. Cloud Run 배포, 빌드, 서비스 계정 사용, 로그 열람, Secret Manager 접근이 필요할 수 있으나 프로젝트 전체 Owner 권한을 기본 요구하지 않습니다. 실제 IAM 역할은 배포 방식이 확정된 뒤 기관 관리자와 검토합니다.
