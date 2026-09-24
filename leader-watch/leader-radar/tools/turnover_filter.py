"""Strict actual-turnover gate; calendar sessions, never close times volume."""
import io, json, math

THRESHOLD = 10_000_000_000
POLICY = 'actual-turnover-3sessions-gt-100eok-v1'

def number(v):
    try:
        n=float(str(v).replace(',', ''))
        return n if math.isfinite(n) and n>=0 else None
    except (TypeError, ValueError):return None

def collect(listing, dates, previous, cached):
    """Keep ALL listing amounts, including names below today's cap floor."""
    if len(dates)!=3 or dates!=sorted(set(dates)):raise ValueError('Need three distinct trading sessions')
    sessions={s['date']:s for s in (previous or {}).get('turnover_sessions',[]) if s['date'] in dates}
    current={}
    for s in listing:
        if s.get('localTradedAt','')[:10]!=dates[-1]:continue
        v=number(s.get('accumulatedTradingValueRaw'))
        if v is None:
            v=number(s.get('accumulatedTradingValue'))
            if v is not None:v*=1_000_000 # Naver display unit: million KRW
        if v is not None:current[s['itemCode']]=v
    if not current:raise ValueError('Current actual turnover unavailable')
    sessions[dates[-1]]=dict(date=dates[-1],amounts=current,source='Naver marketValue accumulatedTradingValueRaw (KRW)')
    missing=[d for d in dates if d not in sessions]
    for year in sorted({d[:4] for d in missing}):
        import pandas as pd
        url=f'https://raw.githubusercontent.com/FinanceData/marcap/master/data/marcap-{year}.parquet'
        frame=pd.read_parquet(io.BytesIO(cached(url,f'marcap-{year}.parquet')),columns=['Code','Date','Amount'])
        frame['day']=frame['Date'].dt.strftime('%Y-%m-%d')
        for day in [d for d in missing if d.startswith(year)]:
            rows=frame[frame.day==day]
            if rows.empty:raise ValueError('Actual turnover session unavailable: '+day)
            sessions[day]=dict(date=day,amounts={str(r.Code).zfill(6):float(r.Amount) for r in rows.itertuples() if number(r.Amount) is not None},source=url+' / Amount (KRW)')
    return [sessions[d] for d in dates]

def decision(code, sessions):
    values=[number(s['amounts'].get(code)) for s in sessions]
    known=[v for v in values if v is not None]
    passed=len(sessions)==3 and any(v>THRESHOLD for v in known)
    complete=len(sessions)==3 and len(known)==3
    return dict(policy=POLICY,passed=passed,complete=complete,
                max_krw=max(known) if known else None,
                days=[dict(date=s['date'],amount_krw=v) for s,v in zip(sessions,values)],
                reason=None if passed else '최근 3거래일 실제 거래대금 미확인' if not complete else '최근 3거래일 거래대금 100억원 초과 없음')

def apply(rows,sessions):
    for r in rows:
        gate=decision(r['code'],sessions);r['turnover_filter']=gate
        if gate['passed']:continue
        e=r['entry'];e['blockers'].append(gate['reason']);e['ready']=False
        score=min(e['score'],59);e['components']['보류 상한 조정']+=score-e['score'];e['score']=score
        e['status']='거래대금 조건 제외';r.update(pool='outside',qualified=False,state=e['status'],priority_score=score)
    return rows
