"""Public HTTP and an explicit local browser fallback. No authentication bypass."""
import hashlib
import ipaddress
import json
import socket
import threading
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler,Request,build_opener

from core import common

BROWSER_LOCK=threading.Lock()


def public_url(url):
    parsed=urlparse(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,80,443):
        raise ValueError('공개 HTTP/HTTPS 주소를 입력하세요.')
    addresses=socket.getaddrinfo(parsed.hostname,parsed.port or (443 if parsed.scheme=='https' else 80),type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError('로컬·사설 네트워크 주소는 수집하지 않습니다.')
    return url


class PublicRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        public_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


class Cancelled(Exception):
    pass


def check(stop):
    if stop.is_set():
        raise Cancelled()


def fetch(url,stop,max_bytes=10*1024*1024,referer=None):
    public_url(url)
    headers={'User-Agent':'Mozilla/5.0 AI-Raider/0.5','Accept':'*/*'}
    if referer:
        headers['Referer']=referer
    with build_opener(PublicRedirect()).open(Request(url,headers=headers),timeout=30) as response:
        if int(response.headers.get('Content-Length','0'))>max_bytes:
            raise ValueError('응답 크기 상한 초과')
        data=bytearray()
        while True:
            check(stop)
            chunk=response.read(min(128*1024,max_bytes+1-len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if len(data)>max_bytes:
                raise ValueError('응답 크기 상한 초과')
        return bytes(data),response.headers.get('Content-Type',''),response.geturl()


def _html(url,stop,browser=False):
    if browser:
        from playwright.sync_api import sync_playwright
        public_url(url)
        # Dedicated profile. Existing personal browser state is never copied.
        profile=common.PRIVATE/'source-browser'
        profile.mkdir(parents=True,exist_ok=True)
        with sync_playwright() as p:
            context=p.chromium.launch_persistent_context(str(profile),channel='msedge',headless=False,accept_downloads=False)
            try:
                def guard(route):
                    try:
                        if route.request.url.startswith(('http://','https://')):
                            public_url(route.request.url)
                        route.continue_()
                    except Exception:
                        route.abort()
                context.route('**/*',guard)
                page=context.new_page()
                page.goto(url,wait_until='domcontentloaded',timeout=45000)
                try:
                    page.wait_for_load_state('networkidle',timeout=5000)
                except Exception:
                    pass
                check(stop)
                return page.content(),page.url
            finally:
                context.close()
    data,kind,final=fetch(url,stop)
    from bs4 import UnicodeDammit
    return UnicodeDammit(data).unicode_markup or data.decode('utf-8',errors='replace'),final


def html(url,stop,browser=False):
    if browser:
        with BROWSER_LOCK:
            check(stop)
            return _html(url,stop,True)
    return _html(url,stop,False)


def save_media(post,root,stop,max_bytes=512*1024*1024):
    root=Path(root)
    folder=root/post['platform']/('p-'+hashlib.sha256(post['post_id'].encode()).hexdigest()[:24])
    folder.mkdir(parents=True,exist_ok=True)
    mime={'image/jpeg':'.jpg','image/png':'.png','image/webp':'.webp','image/gif':'.gif','video/mp4':'.mp4','video/webm':'.webm'}
    for index,asset in enumerate(post['media']):
        check(stop)
        if asset.get('status')=='downloaded':
            continue
        partial=folder/(str(index)+'.part')
        try:
            public_url(asset['url'])
            request=Request(asset['url'],headers={'User-Agent':'Mozilla/5.0 AI-Raider/0.5','Referer':post['url']})
            digest=hashlib.sha256();size=0
            with build_opener(PublicRedirect()).open(request,timeout=30) as response:
                ext=mime.get(response.headers.get('Content-Type','').split(';')[0].lower())
                if not ext:
                    raise ValueError('지원하지 않는 미디어 응답')
                expected=int(response.headers.get('Content-Length','0'))
                if expected>max_bytes:
                    raise ValueError('미디어 크기 상한 초과')
                with partial.open('wb') as stream:
                    while True:
                        check(stop)
                        chunk=response.read(128*1024)
                        if not chunk:
                            break
                        size+=len(chunk)
                        if size>max_bytes:
                            raise ValueError('미디어 크기 상한 초과')
                        stream.write(chunk);digest.update(chunk)
                if not size or (expected and size!=expected):
                    raise ValueError('미완료 미디어 전송')
            path=folder/(str(index)+ext)
            partial.replace(path)
            asset.update(status='downloaded',local_path=path.relative_to(root).as_posix(),bytes=size,sha256=digest.hexdigest())
        except Cancelled:
            raise
        except Exception as exc:
            asset.update(status='error',error_type=type(exc).__name__)
        finally:
            partial.unlink(missing_ok=True)
    return post
