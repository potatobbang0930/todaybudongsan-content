#!/usr/bin/env python3
"""수집한 후보로 콘텐츠 초안을 만든다 (Claude API).

출력 JSON은 structured outputs(output_config.format)로 스키마를 API가 보장하므로
파싱 실패가 없다. 다만 "summary가 정확히 3개" 같은 배열 길이 제약은 JSON Schema로
표현할 수 없어서, 생성 후 scripts/validate_content.py로 다시 검사한다.

평일: Tier 1 후보 중 하나를 골라 "오늘의 이슈"를 쓴다.
주말: 지난 월~금 발행분(content/YYYY-MM-DD.json)을 묶어 "주간 요약"을 쓴다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic

KST = timezone(timedelta(hours=9))
MODEL = "claude-opus-5"

STATEMENT = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["fact", "interpretation", "outlook"]},
        "text": {"type": "string"},
    },
    "required": ["type", "text"],
    "additionalProperties": False,
}

IMPACT = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["fact", "interpretation", "outlook"]},
        "audience": {"type": "string", "description": "영향을 받는 대상. 나눌 수 없으면 빈 문자열."},
        "text": {"type": "string"},
    },
    "required": ["type", "audience", "text"],
    "additionalProperties": False,
}

# content-schema.md의 콘텐츠 오브젝트. date/publishedAt/updatedAt/version은
# 모델이 지어내지 않도록 스크립트가 채운다.
SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "질문형 후크 제목"},
        "summary": {
            "type": "array",
            "items": {"type": "string"},
            "description": "정확히 3개. 각 줄에 날짜·수치·시행일 중 하나 이상.",
        },
        "whyItMatters": {"type": "array", "items": STATEMENT},
        "impact": {"type": "array", "items": IMPACT},
        "timelineImpact": STATEMENT,
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "기관명 + 자료명 + (발행일)"},
                    "url": {"type": "string"},
                },
                "required": ["name", "url"],
                "additionalProperties": False,
            },
        },
        "selectionNote": {
            "type": "string",
            "description": "왜 이 자료를 골랐고 무엇을 탈락시켰는지. PR 본문용이며 콘텐츠에는 들어가지 않는다.",
        },
    },
    "required": ["title", "summary", "whyItMatters", "impact",
                 "timelineImpact", "sources", "selectionNote"],
    "additionalProperties": False,
}


def load_prompt(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    # 프롬프트 파일에서 "# 프롬프트 (여기서부터 그대로 사용)" ~ "# (프롬프트 끝)" 구간만 쓴다.
    start = text.find("# 프롬프트 (여기서부터 그대로 사용)")
    end = text.find("# (프롬프트 끝)")
    if start == -1 or end == -1:
        return text
    return text[start:end].strip()


def build_weekday_input(data: dict) -> str:
    lines = [f"날짜: {data['target_date']}", "", "후보 자료:"]
    for i, c in enumerate(data["candidates"], 1):
        lines.append(f"\n--- 후보 {i} ---")
        lines.append(f"기관: {c['source']}")
        lines.append(f"제목: {c['title']}")
        lines.append(f"발행일: {c['date']}")
        lines.append(f"URL: {c['url']}")
        body = (c.get("body") or "").strip()
        lines.append(f"본문:\n{body if body else '(본문 없음 — 제목만으로 판단하지 말 것)'}")
    return "\n".join(lines)


def build_weekend_input(target: str, content_dir: Path) -> str:
    d = datetime.strptime(target, "%Y-%m-%d")
    # 그 주의 월요일부터 금요일까지
    monday = d - timedelta(days=d.weekday())
    lines = [f"날짜: {target} (주말 — 주간 요약)", "", "이번 주 발행분:"]
    found = 0
    for i in range(5):
        day = (monday + timedelta(days=i)).strftime("%Y-%m-%d")
        f = content_dir / f"{day}.json"
        if not f.exists():
            continue
        item = json.loads(f.read_text(encoding="utf-8"))
        found += 1
        lines.append(f"\n--- {day} ---")
        lines.append(f"제목: {item['title']}")
        lines.append("요약:\n- " + "\n- ".join(item["summary"]))
        lines.append("영향:\n- " + "\n- ".join(
            f"{s.get('audience') or '전체'}: {s['text']}" for s in item["impact"]))
        lines.append("출처: " + ", ".join(s["name"] for s in item["sources"]))
    if found == 0:
        lines.append("\n(이번 주 발행분이 없습니다.)")
    lines.append(f"\n총 {found}건. 3건 미만이면 있는 것만 다루고 억지로 늘리지 않는다.")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default="candidates.json")
    ap.add_argument("--prompt", default="prompts/content_generation.md")
    ap.add_argument("--content-dir", default="content")
    ap.add_argument("--out", default="content/latest.json")
    ap.add_argument("--note-out", default="selection_note.md")
    ap.add_argument("--effort", default="high",
                    choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--dry-run", action="store_true",
                    help="API를 호출하지 않고 보낼 요청만 출력한다 (키 없이 검증용)")
    args = ap.parse_args()

    data = json.loads(Path(args.candidates).read_text(encoding="utf-8"))
    target = data["target_date"]
    weekday = datetime.strptime(target, "%Y-%m-%d").weekday()  # 0=월, 5=토, 6=일
    is_weekend = weekday >= 5

    # 파이프라인 요구사항이라 프롬프트(편집 방침)가 아니라 여기서 붙인다.
    TRAILER = (
        "\n\n---\n"
        "출력의 `selectionNote`에는 **왜 이 자료를 골랐고 무엇을 탈락시켰는지**를 쓴다. "
        "이건 사람이 검수할 때 읽는 설명이고 콘텐츠에는 들어가지 않는다. "
        "선정 기준 A~D 중 무엇이 결정적이었는지, 경합한 후보가 있었다면 왜 졌는지를 밝힌다.\n"
        "`date`·`publishedAt`·`updatedAt`·`version`은 스크립트가 채우므로 출력하지 않는다."
    )

    if is_weekend:
        user_input = build_weekend_input(target, Path(args.content_dir))
    else:
        if not data["candidates"]:
            print("❌ 후보가 없습니다. 평일인데 자료가 없다면 수집을 확인하세요.")
            return 2
        user_input = build_weekday_input(data)
    user_input += TRAILER

    system = load_prompt(Path(args.prompt))

    print(f"모델 {MODEL} · effort={args.effort} · "
          f"{'주말형' if is_weekend else '평일형'} · 후보 {len(data['candidates'])}건")

    if args.dry_run:
        print(f"\n[dry-run] system {len(system)}자 / user {len(user_input)}자")
        print(f"[dry-run] 스키마 필수 필드: {SCHEMA['required']}")
        print("\n--- system 앞부분 ---")
        print(system[:400])
        print("\n--- user 앞부분 ---")
        print(user_input[:600])
        return 0

    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY

    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=system,
        output_config={
            "effort": args.effort,
            "format": {"type": "json_schema", "schema": SCHEMA},
        },
        messages=[{"role": "user", "content": user_input}],
    )

    if response.stop_reason == "refusal":
        detail = getattr(response, "stop_details", None)
        print(f"❌ 모델이 요청을 거절했습니다 (category: "
              f"{getattr(detail, 'category', None)}).")
        return 3
    if response.stop_reason == "max_tokens":
        print("❌ max_tokens에 걸려 출력이 잘렸습니다. 값을 올리거나 effort를 낮추세요.")
        return 4

    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        print("❌ 텍스트 블록이 없습니다.")
        return 5
    draft = json.loads(text)  # 스키마가 보장되므로 파싱은 안전하다

    note = draft.pop("selectionNote", "")
    now = datetime.now(KST).replace(microsecond=0).isoformat()
    item = {
        "date": target,
        "publishedAt": now,
        "updatedAt": now,
        "version": 1,
        **draft,
    }
    # content-schema.md의 필드 순서를 지킨다
    order = ["date", "publishedAt", "updatedAt", "version", "title", "summary",
             "whyItMatters", "impact", "timelineImpact", "sources"]
    item = {k: item[k] for k in order if k in item}

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(item, f, ensure_ascii=False, indent=2)
        f.write("\n")

    Path(args.note_out).write_text(note.strip() + "\n", encoding="utf-8")

    u = response.usage
    print(f"✅ 생성 완료 — {item['title']}")
    print(f"   토큰: 입력 {u.input_tokens} / 출력 {u.output_tokens}")
    print(f"   → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
