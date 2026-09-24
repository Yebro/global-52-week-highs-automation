"""Causal entry-readiness heuristic. Not a probability or an order instruction.
Thresholds are calibrated to historical entry labels, never future profits.
"""
import statistics as st
VERSION='entry-readiness-v2-liquidity100'
MIN_CAP=1e11
CONFIG=dict(min_score=70,max_risk=.16,max_pivot_atr=2,max_ma_atr=6,min_liquidity=5e8,require_slope=False)

def scenes(bars):
    """Local 180-bar detector, bounded correction episodes; no future peaks."""
    events=[];anchor=max(range(min(60,len(bars))),key=lambda j:bars[j]['close']) if bars else None;trough=anchor;pull=False
    for i in range(60,len(bars)):
        c=bars[i]['close'];vol=bars[i]['volume']
        high=max(p['close'] for p in bars[i-60:i]);avg=st.mean(p['volume'] for p in bars[i-50:i])
        reb=None
        if anchor is not None:
            if i-anchor>120:anchor=max(range(i-60,i),key=lambda j:bars[j]['close']);pull=False;trough=anchor
            elif c>=bars[anchor]['close']:
                if pull:reb=dict(kind='rebreakout',i=i,date=bars[i]['date'],pivot=bars[anchor]['close'])
                anchor=i;trough=i;pull=False
            else:
                trough=i if trough is None or c<bars[trough]['close'] else trough
                if c/bars[anchor]['close']<=.90:pull=True
        breakout=c>high and avg>0 and vol/avg>=1.5
        if breakout:
            events.append(dict(kind='breakout',i=i,date=bars[i]['date'],pivot=high))
            anchor=i;trough=i;pull=False
        elif reb:events.append(reb)
    return events

def evaluate(r,config=None):
    cfg=CONFIG if config is None else config
    p=r.get('bars',[])
    if len(p)<81:raise ValueError('Entry scoring needs 81+ original OHLCV bars')
    if any(k not in p[-1] for k in ('open','high','low','close','volume')):raise ValueError('Missing OHLCV')
    ev=scenes(p);last=ev[-1] if ev else None;age=len(p)-1-last['i'] if last else None
    recent=last is not None and age<=2
    pivot=last['pivot'] if recent else r['prior60_high']
    close=r['close'];atr=r['atr20'];ma=r['ma20'];ratio=p[-1]['volume']/st.mean(x['volume'] for x in p[-51:-1])
    values=[x.get('value',x['close']*x['volume']) for x in p[-5:]]
    liquid=r['median_value20_proxy']>=cfg['min_liquidity'] or (st.mean(values)>=cfg['min_liquidity'] and sum(v>=cfg['min_liquidity'] for v in values)>=3)
    # Freeze the initial failure level and upper price at signal-day close.
    # They must not move up just because today's price/ATR rose.
    if recent:
        j=last['i'];prior=p[j-10:j]
        signal_atr=st.mean(max(p[k]['high']-p[k]['low'],abs(p[k]['high']-p[k-1]['close']),abs(p[k]['low']-p[k-1]['close'])) for k in range(j-19,j+1))
        signal_ma=st.mean(x['close'] for x in p[j-19:j+1])
        stop=max(min(x['close'] for x in prior),pivot-signal_atr)
        upper=min(pivot+cfg['max_pivot_atr']*signal_atr,signal_ma+cfg['max_ma_atr']*signal_atr,stop/(1-cfg['max_risk']))
    else:stop=None;upper=None;signal_atr=atr
    risk=(close-stop)/close if stop is not None else None
    dist=(close-pivot)/signal_atr if signal_atr>0 else None
    trend=(5*(close>ma)+5*(r['ma20_slope']>0)+5*(r['rs20']>0)+5*(r['rs60']>0))
    trigger=(35 if last and last['kind']=='breakout' else 32)-3*age if recent else 0
    riskpoints=20 if risk is not None and 0<risk<=.04 else 15 if risk is not None and .04<risk<=.06 else 8 if risk is not None and .06<risk<=cfg['max_risk'] else 0
    timing=10 if recent and dist is not None and 0<=dist<=.5 else 7 if recent and dist is not None and .5<dist<=1 else 3 if recent and dist is not None and 1<dist<=cfg['max_pivot_atr'] else 0
    parts={'진입 장면':trigger,'추세 확인':trend,'거래 확인':10*min(1,ratio/2)+5*(sum(v>=cfg['min_liquidity'] for v in values)>=3),'실패 기준 거리':riskpoints,'추격 부담':timing}
    raw=round(sum(parts.values()),2);blocks=[]
    if not recent:blocks.append('최근 3거래일 내 돌파·재돌파 없음')
    if close<=ma or (cfg['require_slope'] and r['ma20_slope']<=0) or r['rs20']<=0:blocks.append('20일선·기울기·RS20 조건 미달')
    if not liquid:blocks.append('거래대금 지속성 부족')
    if r['cap']<MIN_CAP:blocks.append('시총 1천억원 미달')
    if recent:
        # A failed attempt is not reinstated merely by recovering within its three-day window.
        since=p[last['i']+1:]
        if any(x['close']<pivot or x['close']<=stop for x in since):blocks.append('신호 이후 돌파 기준·실패선 이탈')
        if close<pivot:blocks.append('돌파 기준 아래')
        if upper<pivot or close>upper:blocks.append('진입 검토 상한 초과·추격 보류')
        if risk is None or not 0<risk<=cfg['max_risk']:blocks.append(f'실패 기준 거리 0~{cfg["max_risk"]:.0%} 조건 미달')
    if atr<=0:blocks.append('변동폭 확인 불가')
    if not blocks and raw<cfg['min_score']:blocks.append(f'진입 적합도 {cfg["min_score"]}점 미만')
    score=round(min(raw,59) if blocks else raw,2)
    parts['보류 상한 조정']=round(score-raw,2)
    ready=not blocks
    state=('고변동 조건부' if risk>.08 else '진입 검토') if ready else '추격 보류' if any('상한' in b for b in blocks) else '추세 회복 대기' if close<=ma or r['rs20']<=0 else '돌파·재돌파 대기' if not recent else '조건 확인 필요'
    return dict(version=VERSION,score=score,raw_score=raw,components=parts,ready=ready,status=state,blockers=blocks,setup=last['kind'] if recent else 'none',signal_date=last['date'] if recent else None,signal_age=age if recent else None,pivot=pivot,entry_min=pivot if recent else None,entry_max=upper,failure_price=stop,risk_fraction=risk,volume_ratio50=ratio,liquid=liquid,asof=p[-1]['date'],expires='신호 포함 3거래일·매일 종가 재판정',price_basis='수정주가 기반 계산 참고가격; 주문 가격 아님',validation='검증 전 가설; 과거 14사례의 매매를 재현한 최적화 모델 아님')

def apply(rows):
    reference=[r for r in rows if r['cap']>=5e11 and r['median_value20_proxy']>=5e9]
    for market in ['KOSPI','KOSDAQ']:
        group=[r for r in reference if r['market']==market]
        if not group:raise ValueError('Missing reference cohort: '+market)
        for r in [x for x in rows if x['market']==market]:
            for key in ['rs20','rs60','rs20_prior']:r[key+'_percentile']=sum(x[key]<=r[key] for x in group)/len(group)
            r['rank_change']=r['rs20_percentile']-r['rs20_prior_percentile']
            e=evaluate(r);r['entry']=e;r['priority_score']=e['score'];r['state']=e['status']
            r['qualified']=e['ready'];r['passes_rs']=r['rs20']>0
            watch=(r['rs20']>0 or r['rank_change']>0 or e['signal_date'] is not None) and (r['median_value20_proxy']>=1e9 or r['value_acceleration']>=1.5)
            r['pool']='candidate' if e['ready'] else 'watch' if watch and r['cap']>=MIN_CAP else 'outside'
    return rows
