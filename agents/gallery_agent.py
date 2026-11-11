"""DC Inside AI gallery extraction from public list and article HTML."""
import re
from pathlib import Path
from urllib.parse import urlparse,urljoin,parse_qs,urlencode


class GalleryExtractor:
    def __init__(self,data):
        self.data=Path(data)

    def collect(self,target,s,stop):
        from bs4 import BeautifulSoup
        parsed=urlparse(target)
        if parsed.hostname not in ('gall.dcinside.com','enter.dcinside.com'):
            raise ValueError('AI 활용 갤러리의 디시인사이드 주소를 입력하세요.')
        query=parse_qs(parsed.query)
        gallery=query.get('id',['ai_utilize'])[0]
        if not re.fullmatch('[a-zA-Z0-9_]+',gallery):
            raise ValueError('갤러리 ID를 확인하세요.')
        seen=set();emitted=0
        for page_no in range(1,s['pages']+1):
            source_agents.check(stop)
            listing='https://gall.dcinside.com/mgallery/board/lists/?'+urlencode({'id':gallery,'page':page_no})
            page,final=source_agents.get_html(listing,stop,s['browser'])
            soup=BeautifulSoup(page,'html.parser')
            rows=soup.select('tr.ub-content')
            if not rows and s['browser']:
                page,final=source_agents.html(listing,stop,browser=True)
                rows=BeautifulSoup(page,'html.parser').select('tr.ub-content')
            if not rows:
                raise ValueError('게시글 목록 없음: 접근 제한 또는 페이지 구조 확인 필요')
            fresh=0
            for row in rows:
                link=row.select_one('td.gall_tit a[href*="/board/view/"]')
                if not link:
                    continue
                url=urljoin(final,link.get('href',''))
                no=parse_qs(urlparse(url).query).get('no',[''])[0]
                if not no.isdigit() or no in seen:
                    continue
                seen.add(no);fresh+=1
                date_tag=row.select_one('.gall_date')
                date=source_agents.date_value(date_tag.get('title') if date_tag else None)
                if not source_agents.in_window(date,s):
                    continue
                source_agents.check(stop)
                page,final=source_agents.get_html(url,stop,s['browser'])
                article=BeautifulSoup(page,'html.parser')
                body=article.select_one('.write_div')
                if body is None and s['browser']:
                    page,final=source_agents.html(url,stop,browser=True)
                    article=BeautifulSoup(page,'html.parser');body=article.select_one('.write_div')
                if body is None:
                    raise ValueError('게시글 본문 없음: 로그인·삭제·접근 제한 확인 필요')
                title=article.select_one('.title_subject')
                def number(selector):
                    node=row.select_one(selector)
                    return int(re.sub(r'[^0-9]','',node.get_text()) or 0) if node else None
                yield source_agents.post('gallery',gallery+'-'+no,gallery,final,title.get_text(strip=True) if title else link.get_text(strip=True),
                    body.get_text('\n',strip=True),date,{'likes':number('.gall_recommend'),'views':number('.gall_count')},source_agents.media_tags(body,final),
                    {'tool':'BeautifulSoup + public HTML','page':page_no,'scope':f'최대 {s["pages"]}페이지 · {s["limit"]}건, 댓글 별도 미수집'})
                emitted+=1
                if emitted>=s['limit']:
                    return
                if stop.wait(.4):
                    raise source_agents.Cancelled()
            if not fresh:
                return


# Imported last: agents.source_agents imports this module for ADAPTERS. Shared helpers are
# looked up on that module at call time so patching source_agents.<helper> still applies.
from agents import source_agents  # noqa: E402
