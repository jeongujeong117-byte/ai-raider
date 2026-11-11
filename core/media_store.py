"""Download platform-served media before OCR/transcription, without AI services."""
import hashlib
import re
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

MIME_EXT={'image/jpeg':'.jpg','image/png':'.png','image/webp':'.webp','image/gif':'.gif',
          'video/mp4':'.mp4','video/webm':'.webm'}


def validate_url(url):
    parsed=urlparse(url)
    host=(parsed.hostname or '').lower()
    allowed=any(host==d or host.endswith('.'+d) for d in ('cdninstagram.com','fbcdn.net','twimg.com'))
    if parsed.scheme!='https' or parsed.username or parsed.password or parsed.port not in (None,443) or not allowed:
        raise ValueError('허용된 미디어 CDN 주소가 아닙니다.')
    return url


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def x_media(media):
    result=[]
    if not media:
        return result
    for photo in media.photos:
        result.append({'url':photo.url,'kind':'image'})
    for video in media.videos:
        variants=[v for v in video.variants if v.contentType=='video/mp4']
        if variants:
            result.append({'url':max(variants,key=lambda v:v.bitrate).url,'kind':'video'})
        else:
            result.append({'url':None,'kind':'video','status':'unavailable'})
        result.append({'url':video.thumbnailUrl,'kind':'thumbnail'})
    for animated in media.animated:
        result.append({'url':animated.videoUrl,'kind':'video'})
        result.append({'url':animated.thumbnailUrl,'kind':'thumbnail'})
    return result


def download_media(post, root, stop, max_bytes=512*1024*1024, opener=None):
    """Return assets with local paths/status; failed media does not discard post text."""
    opener=opener or build_opener(SafeRedirect())
    root=Path(root).resolve()
    parts=[post['platform'],post['handle'],str(post['post_id'])]
    if not all(re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',p) and p not in ('.','..') for p in parts):
        raise ValueError('잘못된 미디어 경로입니다.')
    folder=root/parts[0]/('h-'+parts[1])/('p-'+parts[2])
    folder.mkdir(parents=True,exist_ok=True)
    results=[]
    for index,asset in enumerate(post['media']):
        item=dict(asset)
        results.append(item)
        if stop.is_set():
            item['status']='interrupted'
            continue
        if not item.get('url'):
            item['status']='unavailable'
            continue
        partial=folder/f'{index:03d}.part'
        try:
            validate_url(item['url'])
            # Completed files are atomically renamed; partial transfers never count as cached.
            cached=next((p for p in folder.glob(f'{index:03d}.*') if p.suffix in MIME_EXT.values() and p.stat().st_size>0),None)
            if cached:
                item.update(status='downloaded',local_path=cached.relative_to(root).as_posix(),bytes=cached.stat().st_size)
                continue
            request=Request(item['url'],headers={'User-Agent':'Mozilla/5.0','Accept':'image/*,video/*'})
            with opener.open(request,timeout=30) as response:
                content_type=response.headers.get('Content-Type','').split(';')[0].strip().lower()
                if content_type not in MIME_EXT:
                    raise ValueError('이미지·영상 응답이 아닙니다.')
                length=int(response.headers.get('Content-Length','0'))
                if length>max_bytes:
                    raise ValueError('파일 크기 제한을 넘었습니다.')
                digest=hashlib.sha256()
                size=0
                with partial.open('wb') as stream:
                    while True:
                        if stop.is_set():
                            raise InterruptedError()
                        chunk=response.read(128*1024)
                        if not chunk:
                            break
                        size+=len(chunk)
                        if size>max_bytes:
                            raise ValueError('파일 크기 제한을 넘었습니다.')
                        stream.write(chunk)
                        digest.update(chunk)
                if not size or (length and size!=length):
                    raise ValueError('파일 전송이 끝나지 않았습니다.')
                target=folder/f'{index:03d}{MIME_EXT[content_type]}'
                partial.replace(target)
                item.update(status='downloaded',local_path=target.relative_to(root).as_posix(),
                            bytes=size,sha256=digest.hexdigest(),content_type=content_type)
        except InterruptedError:
            item['status']='interrupted'
        except Exception as exc:
            item.update(status='error',error_type=type(exc).__name__)
        finally:
            partial.unlink(missing_ok=True)
    return results
