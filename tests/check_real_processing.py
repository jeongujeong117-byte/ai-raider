"""Opt-in integration check. Run after prepare-processing; no network or social login.

An English WAV fixture is generated with Windows SpeechSynthesizer before this check.
Artifacts stay in gitignored data/verification; they are never inserted into the live DB.
"""
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import av
from PIL import Image, ImageDraw, ImageFont
import raider
from post_processing import Engines, process_post

sys.stdout.reconfigure(encoding='utf-8')
folder=raider.DATA/'verification'
folder.mkdir(exist_ok=True)
image=Image.new('RGB',(1400,400),'white')
draw=ImageDraw.Draw(image)
font=ImageFont.truetype('C:/Windows/Fonts/malgun.ttf',54)
draw.text((50,60),'AI Raider test 2026',font=font,fill='black')
draw.text((50,180),'인공지능 소식을 수집합니다',font=font,fill='black')
image.save(folder/'image.png')
with av.open(str(folder/'silent.mp4'),mode='w') as output:
    stream=output.add_stream('mpeg4',rate=2)
    stream.width,stream.height=image.size
    stream.pix_fmt='yuv420p'
    for index in range(24):
        frame=av.VideoFrame.from_image(image)
        frame.pts=index
        for packet in stream.encode(frame):
            output.mux(packet)
    for packet in stream.encode():
        output.mux(packet)

post=dict(platform='instagram',post_id='verification',text='원문 테스트 본문',
    media=[{'kind':kind,'status':'downloaded','local_path':name} for kind,name in
           [('image','image.png'),('video','silent.mp4'),('audio','voice.wav')]])
result=process_post(post,folder,Engines(raider.DATA),threading.Event())
(folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
assert result['state']=='completed',result
ocr=result['assets'][0]['steps']['ocr']['text']
assert 'Raider' in ocr and '인공지능' in ocr,ocr
assert result['assets'][1]['steps']['transcript']['no_audio'] is True
samples=result['assets'][1]['steps']['frame_ocr']['samples']
assert len(samples)==3,[s['seconds'] for s in samples]
assert '인공지능' in samples[0]['text']
speech=result['assets'][2]['steps']['transcript']['text']
assert 'intelligence' in speech.lower(),speech
print('PASS: actual Korean/English OCR, video frame OCR at 0/5/10 sec, silent video, Whisper CPU ASR, one post grouping')
print('OCR:',ocr)
print('ASR:',speech)
