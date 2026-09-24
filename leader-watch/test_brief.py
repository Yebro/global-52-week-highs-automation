import copy
import gzip
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from daily_brief import components, make_brief
from telegram_delivery import send_once

BASE = Path(__file__).resolve().parent / 'state/snapshots/2026-09-23.json.gz'


class BriefTests(unittest.TestCase):
    def setUp(self):
        self.seed = json.loads(gzip.decompress(BASE.read_bytes()))

    def test_baseline_does_not_invent_rises(self):
        text, top = make_brief(self.seed)
        self.assertEqual(top, [])
        self.assertIn('비교 가능한 이전 기록이 없어', text)

    def test_all_real_scores_reconcile(self):
        for r in self.seed['metrics']:
            self.assertAlmostEqual(round(sum(components(r).values()), 2), r['priority_score'], places=2)

    def test_penalty_release_is_not_called_fundamental_improvement(self):
        old = copy.deepcopy(self.seed)
        now = copy.deepcopy(old)
        now['asof'] = '2026-09-28'
        now['previous_asof'] = old['asof']
        r = next(r for r in now['metrics'] if r['pool'] == 'candidate' and r['extended'])
        r['extended'] = False
        r['priority_score'] = round(sum(components(r).values()), 2)
        text, top = make_brief(now, old)
        self.assertEqual(top, [r['code']])
        self.assertIn('과열 감점 +15.00점', text)
        self.assertIn('상승 종목이 1개', text)

    def test_different_version_suppresses_ranking(self):
        now = copy.deepcopy(self.seed)
        now['previous_asof'] = self.seed['asof']
        now['score_version'] = 'v2'
        self.assertEqual(make_brief(now, self.seed)[1], [])

    def test_top_three_are_ordered_by_gain_not_absolute_score(self):
        old = copy.deepcopy(self.seed)
        old['metrics'] = [copy.deepcopy(self.seed['metrics'][0]) for _ in range(5)]
        for i, row in enumerate(old['metrics']):
            row.update(code=str(i), pool='candidate', rs20_percentile=.1 if i else .9)
            row['priority_score'] = round(sum(components(row).values()), 2)
        now = copy.deepcopy(old)
        now.update(asof='2026-09-28', previous_asof=old['asof'])
        for row, increase in zip(now['metrics'], [.05, .2, .3, .4, .8]):
            row['rs20_percentile'] += increase
            row['priority_score'] = round(sum(components(row).values()), 2)
        old['metrics'][4]['pool'] = 'watch'  # New entry must not enter continuing-candidate ranking.
        text, top = make_brief(now, old)
        self.assertEqual(top, ['3', '2', '1'])
        self.assertLess(len(text.encode('utf-16-le')) // 2, 4096)

    def test_holiday_and_open_day_gate(self):
        import datetime as dt
        from run import session_status, TZ
        self.assertEqual(session_status(dt.datetime(2026, 9, 24, 16, tzinfo=TZ)), 'holiday')
        self.assertEqual(session_status(dt.datetime(2026, 9, 28, 15, tzinfo=TZ)), 'before_close')
        self.assertEqual(session_status(dt.datetime(2026, 9, 28, 16, tzinfo=TZ)), 'open_day')

    def test_network_error_redacted_and_retry_blocked(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'TELEGRAM_BOT_TOKEN': 'FAKE_SECRET', 'TELEGRAM_CHAT_ID': 'TEST_CHAT'}):
            with patch('urllib.request.urlopen', side_effect=ValueError('FAKE_SECRET')) as request:
                with self.assertRaises(RuntimeError) as first:
                    send_once('test', '2026-09-23', d)
                self.assertNotIn('FAKE_SECRET', str(first.exception))
                with self.assertRaises(RuntimeError):
                    send_once('test', '2026-09-23', d)
                self.assertEqual(request.call_count, 1)


if __name__ == '__main__':
    unittest.main()
