#!/usr/bin/env python3
"""수도권에서 지금 넣을 수 있는 청약을 모아 content/applyhome.json 을 만든다.

`collect_sources.py` 의 청약홈 수집과 용도가 다르다.
  - collect_sources.py : **오늘 새로 뜬 공고**를 그날 콘텐츠 후보로 쓴다
  - 이 스크립트        : **아직 접수가 안 끝난 공고 전부**를 앱 화면에 띄운다

앱이 이 파일을 읽어 "지금 넣을 수 있는 청약"과 D-day 를 그린다. 정책 콘텐츠와 달리
사람이 매일 쓰지 않아도 값이 매일 바뀐다 — 마감이 하루씩 다가오기 때문이다.

키는 환경변수로만 읽는다. 이 저장소는 공개라 키를 파일에 두면 안 된다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

APPLYHOME_URL = (
    "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/getAPTLttotPblancDetail"
)

# 2026-08-28 확정: 수도권만 다룬다.
# 대구·부산 공고는 지금 수도권에서 집을 사려는 사람의 판단을 바꾸지 않는다
# (prompts/CONTENT_GENERATION_PROMPT.md 제외 기준 4).
CAPITAL_AREA = ("서울", "경기", "인천")

KST = dt.timezone(dt.timedelta(hours=9))


def today_kst() -> dt.date:
    return dt.datetime.now(KST).date()


def fetch_page(key: str, page: int, cutoff: str) -> list[dict]:
    """접수 마감일이 cutoff 이후인 공고 한 페이지."""
    params = {
        "page": page,
        "perPage": 100,
        "cond[RCEPT_ENDDE::GTE]": cutoff,
        "serviceKey": key,
    }
    url = f"{APPLYHOME_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.load(r)
    # ⚠️ totalCount 는 필터 적용 **전** 전체 건수다 (2026-08-13 확인). data 길이를 쓴다.
    return payload.get("data") or []


def parse_date(value: str | None) -> str | None:
    """API 는 'YYYY-MM-DD' 로 주지만 빈 값·'-' 가 섞인다."""
    if not value:
        return None
    v = str(value).strip()
    if len(v) != 10 or v.count("-") != 2:
        return None
    return v


def to_entry(row: dict, today: dt.date) -> dict | None:
    name = str(row.get("HOUSE_NM") or "").strip()
    area = str(row.get("SUBSCRPT_AREA_CODE_NM") or "").strip()
    begin = parse_date(row.get("RCEPT_BGNDE"))
    end = parse_date(row.get("RCEPT_ENDDE"))
    if not name or not end or area not in CAPITAL_AREA:
        return None

    end_date = dt.date.fromisoformat(end)
    if end_date < today:
        return None

    # 접수 시작 전인지, 접수 중인지. 앱이 "곧 시작"과 "지금 넣을 수 있음"을 나눠 그린다.
    begin_date = dt.date.fromisoformat(begin) if begin else None
    if begin_date and today < begin_date:
        state = "upcoming"
        dday = (begin_date - today).days
    else:
        state = "open"
        dday = (end_date - today).days

    # 세대수는 API 가 int 로 줄 때도 있고 문자열로 줄 때도 있다 (2026-08-28 실측).
    raw_households = row.get("TOT_SUPLY_HSHLDCO")
    if isinstance(raw_households, int):
        households = raw_households
    else:
        text = str(raw_households or "").strip().replace(",", "")
        households = int(text) if text.isdigit() else None

    return {
        "name": name,
        "area": area,
        "address": str(row.get("HSSPLY_ADRES") or "").strip() or None,
        "households": households,
        "receiptBegin": begin,
        "receiptEnd": end,
        # state=open 이면 마감까지, upcoming 이면 시작까지 남은 날이다.
        "state": state,
        "dday": dday,
        "announceDate": parse_date(row.get("RCRIT_PBLANC_DE")),
        "winnerDate": parse_date(row.get("PRZWNER_PRESNATN_DE")),
        # 청약 상세 화면이 날짜를 여섯 줄로 그린다. API 가 주는 걸 다 옮긴다 (2026-08-29 추가).
        # 전에는 접수·공고·발표 넷만 뽑아서 상세 화면을 채울 수 없었다.
        "specialBegin": parse_date(row.get("SPSPLY_RCEPT_BGNDE")),
        "specialEnd": parse_date(row.get("SPSPLY_RCEPT_ENDDE")),
        # 1·2순위는 해당지역 / 기타지역 / 기타경기로 나뉜다. 가장 이른 날을 대표로 쓰고
        # 셋 다 남겨 상세 화면이 골라 쓰게 한다.
        "rank1": {
            "local": parse_date(row.get("GNRL_RNK1_CRSPAREA_RCPTDE")),
            "other": parse_date(row.get("GNRL_RNK1_ETC_AREA_RCPTDE")),
            "gyeonggi": parse_date(row.get("GNRL_RNK1_ETC_GG_RCPTDE")),
        },
        "rank2": {
            "local": parse_date(row.get("GNRL_RNK2_CRSPAREA_RCPTDE")),
            "other": parse_date(row.get("GNRL_RNK2_ETC_AREA_RCPTDE")),
            "gyeonggi": parse_date(row.get("GNRL_RNK2_ETC_GG_RCPTDE")),
        },
        "contractBegin": parse_date(row.get("CNTRCT_CNCLS_BGNDE")),
        "contractEnd": parse_date(row.get("CNTRCT_CNCLS_ENDDE")),
        "houseType": str(row.get("HOUSE_DTL_SECD_NM") or "").strip() or None,
        "url": str(row.get("PBLANC_URL") or "").strip() or None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="content/applyhome.json")
    ap.add_argument("--date", help="기준 날짜 YYYY-MM-DD (기본: 오늘 KST)")
    args = ap.parse_args()

    key = os.environ.get("ODCLOUD_API_KEY", "").strip()
    if not key:
        print("❌ ODCLOUD_API_KEY 환경변수가 없습니다", file=sys.stderr)
        return 1

    today = dt.date.fromisoformat(args.date) if args.date else today_kst()
    cutoff = today.isoformat()

    rows: list[dict] = []
    for page in range(1, 6):  # 100건 × 5 = 500건이면 충분하다
        try:
            batch = fetch_page(key, page, cutoff)
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
            print(f"❌ 청약홈 요청 실패 (page {page}) — {e}", file=sys.stderr)
            return 1
        rows.extend(batch)
        if len(batch) < 100:
            break

    entries = [e for e in (to_entry(r, today) for r in rows) if e]
    # 접수 중인 것 먼저, 그 안에서 마감이 임박한 순.
    entries.sort(key=lambda e: (e["state"] != "open", e["dday"], e["name"]))

    out = {
        "date": cutoff,
        "updatedAt": dt.datetime.now(KST).replace(microsecond=0).isoformat(),
        "area": list(CAPITAL_AREA),
        "count": len(entries),
        "items": entries,
    }
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")

    opened = sum(1 for e in entries if e["state"] == "open")
    print(f"수도권 청약 {len(entries)}건 (접수 중 {opened} · 예정 {len(entries) - opened}) → {args.out}")
    for e in entries[:10]:
        tag = f"D-{e['dday']}" if e["dday"] > 0 else "오늘 마감"
        label = "접수 중" if e["state"] == "open" else "시작 전"
        print(f"  [{e['area']}] {e['name']} · {label} {tag} · {e['households'] or '-'}세대")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
