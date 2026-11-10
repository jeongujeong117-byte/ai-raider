import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

import raider
from post_processing import Processor, NotReady, Stopped, fingerprint, local_file, process_post


class ProcessingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=raider.ROOT)
        self.data=Path(self.temp.name)
        self.root=self.data/'media'
        self.root.mkdir()
        for name in ('a.jpg','b.jpg','c.mp4'):
            (self.root/name).write_bytes(b'fixture')
        self.post=dict(platform='instagram',post_id='1',handle='test',text='original caption',
                       url='https://instagram.com/p/example/',posted_at='2026-11-09T00:00:00+00:00',metrics={},raw={},
                       media=[dict(kind=kind,status='downloaded',local_path=path) for kind,path in
                              [('image','a.jpg'),('image','b.jpg'),('video','c.mp4')]])
        self.calls=[]
        def track(name,value):
            def method(path,stop):
                self.calls.append((name,path.name))
                return value
            return method
        self.engines=NS(classify=lambda p:'video' if p.suffix=='.mp4' else 'image',
            ocr=track('ocr',{'text':'image words'}),transcribe=track('asr',{'text':'spoken words','segments':[{'start':0,'end':2,'text':'spoken words'}]}),
            frames=track('frames',{'samples':[{'seconds':0,'text':'screen words'}],'sampling_seconds':5,'truncated':False}))

    def tearDown(self):
        self.temp.cleanup()

    def test_mixed_carousel_keeps_one_parent_and_ordered_tool_results(self):
        result=process_post(self.post,self.root,self.engines,threading.Event())
        self.assertEqual(result['post_key'],'instagram:1')
        self.assertEqual(result['types'],['image','text','video'])
        self.assertEqual([a['index'] for a in result['assets']],[0,1,2])
        self.assertEqual(self.calls,[('ocr','a.jpg'),('ocr','b.jpg'),('asr','c.mp4'),('frames','c.mp4')])
        self.assertIn('original caption',result['combined_text'])
        self.assertIn('spoken words',result['combined_text'])
        self.assertEqual(result['state'],'completed')

    def test_speech_failure_does_not_block_video_ocr_or_other_assets(self):
        self.engines.transcribe=lambda *a:(_ for _ in ()).throw(NotReady('model missing'))
        result=process_post(self.post,self.root,self.engines,threading.Event())
        video=result['assets'][2]
        self.assertEqual(video['steps']['transcript']['state'],'blocked')
        self.assertEqual(video['steps']['frame_ocr']['state'],'completed')
        self.assertIn('screen words',result['combined_text'])
        self.assertEqual(result['state'],'needs_attention')

    def test_actual_type_overrides_source_hint_and_download_errors_are_retained(self):
        self.post['media'][1]['status']='error'
        self.post['media'][2]['kind']='image'
        result=process_post(self.post,self.root,self.engines,threading.Event())
        self.assertEqual(result['types'],['image','text','video'])
        self.assertEqual(result['assets'][1]['state'],'waiting_media')
        self.assertEqual(result['assets'][2]['detected_type'],'video')

    def test_text_only_and_stop(self):
        self.post['media']=[]
        result=process_post(self.post,self.root,self.engines,threading.Event())
        self.assertEqual(result['types'],['text'])
        self.assertEqual(result['state'],'completed')
        self.post['media']=[dict(kind='image',status='downloaded',local_path='a.jpg')]
        stop=threading.Event();stop.set()
        with self.assertRaises(Stopped):
            process_post(self.post,self.root,self.engines,stop)

    def test_local_file_cannot_escape_media_root(self):
        with self.assertRaises(ValueError):
            local_file(self.root,'../outside')

    def test_queue_dedup_preserves_results_on_recrawl_and_platform_isolation(self):
        store=raider.Store(self.data/'test.sqlite')
        processor=Processor(store,self.data)
        processor.engines=self.engines
        store.save(self.post)
        self.assertTrue(processor.enqueue(self.post))
        self.assertFalse(processor.enqueue(self.post))
        self.assertTrue(processor.run_one())
        result=store.rows()['items'][0]['processing']
        self.assertEqual(result['state'],'completed')
        store.save(self.post)
        self.assertEqual(store.rows()['items'][0]['processing'],result)
        self.assertFalse(processor.enqueue(self.post))
        other=dict(self.post,platform='x')
        store.save(other)
        self.assertEqual(store.rows('x')['items'][0]['processing']['state'],'not_queued')
        self.assertTrue(processor.enqueue(other))
        self.assertTrue(processor.run_one())
        self.assertEqual(store.rows()['total'],2)
        self.assertTrue(processor.enqueue(self.post,force=True))

    def test_input_changes_invalidate_cache_and_stale_job_cannot_overwrite(self):
        store=raider.Store(self.data/'test.sqlite')
        processor=Processor(store,self.data)
        store.save(self.post);processor.enqueue(self.post)
        old=dict(platform='instagram',post_id='1',fingerprint=fingerprint(self.post,self.root))
        changed=dict(self.post,text='updated caption')
        store.save(changed);self.assertTrue(processor.enqueue(changed))
        processor.update(old,'completed',{'combined_text':'stale'})
        self.assertEqual(store.rows()['items'][0]['processing'],{'state':'queued'})

    def test_restart_requeues_interrupted_processing(self):
        store=raider.Store(self.data/'test.sqlite')
        processor=Processor(store,self.data)
        store.save(self.post);processor.enqueue(self.post)
        with store.connect() as db:
            db.execute("UPDATE processing SET state='running'")
        Processor(store,self.data)
        self.assertEqual(store.rows()['items'][0]['processing']['state'],'queued')
