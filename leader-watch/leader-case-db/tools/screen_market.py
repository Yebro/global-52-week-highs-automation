"""Dated current-market screen. Freeze public responses and keep failed observations."""
import json,urllib.request,concurrent.futures,hashlib,re,statistics,math,datetime,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'screening/2026-09-23';RAW=OUT/'raw';ASOF='2026-09-23'
def get(url,name):
 path=RAW/name
 if path.exists():return path.read_bytes()
 raw=urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=30).read();path.write_bytes(raw);return raw
def listing(market,page):
 return json.loads(get(f'https://m.stock.naver.com/api/stocks/marketValue/{market}?page={page}&pageSize=100',f'{market}-{page}.json'))
def numeric(v):
 if v is None:return None
 try:return float(str(v).replace(',','').replace('%',''))
 except ValueError:return None
def prices(code):
 raw=get(f'https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count=180&requestType=0',code+'.xml');a=[]
 for val in re.findall(rb'<item data="([^"]+)"',raw):
  row=val.decode().split('|');day=f'{row[0][:4]}-{row[0][4:6]}-{row[0][6:]}'
  if day<=ASOF and float(row[4])>0:a.append(dict(date=day,open=float(row[1]),high=float(row[2]),low=float(row[3]),close=float(row[4]),volume=int(row[5])))
 return sorted(a,key=lambda r:r['date'])
def is_common(s):
 return s.get('stockEndType')=='stock' and not re.search(r'(우[BC]?|\d+우[BC]?|우\(전환\))$',s['stockName']) and not re.search('스팩|리츠|인프라펀드',s['stockName'])
def one(s,bm,allow_halted_history=False):
 try:
  p=prices(s['itemCode']);dates=[r['date'] for r in p]
  if len(p)<81:raise ValueError('81개 거래일 이력 부족')
  if p[-1]['date']!=ASOF:raise ValueError('최근 가격 날짜 불일치')
  if p[-1]['volume']<=0:raise ValueError('당일 무거래 관측')
  if not allow_halted_history and any(r['volume']<=0 for r in p[-20:]):raise ValueError('최근 20일 무거래 관측')
  if allow_halted_history:
   for r in p:
    if r['volume']==0 and r['high']==0 and r['low']==0:r.update(open=r['close'],high=r['close'],low=r['close'])
  if len(dates)!=len(set(dates)):raise ValueError('날짜 중복')
  market=s['_market'];b=bm[market]
  def rs(n,lag=0):
   z=len(p)-1-lag;now=p[z];old=p[z-n]
   return (now['close']/old['close'])/(b[now['date']]/b[old['date']])-1
  close=p[-1]['close'];v=[r['close']*r['volume'] for r in p];last20=p[-20:];high=max(r['close'] for r in p[-60:]);ma20=statistics.mean(r['close'] for r in last20);ma60=statistics.mean(r['close'] for r in p[-60:])
  peak=p[-60]['close'];mdd=0
  for r in p[-60:]:peak=max(peak,r['close']);mdd=min(mdd,r['close']/peak-1)
  return dict(code=s['itemCode'],name=s['stockName'],market=market,cap=numeric(s.get('marketValueRaw')) or numeric(s['marketValue'])*1e8,cap_asof=s['localTradedAt'][:10],close=close,quote_close=numeric(s['closePrice']),price_quote_match=close==numeric(s['closePrice']),rs20=rs(20),rs60=rs(60),rs20_prior=rs(20,20),return20=close/p[-21]['close']-1,return60=close/p[-61]['close']-1,median_value20_proxy=statistics.median(v[-20:]),value_acceleration=statistics.mean(v[-5:])/statistics.mean(v[-25:-5]),ma20=ma20,ma60=ma60,ma20_slope=ma20/statistics.mean(r['close'] for r in p[-25:-5])-1,distance_ma20=close/ma20-1,prior20_high=max(r['close'] for r in p[-21:-1]),prior60_high=max(r['close'] for r in p[-61:-1]),prior10_low=min(r['close'] for r in p[-11:-1]),drawdown60=close/high-1,mdd60=mdd,atr20=statistics.mean(max(p[i]['high']-p[i]['low'],abs(p[i]['high']-p[i-1]['close']),abs(p[i]['low']-p[i-1]['close'])) for i in range(len(p)-20,len(p))),bars=p,source=f'https://m.stock.naver.com/domestic/stock/{s["itemCode"]}/total')
 except Exception as e:return dict(code=s['itemCode'],name=s['stockName'],error=str(e))
def main():
 RAW.mkdir(parents=True,exist_ok=True);first={m:listing(m,1) for m in ['KOSPI','KOSDAQ']};jobs=[(m,p) for m,a in first.items() for p in range(2,math.ceil(a['totalCount']/100)+1)]
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:pages=list(pool.map(lambda v:listing(*v),jobs))
 universe=[]
 for a in list(first.values())+pages:
  for s in a['stocks']:s['_market']=a['stockListCategoryType'];universe.append(s)
 codes=[s['itemCode'] for s in universe];assert len(codes)==len(set(codes)), 'Listing duplicate'
 assert all(sum(s['_market']==m for s in universe)==a['totalCount'] for m,a in first.items())
 common=[s for s in universe if is_common(s)];cap=[s for s in common if (numeric(s.get('marketValueRaw')) or numeric(s['marketValue'])*1e8)>=5e11];tradable=[s for s in cap if s.get('tradeStopType',{}).get('name')=='TRADING' and s['localTradedAt'][:10]==ASOF]
 print('UNIVERSE',len(universe),'COMMON_HEURISTIC',len(common),'CAP',len(cap),'TRADABLE',len(tradable),flush=True)
 bm={m:{r['date']:r['close'] for r in prices(m)} for m in first};results=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
  for i,r in enumerate(pool.map(lambda s:one(s,bm),tradable)):
   results.append(r)
   if (i+1)%100==0:print('PRICES',i+1,flush=True)
 good=[r for r in results if 'error' not in r and r['price_quote_match']];liquid=[r for r in good if r['median_value20_proxy']>=5e9]
 for m in first:
  group=[r for r in liquid if r['market']==m]
  for key in ['rs20','rs60','rs20_prior']:
   for r in group:r[key+'_percentile']=sum(x[key]<=r[key] for x in group)/len(group)
 candidates=[]
 for r in liquid:
  if not ((r['rs20']>0 and r['rs20_percentile']>=.8) or (r['rs60']>0 and r['rs60_percentile']>=.8)):continue
  r['rank_change']=r['rs20_percentile']-r['rs20_prior_percentile'];r['extended']=r['distance_ma20']>.20 or r['close']-r['ma20']>3*r['atr20']
  r['state']='가격 회복 대기' if r['close']<r['ma20'] else '과열·추격 보류' if r['extended'] else '조정 후 재출발 관찰' if r['mdd60']<=-.15 and r['drawdown60']<-.03 else '초기 부상 관찰' if r['rank_change']>.15 and r['return60']<.5 else '상승 지속 관찰'
  r['priority_score']=round(40*r['rs20_percentile']+25*r['rs60_percentile']+10*max(0,min(1,r['rank_change']/.2))+10*min(1,r['value_acceleration']/1.5)+10*(r['close']>r['ma20'])+5*(r['ma20_slope']>0)-15*r['extended'],2)
  candidates.append(r)
 candidates.sort(key=lambda r:-r['priority_score'])
 counts=dict(listed_by_market={m:a['totalCount'] for m,a in first.items()},listed_total=len(universe),common_name_type_filter=len(common),cap5000=len(cap),tradable_asof=len(tradable),price_valid=len(good),liquid_proxy=len(liquid),quant_candidates=len(candidates),candidate_by_market={m:sum(r['market']==m for r in candidates) for m in first},errors=sum('error'in r for r in results),price_mismatch=sum(not r.get('price_quote_match',True) for r in results))
 output=dict(asof=ASOF,collected_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),policy_version=2,excluded_ranges=[],counts=counts,method=dict(cap_min=5e11,liquidity_proxy_min=5e9,rs_percentile=.8,rank_universe='same-market liquid cap-eligible stocks with valid history; prior ranks use current surviving cohort',liquidity='median(close * volume), proxy not actual traded KRW',security_filter='stockEndType stock; preferred/SPAC/REIT excluded by name; exchange security master not independently reconciled',scores='observation priority only, not probability',date_cutoff=ASOF,flow_unit='shares; no inferred KRW or missing category residual'),candidates=candidates,all_metrics=results,listing=universe,errors=[r for r in results if 'error'in r],benchmark=bm)
 (OUT/'screen.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
 manifest=[dict(file=p.name,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(RAW.iterdir())];(OUT/'raw-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
 print(json.dumps(counts,ensure_ascii=False));print('TOP',json.dumps([{k:r[k] for k in ['code','name','market','close','rs20','rs60','median_value20_proxy','value_acceleration','state','priority_score']} for r in candidates[:25]],ensure_ascii=False))
if __name__=='__main__':sys.stdout.reconfigure(encoding='utf-8');main()
