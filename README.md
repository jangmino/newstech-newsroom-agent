# NewsTech Newsroom Agent

뉴스룸 종사자가 자연어로 질문하면 OpenDART 또는 KOSIS의 공식 데이터를 조회하고, 조회 조건·출처·단위·계산 근거가 포함된 검토용 브리핑을 만드는 워크숍 애플리케이션입니다.

현재 저장소는 **개발 착수용 하네스와 모의 실행 MVP**입니다. 실제 Gemini·OpenDART·KOSIS 호출은 기본적으로 꺼져 있습니다.

## 구조

```text
apps/web      React + Vite 프론트엔드
apps/api      FastAPI 백엔드와 단일 에이전트 오케스트레이터
docs          제품 범위, 아키텍처, 환경 전환, 공공데이터 준비, Codex 하네스
fixtures      API 장애 시 사용할 검증된 저장 자료
infra         Cloud Run 단일 컨테이너 배포 준비
```

개발 중에는 프론트엔드와 백엔드를 별도로 실행합니다. 스테이징에서는 프론트엔드를 빌드해 FastAPI가 함께 제공하므로 Cloud Run 서비스 하나로 운영할 수 있습니다.

## 처음 시작하기

필요 도구:

- Node.js 20
- pnpm 9
- Python 3.12
- uv
- Docker Desktop(선택)
- Google Cloud CLI(스테이징부터)

```bash
cp .env.example .env
pnpm install
cd apps/api && uv sync --dev && cd ../..
```

터미널 두 개에서 실행합니다.

```bash
make dev-api
make dev-web
```

- 프론트엔드: http://localhost:5173
- 백엔드 상태 확인: http://localhost:8000/health

또는 VS Code에서 `Terminal > Run Task > Dev: web + api`를 실행할 수 있습니다.

## 검증

```bash
make check
```

## 환경 전환

| 단계 | 모델·인프라 소유자 | 데이터 방식 | 목적 |
|---|---|---|---|
| local | 개발자 개인 | mock 우선, 개인 키로 제한적 실험 | 기능 개발 |
| stage | 건국대학교·주최 측 | 기관 키 + 저장 자료 fallback | 부하 시험·리허설 |
| event | 건국대학교·주최 측 | 기관 키 + 모니터링 + fallback | 워크숍 운영 |

개인 키를 Git에 커밋하거나 브라우저 코드에 넣지 않습니다. 자세한 내용은 [환경 전환 문서](docs/ENVIRONMENTS.md)를 확인하십시오.

## Codex로 개발하기

VS Code에서 이 저장소 루트를 열면 Codex가 루트의 `AGENTS.md`를 읽습니다. 새 작업을 시작하기 전에 [Codex 개발 하네스](docs/CODEX_HARNESS.md)의 작업 절차와 프롬프트 예시를 확인하십시오.

## 현재 범위

- 포함: 단일 에이전트, OpenDART/KOSIS 어댑터, 결정론적 계산, 근거 패널, 모의 응답, Cloud Run 준비
- 제외: 멀티에이전트, 기사 자동 발행, CMS 연동, 모든 공공데이터 자유 질의, 행사 이후 상시 운영

제품 범위는 [제품 개요](docs/PRODUCT_BRIEF.md)에 정리되어 있습니다.
