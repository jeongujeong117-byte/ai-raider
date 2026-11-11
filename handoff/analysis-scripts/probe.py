import sqlite3, sys, json, random
c = sqlite3.connect("file:"+sys.argv[1]+"?mode=ro", uri=True)
print("posts by platform:", c.execute("select platform,count(*) from posts group by platform").fetchall())
print("health:", c.execute("select * from collection_health").fetchall())
for p in ("instagram","x"):
    print("\n==",p)
    q = lambda s: c.execute(s, (p,)).fetchone()[0]
    n = q("select count(*) from posts where platform=?")
    print("rows",n)
    if not n: continue
    print("handles", q("select count(distinct handle) from posts where platform=?"))
    print("range", c.execute("select min(posted_at),max(posted_at) from posts where platform=?",(p,)).fetchone())
    print("empty text", q("select count(*) from posts where platform=? and (text is null or trim(text)='')"))
    print("metrics NULL", q("select count(*) from posts where platform=? and (metrics is null or metrics='' or metrics='null')"))
    print("media empty", q("select count(*) from posts where platform=? and (media is null or media='' or media='[]')"))
    print("dup ids", c.execute("select count(*) from (select post_id from posts where platform=? group by post_id having count(*)>1)",(p,)).fetchone()[0])
    print("U+FFFD in text", q("select count(*) from posts where platform=? and text like '%'||char(65533)||'%'"))
    rows = c.execute("select post_id,handle,posted_at,text,metrics,media from posts where platform=? order by random() limit 4",(p,)).fetchall()
    for r in rows:
        print({"id":r[0],"handle":r[1],"at":r[2],"text":(r[3] or "")[:90].replace("\n"," "),"metrics":r[4],"media":(r[5] or "")[:80]})
