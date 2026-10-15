"""나라장터 공사 입찰공고를 공공데이터포털 API로 가져와 docs/data.json에 쌓아 두는 프로그램.

환경변수 DATA_GO_KR_KEY 에 인증키가 들어 있어야 합니다.
선택: DAYS(처음 가져올 기간, 기본 14일)
"""
import datetime as dt
import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import rmcrypt

BASE = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"
OP = "getBidPblancListInfoCnstwk"  # 입찰공고목록 정보에 대한 공사조회
KST = dt.timezone(dt.timedelta(hours=9))
DATA = os.path.join("docs", "data.json")
KEEP_DAYS = 90
AFTER_CLOSE_DAYS = 60  # 개찰이 끝난 공고도 이만큼은 남겨 낙찰·계약 결과와 맞춰 봅니다
SLIM_AFTER = 7  # 마감 후 이 일수가 지나면 첨부·담당자 등은 덜어 내 파일을 줄입니다

raw_key = os.environ.get("DATA_GO_KR_KEY", "").strip()
if not raw_key:
    sys.exit("DATA_GO_KR_KEY 가 비어 있습니다. 저장소 Settings > Secrets and variables > Actions 를 확인하세요.")
# Encoding/Decoding 어느 쪽 키가 들어와도 되도록 두 가지를 모두 시도합니다.
KEY_VARIANTS = []
for k in (urllib.parse.unquote(raw_key), raw_key):
    if k not in KEY_VARIANTS:
        KEY_VARIANTS.append(k)


def call(key, page, begin, end, rows=100):
    params = {
        "serviceKey": key,
        "pageNo": page,
        "numOfRows": rows,
        "type": "json",
        "inqryDiv": 1,  # 1 = 공고게시일시 기준
        "inqryBgnDt": begin,
        "inqryEndDt": end,
    }
    url = f"{BASE}/{OP}?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}"
    req = urllib.request.Request(url, headers={"User-Agent": "remarket-bids/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        text = r.read().decode("utf-8", "replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError("JSON이 아닌 응답: " + text[:300])


def parse(resp):
    body = resp.get("response", {})
    head = body.get("header", {})
    code = str(head.get("resultCode", ""))
    if code and code != "00":
        raise RuntimeError(f"API 오류 {code}: {head.get('resultMsg')}")
    b = body.get("body", {})
    items = b.get("items") or []
    if isinstance(items, dict):
        items = items.get("item") or []
    if isinstance(items, dict):
        items = [items]
    return items, int(b.get("totalCount") or 0)


TRANSIENT = (OSError, ValueError, http.client.HTTPException, RuntimeError)


def get_page(key, page, begin, end, tries=5):
    """한 쪽을 가져옵니다. 네트워크가 끊기면 잠시 쉬었다 다시 시도합니다."""
    last = None
    for attempt in range(1, tries + 1):
        try:
            return parse(call(key, page, begin, end))
        except TRANSIENT as e:
            last = e
            print(f"  {page}쪽 시도 {attempt}/{tries} 실패: {e}", file=sys.stderr)
            time.sleep(3 * attempt)
    raise last


def fetch_all(begin, end):
    # 1) 첫 쪽으로 어느 키 방식이 되는지 확인
    key, first, total, last_err = None, None, 0, None
    for k in KEY_VARIANTS:
        try:
            first, total = get_page(k, 1, begin, end, tries=3)
            key = k
            break
        except TRANSIENT as e:
            last_err = e
            print(f"키 방식 시도 실패: {e}", file=sys.stderr)
    if key is None:
        print(f"주의: 모든 키 방식이 실패했습니다(이번에는 새 공고 없이 진행): {last_err}", file=sys.stderr)
        return []
    out = list(first)
    print(f"전체 {total}건, 1쪽 {len(first)}건")
    # 2) 나머지 쪽은 되는 방식으로만 계속 (실패한 쪽은 건너뛰고 받은 것은 보존)
    page, failed = 1, []
    while len(first) and page * 100 < total and page < 100:
        page += 1
        try:
            items, _ = get_page(key, page, begin, end)
            out.extend(items)
        except TRANSIENT as e:
            failed.append(page)
            print(f"  {page}쪽 건너뜀: {e}", file=sys.stderr)
        time.sleep(0.3)
    if failed:
        print(f"주의: {failed}쪽을 받지 못했습니다. 다음 실행에서 보충됩니다.", file=sys.stderr)
    return out


def norm(it):
    atts = []
    for i in range(1, 11):
        n, u = it.get(f"ntceSpecFileNm{i}"), it.get(f"ntceSpecDocUrl{i}")
        if n and u:
            atts.append({"name": n, "url": u})
    no, ordr = it.get("bidNtceNo", ""), it.get("bidNtceOrd", "")
    return {
        "id": f"{no}-{ordr}",
        "title": it.get("bidNtceNm") or "",
        "org": it.get("ntceInsttNm") or "",
        "demand": it.get("dminsttNm") or "",
        "posted": it.get("bidNtceDt") or "",
        "close": it.get("bidClseDt") or "",
        "open": it.get("opengDt") or "",
        "price": it.get("presmptPrce") or it.get("asignBdgtAmt") or "",
        "site": it.get("cnstrtsiteRgnNm") or "",
        "area_ok": it.get("prtcptPsblRgnNm") or "",
        "url": it.get("bidNtceDtlUrl") or it.get("bidNtceUrl") or "",
        "atts": atts,
        "contact": it.get("ntceInsttOfclNm") or "",
        "tel": it.get("ntceInsttOfclTelNo") or "",
        "method": it.get("cntrctCnclsMthdNm") or "",
        "bidtype": it.get("bidMethdNm") or "",
        "winner": it.get("sucsfbidMthdNm") or "",
        "kind": it.get("mainCnsttyNm") or "",
        "budget": it.get("bdgtAmt") or "",
        "begin": it.get("bidBeginDt") or "",
    }


def main():
    now = dt.datetime.now(KST)
    existing = {}
    try:
        for r in (rmcrypt.load("data") or {}).get("items", []):
            existing[r["id"]] = r
    except (ValueError, KeyError):
        pass
    env_days = os.environ.get("DAYS", "").strip()
    days = int(env_days) if env_days else (5 if existing else 60)
    begin = (now - dt.timedelta(days=days)).strftime("%Y%m%d0000")
    end = now.strftime("%Y%m%d%H%M")
    print(f"조회 기간 {begin} ~ {end}")
    raw = []
    b0 = dt.datetime.strptime(begin, "%Y%m%d%H%M").replace(tzinfo=KST)
    e0 = dt.datetime.strptime(end, "%Y%m%d%H%M").replace(tzinfo=KST)
    cur = b0
    while cur < e0:  # 조회 기간이 길면 API가 빈 결과를 주므로 14일씩 나눠 받습니다
        nxt = min(cur + dt.timedelta(days=14), e0)
        print(f"  구간 {cur:%m-%d} ~ {nxt:%m-%d}")
        raw.extend(fetch_all(cur.strftime("%Y%m%d%H%M"), nxt.strftime("%Y%m%d%H%M")))
        cur = nxt
    print(f"받은 공고 {len(raw)}건")
    for it in raw:
        r = norm(it)
        if r["id"] != "-":
            existing[r["id"]] = r
    # 입찰마감이 지난 지 60일 넘은 공고는 정리해서 파일이 커지지 않게 합니다.
    cutoff = (now - dt.timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    stale = (now - dt.timedelta(days=AFTER_CLOSE_DAYS)).strftime("%Y-%m-%d")
    slim = (now - dt.timedelta(days=SLIM_AFTER)).strftime("%Y-%m-%d")
    items = [
        r for r in existing.values()
        if (r["posted"] or "9999")[:10] >= cutoff and (r["close"] or r["posted"] or "9999")[:10] >= stale
    ]
    for r in items:
        if (r["close"] or "9999")[:10] < slim:
            r["atts"], r["contact"], r["tel"], r["bidtype"], r["winner"], r["budget"], r["begin"] = [], "", "", "", "", "", ""
    items.sort(key=lambda r: r["posted"], reverse=True)
    os.makedirs("docs", exist_ok=True)
    rmcrypt.save("data", {"updated": now.isoformat(timespec="minutes"), "count": len(items), "items": items})
    print(f"저장 완료: 누적 {len(items)}건")


main()
