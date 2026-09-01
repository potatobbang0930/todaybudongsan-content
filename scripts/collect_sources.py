#!/usr/bin/env python3
"""Tier 1 공식 자료 수집 (docs/CONTENT_SOURCES.md ①소스 목록).

매일 22시(KST)에 실행해 그날 나온 자료를 모은다.
국토교통부는 본문이 웹페이지에 없고 hwpx 첨부에만 있어서, 첨부를 내려받아
zip 안의 XML(<hp:t> 태그)에서 텍스트를 뽑는다. 2026-08-12에 확인한 제약이다.

출력: candidates.json — [{source, title, date, url, body}, ...]
"""
from __future__ import annotations

import argparse
import html
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from http.cookiejar import CookieJar

KST = timezone(timedelta(hours=9))

# 국토부는 브라우저 UA와 쿠키가 없으면 리다이렉트 루프에 빠진다(2026-08-12 확인).
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# needs_date_lookup=True 인 피드는 RSS에 <pubDate>가 아예 없어서, 상세 페이지에서
# 날짜를 읽어와야 한다. 이걸 안 하면 날짜 필터가 그 기관 자료를 통째로 조용히
# 버린다(2026-08-12에 금융위에서 실제로 발생).
#
# 2026-08-13 추가: 국토교통부 공지사항(N01_B).
# 2026-08-12에는 "우리 주제와 무관"하다고 보고 뺐던 피드다. 그때 선정 기준이
# "확정된 규칙 변경"이어서 *공고*는 규칙 변경이 아니라 전부 걸렸기 때문이다.
# 기준을 "돈·자격·일정·판단"으로 넓히면서 **토지거래허가구역 지정 공고**가
# 자격(B축)의 정확한 재료가 됐다 — 규제지역 지정은 청약·대출 자격을 바로 바꾼다.
# 신호 비율은 낮다(10건 중 직접 관련 2건). 그래서 넣되 선정 단계에서 거른다.
FEEDS = [
    ("국토교통부", "https://www.molit.go.kr/dev/board/board_rss.jsp?rss_id=NEWS", False),
    ("국토교통부(공고)", "https://www.molit.go.kr/dev/board/board_rss.jsp?rss_id=N01_B", False),
    ("재정경제부", "https://mofe.go.kr/com/detailRssTagService.do?bbsId=MOSFBBS_000000000028", False),
    ("금융위원회", "https://www.fsc.go.kr/about/fsc_bbs_rss/?fid=0111", True),
    ("금융위원회(보도설명)", "https://www.fsc.go.kr/about/fsc_bbs_rss/?fid=0112", True),
    ("한국은행", "https://www.bok.or.kr/portal/bbs/B0000552/news.rss?menuNo=200690", False),
    ("한국은행(통화정책)", "https://www.bok.or.kr/portal/bbs/P0000559/news.rss?menuNo=200690", False),
]

MONTHS = {m: i for i, m in enumerate(
    "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), start=1)}


def build_opener() -> urllib.request.OpenerDirector:
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar()))
    opener.addheaders = [("User-Agent", UA), ("Accept-Language", "ko-KR,ko;q=0.9")]
    return opener


# 재시도가 필요한 이유는 fsc.go.kr(금융위) 때문이다. 국내에서는 0.2초에 응답이 오는데
# GitHub 러너에서는 SSL 핸드셰이크부터 타임아웃한다 (2026-09-01 실측).
# 한 번 튕겼다고 그 기관을 통째로 버리면 대출·DSR 자료가 조용히 사라진다.
def get(opener, url: str, timeout: int = 30, tries: int = 3) -> bytes:
    last: Exception | None = None
    for attempt in range(1, tries + 1):
        try:
            with opener.open(url, timeout=timeout) as r:
                return r.read()
        except (urllib.error.URLError, OSError) as e:
            last = e
            if attempt < tries:
                time.sleep(2 ** attempt)  # 2초 → 4초
    print(f"  ⚠️  요청 실패 {url[:70]} — {last} ({tries}회 시도)", file=sys.stderr)
    return b""


def unwrap(text: str) -> str:
    text = re.sub(r"<!\[CDATA\[|\]\]>", "", text)
    return html.unescape(re.sub(r"<[^>]+>", " ", text)).strip()


def parse_pubdate(raw: str) -> str | None:
    """RSS의 여러 날짜 형식을 YYYY-MM-DD(KST)로 정규화한다."""
    raw = raw.strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", raw)  # 재정경제부: 2026-08-12 09:41:11.0
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # RFC 822: Wed, 12 Aug 2026 13:26:06 +0900
    m = re.search(r"(\d{1,2})\s+([A-Z][a-z]{2})\s+(\d{4})", raw)
    if m and m.group(2) in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"
    return None


def extract_hwpx_text(data: bytes) -> str:
    """hwpx는 zip 안의 XML이다. 본문은 <hp:t> 태그에 들어 있다."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return ""
    out: list[str] = []
    for name in sorted(n for n in z.namelist()
                       if "section" in n.lower() and n.endswith(".xml")):
        xml = z.read(name).decode("utf-8", "replace")
        for chunk in re.findall(r"<hp:t>(.*?)</hp:t>", xml, re.S):
            t = html.unescape(re.sub(r"<[^>]+>", "", chunk)).strip()
            if t:
                out.append(t)
    return "\n".join(out)


def fetch_page_date(opener, link: str) -> str | None:
    """RSS에 pubDate가 없는 피드용 — 상세 페이지 본문에서 YYYY-MM-DD를 찾는다."""
    page = get(opener, link, timeout=20).decode("utf-8", "replace")
    if not page:
        return None
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))
    m = re.search(r"(20\d\d)-(\d{2})-(\d{2})", text)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def fetch_molit_body(opener, link: str) -> str:
    """국토부 상세 페이지 → hwpx 첨부 → 본문 텍스트."""
    page = get(opener, link).decode("utf-8", "replace")
    if not page:
        return ""
    m = re.search(r"FilePath=([^&\"']*\.hwpx)", page)
    if not m:
        return ""
    dl = ("https://www.molit.go.kr/portal/common/download/DownloadMltm2.jsp"
          f"?FilePath={m.group(1)}&FileName=doc.hwpx")
    return extract_hwpx_text(get(opener, dl, timeout=60))


# --- 청약홈 분양정보 (한국부동산원, 공공데이터포털 OpenAPI) ---------------------
#
# 2026-08-13 추가. Tier 1 RSS 6개는 전부 중앙부처 보도자료라 **"오늘 뭘 해야 하는지"를
# 주는 소스가 하나도 없었다**(선정 기준 C=일정 축이 통째로 비어 있었다).
# 청약 공고는 접수 시작·마감일이 박혀 있어 그 자체가 행동 시한이다.
#
# 사용자 요청으로 **서울 + APT**만 가져온다. 전국을 다 넣으면 선정 1단계 제외 기준
# 4번(특정 지역)에 걸릴 후보만 잔뜩 늘어난다.
APPLYHOME_URL = ("https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1"
                 "/getAPTLttotPblancDetail")

# 규제 관련 플래그 — 자격(B축) 판단에 직접 쓰인다
REGULATION_FLAGS = [
    ("SPECLT_RDN_EARTH_AT", "투기과열지구"),
    ("MDAT_TRGET_AREA_SECD", "조정대상지역"),
    ("PARCPRC_ULS_AT", "분양가상한제"),
    ("IMPRMN_BSNS_AT", "정비사업"),
]


def fetch_applyhome(cutoff: str, target: str) -> tuple[list[dict], str | None]:
    """서울 APT 분양공고 중 모집공고일이 수집 기간에 든 것.

    반환: (후보 목록, 건너뛴 사유 또는 None)

    키는 환경변수로만 읽는다. 이 저장소는 공개라 키를 파일에 두면 안 된다.
    """
    key = os.environ.get("ODCLOUD_API_KEY", "").strip()
    if not key:
        return [], "ODCLOUD_API_KEY 환경변수가 없습니다"

    params = {
        "page": 1,
        "perPage": 100,
        "cond[SUBSCRPT_AREA_CODE_NM::EQ]": "서울",
        "cond[RCRIT_PBLANC_DE::GTE]": cutoff,
        "cond[RCRIT_PBLANC_DE::LTE]": target,
        "serviceKey": key,
    }
    url = f"{APPLYHOME_URL}?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.load(r)
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        return [], f"요청 실패 — {e}"

    # ⚠️ totalCount는 **필터를 적용하기 전** 전체 건수다(2026-08-13 확인: 서울 8건인데
    # 2844로 응답). 이걸 건수로 쓰면 안 된다. data 길이를 쓴다.
    rows = payload.get("data") or []

    out: list[dict] = []
    for r in rows:
        name = (r.get("HOUSE_NM") or "").strip()
        if not name:
            continue
        flags = [label for field, label in REGULATION_FLAGS if r.get(field) == "Y"]
        lines = [
            f"단지명: {name}",
            f"공급위치: {r.get('HSSPLY_ADRES') or '-'}",
            f"공급규모: {r.get('TOT_SUPLY_HSHLDCO') or '-'}세대",
            f"모집공고일: {r.get('RCRIT_PBLANC_DE') or '-'}",
            f"특별공급 접수: {r.get('SPSPLY_RCEPT_BGNDE') or '-'} ~ {r.get('SPSPLY_RCEPT_ENDDE') or '-'}",
            f"1순위 접수(해당지역): {r.get('GNRL_RNK1_CRSPAREA_RCPTDE') or '-'}",
            f"1순위 접수(기타지역): {r.get('GNRL_RNK1_ETC_AREA_RCPTDE') or '-'}",
            f"전체 접수기간: {r.get('RCEPT_BGNDE') or '-'} ~ {r.get('RCEPT_ENDDE') or '-'}",
            f"당첨자 발표: {r.get('PRZWNER_PRESNATN_DE') or '-'}",
            f"계약: {r.get('CNTRCT_CNCLS_BGNDE') or '-'} ~ {r.get('CNTRCT_CNCLS_ENDDE') or '-'}",
            f"입주예정: {r.get('MVN_PREARNGE_YM') or '-'}",
            f"시공사: {r.get('CNSTRCT_ENTRPS_NM') or '-'}",
            f"사업주체: {r.get('BSNS_MBY_NM') or '-'}",
            f"규제: {', '.join(flags) if flags else '해당 없음'}",
        ]
        out.append({
            "source": "청약홈(서울 APT)",
            "title": f"{name} 입주자모집공고",
            "date": r.get("RCRIT_PBLANC_DE") or target,
            "url": r.get("PBLANC_URL") or "",
            "body": "\n".join(lines),
        })
    return out, None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="수집 대상 날짜 YYYY-MM-DD (기본: 오늘 KST)")
    ap.add_argument("--days", type=int, default=1,
                    help="대상 날짜로부터 며칠 전까지 포함할지 (기본 1 = 당일만)")
    ap.add_argument("--out", default="candidates.json")
    args = ap.parse_args()

    target = args.date or datetime.now(KST).strftime("%Y-%m-%d")
    cutoff = (datetime.strptime(target, "%Y-%m-%d")
              - timedelta(days=args.days - 1)).strftime("%Y-%m-%d")
    print(f"수집 대상: {cutoff} ~ {target} (KST)")

    opener = build_opener()
    candidates: list[dict] = []

    failed: list[str] = []
    skipped: list[str] = []

    for name, url, needs_lookup in FEEDS:
        # 🔴 응답이 200이어도 본문이 중간에 잘려 오는 일이 있다.
        #    2026-09-01 국토부에서 실측: 같은 URL에 6,649바이트(정상)와
        #    3,794바이트(<item> 0개로 잘린 것)가 번갈아 왔다. 예외가 안 나므로
        #    잘린 응답은 "그날 자료가 없었다"와 **구분되지 않는다** — 가장 위험한 실패다.
        #
        #    피드는 날짜와 무관하게 10~100건을 늘 담고 있다. 그래서 **0건은 언제나 실패다.**
        #    날짜 필터는 이 아래에서 따로 돈다.
        items: list[str] = []
        for attempt in range(1, 4):
            raw = get(opener, url)
            xml = raw.decode("utf-8", "replace") if raw else ""
            items = re.findall(r"<item>(.*?)</item>", xml, re.S)
            if items:
                break
            if attempt < 3:
                time.sleep(2 ** attempt)
        if not items:
            # 조용히 넘어가면 "그날 자료가 없었다"와 구분이 안 된다.
            # 한 기관이 통째로 빠진 채 정상처럼 보이는 게 가장 위험하다.
            print(f"  {name}: ❌ 수집 실패 — 이 기관 자료가 통째로 빠집니다")
            failed.append(name)
            continue
        kept = skipped_no_date = 0
        for item in items:
            t = re.search(r"<title>(.*?)</title>", item, re.S)
            title = unwrap(t.group(1)) if t else ""
            # 각 피드의 첫 <item>이 채널 제목인 경우가 있어 걸러낸다
            if not title or title == name:
                continue
            # 금융위는 <link>를 CDATA로 감싼다 — 벗기지 않으면 URL이 깨진다.
            link = re.search(r"<link>(.*?)</link>", item, re.S)
            link = html.unescape(
                re.sub(r"<!\[CDATA\[|\]\]>", "", link.group(1)).strip()) if link else ""

            d = re.search(r"<pubDate>(.*?)</pubDate>", item, re.S)
            date = parse_pubdate(d.group(1)) if d else None
            if date is None and needs_lookup and link:
                date = fetch_page_date(opener, link)
            if date is None:
                skipped_no_date += 1
                continue
            if not (cutoff <= date <= target):
                continue

            desc = re.search(r"<description>(.*?)</description>", item, re.S)
            body = unwrap(desc.group(1))[:4000] if desc else ""
            candidates.append({"source": name, "title": title,
                               "date": date, "url": link, "body": body})
            kept += 1
        note = f" (날짜 확인 실패 {skipped_no_date}건)" if skipped_no_date else ""
        print(f"  {name}: {kept}건 / 전체 {len(items)}건{note}")

    # 청약홈은 RSS가 아니라 JSON API라 위 루프와 경로가 다르다.
    applyhome, skip_reason = fetch_applyhome(cutoff, target)
    if skip_reason:
        # 조용히 넘어가지 않는다 — 접속 실패와 같은 이유다. 결과만 봐서는
        # "그날 공고가 없었다"와 구분되지 않는다.
        print(f"  청약홈(서울 APT): ⚠️  건너뜀 — {skip_reason}")
        skipped.append(f"청약홈(서울 APT): {skip_reason}")
    else:
        candidates.extend(applyhome)
        print(f"  청약홈(서울 APT): {len(applyhome)}건")

    # 국토부만 본문이 첨부에 있다. 다른 기관은 description으로 충분하다.
    for c in candidates:
        if c["source"] == "국토교통부" and c["url"]:
            c["body"] = fetch_molit_body(opener, c["url"])[:8000]
            print(f"  본문 확보: {c['title'][:40]} ({len(c['body'])}자)")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"target_date": target, "candidates": candidates,
                   "failed_sources": failed, "skipped_sources": skipped},
                  f, ensure_ascii=False, indent=2)
    print(f"\n총 {len(candidates)}건 → {args.out}")

    if failed:
        print(f"\n❌ 접속 실패 {len(failed)}곳: {', '.join(failed)}")
        print("   이 결과를 그대로 쓰면 안 됩니다. 빠진 기관에 더 중요한 자료가")
        print("   있었을 수 있고, 결과만 보면 알 방법이 없습니다.")
        print("   (GitHub 러너에서는 .go.kr 사이트 접속이 막힙니다 — 국내에서 실행하세요.)")
        return 1

    if not candidates:
        print("⚠️  후보가 없습니다. 주말·공휴일이면 정상입니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
