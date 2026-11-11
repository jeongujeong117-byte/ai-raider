"""Shared source-agent helpers, adapter registry and the independent durable SourceAgent worker.

Per-source extractors live in agents/{youtube,news,gallery,huggingface}_agent.py and are
re-exported here, so `import source_agents` (an alias of this module) keeps its public names.
"""
import calendar
import json
import threading
import uuid
from datetime import datetime,timedelta
from pathlib import Path
from urllib.parse import urljoin

from agents.github_agent import classify
from core.common import UTC,KST
from core.source_tools import fetch,html,save_media,check,Cancelled,public_url

KINDS={'youtube':'유튜브','news':'뉴스','huggingface':'허깅페이스','gallery':'AI 활용 갤러리'}


def default_start():
    now=datetime.now(KST)
    number=now.year*12+now.month-4
    year,month=divmod(number,12);month+=1
    return now.replace(year=year,month=month,day=min(now.day,calendar.monthrange(year,month)[1])) .date().isoformat()


def date_value(value):
    if not value:
        return None
    if isinstance(value,datetime):
        return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)
    try:
        result=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return result.replace(tzinfo=result.tzinfo or KST).astimezone(UTC)
    except (ValueError,TypeError):
        return None


def in_window(date,settings):
    if date is None:
        return True  # Preserve undated items explicitly, never fabricate a publication date.
    start=datetime.strptime(settings['start'],'%Y-%m-%d').replace(tzinfo=KST)
    end=datetime.strptime(settings['end'],'%Y-%m-%d').replace(tzinfo=KST)+timedelta(days=1)
    return start<=date<end


def post(kind,id,handle,url,title,text,date=None,metrics=None,media=None,raw=None):
    raw=raw or {}
    raw.update(title=title,date_unknown=date is None,
               classification=classify(title,text[:2000],[],text[:10000]))
    return dict(platform=kind,post_id=str(id),handle=handle,url=url,
                posted_at=date.isoformat() if date else '',text=(title+'\n\n'+text).strip(),
                metrics=metrics or {},media=media or [],raw=raw)


def get_html(url,stop,browser=False):
    try:
        return html(url,stop)
    except Cancelled:
        raise
    except Exception:
        if not browser:
            raise
        return html(url,stop,browser=True)


def media_tags(node,base):
    assets=[]
    seen=set()
    for tag in node.select('img,video,video source'):
        value=tag.get('data-src') or tag.get('src')
        if not value or value.startswith('data:'):
            continue
        url=urljoin(base,value)
        if url in seen:
            continue
        seen.add(url)
        assets.append({'url':url,'kind':'image' if tag.name=='img' else 'video'})
    return assets


from agents.youtube_agent import QuietLogger,YoutubeExtractor  # noqa: E402
from agents.news_agent import NewsExtractor  # noqa: E402
from agents.gallery_agent import GalleryExtractor  # noqa: E402
from agents.huggingface_agent import HuggingFaceExtractor  # noqa: E402

ADAPTERS={'youtube':YoutubeExtractor,'news':NewsExtractor,'gallery':GalleryExtractor,'huggingface':HuggingFaceExtractor}


class SourceAgent:
    def __init__(self,kind,store,data,config,processor=None,adapter=None):
        if kind not in KINDS:
            raise ValueError('정보원을 확인하세요.')
        self.kind=kind;self.store=store;self.data=Path(data);self.config=Path(config);self.processor=processor
        self.adapter=adapter or ADAPTERS[kind](data)
        self.stop=threading.Event();self.thread=None;self.lock=threading.Lock()
        with store.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS source_runs(id TEXT PRIMARY KEY,kind TEXT,settings TEXT,state TEXT,created_at TEXT);
            CREATE TABLE IF NOT EXISTS source_jobs(run_id TEXT,target TEXT,state TEXT DEFAULT 'pending',seen INTEGER DEFAULT 0,message TEXT DEFAULT '',PRIMARY KEY(run_id,target));''')
            db.execute("UPDATE source_jobs SET state='interrupted' WHERE state='running' AND run_id IN (SELECT id FROM source_runs WHERE kind=?)",(kind,))
            db.execute("UPDATE source_runs SET state='interrupted' WHERE state='running' AND kind=?",(kind,))

    def defaults(self):
        return json.loads(self.config.read_text(encoding='utf-8-sig'))[self.kind]

    def settings(self,body):
        targets=body.get('targets',self.defaults()['targets'])
        if isinstance(targets,str):
            targets=[t.strip() for t in targets.splitlines() if t.strip()]
        if not isinstance(targets,list) or not 1<=len(targets)<=100 or any(not isinstance(t,str) or len(t)>2000 for t in targets):
            raise ValueError('대상을 줄마다 하나씩 1~100개 입력하세요.')
        limit=int(body.get('limit',self.defaults()['limit']));pages=int(body.get('pages',100));mb=int(body.get('max_mb',512))
        if not 1<=limit<=10000 or not 1<=pages<=1000 or not 1<=mb<=4096:
            raise ValueError('건수 1~10000, 페이지 1~1000, 파일 1~4096MB로 설정하세요.')
        start=body.get('start') or default_start();end=body.get('end') or datetime.now(KST).date().isoformat()
        a=datetime.strptime(start,'%Y-%m-%d');b=datetime.strptime(end,'%Y-%m-%d')
        if a>b:
            raise ValueError('날짜 범위를 확인하세요.')
        return dict(targets=list(dict.fromkeys(targets)),limit=limit,pages=pages,max_mb=mb,start=start,end=end,
                    download_media=bool(body.get('download_media',True)),browser=bool(body.get('browser',False)))

    def start(self,body=None,run_id=None):
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError('이 정보원이 수집 중입니다.')
            if run_id:
                with self.store.connect() as db:
                    if not db.execute('SELECT id FROM source_runs WHERE id=? AND kind=?',(run_id,self.kind)).fetchone():
                        raise ValueError('작업을 찾지 못했습니다.')
            else:
                settings=self.settings(body or {})
                run_id=uuid.uuid4().hex
                with self.store.connect() as db:
                    db.execute('INSERT INTO source_runs VALUES(?,?,?,?,?)',(run_id,self.kind,json.dumps(settings),'pending',datetime.now(UTC).isoformat()))
                    db.executemany('INSERT INTO source_jobs(run_id,target) VALUES(?,?)',[(run_id,t) for t in settings['targets']])
            self.stop.clear();self.thread=threading.Thread(target=self.work,args=(run_id,),daemon=True);self.thread.start()
            return run_id

    def work(self,run):
        with self.store.connect() as db:
            settings=json.loads(db.execute('SELECT settings FROM source_runs WHERE id=?',(run,)).fetchone()[0])
            db.execute("UPDATE source_runs SET state='running' WHERE id=?",(run,))
            jobs=[dict(j) for j in db.execute("SELECT * FROM source_jobs WHERE run_id=? AND state!='queried'",(run,))]
        for job in jobs:
            if self.stop.is_set():
                break
            count=0;issues=0
            with self.store.connect() as db:
                db.execute("UPDATE source_jobs SET state='running' WHERE run_id=? AND target=?",(run,job['target']))
            try:
                for item in self.adapter.collect(job['target'],settings,self.stop):
                    check(self.stop)
                    self.store.save(item)  # Raw text survives download/OCR failures.
                    if settings['download_media'] and self.kind!='youtube':
                        save_media(item,self.data/'media',self.stop,settings['max_mb']*1024*1024)
                        self.store.save(item)
                    issues+=len(item['raw'].get('errors',[]))+sum(a.get('status')=='error' for a in item['media'])
                    if self.processor:
                        self.processor.enqueue(item)
                    count+=1
                    with self.store.connect() as db:
                        db.execute('UPDATE source_jobs SET seen=? WHERE run_id=? AND target=?',(count,run,job['target']))
                state='needs_attention' if issues else 'queried'
                message=f'{count}건 저장 · 오류 {issues}개 · 설정 범위 조회 종료, 완전성 미검증'
            except Cancelled:
                state='interrupted';message='미완료 대상은 이어받기 시 다시 조회'
            except Exception as exc:
                state='error';message='수집 오류 ('+type(exc).__name__+') · 접근/로그인/구조 확인 후 이어받기'
            with self.store.connect() as db:
                db.execute('UPDATE source_jobs SET state=?,seen=?,message=? WHERE run_id=? AND target=?',(state,count,message,run,job['target']))
        with self.store.connect() as db:
            states=[r[0] for r in db.execute('SELECT state FROM source_jobs WHERE run_id=?',(run,))]
            state='stopped' if self.stop.is_set() else ('finished_unverified' if all(s=='queried' for s in states) else 'needs_attention')
            db.execute('UPDATE source_runs SET state=? WHERE id=?',(state,run))

    def status(self,run=None):
        with self.store.connect() as db:
            runs=[dict(r) for r in db.execute('SELECT id,kind,state,created_at FROM source_runs WHERE kind=? ORDER BY created_at DESC LIMIT 20',(self.kind,))]
            run=run or (runs[0]['id'] if runs else '')
            jobs=[dict(r) for r in db.execute('SELECT * FROM source_jobs WHERE run_id=?',(run,))]
        return {'runs':runs,'jobs':jobs,'defaults':self.defaults(),'busy':bool(self.thread and self.thread.is_alive()),
                'default_start':default_start(),'default_end':datetime.now(KST).date().isoformat()}
