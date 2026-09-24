"""Entry-readiness v2 briefing; baseline migrations never invent rises."""
VERSION='entry-readiness-v2'
def make_brief(current,previous=None):
 comparable=previous is not None and current.get('previous_asof')==previous['asof'] and previous.get('score_version')==current['score_version']==VERSION
 old={r['code']:r for r in previous['metrics']} if comparable else {}
 candidates=[r for r in current['metrics'] if r['pool']=='candidate' and r['entry']['ready']]
 ranked=[]
 for r in candidates:
  p=old.get(r['code'])
  if not p or p['pool']!='candidate':continue
  delta=round(r['priority_score']-p['priority_score'],2)
  if delta>0:ranked.append((delta,r,p))
 ranked.sort(key=lambda x:(-x[0],-x[1]['priority_score'],x[1]['code']))
 lines=[f"주도주 레이더 | {current['asof']} 종가",f"진입 검토 {len(candidates)}종목 · 시총 1,000억원 이상",'진입 적합도 상승 TOP 3']
 if not comparable:lines.append('새 점수 기준 기록: 이전 관찰 점수와 비교하지 않습니다.')
 elif not ranked:lines.append('기존 진입 검토 종목 중 점수 상승 없음')
 for i,(delta,r,p) in enumerate(ranked[:3],1):
  e=r['entry'];parts=e['components'];before=p['entry']['components']
  assert abs(sum(parts.values())-r['priority_score'])<.02
  gains=sorted([(k,parts[k]-before.get(k,0))for k in parts if parts[k]>before.get(k,0)],key=lambda x:-x[1])
  lines += ['',f"{i}. {r['name']} {p['priority_score']:.1f} → {r['priority_score']:.1f} (+{delta:.1f})",f"{e['status']} · 신호 {e['signal_date']}",'점수 기여: '+', '.join(f'{k} +{v:.1f}'for k,v in gains[:2]),f"검토 {e['entry_min']:,.0f}~{e['entry_max']:,.0f}원 / 기준 종가 {r['close']:,.0f}원",f"실패 기준 {e['failure_price']:,.0f}원 · 거리 {e['risk_fraction']:.1%}"]
 new=sorted([r for r in candidates if comparable and r['code']in{v['code']for v in current.get('changes',{}).get('new',[])}],key=lambda r:-r['priority_score'])
 lines+=['',f'새 조건 충족: {len(new)}종목'if comparable else'새 조건 충족: 비교 대기']
 for r in new[:3]:
  e=r['entry'];lines.append(f"{r['name']} {r['priority_score']:.1f}점 · {e['status']} · 검토 {e['entry_min']:,.0f}~{e['entry_max']:,.0f}원 · 실패선 {e['failure_price']:,.0f}원 ({e['risk_fraction']:.1%})")
 if len(new)>3:lines.append(f'외 {len(new)-3}종목은 대시보드에서 확인')
 lines+=['','종가 기준 조건부 검토이며 자동 매수 지시가 아닙니다. 다음 가격이 검토 상한 초과·실패선 이탈이면 보류합니다.','고변동 조건부는 실패선 거리 8% 초과입니다. 갭·미체결로 손실이 이 거리를 넘을 수 있습니다.','점수는 과거 14사례 진입에 맞춘 재현 모형이며 미래 수익확률이 아닙니다.']
 return '\n'.join(lines),[r['code']for _,r,_ in ranked[:3]]
