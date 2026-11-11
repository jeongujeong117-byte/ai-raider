import csv, sys, collections, re
rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8-sig", newline="")))
print("rows", len(rows), "cols", list(rows[0].keys()))
by = collections.Counter(r["platform"] for r in rows); print("platform", dict(by))
keys = collections.Counter((r["platform"], r["post_id"]) for r in rows)
d = {k:v for k,v in keys.items() if v>1}; print("duplicate (platform,post_id):", len(d), list(d.items())[:3])
for p in by:
    rs = [r for r in rows if r["platform"]==p]
    empt_t = sum(1 for r in rs if not r["title"].strip())
    empt_u = sum(1 for r in rs if not r["url"].strip())
    bad_date = sum(1 for r in rs if not re.match(r"^\d{4}-\d\d-\d\dT", r["posted_at"]))
    repl = sum(1 for r in rs if "\ufffd" in r["title"])
    ds = sorted(r["posted_at"] for r in rs if r["posted_at"])
    print(p, "empty_title", empt_t, "empty_url", empt_u, "bad_date", bad_date, "mojibake", repl, "range", ds[0][:10] if ds else None, ds[-1][:10] if ds else None)
