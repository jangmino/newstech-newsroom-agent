import { useState } from 'react';
import { getJson, postJson, type ApiGet, type ApiPost } from './api';
import { EventWorkshop } from './EventWorkshop';
export default function App({ post = postJson, get = getJson }: { post?: ApiPost; get?: ApiGet }) {
  const [part, setPart] = useState<1 | 2>(1);
  return <><nav className="workshop-parts" aria-label="실습 구성"><button aria-pressed={part === 1} onClick={() => setPart(1)}>1부 · 조건과 근거 확인</button><button aria-pressed={part === 2} onClick={() => setPart(2)}>2부 · 자유 질문과 AI 브리핑</button><span>실습을 바꾸면 질문·결과·검토가 초기화됩니다.</span></nav><EventWorkshop key={part} part={part} post={post} get={get} /></>;
}
