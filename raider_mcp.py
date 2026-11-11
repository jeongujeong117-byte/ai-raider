"""Read-only stdio MCP server exposing collected posts (list / get / unanalyzed)."""
import argparse
from typing import Any
import json
import sqlite3
import sys
from pathlib import Path

from core import common

_COLUMNS = ("platform", "post_id", "handle", "url", "posted_at", "text", "metrics", "media", "collected_at", "raw")
_JSON_COLUMNS = ("metrics", "media", "raw")
_ORDER = "ORDER BY posted_at DESC, platform ASC, post_id DESC"
_SELECT = "SELECT " + ", ".join("p." + c for c in _COLUMNS) + " FROM posts p"
_UNANALYZED = " AND NOT EXISTS (SELECT 1 FROM post_analyses a WHERE a.platform = p.platform AND a.post_id = p.post_id)"


class ReaderError(RuntimeError):
    """Fixed, safe error message; never carries SQL text, paths or secrets."""


def _int(value, name, low, high=None):
    if isinstance(value, bool) or not isinstance(value, int) or value < low or (high is not None and value > high):
        raise ValueError(f"{name} must be an integer in range")
    return value


def _str(value, name, required=False):
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(f"{name} must be a {'non-empty ' if required else ''}string")
    return value


class PostReader:
    def __init__(self, db_path):
        self.path = Path(db_path)
        if not self.path.is_file():
            raise FileNotFoundError("database not found")

    def _connect(self):
        try:
            db = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True, timeout=30)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only = ON")
            return db
        except sqlite3.Error:
            raise ReaderError("database unavailable") from None

    def _query(self, work):
        db = self._connect()
        try:
            return work(db)
        except ReaderError:
            raise
        except sqlite3.Error:
            raise ReaderError("database query failed") from None
        finally:
            db.close()

    @staticmethod
    def _post(row):
        post = {}
        for col in _COLUMNS:
            value = row[col]
            if col in _JSON_COLUMNS and value is not None:
                try:
                    value = json.loads(value)
                except (TypeError, ValueError):
                    raise ReaderError("stored post contains invalid JSON") from None
            post[col] = value
        return post

    def _list(self, platform, handle, offset, limit, unanalyzed):
        _str(platform, "platform"); _str(handle, "handle")
        _int(offset, "offset", 0); _int(limit, "limit", 1, 500)
        where, params = " WHERE 1=1", []
        for col, val in (("platform", platform), ("handle", handle)):
            if val:
                where += f" AND p.{col} = ?"
                params.append(val)

        def work(db):
            extra = ""
            if unanalyzed:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='post_analyses'").fetchone():
                    cols = {r["name"] for r in db.execute("PRAGMA table_info(post_analyses)")}
                    if not {"platform", "post_id"} <= cols:
                        raise ReaderError("post_analyses lacks required identity columns")
                    extra = _UNANALYZED
            total = db.execute("SELECT COUNT(*) FROM posts p" + where + extra, params).fetchone()[0]
            rows = db.execute(f"{_SELECT}{where}{extra} {_ORDER} LIMIT ? OFFSET ?", params + [limit, offset]).fetchall()
            return {"total": total, "items": [self._post(r) for r in rows]}
        return self._query(work)

    def list_posts(self, platform="", handle="", offset=0, limit=100):
        return self._list(platform, handle, offset, limit, False)

    def list_unanalyzed(self, platform="", handle="", offset=0, limit=100):
        return self._list(platform, handle, offset, limit, True)

    def get_post(self, platform, post_id):
        _str(platform, "platform", True); _str(post_id, "post_id", True)

        def work(db):
            row = db.execute(f"{_SELECT} WHERE p.platform = ? AND p.post_id = ?", (platform, post_id)).fetchone()
            return self._post(row) if row else None
        return self._query(work)


def create_server(db_path):
    from mcp.server.fastmcp import FastMCP
    from mcp.types import ToolAnnotations
    from pydantic import StrictInt, StrictStr

    reader = PostReader(db_path)
    server = FastMCP("ai-raider-posts")
    hint = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

    def safe(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ValueError, ReaderError):
            raise
        except Exception:
            raise ReaderError("internal error") from None

    @server.tool(name="list_posts", description="List collected posts (newest first) with optional platform/handle filter and paging.", annotations=hint)
    def list_posts(platform: StrictStr = "", handle: StrictStr = "", offset: StrictInt = 0, limit: StrictInt = 100) -> dict[str, Any]:
        return safe(reader.list_posts, platform, handle, offset, limit)

    @server.tool(name="get_post", description="Get one post by platform and post_id; returns null if absent.", annotations=hint)
    def get_post(platform: StrictStr, post_id: StrictStr) -> dict[str, Any] | None:
        return safe(reader.get_post, platform, post_id)

    @server.tool(name="list_unanalyzed", description="List posts without an AI analysis record.", annotations=hint)
    def list_unanalyzed(platform: StrictStr = "", handle: StrictStr = "", offset: StrictInt = 0, limit: StrictInt = 100) -> dict[str, Any]:
        return safe(reader.list_unanalyzed, platform, handle, offset, limit)

    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only MCP server for collected posts (stdio).")
    parser.add_argument("--db", default=str(common.DATA / "raider.sqlite"), help="SQLite database path")
    args = parser.parse_args(argv)
    try:
        server = create_server(args.db)
    except FileNotFoundError:
        print("error: database not found", file=sys.stderr)
        return 2
    except ImportError:
        print("error: mcp extra not installed (uv sync --extra mcp)", file=sys.stderr)
        return 2
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
