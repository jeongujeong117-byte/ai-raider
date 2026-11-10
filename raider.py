"""Local collector. Standard-library UI; collection adapters are loaded on demand."""
from __future__ import annotations

import argparse
import asyncio
import calendar
import csv
import io
import json
import os
import re
import secrets
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse, unquote
from source_manager import Registry
from media_store import download_media, x_media, MIME_EXT
from post_processing import Processor, prepare
from github_agent import GithubAgent
from source_agents import SourceAgent, KINDS

ROOT = Path(__file__).resolve().parent
os.environ["TWS_TELEMETRY"] = "0"
DATA = ROOT / "data"
PRIVATE = ROOT / ".private"
UTC = timezone.utc
KST = timezone(timedelta(hours=9))


def now():
    return datetime.now(UTC)


def months_ago(value, months=3):
    number = value.year * 12 + value.month - 1 - months
    year, month = divmod(number, 12)
    month += 1
    return value.replace(year=year, month=month,
                         day=min(value.day, calendar.monthrange(year, month)[1]))


def window(start=None, end=None):
    """User dates are KST, end date inclusive; freeze exact now for defaults."""
    finish = (min(datetime.fromisoformat(end).replace(tzinfo=KST) + timedelta(days=1), now())
              if end else now())
    begin = datetime.fromisoformat(start).replace(tzinfo=KST) if start else months_ago(finish.astimezone(KST))
    if begin >= finish:
        raise ValueError("시작일은 종료일보다 빨라야 합니다.")
    return begin.astimezone(UTC), finish.astimezone(UTC)


def accounts():
    return Registry(ROOT).accounts()


class Store:
    def __init__(self, path=None):
        self.path = Path(path or DATA / "raider.sqlite")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS posts (
              platform TEXT, post_id TEXT, handle TEXT, url TEXT, posted_at TEXT,
              text TEXT, metrics TEXT, media TEXT, collected_at TEXT, raw TEXT,
              PRIMARY KEY(platform, post_id));
            CREATE TABLE IF NOT EXISTS runs (
              id TEXT PRIMARY KEY, start TEXT, end TEXT, state TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS tasks (
              run_id TEXT, platform TEXT, handle TEXT, slice_start TEXT, slice_end TEXT,
              state TEXT, seen INTEGER DEFAULT 0, message TEXT DEFAULT '',
              PRIMARY KEY(run_id, platform, handle, slice_start));
            CREATE INDEX IF NOT EXISTS posts_date ON posts(posted_at);
            CREATE TABLE IF NOT EXISTS processing (
              platform TEXT, post_id TEXT, fingerprint TEXT, state TEXT,
              result TEXT DEFAULT '{}', updated_at REAL,
              PRIMARY KEY(platform,post_id));
            ''')
            if 'download_media' not in {r['name'] for r in db.execute('PRAGMA table_info(runs)')}:
                db.execute('ALTER TABLE runs ADD COLUMN download_media INTEGER NOT NULL DEFAULT 0')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def save(self, post):
        with self.connect() as db:
            db.execute('''INSERT INTO posts VALUES (?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(platform,post_id) DO UPDATE SET text=excluded.text,
              metrics=excluded.metrics,media=excluded.media,collected_at=excluded.collected_at,raw=excluded.raw''',
              (post["platform"], str(post["post_id"]), post["handle"], post["url"], post["posted_at"],
               post["text"], json.dumps(post["metrics"]), json.dumps(post["media"]), now().isoformat(),
               json.dumps(post.get("raw", {}), ensure_ascii=False, default=str)))

    def create_run(self, selected, begin, finish, download_files=False):
        run_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO runs(id,start,end,state,created_at,download_media) VALUES (?,?,?,?,?,?)", (run_id, begin.isoformat(), finish.isoformat(), "pending", now().isoformat(),int(download_files)))
            for account in selected:
                slices = [(begin, finish)]
                if account["platform"] == "x":
                    slices = []
                    cursor = begin
                    while cursor < finish:
                        edge = min(cursor.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1), finish)
                        slices.append((cursor, edge))
                        cursor = edge
                db.executemany("INSERT INTO tasks(run_id,platform,handle,slice_start,slice_end,state) VALUES (?,?,?,?,?,?)",
                    [(run_id, account["platform"], account["handle"], a.isoformat(), b.isoformat(), "pending") for a,b in slices])
        return run_id

    def tasks(self, run_id):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM tasks WHERE run_id=? ORDER BY platform,handle,slice_start", (run_id,))]

    def task(self, row, state, seen, message=""):
        with self.connect() as db:
            db.execute("UPDATE tasks SET state=?,seen=?,message=? WHERE run_id=? AND platform=? AND handle=? AND slice_start=?",
                       (state,seen,message,row["run_id"],row["platform"],row["handle"],row["slice_start"]))

    def run_state(self, run_id, state):
        with self.connect() as db:
            db.execute("UPDATE runs SET state=? WHERE id=?", (state,run_id))

    def rows(self, platform="", handle="", offset=0, limit=100, sort="date", category=""):
        where, params = [], []
        for key, value in (("platform",platform),("handle",handle)):
            if value:
                where.append(key+"=?")
                params.append(value)
        if category:
            names=[a['handle'] for a in accounts() if a['category']==category and (not platform or a['platform']==platform)]
            if not platform:
                raise ValueError('분류 조회에는 플랫폼을 선택하세요.')
            if not names:
                return {'total':0,'items':[]}
            where.append('handle IN ('+','.join('?' for _ in names)+')')
            params.extend(names)
        clause = " WHERE " + " AND ".join(where) if where else ""
        order = "posted_at DESC,post_id DESC"
        # Reactions across platforms are deliberately not combined into one score.
        if sort == "likes" and platform:
            order = "CAST(json_extract(metrics,'$.likes') AS INTEGER) DESC, posted_at DESC"
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM posts"+clause, params).fetchone()[0]
            result = [dict(r) for r in db.execute("SELECT * FROM posts"+clause+" ORDER BY "+order+" LIMIT ? OFFSET ?", params+[limit,offset])]
        for row in result:
            for key in ("metrics","media","raw"):
                row[key] = json.loads(row[key])
        # Derived data live separately so a new crawl cannot erase OCR/transcripts.
        with self.connect() as db:
            for row in result:
                processed=db.execute('SELECT state,result FROM processing WHERE platform=? AND post_id=?',
                                     (row['platform'],row['post_id'])).fetchone()
                row['processing']={**json.loads(processed['result']),'state':processed['state']} if processed else {'state':'not_queued'}
        return {"total":total,"items":result}


class Cancelled(Exception):
    pass


def instagram(task, begin, finish, stop):
    import instaloader
    settings = PRIVATE / "instagram.json"
    if not settings.exists():
        raise RuntimeError("Instagram 로그인이 필요합니다. 터미널에서 uv run python raider.py login-instagram 실행")
    username = json.loads(settings.read_text(encoding="utf-8"))["username"]
    loader = instaloader.Instaloader(max_connection_attempts=1, request_timeout=30,
                                    download_pictures=False, download_videos=False)
    loader.load_session_from_file(username, str(PRIVATE / "instagram.session"))
    profile = instaloader.Profile.from_username(loader.context, task["handle"])
    # Full enumeration avoids stopping on an out-of-order pinned post.
    for post in profile.get_posts():
        if stop.is_set():
            raise Cancelled()
        date = post.date_utc.replace(tzinfo=UTC)
        if not begin <= date < finish:
            continue
        media = [{"url":post.url,"kind":"thumbnail" if post.is_video else "image"}]
        if post.typename == "GraphSidecar":
            media=[]
            for n in post.get_sidecar_nodes():
                if n.is_video:
                    media.append({'url':n.video_url,'kind':'video'})
                media.append({'url':n.display_url,'kind':'thumbnail' if n.is_video else 'image'})
        elif post.is_video:
            media.insert(0,{'url':post.video_url,'kind':'video'})
        yield {"platform":"instagram","post_id":str(post.mediaid),"handle":task["handle"],
               "url":f"https://www.instagram.com/p/{post.shortcode}/", "posted_at":date.isoformat(),
               "text":post.caption or "", "metrics":{"likes":post.likes,"comments":post.comments,
               "views":getattr(post,"video_view_count",None) if post.is_video else None},"media":media,
               "raw":{"shortcode":post.shortcode,"type":post.typename}}


async def x_posts(task, begin, finish, stop):
    from twscrape import API
    path = PRIVATE / "x-accounts.db"
    if not path.exists():
        raise RuntimeError("X 세션이 필요합니다. README의 X 로그인 설정을 먼저 완료하세요.")
    api = API(str(path), raise_when_no_account=True)
    day = begin.date().isoformat()
    next_day = (begin + timedelta(days=1)).date().isoformat()
    query = f"from:{task['handle']} since:{day} until:{next_day}"
    async for tweet in api.search(query, limit=0, kv={"product":"Latest"}):
        if stop.is_set():
            raise Cancelled()
        date = tweet.date.astimezone(UTC)
        if not begin <= date < finish or tweet.user.username.lower() != task["handle"].lower():
            continue
        yield {"platform":"x","post_id":str(tweet.id),"handle":task["handle"],
               "url":tweet.url,"posted_at":date.isoformat(),"text":tweet.rawContent,
               "metrics":{"likes":tweet.likeCount,"comments":tweet.replyCount,"reposts":tweet.retweetCount,
                          "quotes":tweet.quoteCount,"views":tweet.viewCount},
               "media":x_media(tweet.media),"raw":json.loads(tweet.json())}


class Runner:
    def __init__(self, store, processor=None):
        self.store, self.stop = store, threading.Event()
        self.processor=processor
        self.lock, self.thread, self.current = threading.Lock(), None, None
        # A process restart must not leave stale 'running' jobs in the interface.
        with store.connect() as db:
            db.execute("UPDATE runs SET state='interrupted' WHERE state='running'")
            db.execute("UPDATE tasks SET state='interrupted' WHERE state='running'")

    def start(self, run_id):
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError("이미 수집 중입니다. 중지 후 다시 시작하세요.")
            if not self.store.tasks(run_id):
                raise ValueError("수집 작업을 찾을 수 없습니다.")
            self.stop.clear()
            self.current = run_id
            self.thread = threading.Thread(target=self.work, args=(run_id,), daemon=True)
            self.thread.start()

    def work(self, run_id):
        self.store.run_state(run_id,"running")
        with self.store.connect() as db:
            download_files=bool(db.execute('SELECT download_media FROM runs WHERE id=?',(run_id,)).fetchone()[0])
        failed_platforms = set()
        for task in self.store.tasks(run_id):
            if self.stop.is_set():
                break
            if task["state"] == "queried":
                continue
            if task["platform"] in failed_platforms:
                self.store.task(task,"blocked",task["seen"],"같은 플랫폼의 선행 오류 해결 후 이어받으세요.")
                continue
            count = 0
            media_errors = 0
            self.store.task(task,"running",count)
            begin, finish = map(datetime.fromisoformat,(task["slice_start"],task["slice_end"]))
            def save(post):
                nonlocal count, media_errors
                # Persist text and references first, even if downloading is interrupted.
                self.store.save(post)
                if download_files:
                    post['media']=download_media(post,DATA/'media',self.stop)
                    self.store.save(post)
                    media_errors+=sum(a.get('status')!='downloaded' for a in post['media'])
                if self.processor:
                    self.processor.enqueue(post)
                count += 1
                self.store.task(task,"running",count)
            try:
                if task["platform"] == "instagram":
                    for post in instagram(task,begin,finish,self.stop):
                        save(post)
                else:
                    async def consume():
                        async for post in x_posts(task,begin,finish,self.stop):
                            save(post)
                    asyncio.run(consume())
                if self.stop.is_set():
                    raise Cancelled()
                self.store.task(task,"queried_media_errors" if media_errors else "queried",count,
                    f"조회 종료 · 미디어 실패 {media_errors}개 · 전체 과거 자료 제공 여부 미검증")
            except Cancelled:
                self.store.task(task,"interrupted",count,"이어받기 시 미완료 구간을 다시 조회합니다.")
                break
            except Exception as exc:
                # Upstream exceptions can contain authenticated URLs or cookies.
                self.store.task(task,"error",count,"수집기 오류 ("+type(exc).__name__+"): 설치 버전·로그인 세션·접근 제한을 확인하세요. 해당 플랫폼의 후속 요청을 멈췄습니다.")
                failed_platforms.add(task["platform"])
        states = [t["state"] for t in self.store.tasks(run_id)]
        state = "stopped" if self.stop.is_set() else ("needs_attention" if any(s!="queried" for s in states) else "finished_unverified")
        self.store.run_state(run_id,state)


def serve(port=8765):
    store = Store()
    processor=Processor(store,DATA)
    processor.start()
    runner = Runner(store,processor)
    token = secrets.token_urlsafe(32)
    host = f"127.0.0.1:{port}"
    registry = Registry(ROOT)
    github_agent=GithubAgent(DATA/'github',ROOT/'config/github.json')
    source_agents={kind:SourceAgent(kind,store,DATA,ROOT/'config/other_sources.json',processor) for kind in KINDS}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass

        def send(self,data,status=200,kind="application/json; charset=utf-8",download=None):
            body = data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type",kind)
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            if download:
                self.send_header("Content-Disposition",f'attachment; filename="{download}"')
            self.send_header("Content-Length",str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.headers.get("Host") != host:
                return self.send({"error":"잘못된 호스트"},403)
            parsed = urlparse(self.path)
            q = {k:v[0] for k,v in parse_qs(parsed.query).items()}
            if parsed.path=='/sources':
                return self.send((ROOT/'web/sources.html').read_bytes().replace(b'__TOKEN__',token.encode()),kind='text/html; charset=utf-8')
            if parsed.path=='/api/sources/state':
                kind=q.get('kind','youtube')
                if kind not in source_agents:
                    return self.send({'error':'정보원을 확인하세요.'},400)
                return self.send(source_agents[kind].status(q.get('run_id')))
            if parsed.path=='/github':
                return self.send((ROOT/'web/github.html').read_bytes().replace(b'__TOKEN__',token.encode()),kind='text/html; charset=utf-8')
            if parsed.path.startswith('/api/github/'):
                try:
                    if parsed.path=='/api/github/state':
                        return self.send(github_agent.status(q.get('run_id')))
                    if parsed.path=='/api/github/repos':
                        return self.send(github_agent.store.rows(q.get('category',''),q.get('skills')=='1',q.get('sort','stars'),
                            max(0,int(q.get('offset',0))),min(100,max(1,int(q.get('limit',50))))))
                    if parsed.path=='/api/github/repo':
                        return self.send(github_agent.store.detail(q['name']))
                    if parsed.path=='/api/github/export':
                        # Group metadata, files, documents, releases and observations by repo.
                        items=github_agent.store.rows(q.get('category',''),q.get('skills')=='1',q.get('sort','stars'))['items']
                        for item in items:
                            item.update(github_agent.store.detail(item['full_name']))
                        return self.send(json.dumps({'items':items},ensure_ascii=False,indent=2).encode(),download='github-repositories.json')
                    if parsed.path=='/api/github/archive':
                        detail=github_agent.store.detail(q['name'])
                        archive=detail.get('archive',{})
                        root=github_agent.store.root.resolve()
                        path=(root/archive.get('path','')).resolve()
                        if archive.get('state')!='downloaded' or not path.is_relative_to(root/'archives') or not path.is_file() or path.suffix!='.zip':
                            return self.send({'error':'저장한 ZIP이 없습니다.'},404)
                        self.send_response(200)
                        self.send_header('Content-Type','application/zip')
                        self.send_header('Content-Disposition','attachment; filename="repository.zip"')
                        self.send_header('Content-Length',str(path.stat().st_size))
                        self.send_header('X-Content-Type-Options','nosniff')
                        self.end_headers()
                        with path.open('rb') as stream:
                            while chunk:=stream.read(128*1024):
                                self.wfile.write(chunk)
                        return
                except (ValueError,KeyError,TypeError) as exc:
                    return self.send({'error':str(exc)},400)
                return self.send({'error':'없는 GitHub 경로'},404)
            if parsed.path.startswith('/media/'):
                root=(DATA/'media').resolve()
                path=(root/unquote(parsed.path[len('/media/'):])).resolve()
                if not path.is_relative_to(root) or not path.is_file() or path.suffix not in MIME_EXT.values():
                    return self.send({'error':'파일을 찾지 못했습니다.'},404)
                content_type=next((k for k,v in MIME_EXT.items() if v==path.suffix),'application/octet-stream')
                self.send_response(200)
                self.send_header('Content-Type',content_type)
                self.send_header('Content-Length',str(path.stat().st_size))
                self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('Cache-Control','no-store')
                self.end_headers()
                with path.open('rb') as stream:
                    while chunk:=stream.read(128*1024):
                        self.wfile.write(chunk)
                return
            if parsed.path == "/":
                return self.send((ROOT/"web/index.html").read_bytes().replace(b"__TOKEN__",token.encode()),kind="text/html; charset=utf-8")
            if parsed.path == "/api/state":
                with store.connect() as db:
                    runs = [dict(r) for r in db.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT 20")]
                run_id = q.get("run_id") or (runs[0]["id"] if runs else "")
                return self.send({"accounts":accounts(),"categories":registry.categories(),"processing":processor.status(),"runs":runs,"tasks":store.tasks(run_id),"defaults":{"start":months_ago(now().astimezone(KST)).date().isoformat(),"end":now().astimezone(KST).date().isoformat()},
                                  "login":{"instagram":(PRIVATE/"instagram.json").exists(),"x":(PRIVATE/"x-accounts.db").exists()}})
            if parsed.path in ("/api/posts","/export"):
                try:
                    limit = -1 if parsed.path=="/export" else min(200,max(1,int(q.get("limit",100))))
                    result=store.rows(q.get("platform",""),q.get("handle",""),max(0,int(q.get("offset",0))),limit,q.get("sort","date"),q.get('category',''))
                except ValueError:
                    return self.send({"error":"잘못된 조회 값"},400)
                if parsed.path=="/export":
                    if q.get("format")=="csv":
                        out=io.StringIO(newline="")
                        writer=csv.writer(out)
                        keys=["platform","post_id","handle","url","posted_at","text","metrics","media","processing","collected_at"]
                        writer.writerow(keys)
                        for row in result["items"]:
                            cells=[]
                            for key in keys:
                                value=str(row[key]) if not isinstance(row[key],(dict,list)) else json.dumps(row[key],ensure_ascii=False)
                                if value.lstrip().startswith(("=","+","-","@")):
                                    value="'"+value
                                cells.append(value)
                            writer.writerow(cells)
                        return self.send(out.getvalue().encode("utf-8-sig"),kind="text/csv; charset=utf-8",download="posts.csv")
                    return self.send(json.dumps(result,ensure_ascii=False,indent=2).encode(),download="posts.json")
                return self.send(result)
            return self.send({"error":"없는 경로"},404)

        def do_POST(self):
            if self.headers.get("Host")!=host or self.headers.get("X-Raider-Token")!=token:
                return self.send({"error":"허용되지 않은 요청"},403)
            try:
                size=int(self.headers.get("Content-Length",0))
                if not 0<size<=100000:
                    raise ValueError("요청 크기를 확인하세요.")
                body=json.loads(self.rfile.read(size))
                if not isinstance(body,dict):
                    raise ValueError('요청 형식을 확인하세요.')
                if self.path.startswith('/api/sources/'):
                    kind=body.get('kind')
                    if kind not in source_agents:
                        raise ValueError('정보원을 확인하세요.')
                    agent=source_agents[kind]
                    if self.path=='/api/sources/start':
                        return self.send({'run_id':agent.start(body)})
                    if self.path=='/api/sources/resume':
                        return self.send({'run_id':agent.start(run_id=body['run_id'])})
                    if self.path=='/api/sources/stop':
                        agent.stop.set()
                        return self.send({'ok':True})
                    raise ValueError('없는 정보원 요청입니다.')
                if self.path=='/api/github/start':
                    return self.send({'run_id':github_agent.start(body)})
                if self.path=='/api/github/resume':
                    return self.send({'run_id':github_agent.start(run_id=body['run_id'])})
                if self.path=='/api/github/stop':
                    github_agent.stop.set()
                    return self.send({'ok':True})
                if self.path=='/api/github/category':
                    github_agent.store.assign(body['name'],body['category'])
                    return self.send({'ok':True})
                if self.path=='/api/processing/retry':
                    # Page through saved records; this never starts a social-network crawl.
                    offset=0
                    queued=0
                    while True:
                        rows=store.rows(body.get('platform',''),body.get('handle',''),offset,200)['items']
                        if not rows:
                            break
                        for post in rows:
                            if not body.get('post_id') or post['post_id']==str(body['post_id']):
                                queued+=int(processor.enqueue(post,force=True))
                        offset+=len(rows)
                    return self.send({'queued':queued})
                if self.path=='/api/accounts/preview':
                    return self.send(registry.preview(body['platform'],body['text']))
                if self.path=='/api/accounts/add':
                    return self.send(registry.add(body['platform'],body['text'],body.get('category','미분류')))
                if self.path=='/api/categories/add':
                    return self.send(registry.add_category(body['platform'],body['name']))
                if self.path=='/api/accounts/category':
                    registry.assign(body['platform'],body['handle'],body['category'])
                    return self.send({'ok':True})
                if self.path=="/api/stop":
                    runner.stop.set()
                    return self.send({"ok":True})
                if self.path=="/api/resume":
                    runner.start(body["run_id"])
                    return self.send({"ok":True})
                if self.path=="/api/start":
                    if runner.thread and runner.thread.is_alive():
                        raise ValueError("현재 수집 중입니다.")
                    keys=set(body["accounts"])
                    chosen=[a for a in accounts() if f"{a['platform']}:{a['handle']}" in keys]
                    if not chosen:
                        raise ValueError("계정을 하나 이상 선택하세요.")
                    begin,finish=window(body.get("start"),body.get("end"))
                    run_id=store.create_run(chosen,begin,finish,bool(body.get('download_media',True)))
                    runner.start(run_id)
                    return self.send({"run_id":run_id})
                return self.send({"error":"없는 경로"},404)
            except (ValueError,KeyError,TypeError) as exc:
                return self.send({"error":str(exc)},400)

    print(f"AI Raider: http://{host} (종료: Ctrl+C)")
    server=ThreadingHTTPServer(("127.0.0.1",port),Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        runner.stop.set()
    finally:
        processor.stop.set()
        github_agent.stop.set()
        for agent in source_agents.values():
            agent.stop.set()
        processor.wake.set()
        processor.thread.join(timeout=3)
        server.server_close()


def main():
    parser=argparse.ArgumentParser(description="AI Raider 수집 관리")
    commands=parser.add_subparsers(dest="command",required=True)
    server=commands.add_parser("serve")
    server.add_argument("--port",type=int,default=8765)
    commands.add_parser("login-instagram")
    commands.add_parser("check")
    commands.add_parser('prepare-processing',help='한국어·영어 OCR 및 Whisper 모델을 로컬에 준비')
    gh=commands.add_parser('github',help='GitHub 전담 수집 에이전트')
    gh.add_argument('--mode',choices=['baseline','recent','watch'],default='baseline')
    gh.add_argument('--repos',default='',help='owner/repo 목록(쉼표 또는 공백)')
    gh.add_argument('--query',action='append',help='반복 지정 가능. 생략하면 기본 검색식 사용')
    gh.add_argument('--min-stars',type=int,default=1000)
    gh.add_argument('--limit-per-query',type=int,default=100)
    gh.add_argument('--since',help='최근 발견 및 릴리스 기준일 YYYY-MM-DD')
    gh.add_argument('--archive-mb',type=int,default=512)
    gh.add_argument('--metadata-only',action='store_true')
    gh.add_argument('--resume',help='기존 작업 ID 이어받기')
    source=commands.add_parser('source',help='YouTube·뉴스·허깅페이스·갤러리 전담 추출')
    source.add_argument('kind',choices=list(KINDS))
    source.add_argument('--target',action='append',help='반복 지정 가능')
    source.add_argument('--start')
    source.add_argument('--end')
    source.add_argument('--limit',type=int,default=30)
    source.add_argument('--pages',type=int,default=100)
    source.add_argument('--max-mb',type=int,default=512)
    source.add_argument('--metadata-only',action='store_true')
    source.add_argument('--browser',action='store_true')
    source.add_argument('--resume')
    login=commands.add_parser('source-browser-login',help='별도 수집용 Edge 프로필에서 사용자 로그인')
    login.add_argument('url')
    args=parser.parse_args()
    if args.command=="serve":
        serve(args.port)
    elif args.command=='prepare-processing':
        prepare(DATA)
    elif args.command=='source-browser-login':
        from source_tools import public_url
        public_url(args.url)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            context=p.chromium.launch_persistent_context(str(PRIVATE/'source-browser'),channel='msedge',headless=False)
            try:
                context.new_page().goto(args.url,wait_until='domcontentloaded')
                input('브라우저에서 직접 로그인·인증을 완료한 후 Enter: ')
            finally:
                context.close()
    elif args.command=='source':
        store=Store();processor=Processor(store,DATA);processor.start()
        agent=SourceAgent(args.kind,store,DATA,ROOT/'config/other_sources.json',processor)
        body=vars(args).copy()
        if args.target is not None:
            body['targets']=args.target
        body['download_media']=not args.metadata_only
        run=agent.start(body,run_id=args.resume)
        print('Source run:',run,flush=True)
        try:
            while agent.thread.is_alive():
                agent.thread.join(timeout=1)
        except KeyboardInterrupt:
            agent.stop.set();agent.thread.join(timeout=50)
        finally:
            processor.stop.set();processor.wake.set()
        print(json.dumps(agent.status(run),ensure_ascii=False,indent=2))
    elif args.command=='github':
        agent=GithubAgent(DATA/'github',ROOT/'config/github.json')
        body=vars(args).copy()
        body.update(queries=args.query if args.query is not None else ([] if args.repos else agent.defaults()['queries']),download_archive=not args.metadata_only)
        run_id=agent.start(body,run_id=args.resume)
        print('GitHub run:',run_id,flush=True)
        try:
            while agent.thread.is_alive():
                agent.thread.join(timeout=1)
        except KeyboardInterrupt:
            agent.stop.set()
            agent.thread.join(timeout=50)
        print(json.dumps(agent.status(run_id),ensure_ascii=False,indent=2))
    elif args.command=="check":
        print(json.dumps({"accounts":len(accounts()),"default_start":months_ago(now().astimezone(KST)).isoformat(),"end":now().astimezone(KST).isoformat()},ensure_ascii=False,indent=2))
    else:
        import instaloader
        PRIVATE.mkdir(exist_ok=True)
        username=input("Instagram 로그인 아이디: ").strip()
        loader=instaloader.Instaloader()
        loader.interactive_login(username)
        loader.save_session_to_file(str(PRIVATE/"instagram.session"))
        (PRIVATE/"instagram.json").write_text(json.dumps({"username":username}),encoding="utf-8")
        print("Instagram 세션을 로컬 .private 폴더에 저장했습니다.")


if __name__=="__main__":
    main()
