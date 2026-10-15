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
import urllib.error
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
ROWS = 999  # 한 번에 받는 건수. 서버가 이만큼 못 주면 100으로 내려갑니다(호출 횟수를 줄여 하루 한도를 아끼려는 것)
DEFAULT_DAYS = {"win": 5, "con": 30}  # 어디까지 받았는지 기록이 없을 때 거슬러 올라갈 기간
QUOTA = {"hit": False}  # 하루 호출 한도(429)에 걸리면 True


class QuotaError(Exception):
    """API 호출 한도 초과(429). 계속 두드려 봐야 소용없으므로 따로 다룹니다."""

raw_key = os.environ.get("DATA_GO_KR_KEY", "").strip()
if not raw_key:
    sys.exit("DATA_GO_KR_KEY 가 비어 있습니다.")
KEYS = []
for k in (urllib.parse.unquote(raw_key), raw_key):
    if k not in KEYS:
        KEYS.append(k)


def call(url, key, page, begin, end, rows):
    q = {"serviceKey": key, "pageNo": page, "numOfRows": rows, "type": "json",
         "inqryDiv": 1, "inqryBgnDt": begin, "inqryEndDt": end}
    full = url + "?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote)
    req = urllib.request.Request(full, headers={"User-Agent": "remarket-bids/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            text = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise QuotaError("HTTP 429 호출 한도 초과")
        raise
    try:
        d = json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError("JSON이 아닌 응답: " + text[:200])
    d = d.get("response", d)
    head = d.get("header", {})
    if str(head.get("resultCode", "")) not in ("", "00"):
        if str(head.get("resultCode")) == "22":  # 서비스 요청제한횟수 초과
            raise QuotaError(f"API 오류 22: {head.get('resultMsg')}")
        raise RuntimeError(f"API 오류 {head.get('resultCode')}: {head.get('resultMsg')}")
    b = d.get("body", {})
    items = b.get("items") or []
    if isinstance(items, dict):
        items = items.get("item") or []
    if isinstance(items, dict):
        items = [items]
    return items, int(b.get("totalCount") or 0)


def get_page(url, key, page, begin, end, rows, tries=5):
    last = None
    for a in range(1, tries + 1):
        try:
            return call(url, key, page, begin, end, rows)
        except QuotaError as e:
            print(f"  {page}쪽 시도 {a}/{tries} 한도 초과: {e}", file=sys.stderr, flush=True)
            if a == tries or a >= 3:  # 몇 번 쉬어 봐도 안 풀리면 오늘 한도를 다 쓴 것으로 봅니다
                QUOTA["hit"] = True
                raise
            time.sleep(20 * a)
        except TRANSIENT as e:
            last = e
            print(f"  {page}쪽 시도 {a}/{tries} 실패: {e}", file=sys.stderr, flush=True)
            time.sleep(3 * a)
    raise last


def fetch_all(url, begin, end):
    """(받은 목록, 빠짐없이 다 받았는지) 를 돌려줍니다. 중간에 하나라도 놓치면 두 번째 값이 False."""
    global ROWS
    name = url.rsplit("/", 1)[-1]
    key, first, total, err = None, None, 0, None
    try:
        for k in KEYS:
            try:
                first, total = get_page(url, k, 1, begin, end, ROWS, tries=3)
                if ROWS > 100 and len(first) < min(ROWS, total):
                    # 서버가 요청한 건수만큼 안 주면 쪽 계산이 어긋나 누락이 생기므로 100건 방식으로 되돌립니다
                    print(f"  서버가 {ROWS}건씩 주지 않아 100건씩으로 바꿉니다", file=sys.stderr, flush=True)
                    ROWS = 100
                    first, total = get_page(url, k, 1, begin, end, ROWS, tries=3)
                key = k
                break
            except TRANSIENT as e:
                err = e
    except QuotaError:
        print(f"조회 중단({name}): 호출 한도 초과", file=sys.stderr, flush=True)
        return [], False
    if key is None:
        print(f"조회 실패({name}): {err}", file=sys.stderr, flush=True)
        return [], False
    out, complete = list(first), True
    print(f"{name}: 전체 {total}건", flush=True)
    page, size = 1, max(ROWS, 1)
    while len(first) and page * size < total:
        if page >= 200:
            complete = False
            print("쪽수 한도(200쪽)에 걸려 여기까지만 받습니다", file=sys.stderr, flush=True)
            break
        if time.time() - T0 > BUDGET:
            complete = False
            print("시간 제한으로 여기까지만 받습니다", file=sys.stderr, flush=True)
            break
        page += 1
        try:
            items, _ = get_page(url, key, page, begin, end, ROWS)
            out.extend(items)
        except QuotaError:
            complete = False
            print(f"  {page}쪽에서 호출 한도 초과로 멈춥니다", file=sys.stderr, flush=True)
            break
        except TRANSIENT as e:
            complete = False
            print(f"  {page}쪽 건너뜀: {e}", file=sys.stderr, flush=True)
        time.sleep(0.3)
    return out, complete


def fetch_range(url, begin, end, step=14):
    """API는 긴 기간을 주면 빈 결과를 주므로 step일씩 나눠 최근 구간부터 받습니다.

    (받은 목록, 최근~어디까지 빠짐없이 받았는지[시각]) 를 돌려줍니다. 하나도 못 받았으면 (None, None).
    """
    b0 = dt.datetime.strptime(begin, "%Y%m%d%H%M")
    e0 = dt.datetime.strptime(end, "%Y%m%d%H%M")
    out, hi, any_ok = [], e0, False
    covered, contiguous = None, True
    # 최근 구간부터 받아, 하루 호출 한도에 걸려도 가장 쓸모 있는 최근 것이 먼저 채워집니다
    while hi > b0 and time.time() - T0 <= BUDGET and not QUOTA["hit"]:
        lo = max(hi - dt.timedelta(days=step), b0)
        r, complete = fetch_all(url, lo.strftime("%Y%m%d%H%M"), hi.strftime("%Y%m%d%H%M"))
        if r:
            out.extend(r)
        if complete:
            any_ok = True
            if contiguous:
                covered = lo
        else:
            contiguous = False
        hi = lo
    return (out if (any_ok or out) else None), covered


def new_mark(old_mark, covered, b0, end_dt):
    """'여기까지는 빠짐없이 받았다' 기록을 갱신합니다.

    이번에 받은 범위가 이전 기록과 이어지거나 처음부터 끝까지 성공했을 때만 앞으로 옮기고,
    중간에 구멍이 남았으면 이전 기록을 그대로 두어 다음 실행이 그 구멍부터 다시 받게 합니다.
    """
    if covered is None:
        return old_mark
    if covered <= b0:
        return end_dt.isoformat(timespec="minutes")
    if old_mark and covered <= dt.datetime.fromisoformat(old_mark).replace(tzinfo=None):
        return end_dt.isoformat(timespec="minutes")
    return old_mark


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
    end = now.strftime("%Y%m%d%H%M")
    old_ok = old.get("ok") or {}

    def begin_for(kind):
        """직접 기간을 준 경우엔 그대로, 아니면 '마지막으로 빠짐없이 받은 시점 하루 전'부터 받습니다."""
        if env_days:
            d = now - dt.timedelta(days=int(env_days))
        else:
            if old_ok.get(kind):  # 기록이 있으면: 최근 5일, 또는 마지막 성공 시점 하루 전 중 더 먼저인 곳부터
                d = min(now - dt.timedelta(days=5), dt.datetime.fromisoformat(old_ok[kind]) - dt.timedelta(days=1))
            else:  # 기록이 없으면(처음이거나 이 기능이 들어오기 전): 구멍이 있을 수 있으니 넉넉히
                d = now - dt.timedelta(days=DEFAULT_DAYS[kind] if old["win"] else 60)
        d = max(d, now - dt.timedelta(days=KEEP_DAYS))
        return d.strftime("%Y%m%d0000")

    win, con = old["win"], old["con"]
    wb, cb = begin_for("win"), begin_for("con")
    print(f"조회 기간 낙찰 {wb} ~ {end} / 계약 {cb} ~ {end}", flush=True)
    ws, w_cov = fetch_range(WIN_URL, wb, end)
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
    cs, c_cov = fetch_range(CON_URL, cb, end, step=4)  # 계약은 하루 3천건 이상이라 4일씩 나눠야 쪽수 한도(200쪽)에 안 걸립니다
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
    ok = {
        "win": new_mark(old_ok.get("win"), w_cov, dt.datetime.strptime(wb, "%Y%m%d%H%M"), now),
        "con": new_mark(old_ok.get("con"), c_cov, dt.datetime.strptime(cb, "%Y%m%d%H%M"), now),
    }
    rmcrypt.save("awards", {"updated": now.isoformat(timespec="minutes"), "win": win, "con": con, "ok": ok})
    print(f"저장 완료: 낙찰 {len(win)}건, 계약 {len(con)}건", flush=True)
    for kind, label in (("win", "낙찰"), ("con", "계약")):
        if ok[kind] != now.isoformat(timespec="minutes"):
            print(f"⚠ {label} 정보를 끝까지 받지 못했습니다. 다음 실행 때 빠진 기간부터 이어서 받습니다 (마지막으로 빠짐없이 받은 시점: {ok[kind] or '기록 없음'})", flush=True)


main()
