import json
import tempfile
import threading
import unittest
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

import raider
import source_agents as sa
from source_tools import public_url,Cancelled


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=raider.ROOT)
        self.root=Path(self.temp.name)
        self.store=raider.Store(self.root/'db.sqlite')
        self.config=raider.ROOT/'config/other_sources.json'
        self.settings=dict(start='2026-08-10',end='2026-11-10',limit=10,pages=2,max_mb=1,download_media=False,browser=False)

    def tearDown(self):
        self.temp.cleanup()

    def item(self,id='1'):
        return sa.post('news',id,'site','https://example.com/'+id,'AI news','marketing workflow',datetime(2026,11,1,tzinfo=timezone.utc))

    def test_dates_preserve_unknown_and_korean_end_day(self):
        self.assertTrue(sa.in_window(sa.date_value('2026-11-10 23:59:59'),self.settings))
        self.assertFalse(sa.in_window(sa.date_value('2026-11-11 00:00:00'),self.settings))
        self.assertTrue(sa.in_window(None,self.settings))
        self.assertIsNone(sa.date_value('unknown'))
        item=sa.post('news','undated','site','https://example.com','x','body')
        self.assertEqual(item['posted_at'],'')
        self.assertTrue(item['raw']['date_unknown'])

    def test_worker_resume_keeps_partial_items_and_skips_completed_targets(self):
        calls=[]
        def failing(target,settings,stop):
            calls.append(target)
            yield self.item()
            raise RuntimeError('secret-token')
        agent=sa.SourceAgent('news',self.store,self.root,self.config,adapter=NS(collect=failing))
        run=agent.start({'targets':['https://example.com/rss'],**self.settings});agent.thread.join(5)
        self.assertEqual(agent.status(run)['jobs'][0]['state'],'error')
        self.assertNotIn('secret-token',json.dumps(agent.status(run)))
        self.assertEqual(self.store.rows('news')['total'],1)
        agent.adapter.collect=lambda *args:iter([self.item(),self.item('2')])
        agent.start(run_id=run);agent.thread.join(5)
        self.assertEqual(agent.status(run)['jobs'][0]['state'],'queried')
        self.assertEqual(self.store.rows('news')['total'],2)
        agent.adapter.collect=lambda *args:(_ for _ in ()).throw(AssertionError('should skip'))
        agent.start(run_id=run);agent.thread.join(5)
        self.assertEqual(agent.status(run)['jobs'][0]['state'],'queried')

    def test_sources_are_independent_and_invalid_range_rejected(self):
        news=sa.SourceAgent('news',self.store,self.root,self.config)
        gallery=sa.SourceAgent('gallery',self.store,self.root,self.config)
        with self.assertRaises(ValueError):
            news.settings({'targets':[]})
        with self.assertRaises(ValueError):
            news.settings({'start':'2026-12-01','end':'2026-01-01'})
        with self.assertRaises(ValueError):
            news.settings({'limit':10001})
        self.assertEqual(gallery.status()['runs'],[])

    def test_news_rss_body_and_image_remain_one_item(self):
        xml=b'<rss version="2.0"><channel><title>News</title><item><title>AI release</title><link>https://example.com/article</link><pubDate>Mon, 09 Nov 2026 00:00:00 GMT</pubDate><description>summary</description></item></channel></rss>'
        page='<html><head><title>AI release</title></head><body><article><h1>AI release</h1><p>'+('A new artificial intelligence tool supports marketing work. '*20)+'</p><img src="/photo.jpg"></article></body></html>'
        with patch('source_agents.fetch',return_value=(xml,'application/xml','https://example.com/rss')),patch('source_agents.get_html',return_value=(page,'https://example.com/article')):
            items=list(sa.NewsExtractor(self.root).collect('https://example.com/rss',self.settings,threading.Event()))
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]['media'][0]['url'],'https://example.com/photo.jpg')
        self.assertIn('artificial intelligence',items[0]['text'])

    def test_news_failure_retains_feed_summary_and_error(self):
        extractor=sa.NewsExtractor(self.root)
        with patch('source_agents.get_html',side_effect=OSError('secret')):
            item=extractor.article('https://example.com/a',threading.Event(),fallback={'title':'title','text':'feed summary','date':None})
        self.assertIn('feed summary',item['text'])
        self.assertEqual(item['raw']['errors'][0]['step'],'article')

    def test_gallery_parser_pagination_id_and_reactions(self):
        listing='<table><tr class="ub-content"><td class="gall_tit"><a href="/mgallery/board/view/?id=ai_utilize&no=123">AI tool</a></td><td class="gall_date" title="2026-11-09 12:00:00"></td><td class="gall_count">1,234</td><td class="gall_recommend">5</td></tr></table>'
        article='<h3 class="title_subject">AI tool</h3><div class="write_div">useful text<img src="https://image.dcinside.com/a.png"></div>'
        with patch('source_agents.get_html',side_effect=[(listing,'https://gall.dcinside.com/mgallery/board/lists/'),(article,'https://gall.dcinside.com/mgallery/board/view/?id=ai_utilize&no=123')]):
            settings={**self.settings,'limit':1}
            items=list(sa.GalleryExtractor(self.root).collect('https://gall.dcinside.com/mgallery/board/lists/?id=ai_utilize',settings,threading.Event()))
        self.assertEqual(items[0]['post_id'],'ai_utilize-123')
        self.assertEqual(items[0]['metrics']['views'],1234)
        self.assertEqual(len(items[0]['media']),1)

    def test_browser_is_only_fallback_after_public_request_fails(self):
        with patch('source_agents.html',side_effect=[OSError('blocked'),('rendered','https://example.com')]) as browser:
            self.assertEqual(sa.get_html('https://example.com',threading.Event(),True)[0],'rendered')
            self.assertEqual(browser.call_args.kwargs,{'browser':True})

    def test_private_network_urls_are_rejected(self):
        with patch('source_tools.socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(ValueError):
                public_url('https://localhost/test')
        with self.assertRaises(ValueError):
            public_url('file:///private')

    def test_cancelled_target_is_resumable(self):
        def collect(*args):
            raise Cancelled()
            yield
        agent=sa.SourceAgent('news',self.store,self.root,self.config,adapter=NS(collect=collect))
        run=agent.start({'targets':['https://example.com'],**self.settings});agent.thread.join(5)
        self.assertEqual(agent.status(run)['jobs'][0]['state'],'interrupted')

    def test_huggingface_documents_and_file_inventory_grouped(self):
        info=NS(private=False,last_modified=datetime(2026,11,1,tzinfo=timezone.utc),sha='a'*40,
                siblings=[NS(rfilename='README.md',size=10),NS(rfilename='weights.safetensors',size=100000)],likes=20,downloads=100,tags=['text-generation'])
        api=NS(repo_info=lambda *a,**kw:info)
        with patch('huggingface_hub.HfApi',return_value=api),patch('source_agents.fetch',return_value=(b'# Local card','text/plain','https://huggingface.co/a/b')):
            items=list(sa.HuggingFaceExtractor(self.root).collect('model:a/b',self.settings,threading.Event()))
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]['post_id'],'model:a/b')
        self.assertEqual(len(items[0]['raw']['files']),2)
        self.assertEqual(len(items[0]['raw']['documents']),1)
        self.assertEqual(list((self.root/'source-files').rglob('*.safetensors')),[])

    def test_youtube_subtitles_metadata_and_file_remain_one_video(self):
        id='abcdefghijk'
        info=dict(id=id,title='AI tool',description='body',channel_id='channel',timestamp=1793491200,like_count=20,
                  subtitles={'ko':[{'ext':'json3','url':'https://www.youtube.com/api/timedtext'}]})
        class FakeYDL:
            def __init__(self,opts): self.opts=opts
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def extract_info(self,url,download=False):
                if self.opts.get('extract_flat'):
                    return {'entries':[{'id':id}]}
                if download:
                    path=Path(self.opts['outtmpl'].replace('%(ext)s','mp4'))
                    path.write_bytes(b'fixture')
                return info
            def prepare_filename(self,downloaded):
                return self.opts['outtmpl'].replace('%(ext)s','mp4')
        subtitles=json.dumps({'events':[{'tStartMs':1000,'segs':[{'utf8':'한국어 자막'}]}]}).encode()
        with patch('yt_dlp.YoutubeDL',FakeYDL),patch('source_agents.fetch',return_value=(subtitles,'application/json','')):
            items=list(sa.YoutubeExtractor(self.root).collect('https://www.youtube.com/@OpenAI/videos',{**self.settings,'download_media':True},threading.Event()))
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]['post_id'],id)
        self.assertIn('한국어 자막',items[0]['text'])
        self.assertEqual(items[0]['media'][0]['status'],'downloaded')
        self.assertEqual(items[0]['raw']['subtitles'][0]['start'],1)

    def test_media_download_failure_does_not_erase_raw_text(self):
        item=self.item();item['media']=[{'kind':'image','url':'https://example.com/a.jpg'}]
        adapter=NS(collect=lambda *args:iter([item]))
        agent=sa.SourceAgent('news',self.store,self.root,self.config,adapter=adapter)
        def failed(post,*args):
            post['media'][0]['status']='error'
            return post
        with patch('source_agents.save_media',side_effect=failed):
            run=agent.start({'targets':['https://example.com'],**self.settings,'download_media':True});agent.thread.join(5)
        self.assertIn('marketing workflow',self.store.rows('news')['items'][0]['text'])
        self.assertEqual(agent.status(run)['jobs'][0]['state'],'needs_attention')
