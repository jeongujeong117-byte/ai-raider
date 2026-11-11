"""Instagram public-profile collection through a locally saved instaloader session."""
import json
from pathlib import Path

from agents import Cancelled
from core import common
from core.common import UTC


def instagram(task, begin, finish, stop, *, private=None):
    """Yield posts in [begin, finish). `private` defaults to the repository .private folder."""
    import instaloader
    private = common.PRIVATE if private is None else Path(private)
    settings = private / "instagram.json"
    if not settings.exists():
        raise RuntimeError("Instagram 로그인이 필요합니다. 터미널에서 uv run python raider.py login-instagram 실행")
    username = json.loads(settings.read_text(encoding="utf-8"))["username"]
    loader = instaloader.Instaloader(max_connection_attempts=1, request_timeout=30,
                                    download_pictures=False, download_videos=False)
    loader.load_session_from_file(username, str(private / "instagram.session"))
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
