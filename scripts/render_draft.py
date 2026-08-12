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

    out.append("**오늘 뭐가 바뀌었냐면**")
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
