"""News extraction: RSS listing (feedparser) and article body (trafilatura)."""
import hashlib
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from core.common import UTC


class NewsExtractor:
    def __init__(self,data):
        self.data=Path(data)

    def article(self,url,stop,browser=False,fallback=None):
        from bs4 import BeautifulSoup
        import trafilatura
        fallback=fallback or {}
        errors=[]
        try:
            page,final=source_agents.get_html(url,stop,browser)
            document=trafilatura.bare_extraction(page,url=final,with_metadata=True)
            if not document or not document.text:
                if browser:
                    page,final=source_agents.html(url,stop,browser=True)
                    document=trafilatura.bare_extraction(page,url=final,with_metadata=True)
            if not document or not document.text:
                raise ValueError('본문을 찾지 못했습니다.')
            soup=BeautifulSoup(page,'html.parser')
            body=soup.select_one('article') or soup.select_one('#article-view-content-div') or soup
            text=document.text
            title=document.title or fallback.get('title','')
            date=source_agents.date_value(document.date) or fallback.get('date')
            media=source_agents.media_tags(body,final)
        except source_agents.Cancelled:
            raise
        except Exception as exc:
            if not fallback.get('text'):
                raise
            final=url;text=fallback['text'];title=fallback.get('title','');date=fallback.get('date');media=[]
            errors.append({'step':'article','error_type':type(exc).__name__})
        return source_agents.post('news',hashlib.sha256(url.encode()).hexdigest(),urlparse(final).hostname or 'news',final,title,text,date,media=media,
                    raw={'tool':'feedparser + trafilatura','errors':errors,'scope':'RSS 제공 목록 또는 지정 기사. 전체 뉴스 과거 목록 아님'})

    def collect(self,target,s,stop):
        import feedparser
        from bs4 import BeautifulSoup
        from calendar import timegm
        payload,_,_=source_agents.fetch(target,stop)
        feed=feedparser.parse(payload)
        if not feed.entries:
            yield self.article(target,stop,s['browser'])
            return
        seen=set()
        for entry in feed.entries[:s['limit']]:
            source_agents.check(stop)
            url=entry.get('link')
            if not url or url in seen:
                continue
            seen.add(url)
            stamp=entry.get('published_parsed') or entry.get('updated_parsed')
            date=datetime.fromtimestamp(timegm(stamp),UTC) if stamp else None
            if not source_agents.in_window(date,s):
                continue
            summary=BeautifulSoup(entry.get('summary',''),'html.parser').get_text('\n',strip=True)
            item=self.article(url,stop,s['browser'],{'title':entry.get('title',''),'text':summary,'date':date})
            if source_agents.in_window(source_agents.date_value(item['posted_at']),s):
                item['raw']['feed']=target
                yield item


# Imported last: agents.source_agents imports this module for ADAPTERS. Shared helpers are
# looked up on that module at call time so patching source_agents.<helper> still applies.
from agents import source_agents  # noqa: E402
