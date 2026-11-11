"""Blackbox verification tests for T-002: Read-only Post Query MCP Server.

Verifies:
1. PostReader initialization, read-only constraints, connection cleanup, and Store separation.
2. list_posts query semantics: filtering, multi-key ordering, pre-page totals, pagination boundaries.
3. get_post query semantics: non-empty string validation, cross-platform isolation, null for missing.
4. list_unanalyzed semantics: presence/absence of post_analyses, processing table ignored, corrupt schema errors.
5. Content fidelity and error hygiene: metrics likes null vs 0, empty text, 300k+ unicode text, corrupt JSON, no secret/path leaks.
6. MCP protocol over stdio: tool declarations, read-only annotations, end-to-end tool calls, and SDK coercion contrast.
7. Non-mutation guarantees & WAL mode semantics: hash/mtime invariants, write rejection, WAL uncheckpointed commit visibility, and sidecar observations.
"""
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

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import raider_mcp
from raider_mcp import PostReader, ReaderError

try:
    import mcp  # noqa: F401
    HAVE_MCP = True
except ImportError:
    HAVE_MCP = False

POSTS_SCHEMA = """CREATE TABLE posts (
    platform TEXT,
    post_id TEXT,
    handle TEXT,
    url TEXT,
    posted_at TEXT,
    text TEXT,
    metrics TEXT,
    media TEXT,
    collected_at TEXT,
    raw TEXT,
    PRIMARY KEY(platform, post_id)
);"""


def make_fixture_db(path, rows=(), journal_mode="DELETE"):
    conn = sqlite3.connect(path)
    if journal_mode.upper() != "DELETE":
        conn.execute(f"PRAGMA journal_mode = {journal_mode}")
    conn.executescript(POSTS_SCHEMA)
    for r in rows:
        conn.execute("INSERT INTO posts VALUES (?,?,?,?,?,?,?,?,?,?)", r)
    conn.commit()
    conn.close()


def make_post_row(
    platform="x",
    post_id="1",
    handle="tester",
    posted_at="2026-01-01T00:00:00Z",
    text="content",
    metrics='{"likes": null, "reposts": 0}',
    media="[]",
    raw="{}",
    collected_at="2026-01-01T01:00:00Z",
    url=None,
):
    return (
        platform,
        post_id,
        handle,
        url or f"https://{platform}.example.com/{handle}/{post_id}",
        posted_at,
        text,
        metrics,
        media,
        collected_at,
        raw,
    )


def compute_file_fingerprint(path):
    p = Path(path)
    content = p.read_bytes()
    sha = hashlib.sha256(content).hexdigest()
    mtime_ns = p.stat().st_mtime_ns
    conn = sqlite3.connect(f"{p.resolve().as_uri()}?mode=ro", uri=True)
    tables = sorted(r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"))
    conn.close()
    return sha, mtime_ns, tables


class BlackboxReaderTests(unittest.TestCase):
    """Direct API validation of PostReader semantics, safety, and invariants."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = str(Path(self.tmp.name) / "test_reader.sqlite")

    def test_01_store_separation_and_missing_file_safety(self):
        """PostReader does not import or call Store constructor, and rejects missing DB without creating it."""
        # 1. Verify PostReader module does not import Store
        self.assertFalse(hasattr(raider_mcp, "Store"), "raider_mcp must not expose Store")
        import inspect
        src = inspect.getsource(raider_mcp)
        self.assertNotIn("Store(", src, "PostReader must not invoke Store constructor")
        self.assertNotIn("from core.store import Store", src)

        # 2. Missing DB raises FileNotFoundError and does not create file
        missing_path = str(Path(self.tmp.name) / "nonexistent.sqlite")
        with self.assertRaises(FileNotFoundError):
            PostReader(missing_path)
        self.assertFalse(Path(missing_path).exists(), "Missing DB must not be created")

    def test_02_readonly_mode_query_only_and_connection_cleanup(self):
        """PostReader uses mode=ro and query_only, blocks mutations, and releases connections."""
        make_fixture_db(self.db_path, [make_post_row("x", "101")])
        reader = PostReader(self.db_path)

        # Direct connection mutation attempt must fail
        db_conn = reader._connect()
        try:
            with self.assertRaises(sqlite3.Error):
                db_conn.execute("DELETE FROM posts")
            with self.assertRaises(sqlite3.Error):
                db_conn.execute("INSERT INTO posts VALUES ('x','102','h','u','t','txt','{}','[]','c','{}')")
            with self.assertRaises(sqlite3.Error):
                db_conn.execute("UPDATE posts SET text='hacked'")
        finally:
            db_conn.close()

        # Check connection cleanup: files should not remain locked on Windows
        res = reader.list_posts()
        self.assertEqual(res["total"], 1)
        # Verify file can be renamed or modified externally (shows connection was closed)
        temp_rename = str(Path(self.tmp.name) / "renamed.sqlite")
        os.rename(self.db_path, temp_rename)
        os.rename(temp_rename, self.db_path)

    def test_03_list_posts_ordering_and_pagination(self):
        """list_posts implements posted_at DESC, platform ASC, post_id DESC ordering and paging."""
        # Create records to test 3-tier ordering:
        # 1. Different dates: 2026-03-01 vs 2026-01-01
        # 2. Same date, different platform: 'bluesky' vs 'x'
        # 3. Same date, same platform, different post_id: 'post_90' vs 'post_10'
        rows = [
            make_post_row("x", "1", posted_at="2026-01-01T00:00:00Z"),
            make_post_row("x", "post_10", posted_at="2026-02-01T12:00:00Z"),
            make_post_row("x", "post_90", posted_at="2026-02-01T12:00:00Z"),
            make_post_row("bluesky", "post_50", posted_at="2026-02-01T12:00:00Z"),
            make_post_row("threads", "2", posted_at="2026-03-01T00:00:00Z"),
        ]
        make_fixture_db(self.db_path, rows)
        reader = PostReader(self.db_path)

        # Full list ordering check
        all_res = reader.list_posts(limit=100)
        self.assertEqual(all_res["total"], 5)
        expected_order = [
            ("threads", "2"),        # 2026-03-01
            ("bluesky", "post_50"),  # 2026-02-01, platform 'bluesky' < 'x'
            ("x", "post_90"),        # 2026-02-01, platform 'x', 'post_90' > 'post_10' DESC
            ("x", "post_10"),        # 2026-02-01, platform 'x', 'post_10'
            ("x", "1"),              # 2026-01-01
        ]
        actual_order = [(p["platform"], p["post_id"]) for p in all_res["items"]]
        self.assertEqual(actual_order, expected_order)

        # Paging: offset=1, limit=2
        page = reader.list_posts(offset=1, limit=2)
        self.assertEqual(page["total"], 5, "total must reflect pre-paging match count")
        self.assertEqual([(p["platform"], p["post_id"]) for p in page["items"]], expected_order[1:3])

        # Page boundary: offset >= total
        empty_page = reader.list_posts(offset=5, limit=10)
        self.assertEqual(empty_page["total"], 5)
        self.assertEqual(empty_page["items"], [])

        # Limit upper bound (500)
        max_limit_res = reader.list_posts(limit=500)
        self.assertEqual(len(max_limit_res["items"]), 5)

    def test_04_list_posts_strict_input_validation(self):
        """list_posts strictly rejects booleans, out-of-range limits, and non-string filters."""
        make_fixture_db(self.db_path, [make_post_row("x", "1")])
        reader = PostReader(self.db_path)

        # limit validation: int 1..500
        for bad_limit in [0, -1, 501, True, False, "10", 1.5, None, []]:
            with self.assertRaises(ValueError, msg=f"Should reject limit={bad_limit!r}"):
                reader.list_posts(limit=bad_limit)

        # offset validation: int >= 0
        for bad_offset in [-1, True, False, "0", 0.0, None, {}]:
            with self.assertRaises(ValueError, msg=f"Should reject offset={bad_offset!r}"):
                reader.list_posts(offset=bad_offset)

        # platform / handle validation: str only
        for bad_str in [123, None, True, False, []]:
            with self.assertRaises(ValueError, msg=f"Should reject platform={bad_str!r}"):
                reader.list_posts(platform=bad_str)
            with self.assertRaises(ValueError, msg=f"Should reject handle={bad_str!r}"):
                reader.list_posts(handle=bad_str)

    def test_05_sql_injection_defense(self):
        """SQL injection attempts in filters are treated as literal strings and do not alter query."""
        make_fixture_db(self.db_path, [make_post_row("x", "1", handle="good_user")])
        reader = PostReader(self.db_path)

        injections = [
            "' OR '1'='1",
            "good_user' --",
            "'; DROP TABLE posts; --",
            "' UNION SELECT 'x','2','h','u','t','txt','{}','[]','c','{}' --",
        ]
        for payload in injections:
            res_handle = reader.list_posts(handle=payload)
            self.assertEqual(res_handle["total"], 0, f"Payload {payload} should match 0 rows")
            self.assertEqual(res_handle["items"], [])

            res_plat = reader.list_posts(platform=payload)
            self.assertEqual(res_plat["total"], 0)

        # Normal query still works intact
        self.assertEqual(reader.list_posts(handle="good_user")["total"], 1)

    def test_06_get_post_semantics_and_platform_isolation(self):
        """get_post isolates same post_id across different platforms and strictly validates keys."""
        rows = [
            make_post_row("x", "common_id", text="Twitter post"),
            make_post_row("instagram", "common_id", text="Instagram post"),
            make_post_row("youtube", "yt_01", text="YouTube post"),
        ]
        make_fixture_db(self.db_path, rows)
        reader = PostReader(self.db_path)

        # Cross-platform isolation
        post_x = reader.get_post("x", "common_id")
        post_ig = reader.get_post("instagram", "common_id")
        self.assertIsNotNone(post_x)
        self.assertIsNotNone(post_ig)
        self.assertEqual(post_x["text"], "Twitter post")
        self.assertEqual(post_ig["text"], "Instagram post")
        self.assertEqual(post_x["platform"], "x")
        self.assertEqual(post_ig["platform"], "instagram")

        # Missing post returns None
        self.assertIsNone(reader.get_post("x", "nonexistent"))
        self.assertIsNone(reader.get_post("unknown_platform", "common_id"))

        # Input validation: non-empty string required
        invalid_keys = ["", "   ", None, 123, True, False, []]
        for bad_plat in invalid_keys:
            with self.assertRaises(ValueError, msg=f"Should reject platform={bad_plat!r}"):
                reader.get_post(bad_plat, "common_id")
        for bad_id in invalid_keys:
            with self.assertRaises(ValueError, msg=f"Should reject post_id={bad_id!r}"):
                reader.get_post("x", bad_id)

    def test_07_list_unanalyzed_comprehensive_matrix(self):
        """list_unanalyzed handles table absence, presence, duplicate/null records, and ignores processing."""
        rows = [
            make_post_row("x", "1", handle="user1"),
            make_post_row("x", "2", handle="user1"),
            make_post_row("instagram", "1", handle="user2"),
            make_post_row("threads", "1", handle="user3"),
        ]
        make_fixture_db(self.db_path, rows)
        reader = PostReader(self.db_path)

        # 1. No post_analyses table: all 4 posts are unanalyzed
        res_no_table = reader.list_unanalyzed()
        self.assertEqual(res_no_table["total"], 4)
        self.assertEqual(len(res_no_table["items"]), 4)

        # 2. Add processing table (OCR/transcription): MUST NOT mark post as analyzed
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE processing (platform TEXT, post_id TEXT, state TEXT, updated_at TEXT)")
        conn.execute("INSERT INTO processing VALUES ('x', '1', 'completed', '2026-01-01')")
        conn.commit()
        conn.close()

        res_with_processing = reader.list_unanalyzed()
        self.assertEqual(res_with_processing["total"], 4, "processing table must not count as analysis")

        # 3. Add post_analyses with normal, duplicate, and NULL records
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE post_analyses (platform TEXT, post_id TEXT, analysis TEXT, confidence REAL)")
        # Normal analysis for x:1
        conn.execute("INSERT INTO post_analyses VALUES ('x', '1', 'ai summary 1', 0.95)")
        # Duplicate analysis record for x:1 (should not break query)
        conn.execute("INSERT INTO post_analyses VALUES ('x', '1', 'duplicate summary', 0.90)")
        # Analysis record with NULL post_id (should not cause null-matching errors)
        conn.execute("INSERT INTO post_analyses VALUES ('x', NULL, 'bad row', 0.0)")
        # Analysis record with NULL platform
        conn.execute("INSERT INTO post_analyses VALUES (NULL, '2', 'bad row 2', 0.0)")
        conn.commit()
        conn.close()

        # Only x:1 should be excluded. x:2, instagram:1, threads:1 remain unanalyzed (total 3)
        res_with_analyses = reader.list_unanalyzed()
        self.assertEqual(res_with_analyses["total"], 3)
        remaining_pairs = {(p["platform"], p["post_id"]) for p in res_with_analyses["items"]}
        self.assertEqual(remaining_pairs, {("x", "2"), ("instagram", "1"), ("threads", "1")})

        # 4. Filters with unanalyzed
        res_filtered = reader.list_unanalyzed(platform="x")
        self.assertEqual(res_filtered["total"], 1)
        self.assertEqual(res_filtered["items"][0]["post_id"], "2")

        # 5. Schema corruption in post_analyses: missing required identity column -> explicit safe error
        conn = sqlite3.connect(self.db_path)
        conn.execute("DROP TABLE post_analyses")
        conn.execute("CREATE TABLE post_analyses (invalid_col1 TEXT, invalid_col2 TEXT)")
        conn.commit()
        conn.close()

        with self.assertRaises(ReaderError) as ctx:
            reader.list_unanalyzed()
        self.assertIn("post_analyses lacks required identity columns", str(ctx.exception))
        # Ensure list_posts still functions normally
        self.assertEqual(reader.list_posts()["total"], 4)

    def test_08_content_fidelity_unicode_none_and_corrupt_data(self):
        """Content fidelity: preserves 300k+ unicode text, keeps likes=None vs likes=0, handles bad JSON."""
        # 300k+ unicode payload with Korean, CJK, and emoji
        large_unicode = "가나다라마바사! 🚀 🌟 🛰️ 💻 🇰🇷 [테스트 데이터]" * 10001  # > 300,000 characters
        self.assertGreater(len(large_unicode), 300000)

        rows = [
            make_post_row("x", "p_none", text="", metrics='{"likes": null, "reposts": 0}'),
            make_post_row("x", "p_zero", text=None, metrics='{"likes": 0, "reposts": 5}'),
            make_post_row("x", "p_large", text=large_unicode, raw=json.dumps({"big": large_unicode})),
            make_post_row("x", "p_corrupt_json", raw="{invalid_json: true,"),
        ]
        make_fixture_db(self.db_path, rows)
        reader = PostReader(self.db_path)

        # 1. Distinguish likes=None from likes=0, preserve empty string and None text
        post_none = reader.get_post("x", "p_none")
        self.assertEqual(post_none["text"], "")
        self.assertIsNone(post_none["metrics"]["likes"])
        self.assertEqual(post_none["metrics"]["reposts"], 0)

        post_zero = reader.get_post("x", "p_zero")
        self.assertIsNone(post_zero["text"])
        self.assertEqual(post_zero["metrics"]["likes"], 0)
        self.assertEqual(post_zero["metrics"]["reposts"], 5)

        # 2. Large unicode text fidelity without truncation
        post_large = reader.get_post("x", "p_large")
        self.assertEqual(len(post_large["text"]), len(large_unicode))
        self.assertEqual(post_large["text"], large_unicode)
        self.assertEqual(post_large["raw"]["big"], large_unicode)

        # 3. Corrupted JSON raises explicit safe ReaderError without path leaks
        with self.assertRaises(ReaderError) as ctx:
            reader.get_post("x", "p_corrupt_json")
        err_msg = str(ctx.exception)
        self.assertEqual(err_msg, "stored post contains invalid JSON")
        self.assertNotIn(self.tmp.name, err_msg)
        self.assertNotIn("SELECT", err_msg)

        # 4. Corrupted database / missing posts table
        empty_db_path = str(Path(self.tmp.name) / "empty_no_table.sqlite")
        sqlite3.connect(empty_db_path).close()
        reader_empty = PostReader(empty_db_path)
        with self.assertRaises(ReaderError) as ctx_empty:
            reader_empty.list_posts()
        self.assertEqual(str(ctx_empty.exception), "database query failed")
        self.assertNotIn(self.tmp.name, str(ctx_empty.exception))

    def test_09_wal_mode_uncheckpointed_visibility_and_sidecars(self):
        """WAL mode visibility: uncheckpointed WAL commits are visible without immutable=1, observe sidecars."""
        # 1. Create DB in WAL mode
        make_fixture_db(self.db_path, [make_post_row("x", "committed_1")], journal_mode="WAL")

        # 2. Write an uncheckpointed row via an open writer connection
        writer = sqlite3.connect(self.db_path)
        writer.execute("INSERT INTO posts VALUES (?,?,?,?,?,?,?,?,?,?)", make_post_row("x", "uncheckpointed_wal_2"))
        writer.commit()

        # Check sidecar files before reading
        parent = Path(self.db_path).parent
        name = Path(self.db_path).name
        sidecars_before = sorted(p.name for p in parent.glob(f"{name}*"))
        self.assertIn(f"{name}-wal", sidecars_before, "WAL file should exist with active writer")

        # 3. Read via PostReader: must see BOTH rows (even the uncheckpointed WAL row)
        reader = PostReader(self.db_path)
        res = reader.list_posts()
        self.assertEqual(res["total"], 2, "PostReader must see uncheckpointed WAL commits")
        ids = {p["post_id"] for p in res["items"]}
        self.assertEqual(ids, {"committed_1", "uncheckpointed_wal_2"})

        # Specific get_post on uncheckpointed row
        p2 = reader.get_post("x", "uncheckpointed_wal_2")
        self.assertIsNotNone(p2)
        self.assertEqual(p2["post_id"], "uncheckpointed_wal_2")

        writer.close()


@unittest.skipUnless(HAVE_MCP, "optional extra 'mcp' not installed")
class BlackboxServerMcpProtocolTests(unittest.TestCase):
    """End-to-end blackbox tests for MCP server running as an independent stdio subprocess."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = str(Path(self.tmp.name) / "mcp_test.sqlite")
        rows = [
            make_post_row("x", "1", handle="dev1", posted_at="2026-01-01T00:00:00Z", text="Hello MCP"),
            make_post_row("x", "2", handle="dev2", posted_at="2026-01-02T00:00:00Z", text="Second post"),
            make_post_row("instagram", "1", handle="igdev", posted_at="2026-01-03T00:00:00Z", text="IG post"),
        ]
        make_fixture_db(self.db_path, rows)

        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE post_analyses (platform TEXT, post_id TEXT)")
        conn.execute("INSERT INTO post_analyses VALUES ('x', '1')")
        conn.commit()
        conn.close()

    def _execute_mcp_session(self, action):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=sys.executable,
            args=[str(ROOT / "raider_mcp.py"), "--db", self.db_path],
            cwd=str(ROOT),
        )

        async def run_client():
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    return await action(session)

        return asyncio.run(asyncio.wait_for(run_client(), timeout=30))

    def test_01_tool_registration_and_annotations(self):
        """MCP server exposes exactly 3 tools with readOnlyHint=True and destructiveHint=False."""
        async def action(session):
            tools_response = await session.list_tools()
            return tools_response.tools

        tools = self._execute_mcp_session(action)
        tool_names = sorted(t.name for t in tools)
        self.assertEqual(tool_names, ["get_post", "list_posts", "list_unanalyzed"])

        for t in tools:
            self.assertIsNotNone(t.annotations, f"Tool {t.name} must have annotations")
            self.assertTrue(t.annotations.readOnlyHint, f"Tool {t.name} must be readOnlyHint=True")
            self.assertFalse(t.annotations.destructiveHint, f"Tool {t.name} must be destructiveHint=False")

    def test_02_call_tool_queries_and_null_behavior(self):
        """call_tool executes list_posts, get_post, and list_unanalyzed with structured responses."""
        sha_before, mtime_before, tables_before = compute_file_fingerprint(self.db_path)

        async def action(session):
            # 1. list_posts
            res_list = await session.call_tool("list_posts", {"platform": "x", "limit": 10})
            # 2. get_post existing
            res_get = await session.call_tool("get_post", {"platform": "x", "post_id": "2"})
            # 3. get_post non-existing -> null result
            res_none = await session.call_tool("get_post", {"platform": "x", "post_id": "nonexistent"})
            # 4. list_unanalyzed -> x:1 is analyzed, x:2 and ig:1 are unanalyzed (total 2)
            res_un = await session.call_tool("list_unanalyzed", {})
            return res_list, res_get, res_none, res_un

        res_list, res_get, res_none, res_un = self._execute_mcp_session(action)

        self.assertFalse(res_list.isError)
        self.assertEqual(res_list.structuredContent["total"], 2)  # x:1, x:2

        self.assertFalse(res_get.isError)
        self.assertEqual(res_get.structuredContent["result"]["text"], "Second post")

        self.assertFalse(res_none.isError)
        self.assertIsNone(res_none.structuredContent["result"])

        self.assertFalse(res_un.isError)
        self.assertEqual(res_un.structuredContent["total"], 2)

        # Database must remain completely unmodified
        sha_after, mtime_after, tables_after = compute_file_fingerprint(self.db_path)
        self.assertEqual(sha_after, sha_before)
        self.assertEqual(mtime_after, mtime_before)
        self.assertEqual(tables_after, tables_before)

    def test_03_error_handling_and_safe_redaction(self):
        """Server errors return isError=True and never leak DB path, SQL, or secrets."""
        # Insert a corrupt json row to test error handling
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO posts VALUES (?,?,?,?,?,?,?,?,?,?)", make_post_row("x", "corrupt", raw="{corrupted_json"))
        conn.commit()
        conn.close()

        async def action(session):
            # Corrupted JSON post query
            err_json = await session.call_tool("get_post", {"platform": "x", "post_id": "corrupt"})
            # Out-of-range limit (0)
            err_limit = await session.call_tool("list_posts", {"limit": 0})
            # Empty platform
            err_plat = await session.call_tool("get_post", {"platform": "", "post_id": "1"})
            return err_json, err_limit, err_plat

        err_json, err_limit, err_plat = self._execute_mcp_session(action)

        for res in (err_json, err_limit, err_plat):
            self.assertTrue(res.isError)
            self.assertTrue(res.content)
            for c in res.content:
                text = getattr(c, "text", str(c))
                self.assertNotIn(self.tmp.name, text, "Error response must not leak temp DB path")
                self.assertNotIn("Traceback", text, "Error response must not leak stack traces")

    def test_04_sdk_coercion_contrast_analysis(self):
        """Contrast direct API validation vs MCP SDK argument coercion behavior.

        Direct API rejects bools and string numbers for int fields (limit=True, limit='10').
        FastMCP / Pydantic v2 in default lax mode coerces JSON bool `true` to `1` and string `"10"` to `10`.
        This test documents and asserts this architectural boundary behavior.
        """
        reader = PostReader(self.db_path)

        # 1. Direct API boundary assertions: strictly raises ValueError
        with self.assertRaises(ValueError):
            reader.list_posts(limit=True)
        with self.assertRaises(ValueError):
            reader.list_posts(limit="10")
        with self.assertRaises(ValueError):
            reader.list_posts(offset=False)
        with self.assertRaises(ValueError):
            reader.list_posts(offset="0")

        # 2. MCP stdio boundary assertions: FastMCP/Pydantic lax coercion
        async def action(session):
            # JSON bool `true` coerced to int 1 by Pydantic before reaching reader
            coerced_bool = await session.call_tool("list_posts", {"limit": True})
            # JSON string `"2"` coerced to int 2 by Pydantic
            coerced_str = await session.call_tool("list_posts", {"limit": "2"})
            # JSON string `"bad"` cannot be coerced to int -> Pydantic validation error
            invalid_str = await session.call_tool("list_posts", {"limit": "bad"})
            return coerced_bool, coerced_str, invalid_str

        coerced_bool, coerced_str, invalid_str = self._execute_mcp_session(action)

        # Confirm SDK coercion: bool True becomes limit=1 (returns 1 item)
        self.assertFalse(coerced_bool.isError)
        self.assertEqual(len(coerced_bool.structuredContent["items"]), 1)

        # Confirm SDK coercion: string "2" becomes limit=2 (returns 2 items)
        self.assertFalse(coerced_str.isError)
        self.assertEqual(len(coerced_str.structuredContent["items"]), 2)

        # Confirm SDK validation: string "bad" fails with isError=True
        self.assertTrue(invalid_str.isError)

    def test_05_stdio_hygiene_and_clean_shutdown(self):
        """Server emits only valid JSON-RPC on stdout and shuts down cleanly when stdin closes."""
        proc = subprocess.Popen(
            [sys.executable, str(ROOT / "raider_mcp.py"), "--db", self.db_path],
            cwd=str(ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            init_msg = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "blackbox-tester", "version": "1.0"},
                },
            }
            init_notify = {"jsonrpc": "2.0", "method": "notifications/initialized"}
            call_msg = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "list_posts", "arguments": {"limit": 1}},
            }

            for payload in (init_msg, init_notify, call_msg):
                proc.stdin.write((json.dumps(payload) + "\n").encode())
                proc.stdin.flush()

            # Read lines emitted for initialize response and call_tool response
            line1 = proc.stdout.readline().decode()
            line2 = proc.stdout.readline().decode()

            # Close stdin to trigger clean shutdown
            proc.stdin.close()
            remaining_stdout = proc.stdout.read()
            proc.wait(timeout=10)
        finally:
            if proc.poll() is None:
                proc.kill()
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream:
                    stream.close()

        self.assertEqual(remaining_stdout, b"", "No trailing output after shutdown")
        for line in (line1, line2):
            self.assertTrue(line.strip())
            parsed = json.loads(line)
            self.assertEqual(parsed.get("jsonrpc"), "2.0")

    def test_06_missing_db_cli_exit_code_and_help(self):
        """CLI --help returns 0; missing database exits with code 2 without creating file."""
        # 1. --help exit code
        res_help = subprocess.run(
            [sys.executable, str(ROOT / "raider_mcp.py"), "--help"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(res_help.returncode, 0)
        self.assertIn("usage:", res_help.stdout.lower())

        # 2. Missing DB exit code 2 and no file created
        missing_db = str(Path(self.tmp.name) / "never_created.sqlite")
        res_missing = subprocess.run(
            [sys.executable, str(ROOT / "raider_mcp.py"), "--db", missing_db],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(res_missing.returncode, 2)
        self.assertFalse(Path(missing_db).exists(), "Missing DB must not be created by CLI")
        self.assertIn("error: database not found", res_missing.stderr)


if __name__ == "__main__":
    unittest.main()
