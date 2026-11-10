"""Run against an isolated temporary store; no social network requests."""
import json
import re
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import raider
from source_manager import Registry
from test_github_agent import FakeClient

with tempfile.TemporaryDirectory(dir=raider.ROOT) as folder:
    root=Path(folder)
    (root/'config').mkdir()
    (root/'config/sources.json').write_bytes((raider.ROOT/'config/sources.json').read_bytes())
    registry=Registry(root)
    initial_count=len(registry.accounts())
    made=[]
    server_class=raider.ThreadingHTTPServer
    agent_class=raider.GithubAgent
    source_class=raider.SourceAgent
    def fake_source(kind,*args):
        from types import SimpleNamespace
        def collect(target,settings,stop):
            yield dict(platform=kind,post_id='fixture',handle='fixture',url='https://example.com/'+kind,
                       posted_at='2026-11-09T00:00:00+00:00',text='source body',metrics={},media=[],raw={'title':'source fixture'})
        return source_class(kind,*args,adapter=SimpleNamespace(collect=collect))
    def capture(address,handler):
        server=server_class(address,handler)
        made.append(server)
        return server
    with patch('raider.DATA',root),patch('raider.Registry',lambda _:registry),patch('raider.ThreadingHTTPServer',capture),patch('raider.GithubAgent',lambda *args:agent_class(*args,client_factory=FakeClient)),patch('raider.SourceAgent',fake_source):
        thread=threading.Thread(target=raider.serve,args=(18765,),daemon=True)
        thread.start()
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        base='http://127.0.0.1:18765'
        try:
            for _ in range(40):
                try:
                    page=opener.open(base,timeout=1).read().decode()
                    break
                except (OSError,urllib.error.URLError):
                    time.sleep(.1)
            else:
                raise AssertionError('Server did not become ready')
            token=re.search("const token='([^']+)'",page).group(1)
            assert '__TOKEN__' not in page
            state=json.load(opener.open(base+'/api/state',timeout=3))
            assert len(state['accounts'])==initial_count
            assert json.load(opener.open(base+'/api/posts',timeout=3))['total']==0
            assert opener.open(base+'/export?format=csv',timeout=3).status==200
            def post(path,body,headers,expected):
                req=urllib.request.Request(base+path,json.dumps(body).encode(),headers,method='POST')
                try:
                    response=opener.open(req,timeout=3)
                    assert response.status==expected
                    return json.load(response)
                except urllib.error.HTTPError as e:
                    assert e.code==expected,(e.code,expected)
            post('/api/start',{'accounts':[]},{},403)
            post('/api/start',{'accounts':[]},{'X-Raider-Token':token},400)
            post('/api/resume',{'run_id':'missing'},{'X-Raider-Token':token},400)
            headers={'X-Raider-Token':token}
            result=post('/api/accounts/preview',{'platform':'instagram','text':'@ai.asap.kr @testnewone@testnewtwo'},headers,200)
            assert len(result['new'])==2 and result['existing']==['ai.asap.kr']
            post('/api/accounts/add',{'platform':'instagram','text':'@good @bad-name'},headers,400)
            post('/api/categories/add',{'platform':'instagram','name':'테스트 분류'},headers,200)
            post('/api/accounts/add',{'platform':'instagram','text':'@testnewone@testnewtwo','category':'테스트 분류'},headers,200)
            state=json.load(opener.open(base+'/api/state'))
            assert len(state['accounts'])==initial_count+2
            assert '테스트 분류' not in state['categories']['x']
            post('/api/accounts/category',{'platform':'instagram','handle':'testnewone','category':'AI 소식'},headers,200)
            assert json.load(opener.open(base+'/api/posts?platform=instagram&category=AI%20%EC%86%8C%EC%8B%9D'))['total']==0
            try:
                opener.open(base+'/media/%2e%2e/raider.sqlite')
                raise AssertionError('Traversal permitted')
            except urllib.error.HTTPError as error:
                assert error.code==404
            saved=raider.Store(root/'raider.sqlite')
            saved.save(dict(platform='instagram',post_id='local-fixture',handle='ai.asap.kr',text='original body',
                            url='https://instagram.com/p/test/',posted_at='2026-11-09T00:00:00+00:00',metrics={},media=[],raw={}))
            post('/api/processing/retry',{'platform':'instagram','post_id':'local-fixture'},headers,200)
            for _ in range(40):
                item=json.load(opener.open(base+'/api/posts'))['items'][0]
                if item['processing']['state']=='completed':
                    break
                time.sleep(.1)
            assert item['processing']['state']=='completed'
            assert item['processing']['post_key']=='instagram:local-fixture'
            assert item['processing']['combined_text']=='original body'
            exported=json.load(opener.open(base+'/export'))
            assert exported['items'][0]['processing']['post_key']=='instagram:local-fixture'
            github_page=opener.open(base+'/github').read().decode()
            assert '__TOKEN__' not in github_page and 'GitHub' in github_page
            post('/api/github/start',{}, {},403)
            post('/api/github/start',{'queries':[],'repos':'bad-name'},headers,400)
            result=post('/api/github/start',{'queries':[],'repos':'owner/ai-skills','download_archive':False},headers,200)
            for _ in range(60):
                state=json.load(opener.open(base+'/api/github/state'))
                if not state['busy']:
                    break
                time.sleep(.1)
            assert state['jobs'][0]['state']=='completed',state
            rows=json.load(opener.open(base+'/api/github/repos'))
            assert rows['total']==1 and rows['items'][0]['stars']==3000
            detail=json.load(opener.open(base+'/api/github/repo?name=owner/ai-skills'))
            assert detail['commit_sha']=='a'*40 and detail['readme']=='# Marketing assistant'
            post('/api/github/category',{'name':'owner/ai-skills','category':'computing'},headers,200)
            assert json.load(opener.open(base+'/api/github/repos?category=computing'))['total']==1
            exported=json.load(opener.open(base+'/api/github/export'))
            assert exported['items'][0]['full_name']=='owner/ai-skills'
            assert 'snapshots' in exported['items'][0]
            assert '__TOKEN__' not in opener.open(base+'/sources').read().decode()
            for kind in ['youtube','news','huggingface','gallery']:
                post('/api/sources/start',{'kind':kind,'targets':['https://example.com'],'download_media':False},headers,200)
                for _ in range(50):
                    source=json.load(opener.open(base+'/api/sources/state?kind='+kind))
                    if not source['busy']:
                        break
                    time.sleep(.1)
                assert source['jobs'][0]['state']=='queried',(kind,source)
                rows=json.load(opener.open(base+'/api/posts?platform='+kind))
                assert rows['total']==1 and rows['items'][0]['text']=='source body'
            post('/api/sources/start',{'kind':'unknown'},headers,400)
            print('PASS: all source pages, independent agents, collection/resume routes, categories, processing/export and CSRF')
        finally:
            if made:
                made[0].shutdown()
                thread.join(timeout=5)
