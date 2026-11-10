import json
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import raider


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=raider.ROOT)
        self.store = raider.Store(Path(self.temp.name) / 'test.sqlite')

    def tearDown(self):
        self.temp.cleanup()

    def test_calendar_month_end_and_leap_year(self):
        self.assertEqual(raider.months_ago(datetime(2024, 5, 31)).date().isoformat(), '2024-02-29')
        self.assertEqual(raider.months_ago(datetime(2026, 5, 31)).date().isoformat(), '2026-02-28')

    def test_korean_dates_and_inclusive_end(self):
        with patch('raider.now',return_value=datetime(2026,11,11,tzinfo=raider.UTC)):
            a,b = raider.window('2026-08-09','2026-11-09')
        self.assertEqual(a.isoformat(),'2026-08-08T15:00:00+00:00')
        self.assertEqual(b.isoformat(),'2026-11-09T15:00:00+00:00')
        with self.assertRaises(ValueError):
            raider.window('2026-11-10','2026-11-09')

    def test_all_accounts_and_no_duplicate_handles(self):
        rows=raider.accounts()
        self.assertGreaterEqual(len(rows),1)
        self.assertEqual(len({(a['platform'],a['handle'].lower()) for a in rows}),len(rows))

    def test_x_day_slices_have_no_gaps(self):
        with patch('raider.now',return_value=datetime(2026,11,11,tzinfo=raider.UTC)):
            a,b=raider.window('2026-11-08','2026-11-09')
        run=self.store.create_run([{'platform':'x','handle':'example'}],a,b)
        tasks=self.store.tasks(run)
        self.assertEqual(len(tasks),3)
        self.assertEqual(tasks[0]['slice_start'],a.isoformat())
        self.assertEqual(tasks[-1]['slice_end'],b.isoformat())
        for left,right in zip(tasks,tasks[1:]):
            self.assertEqual(left['slice_end'],right['slice_start'])

    def post(self,id='1'):
        return dict(platform='instagram',post_id=id,handle='test',url='https://www.instagram.com/p/test/',
                    posted_at='2026-11-09T00:00:00+00:00',text='hello',metrics={'likes':None},media=[],raw={})

    def test_upsert_preserves_null_and_updates_reactions(self):
        p=self.post()
        self.store.save(p)
        self.assertIsNone(self.store.rows()['items'][0]['metrics']['likes'])
        p['metrics']['likes']=12
        self.store.save(p)
        self.assertEqual(self.store.rows()['total'],1)
        self.assertEqual(self.store.rows()['items'][0]['metrics']['likes'],12)

    def test_resume_replays_failed_account_without_duplicate_posts(self):
        a,b=raider.window('2026-11-01','2026-11-09')
        run=self.store.create_run([{'platform':'instagram','handle':'test'}],a,b)
        runner=raider.Runner(self.store)
        def failing(*args):
            yield self.post()
            raise RuntimeError('secret-cookie-do-not-log')
        with patch('raider.instagram',failing):
            runner.work(run)
        self.assertEqual(self.store.tasks(run)[0]['state'],'error')
        self.assertNotIn('secret-cookie',self.store.tasks(run)[0]['message'])
        def working(*args):
            yield self.post()
            yield self.post('2')
        with patch('raider.instagram',working):
            runner.work(run)
        self.assertEqual(self.store.tasks(run)[0]['state'],'queried')
        self.assertEqual(self.store.rows()['total'],2)
        with patch('raider.instagram',side_effect=AssertionError('Completed task must be skipped')):
            runner.work(run)

    def test_restart_marks_running_jobs_interrupted(self):
        a,b=raider.window('2026-11-01','2026-11-09')
        run=self.store.create_run([{'platform':'instagram','handle':'test'}],a,b)
        self.store.run_state(run,'running')
        self.store.task(self.store.tasks(run)[0],'running',2)
        raider.Runner(self.store)
        self.assertEqual(self.store.tasks(run)[0]['state'],'interrupted')

    def test_instagram_does_not_stop_at_old_pinned_post(self):
        from types import SimpleNamespace
        a,b=raider.window('2026-11-01','2026-11-09')
        def post(date,id):
            return SimpleNamespace(date_utc=datetime.fromisoformat(date),url='https://example.com/a',
                is_video=False,typename='GraphImage',mediaid=id,shortcode=str(id),caption='text',likes=1,comments=0)
        posts=[post('2020-01-01',1),post('2026-11-02',2),post('2026-12-01',3)]
        fake=SimpleNamespace(Instaloader=lambda **kw:SimpleNamespace(context=None,load_session_from_file=lambda *a:None),
            Profile=SimpleNamespace(from_username=lambda *args:SimpleNamespace(get_posts=lambda:iter(posts))))
        private=Path(self.temp.name)
        (private/'instagram.json').write_text(json.dumps({'username':'me'}))
        with patch('raider.PRIVATE',private),patch.dict('sys.modules',{'instaloader':fake}):
            result=list(raider.instagram({'handle':'test'},a,b,threading.Event()))
        self.assertEqual([r['post_id'] for r in result],['2'])


if __name__=='__main__':
    unittest.main()
