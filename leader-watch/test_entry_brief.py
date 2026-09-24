import unittest,json,gzip,copy
from pathlib import Path
from entry_brief import make_brief
class EntryBriefTests(unittest.TestCase):
 def setUp(self):self.a=json.loads(gzip.decompress((Path(__file__).parent/'state/snapshots-entry-v2/2026-09-23.json.gz').read_bytes()))
 def test_baseline_and_mixed_versions(self):
  self.assertEqual(make_brief(self.a)[1],[])
  old=copy.deepcopy(self.a);old['score_version']='rs-price-v1';now=copy.deepcopy(self.a);now['previous_asof']=old['asof']
  self.assertEqual(make_brief(now,old)[1],[])
 def test_positive_gains_only_and_new_entries_separate(self):
  old=copy.deepcopy(self.a);now=copy.deepcopy(self.a);now.update(asof='2026-09-28',previous_asof=old['asof'])
  selected=[r for r in now['metrics']if r['pool']=='candidate'][:4]
  for i,r in enumerate(selected):
   r['priority_score']+=i+1;r['entry']['components']['추세 확인']+=i+1
  next(r for r in old['metrics']if r['code']==selected[-1]['code'])['pool']='watch'
  text,top=make_brief(now,old)
  self.assertEqual(top,[r['code']for r in selected[2::-1]])
  self.assertIn('실패 기준',text);self.assertLess(len(text.encode('utf-16-le'))//2,4096)
if __name__=='__main__':unittest.main()
