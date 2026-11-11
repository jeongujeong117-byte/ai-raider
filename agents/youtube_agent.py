"""YouTube metadata, provided subtitles and optional video file through yt-dlp."""
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from core import common
from core.common import UTC,KST


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
            source_agents.check(stop)
            if status.get('downloaded_bytes',0)>s['max_mb']*1024*1024:
                raise ValueError('영상 파일 크기 상한 초과')
        base={'quiet':True,'no_warnings':True,'logger':QuietLogger(),'socket_timeout':30,'retries':1,'fragment_retries':1,
              'playlistend':s['limit'],'progress_hooks':[hook], 'remote_components':set()}
        if shutil.which('node'):
            base['js_runtimes']={'node':{'path':shutil.which('node')}}
        cookies=common.PRIVATE/'youtube.cookies.txt'
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
            source_agents.check(stop)
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
            if not source_agents.in_window(date,s):
                continue
            raw={'tool':'yt-dlp','duration_seconds':info.get('duration'),'errors':[],'subtitles':[],'scope':f'최대 {s["limit"]}개 목록. 비공개·삭제·차단 영상은 확보 보장 없음'}
            subtitles=info.get('subtitles') or info.get('automatic_captions') or {}
            for lang in ['ko','en']:
                selected=next((a for a in subtitles.get(lang,[]) if a.get('ext')=='json3'),None)
                if selected:
                    try:
                        payload,_,_=source_agents.fetch(selected['url'],stop)
                        events=json.loads(payload).get('events',[])
                        raw['subtitles']=[{'start':e.get('tStartMs',0)/1000,'text':''.join(a.get('utf8','') for a in e.get('segs',[])).strip()} for e in events if e.get('segs')]
                        raw['subtitle_language']=lang
                    except source_agents.Cancelled:
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
                except source_agents.Cancelled:
                    raise
                except Exception as exc:
                    media=[{'kind':'video','status':'error','error_type':type(exc).__name__}]
                    raw['errors'].append({'step':'video','error_type':type(exc).__name__})
                    for partial in folder.glob('*.part'):
                        partial.unlink(missing_ok=True)
            yield source_agents.post('youtube',id,info.get('channel_id') or 'youtube',url,info.get('title',''),text,date,
                       {'likes':info.get('like_count'),'views':info.get('view_count'),'comments':info.get('comment_count')},media,raw)


# Imported last: agents.source_agents imports this module for ADAPTERS. Shared helpers are
# looked up on that module at call time so patching source_agents.<helper> still applies.
from agents import source_agents  # noqa: E402
