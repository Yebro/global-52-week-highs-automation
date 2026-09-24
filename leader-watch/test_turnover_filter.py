import sys, unittest, copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'leader-radar/tools'))
import turnover_filter as tf

def sessions(values):
    return [dict(date=d,amounts={'A':v}) for d,v in zip(['2026-09-18','2026-09-21','2026-09-22'],values)]

class TurnoverTests(unittest.TestCase):
    def test_strict_boundary_and_any_of_three(self):
        self.assertFalse(tf.decision('A',sessions([1e10,1e10,1e10]))['passed'])
        for i in range(3):
            v=[0,0,0];v[i]=1e10+1
            self.assertTrue(tf.decision('A',sessions(v))['passed'])
    def test_sum_is_not_daily_max(self):
        self.assertFalse(tf.decision('A',sessions([6e9]*3))['passed'])
    def test_missing_not_zero_but_one_confirmed_pass_is_sufficient(self):
        a=tf.decision('A',sessions([None,0,0]));self.assertFalse(a['passed']);self.assertFalse(a['complete'])
        self.assertTrue(tf.decision('A',sessions([None,1e10+1,0]))['passed'])
    def test_uses_market_sessions_and_preserves_below_cap_names(self):
        prev={'turnover_sessions':sessions([2e10,0,0])}
        listing=[dict(itemCode='A',localTradedAt='2026-09-23T16:00:00',accumulatedTradingValueRaw='10000000000',marketValueRaw='100')]
        def no_fetch(*args):raise AssertionError('Should use saved prior sessions')
        current=tf.collect(listing,['2026-09-21','2026-09-22','2026-09-23'],prev,no_fetch)
        self.assertEqual(len(current),3);self.assertFalse(tf.decision('A',current)['passed'])
        self.assertEqual(current[-1]['amounts']['A'],1e10)
    def test_excludes_candidate_and_watch_and_reconciles_score(self):
        for pool in ['candidate','watch']:
            r=dict(code='A',pool=pool,entry=dict(blockers=[],ready=True,score=80,components={'base':80,'보류 상한 조정':0}))
            tf.apply([r],sessions([1e9]*3))
            self.assertEqual(r['pool'],'outside');self.assertFalse(r['entry']['ready'])
            self.assertEqual(sum(r['entry']['components'].values()),r['priority_score'])

if __name__=='__main__':unittest.main()
