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
import re
import sys
import urllib.error
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
FEEDS = [
    ("국토교통부", "https://www.molit.go.kr/dev/board/board_rss.jsp?rss_id=NEWS", False),
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


def get(opener, url: str, timeout: int = 30) -> bytes:
    try:
        with opener.open(url, timeout=timeout) as r:
            return r.read()
    except (urllib.error.URLError, OSError) as e:
        print(f"  ⚠️  요청 실패 {url[:70]} — {e}", file=sys.stderr)
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

    for name, url, needs_lookup in FEEDS:
        raw = get(opener, url)
        if not raw:
            continue
        xml = raw.decode("utf-8", "replace")
        items = re.findall(r"<item>(.*?)</item>", xml, re.S)
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

    # 국토부만 본문이 첨부에 있다. 다른 기관은 description으로 충분하다.
    for c in candidates:
        if c["source"] == "국토교통부" and c["url"]:
            c["body"] = fetch_molit_body(opener, c["url"])[:8000]
            print(f"  본문 확보: {c['title'][:40]} ({len(c['body'])}자)")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"target_date": target, "candidates": candidates},
                  f, ensure_ascii=False, indent=2)
    print(f"\n총 {len(candidates)}건 → {args.out}")
    if not candidates:
        print("⚠️  후보가 없습니다. 주말·공휴일이면 정상입니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
