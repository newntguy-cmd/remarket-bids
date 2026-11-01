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
    os.makedirs("docs", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"updated": now.isoformat(timespec="minutes"), "n": len(rows), "items": rows,
                   "corp": {b: {"a": c["a"], "t": c["t"]} for b, c in corp.items()}}, f, ensure_ascii=False, separators=(",", ":"))
    print(f"공개용 {len(rows)}건 저장 ({OUT})")


if __name__ == "__main__":
    main()
