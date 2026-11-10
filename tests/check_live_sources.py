"""Small explicit public-network check. Never counts a failed source as complete."""
import json
import sys
import threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import raider
from source_agents import ADAPTERS
sys.stdout.reconfigure(encoding='utf-8')
kind=sys.argv[1]
target={'news':'https://www.aitimes.com/rss/allArticle.xml',
        'gallery':'https://gall.dcinside.com/mgallery/board/lists/?id=ai_utilize',
        'huggingface':'model:openai/whisper-tiny',
        'youtube':'https://www.youtube.com/@OpenAI/videos'}[kind]
settings=dict(start='2020-01-01',end='2030-12-31',limit=1,pages=1,download_media=False,browser=False,max_mb=1)
if '--download' in sys.argv:
    settings.update(download_media=True,max_mb=64)
folder=raider.DATA/'verification-other';folder.mkdir(exist_ok=True)
try:
    items=list(ADAPTERS[kind](raider.DATA).collect(target,settings,threading.Event()))
    result={'kind':kind,'count':len(items),'items':items}
    assert items,'No records returned'
    print(kind,'PASS',len(items),'records; title:',items[0]['raw']['title'][:100])
    if items[0]['raw'].get('errors'):
        print('PARTIAL:',items[0]['raw']['errors'])
except Exception as exc:
    result={'kind':kind,'state':'failed','error_type':type(exc).__name__}
    print(kind,'FAILED',type(exc).__name__)
(folder/(kind+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
