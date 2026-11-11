import sqlite3, sys
c = sqlite3.connect("file:"+sys.argv[1]+"?mode=ro", uri=True)
for (n,) in c.execute("select name from sqlite_master where type='table' order by name"):
    cnt = c.execute(f'select count(*) from "{n}"').fetchone()[0]
    cols = [r[1] for r in c.execute(f'pragma table_info("{n}")')]
    print(n, cnt, cols)
