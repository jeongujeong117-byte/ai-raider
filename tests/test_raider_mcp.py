import asyncio
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import raider_mcp
from raider_mcp import PostReader, ReaderError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = """CREATE TABLE posts (platform TEXT, post_id TEXT, handle TEXT, url TEXT, posted_at TEXT,
  text TEXT, metrics TEXT, media TEXT, collected_at TEXT, raw TEXT, PRIMARY KEY(platform, post_id));"""


def make_db(path, rows=()):
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    for r in rows:
        db.execute("INSERT INTO posts VALUES (?,?,?,?,?,?,?,?,?,?)", r)
    db.commit()
    db.close()


def row(platform, pid, handle="h", posted="2026-01-01", text="t", metrics='{"likes": null, "n": 0}', media="[]", raw="{}"):
    return (platform, pid, handle, f"https://x/{pid}", posted, text, metrics, media, "2026-01-02", raw)


def fingerprint(path):
    db = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
    tables = sorted(r[0] for r in db.execute("SELECT name FROM sqlite_master"))
    db.close()
    return hashlib.sha256(Path(path).read_bytes()).hexdigest(), os.stat(path).st_mtime_ns, tables


class ReaderCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "r.sqlite")

    def test_missing_db_not_created(self):
        with self.assertRaises(FileNotFoundError):
            PostReader(self.path)
        self.assertFalse(Path(self.path).exists())

    def test_empty_and_missing_post(self):
        make_db(self.path)
        r = PostReader(self.path)
        self.assertEqual(r.list_posts(), {"total": 0, "items": []})
        self.assertIsNone(r.get_post("x", "1"))

    def test_same_id_other_platform_and_fields(self):
        make_db(self.path, [row("x", "1", text="from x"), row("instagram", "1", text="from ig")])
        r = PostReader(self.path)
        self.assertEqual(r.get_post("x", "1")["text"], "from x")
        self.assertEqual(r.get_post("instagram", "1")["text"], "from ig")
        self.assertEqual(set(r.get_post("x", "1")), set(raider_mcp._COLUMNS))

    def test_order_paging_total(self):
        make_db(self.path, [row("x", str(i), posted=f"2026-01-0{i}") for i in range(1, 6)] + [row("a", "9", posted="2026-01-05")])
        r = PostReader(self.path)
        page = r.list_posts(offset=1, limit=2)
        self.assertEqual(page["total"], 6)
        self.assertEqual([(p["platform"], p["post_id"]) for p in page["items"]], [("x", "5"), ("x", "4")])
        self.assertEqual(r.list_posts()["items"][0]["platform"], "a")
        self.assertEqual(r.list_posts(platform="x", limit=1)["total"], 5)

    def test_none_empty_large_preserved(self):
        big = json.dumps({"blob": "z" * 300000})
        make_db(self.path, [row("x", "1", text="", metrics=None, media=None, raw=big),
                            row("x", "2", metrics='{"likes": 0}', text=None)])
        r = PostReader(self.path)
        p = r.get_post("x", "1")
        self.assertEqual(p["text"], "")
        self.assertIsNone(p["metrics"])
        self.assertIsNone(p["media"])
        self.assertEqual(len(p["raw"]["blob"]), 300000)
        self.assertEqual(r.get_post("x", "2")["metrics"], {"likes": 0})
        self.assertIsNone(r.get_post("x", "2")["text"])

    def test_injection_filter_is_literal(self):
        make_db(self.path, [row("x", "1", handle="a")])
        r = PostReader(self.path)
        for bad in ("' OR '1'='1", "a'; DROP TABLE posts;--"):
            self.assertEqual(r.list_posts(handle=bad)["total"], 0)
        self.assertEqual(r.list_posts()["total"], 1)

    def test_invalid_input(self):
        make_db(self.path)
        r = PostReader(self.path)
        for kw in ({"limit": 0}, {"limit": 501}, {"limit": True}, {"limit": "1"}, {"offset": -1},
                   {"offset": True}, {"platform": 1}, {"handle": None}):
            with self.assertRaises(ValueError, msg=kw):
                r.list_posts(**kw)
            with self.assertRaises(ValueError, msg=kw):
                r.list_unanalyzed(**kw)
        for args in (("", "1"), ("x", ""), ("x", "  "), (1, "1"), ("x", None)):
            with self.assertRaises(ValueError, msg=args):
                r.get_post(*args)

    def test_unanalyzed_no_table_all_unanalyzed_and_no_creation(self):
        make_db(self.path, [row("x", "1"), row("x", "2")])
        before = fingerprint(self.path)
        self.assertEqual(PostReader(self.path).list_unanalyzed()["total"], 2)
        self.assertEqual(fingerprint(self.path), before)

    def test_unanalyzed_with_table(self):
        make_db(self.path, [row("x", "1"), row("x", "2"), row("ig", "1")])
        db = sqlite3.connect(self.path)
        db.execute("CREATE TABLE post_analyses (platform TEXT, post_id TEXT, summary TEXT)")
        db.execute("INSERT INTO post_analyses VALUES ('x','1','s')")
        db.commit()
        db.close()
        got = PostReader(self.path).list_unanalyzed()
        self.assertEqual(sorted((p["platform"], p["post_id"]) for p in got["items"]), [("ig", "1"), ("x", "2")])
        self.assertEqual(got["total"], 2)

    def test_processing_table_is_not_analysis(self):
        make_db(self.path, [row("x", "1")])
        db = sqlite3.connect(self.path)
        db.execute("CREATE TABLE processing (platform TEXT, post_id TEXT, state TEXT)")
        db.execute("INSERT INTO processing VALUES ('x','1','done')")
        db.commit()
        db.close()
        self.assertEqual(PostReader(self.path).list_unanalyzed()["total"], 1)

    def test_unanalyzed_corrupt_table_surfaces_error(self):
        make_db(self.path, [row("x", "1")])
        db = sqlite3.connect(self.path)
        db.execute("CREATE TABLE post_analyses (foo TEXT)")
        db.commit()
        db.close()
        with self.assertRaises(ReaderError):
            PostReader(self.path).list_unanalyzed()
        self.assertEqual(PostReader(self.path).list_posts()["total"], 1)

    def test_corrupt_json_and_safe_errors(self):
        make_db(self.path, [row("x", "1", raw="{broken")])
        r = PostReader(self.path)
        with self.assertRaises(ReaderError) as c:
            r.get_post("x", "1")
        self.assertNotIn(self.tmp.name, str(c.exception))
        other = str(Path(self.tmp.name) / "empty.sqlite")
        sqlite3.connect(other).close()
        with self.assertRaises(ReaderError) as c:
            PostReader(other).list_posts()
        msg = str(c.exception)
        self.assertEqual(msg, "database query failed")
        self.assertNotIn(self.tmp.name, msg)

    def test_write_attempt_impossible(self):
        make_db(self.path, [row("x", "1")])
        db = PostReader(self.path)._connect()
        with self.assertRaises(sqlite3.Error):
            db.execute("DELETE FROM posts")
        db.close()
        self.assertEqual(PostReader(self.path).list_posts()["total"], 1)


try:
    import mcp  # noqa: F401
    HAVE_MCP = True
except ImportError:
    HAVE_MCP = False


@unittest.skipUnless(HAVE_MCP, "optional extra 'mcp' not installed")
class ServerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "s.sqlite")
        make_db(self.path, [row("x", "1", text="one", metrics=None), row("ig", "1", text="two"),
                            row("x", "2", handle="bad", posted="2026-02-01", raw="{bad")])
        db = sqlite3.connect(self.path)
        db.execute("CREATE TABLE post_analyses (platform TEXT, post_id TEXT)")
        db.execute("INSERT INTO post_analyses VALUES ('x','1')")
        db.commit()
        db.close()

    def _run(self, scenario):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "raider_mcp.py"), "--db", self.path], cwd=str(ROOT))

        async def go():
            async with stdio_client(params) as (r, w):
                async with ClientSession(r, w) as s:
                    await s.initialize()
                    return await scenario(s)
        return asyncio.run(asyncio.wait_for(go(), 60))

    def test_tools_over_stdio(self):
        before = fingerprint(self.path)

        async def scenario(s):
            tools = (await s.list_tools()).tools
            names = sorted(t.name for t in tools)
            self.assertTrue(all(t.annotations and t.annotations.readOnlyHint for t in tools))
            lst = await s.call_tool("list_posts", {"handle": "h", "limit": 1})
            one = await s.call_tool("get_post", {"platform": "ig", "post_id": "1"})
            none = await s.call_tool("get_post", {"platform": "ig", "post_id": "nope"})
            un = await s.call_tool("list_unanalyzed", {"handle": "h"})
            badlimit = await s.call_tool("list_posts", {"limit": 0})
            badjson = await s.call_tool("get_post", {"platform": "x", "post_id": "2"})
            return names, lst, one, none, un, badlimit, badjson

        names, lst, one, none, un, badlimit, badjson = self._run(scenario)
        self.assertEqual(names, ["get_post", "list_posts", "list_unanalyzed"])
        data = lst.structuredContent
        self.assertEqual(data["total"], 2)
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(one.structuredContent["result"]["text"], "two")
        self.assertFalse(none.isError)
        self.assertEqual(sorted(p["post_id"] for p in un.structuredContent["items"]), ["1"])
        self.assertEqual(un.structuredContent["total"], 1)
        self.assertTrue(badlimit.isError)
        self.assertTrue(badjson.isError)
        text = badjson.content[0].text
        self.assertNotIn(self.tmp.name, text)
        self.assertNotIn("Traceback", text)
        self.assertEqual(fingerprint(self.path), before)

    def test_strict_argument_types_over_stdio(self):
        bad_cases = [
            ("list_posts", {"limit": True}), ("list_posts", {"limit": "2"}), ("list_posts", {"limit": 2.0}),
            ("list_posts", {"limit": 1.5}), ("list_posts", {"limit": None}), ("list_posts", {"offset": False}),
            ("list_posts", {"offset": "0"}), ("list_posts", {"offset": 0.0}), ("list_posts", {"offset": None}),
            ("list_posts", {"platform": 1}), ("list_posts", {"handle": True}), ("list_posts", {"platform": None}),
            ("list_unanalyzed", {"limit": True}), ("list_unanalyzed", {"limit": "2"}), ("list_unanalyzed", {"limit": 2.0}),
            ("list_unanalyzed", {"limit": None}), ("list_unanalyzed", {"offset": False}), ("list_unanalyzed", {"offset": "0"}),
            ("list_unanalyzed", {"offset": 0.0}), ("list_unanalyzed", {"offset": None}),
            ("list_unanalyzed", {"platform": 5}), ("list_unanalyzed", {"handle": ["h"]}),
            ("get_post", {"platform": 1, "post_id": "1"}), ("get_post", {"platform": "x", "post_id": 1}),
            ("get_post", {"platform": "x", "post_id": None}), ("get_post", {"platform": "x", "post_id": True}),
        ]
        good_cases = [("list_posts", {"handle": "h", "limit": 2, "offset": 0}), ("list_unanalyzed", {"handle": "h", "limit": 500, "offset": 0}),
                      ("get_post", {"platform": "x", "post_id": "1"})]

        async def scenario(s):
            bad = [(n, a, (await s.call_tool(n, a)).isError) for n, a in bad_cases]
            good = [(n, a, (await s.call_tool(n, a)).isError) for n, a in good_cases]
            return bad, good

        bad, good = self._run(scenario)
        for n, a, err in bad:
            self.assertTrue(err, f"{n} {a} should be rejected")
        for n, a, err in good:
            self.assertFalse(err, f"{n} {a} should succeed")

    def test_stdout_only_protocol(self):
        proc = subprocess.Popen([sys.executable, str(ROOT / "raider_mcp.py"), "--db", self.path], cwd=str(ROOT),
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}
            note = {"jsonrpc": "2.0", "method": "notifications/initialized"}
            call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "list_posts", "arguments": {}}}
            for m in (init, note, call):
                proc.stdin.write((json.dumps(m) + "\n").encode())
                proc.stdin.flush()
            lines = [proc.stdout.readline().decode(), proc.stdout.readline().decode()]
            proc.stdin.close()
            rest = proc.stdout.read()
            proc.wait(timeout=30)
        finally:
            proc.kill()
            for f in (proc.stdin, proc.stdout, proc.stderr):
                f.close()
        self.assertEqual(rest, b"")
        lines = [l for l in lines if l.strip()]
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertEqual(json.loads(line)["jsonrpc"], "2.0")

    def test_missing_db_server_does_not_create(self):
        missing = str(Path(self.tmp.name) / "nope.sqlite")
        res = subprocess.run([sys.executable, str(ROOT / "raider_mcp.py"), "--db", missing], cwd=str(ROOT),
                             capture_output=True, timeout=60, stdin=subprocess.DEVNULL)
        self.assertNotEqual(res.returncode, 0)
        self.assertEqual(res.stdout, b"")
        self.assertFalse(Path(missing).exists())

    def test_import_has_no_side_effects(self):
        res = subprocess.run([sys.executable, "-c", "import raider_mcp, threading; print(threading.active_count())"],
                             cwd=str(ROOT), capture_output=True, timeout=60)
        self.assertEqual(res.stdout.strip(), b"1")


if __name__ == "__main__":
    unittest.main()
