import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

import raider
from source_manager import Registry, parse_handles
from media_store import download_media, validate_url, x_media


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=raider.ROOT)
        self.root=Path(self.temp.name)
        (self.root/'config').mkdir()
        (self.root/'config/sources.json').write_text(json.dumps({'accounts':[]}),encoding='utf-8')
        self.registry=Registry(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_bulk_boundaries_duplicates_and_invalid(self):
        result=parse_handles('instagram','@first@second\n@FIRST, https://instagram.com/third/ a@b.com @bad-name')
        self.assertEqual(result['handles'],['first','second','third'])
        self.assertEqual(result['repeated'],['FIRST'])
        self.assertEqual(result['invalid'],['a@b.com','@bad-name'])
        self.assertTrue(parse_handles('x','https://instagram.com/first')['invalid'])

    def test_platform_categories_persist_and_duplicates_keep_category(self):
        self.registry.add_category('instagram','건강 AI')
        self.assertNotIn('건강 AI',self.registry.categories()['x'])
        self.registry.add('instagram','@same @second','건강 AI')
        self.registry.add('x','@same','공식 발표')
        self.registry.add('instagram','@SAME','미분류')
        self.assertEqual(len(self.registry.accounts()),3)
        self.assertEqual(self.registry.accounts()[0]['category'],'건강 AI')
        self.registry.assign('instagram','same','AI 소식')
        self.assertEqual(Registry(self.root).accounts()[0]['category'],'AI 소식')
        with self.assertRaises(ValueError):
            self.registry.assign('x','same','건강 AI')

    def test_invalid_batch_is_not_partially_saved(self):
        with self.assertRaises(ValueError):
            self.registry.add('x','@valid @bad-name')
        self.assertEqual(self.registry.accounts(),[])


class Response(io.BytesIO):
    def __init__(self,data,length=None,mime='image/jpeg'):
        super().__init__(data)
        self.headers={'Content-Type':mime,'Content-Length':str(len(data) if length is None else length)}


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=raider.ROOT)
        self.root=Path(self.temp.name)
        self.post=dict(platform='instagram',handle='test',post_id='123',media=[{'url':'https://s.cdninstagram.com/a.jpg','kind':'image'}])

    def tearDown(self):
        self.temp.cleanup()

    def test_download_cache_and_sha256(self):
        opener=NS(open=lambda *a,**kw:Response(b'image-data'))
        result=download_media(self.post,self.root,threading.Event(),opener=opener)[0]
        self.assertEqual(result['status'],'downloaded')
        self.assertEqual(len(result['sha256']),64)
        self.assertEqual((self.root/result['local_path']).read_bytes(),b'image-data')
        opener=NS(open=lambda *a,**kw:self.fail('cached asset was downloaded twice'))
        self.assertEqual(download_media(self.post,self.root,threading.Event(),opener=opener)[0]['status'],'downloaded')

    def test_truncation_size_and_wrong_content_leave_no_partial_file(self):
        for response,limit in [(Response(b'x',10),100),(Response(b'xx'),1),(Response(b'<html>',mime='text/html'),100)]:
            result=download_media(self.post,self.root,threading.Event(),max_bytes=limit,opener=NS(open=lambda *a,**kw:response))[0]
            self.assertEqual(result['status'],'error')
            self.assertEqual(list(self.root.rglob('*.part')),[])
            self.assertEqual(list(self.root.rglob('*.jpg')),[])

    def test_url_restrictions_and_stop(self):
        for url in ['http://pbs.twimg.com/a','https://localhost/a','https://twimg.com.evil.test/a','https://u:p@pbs.twimg.com/a','https://pbs.twimg.com:8443/a']:
            with self.assertRaises(ValueError):
                validate_url(url)
        stop=threading.Event();stop.set()
        self.assertEqual(download_media(self.post,self.root,stop)[0]['status'],'interrupted')

    def test_x_highest_quality_mp4_and_animation(self):
        media=NS(photos=[NS(url='photo')],videos=[NS(thumbnailUrl='thumb',variants=[NS(contentType='video/mp4',bitrate=1,url='small'),NS(contentType='video/mp4',bitrate=9,url='large')])],animated=[NS(videoUrl='gif.mp4',thumbnailUrl='gif.jpg')])
        self.assertEqual([a['url'] for a in x_media(media)],['photo','large','thumb','gif.mp4','gif.jpg'])

    def test_media_failure_preserves_post_and_resume_retries(self):
        store=raider.Store(self.root/'db.sqlite')
        a,b=raider.window('2026-11-01','2026-11-09')
        run=store.create_run([{'platform':'instagram','handle':'test'}],a,b,True)
        runner=raider.Runner(store)
        post=dict(self.post,url='https://instagram.com/p/example/',posted_at='2026-11-02T00:00:00+00:00',text='keep me',metrics={},raw={})
        with patch('raider.instagram',lambda *args:iter([post])),patch('raider.download_media',return_value=[{'status':'error'}]):
            runner.work(run)
        self.assertEqual(store.rows()['items'][0]['text'],'keep me')
        self.assertEqual(store.tasks(run)[0]['state'],'queried_media_errors')
        with patch('raider.instagram',lambda *args:iter([post])),patch('raider.download_media',return_value=[{'status':'downloaded'}]):
            runner.work(run)
        self.assertEqual(store.tasks(run)[0]['state'],'queried')
        self.assertEqual(store.rows()['total'],1)
