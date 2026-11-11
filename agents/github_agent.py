"""Independent, read-only public GitHub collection agent backed by PyGithub.

Repository snapshots are data: no clone hooks, imports, installs or code execution.
"""
import hashlib
import io
import json
import os
import re
import sqlite3
import threading
import uuid
import zipfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from itertools import islice
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse
from urllib.request import Request, HTTPRedirectHandler, build_opener

UTC=timezone.utc
KST=timezone(timedelta(hours=9))
CATEGORIES={'computing':'컴퓨팅 기술','practice':'분야별 실무 활용'}
REPO_RE=re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_.-]{1,100}')


def timestamp():
    return datetime.now(UTC).isoformat()


def parse_repos(text):
    if not isinstance(text,str) or len(text)>50000:
        raise ValueError('저장소 목록을 확인하세요.')
    valid=[]
    invalid=[]
    for token in re.split(r'[\s,;]+',text.strip()):
        if not token:
            continue
        value=token
        if token.startswith(('http://','https://')):
            url=urlparse(token)
            value=url.path.strip('/')
            if url.hostname not in ('github.com','www.github.com') or url.username or url.password:
                invalid.append(token)
                continue
        if value.endswith('.git'):
            value=value[:-4]
        if not REPO_RE.fullmatch(value) or value.split('/')[1] in ('.','..'):
            invalid.append(token)
        elif value.lower() not in {x.lower() for x in valid}:
            valid.append(value)
    if invalid:
        raise ValueError('owner/repo 또는 GitHub 저장소 주소를 확인하세요: '+', '.join(invalid[:5]))
    return valid


def options(body,defaults):
    mode=body.get('mode','baseline')
    if mode not in ('baseline','recent','watch'):
        raise ValueError('수집 모드를 확인하세요.')
    queries=body.get('queries',defaults['queries'])
    if isinstance(queries,str):
        queries=[q.strip() for q in queries.splitlines() if q.strip()]
    if not isinstance(queries,list) or len(queries)>20 or any(not isinstance(q,str) or not 1<=len(q)<=200 for q in queries):
        raise ValueError('검색식은 줄마다 하나씩, 최대 20개·각 200자로 입력하세요.')
    repos=parse_repos(body.get('repos',''))
    stars=int(body.get('min_stars',defaults['min_stars']))
    limit=int(body.get('limit_per_query',defaults['limit_per_query']))
    mb=int(body.get('archive_mb',defaults['archive_mb']))
    if not 0<=stars<=10000000 or not 1<=limit<=1000 or not 1<=mb<=4096:
        raise ValueError('스타 0~1000만, 검색식당 1~1000건, ZIP 상한 1~4096MB로 설정하세요.')
    since=body.get('since') or (datetime.now(KST)-timedelta(days=90)).date().isoformat()
    since=datetime.strptime(since,'%Y-%m-%d').date().isoformat()
    if mode!='watch' and not queries and not repos:
        raise ValueError('검색식 또는 저장소를 입력하세요.')
    download=body.get('download_archive',True)
    if not isinstance(download,bool):
        raise ValueError('파일 저장 옵션을 확인하세요.')
    return dict(mode=mode,queries=queries,repos=repos,min_stars=stars,limit_per_query=limit,
                archive_mb=mb,download_archive=download,since=since)


def classify(name,description,topics,readme):
    """Explainable provisional categories, independently editable by the user."""
    text=(' '.join([name,description or '',*topics])+' '+readme[:12000]).lower()
    practice=['marketing','sales','crm','customer support','customer service','finance','accounting',
              'legal','healthcare','education','recruitment','e-commerce','ecommerce','content creation',
              'social media','presentation','마케팅','영업','회계','법률','의료','교육','채용','쇼핑몰','콘텐츠 제작']
    computing=['framework','inference','training','fine-tuning','compiler','gpu','cuda','sdk',
               'benchmark','evaluation','mcp server','agent framework','runtime','프레임워크','추론','학습','개발 도구']
    p=[w for w in practice if re.search(r'(?<![a-z])'+re.escape(w)+r'(?![a-z])',text)]
    c=[w for w in computing if re.search(r'(?<![a-z])'+re.escape(w)+r'(?![a-z])',text)]
    category='practice' if p and (len(p)>=len(c) or not c) else 'computing'
    return {'category':category,'review_needed':bool(p and c) or not(p or c),
            'reason':{'practice_matches':p,'computing_matches':c,'method':'keyword_rules_v1'}}


def safe_error(exc):
    status=getattr(exc,'status',None)
    rate=status==429 or (status==403 and (str(getattr(exc,'headers',{}).get('x-ratelimit-remaining',''))=='0' or 'rate limit' in str(getattr(exc,'data','')).lower()))
    return {'state':'rate_limited' if rate else 'error','type':type(exc).__name__,'http_status':status,
            'message':'요청 제한입니다. 시간을 두고 이어받으세요.' if rate else '네트워크·공개 여부·설치 상태를 확인하고 이어받으세요.'}


class Stopped(Exception):
    pass


def check_stop(stop):
    if stop.is_set():
        raise Stopped()


class ArchiveRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        validate_archive_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def validate_archive_url(url):
    parsed=urlparse(url)
    if parsed.scheme!='https' or parsed.hostname!='codeload.github.com' or parsed.port not in (None,443) or parsed.username or parsed.password:
        raise ValueError('허용된 GitHub 아카이브 주소가 아닙니다.')


def download_archive(full_name,sha,root,max_bytes,stop,opener=None):
    if not REPO_RE.fullmatch(full_name) or not re.fullmatch('[0-9a-f]{40}',sha):
        raise ValueError('저장소 이름과 커밋을 확인하세요.')
    owner,name=full_name.split('/')
    root=Path(root)
    folder=root/('o-'+owner)/('r-'+name)
    folder.mkdir(parents=True,exist_ok=True)
    target=folder/(sha+'.zip')
    if target.exists():
        with zipfile.ZipFile(target) as archive:
            if not archive.infolist():
                raise ValueError('빈 아카이브입니다.')
        return target
    partial=target.with_suffix('.part')
    opener=opener or build_opener(ArchiveRedirect())
    url=f'https://codeload.github.com/{full_name}/zip/{sha}'
    validate_archive_url(url)
    try:
        with opener.open(Request(url,headers={'User-Agent':'AI-Raider/0.4','Accept':'application/zip'}),timeout=45) as response:
            expected=int(response.headers.get('Content-Length','0'))
            if expected>max_bytes:
                raise ValueError('ZIP 크기 상한을 넘었습니다.')
            size=0
            with partial.open('wb') as stream:
                while True:
                    check_stop(stop)
                    chunk=response.read(128*1024)
                    if not chunk:
                        break
                    size+=len(chunk)
                    if size>max_bytes:
                        raise ValueError('ZIP 크기 상한을 넘었습니다.')
                    stream.write(chunk)
            if not size or (expected and expected!=size):
                raise ValueError('미완료 다운로드입니다.')
        with zipfile.ZipFile(partial) as archive:
            if not archive.infolist():
                raise ValueError('빈 아카이브입니다.')
        partial.replace(target)
        return target
    finally:
        partial.unlink(missing_ok=True)


def read_archive(path,stop):
    """Inventory all ZIP members, read bounded docs. Never extract paths or execute files."""
    files=[]
    documents=[]
    warnings=[]
    skill_paths=[]
    total_text=0
    readme=''
    with zipfile.ZipFile(path) as archive:
        members=archive.infolist()
        if len(members)>100000:
            raise ValueError('파일 목록 상한 100000건을 넘었습니다.')
        for info in members:
            check_stop(stop)
            if info.is_dir():
                continue
            posix=PurePosixPath(info.filename)
            if posix.is_absolute() or '..' in posix.parts or '\\' in info.filename or ':' in info.filename:
                raise ValueError('안전하지 않은 ZIP 경로입니다.')
            relative='/'.join(posix.parts[1:])
            if not relative:
                continue
            record={'path':relative,'bytes':info.file_size,'crc':info.CRC}
            files.append(record)
            leaf=posix.name.lower()
            is_skill=leaf=='skill.md'
            if is_skill:
                skill_paths.append(relative)
            interesting=is_skill or leaf.startswith('readme') or (posix.suffix.lower() in ('.md','.rst','.txt','.ipynb') and any(p.lower() in ('docs','examples','cookbook','skills') for p in posix.parts))
            if not interesting:
                continue
            if len(documents)>=200 or total_text>=8*1024*1024 or info.file_size>2*1024*1024 or info.file_size>max(1,info.compress_size)*1000:
                warnings.append('문서 읽기 상한: '+relative)
                continue
            max_read=min(256*1024,8*1024*1024-total_text)
            with archive.open(info) as stream:
                data=stream.read(max_read+1)
            truncated=len(data)>max_read or info.file_size>max_read
            text=data[:max_read].decode('utf-8',errors='replace')
            total_text+=min(len(data),max_read)
            document={'path':relative,'text':text,'truncated':truncated,'kind':'skill' if is_skill else 'document'}
            if is_skill:
                document['classification']=classify(relative,'',[],text)
            documents.append(document)
            if leaf.startswith('readme') and ('/' not in relative or not readme):
                readme=text
    return {'files':files,'documents':documents,'skill_paths':skill_paths,'readme':readme,
            'warnings':warnings,'file_count':len(files)}


class GithubStore:
    def __init__(self,root):
        self.root=Path(root)
        self.root.mkdir(parents=True,exist_ok=True)
        self.path=self.root/'github.sqlite'
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS repositories(id INTEGER PRIMARY KEY,full_name TEXT UNIQUE COLLATE NOCASE,
              category TEXT,manual_category TEXT,metadata TEXT,detail TEXT,updated_at TEXT);
            CREATE TABLE IF NOT EXISTS snapshots(repo_id INTEGER,day TEXT,stars INTEGER,observed_at TEXT,
              PRIMARY KEY(repo_id,day));
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,options TEXT,state TEXT,created_at TEXT,message TEXT DEFAULT '');
            CREATE TABLE IF NOT EXISTS queries(run_id TEXT,query TEXT,state TEXT DEFAULT 'pending',count INTEGER DEFAULT 0,
              message TEXT DEFAULT '',PRIMARY KEY(run_id,query));
            CREATE TABLE IF NOT EXISTS jobs(run_id TEXT,full_name TEXT COLLATE NOCASE,state TEXT DEFAULT 'pending',
              message TEXT DEFAULT '',PRIMARY KEY(run_id,full_name));
            ''')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=30)
        db.row_factory=sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self,settings):
        run=uuid.uuid4().hex
        queries=[] if settings['mode']=='watch' else settings['queries']
        repos=settings['repos']
        if settings['mode']=='watch':
            repos=[r['full_name'] for r in self.rows()['items']]
            if not repos:
                raise ValueError('먼저 저장소를 수집하세요.')
        with self.connect() as db:
            db.execute('INSERT INTO runs(id,options,state,created_at) VALUES(?,?,?,?)',(run,json.dumps(settings),'pending',timestamp()))
            db.executemany('INSERT INTO queries(run_id,query) VALUES(?,?)',[(run,q) for q in dict.fromkeys(queries)])
            db.executemany('INSERT OR IGNORE INTO jobs(run_id,full_name) VALUES(?,?)',[(run,r) for r in repos])
        return run

    def save(self,metadata,detail=None):
        stamp=timestamp()
        classification=classify(metadata['full_name'],metadata['description'],metadata['topics'],(detail or {}).get('readme',''))
        with self.connect() as db:
            old=db.execute('SELECT detail FROM repositories WHERE id=?',(metadata['id'],)).fetchone()
            if detail is None and old:
                detail=json.loads(old['detail'])
                classification=classify(metadata['full_name'],metadata['description'],metadata['topics'],detail.get('readme',''))
            detail=detail or {}
            metadata={**metadata,'classification':classification}
            db.execute('''INSERT INTO repositories(id,full_name,category,metadata,detail,updated_at) VALUES(?,?,?,?,?,?)
              ON CONFLICT(id) DO UPDATE SET full_name=excluded.full_name,category=excluded.category,metadata=excluded.metadata,
              detail=excluded.detail,updated_at=excluded.updated_at''',
              (metadata['id'],metadata['full_name'],classification['category'],json.dumps(metadata,ensure_ascii=False),json.dumps(detail,ensure_ascii=False),stamp))
            day=datetime.fromisoformat(stamp).astimezone(KST).date().isoformat()
            db.execute('INSERT INTO snapshots VALUES(?,?,?,?) ON CONFLICT(repo_id,day) DO UPDATE SET stars=excluded.stars,observed_at=excluded.observed_at',
                       (metadata['id'],day,metadata['stars'],stamp))

    def rows(self,category='',skills=False,sort='stars',offset=0,limit=None):
        if category and category not in CATEGORIES:
            raise ValueError('분류를 확인하세요.')
        items=[]
        with self.connect() as db:
            records=db.execute('SELECT * FROM repositories').fetchall()
            for record in records:
                row=json.loads(record['metadata'])
                detail=json.loads(record['detail'])
                row.update(category=record['manual_category'] or record['category'],manual_category=record['manual_category'],
                           updated_at=record['updated_at'],archive=detail.get('archive',{'state':'not_collected'}),
                           file_count=detail.get('file_count'),skill_paths=detail.get('skill_paths',[]),
                           release_count=len(detail.get('releases',[])),warnings=detail.get('warnings',[]))
                row['skill_status']='confirmed' if row['skill_paths'] else ('candidate' if re.search(r'\bskills?\b',row['full_name']+' '+(row['description'] or ''),re.I) else 'not_detected')
                observations=db.execute('SELECT * FROM snapshots WHERE repo_id=? ORDER BY day',(row['id'],)).fetchall()
                row['growth']=None
                if len(observations)>=2:
                    latest=observations[-1]
                    edge=datetime.fromisoformat(latest['observed_at'])-timedelta(days=7)
                    prior=next((o for o in observations[:-1] if datetime.fromisoformat(o['observed_at'])>=edge),observations[-2])
                    days=(datetime.fromisoformat(latest['observed_at'])-datetime.fromisoformat(prior['observed_at'])).total_seconds()/86400
                    if days>0:
                        row['growth']={'stars':latest['stars']-prior['stars'],'days':round(days,3),
                                       'from':prior['observed_at'],'to':latest['observed_at']}
                if (not category or row['category']==category) and (not skills or row['skill_status']!='not_detected'):
                    items.append(row)
        items.sort(key=lambda r:((r['growth'] is not None, r['growth']['stars'] if r['growth'] else 0,r['stars']) if sort=='growth' else (r['stars'],r['full_name'])),reverse=True)
        return {'total':len(items),'items':items[offset:offset+limit if limit is not None else None]}

    def detail(self,full_name):
        with self.connect() as db:
            row=db.execute('SELECT * FROM repositories WHERE full_name=? COLLATE NOCASE',(full_name,)).fetchone()
            if not row:
                raise ValueError('수집한 저장소를 찾지 못했습니다.')
            return {**json.loads(row['metadata']),**json.loads(row['detail']),
                    'category':row['manual_category'] or row['category'],
                    'snapshots':[dict(r) for r in db.execute('SELECT * FROM snapshots WHERE repo_id=? ORDER BY day',(row['id'],))]}

    def assign(self,full_name,category):
        if category not in (*CATEGORIES,'auto'):
            raise ValueError('분류를 확인하세요.')
        with self.connect() as db:
            if db.execute('UPDATE repositories SET manual_category=? WHERE full_name=? COLLATE NOCASE',
                          (None if category=='auto' else category,full_name)).rowcount!=1:
                raise ValueError('저장소를 찾지 못했습니다.')


class PublicGithub:
    def __init__(self):
        from github import Github,Auth
        token=os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')
        self.client=Github(auth=Auth.Token(token) if token else None,per_page=100,timeout=30,retry=0)

    def search(self,query,limit,stop):
        found=self.client.search_repositories(query,sort='stars',order='desc')
        # Expose total count for scope warnings; no claim that all GitHub was searched.
        total=found.totalCount
        def iterator():
            for repo in islice(found,limit):
                check_stop(stop)
                yield repo.full_name
        return total,iterator()

    def get(self,name):
        repo=self.client.get_repo(name)
        if repo.private:
            raise ValueError('공개 저장소만 수집합니다.')
        return repo

    def close(self):
        self.client.close()


def metadata(repo):
    def iso(value):
        return value.isoformat() if value else None
    return {'id':repo.id,'full_name':repo.full_name,'url':repo.html_url,'description':repo.description or '',
            'stars':repo.stargazers_count,'forks':repo.forks_count,'language':repo.language,
            'topics':list(repo.topics or []),'created_at':iso(repo.created_at),'pushed_at':iso(repo.pushed_at),
            'archived':repo.archived,'default_branch':repo.default_branch,'size_kb':repo.size,
            'license':repo.license.spdx_id if repo.license else None}


class GithubAgent:
    def __init__(self,root,config,client_factory=PublicGithub):
        self.store=GithubStore(root)
        self.config=Path(config)
        self.client_factory=client_factory
        self.stop=threading.Event()
        self.thread=None
        self.lock=threading.Lock()
        with self.store.connect() as db:
            db.execute("UPDATE runs SET state='interrupted' WHERE state='running'")
            db.execute("UPDATE queries SET state='interrupted' WHERE state='running'")
            db.execute("UPDATE jobs SET state='interrupted' WHERE state='running'")

    def defaults(self):
        return json.loads(self.config.read_text(encoding='utf-8-sig'))

    def start(self,body=None,run_id=None):
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError('GitHub 에이전트가 이미 수집 중입니다.')
            if run_id:
                with self.store.connect() as db:
                    if not db.execute('SELECT 1 FROM runs WHERE id=?',(run_id,)).fetchone():
                        raise ValueError('GitHub 작업을 찾지 못했습니다.')
            else:
                run_id=self.store.create(options(body or {},self.defaults()))
            self.stop.clear()
            self.thread=threading.Thread(target=self.work,args=(run_id,),daemon=True)
            self.thread.start()
            return run_id

    def status(self,run_id=None):
        with self.store.connect() as db:
            runs=[dict(r) for r in db.execute('SELECT id,state,created_at,message FROM runs ORDER BY created_at DESC LIMIT 20')]
            run_id=run_id or (runs[0]['id'] if runs else '')
            jobs=[dict(r) for r in db.execute('SELECT * FROM jobs WHERE run_id=? ORDER BY full_name',(run_id,))]
            queries=[dict(r) for r in db.execute('SELECT * FROM queries WHERE run_id=?',(run_id,))]
        return {'runs':runs,'jobs':jobs,'queries':queries,'defaults':self.defaults(),
                'token_present':bool(os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN')),
                'busy':bool(self.thread and self.thread.is_alive())}

    def set_run(self,run,state,message=''):
        with self.store.connect() as db:
            db.execute('UPDATE runs SET state=?,message=? WHERE id=?',(state,message,run))

    def work(self,run):
        self.set_run(run,'running')
        client=None
        try:
            with self.store.connect() as db:
                settings=json.loads(db.execute('SELECT options FROM runs WHERE id=?',(run,)).fetchone()[0])
                queries=[dict(q) for q in db.execute("SELECT * FROM queries WHERE run_id=? AND state!='queried'",(run,))]
            client=self.client_factory()
            for query in queries:
                check_stop(self.stop)
                text=query['query']+f" stars:>={settings['min_stars']} is:public fork:false"
                if settings['mode']=='recent':
                    text+=' created:>='+settings['since']
                with self.store.connect() as db:
                    db.execute("UPDATE queries SET state='running' WHERE run_id=? AND query=?",(run,query['query']))
                total,found=client.search(text,settings['limit_per_query'],self.stop)
                count=0
                for name in found:
                    check_stop(self.stop)
                    if not REPO_RE.fullmatch(name):
                        continue
                    with self.store.connect() as db:
                        db.execute('INSERT OR IGNORE INTO jobs(run_id,full_name) VALUES(?,?)',(run,name))
                    count+=1
                with self.store.connect() as db:
                    db.execute("UPDATE queries SET state='queried',count=?,message=? WHERE run_id=? AND query=?",
                        (count,f'검색 응답 총 {total}건 · 상위 {count}건 발견 · 검색 상한/시점에 따른 누락 가능',run,query['query']))
            with self.store.connect() as db:
                jobs=[dict(j) for j in db.execute("SELECT * FROM jobs WHERE run_id=? AND state NOT IN ('completed') ORDER BY full_name",(run,))]
            rate_limited=False
            for job in jobs:
                check_stop(self.stop)
                name=job['full_name']
                with self.store.connect() as db:
                    db.execute("UPDATE jobs SET state='running',message='' WHERE run_id=? AND full_name=?",(run,name))
                try:
                    repo=client.get(name)
                    info=metadata(repo)
                    self.store.save(info)
                    detail=self.collect(repo,settings)
                    self.store.save(info,detail)
                    rate_limited=any(e.get('state')=='rate_limited' for e in (detail.get('release_error',{}),detail['archive'].get('error',{})))
                    state='rate_limited' if rate_limited else ('completed' if detail['archive']['state'] in ('downloaded','disabled') and not detail.get('release_error') else 'needs_attention')
                    message='파일 스냅샷·문서·최근 릴리스 조회 종료' if state=='completed' else '파일/릴리스 일부 미수집 · 상세 확인 후 이어받기'
                except Stopped:
                    raise
                except Exception as exc:
                    error=safe_error(exc)
                    state=error['state']
                    message=json.dumps(error,ensure_ascii=False)
                    rate_limited=state=='rate_limited'
                with self.store.connect() as db:
                    db.execute('UPDATE jobs SET state=?,message=? WHERE run_id=? AND full_name=?',(state,message,run,name))
                if rate_limited:
                    break
            with self.store.connect() as db:
                unfinished=db.execute("SELECT COUNT(*) FROM jobs WHERE run_id=? AND state!='completed'",(run,)).fetchone()[0]
            self.set_run(run,'rate_limited' if rate_limited else ('needs_attention' if unfinished else 'finished_unverified'),
                         '지정한 검색·저장소의 조회 종료이며 GitHub 전체 또는 모든 과거 버전의 완전 수집은 아닙니다.')
        except Stopped:
            self.set_run(run,'stopped','이어받기 시 미완료 검색·저장소를 다시 조회합니다.')
        except Exception as exc:
            error=safe_error(exc)
            self.set_run(run,error['state'],json.dumps(error,ensure_ascii=False))
        finally:
            with self.store.connect() as db:
                db.execute("UPDATE jobs SET state='interrupted' WHERE run_id=? AND state='running'",(run,))
                db.execute("UPDATE queries SET state='interrupted' WHERE run_id=? AND state='running'",(run,))
            if client:
                client.close()

    def collect(self,repo,settings):
        check_stop(self.stop)
        detail={}
        sha=repo.get_commit(repo.default_branch).sha
        detail['commit_sha']=sha
        try:
            if settings['download_archive']:
                path=download_archive(repo.full_name,sha,self.store.root/'archives',settings['archive_mb']*1024*1024,self.stop)
                detail=read_archive(path,self.stop)
                detail['commit_sha']=sha
                detail['archive']={'state':'downloaded','path':path.relative_to(self.store.root).as_posix(),'bytes':path.stat().st_size}
                digest=hashlib.sha256()
                with path.open('rb') as stream:
                    while block:=stream.read(1024*1024):
                        check_stop(self.stop)
                        digest.update(block)
                detail['archive']['sha256']=digest.hexdigest()
            else:
                detail['archive']={'state':'disabled'}
                readme=repo.get_readme(ref=sha)
                detail['readme']=readme.decoded_content[:256*1024].decode('utf-8',errors='replace')
        except Stopped:
            raise
        except Exception as exc:
            detail['archive']={'error':safe_error(exc),'state':'error','message':'파일 또는 README 수집 실패. 크기 상한·접근·네트워크를 확인하세요.'}
        detail['releases']=[]
        cutoff=datetime.strptime(settings['since'],'%Y-%m-%d').replace(tzinfo=KST)
        if detail['archive'].get('error',{}).get('state')=='rate_limited':
            return detail
        try:
            # API ordering is not assumed to be publication-date order.
            for release in islice(repo.get_releases(),100):
                check_stop(self.stop)
                date=release.published_at or release.created_at
                if date and date>=cutoff:
                    detail['releases'].append({'id':release.id,'tag':release.tag_name,'name':release.title,
                        'body':(release.body or '')[:100000],'url':release.html_url,'published_at':date.isoformat(),
                        'prerelease':release.prerelease})
            detail['release_scope']='최대 100개 릴리스 검사 후 기준일 이후 항목 저장 · 전체 과거 릴리스 보장 없음'
        except Stopped:
            raise
        except Exception as exc:
            detail['release_error']=safe_error(exc)
        return detail
