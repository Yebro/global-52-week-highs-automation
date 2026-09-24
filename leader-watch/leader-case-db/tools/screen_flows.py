import json,concurrent.futures,sys,hashlib
from screen_market import OUT,RAW,get,numeric,ASOF
def fetch(r):
 code=r['code'];url=f'https://m.stock.naver.com/api/stock/{code}/trend?pageSize=30&page=1'
 try:
  rows=json.loads(get(url,code+'-flows.json'));bydate={x['bizdate']:x for x in rows if x['bizdate']<=ASOF.replace('-','')};results={}
  for n in [5,20]:
   dates=[x['date'].replace('-','') for x in r['bars'][-n:]];available=[bydate[d] for d in dates if d in bydate];groups={}
   for name,key in [('개인','individualPureBuyQuant'),('기관','organPureBuyQuant'),('외국인','foreignerPureBuyQuant')]:
    vals=[numeric(x.get(key)) for x in available];valid=len(vals)==n and all(v is not None for v in vals)
    groups[name]=dict(net_shares=sum(vals) if valid else None,buy_days=sum(v>0 for v in vals) if valid else None)
   valid=all(g['net_shares'] is not None for g in groups.values());leader=max(groups,key=lambda k:groups[k]['net_shares']) if valid else None
   results[str(n)]=dict(start=dates[0],end=dates[-1],observed_days=len(available),expected_days=n,groups=groups,largest_net_buyer=leader if leader and groups[leader]['net_shares']>0 else None)
  return code,dict(url=url,unit='주 · 순매수 수량',periods=results,scope='개인·기관·외국인만 비교. 기타 주체 미합산; 금액 또는 전체 수급의 지배력으로 해석하지 않음.')
 except Exception as e:return code,dict(error=str(e),url=url)
if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8');a=json.loads((OUT/'screen.json').read_text(encoding='utf-8'))
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:flows=dict(pool.map(fetch,a['candidates']))
 (OUT/'flows.json').write_text(json.dumps(flows,ensure_ascii=False,indent=2),encoding='utf-8')
 for r in a['candidates'][:18]:print(r['name'],json.dumps(flows[r['code']],ensure_ascii=False))
 manifest=[dict(file=p.name,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(RAW.iterdir())];(OUT/'raw-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
