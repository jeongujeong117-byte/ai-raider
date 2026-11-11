import sqlite3, json, sys, collections
c = sqlite3.connect("file:"+sys.argv[1]+"?mode=ro", uri=True)
rows = c.execute("select post_id,handle,text,raw from posts where platform='x'").fetchall()
ids = {r[0] for r in rows}
keys = collections.Counter()
sample = None
for r in rows:
    try: raw = json.loads(r[3])
    except Exception: continue
    for k in raw: keys[k]+=1
    if sample is None and r[2].startswith("@"): sample = raw
print("raw keys (top):", [k for k,_ in keys.most_common(40)])
reply_fields = [k for k in keys if "reply" in k.lower() or "conversation" in k.lower() or "quoted" in k.lower() or "retweet" in k.lower()]
print("relation fields:", {k:keys[k] for k in reply_fields})
tot=with_parent=parent_in_db=0; texts=collections.Counter()
for r in rows:
    try: raw=json.loads(r[3])
    except Exception: continue
    if not r[2].startswith("@"): continue
    tot+=1
    pid = raw.get("inReplyToTweetId") or raw.get("in_reply_to_status_id") or raw.get("inReplyToTweetIdStr")
    if pid:
        with_parent+=1
        if str(pid) in ids: parent_in_db+=1
    texts[" ".join(r[2].split())]+=1
print("replies",tot,"with parent id",with_parent,"parent also in DB",parent_in_db)
dups = {t:n for t,n in texts.items() if n>1}
print("reply texts duplicated:",len(dups),"rows saved if merged:",sum(n-1 for n in dups.values()))
print("top dup:", [(t[:50],n) for t,n in sorted(dups.items(), key=lambda x:-x[1])[:5]])
