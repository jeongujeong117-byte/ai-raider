"""SQLite store for collected posts, social collection runs/tasks and processing results."""
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

from core import common
from core.common import now
from core.source_manager import Registry


class Store:
    def __init__(self, path=None):
        self.path = Path(path or common.DATA / "raider.sqlite")
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

    def _accounts(self):
        """Registered accounts for category filters; raider.Store binds this to raider.accounts()."""
        return Registry(common.ROOT).accounts()

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
            names=[a['handle'] for a in self._accounts() if a['category']==category and (not platform or a['platform']==platform)]
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
