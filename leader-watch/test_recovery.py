import datetime as dt
import unittest
from unittest.mock import patch
from run import latest_closed_session, TZ, failure

class RecoveryTests(unittest.TestCase):
    def test_delayed_monday_run_after_midnight_recovers_monday(self):
        self.assertEqual(latest_closed_session(dt.datetime(2026,10,13,1,34,tzinfo=TZ)), '2026-10-12')

    def test_weekend_recovers_friday(self):
        self.assertEqual(latest_closed_session(dt.datetime(2026,10,17,12,tzinfo=TZ)), '2026-10-16')

    def test_1600_cutoff_and_holidays(self):
        self.assertEqual(latest_closed_session(dt.datetime(2026,9,28,15,59,tzinfo=TZ)), '2026-09-23')
        self.assertEqual(latest_closed_session(dt.datetime(2026,9,28,16,tzinfo=TZ)), '2026-09-28')
        self.assertEqual(latest_closed_session(dt.datetime(2026,10,9,18,tzinfo=TZ)), '2026-10-08')

    def test_failures_persist_daily_checkpoint_before_duplicate_alert_guard(self):
        events=[]
        with patch('run.persist',side_effect=lambda:events.append('persist')), patch('run.send_once',side_effect=lambda *a,**k:events.append('send') or 'already_sent'):
            failure()
        self.assertEqual(events,['persist','send'])

if __name__=='__main__':unittest.main()
