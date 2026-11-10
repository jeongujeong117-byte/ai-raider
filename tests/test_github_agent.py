import io
import json
import tempfile
import threading
import unittest
import zipfile
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

import raider
import github_agent as gh

SHA='a'*40


def fake_repo(name='owner/ai-skills',id=1):
    return NS(id=id,full_name=name,html_url='https://github.com/'+name,private=False,description='AI agent skills for marketing sales',
              stargazers_count=3000,forks_count=200,language='Python',topics=['agent-skills'],created_at=datetime(2020,1,1,tzinfo=timezone.utc),
              pushed_at=datetime(2026,11,10,tzinfo=timezone.utc),archived=False,default_branch='main',size=20,license=NS(spdx_id='MIT'),
              get_commit=lambda branch:NS(sha=SHA),get_readme=lambda **kw:NS(decoded_content=b'# Marketing assistant'),get_releases=lambda:[])


class FakeClient:
    def __init__(self):
        self.queries=[]
        self.gets=[]
        self.closed=False
    def search(self,query,limit,stop):
        self.queries.append(query)
        return 5000,iter(['owner/ai-skills'][:limit])
    def get(self,name):
        self.gets.append(name)
        return fake_repo(name)
    def close(self):
        self.closed=True


class GithubTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=raider.ROOT)
        self.root=Path(self.temp.name)
        self.client=FakeClient()
        self.agent=gh.GithubAgent(self.root/'github',raider.ROOT/'config/github.json',lambda:self.client)
        self.settings=gh.options({'queries':['topic:llm'],'download_archive':False,'since':'2026-08-10'},self.agent.defaults())

    def tearDown(self):
        self.temp.cleanup()

    def test_bulk_urls_validation_and_dedup(self):
        self.assertEqual(gh.parse_repos('owner/repo, https://github.com/OWNER/REPO.git\nother/second'),['owner/repo','other/second'])
        for text in ['https://evil.test/owner/repo','owner/repo/tree/main','../repo','owner/..','owner/repo;bad']:
            with self.assertRaises(ValueError):
                gh.parse_repos(text)

    def test_options_limits_and_direct_only(self):
        for body in [{'limit_per_query':1001},{'archive_mb':0},{'min_stars':-1},{'queries':[],'repos':''},{'download_archive':'false'}]:
            with self.assertRaises(ValueError):
                gh.options(body,self.agent.defaults())
        self.assertEqual(gh.options({'queries':[],'repos':'owner/repo'},self.agent.defaults())['repos'],['owner/repo'])

    def test_two_categories_explainable_and_uncertain(self):
        self.assertEqual(gh.classify('a/b','GPU inference framework',['cuda'],'')['category'],'computing')
        self.assertEqual(gh.classify('a/b','AI sales CRM marketing',[],'')['category'],'practice')
        self.assertTrue(gh.classify('a/b','',[],'')['review_needed'])
        self.assertTrue(gh.classify('a/b','marketing framework',[],'')['review_needed'])

    def test_search_job_dedup_scope_and_resume_skips_completed(self):
        self.settings['queries']=['topic:llm','topic:ai-agents']
        run=self.agent.store.create(self.settings)
        self.agent.work(run)
        status=self.agent.status(run)
        self.assertEqual(len(status['jobs']),1)
        self.assertEqual(status['jobs'][0]['state'],'completed')
        self.assertIn('stars:>=1000 is:public fork:false',self.client.queries[0])
        self.assertNotIn('created:',self.client.queries[0])
        self.assertEqual(self.agent.store.rows()['total'],1)
        self.assertTrue(self.client.closed)
        self.agent.work(run)
        self.assertEqual(len(self.client.gets),1)
        self.assertEqual(len(self.client.queries),2)

    def test_recent_discovery_does_not_claim_growth(self):
        self.settings['mode']='recent'
        run=self.agent.store.create(self.settings);self.agent.work(run)
        self.assertIn('created:>=2026-08-10',self.client.queries[0])
        row=self.agent.store.rows()['items'][0]
        self.assertIsNone(row['growth'])
        self.assertEqual(row['skill_status'],'candidate')

    def test_star_snapshots_and_manual_category_survive_refresh(self):
        store=self.agent.store
        metadata=gh.metadata(fake_repo())
        with patch('github_agent.timestamp',return_value='2026-11-01T00:00:00+00:00'):
            store.save(metadata,{'skill_paths':['skills/test/SKILL.md']})
        store.assign(metadata['full_name'],'computing')
        metadata['stars']=3010
        with patch('github_agent.timestamp',return_value='2026-11-03T00:00:00+00:00'):
            store.save(metadata)
            metadata['stars']=3015
            store.save(metadata)
        row=store.rows()['items'][0]
        self.assertEqual(row['growth']['stars'],15)
        self.assertEqual(row['growth']['days'],2)
        self.assertEqual(row['category'],'computing')
        self.assertEqual(row['skill_status'],'confirmed')
        self.assertEqual(len(store.detail(metadata['full_name'])['snapshots']),2)
        store.assign(metadata['full_name'],'auto')
        self.assertEqual(store.rows()['items'][0]['category'],'practice')

    def test_watch_revisits_existing_repositories_without_search(self):
        self.agent.store.save(gh.metadata(fake_repo()))
        self.settings['mode']='watch'
        run=self.agent.store.create(self.settings);self.agent.work(run)
        self.assertEqual(self.client.queries,[])
        self.assertEqual(self.client.gets,['owner/ai-skills'])

    def test_rate_limit_halts_and_redacts_errors(self):
        class LimitError(Exception):
            status=429
        self.client.get=lambda name:(_ for _ in ()).throw(LimitError('secret-token-value'))
        self.settings.update(queries=[],repos=['owner/first','owner/second'])
        run=self.agent.store.create(self.settings);self.agent.work(run)
        state=self.agent.status(run)
        self.assertEqual(state['runs'][0]['state'],'rate_limited')
        self.assertEqual([j['state'] for j in state['jobs']],['rate_limited','pending'])
        self.assertNotIn('secret-token',json.dumps(state))

    def test_stop_and_restart_recovery(self):
        run=self.agent.store.create(self.settings)
        self.agent.stop.set();self.agent.work(run)
        self.assertEqual(self.agent.status(run)['runs'][0]['state'],'stopped')
        with self.agent.store.connect() as db:
            db.execute("UPDATE runs SET state='running'")
        recovered=gh.GithubAgent(self.root/'github',self.agent.config)
        self.assertEqual(recovered.status(run)['runs'][0]['state'],'interrupted')

    def make_zip(self,files):
        path=self.root/'fixture.zip'
        with zipfile.ZipFile(path,'w') as archive:
            for name,text in files.items():
                info=zipfile.ZipInfo('placeholder')
                info.filename=name  # Windows ZipInfo constructor otherwise normalizes backslashes.
                archive.writestr(info,text)
        return path

    def test_archive_inventory_skill_order_and_bounded_documents(self):
        path=self.make_zip({'repo-sha/README.md':'# GPU framework','repo-sha/skills/a/SKILL.md':'# Sales skill',
                            'repo-sha/src/main.py':'print(1)','repo-sha/docs/long.md':'x'*300000})
        result=gh.read_archive(path,threading.Event())
        self.assertEqual(result['file_count'],4)
        self.assertEqual(result['skill_paths'],['skills/a/SKILL.md'])
        self.assertEqual(result['readme'],'# GPU framework')
        self.assertTrue(result['documents'][-1]['truncated'])
        self.assertEqual(len(result['documents']),3)
        self.assertFalse((self.root/'src').exists())

    def test_unsafe_zip_members_rejected_without_extraction(self):
        for name in ['repo/../../escape','/absolute/path','repo/C:/file','repo\\..\\..\\escape']:
            with self.assertRaises(ValueError):
                gh.read_archive(self.make_zip({name:'bad'}),threading.Event())

    def test_zip_download_size_partial_cleanup_and_cache(self):
        payload=self.make_zip({'repo/README.md':'hello'}).read_bytes()
        class Response(io.BytesIO):
            headers={'Content-Length':str(len(payload))}
        opener=NS(open=lambda *a,**kw:Response(payload))
        root=self.root/'archives'
        with self.assertRaises(ValueError):
            gh.download_archive('owner/repo',SHA,root,1,threading.Event(),opener)
        self.assertEqual(list(root.rglob('*.part')),[])
        path=gh.download_archive('owner/repo',SHA,root,10000,threading.Event(),opener)
        self.assertTrue(path.is_file())
        with patch.object(opener,'open',side_effect=AssertionError('cache should be used')):
            self.assertEqual(gh.download_archive('owner/repo',SHA,root,10000,threading.Event(),opener),path)

    def test_archive_validation_and_release_filter_group_under_repo(self):
        path=self.make_zip({'repo/README.md':'AI marketing','repo/skills/SKILL.md':'Instructions'})
        self.settings['download_archive']=True
        self.agent.store.root.mkdir(exist_ok=True)
        target=self.agent.store.root/'archives/test.zip';target.parent.mkdir();target.write_bytes(path.read_bytes())
        repo=fake_repo()
        def release(id,date):
            return NS(id=id,tag_name='v'+str(id),title='Release',body='notes',html_url=repo.html_url+'/releases/tag/v'+str(id),
                      published_at=datetime.fromisoformat(date),created_at=None,prerelease=False)
        repo.get_releases=lambda:[release(1,'2020-01-01T00:00:00+00:00'),release(2,'2026-10-01T00:00:00+00:00')]
        with patch('github_agent.download_archive',return_value=target):
            detail=self.agent.collect(repo,self.settings)
        self.agent.store.save(gh.metadata(repo),detail)
        saved=self.agent.store.detail(repo.full_name)
        self.assertEqual(saved['commit_sha'],SHA)
        self.assertEqual(saved['skill_paths'],['skills/SKILL.md'])
        self.assertEqual([r['id'] for r in saved['releases']],[2])
        self.assertEqual(len(saved['archive']['sha256']),64)

    def test_archive_url_redirect_allowlist(self):
        for url in ['http://codeload.github.com/a','https://codeload.github.com.evil.test/a','https://localhost/a','https://u:p@codeload.github.com/a']:
            with self.assertRaises(ValueError):
                gh.validate_archive_url(url)
