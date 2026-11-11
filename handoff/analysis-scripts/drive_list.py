import sys
import gdown

url = sys.argv[1]
files = gdown.download_folder(url=url, skip_download=True, quiet=True, use_cookies=False)
print("total entries:", len(files))
from collections import Counter
import os
ext = Counter(os.path.splitext(f.path)[1].lower() or "(none)" for f in files)
print("by extension:", dict(ext.most_common(20)))
top = Counter(f.path.split("/")[0] for f in files)
print("by top-level:", dict(top.most_common(30)))
for f in files[:40]:
    print(f.path)
