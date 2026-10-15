"""나라장터 공사 낙찰결과·계약결과를 받아 docs/awards.json 에 쌓습니다.

환경변수 DATA_GO_KR_KEY 필요. 선택: DAYS(처음 가져올 기간).
실패해도 기존 awards.json 은 그대로 보존합니다.
"""
import datetime as dt
import http.client
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

import rmcrypt

H = "https://apis.data.go.kr/1230000"
WIN_URL = f"{H}/as/ScsbidInfoService/getScsbidListSttusCnstwk"
CON_URL = f"{H}/ao/CntrctInfoService/getCntrctInfoListCnstwk"
KST = dt.timezone(dt.timedelta(hours=9))
OUT = os.path.join("docs", "awards.json")
KEEP_DAYS = 60
T0 = time.time()
BUDGET = 25 * 60  # 이 시간이 지나면 더 받지 않고 지금까지 받은 것만 저장합니다
TRANSIENT = (OSError, ValueError, http.client.HTTPException, RuntimeError)

raw_key = os.environ.get("DATA_GO_KR_KEY", "").strip()
if not raw_key:
    sys.exit("DATA_GO_KR_KEY 가 비어 있습니다.")
KEYS = []
for k in (urllib.parse.unquote(raw_key), raw_key):
    if k not in KEYS:
        KEYS.append(k)


def call(url, key, page, begin, end):
    q = {"serviceKey": key, "pageNo": page, "numOfRows": 100, "type": "json",
         "inqryDiv": 1, "inqryBgnDt": begin, "inqryEndDt": end}
    full = url + "?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote)
    req = urllib.request.Request(full, headers={"User-Agent": "remarket-bids/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        text = r.read().decode("utf-8", "replace")
    try:
        d = json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError("JSON이 아닌 응답: " + text[:200])
    d = d.get("response", d)
    head = d.get("header", {})
    if str(head.get("resultCode", "")) not in ("", "00"):
        raise RuntimeError(f"API 오류 {head.get('resultCode')}: {head.get('resultMsg')}")
    b = d.get("body", {})
    items = b.get("items") or []
    if isinstance(items, dict):
        items = items.get("item") or []
    if isinstance(items, dict):
        items = [items]
    return items, int(b.get("totalCount") or 0)


def get_page(url, key, page, begin, end, tries=5):
    last = None
    for a in range(1, tries + 1):
        try:
            return call(url, key, page, begin, end)
        except TRANSIENT as e:
            last = e
            print(f"  {page}쪽 시도 {a}/{tries} 실패: {e}", file=sys.stderr)
            time.sleep(3 * a)
    raise last


def fetch_all(url, begin, end):
    key, first, total, err = None, None, 0, None
    for k in KEYS:
        try:
            first, total = get_page(url, k, 1, begin, end, tries=3)
            key = k
            break
        except TRANSIENT as e:
            err = e
    if key is None:
        print(f"조회 실패({url.rsplit('/', 1)[-1]}): {err}", file=sys.stderr)
        return None
    out = list(first)
    print(f"{url.rsplit('/', 1)[-1]}: 전체 {total}건")
    page = 1
    while len(first) and page * 100 < total and page < 200:
        if time.time() - T0 > BUDGET:
            print("시간 제한으로 여기까지만 받습니다", file=sys.stderr)
            break
        page += 1
        try:
            items, _ = get_page(url, key, page, begin, end)
            out.extend(items)
        except TRANSIENT as e:
            print(f"  {page}쪽 건너뜀: {e}", file=sys.stderr)
        time.sleep(0.3)
    return out


def fetch_range(url, begin, end, step=14):
    """API는 긴 기간을 주면 빈 결과를 주므로 14일씩 나눠 받습니다. 한 구간이라도 실패하면 None."""
    b0 = dt.datetime.strptime(begin, "%Y%m%d%H%M")
    e0 = dt.datetime.strptime(end, "%Y%m%d%H%M")
    out, hi, ok = [], e0, False
    while hi > b0 and time.time() - T0 <= BUDGET:  # 최근 구간부터 받아, 하루 호출 한도에 걸려도 가장 쓸모 있는 최근 것이 먼저 채워집니다
        lo = max(hi - dt.timedelta(days=step), b0)
        r = fetch_all(url, lo.strftime("%Y%m%d%H%M"), hi.strftime("%Y%m%d%H%M"))
        if r is not None:
            out.extend(r)
            ok = True
        hi = lo
    return out if ok else None


def parse_corps(s):
    """[1^주계약업체^단독^업체명^대표자^국적^지분^업체명^^사업자번호] 형태를 풀어 줍니다."""
    res = []
    for m in re.findall(r"\[(.*?)\]", s or ""):
        p = m.split("^")
        if len(p) >= 10:
            res.append({"role": p[1], "name": p[3], "ceo": p[4], "share": p[6], "biz": re.sub(r"\D", "", p[9])})
    return res


def main():
    now = dt.datetime.now(KST)
    old = {"win": {}, "con": {}}
    loaded = rmcrypt.load("awards")
    if loaded:
        old = loaded
        old.setdefault("win", {}); old.setdefault("con", {})
    env_days = os.environ.get("DAYS", "").strip()
    days = int(env_days) if env_days else (5 if old["win"] else 60)
    begin = (now - dt.timedelta(days=days)).strftime("%Y%m%d0000")
    end = now.strftime("%Y%m%d%H%M")
    print(f"조회 기간 {begin} ~ {end}")

    win, con = old["win"], old["con"]
    ws = fetch_range(WIN_URL, begin, end)
    for it in ws or []:
        no, od = it.get("bidNtceNo"), it.get("bidNtceOrd")
        if not no:
            continue
        rec = {
            "n": it.get("bidwinnrNm") or "", "b": re.sub(r"\D", "", it.get("bidwinnrBizno") or ""),
            "c": it.get("bidwinnrCeoNm") or "", "a": it.get("bidwinnrAdrs") or "",
            "t": it.get("bidwinnrTelNo") or "", "amt": it.get("sucsfbidAmt") or "",
            "rate": it.get("sucsfbidRate") or "", "d": (it.get("fnlSucsfDate") or it.get("rlOpengDt") or "")[:10],
            "np": it.get("prtcptCnum") or "", "nm": it.get("bidNtceNm") or "", "dm": it.get("dminsttNm") or "", "rb": it.get("rbidNo") or "000", "reg": it.get("rgstDt") or "",
        }
        k = f"{no}-{od}"
        if k not in win or rec["rb"] >= win[k].get("rb", "000"):
            win[k] = rec
    cs = fetch_range(CON_URL, begin, end, step=4)  # 계약은 하루 3천건 이상이라 4일씩 나눠야 쪽수 한도(200쪽)에 안 걸립니다
    for it in cs or []:
        no = it.get("ntceNo")
        if not no:
            continue
        corps = parse_corps(it.get("corpList"))
        if not corps:
            continue
        rec = {
            "corps": corps, "date": it.get("cntrctDate") or it.get("cntrctCnclsDate") or "",
            "amt": it.get("totCntrctAmt") or "", "reg": it.get("rgstDt") or "",
            "no": it.get("untyCntrctNo") or "", "nm": it.get("cnstwkNm") or "", "org": it.get("cntrctInsttNm") or "", "url": it.get("cntrctDtlInfoUrl") or "",
        }
        if no not in con or rec["reg"] >= con[no].get("reg", ""):
            con[no] = rec
    if ws is None and cs is None:
        sys.exit("낙찰·계약 모두 받지 못해 기존 파일을 그대로 둡니다.")

    cutoff = (now - dt.timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    # 계약 목록은 공사 전체라 양이 많으므로, 낙찰 결과와 연결되는 것만 보관합니다.
    won_nos = {k.split("-")[0] for k in win}
    con = {k: v for k, v in con.items() if k in won_nos}
    win = {k: v for k, v in win.items() if (v.get("reg") or v.get("d") or "9999")[:10] >= cutoff}
    con = {k: v for k, v in con.items() if (v.get("reg") or v.get("date") or "9999")[:10] >= cutoff}
    rmcrypt.save("awards", {"updated": now.isoformat(timespec="minutes"), "win": win, "con": con})
    print(f"저장 완료: 낙찰 {len(win)}건, 계약 {len(con)}건")


main()
