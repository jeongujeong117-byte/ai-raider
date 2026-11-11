"""Platform-scoped account categories and atomic bulk account registration."""
import json
import re
import threading
import uuid
from pathlib import Path
from urllib.parse import urlparse

DEFAULTS = {
    'instagram': ['미분류','AI 소식','업무·생산성','개발·에이전트','연구·교육','마케팅·사업','이미지·영상','로봇·산업'],
    'x': ['미분류','공식 발표','뉴스·큐레이션','프롬프트·활용','개발·도구','연구·평가','산업·정책'],
}
LOCK = threading.RLock()


def valid_handle(platform, value):
    if platform == 'instagram':
        return bool(re.fullmatch(r'[A-Za-z0-9_](?:[A-Za-z0-9_.]{0,28}[A-Za-z0-9_])?', value)) and '..' not in value
    return platform == 'x' and bool(re.fullmatch(r'[A-Za-z0-9_]{1,15}', value))


def parse_handles(platform, text):
    if platform not in DEFAULTS or not isinstance(text,str) or len(text)>50000:
        raise ValueError('플랫폼과 붙여넣기 내용을 확인하세요.')
    valid, invalid, repeated, seen = [], [], [], set()
    # Also accept @first@second without whitespace, without partially accepting bad handles.
    tokens=[]
    for item in re.split(r'[\s,;，、]+', text.strip()):
        tokens.extend([t for t in re.split(r'(?=@)',item) if t] if item.startswith('@') else [item])
    for token in tokens:
        if not token:
            continue
        value = token
        if token.startswith(('https://','http://')):
            url=urlparse(token)
            allowed={'instagram.com','www.instagram.com'} if platform=='instagram' else {'x.com','www.x.com','twitter.com','www.twitter.com'}
            pieces=url.path.strip('/').split('/')
            if url.hostname not in allowed or len(pieces)!=1:
                invalid.append(token)
                continue
            value=pieces[0]
        elif value.startswith('@'):
            value=value[1:]
        if not valid_handle(platform,value):
            invalid.append(token)
        elif value.lower() in seen:
            repeated.append(value)
        else:
            seen.add(value.lower())
            valid.append(value)
    return {'handles':valid,'invalid':invalid,'repeated':repeated}


def guess_category(account):
    if account.get('category'):
        return account['category']
    text=' '.join(account.get('topics',[]))+' '+account.get('information_focus','')
    if account['platform']=='instagram':
        rules=[('로봇·산업',('로봇','미래기술')),('연구·교육',('교육','연구','논문','학술')),
               ('개발·에이전트',('개발','코딩','에이전트')),('업무·생산성',('자동화','생산성','노션','기록')),
               ('마케팅·사업',('마케팅','사업','창업','기업','비즈니스')),('이미지·영상',('이미지','영상','디자인')),
               ('AI 소식',('뉴스','트렌드','소식'))]
    else:
        if account['handle'].lower() in {'openai','anthropicai','googledeepmind'}:
            return '공식 발표'
        rules=[('연구·평가',('연구','평가','학술')),('개발·도구',('개발','코딩','도구','오픈')),
               ('프롬프트·활용',('프롬프트','활용','실사용')),('산업·정책',('산업','정책','기업')),
               ('뉴스·큐레이션',('뉴스','소식','동향','해설','큐레이션'))]
    return next((name for name,words in rules if any(w in text for w in words)),'미분류')


class Registry:
    def __init__(self, root):
        self.root=Path(root)
        self.path=self.root/'config/sources.json'
        self.categories_path=self.root/'config/categories.json'

    def _load(self):
        return json.loads(self.path.read_text(encoding='utf-8-sig'))

    @staticmethod
    def _write(path, value):
        path.parent.mkdir(parents=True,exist_ok=True)
        temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)

    def accounts(self):
        with LOCK:
            result=self._load()['accounts']
            for row in result:
                if not valid_handle(row['platform'],row['handle']):
                    raise ValueError('계정 설정의 플랫폼 또는 핸들을 확인하세요.')
                row['category']=guess_category(row)
            return result

    def categories(self):
        with LOCK:
            result={k:list(v) for k,v in DEFAULTS.items()}
            if self.categories_path.exists():
                for platform,names in json.loads(self.categories_path.read_text(encoding='utf-8-sig')).items():
                    if platform in result:
                        result[platform]=list(dict.fromkeys(['미분류']+names))
            for account in self.accounts():
                if account['category'] not in result[account['platform']]:
                    result[account['platform']].append(account['category'])
            return result

    def add_category(self, platform, name):
        if platform not in DEFAULTS or not isinstance(name,str) or not 1<=len(name.strip())<=40 or any(ord(c)<32 for c in name):
            raise ValueError('분류 이름은 1~40자로 입력하세요.')
        with LOCK:
            result=self.categories()
            if name.strip() not in result[platform]:
                result[platform].append(name.strip())
                self._write(self.categories_path,result)
            return result

    def preview(self, platform, text):
        result=parse_handles(platform,text)
        existing={r['handle'].lower() for r in self.accounts() if r['platform']==platform}
        result['new']=[h for h in result['handles'] if h.lower() not in existing]
        result['existing']=[h for h in result['handles'] if h.lower() in existing]
        return result

    def add(self, platform, text, category='미분류'):
        with LOCK:
            if category not in self.categories().get(platform,[]):
                raise ValueError('선택한 플랫폼에 없는 분류입니다.')
            result=self.preview(platform,text)
            if result['invalid']:
                raise ValueError('잘못된 계정을 수정한 뒤 등록하세요: '+', '.join(result['invalid'][:10]))
            if not result['handles']:
                raise ValueError('@계정을 하나 이상 입력하세요.')
            config=self._load()
            for handle in result['new']:
                config['accounts'].append({'platform':platform,'handle':handle,'display_name':handle,
                    'url':('https://www.instagram.com/' if platform=='instagram' else 'https://x.com/')+handle,
                    'category':category,'selection_status':'selected','selection_basis':'user_bulk_add',
                    'collection_state':'not_started','verification_note':'사용자 등록 · 실제 계정 존재 여부는 수집 시 확인'})
            if result['new']:
                self._write(self.path,config)
            return result

    def assign(self, platform, handle, category):
        with LOCK:
            if category not in self.categories().get(platform,[]):
                raise ValueError('선택한 플랫폼에 없는 분류입니다.')
            config=self._load()
            for account in config['accounts']:
                if account['platform']==platform and account['handle'].lower()==handle.lower():
                    account['category']=category
                    self._write(self.path,config)
                    return
            raise ValueError('등록된 계정을 찾지 못했습니다.')
