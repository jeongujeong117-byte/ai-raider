import sqlite3, sys, json, os, random
c = sqlite3.connect("file:"+sys.argv[1]+"?mode=ro", uri=True)
out = sys.argv[2]
os.makedirs(out, exist_ok=True)
def load(p):
    return c.execute("select post_id,handle,url,posted_at,text,metrics,media,collected_at from posts where platform=?",(p,)).fetchall()
x = load("x"); ig = load("instagram")
# X
bad_json = 0; allzero = 0; reply = 0; nullviews = 0; dupset = {}
byh = {}
for r in x:
    try: m = json.loads(r[5])
    except Exception: bad_json += 1; continue
    if all((m.get(k) in (0,None)) for k in ("likes","reposts","quotes","views")): allzero += 1
    if m.get("views") is None: nullviews += 1
    if r[4].startswith("@"): reply += 1
    byh[r[1]] = byh.get(r[1],0)+1
    dupset.setdefault(r[4][:120], []).append(r[0])
print("X rows",len(x),"bad metrics json",bad_json,"all-zero metrics",allzero,"views None",nullviews,"reply(@-start)",reply)
print("X per-handle top:",sorted(byh.items(), key=lambda t:-t[1])[:8], "min:",sorted(byh.items(), key=lambda t:t[1])[:3])
print("X identical text prefix groups(>1):", sum(1 for v in dupset.values() if len(v)>1))
# Instagram
cn = 0; ln = 0; vn=0; media_kinds = {}
for r in ig:
    m = json.loads(r[5]); cn += m.get("comments") is None; ln += m.get("likes") is None
    for it in json.loads(r[6]):
        k=(it.get("kind"), it.get("status"), bool(it.get("url")), bool(it.get("sha256")))
        media_kinds[k]=media_kinds.get(k,0)+1
print("IG rows",len(ig),"comments None",cn,"likes None",ln)
print("IG media (kind,status,has_url,has_sha):",media_kinds)
print("IG handles:", sorted({r[1] for r in ig}))
# local media dir check
base="C:/Users/jeong/Documents/ai-raider/data/media"
print("media dir top:", os.listdir(base))
# samples
random.seed(7)
def rec(r): return dict(post_id=r[0],handle=r[1],url=r[2],posted_at=r[3],text=r[4],metrics=json.loads(r[5]),media=json.loads(r[6]),collected_at=r[7])
xs = [rec(r) for r in random.sample(x, 300)]
json.dump({"platform":"x","note":"random sample 300 of %d"%len(x),"items":xs}, open(out+"/sample_x.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump({"platform":"instagram","note":"all %d rows"%len(ig),"items":[rec(r) for r in ig]}, open(out+"/sample_instagram.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
print("wrote samples")
