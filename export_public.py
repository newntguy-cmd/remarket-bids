"""입찰 레이더의 잠긴 데이터를 읽어, 공개해도 되는 항목만 docs/public.json 으로 내보냅니다.

공개하지 않는 것: 대표자명, 개인사업자의 모든 연락 정보.
공개하는 것: 공사명, 발주처, 지역, 공종, 낙찰(예정) 업체명, 금액, 낙찰률, 날짜, 참가업체 수,
            그리고 법인(주식회사 등)에 한해 사업자번호·주소·대표 전화(조달청 등록 정보).
환경변수 SITE_PASSWORD 가 있으면 잠긴 파일을, 없으면 평문 json 을 읽습니다.
"""
import datetime as dt
import json
import os
import re
import sys

import rmcrypt

KST = dt.timezone(dt.timedelta(hours=9))
KEEP_DAYS = 60
OUT = os.path.join("docs", "public.json")
OUT_BIDS = os.path.join("docs", "bids.json")

# 지역 판별 (docs/index.html 의 detect 와 같은 규칙)
PRE = [("광주시", "경기"), ("전남광주", "광주·전남"), ("BIFC", "부산")]
PROV = [("서울", "서울"), ("경기도", "경기"), ("인천", "인천"), ("강원", "강원"), ("충청북도", "충북"), ("충북", "충북"),
        ("충청남도", "충남"), ("충남", "충남"), ("대전", "대전"), ("세종", "세종"), ("전북", "전북"), ("전라북도", "전북"),
        ("전남", "광주·전남"), ("전라남도", "광주·전남"), ("광주", "광주·전남"), ("경상북도", "경북"), ("경북", "경북"),
        ("대구", "대구"), ("경상남도", "경남"), ("경남", "경남"), ("부산", "부산"), ("울산", "울산"), ("제주", "제주")]
CITY = {
    "경기": "수원 성남 고양 용인 부천 안산 안양 남양주 화성 평택 의정부 시흥 파주 김포 광명 군포 !하남 !오산 !이천 !여주 !구리 양주 동두천 !과천 !의왕 !안성 양평 가평 연천 포천",
    "강원": "춘천 원주 강릉 !동해 !태백 속초 삼척 홍천 횡성 영월 평창 정선 철원 화천 양구 !인제 양양",
    "충북": "청주 충주 제천 !보은 !옥천 !영동 증평 진천 괴산 !음성 단양",
    "충남": "천안 !공주 보령 아산 서산 논산 계룡 당진 금산 !부여 서천 청양 홍성 !예산 태안",
    "전북": "전주 군산 익산 정읍 남원 김제 완주 !진안 무주 !장수 임실 순창 고창 부안",
    "광주·전남": "목포 여수 순천 나주 광양 담양 곡성 구례 고흥 보성 화순 장흥 강진 해남 완도 진도 함평 !영광 !장성 무안 신안",
    "경북": "포항 경주 김천 안동 구미 !영주 영천 !상주 문경 경산 군위 의성 청송 !영양 영덕 !청도 !고령 !성주 칠곡 예천 봉화 울진 울릉",
    "경남": "창원 진주 통영 사천 김해 밀양 거제 양산 의령 함안 창녕 !남해 하동 산청 함양 거창 합천",
}


def _mk(t):
    return re.compile(t[1:] + "[시군]") if t[0] == "!" else re.compile(t)


PRE_RE = [(re.compile(k), r) for k, r in PRE]
PROV_RE = [(re.compile(k), r) for k, r in PROV]
CITY_RE = [(_mk(t), r) for r, ts in CITY.items() for t in ts.split()]


def _earliest(text, lst):
    best = None
    for rx, reg in lst:
        m = rx.search(text)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), reg)
    return best[1] if best else None


def detect(*texts):
    for t in texts:
        if not t:
            continue
        g = _earliest(t, PRE_RE) or _earliest(t, PROV_RE) or _earliest(t, CITY_RE)
        if g:
            return g
    return "미분류"


CORP_NAME = re.compile(r"주식회사|\(주\)|㈜|유한회사|\(유\)|합자회사|합명회사|협동조합|농업회사법인|영농조합법인|사단법인|재단법인|\(사\)|\(재\)")


def is_corp(name, biz):
    """법인 여부. 사업자번호 가운데 두 자리가 81~88이면 법인, 01~79이면 개인사업자입니다."""
    d = re.sub(r"\D", "", biz or "")
    if len(d) == 10:
        mid = int(d[3:5])
        if 81 <= mid <= 88:
            return True
        if 1 <= mid <= 79:
            return False
    return bool(CORP_NAME.search(name or ""))


def money(s):
    try:
        return int(float(str(s).replace(",", "")))
    except ValueError:
        return 0


def export_bids(bids, now):
    """진행 중인 입찰공고를 공개용으로 내보냅니다. 담당자 이름·전화·첨부파일은 넣지 않습니다."""
    today = now.strftime("%Y-%m-%d")
    out = []
    for b in bids:
        cl = (b.get("close") or "")
        if not cl or cl[:10] < today:
            continue
        u = b.get("url") or ""
        if u.startswith("http://"):
            u = "https://" + u[len("http://"):]
        if not re.match(r"^https://[a-z0-9.]*g2b\.go\.kr/", u):
            u = ""
        title = b.get("title") or ""
        out.append({
            "id": b["id"], "nm": title, "og": b.get("org") or "", "dm": b.get("demand") or "",
            "pd": (b.get("posted") or "")[:10], "cl": cl[:16], "op": (b.get("open") or "")[:16],
            "pr": money(b.get("price")), "rg": detect(b.get("site"), b.get("demand"), b.get("org"), title),
            "kind": b.get("kind") or "", "ar": b.get("area_ok") or "", "m": b.get("method") or "", "u": u,
        })
    out.sort(key=lambda r: (r["cl"], r["id"]))
    with open(OUT_BIDS, "w", encoding="utf-8") as f:
        json.dump({"updated": now.isoformat(timespec="minutes"), "n": len(out), "items": out}, f, ensure_ascii=False, separators=(",", ":"))
    print(f"입찰공고 {len(out)}건 저장 ({OUT_BIDS})")


CORP_URL = "https://apis.data.go.kr/1230000/ao/UsrInfoService02/getPrcrmntCorpBasicInfo02"
FILL_MAX = 600


def _clean(v):
    v = (v or "").strip()
    return "" if "*" in v else v


def _items(j):
    b = (j.get("response") or j).get("body") or {}
    it = b.get("items")
    if isinstance(it, dict):
        it = it.get("item")
    if isinstance(it, dict):
        it = [it]
    return it or []


BIZNO_MAX = 150


def bizno_lookup(biz, ua):
    """비즈노(bizno.net) 검색 화면에서 사업자번호로 전화·주소를 찾습니다. 못 찾으면 None."""
    import urllib.parse
    import urllib.request
    import html as H

    def get(u):
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": ua, "Accept-Language": "ko"}), timeout=10) as r:
            return r.read().decode("utf-8", "replace")

    def pick(page, label):
        m = re.search(label + r"\s*</(?:th|dt|td|span|b|strong)>\s*<(?:td|dd|span)[^>]*>(.*?)</(?:td|dd|span)>", page, re.S)
        if not m:
            m = re.search(label + r"[^<\n]{0,6}[:\s]*</?[^>]*>\s*([^<]{4,120})", page)
        return H.unescape(re.sub(r"<[^>]+>", " ", m.group(1))).strip() if m else ""

    page = get("https://bizno.net/?query=" + biz)
    link = re.search(r'href="(/article/[^"#?]+|/\d{3}-?\d{2}-?\d{5}[^"]*)"', page)
    if link:
        page = get("https://bizno.net" + link.group(1))
    t = pick(page, "전화번호")
    a = pick(page, "(?:사업장\\s*)?주소")
    t = _clean(re.sub(r"[^0-9\-]", "", t)) if re.search(r"\d{2,4}-\d{3,4}-\d{4}", t) else ""
    a = _clean(a)
    return {"a": a, "t": t} if (t or a) else None


def fill_missing(rows, corp, now):
    """낙찰 결과에 전화·주소가 비어 있거나 가려진 법인은 조달업체 등록정보(사업자번호 조회)에서 채웁니다."""
    import urllib.parse
    import urllib.request
    raw = os.environ.get("DATA_GO_KR_KEY", "").strip()
    if not raw:
        print("DATA_GO_KR_KEY 없음: 연락처 보충 건너뜀")
        return
    cache = rmcrypt.load("corpx") or {}
    today = now.strftime("%Y-%m-%d")
    need = []
    for r in rows:
        b = r.get("b")
        if not b or b in need:
            continue
        c = corp.get(b)
        if c and (_clean(c.get("t")) or _clean(c.get("a"))):
            continue
        hit = cache.get(b)
        if hit and (hit.get("t") or hit.get("a")):
            corp[b] = {"a": hit.get("a", ""), "t": hit.get("t", ""), "d": hit.get("d", "")}
            continue
        if hit and (hit.get("x") or "") >= (now - dt.timedelta(days=7)).strftime("%Y-%m-%d"):
            continue
        need.append(b)
    print(f"연락처 보충 대상 {len(need)}곳 (이번 실행 최대 {FILL_MAX}곳)")
    key = urllib.parse.unquote(raw)
    got = tried = 0
    shown = 0
    import time as _t
    t0 = _t.time()
    fails = 0
    for b in need[:FILL_MAX]:
        if _t.time() - t0 > 240 or fails >= 8:
            print(f"  조달청 조회 중단(시간 {int(_t.time() - t0)}초, 연속 실패 {fails}회)")
            break
        tried += 1
        found = None
        for extra in ({"inqryDiv": "3", "bizno": b}, {"inqryDiv": "1", "bizno": b}):
            q = {"serviceKey": key, "pageNo": 1, "numOfRows": 5, "type": "json"}
            q.update(extra)
            try:
                with urllib.request.urlopen(urllib.request.Request(CORP_URL + "?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote), headers={"User-Agent": "remarket-bids/1.0"}), timeout=8) as resp:
                    txt = resp.read().decode("utf-8", "replace")
                if shown < 3:
                    print("  응답 예시:", extra.get("inqryDiv"), txt[:400].replace("\n", " "))
                    shown += 1
                its = _items(json.loads(txt))
            except Exception as e:
                fails += 1
                if shown < 3:
                    print("  오류:", extra.get("inqryDiv"), str(e)[:200])
                    shown += 1
                continue
            fails = 0
            for it in its:
                if re.sub(r"\D", "", str(it.get("bizno") or it.get("bizrno") or b)) != b:
                    continue
                t = _clean(it.get("telNo") or it.get("tel") or "")
                a = _clean(" ".join(x for x in (it.get("adrs") or it.get("rgnAdrs") or "", it.get("dtlAdrs") or "") if x))
                if t or a:
                    found = {"a": a, "t": t, "d": today}
                    break
            if found:
                break
        if found:
            cache[b] = found
            corp[b] = dict(found)
            got += 1
        else:
            cache[b] = {"x": today}
    print(f"연락처 보충(조달청 등록정보): {tried}곳 조회, {got}곳 채움")
    # 2차: 조달청에도 없으면 비즈노에서 사업자번호로 찾습니다 (robots.txt 가 막으면 하지 않고, 천천히 소량만)
    import urllib.request
    ua = "Mozilla/5.0 (compatible; ilgammarket-bot/1.0; +https://ilgammarket.co.kr)"
    allow = True
    try:
        rb = urllib.request.urlopen(urllib.request.Request("https://bizno.net/robots.txt", headers={"User-Agent": ua}), timeout=20).read().decode("utf-8", "replace")
        grp = False
        for ln in rb.splitlines():
            l = ln.split("#")[0].strip().lower()
            if l.startswith("user-agent:"):
                grp = l.split(":", 1)[1].strip() == "*"
            elif grp and l.startswith("disallow:") and l.split(":", 1)[1].strip() in ("/", "/?query", "/?"):
                allow = False
    except Exception as e:
        print("  비즈노 robots.txt 확인 실패:", str(e)[:120])
    if not allow:
        print("  비즈노 robots.txt 가 막고 있어 조회하지 않습니다")
    else:
        n2 = g2 = 0
        tb = _t.time()
        bf = 0
        left = [b for b in need if not (cache.get(b) or {}).get("t") and not (cache.get(b) or {}).get("a")]
        for b in left[:BIZNO_MAX]:
            if _t.time() - tb > 240 or bf >= 5:
                print(f"  비즈노 조회 중단(시간 {int(_t.time() - tb)}초, 연속 실패 {bf}회)")
                break
            n2 += 1
            try:
                f = bizno_lookup(b, ua)
                bf = 0
            except Exception as e:
                bf += 1
                if n2 <= 3:
                    print("  비즈노 오류:", str(e)[:160])
                f = None
            if n2 <= 2:
                print("  비즈노 결과 예시:", b, f)
            if f:
                f["d"] = today
                cache[b] = f
                corp[b] = dict(f)
                g2 += 1
            _t.sleep(2.0)
        print(f"연락처 보충(비즈노): {n2}곳 조회, {g2}곳 채움")
    rmcrypt.save("corpx", cache)


def main():
    now = dt.datetime.now(KST)
    bids = (rmcrypt.load("data") or {}).get("items", [])
    aw = rmcrypt.load("awards") or {}
    by_id = {b["id"]: b for b in bids}
    cutoff = (now - dt.timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    rows = []
    corp = {}
    for status, src in (("낙찰", aw.get("win") or {}), ("낙찰예정", aw.get("ope") or {})):
        for k, v in src.items():
            # 연락처는 최근 낙찰이 아니어도 모읍니다: 방금 낙찰된 업체는 계약이 아직 없어서, 예전 계약의 전화·주소를 대신 씁니다
            bz0 = re.sub(r"\D", "", v.get("b") or "")
            if bz0 and v.get("n") and (v.get("t") or v.get("a")) and is_corp(v["n"], bz0):
                if bz0 not in corp or (v.get("d") or "") > corp[bz0]["d"]:
                    corp[bz0] = {"a": v.get("a") or "", "t": v.get("t") or "", "d": v.get("d") or ""}
            if (v.get("d") or "") < cutoff or not v.get("n"):
                continue
            b = by_id.get(k, {})
            title = v.get("nm") or b.get("title") or ""
            u = b.get("url") or ""
            if u.startswith("http://"):
                u = "https://" + u[len("http://"):]
            if not re.match(r"^https://[a-z0-9.]*g2b\.go\.kr/", u):
                u = ""
            bz = re.sub(r"\D", "", v.get("b") or "")
            cb = ""
            if bz and is_corp(v["n"], bz):
                cb = bz
                if (v.get("t") or v.get("a")) and (bz not in corp or (v.get("d") or "") > corp[bz]["d"]):
                    corp[bz] = {"a": v.get("a") or "", "t": v.get("t") or "", "d": v.get("d") or ""}
            rows.append({
                "id": k, "s": status, "nm": title, "dm": v.get("dm") or b.get("demand") or "",
                "rg": detect(b.get("site"), v.get("dm"), b.get("org"), title),
                "kind": b.get("kind") or "", "co": v["n"], "amt": money(v.get("amt")),
                "rate": v.get("rate") or "", "np": v.get("np") or "", "d": v.get("d") or "",
                "u": u, "b": cb,
            })
    rows.sort(key=lambda r: (r["d"], r["amt"]), reverse=True)
    try:
        fill_missing(rows, corp, now)
    except Exception as e:
        print("연락처 보충 실패(건너뜀):", str(e)[:200])
    os.makedirs("docs", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"updated": now.isoformat(timespec="minutes"), "n": len(rows), "items": rows,
                   "corp": {b: {"a": c["a"], "t": c["t"]} for b, c in corp.items()}}, f, ensure_ascii=False, separators=(",", ":"))
    print(f"공개용 {len(rows)}건 저장 ({OUT})")
    export_bids(bids, now)


if __name__ == "__main__":
    main()
