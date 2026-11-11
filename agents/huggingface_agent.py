"""Hugging Face Hub public repository cards, configs and file inventory."""
import hashlib
import re
from pathlib import Path


class HuggingFaceExtractor:
    def __init__(self,data):
        self.data=Path(data)

    def collect(self,target,s,stop):
        from huggingface_hub import HfApi
        api=HfApi(token=False)
        types={'models':'model','datasets':'dataset','spaces':'space'}
        kind=types.get(target)
        if kind:
            method={'model':api.list_models,'dataset':api.list_datasets,'space':api.list_spaces}[kind]
            ids=[r.id for r in method(sort='likes',direction=-1,limit=s['limit'])]
        else:
            match=re.fullmatch(r'(model|dataset|space):([\w.-]+/[\w.-]+)',target)
            if not match:
                raise ValueError('models/datasets/spaces 또는 model:owner/name 형식으로 입력하세요.')
            kind=match[1];ids=[match[2]]
        for id in ids:
            source_agents.check(stop)
            info=api.repo_info(id,repo_type=kind,files_metadata=True)
            if getattr(info,'private',False):
                continue
            date=source_agents.date_value(getattr(info,'last_modified',None) or getattr(info,'lastModified',None))
            if not source_agents.in_window(date,s):
                continue
            prefix='' if kind=='model' else ('datasets/' if kind=='dataset' else 'spaces/')
            url='https://huggingface.co/'+prefix+id
            files=[{'path':r.rfilename,'bytes':getattr(r,'size',None)} for r in (info.siblings or [])]
            errors=[];card='';saved=[]
            for file in files:
                if not (file['path'].lower().endswith(('.md','.txt','.json','.yaml','.yml')) and (file['path'].lower().endswith('.md') or file['path'] in ('config.json','model_index.json'))):
                    continue
                if len(saved)>=20:
                    break
                source_agents.check(stop)
                try:
                    from urllib.parse import quote
                    content,_,_=source_agents.fetch(url+'/resolve/'+quote(info.sha,safe='')+'/'+quote(file['path'],safe='/'),stop,max_bytes=1024*1024)
                    folder=self.data/'source-files/huggingface'/hashlib.sha256((kind+id+info.sha).encode()).hexdigest()[:24]
                    folder.mkdir(parents=True,exist_ok=True)
                    path=folder/(str(len(saved))+'.txt');path.write_bytes(content)
                    text=content.decode('utf-8',errors='replace')
                    saved.append({'path':file['path'],'local_path':path.relative_to(self.data).as_posix(),'text':text})
                    if file['path'].lower()=='readme.md':
                        card=text
                except source_agents.Cancelled:
                    raise
                except Exception as exc:
                    errors.append({'path':file['path'],'error_type':type(exc).__name__})
            yield source_agents.post('huggingface',kind+':'+id,id,url,id,card,date,
                       {'likes':getattr(info,'likes',None),'downloads':getattr(info,'downloads',None)},raw={
                           'tool':'official huggingface_hub HfApi','repo_type':kind,'sha':info.sha,'tags':getattr(info,'tags',[]),
                           'files':files,'documents':saved,'errors':errors,'scope':'현재 파일 목록·카드·설정. 모델 가중치·데이터 원본 자동 다운로드 없음'})


# Imported last: agents.source_agents imports this module for ADAPTERS. Shared helpers are
# looked up on that module at call time so patching source_agents.<helper> still applies.
from agents import source_agents  # noqa: E402
