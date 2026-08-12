#!/usr/bin/env python3
"""발행된 latest.json을 날짜별 보관본과 인덱스에 반영한다.

사람이 손대는 파일을 latest.json 하나로 유지하기 위해, 나머지는 여기서 만든다.
  - content/<date>.json : 주말 "주간 요약"을 쓸 때 그 주 콘텐츠를 읽는 용도
  - content/archive.json: 날짜·제목 인덱스 (최신순)

같은 날짜를 다시 발행하면(사실 정정 등) 보관본을 덮어쓰고 인덱스 제목을 갱신한다.
"""
import json
import os
import sys

CONTENT_DIR = "content"
LATEST = os.path.join(CONTENT_DIR, "latest.json")
ARCHIVE = os.path.join(CONTENT_DIR, "archive.json")


def write_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main() -> int:
    with open(LATEST, encoding="utf-8") as f:
        latest = json.load(f)

    date = latest.get("date")
    title = latest.get("title")
    if not date or not title:
        print("❌ latest.json에 date 또는 title이 없습니다")
        return 1

    # 1) 날짜별 보관본
    dated = os.path.join(CONTENT_DIR, f"{date}.json")
    write_json(dated, latest)
    print(f"보관본 기록: {dated}")

    # 2) 인덱스 — 같은 날짜가 있으면 제목만 갱신, 없으면 추가
    entries = []
    if os.path.exists(ARCHIVE):
        try:
            with open(ARCHIVE, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, list):
                entries = [e for e in loaded if isinstance(e, dict) and e.get("date")]
        except json.JSONDecodeError:
            print("⚠️  archive.json을 읽지 못해 새로 만듭니다")

    entries = [e for e in entries if e.get("date") != date]
    entries.append({"date": date, "title": title})
    entries.sort(key=lambda e: e["date"], reverse=True)  # 최신순
    write_json(ARCHIVE, entries)
    print(f"인덱스 갱신: {ARCHIVE} ({len(entries)}건)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
