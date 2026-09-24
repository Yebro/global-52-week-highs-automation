"""Full-universe daily snapshots. No backfilled market caps or fabricated changes."""
from pathlib import Path
import argparse,concurrent.futures,datetime,hashlib,json,math,re,sqlite3,sys,urllib.request
ROOT=Path(__file__).resolve().parents[1];DB=ROOT.parent/'leader-case-db';BASE=DB/'monitoring-entry-v2-liquidity100';TZ=datetime.timezone(datetime.timedelta(hours=9))
sys.path.insert(0,str(DB/'tools'))
import screen_market as sm
import screen_flows as sf
import entry_score
import turnover_filter
VERSION=entry_score.VERSION

def request(url):
 return urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=35).read()

def legacy_score_rows(rows):
 reference=[r for r in rows if r['cap']>=5e11 and r['median_value20_proxy']>=5e9]
 for market in ['KOSPI','KOSDAQ']:
  group=[r for r in reference if r['market']==market]
  if not group:raise ValueError('Missing reference cohort: '+market)
  for r in [x for x in rows if x['market']==market]:
   for key in ['rs20','rs60','rs20_prior']:
    r[key+'_percentile']=sum(x[key]<=r[key] for x in group)/len(group)
   r['rank_change']=r['rs20_percentile']-r['rs20_prior_percentile'];r['extended']=r['distance_ma20']>.2 or r['close']-r['ma20']>3*r['atr20']
   r['state']='가격 회복 대기' if r['close']<r['ma20'] else '과열·추격 보류' if r['extended'] else '조정 후 재출발 관찰' if r['mdd60']<=-.15 and r['drawdown60']<-.03 else '초기 부상 관찰' if r['rank_change']>.15 and r['return60']<.5 else '상승 지속 관찰'
   r['priority_score']=round(40*r['rs20_percentile']+25*r['rs60_percentile']+10*max(0,min(1,r['rank_change']/.2))+10*min(1,r['value_acceleration']/1.5)+10*(r['close']>r['ma20'])+5*(r['ma20_slope']>0)-15*r['extended'],2)
   r['passes_rs']=(r['rs20']>0 and r['rs20_percentile']>=.8) or (r['rs60']>0 and r['rs60_percentile']>=.8)
   r['qualified']=r['median_value20_proxy']>=5e9 and r['passes_rs']
   r['pool']='candidate' if r['cap']>=5e11 and r['qualified'] else 'watch' if 4e11<=r['cap']<5e11 and r['qualified'] else 'outside'
 return rows

def score_rows(rows):return entry_score.apply(rows)

def compare(current,previous):
 result={k:[] for k in ['new','rising','exits','unknown','cap_crossings','new_watch']}
 if previous and previous.get('score_version')!=current.get('score_version'):previous=None
 now={r['code']:r for r in current['metrics']};old={r['code']:r for r in previous['metrics']} if previous else {}
 old_listing={r['itemCode']:r for r in previous['listing']} if previous else {}
 for r in current['metrics']:
  r.update(previous_score=None,score_delta=None,change='baseline' if not previous else 'unchanged')
  if not previous:continue
  p=old.get(r['code']);prior_cap=sm.numeric(old_listing.get(r['code'],{}).get('marketValueRaw'))
  if prior_cap is None:prior_cap=(sm.numeric(old_listing.get(r['code'],{}).get('marketValue')) or 0)*1e8 or None
  if prior_cap is not None and prior_cap<5e11<=r['cap']:
   result['cap_crossings'].append({'code':r['code'],'name':r['name'],'previous_cap':prior_cap,'cap':r['cap'],'pool':r['pool']})
  if p and previous['score_version']==current['score_version']:
   r['previous_score']=p['priority_score'];r['score_delta']=round(r['priority_score']-p['priority_score'],2)
  if r['pool']=='candidate' and (not p or p['pool']!='candidate'):
   uncertain=not p and r['code'] in old_listing and prior_cap is not None and prior_cap>=entry_score.MIN_CAP
   r['change']='new_unverified' if uncertain else 'new'
   result['unknown' if uncertain else 'new'].append({'code':r['code'],'name':r['name'],'reason':'이전 관측 결측 · 신규 판정 보류' if uncertain else '직전 기록 대비 조건 충족'})
  elif r['pool']=='candidate' and p and p['pool']=='candidate' and r['score_delta'] is not None and r['score_delta']>0:
   r['change']='rising';result['rising'].append({'code':r['code'],'name':r['name'],'delta':r['score_delta']})
  if r['pool']=='watch' and (not p or p['pool']!='watch'):result['new_watch'].append({'code':r['code'],'name':r['name']})
 if previous:
  # Keep cap crossings visible even for newly listed or suspended names lacking history.
  for s in current['listing']:
   code=s['itemCode']
   if code in now or not sm.is_common(s):continue
   p=old_listing.get(code,{})
   before=sm.numeric(p.get('marketValueRaw')) or (sm.numeric(p.get('marketValue')) or 0)*1e8
   after=sm.numeric(s.get('marketValueRaw')) or (sm.numeric(s.get('marketValue')) or 0)*1e8
   if 0<before<5e11<=after:result['cap_crossings'].append({'code':code,'name':s['stockName'],'previous_cap':before,'cap':after,'pool':'unverified','reason':'시총 기준 통과 · 가격 이력·거래상태 확인 필요'})
  for code,p in old.items():
   if p['pool']!='candidate':continue
   r=now.get(code)
   if r is None:
    result['unknown'].append({'code':code,'name':p['name'],'reason':'당일 가격·거래상태 확인 필요'});continue
   if r['pool']!='candidate':
    reasons=[]
    reasons.extend(r.get('entry',{}).get('blockers',[]))
    result['exits'].append({'code':code,'name':p['name'],'reason':' · '.join(reasons),'score':r['priority_score']})
 result['rising'].sort(key=lambda r:-r['delta'])
 return result

def run(bootstrap=None):
 BASE.mkdir(parents=True,exist_ok=True);today=datetime.datetime.now(TZ).date().isoformat()
 if bootstrap:
  original=DB/'screening'/bootstrap;seed=json.loads((original/'screen.json').read_text(encoding='utf-8'));asof=seed['asof'];universe=seed['listing'];first=None
 else:
  # Fresh full listings are requested on every open-day run. No fixed 90-stock universe.
  first={m:json.loads(request(f'https://m.stock.naver.com/api/stocks/marketValue/{m}?page=1&pageSize=100')) for m in ['KOSPI','KOSDAQ']}
  market_dates={max(s['localTradedAt'][:10] for s in a['stocks'] if s.get('localTradedAt')) for a in first.values()}
  if len(market_dates)!=1:raise ValueError('Market dates differ; keep last good snapshot')
  asof=market_dates.pop()
  if asof!=today:
   print(json.dumps({'status':'no_current_session','latest_quote_date':asof,'today':today}));return
  if datetime.datetime.now(TZ).hour<16:raise ValueError('Run after 16:00 KST for closing snapshot')
  original=DB/'screening'/asof;seed=None
 folder=BASE/asof;rawdir=folder/'raw';rawdir.mkdir(parents=True,exist_ok=True)
 target=folder/'snapshot.json'
 if target.exists():print(json.dumps({'status':'already_saved','asof':asof}));return
 def cached(url,name):
  p=rawdir/name
  if bootstrap and p.exists():return p.read_bytes()
  legacy=original/'raw'/name
  b=legacy.read_bytes() if bootstrap and legacy.exists() else request(url)
  p.write_bytes(b);return b
 sm.get=cached;sm.RAW=rawdir;sm.ASOF=asof;sf.get=cached;sf.ASOF=asof
 if first:
  for m,a in first.items():(rawdir/f'{m}-1.json').write_text(json.dumps(a),encoding='utf-8')
  jobs=[(m,p) for m,a in first.items() for p in range(2,math.ceil(a['totalCount']/100)+1)]
  with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:pages=list(pool.map(lambda x:sm.listing(*x),jobs))
  universe=[]
  for a in list(first.values())+pages:
   for s in a['stocks']:s['_market']=a['stockListCategoryType'];universe.append(s)
  for m,a in first.items():assert sum(s['_market']==m for s in universe)==a['totalCount'],'Incomplete listing'
 assert len({r['itemCode'] for r in universe})==len(universe),'Duplicate listing'
 prior_paths=sorted(p for p in BASE.glob('*/snapshot.json') if p.parent.name<asof)
 previous=json.loads(prior_paths[-1].read_text(encoding='utf-8')) if prior_paths else None
 previous_codes={r['code'] for r in previous['metrics'] if r['pool'] in ['candidate','watch']} if previous else set()
 common=[s for s in universe if sm.is_common(s)]
 def cap(s):return sm.numeric(s.get('marketValueRaw')) or (sm.numeric(s.get('marketValue')) or 0)*1e8
 eligible=[s for s in common if cap(s)>=entry_score.MIN_CAP or s['itemCode'] in previous_codes]
 tradable=[s for s in eligible if s.get('tradeStopType',{}).get('name')=='TRADING' and s['localTradedAt'][:10]==asof]
 benchmark=seed['benchmark'] if seed else {m:{r['date']:r['close'] for r in sm.prices(m)} for m in first}
 seeded={r['code']:r for r in seed['all_metrics']} if seed else {}
 def measure(s):return seeded[s['itemCode']] if s['itemCode'] in seeded and 'error' not in seeded[s['itemCode']] else sm.one(s,benchmark,allow_halted_history=True)
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(measure,tradable))
 valid=[r for r in results if 'error' not in r and r.get('price_quote_match')]
 # An incomplete fetch must not turn missing stocks into false exits or move every percentile.
 unexpected=[r for r in results if 'error' in r and r['error'] not in ['81개 거래일 이력 부족','최근 20일 무거래 관측','당일 무거래 관측']]
 if unexpected:raise ValueError('Incomplete price collection; no snapshot saved: '+json.dumps(unexpected,ensure_ascii=False))
 if any(not r.get('price_quote_match',True) for r in results):raise ValueError('Price/quote mismatch; no snapshot saved')
 sessions=turnover_filter.collect(universe,sorted(benchmark["KOSPI"])[-3:],previous,cached)
 scored=turnover_filter.apply(score_rows(valid),sessions)
 selected=sorted([r for r in scored if r['pool']!='outside'],key=lambda r:-r['priority_score'])
 # Flows are supporting evidence, not an entry gate. Limit expensive supplementary fetches.
 flow_selected=[r for r in selected if r['pool']=='candidate'][:60]+[r for r in selected if r['pool']=='watch'][:40]
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:flow=dict(pool.map(sf.fetch,flow_selected))
 data=dict(schema_version=1,score_version=VERSION,asof=asof,previous_asof=previous['asof'] if previous else None,collected_at=datetime.datetime.now(TZ).isoformat(),listing=universe,metrics=scored,flows=flow,errors=[r for r in results if 'error' in r],counts=dict(listed=len(universe),common=len(common),cap4000=sum(cap(s)>=4e11 for s in common),cap5000=sum(cap(s)>=5e11 for s in common),valid=len(valid),candidate=sum(r['pool']=='candidate' for r in scored),watch=sum(r['pool']=='watch' for r in scored)),method=dict(cap_min=5e11,prewatch_min=4e11,liquidity_proxy_min=5e9,rs_percentile=.8,ranking_reference='same market, cap >= 500bn KRW and liquid; watch stocks evaluated against this reference without changing it',score_version=VERSION,score_alert_threshold=5,prior_comparison='previous successful dated snapshot, not necessarily previous trading day'))
 data['turnover_sessions']=sessions
 data['counts']['turnover_excluded']=sum(not r['turnover_filter']['passed'] for r in scored)
 data['changes']=compare(data,previous)
 data['counts']['cap1000']=sum(cap(s)>=entry_score.MIN_CAP for s in common)
 data['schema_version']=2
 data['method']=dict(score_version=VERSION,cap_min=entry_score.MIN_CAP,configuration=entry_score.CONFIG,turnover_policy=turnover_filter.POLICY,turnover_min_exclusive=turnover_filter.THRESHOLD,turnover_sessions=3,reference_cap_min=5e11,reference_liquidity_min=5e9,components={'setup':35,'trend':20,'liquidity':15,'failure_distance':20,'entry_position':10},signal_max_age=2,blocked_score_ceiling=59,validation='Calibrated to historical entry labels; not an out-of-sample profit test; no live order execution',flow_coverage='Top 60 entry-review and top 40 watch rows; missing flow is not zero',prior_comparison='previous successful same-version snapshot')
 # Only metrics are needed in the daily DB; raw prices remain in hashed source snapshots.
 for r in data['metrics']:r.pop('bars',None)
 body=json.dumps(data,ensure_ascii=False,sort_keys=True);sha=hashlib.sha256(body.encode()).hexdigest()
 con=sqlite3.connect(DB/'leader_cases.sqlite3');con.execute('CREATE TABLE IF NOT EXISTS entry_liquidity_monitor_snapshots(asof TEXT PRIMARY KEY,score_version TEXT,sha256 TEXT,payload_json TEXT)')
 old=con.execute('SELECT sha256 FROM entry_liquidity_monitor_snapshots WHERE asof=?',(asof,)).fetchone()
 if old:assert old[0]==sha,'Snapshot is immutable'
 else:con.execute('INSERT INTO entry_liquidity_monitor_snapshots VALUES (?,?,?,?)',(asof,VERSION,sha,body))
 con.commit();con.close();temp=target.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(target)
 (folder/'raw-manifest.json').write_text(json.dumps([{'file':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(rawdir.iterdir())],indent=2),encoding='utf-8')
 print(json.dumps({'status':'saved','asof':asof,'counts':data['counts'],'changes':{k:len(v) for k,v in data['changes'].items()}},ensure_ascii=False))

if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');parser=argparse.ArgumentParser();parser.add_argument('--bootstrap');args=parser.parse_args();run(args.bootstrap)
