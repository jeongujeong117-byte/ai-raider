"""Source-specific extraction adapters and independent durable collection workers."""
import calendar
import hashlib
import json
import re
import shutil
import threading
import time
import uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.parse import urlparse,urljoin,parse_qs,urlencode

from github_agent import classify
from source_tools import fetch,html,save_media,check,Cancelled,public_url

UTC=timezone.utc
KST=timezone(timedelta(hours=9))
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


class NewsExtractor:
    def __init__(self,data):
        self.data=Path(data)

    def article(self,url,stop,browser=False,fallback=None):
        from bs4 import BeautifulSoup
        import trafilatura
        fallback=fallback or {}
        errors=[]
        try:
            page,final=get_html(url,stop,browser)
            document=trafilatura.bare_extraction(page,url=final,with_metadata=True)
            if not document or not document.text:
                if browser:
                    page,final=html(url,stop,browser=True)
                    document=trafilatura.bare_extraction(page,url=final,with_metadata=True)
            if not document or not document.text:
                raise ValueError('본문을 찾지 못했습니다.')
            soup=BeautifulSoup(page,'html.parser')
            body=soup.select_one('article') or soup.select_one('#article-view-content-div') or soup
            text=document.text
            title=document.title or fallback.get('title','')
            date=date_value(document.date) or fallback.get('date')
            media=media_tags(body,final)
        except Cancelled:
            raise
        except Exception as exc:
            if not fallback.get('text'):
                raise
            final=url;text=fallback['text'];title=fallback.get('title','');date=fallback.get('date');media=[]
            errors.append({'step':'article','error_type':type(exc).__name__})
        return post('news',hashlib.sha256(url.encode()).hexdigest(),urlparse(final).hostname or 'news',final,title,text,date,media=media,
                    raw={'tool':'feedparser + trafilatura','errors':errors,'scope':'RSS 제공 목록 또는 지정 기사. 전체 뉴스 과거 목록 아님'})

    def collect(self,target,s,stop):
        import feedparser
        from bs4 import BeautifulSoup
        from calendar import timegm
        payload,_,_=fetch(target,stop)
        feed=feedparser.parse(payload)
        if not feed.entries:
            yield self.article(target,stop,s['browser'])
            return
        seen=set()
        for entry in feed.entries[:s['limit']]:
            check(stop)
            url=entry.get('link')
            if not url or url in seen:
                continue
            seen.add(url)
            stamp=entry.get('published_parsed') or entry.get('updated_parsed')
            date=datetime.fromtimestamp(timegm(stamp),UTC) if stamp else None
            if not in_window(date,s):
                continue
            summary=BeautifulSoup(entry.get('summary',''),'html.parser').get_text('\n',strip=True)
            item=self.article(url,stop,s['browser'],{'title':entry.get('title',''),'text':summary,'date':date})
            if in_window(date_value(item['posted_at']),s):
                item['raw']['feed']=target
                yield item


class GalleryExtractor:
    def __init__(self,data):
        self.data=Path(data)

    def collect(self,target,s,stop):
        from bs4 import BeautifulSoup
        parsed=urlparse(target)
        if parsed.hostname not in ('gall.dcinside.com','enter.dcinside.com'):
            raise ValueError('AI 활용 갤러리의 디시인사이드 주소를 입력하세요.')
        query=parse_qs(parsed.query)
        gallery=query.get('id',['ai_utilize'])[0]
        if not re.fullmatch('[a-zA-Z0-9_]+',gallery):
            raise ValueError('갤러리 ID를 확인하세요.')
        seen=set();emitted=0
        for page_no in range(1,s['pages']+1):
            check(stop)
            listing='https://gall.dcinside.com/mgallery/board/lists/?'+urlencode({'id':gallery,'page':page_no})
            page,final=get_html(listing,stop,s['browser'])
            soup=BeautifulSoup(page,'html.parser')
            rows=soup.select('tr.ub-content')
            if not rows and s['browser']:
                page,final=html(listing,stop,browser=True)
                rows=BeautifulSoup(page,'html.parser').select('tr.ub-content')
            if not rows:
                raise ValueError('게시글 목록 없음: 접근 제한 또는 페이지 구조 확인 필요')
            fresh=0
            for row in rows:
                link=row.select_one('td.gall_tit a[href*="/board/view/"]')
                if not link:
                    continue
                url=urljoin(final,link.get('href',''))
                no=parse_qs(urlparse(url).query).get('no',[''])[0]
                if not no.isdigit() or no in seen:
                    continue
                seen.add(no);fresh+=1
                date_tag=row.select_one('.gall_date')
                date=date_value(date_tag.get('title') if date_tag else None)
                if not in_window(date,s):
                    continue
                check(stop)
                page,final=get_html(url,stop,s['browser'])
                article=BeautifulSoup(page,'html.parser')
                body=article.select_one('.write_div')
                if body is None and s['browser']:
                    page,final=html(url,stop,browser=True)
                    article=BeautifulSoup(page,'html.parser');body=article.select_one('.write_div')
                if body is None:
                    raise ValueError('게시글 본문 없음: 로그인·삭제·접근 제한 확인 필요')
                title=article.select_one('.title_subject')
                def number(selector):
                    node=row.select_one(selector)
                    return int(re.sub(r'[^0-9]','',node.get_text()) or 0) if node else None
                yield post('gallery',gallery+'-'+no,gallery,final,title.get_text(strip=True) if title else link.get_text(strip=True),
                    body.get_text('\n',strip=True),date,{'likes':number('.gall_recommend'),'views':number('.gall_count')},media_tags(body,final),
                    {'tool':'BeautifulSoup + public HTML','page':page_no,'scope':f'최대 {s["pages"]}페이지 · {s["limit"]}건, 댓글 별도 미수집'})
                emitted+=1
                if emitted>=s['limit']:
                    return
                if stop.wait(.4):
                    raise Cancelled()
            if not fresh:
                return


class HuggingFaceExtractor:
    def __init__(self,data):
        self.data=Path(data)

    def collect(self,target,s,stop):
        from huggingface_hub import HfApi
        api=HfApi(token=False)
        types={'models':'model','datasets':'dataset','spaces':'space'}
        kind=types.get(target)
        if kind:
            method={'model':api.list_models,'dataset':api.list_datasets,'space':api.list_spaces}[kind]
            ids=[r.id for r in method(sort='likes',direction=-1,limit=s['limit'])]
        else:
            match=re.fullmatch(r'(model|dataset|space):([\w.-]+/[\w.-]+)',target)
            if not match:
                raise ValueError('models/datasets/spaces 또는 model:owner/name 형식으로 입력하세요.')
            kind=match[1];ids=[match[2]]
        for id in ids:
            check(stop)
            info=api.repo_info(id,repo_type=kind,files_metadata=True)
            if getattr(info,'private',False):
                continue
            date=date_value(getattr(info,'last_modified',None) or getattr(info,'lastModified',None))
            if not in_window(date,s):
                continue
            prefix='' if kind=='model' else ('datasets/' if kind=='dataset' else 'spaces/')
            url='https://huggingface.co/'+prefix+id
            files=[{'path':r.rfilename,'bytes':getattr(r,'size',None)} for r in (info.siblings or [])]
            errors=[];card='';saved=[]
            for file in files:
                if not (file['path'].lower().endswith(('.md','.txt','.json','.yaml','.yml')) and (file['path'].lower().endswith('.md') or file['path'] in ('config.json','model_index.json'))):
                    continue
                if len(saved)>=20:
                    break
                check(stop)
                try:
                    from urllib.parse import quote
                    content,_,_=fetch(url+'/resolve/'+quote(info.sha,safe='')+'/'+quote(file['path'],safe='/'),stop,max_bytes=1024*1024)
                    folder=self.data/'source-files/huggingface'/hashlib.sha256((kind+id+info.sha).encode()).hexdigest()[:24]
                    folder.mkdir(parents=True,exist_ok=True)
                    path=folder/(str(len(saved))+'.txt');path.write_bytes(content)
                    text=content.decode('utf-8',errors='replace')
                    saved.append({'path':file['path'],'local_path':path.relative_to(self.data).as_posix(),'text':text})
                    if file['path'].lower()=='readme.md':
                        card=text
                except Cancelled:
                    raise
                except Exception as exc:
                    errors.append({'path':file['path'],'error_type':type(exc).__name__})
            yield post('huggingface',kind+':'+id,id,url,id,card,date,
                       {'likes':getattr(info,'likes',None),'downloads':getattr(info,'downloads',None)},raw={
                           'tool':'official huggingface_hub HfApi','repo_type':kind,'sha':info.sha,'tags':getattr(info,'tags',[]),
                           'files':files,'documents':saved,'errors':errors,'scope':'현재 파일 목록·카드·설정. 모델 가중치·데이터 원본 자동 다운로드 없음'})


class QuietLogger:
    def debug(self,*a): pass
    def warning(self,*a): pass
    def error(self,*a): pass


class YoutubeExtractor:
    def __init__(self,data):
        self.data=Path(data)

    def collect(self,target,s,stop):
        from yt_dlp import YoutubeDL
        if urlparse(target).hostname not in ('www.youtube.com','youtube.com','youtu.be'):
            raise ValueError('YouTube 영상·채널·재생목록 주소를 입력하세요.')
        def hook(status):
            check(stop)
            if status.get('downloaded_bytes',0)>s['max_mb']*1024*1024:
                raise ValueError('영상 파일 크기 상한 초과')
        base={'quiet':True,'no_warnings':True,'logger':QuietLogger(),'socket_timeout':30,'retries':1,'fragment_retries':1,
              'playlistend':s['limit'],'progress_hooks':[hook], 'remote_components':set()}
        if shutil.which('node'):
            base['js_runtimes']={'node':{'path':shutil.which('node')}}
        cookies=Path(__file__).parent/'.private/youtube.cookies.txt'
        if cookies.is_file():
            base['cookiefile']=str(cookies)
        with YoutubeDL({**base,'extract_flat':'in_playlist','skip_download':True}) as ydl:
            listing=ydl.extract_info(target,download=False)
        entries=listing.get('entries') if listing else []
        if entries is None:
            entries=[listing]
        if not entries and listing and listing.get('id'):
            entries=[listing]
        from itertools import islice
        for entry in islice(entries or [],s['limit']):
            check(stop)
            if not entry:
                continue
            id=entry.get('id','')
            if not re.fullmatch(r'[A-Za-z0-9_-]{11}',id):
                continue
            url='https://www.youtube.com/watch?v='+id
            with YoutubeDL({**base,'skip_download':True,'noplaylist':True}) as ydl:
                info=ydl.extract_info(url,download=False)
            date=datetime.fromtimestamp(info['timestamp'],UTC) if info.get('timestamp') else None
            if not date and info.get('upload_date'):
                date=datetime.strptime(info['upload_date'],'%Y%m%d').replace(tzinfo=KST)
            if not in_window(date,s):
                continue
            raw={'tool':'yt-dlp','duration_seconds':info.get('duration'),'errors':[],'subtitles':[],'scope':f'최대 {s["limit"]}개 목록. 비공개·삭제·차단 영상은 확보 보장 없음'}
            subtitles=info.get('subtitles') or info.get('automatic_captions') or {}
            for lang in ['ko','en']:
                selected=next((a for a in subtitles.get(lang,[]) if a.get('ext')=='json3'),None)
                if selected:
                    try:
                        payload,_,_=fetch(selected['url'],stop)
                        events=json.loads(payload).get('events',[])
                        raw['subtitles']=[{'start':e.get('tStartMs',0)/1000,'text':''.join(a.get('utf8','') for a in e.get('segs',[])).strip()} for e in events if e.get('segs')]
                        raw['subtitle_language']=lang
                    except Cancelled:
                        raise
                    except Exception as exc:
                        raw['errors'].append({'step':'subtitles','error_type':type(exc).__name__})
                    break
            text=info.get('description','')
            if raw['subtitles']:
                text+='\n\n[제공 자막]\n'+'\n'.join(f"{r['start']}초: {r['text']}" for r in raw['subtitles'])
            media=[]
            if s['download_media']:
                folder=self.data/'media/youtube'/('p-'+id)
                folder.mkdir(parents=True,exist_ok=True)
                try:
                    with YoutubeDL({**base,'noplaylist':True,'format':'best[ext=mp4]/best',
                                    'outtmpl':str(folder/'video.%(ext)s'),'max_filesize':s['max_mb']*1024*1024}) as ydl:
                        downloaded=ydl.extract_info(url,download=True)
                        path=Path(ydl.prepare_filename(downloaded))
                    if not path.is_file():
                        raise ValueError('파일이 저장되지 않았습니다. 크기·접근 제한 확인 필요')
                    media=[{'kind':'video','status':'downloaded','local_path':path.relative_to(self.data/'media').as_posix(),'bytes':path.stat().st_size}]
                except Cancelled:
                    raise
                except Exception as exc:
                    media=[{'kind':'video','status':'error','error_type':type(exc).__name__}]
                    raw['errors'].append({'step':'video','error_type':type(exc).__name__})
                    for partial in folder.glob('*.part'):
                        partial.unlink(missing_ok=True)
            yield post('youtube',id,info.get('channel_id') or 'youtube',url,info.get('title',''),text,date,
                       {'likes':info.get('like_count'),'views':info.get('view_count'),'comments':info.get('comment_count')},media,raw)


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
