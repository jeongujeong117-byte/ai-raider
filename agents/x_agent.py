"""X (Twitter) collection through a locally saved twscrape account database."""
import json
import os
from datetime import timedelta
from pathlib import Path

from agents import Cancelled
from core import common
from core.common import UTC
from core.media_store import x_media

# Set before twscrape is first imported (it is imported lazily inside x_posts).
os.environ["TWS_TELEMETRY"] = "0"


async def x_posts(task, begin, finish, stop, *, private=None):
    """Yield one day slice of posts. `private` defaults to the repository .private folder."""
    from twscrape import API
    path = (common.PRIVATE if private is None else Path(private)) / "x-accounts.db"
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
