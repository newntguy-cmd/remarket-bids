# remarket-bids

나라장터 공사 입찰공고를 공공데이터포털 API로 매일 모아 지역별로 보여 주는 리마켓 영업용 페이지입니다.

- `collect.py`: API에서 공고를 가져와 `docs/data.json`에 누적 저장
- `.github/workflows/collect.yml`: 매일 09:30, 15:30(한국시간) 자동 실행
- `docs/index.html`: 지역별 보기 화면 (GitHub Pages)
- 인증키는 저장소 Secrets의 `DATA_GO_KR_KEY`에만 보관
