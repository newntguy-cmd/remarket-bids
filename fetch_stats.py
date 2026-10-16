"""GoatCounter 방문 통계를 가져와 잠가서 docs/stats.enc 로 저장합니다."""
import json, os, sys, urllib.request, urllib.error, datetime as dt
import rmcrypt

CODE = "remarket-bids"
tok = os.environ.get("GOATCOUNTER_TOKEN", "")
if not tok:
    sys.exit("GOATCOUNTER_TOKEN 이 없습니다")
end = dt.datetime.now(dt.timezone.utc)
start = end - dt.timedelta(days=30)
url = (f"https://{CODE}.goatcounter.com/api/v0/stats/total"
       f"?start={start:%Y-%m-%dT%H:%M:%SZ}&end={end:%Y-%m-%dT%H:%M:%SZ}")
req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
try:
    d = json.load(urllib.request.urlopen(req, timeout=60))
except urllib.error.HTTPError as e:
    sys.exit(f"통계 조회 실패: HTTP {e.code} {e.read()[:300]!r} (토큰 길이 {len(tok)})")
print("응답 키:", list(d.keys()), "일수:", len(d.get("stats", [])))
for s_ in d.get("stats", [])[-3:]:
    print("원본", s_.get("day"), s_.get("hourly"), "합계", s_.get("daily"))
print("시각", end.isoformat())
days = [{"day": s["day"], "hourly": s.get("hourly", [])} for s in d.get("stats", [])]
rmcrypt.save("stats", {"updated": end.isoformat(), "total": d.get("total"), "days": days})
print("저장 완료")
