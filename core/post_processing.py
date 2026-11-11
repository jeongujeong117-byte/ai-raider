"""Local, resumable post-level routing. No paid API and no semantic rewriting."""
import hashlib
import importlib.util
import json
import threading
import time
from pathlib import Path
from urllib.request import urlopen

VERSION = 1
FRAME_SECONDS = 5
MAX_FRAMES = 300
MODEL = 'small'


class Stopped(Exception):
    pass


class NotReady(Exception):
    pass


def local_file(root, relative):
    root=Path(root).resolve()
    path=(root/relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('저장된 원본 파일을 찾지 못했습니다.')
    return path


def fingerprint(post, root):
    assets=[]
    for item in post['media']:
        metadata=None
        if item.get('local_path'):
            try:
                info=local_file(root,item['local_path']).stat()
                metadata=[info.st_size,info.st_mtime_ns]
            except (OSError,ValueError):
                pass
        assets.append([item.get('kind'),item.get('status'),item.get('local_path'),metadata])
    value=[VERSION,MODEL,FRAME_SECONDS,MAX_FRAMES,post['text'],assets]
    return hashlib.sha256(json.dumps(value,ensure_ascii=False).encode()).hexdigest()


def readiness(data):
    models=Path(data)/'models'
    packages={name:importlib.util.find_spec(name) is not None for name in ('PIL','tesserocr','av','faster_whisper')}
    ocr=all((models/'tessdata'/f'{lang}.traineddata').is_file() for lang in ('kor','eng'))
    speech=all((models/'whisper-small'/name).is_file() for name in ('model.bin','config.json','tokenizer.json'))
    return {'packages':packages,'ocr_ready':ocr and packages['PIL'] and packages['tesserocr'],
            'transcription_ready':speech and packages['av'] and packages['faster_whisper'],
            'frame_seconds':FRAME_SECONDS,'max_frames':MAX_FRAMES,'speech_model':MODEL}


def prepare(data):
    """Explicit setup only: downloads model weights, never uploads posts."""
    from faster_whisper import download_model
    import tesserocr
    from PIL import Image
    models=Path(data)/'models'
    tess=models/'tessdata'
    tess.mkdir(parents=True,exist_ok=True)
    for language in ('kor','eng'):
        target=tess/f'{language}.traineddata'
        if target.exists():
            continue
        print(f'OCR model: {language}',flush=True)
        temp=target.with_suffix('.part')
        try:
            with urlopen(f'https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/{language}.traineddata',timeout=60) as response,temp.open('wb') as stream:
                while chunk:=response.read(1024*1024):
                    stream.write(chunk)
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)
    print('Whisper small model (local CPU/int8)',flush=True)
    download_model(MODEL,output_dir=str(models/'whisper-small'))
    print(json.dumps(readiness(data),ensure_ascii=False),flush=True)


class Engines:
    def __init__(self,data):
        self.data=Path(data)
        self.whisper=None

    def image_text(self,image):
        if not readiness(self.data)['ocr_ready']:
            raise NotReady('OCR 준비 필요: uv sync --extra processing 후 prepare-processing 실행')
        import tesserocr
        from PIL import ImageOps
        with tesserocr.PyTessBaseAPI(path=str(self.data/'models/tessdata'),lang='kor+eng',
                                   oem=tesserocr.OEM.LSTM_ONLY,psm=tesserocr.PSM.SINGLE_BLOCK) as engine:
            image=ImageOps.exif_transpose(image).convert('RGB')
            if max(image.size)>2400:
                image.thumbnail((2400,2400))
            engine.SetImage(image)
            return {'text':engine.GetUTF8Text().strip(),'confidence':engine.MeanTextConf()}

    def classify(self,path):
        from PIL import Image
        try:
            with Image.open(path) as image:
                return 'video' if getattr(image,'is_animated',False) else 'image'
        except (OSError,ValueError):
            import av
            with av.open(str(path)) as container:
                if container.streams.video:
                    return 'video'
                if container.streams.audio:
                    return 'audio'
            return 'unknown'

    def ocr(self,path,stop):
        from PIL import Image
        check_stop(stop)
        with Image.open(path) as image:
            return self.image_text(image)

    def frames(self,path,stop):
        import av
        if not readiness(self.data)['ocr_ready']:
            raise NotReady('한국어·영어 OCR 모델 준비 필요')
        samples=[]
        next_time=0.0
        truncated=False
        with av.open(str(path)) as container:
            if not container.streams.video:
                return {'samples':[],'sampling_seconds':FRAME_SECONDS,'truncated':False,'note':'영상 스트림 없음'}
            stream=container.streams.video[0]
            duration=float(stream.duration*stream.time_base) if stream.duration is not None else (container.duration/av.time_base if container.duration else None)
            for frame in container.decode(video=0):
                check_stop(stop)
                stamp=frame.time
                if stamp is None or stamp+0.001<next_time:
                    continue
                if len(samples)>=MAX_FRAMES:
                    truncated=True
                    break
                result=self.image_text(frame.to_image())
                samples.append({'seconds':round(stamp,3),**result})
                next_time=float(stamp)+FRAME_SECONDS
        return {'samples':samples,'sampling_seconds':FRAME_SECONDS,'truncated':truncated,'duration_seconds':duration,
                'note':'일정 간격의 화면 표본입니다. 잠깐 나오는 글자는 누락될 수 있습니다.'}

    def transcribe(self,path,stop):
        import av
        check_stop(stop)
        with av.open(str(path)) as container:
            if not container.streams.audio:
                return {'text':'','segments':[],'no_audio':True}
        if not readiness(self.data)['transcription_ready']:
            raise NotReady('Whisper 모델 준비 필요: prepare-processing 실행')
        if self.whisper is None:
            from faster_whisper import WhisperModel
            self.whisper=WhisperModel(str(self.data/'models/whisper-small'),device='cpu',compute_type='int8',local_files_only=True)
        segments,info=self.whisper.transcribe(str(path),language=None,beam_size=5,vad_filter=True)
        rows=[]
        for segment in segments:
            check_stop(stop)
            rows.append({'start':round(segment.start,3),'end':round(segment.end,3),'text':segment.text.strip()})
        return {'language':info.language,'language_probability':info.language_probability,
                'segments':rows,'text':'\n'.join(r['text'] for r in rows),'no_audio':False}


def check_stop(stop):
    if stop.is_set():
        raise Stopped()


def process_post(post,root,engines,stop,progress=lambda result:None):
    """Every derived item belongs to the same platform + post_id; retain media ordering."""
    result={'post_key':post['platform']+':'+str(post['post_id']),'types':[],
            'body':{'tool':'original_text','text':post['text']},'assets':[], 'combined_text':post['text']}
    def types():
        found={'text'} if post['text'].strip() else set()
        found.update(a.get('detected_type',a['role']) for a in result['assets'] if a['role']!='thumbnail')
        return sorted(found)
    for index,asset in enumerate(post['media']):
        check_stop(stop)
        row={'index':index,'role':asset.get('kind','unknown'),'local_path':asset.get('local_path'),'steps':{}}
        result['assets'].append(row)
        try:
            if asset.get('status')!='downloaded' or not asset.get('local_path'):
                row.update(state='waiting_media',detected_type=asset.get('kind','unknown'),message='원본 파일 수집 후 재처리 필요')
            else:
                path=local_file(root,asset['local_path'])
                detected=engines.classify(path)
                row['detected_type']=detected
                routes={'image':[('ocr','Tesseract kor+eng',engines.ocr)],
                        'video':[('transcript','faster-whisper small / CPU int8',engines.transcribe),('frame_ocr','PyAV + Tesseract kor+eng',engines.frames)],
                        'audio':[('transcript','faster-whisper small / CPU int8',engines.transcribe)]}
                for name,tool,method in routes.get(detected,[]):
                    check_stop(stop)
                    try:
                        row['steps'][name]={'state':'completed','tool':tool,**method(path,stop)}
                    except Stopped:
                        raise
                    except NotReady as exc:
                        row['steps'][name]={'state':'blocked','tool':tool,'message':str(exc)}
                    except Exception as exc:
                        row['steps'][name]={'state':'error','tool':tool,'error_type':type(exc).__name__}
                    progress(result)
                row['state']='completed' if row['steps'] and all(s['state']=='completed' for s in row['steps'].values()) else 'needs_attention'
                if detected=='unknown':
                    row['message']='지원하지 않는 파일 형식'
        except Stopped:
            raise
        except Exception as exc:
            row.update(state='error',error_type=type(exc).__name__)
        result['types']=types()
        result['combined_text']=combined(result)
        progress(result)
    result['types']=types()
    result['combined_text']=combined(result)
    result['state']='completed' if all(a['state']=='completed' for a in result['assets']) else 'needs_attention'
    return result


def combined(result):
    chunks=[result['body']['text']] if result['body']['text'] else []
    for asset in result['assets']:
        for name,step in asset['steps'].items():
            if step['state']!='completed':
                continue
            if step.get('text'):
                chunks.append(f"[첨부 {asset['index']+1} / {name}]\n"+step['text'])
            # Keep timestamps, suppress repeated screen text only in combined view.
            last=None
            for sample in step.get('samples',[]):
                text=sample['text'].strip()
                if text and text!=last:
                    chunks.append(f"[첨부 {asset['index']+1} / 화면 {sample['seconds']}초]\n{text}")
                last=text
    return '\n\n'.join(chunks)


class Processor:
    def __init__(self,store,data):
        self.store=store
        self.data=Path(data)
        self.engines=Engines(data)
        self.stop=threading.Event()
        self.wake=threading.Event()
        self.thread=None
        with store.connect() as db:
            db.execute("UPDATE processing SET state='queued' WHERE state IN ('running','interrupted')")

    def start(self):
        self.thread=threading.Thread(target=self.loop,daemon=True)
        self.thread.start()

    def enqueue(self,post,force=False):
        digest=fingerprint(post,self.data/'media')
        with self.store.connect() as db:
            previous=db.execute('SELECT fingerprint,state FROM processing WHERE platform=? AND post_id=?',(post['platform'],str(post['post_id']))).fetchone()
            if previous and previous['fingerprint']==digest and (not force or previous['state'] in ('queued','running')):
                return False
            db.execute('''INSERT INTO processing(platform,post_id,fingerprint,state,result,updated_at) VALUES(?,?,?,'queued','{}',?)
                ON CONFLICT(platform,post_id) DO UPDATE SET fingerprint=excluded.fingerprint,state='queued',result='{}',updated_at=excluded.updated_at''',
                (post['platform'],str(post['post_id']),digest,time.time()))
        self.wake.set()
        return True

    def update(self,job,state,result):
        with self.store.connect() as db:
            db.execute('UPDATE processing SET state=?,result=?,updated_at=? WHERE platform=? AND post_id=? AND fingerprint=?',
                (state,json.dumps(result,ensure_ascii=False),time.time(),job['platform'],job['post_id'],job['fingerprint']))

    def run_one(self):
        with self.store.connect() as db:
            job=db.execute("SELECT * FROM processing WHERE state='queued' ORDER BY updated_at LIMIT 1").fetchone()
            if job is None:
                return False
            job=dict(job)
            row=db.execute('SELECT * FROM posts WHERE platform=? AND post_id=?',(job['platform'],job['post_id'])).fetchone()
            db.execute("UPDATE processing SET state='running' WHERE platform=? AND post_id=?",(job['platform'],job['post_id']))
        if row is None:
            self.update(job,'needs_attention',{'message':'원문 없음'})
            return True
        post=dict(row)
        post['media']=json.loads(post['media'])
        try:
            result=process_post(post,self.data/'media',self.engines,self.stop,
                progress=lambda r:self.update(job,'running',r))
            self.update(job,result['state'],result)
        except Stopped:
            with self.store.connect() as db:
                db.execute("UPDATE processing SET state='interrupted' WHERE platform=? AND post_id=? AND fingerprint=?",(job['platform'],job['post_id'],job['fingerprint']))
        except Exception as exc:
            self.update(job,'needs_attention',{'error_type':type(exc).__name__})
        return True

    def loop(self):
        # Include records collected before this feature was installed.
        offset=0
        while not self.stop.is_set():
            posts=self.store.rows(offset=offset,limit=200)['items']
            if not posts:
                break
            for post in posts:
                self.enqueue(post)
            offset+=len(posts)
        while not self.stop.is_set():
            if not self.run_one():
                self.wake.wait(2)
                self.wake.clear()

    def status(self):
        with self.store.connect() as db:
            counts={r['state']:r['n'] for r in db.execute('SELECT state,COUNT(*) n FROM processing GROUP BY state')}
        return {'counts':counts,**readiness(self.data)}
