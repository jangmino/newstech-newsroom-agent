# Public-data fixtures

공공 API 장애와 회귀 테스트에 사용할 공개 발췌의 안내입니다. 원본 두 파일은
[`apps/api/src/newsroom_agent/snapshot_data/`](../../apps/api/src/newsroom_agent/snapshot_data/)로
옮겼습니다. 백엔드 패키지와 테스트가 같은 파일 한 부를 사용합니다.

규칙:

- 원본 API 키와 키가 포함된 URL은 저장하지 않습니다.
- 개인정보 또는 비공개 자료를 저장하지 않습니다.
- 각 fixture에 자료원, 조회 조건, 조회 시각, 단위와 검증자를 기록합니다.
- 워크숍에서 fallback으로 보여줄 때는 `snapshot` 자료임을 화면에 명시합니다.
- 실제 응답을 추가하기 전에 값과 라이선스·이용조건을 확인합니다.

## 현재 자료

[`opendart-samsung-revenue-2022-2024.json`](../../apps/api/src/newsroom_agent/snapshot_data/opendart-samsung-revenue-2022-2024.json)은 실제 조회한 삼성전자 두 사업연도의 연결
매출액 정규화 발췌입니다. 원문 백만원 값을 원으로 환산해 대조했고 회사·계정·접수번호·
조회 시각·공개 원문 경로·확인자를 기록했습니다. 전체 API 응답이나 공시 본문은 없습니다.
테스트는 선택 행을 재구성해 사용합니다. 앱은 명시적으로 선택·승인한 snapshot 모드에서만 읽습니다.
확인 범위와 이용조건은 [실제 확인 기록](../../docs/OPENDART_SMOKE_TEST.md)을 참고하십시오.

[`kosis-youth-employment-2020-2024.json`](../../apps/api/src/newsroom_agent/snapshot_data/kosis-youth-employment-2020-2024.json)은 실제 KOSIS API의 15~29세 고용률
17개 시도 × 5년 = 85개 셀을 발췌한 자료입니다. 같은 표의 항목·분류·연간 기간·주석을
대조했고, 원래 수치 문자열·단위·최종수정일·보관 시각·공개 요청 조건을 남겼습니다.
자료 행과 메타데이터의 영문 필드를 제외하고 기간은 연간 목록만 추출했습니다.
통계표 화면과의 전수 대조나 사람의 통계 해석 검토를 완료한 자료는 아닙니다.
오프라인 테스트와 명시적으로 승인한 snapshot에서 사용합니다. 오류 사례는 테스트에서
복사·변형하고 실제 응답에 있었던 누락값으로 소개하지 않습니다.
[KOSIS 계약·확인 기록](../../docs/KOSIS_EMPLOYMENT.md)에 이용조건과 검증 한계를 정리했습니다.

[ADR 0011](../../docs/decisions/0011-explicit-public-data-snapshot.md)로 테스트 전용이던 사용
범위를 확대했습니다. 수치·출처·원래 시각은 바꾸지 않았으며 버전·해시로 고정합니다.
live 실패를 자동 대체하지 않고 [저장 자료 계약](../../docs/SNAPSHOT_FALLBACK.md)을 따릅니다.
