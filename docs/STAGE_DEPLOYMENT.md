# 임시 개인 stage 배포와 기관 전환

[ADR 0015](decisions/0015-temporary-personal-stage.md)에 따라 기관 계정이 준비될 때까지
개인 GCP의 전용 프로젝트에서 배포를 검증합니다. 후속 [ADR 0016](decisions/0016-personal-stage-live-validation.md)으로
개인 환경 live 시험도 승인됐으며 기관 계정 요청·환경 전환은 마지막 인계 단계로 미룹니다.
이 문서는 계정·프로젝트 ID·결제 ID·접근코드 값을 보관하지 않습니다.

## 첫 stage의 범위

| 항목 | 구성 |
|---|---|
| 배포 | React 정적 파일 + FastAPI 단일 Cloud Run 컨테이너 |
| 리전 | `asia-northeast3` (서울) |
| 리소스 | 1 vCPU, 512 MiB, 요청 기반 과금, CPU boost 끔 |
| 실행 | 최소 0, 리비전 최대 1 인스턴스, 컨테이너당 동시 8요청, 단일 Uvicorn 프로세스 |
| 시간 제한 | 요청 60초, `/health` 시작 검사 |
| 자료 | mock·공식 저장 자료; Gemini/OpenDART/KOSIS live 모두 꺼짐 |
| 입장 | `APP_ENV=stage`, Secret Manager의 공유 접근코드 필수 |
| 접근 | 먼저 IAM 비공개 배포; 사용자가 공개 URL을 선택하면 Cloud Run invoker 공개 |
| 보관 | DB 없음; 검토·질문은 탭 메모리, 원자료 캐시는 서버 프로세스 메모리 |

Cloud Run의 최대 인스턴스 설정은 행사 전체 호출량·절대 비용 상한이 아닙니다. 배포 전환·
재시작 등에서 프로세스가 바뀔 수 있고 기존 한도/캐시도 초기화됩니다.
첫 배포는 30명 동시 사용을 검증한 크기가 아닙니다.
[인스턴스 설정](https://docs.cloud.google.com/run/docs/configuring/max-instances),
[요청 기반 과금](https://cloud.google.com/run/pricing)을 따릅니다.

## 공개 설정과 비밀정보

- `infra/stage-config.example.json`을 Git에서 제외한 `infra/stage-config.local.json`으로
  복사하고 계정·프로젝트·리전·자원 이름과 Secret 버전 번호만 넣습니다. 키나 코드 값은
  이 파일에도 넣지 않습니다. 모든 명령에서 `--account`, `--project`, `--region`을 명시합니다.
- `infra/stage.env.yaml`은 공개 실행 설정입니다. `.env`를 업로드하거나 이 파일에 합치지 않습니다.
- 런타임 `newsroom-runtime`과 빌드 `newsroom-build` 서비스 계정은 분리합니다.
  다운로드 가능한 서비스 계정 키 JSON을 생성하지 않습니다.
- 접근코드는 충분히 긴 무작위 값으로 새로 만들고 Secret Manager에 입력합니다.
  값은 명령 인자·로그·문서·Git에 넣지 않고 stdin 또는 권한 600의 Git 제외 파일로 전달합니다.
  컨테이너에는 숫자로 고정한 Secret 버전을 환경변수로 주입합니다.
- 첫 배포에 Gemini·OpenDART·KOSIS 키를 복사하지 않습니다. live 검증을 진행할 때 별도
  Secret과 실행 설정으로 연결합니다. 기관 환경에는 기관 키를 새로 주입합니다.

환경변수로 주입하는 Secret은 인스턴스 시작 시 읽으므로 버전을 고정합니다.
[Cloud Run Secret 설정](https://docs.cloud.google.com/run/docs/configuring/services/secrets)을 따릅니다.

## 준비와 권한

1. 사용할 Google 계정으로 CLI 로그인합니다. 기존 계정 설정을 유지하려면
   `gcloud auth login <ACCOUNT> --no-activate`를 사용하고 이후 계정을 명시합니다.
2. 기존 업무 프로젝트와 분리된 프로젝트를 만듭니다. 사용할 결제 계정·비용 알림 금액·
   공개 범위를 확인한 뒤 연결합니다. 이 문서의 예시는 자동 실행되지 않습니다.
3. Cloud Run, Cloud Build, Artifact Registry, Secret Manager, IAM, Logging, Budget API를
   활성화합니다. Gemini/Vertex·공공자료 API의 live 사용은 첫 배포 범위가 아닙니다.
4. 리전별 Docker 저장소, 비공개 소스 업로드 버킷, 두 서비스 계정, 접근코드 Secret을 만듭니다.
5. 아래 권한을 해당 자원에만 부여합니다. 실제 배포자는 프로젝트 생성·결제 연결·API 활성화·
   자원 생성·IAM 관리·빌드 제출·서비스 계정 사용 권한이 필요합니다. 기관에서는 담당자가
   자원을 만들고 개발자에게 필요한 역할만 위임하는 방식으로 조정합니다.

| 주체 | 권한 범위 |
|---|---|
| 런타임 서비스 계정 | 해당 접근코드 Secret의 `roles/secretmanager.secretAccessor` |
| 빌드 서비스 계정 | 해당 이미지 저장소의 `roles/artifactregistry.writer` |
| 빌드 서비스 계정 | 소스 버킷의 `roles/storage.objectViewer`, 프로젝트의 `roles/logging.logWriter` |
| 배포자 | 빌드 제출, Cloud Run 배포, 위 서비스 계정의 `iam.serviceAccounts.actAs` |

Cloud Build는 기본 계정 대신 지정한 빌드 계정을 사용하고 로그는 `CLOUD_LOGGING_ONLY`로
보냅니다. [사용자 지정 빌드 계정](https://docs.cloud.google.com/build/docs/securing-builds/configure-user-specified-service-accounts)을 참고합니다.

## 빌드와 배포 명령 만들기

저장소 루트에서 실행합니다. 패키징·계획 생성은 클라우드 자원을 변경하지 않습니다.
패키징 도구는 기존 출력 디렉터리를 덮어쓰지 않으므로 빌드마다 새 경로를 사용합니다.

```bash
make check
python3 scripts/stage.py package --output .cache/stage-source
python3 scripts/stage.py plan --config infra/stage-config.local.json --tag stage-<COMMIT>
```

`package`는 명시한 빌드 파일·웹 소스·Python 소스·두 공식 저장 JSON만 복사하며 `.env`를
읽지 않습니다. 소스 symlink를 거절합니다. `.gcloudignore`와 `.dockerignore`도 허용 목록을
사용하여 Git 이력·개인 설정·키·캐시·의존성 디렉터리를 제외합니다.
업로드 전 `gcloud meta list-files-for-upload .cache/stage-source`로 목록을 확인합니다.
루트 전체 업로드 대신 검토한 패키지 디렉터리를 Cloud Build에 제출합니다.
[gcloudignore](https://docs.cloud.google.com/sdk/gcloud/reference/topic/gcloudignore)를 따릅니다.

계획의 `build` 명령은 지정 프로젝트·계정·리전·빌드 서비스 계정으로 이미지를 만들고
Artifact Registry에 올립니다. `infra/cloudbuild.yaml`은 AMD64 이미지를 만들며 Secret을
빌드에 전달하지 않습니다. Cloud Build 성공 뒤 결과 이미지의 digest를 확인합니다.

```bash
python3 scripts/stage.py plan --config infra/stage-config.local.json \
  --tag stage-<COMMIT> --image-digest sha256:<64_HEX_DIGEST>
```

이제 출력되는 `deploy_private` 명령은 태그가 아닌 digest를 사용합니다. 실행 설정과
접근코드 Secret 버전을 검토하고 배포합니다. 공개 URL 선택 시 별도로 해당 서비스에만
`allUsers`의 `roles/run.invoker`를 부여합니다. API는 계속 앱의 접근코드를 검사합니다.
비공개 유지 시 Google IAM을 통과하는 `gcloud run services proxy`로 확인합니다.

## 배포 후 확인과 비용

아래는 첫 mock 배포의 확인 기준입니다. 현재 live stage의 설정·Secret 참조·후보 배포·
트래픽 전환·복귀·검증은 [실제 연결 확인](STAGE_LIVE_TEST.md)을 따릅니다.

- 공개 UI·정적 파일·`/health`가 열리고 `/api/v1/access`가 `{required:true, available:true}`인지 확인.
- 코드 없는 분석·실행·운영 상태·OpenAPI 요청이 401인지 확인.
- 입장 뒤 mock과 두 공식 저장 자료에서 계획 → 편집 → 승인 → 결과 → 사람 검토 확인.
- 승인 없는 실행은 422이며 live 선택은 비활성 오류여야 함.
- 상태 화면에 실제 공급자 비활성, 저장 자료 사용 가능, 프로세스별 한도 표시 확인.
- 응답 요청 ID와 앱 JSON 로그를 대조. 토큰·접근코드·전체 헤더/질문은 출력하지 않음.
- Cloud Run 플랫폼 로그는 앱 로그와 별개이며 URL·IP·사용자 에이전트 등이 포함될 수 있음.
  URL에 비밀정보를 넣지 않고 프로젝트 로그 접근 권한과 보관 기간을 별도로 확인.

비용 알림은 이 프로젝트로 범위를 한정하고 50%·90%·100% 임계값으로 설정합니다.
Cloud Run 외 빌드 시간·이미지 보관·Secret·로그/네트워크 요금도 확인합니다.
예산 알림은 지출을 자동 차단하지 않습니다. 사용하지 않을 때 최소 인스턴스 0을 유지하고
검증 종료 후 자원 목록을 확인하여 정리합니다.
[예산 알림의 한계](https://docs.cloud.google.com/billing/docs/how-to/budgets)를 참고합니다.

## 기관 계정을 받았을 때

1. 기관 프로젝트·결제·리전·IAM·로그 정책·비용 담당자를 확정합니다.
2. 동일 코드 커밋과 배포 설정으로 기관 프로젝트에 자원을 새로 만듭니다.
3. 기관 소유 공급자 키와 **새 접근코드**를 기관 Secret Manager에 등록합니다.
   개인 Secret 값·서비스 계정 키를 이전하지 않습니다.
4. 기관 이미지 저장소의 digest와 Secret 버전을 고정하여 새 서비스로 배포합니다.
5. 승인·자료 모드·검토·오류·snapshot·부하 흐름을 검증한 뒤 참가자 URL을 교체합니다.
6. 개인 환경의 서비스·이미지·소스 버킷·Secret·예산 알림·IAM을 목록화하여 정리합니다.
   삭제는 사용 중인 자원과 롤백 필요성을 확인한 뒤 수행합니다.

롤백은 같은 프로젝트의 검증된 이전 리비전으로 트래픽을 되돌리는 방식으로 수행합니다.
이전 리비전이 참조하는 Secret 버전을 먼저 폐기하지 않습니다. 메모리 캐시와 참가자 검토
상태는 이전·롤백 대상이 아니며 새로 확인합니다.

행사 시작·장애 대응·종료 후 공개 접근 차단은 [운영자 가이드](OPERATOR_GUIDE.md)를 따릅니다.
Invoker IAM 검사 활성화와 공개 invoker 바인딩 제거를 함께 확인하고, 인증 없는 새 요청으로
차단 결과를 검증합니다. [행사 점검표](EVENT_CHECKLIST.md)에 실행 결과를 남깁니다.
