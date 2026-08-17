#!/usr/bin/env python3
"""콘텐츠 JSON을 PR 본문용 마크다운으로 렌더링한다.

검수자가 JSON diff가 아니라 읽을 수 있는 글을 보게 하려는 것이다.
화면 문구는 docs/UXW_GUIDE.md 기준과 맞춘다.
"""
import json
import sys

LABEL = {
    "fact": "확인된 내용",
    "interpretation": "이렇게 볼 수 있어요",
    "outlook": "아직 지켜봐야 해요",
}


def main(path: str) -> int:
    d = json.load(open(path, encoding="utf-8"))
    out = []

    # 제목과 확정 여부는 첫 화면에서 함께 읽히는 한 덩어리다.
    # 검수할 때도 같이 보여야 "이거 확정된 거야?"를 판단할 수 있다.
    out.append(f"### {d['title']}")
    status = d.get("status")
    if status:
        mark = "🟠 확정 전" if not status.get("confirmed") else "⚪ 확정"
        out.append(f"{mark} · {status.get('label', '')}")
    else:
        out.append("_(status 없음 — 화면에 확정 여부 줄이 나오지 않아요)_")

    # 앱 화면과 같은 기준으로 제목을 고른다 (TodayIssueScreen.tsx SUMMARY_TITLE).
    # 여기가 어긋나면 PR 미리보기가 실제 화면과 다른 것을 보여준다.
    summary_title = (
        "이번 주 뭐가 바뀌었냐면" if d.get("kind") == "weekly" else "오늘 뭐가 바뀌었냐면"
    )
    out.append(f"\n**{summary_title}**")
    out += [f"- {line}" for line in d["summary"]]

    out.append("\n**이게 왜 중요하냐면**")
    for s in d["whyItMatters"]:
        out.append(f"- `{LABEL.get(s['type'], s['type'])}` {s['text']}")

    out.append("\n**누가 영향을 받나요**")
    for s in d["impact"]:
        who = (s.get("audience") or "").strip()
        prefix = f"*{who}* — " if who else ""
        out.append(f"- {prefix}`{LABEL.get(s['type'], s['type'])}` {s['text']}")

    t = d["timelineImpact"]
    out.append("\n**집 사는 시기가 달라질까요**")
    out.append(f"- `{LABEL.get(t['type'], t['type'])}` {t['text']}")

    out.append("\n**출처**")
    for s in d["sources"]:
        url = (s.get("url") or "").strip()
        out.append(f"- {s['name']}" + (f"\n  {url}" if url else ""))

    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "content/latest.json"))
