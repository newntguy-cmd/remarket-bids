import json, os, urllib.parse, urllib.request
raw = os.environ["DATA_GO_KR_KEY"].strip()
keys = [urllib.parse.unquote(raw), raw]
BASE = "https://apis.data.go.kr/1230000/as/ScsbidInfoService"
out = []
def go(op, **q):
    for k in keys:
        p = {"serviceKey": k, "pageNo": 1, "numOfRows": 5, "type": "json", **q}
        u = f"{BASE}/{op}?" + urllib.parse.urlencode(p, quote_via=urllib.parse.quote)
        try:
            t = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "x"}), timeout=60).read().decode("utf-8", "replace")
            out.append(f"== {op} {q}\n{t[:2500]}\n")
            return
        except Exception as e:
            out.append(f"== {op} {q} ERR {e}\n")
for op in ("getOpengResultListInfoCnstwk", "getOpengResultListInfoCnstwkPreparPcDetail"):
    go(op, inqryDiv=2, bidNtceNo="R26BK01774112")
    go(op, inqryDiv=1, inqryBgnDt="202610221200", inqryEndDt="202610221400")
open("docs/probe.txt", "w", encoding="utf-8").write("\n".join(out))
