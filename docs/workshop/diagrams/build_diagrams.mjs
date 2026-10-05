// Dependency-free SVG assets for the workshop slide planning pack.
// Logical editable counterparts are the adjacent .mmd files.
import { writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const out=dirname(fileURLToPath(import.meta.url));
const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
const colors={ink:'#191919',gray:'#626262',blue:'#235CBB',line:'#B9BEC5',light:'#F4F4F4',green:'#E5F0EB',pale:'#EAF0FB'};
let items=[];
function text(x,y,lines,{size=25,bold=false,fill=colors.ink,anchor='start',gap=38}={}) {
  items.push(`<text x="${x}" y="${y}" font-size="${size}" font-weight="${bold?700:400}" fill="${fill}" text-anchor="${anchor}">${[].concat(lines).map((l,i)=>`<tspan x="${x}" dy="${i?gap:0}">${esc(l)}</tspan>`).join('')}</text>`);
}
function box(x,y,w,h,title,lines=[],fill=colors.light){
  items.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${fill}" stroke="${colors.line}" stroke-width="1.5"/>`);
  text(x+24,y+43,title,{size:27,bold:true});
  text(x+24,y+87,lines,{size:24,gap:35});
}
function arrow(points,{dash=false,blue=false}={}){items.push(`<polyline points="${points}" fill="none" stroke="${blue?colors.blue:colors.gray}" stroke-width="2.5" ${dash?'stroke-dasharray="7 6"':''} marker-end="url(#arrow)"/>`);}
function base(title,sub){items=[];text(60,74,title,{size:40,bold:true});text(60,124,sub,{size:23,fill:colors.gray});}
function save(name,desc){
 const svg=`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900" width="1600" height="900" role="img" aria-labelledby="title desc"><title id="title">${esc(desc)}</title><desc id="desc">${esc(desc)}. 자세한 논리 구조는 같은 이름의 Mermaid 파일에 있습니다.</desc><defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="${colors.gray}"/></marker></defs><rect width="1600" height="900" fill="white"/><g font-family="Apple SD Gothic Neo, Noto Sans KR, sans-serif">${items.join('')}</g></svg>`;
 writeFileSync(join(out,name+'.svg'),svg+'\n');
}

base('화면과 서버의 역할을 나누고 한 서비스로 배포합니다','현재 앱 구조 · 외부 API와 비밀값은 서버에서만 사용');
items.push(`<rect x="435" y="180" width="680" height="595" fill="white" stroke="${colors.blue}" stroke-width="2"/>`);
text(460,220,'Cloud Run · FastAPI 한 컨테이너',{size:27,bold:true});
box(60,305,310,200,'참가자 브라우저',['React · TypeScript','질문 · 승인 · 사람 검토'],colors.green);
box(470,255,610,100,'웹 정적 파일 + 실습 API',[],colors.light);
box(470,390,610,145,'EventService · 단일 조정 흐름',['조건·승인 검사 → 어댑터 호출','공식 API / 패키지 저장 원자료 / 캐시'],colors.light);
box(470,580,610,150,'계산과 출력 검증',['Python: 단위 · 증감 · 순위','Gemini 출력: 근거 ID · 숫자 슬롯'],colors.light);
box(1210,195,330,145,'Gemini API',['질문 계획 · 근거 설명','일반 응답은 별도 호출'],colors.pale);
box(1210,400,330,145,'외부 공식 API',['OpenDART · KOSIS','서버만 실제 조회'],colors.light);
box(1210,610,330,120,'Secret Manager',['서버가 비밀값 사용'],colors.green);
arrow('370,350 435,350');text(373,327,'HTTPS',{size:18});
arrow('435,485 370,485');
arrow('775,355 775,390');arrow('775,535 775,580');
arrow('1080,420 1158,420 1158,265 1210,265');
arrow('1210,310 1180,310 1180,650 1080,650');
arrow('1080,475 1210,475');arrow('1210,505 1080,505');
arrow('1210,670 1135,670 1135,755 1115,755',{dash:true});
text(60,823,'로컬: Vite와 FastAPI 두 프로세스   |   배포: 정적 웹 파일과 API를 함께 제공',{size:24});
text(60,863,'브라우저에서 React 실행 · Cloud Build → Artifact Registry → Cloud Run · 승인 후에만 수치 조회',{size:22,fill:colors.gray});
save('01_architecture','프론트엔드와 백엔드 및 공급자의 역할 구성도');

base('화면에서 읽는 순서와 서버가 실행하는 순서를 구분합니다','2부의 새 조사 사례 · 계획 승인 뒤에만 조회·계산·브리핑 실행');
box(60,195,400,145,'01 취재 질문하기',['질문과 필요한 확인 답변'],colors.green);
box(600,195,400,145,'02 조사 계획 검토',['조건 · 자료 방식 · 사람 승인'],colors.green);
box(1140,195,400,145,'브리핑 작성 중',['자료 조회 → 계산 → Gemini'],colors.pale);
arrow('460,265 600,265');text(478,242,'계획 제안',{size:21});
arrow('1000,265 1140,265');text(1018,242,'승인 후',{size:21,fill:colors.blue});
arrow('1340,340 1340,420 220,420 220,490');
box(60,490,320,165,'03 응답 비교',['근거 브리핑 먼저 표시','일반 응답은 버튼 호출'],colors.pale);
box(445,490,325,165,'발견을 뒷받침하는 비교',['비교표 · 순위 · 비중','표 열기는 새 호출 아님']);
box(835,490,320,165,'04 자료와 계산 근거',['원문 · 단위 · 식 · 시각','실행 기록과 상세 보기']);
box(1220,490,320,165,'05 사람 검토와 수정',['사실 · 해석 · 후속 질문','수정 초안과 기록 저장'],colors.green);
arrow('380,570 445,570');arrow('770,570 835,570');arrow('1155,570 1220,570');
text(60,730,'일반 응답 비교는 별도 Gemini 호출입니다. 근거·표·검토 폼을 펼치는 일은 추가 호출이 아닙니다.',{size:26});
text(60,789,'계획이 모호하면 질답으로 돌아갑니다. 질문·조건 변경과 재조회는 결과·검토를 초기화합니다.',{size:24,fill:colors.gray});
text(60,842,'검토 기록 내려받기 → 원문 대조와 후속 취재에 활용 · 자동 기사 작성·발행 없음',{size:24,fill:colors.gray});
save('02_pipeline','참가자 화면 순서와 승인 및 별도 일반 응답 호출');

base('두 응답은 같은 조사 범위에서 서로 다른 입력을 받습니다','같은 Gemini의 역할·입력·출력 제약 비교 · 챗봇 제품 전체의 성능 평가가 아님');
box(400,180,800,100,'공통 사용자 입력: question + approved_conditions',[],colors.green);
arrow('580,280 580,320 390,320 390,355');arrow('1020,280 1020,320 1210,320 1210,355');
box(60,355,660,285,'일반 응답 · 별도 버튼 호출',[
 '시스템 지시: 불확실한 수치·출처 생성 금지',
 '사용자 메시지: 질문 + 승인 조건',
 '공식 조회값·계산 결과·웹 검색 도구 없음',
 '출력: text'
],colors.light);
box(880,355,660,285,'근거 기반 브리핑',[
 '시스템 지시: 제공 근거만 · 계산 금지 · 인용',
 '사용자 메시지: 공통 입력 + facts + caveats',
 '자료 방식·조사 방법도 전달',
 '출력: 요약 · 발견 · 한계 · 후속 취재'
],colors.pale);
arrow('1210,640 1210,690');
box(880,690,660,100,'코드 검사 → 근거 ID · 숫자 슬롯 → 화면 표시',[],colors.light);
text(60,724,'approved_conditions는 앱이 정한 필드명입니다.',{size:25});
text(60,772,'자료원 이름이 있다고 API가 호출되지는 않습니다.',{size:24,fill:colors.gray});
text(60,850,'근거 브리핑에만 검증된 사실 입력과 인용 제약이 추가됩니다. 일반 응답도 맞거나 모른다고 답할 수 있습니다.',{size:22,fill:colors.gray});
save('03_model_inputs','일반 응답과 근거 기반 브리핑의 입력 및 시스템 지시 비교');

base('D와 E는 원문 대조를 준비하고 브리핑을 새로 생성합니다','2026-10-05 검증본 · 실시간 재조회나 사전 생성 답안 재생과 구분');
text(60,203,'사전 준비',{size:28,bold:true});
box(60,235,420,195,'공식 자료 수집',['D: 대표이사·직원·보수','E: 두 회사 × 5개년 보고서','OpenDART API + 원문']);
box(590,235,420,195,'표 추출과 의미 대조',['정정 후 표 · 단위 · 정의','같은 보고서 전기 비교액','E 사업 매출 35개 행']);
box(1120,235,420,195,'공식 저장 원자료',['접수번호 · 원문 위치','확보 시각 · 버전 · 검증','회사별 사업 분류 보존']);
arrow('480,330 590,330');arrow('1010,330 1120,330');
text(60,511,'참가자 실습',{size:28,bold:true});
box(60,550,320,150,'조사 계획 승인',['저장 자료 사용도 확인'],colors.green);
box(445,550,325,150,'코드 계산',['비중 · 증가액 · 배율','동일 조건은 재사용 가능']);
box(835,550,320,150,'새 Gemini 브리핑',['계산 근거와 한계 설명'],colors.pale);
box(1220,550,320,150,'사람의 검토',['원문 대조 · 수정','후속 취재 판단'],colors.green);
arrow('380,630 445,630');arrow('770,630 835,630');arrow('1155,630 1220,630');
arrow('1330,430 1330,470 607,470 607,550');
text(60,785,'핵심은 비교 기준을 맞추는 일입니다. 반복 API 호출과 대기를 줄이는 운영 효과도 있습니다.',{size:26});
text(60,842,'저장 원자료만으로 Gemini 장애를 해결하지는 못합니다. 공식 자료의 해석에는 사람 검토가 남습니다.',{size:23,fill:colors.gray});
save('04_prepared_sources','D와 E의 사전 자료 준비와 승인 후 브리핑 생성');

base('취재 지식은 원자료와 해석을 연결해 쌓을 수 있습니다','향후 뉴스룸 확장 제안 · 현재 웹앱에 Wiki나 조직 저장 기능을 구현했다는 뜻은 아님');
box(60,230,430,265,'원자료 보존',['공시 · 통계 · 허용된 취재 기록','원문 위치 · 기준 시점 · 버전','모델이 원본을 덮어쓰지 않음']);
box(585,230,430,265,'출처를 연결한 파생 지식',['기업 · 주제 · 사건별 노트','요약 · 상충하는 주장 · 변경','원자료로 돌아가는 연결']);
box(1110,230,430,265,'사람 검토와 활용',['브리핑 · 후속 취재 질문','검토자 · 상태 · 판단 이유','데스크 인계와 재사용'],colors.green);
arrow('490,355 585,355');arrow('1015,355 1110,355');
arrow('1330,495 1330,565 275,565 275,495');text(570,549,'미해결 질문 → 추가 자료 확보',{size:24});
text(60,650,'Second Brain: 수집·정리·요약·활용의 방법론',{size:27,bold:true});
text(60,698,'LLM Wiki: 원자료를 바탕으로 연결된 문서를 유지하는 패턴',{size:27,bold:true});
text(60,772,'뉴스룸의 추가 설계: 접근 권한 · 출처 추적 · 정정 반영 · 검토 책임 · 갱신 이력',{size:25});
text(60,840,'모델의 요약은 새 독립 근거가 아닙니다. 원자료와 검토 상태를 함께 유지합니다.',{size:24,fill:colors.gray});
save('05_knowledge','원자료와 파생 지식 및 사람 검토를 연결하는 뉴스룸 지식 관리 제안');

const names=['01_architecture','02_pipeline','03_model_inputs','04_prepared_sources','05_knowledge'];
writeFileSync(join(out,'preview.html'),`<!doctype html><html lang="ko"><meta charset="utf-8"><title>NewsTech 슬라이드 도해 미리보기</title><style>body{font-family:system-ui,sans-serif;max-width:1600px;margin:30px auto;background:#eee;color:#191919}h1,p{margin:20px}figure{margin:30px 0;background:white}img{display:block;width:100%;height:auto}figcaption{padding:12px 20px}a{color:#235cbb}</style><h1>슬라이드 도해 미리보기</h1><p>원고 제작용 도해 5개입니다. SVG는 삽입용, Mermaid는 논리 구조 편집용입니다.</p>${names.map(n=>`<figure><img src="${n}.svg" alt="${n}"><figcaption><a href="${n}.svg">SVG</a> · <a href="${n}.mmd">Mermaid 원본</a></figcaption></figure>`).join('')}</html>\n`);
console.log('Generated five SVG diagrams and preview.html');
