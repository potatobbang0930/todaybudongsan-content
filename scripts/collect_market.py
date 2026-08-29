#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""수도권 시군구별 주간 시세 요약을 만든다 → content/market/{코드}.json

국토교통부 실거래가 API(매매·전월세)를 지역·월 단위로 받아 **주간 집계로 줄여서만** 저장한다.
원본 거래는 커밋하지 않는다 (docs/PRD.md 8-3 저장 원칙 A).

키는 환경변수 RTMS_API_KEY 로만 읽는다. 이 저장소는 공개라 파일에 두면 안 된다.

    set -a; . ~/.todaybudongsan.env; set +a
    python3 scripts/collect_market.py                 # 전체 80곳, 최근 6개월
    python3 scripts/collect_market.py --only 11305    # 한 곳만
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from regions import REGIONS, BY_CODE, api_codes, label  # noqa: E402

KST = dt.timezone(dt.timedelta(hours=9))
PYEONG = 3.305785  # 1평 = 3.3058㎡

TRADE_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
RENT_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptRent/getRTMSDataSvcAptRent"

# 전용면적 구간. 같은 "84㎡"라도 실제 값은 83~85 로 흩어진다.
AREA_BANDS = {"m84": (79.0, 86.5), "m59": (54.0, 62.0)}

# 최근 3개월 매매가 이 수보다 적으면 숫자를 감춘다 (design.md 5절).
SPARSE_MIN_TRADES = 20

# 🔴 API 가 429 를 낸다 (2026-08-29 실측). 병렬로 부르면 절반이 실패한다. 직렬 + 간격.
REQUEST_INTERVAL = 0.35


def today_kst() -> dt.date:
    return dt.datetime.now(KST).date()


def fetch(url: str, code: str, ym: str, retries: int = 6) -> list[dict]:
    """한 지역·한 달치 거래. 페이지를 끝까지 넘긴다."""
    key = os.environ["RTMS_API_KEY"]
    out: list[dict] = []
    page = 1
    while True:
        q = urllib.parse.urlencode(
            {"serviceKey": key, "LAWD_CD": code, "DEAL_YMD": ym,
             "pageNo": page, "numOfRows": 1000}
        )
        root = None
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(f"{url}?{q}", timeout=40) as r:
                    root = ET.fromstring(r.read())
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    time.sleep(1.2 * (attempt + 1))
                    continue
                raise
            except (urllib.error.URLError, OSError, ET.ParseError):
                time.sleep(1.0 * (attempt + 1))
        if root is None:
            raise RuntimeError(f"{code} {ym} 요청 실패 (429 반복)")

        rc = root.findtext(".//resultCode")
        if rc not in ("000", "00", None):
            raise RuntimeError(f"{code} {ym} resultCode={rc} {root.findtext('.//resultMsg')}")

        items = root.findall(".//item")
        out.extend({c.tag: (c.text or "").strip() for c in it} for it in items)
        total = int(root.findtext(".//totalCount") or 0)
        if len(out) >= total or not items:
            return out
        page += 1
        time.sleep(REQUEST_INTERVAL)


def to_int(text: str | None) -> int | None:
    if not text:
        return None
    t = text.replace(",", "").strip()
    return int(t) if t.lstrip("-").isdigit() else None


def to_float(text: str | None) -> float | None:
    try:
        return float((text or "").strip())
    except ValueError:
        return None


def deal_date(row: dict) -> dt.date | None:
    y, m, d = to_int(row.get("dealYear")), to_int(row.get("dealMonth")), to_int(row.get("dealDay"))
    if not (y and m and d):
        return None
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def week_key(d: dt.date) -> str:
    """'2026-08-4' — 그 달의 몇째 주인지. 화면에는 '8월 4주'로 쓴다."""
    return f"{d.year}-{d.month:02d}-{(d.day - 1) // 7 + 1}"


def band(area: float | None) -> str | None:
    if area is None:
        return None
    for name, (lo, hi) in AREA_BANDS.items():
        if lo <= area <= hi:
            return name
    return None


def median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def normalize_trades(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        amount = to_int(r.get("dealAmount"))          # 만원
        area = to_float(r.get("excluUseAr"))          # ㎡
        d = deal_date(r)
        if not (amount and area and d) or area <= 0:
            continue
        if (r.get("cdealType") or "").strip() == "O":  # 해제된 거래
            continue
        out.append({
            "date": d, "amount": amount, "area": area,
            "apt": r.get("aptNm") or "", "seq": r.get("aptSeq") or "",
            "pyeong": amount / (area / PYEONG),        # 만원/평
            "band": band(area),
        })
    return out


def normalize_rents(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        deposit = to_int(r.get("deposit"))
        rent = to_int(r.get("monthlyRent"))
        area = to_float(r.get("excluUseAr"))
        d = deal_date(r)
        if deposit is None or rent is None or not (area and d):
            continue
        out.append({
            "date": d, "deposit": deposit, "rent": rent, "area": area,
            "apt": r.get("aptNm") or "", "seq": r.get("aptSeq") or "",
            "band": band(area), "jeonse": rent == 0,
        })
    return out


# 🔴 주별 표본이 작아서 그대로 쓰면 값이 튄다 (2026-08-29 실측).
#    강북구 84㎡ 전세가율을 주별로 내니 58% ~ 108% 사이를 오갔다. 그 주에 84㎡ 매매가
#    한두 건뿐이라 중간값이 아무 값이나 됐을 뿐, 시장이 그렇게 움직인 게 아니다.
#    → 평당가는 그 주 거래가 MIN_WEEK_TRADES 미만이면 비운다.
#    → 전세가율은 그 주를 포함한 최근 RATIO_WINDOW 주를 합쳐 계산한다.
#    → 평당가도 같은 이유로 4주를 합쳐 본다. 강북구는 신축과 구축의 평당가 차이가 커서
#      "그 주에 어느 단지가 팔렸나"로 중앙값이 ±18% 움직였다. 시장이 아니라 표본이 움직인 것이다.
WINDOW = 4               # 평당가·전세가율 모두 4주를 합쳐 본다
MIN_WEEK_TRADES = 5      # 4주를 합쳐도 거래가 이보다 적으면 평당가를 비운다
MIN_RATIO_SAMPLES = 3    # 4주를 합쳐도 84㎡ 표본이 이보다 적으면 중간값을 비운다

# 🔴 전세가율을 "그 지역 84㎡ 전세 중간값 ÷ 매매 중간값"으로 내면 틀린다 (2026-08-29 실측).
#    강서구 30% · 서초구 37% · 포천 109% · 안성 107% 처럼 말이 안 되는 값이 나왔다.
#    매매에 잡힌 단지와 전세에 잡힌 단지가 서로 달라서다 — 강서구는 마곡 신축이 매매를 끌어올리고
#    전세는 구축 위주라 비율이 30%로 눌렸다.
#    → 같은 단지·같은 평형에서 매매와 전세가 둘 다 있는 곳만 골라 단지별 비율을 내고, 그 중앙값을 쓴다.
RATIO_DAYS = 92          # 전세가율은 단지 매칭이 필요해 3개월 창을 쓴다
MIN_RATIO_COMPLEXES = 3  # 짝이 맞는 단지가 이보다 적으면 비운다


def jeonse_ratio(trades: list[dict], rents: list[dict],
                 until: dt.date | None = None) -> int | None:
    """같은 단지·같은 평형끼리 짝지어 낸 전세가율(%)."""
    if until is None:
        dates = [r["date"] for r in trades + rents]
        if not dates:
            return None
        until = max(dates)
    lo = until - dt.timedelta(days=RATIO_DAYS)

    def win(rows):
        return [r for r in rows if lo <= r["date"] <= until]

    sale: dict[tuple, list[int]] = {}
    for t in win(trades):
        if t["band"]:
            sale.setdefault((t["seq"], t["band"]), []).append(t["amount"])
    lease: dict[tuple, list[int]] = {}
    for r in win(rents):
        if r["jeonse"] and r["band"] and r.get("seq"):
            lease.setdefault((r["seq"], r["band"]), []).append(r["deposit"])

    ratios = [median(lease[k]) / median(sale[k]) for k in sale.keys() & lease.keys()]
    if len(ratios) < MIN_RATIO_COMPLEXES:
        return None
    return round(median(ratios) * 100)


def weekly(trades: list[dict], rents: list[dict], weeks: int) -> list[dict]:
    """주별 요약. 평당가·전세가율·거래건수만 남긴다."""
    buckets: dict[str, dict] = {}

    def bucket(wk):
        return buckets.setdefault(wk, {"tp": [], "t84": [], "j84": [], "tc": 0, "rc": 0})

    for t in trades:
        b = bucket(week_key(t["date"]))
        b["tp"].append(t["pyeong"])
        b["tc"] += 1
        if t["band"] == "m84":
            b["t84"].append(t["amount"])
    for r in rents:
        b = bucket(week_key(r["date"]))
        b["rc"] += 1
        if r["jeonse"] and r["band"] == "m84":
            b["j84"].append(r["deposit"])

    order = sorted(buckets)
    # 각 주의 전세가율은 "그 주까지의 최근 3개월"을 단지 매칭해서 낸다
    week_end: dict[str, dt.date] = {}
    for r in trades + rents:
        wk = week_key(r["date"])
        week_end[wk] = max(week_end.get(wk, r["date"]), r["date"])
    ratio_by_week = {wk: jeonse_ratio(trades, rents, week_end[wk]) for wk in order}
    out = []
    for idx, wk in enumerate(order):
        b = buckets[wk]
        window = [buckets[w] for w in order[max(0, idx - WINDOW + 1): idx + 1]]
        tp = [v for w in window for v in w["tp"]]
        ratio = ratio_by_week.get(wk)
        out.append({
            "week": wk,
            # 🔴 평당가도 전세가율도 그 주 하나가 아니라 최근 4주를 합친 값이다.
            #    화면에 "최근 4주 기준"이라고 적어야 한다.
            "pyeongPrice": round(median(tp)) if len(tp) >= MIN_WEEK_TRADES else None,
            "jeonseRatio": ratio,
            "tradeCount": b["tc"],
            "rentCount": b["rc"],
        })
    return out[-weeks:]


def recent_weeks(rows: list[dict], n: int) -> tuple[list[dict], list[str]]:
    """가장 최근 n개 주에 든 거래만. 화면의 대표 숫자는 다 이 창으로 낸다."""
    if not rows:
        return [], []
    keys = sorted({week_key(r["date"]) for r in rows})[-n:]
    return [r for r in rows if week_key(r["date"]) in keys], keys


def latest_detail(trades: list[dict], months3: list[dict]) -> dict:
    """화면 상단 숫자 + 신고가 5곳 + 많이 팔린 곳 5곳.

    🔴 전부 최근 4주 기준이다. 한 주만 보면 84㎡ 거래가 아예 없는 지역이 흔하다
    (2026-08-29 실측: 80곳 중 과천·마포·중구 등에서 최근 주 84㎡ 중간값이 비었다).
    """
    window, keys = recent_weeks(trades, WINDOW)
    if not window:
        return {"week": None, "weeks": WINDOW, "pyeongPrice": None, "m84": None, "m59": None,
                "count": 0, "highs": [], "actives": []}
    latest = keys[-1]

    # 신고가: 같은 단지·같은 평형에서, 창 이전 3개월 안의 최고가를 넘긴 거래
    prev_high: dict[tuple, int] = {}
    for t in sorted(months3, key=lambda x: x["date"]):
        if week_key(t["date"]) in keys:
            continue
        k = (t["seq"], t["band"])
        prev_high[k] = max(prev_high.get(k, 0), t["amount"])
    highs, seen = [], set()
    for t in sorted(window, key=lambda x: -x["amount"]):
        k = (t["seq"], t["band"])
        prev = prev_high.get(k)
        if prev and t["amount"] > prev and k not in seen:
            seen.add(k)
            highs.append({"apt": t["apt"], "area": round(t["area"], 1),
                          "amount": t["amount"], "prevHigh": prev})
        if len(highs) == 5:
            break

    counts: dict[str, list[int]] = {}
    for t in window:
        counts.setdefault(t["apt"], []).append(t["amount"])
    actives = sorted(counts.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:5]

    return {
        "week": latest,
        "weeks": WINDOW,
        "pyeongPrice": round(median([t["pyeong"] for t in window])),
        "m84": round(median([t["amount"] for t in window if t["band"] == "m84"]) or 0) or None,
        "m59": round(median([t["amount"] for t in window if t["band"] == "m59"]) or 0) or None,
        "count": len(window),
        "highs": highs,
        "actives": [{"apt": a, "count": len(v), "median": round(median(v))} for a, v in actives],
    }


def rent_detail(rents: list[dict], trades: list[dict]) -> dict:
    """전세·월세 대표 숫자. 매매와 같은 최근 4주 창을 쓴다."""
    window, keys = recent_weeks(rents, WINDOW)
    j84 = [r["deposit"] for r in window if r["jeonse"] and r["band"] == "m84"]
    j59 = [r["deposit"] for r in window if r["jeonse"] and r["band"] == "m59"]
    monthly = [r for r in window if not r["jeonse"]]
    m_j84 = round(median(j84)) if len(j84) >= MIN_RATIO_SAMPLES else None
    return {
        "week": keys[-1] if keys else None,
        "weeks": WINDOW,
        "jeonseM84": m_j84,
        "jeonseM59": round(median(j59)) if len(j59) >= MIN_RATIO_SAMPLES else None,
        "monthlyDeposit": round(median([r["deposit"] for r in monthly])) if monthly else None,
        "monthlyRent": round(median([r["rent"] for r in monthly])) if monthly else None,
        # 지역 중간값끼리 나누지 않는다 — 위 jeonse_ratio 주석 참고
        "jeonseRatio": jeonse_ratio(trades, rents),
        "ratioDays": RATIO_DAYS,
        "count": len(window),
    }


def months_back(today: dt.date, n: int) -> list[str]:
    out, y, m = [], today.year, today.month
    for _ in range(n):
        out.append(f"{y}{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def collect_region(code: str, yms: list[str], verbose: bool) -> tuple[list[dict], list[dict]]:
    trades_raw, rents_raw = [], []
    for api_code in api_codes(code):
        for ym in yms:
            trades_raw += fetch(TRADE_URL, api_code, ym)
            time.sleep(REQUEST_INTERVAL)
            rents_raw += fetch(RENT_URL, api_code, ym)
            time.sleep(REQUEST_INTERVAL)
    if verbose:
        print(f"    원본 매매 {len(trades_raw)} · 전월세 {len(rents_raw)}")
    return normalize_trades(trades_raw), normalize_rents(rents_raw)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="content/market")
    ap.add_argument("--months", type=int, default=6, help="몇 달치를 받을지 (기본 6)")
    ap.add_argument("--weeks", type=int, default=26, help="주간 흐름을 몇 주 남길지")
    ap.add_argument("--only", nargs="*", help="특정 지역 코드만")
    ap.add_argument("--date", help="기준 날짜 YYYY-MM-DD (기본 오늘 KST)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if not os.environ.get("RTMS_API_KEY", "").strip():
        print("❌ RTMS_API_KEY 환경변수가 없습니다", file=sys.stderr)
        return 1

    today = dt.date.fromisoformat(args.date) if args.date else today_kst()
    yms = months_back(today, args.months)
    targets = [r for r in REGIONS if not args.only or r[0] in args.only]
    if args.only and len(targets) != len(args.only):
        print(f"❌ 모르는 지역 코드: {set(args.only) - {r[0] for r in targets}}", file=sys.stderr)
        return 1

    os.makedirs(args.out_dir, exist_ok=True)
    index, failed = [], []
    for i, (code, sido, name, group, _) in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] {sido} {name} ({code})")
        try:
            trades, rents = collect_region(code, yms, args.verbose)
        except Exception as e:  # 한 지역이 실패해도 나머지는 계속한다
            print(f"    ❌ 실패 — {e}", file=sys.stderr)
            failed.append(code)
            continue

        cut3 = today - dt.timedelta(days=92)
        trades3 = [t for t in trades if t["date"] >= cut3]
        sparse = len(trades3) < SPARSE_MIN_TRADES

        detail = latest_detail(trades, trades3)
        doc = {
            "code": code,
            "region": f"{sido} {name}",
            "sido": sido,
            "group": group,
            "updatedAt": dt.datetime.now(KST).replace(microsecond=0).isoformat(),
            # 🔴 표본이 적으면 앱이 숫자를 감추고 E2_MarketEmpty 를 그린다
            "sparse": sparse,
            "trades3m": len(trades3),
            "trade": detail,
            "rent": rent_detail(rents, trades),
            # 🔴 trade·rent·weeks 의 모든 중간값이 "최근 4주"를 합친 값이다. 건수만 그 창의 합계다.
            "window": WINDOW,
            "weeks": weekly(trades, rents, args.weeks),
        }
        with open(os.path.join(args.out_dir, f"{code}.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
            f.write("\n")

        index.append({"code": code, "region": doc["region"], "sido": sido,
                      "name": name, "group": group, "sparse": sparse})
        flag = " ⚠️ 표본 부족" if sparse else ""
        print(f"    {detail['week']} · 평당 {detail['pyeongPrice']}만 · "
              f"매매 {detail['count']}건 · 3개월 {len(trades3)}건{flag}")

    if not args.only:
        with open(os.path.join(args.out_dir, "index.json"), "w", encoding="utf-8") as f:
            json.dump({"updatedAt": dt.datetime.now(KST).replace(microsecond=0).isoformat(),
                       "count": len(index), "regions": index}, f, ensure_ascii=False, indent=2)
            f.write("\n")

    print(f"\n완료 — {len(index)}곳 저장, 실패 {len(failed)}곳")
    if failed:
        print("실패:", ", ".join(f"{c}({label(c)})" for c in failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
