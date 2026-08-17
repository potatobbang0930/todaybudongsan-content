#!/usr/bin/env python3
"""콘텐츠 JSON 검증.

앱(app/src/content/loadContent.ts)의 런타임 검증과 같은 규칙을 쓴다.
여기서 통과해야 앱이 폴백으로 내려가지 않는다.
문체 규칙은 docs/UXW_GUIDE.md 기준.
"""
import json
import re
import sys

TYPES = {"fact", "interpretation", "outlook"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# docs/UXW_GUIDE.md 4절 "AI가 쓴 티가 나는 패턴" + 콘텐츠 원칙 금지 표현
FORBIDDEN = {
    "당신": "번역투 — 주어를 생략하세요",
    "여러분": "번역투 — 주어를 생략하세요",
    "습니다": "해요체가 아님",
    "할 수 있습니다": "AI 티 — 해요체로",
    "중요합니다": "AI 티 — 중요하다고 말하지 말고 보여주세요",
    "에 대해": "AI 티 — 조사로 바꾸세요",
    "와 관련하여": "AI 티 — 조사로 바꾸세요",
    "결론적으로": "AI 티 — 지워도 뜻이 통합니다",
    "종합하면": "AI 티 — 지워도 뜻이 통합니다",
    "폭등": "과장 표현",
    "폭락": "과장 표현",
    "지금이 기회": "투자 권유",
    # 활용형까지 넣는다. '서두르'만 두면 '서둘러'를 놓친다(2026-08-12 테스트에서 확인).
    "서두르": "조급함 유도",
    "서둘러": "조급함 유도",
    "지금 사": "매수 권유",
    "매수하세요": "매수 권유",
    "매도하세요": "매도 권유",
}

errors: list[str] = []
warnings: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def need(cond: bool, msg: str) -> bool:
    if not cond:
        err(msg)
    return cond


def check_statement(s, where: str, allow_audience: bool = False) -> None:
    if not isinstance(s, dict):
        err(f"{where}: 객체가 아닙니다")
        return
    if s.get("type") not in TYPES:
        err(f"{where}: type이 {sorted(TYPES)} 중 하나여야 합니다 (현재: {s.get('type')!r})")
    if not isinstance(s.get("text"), str) or not s["text"].strip():
        err(f"{where}: text가 비어 있습니다")
    if not allow_audience and "audience" in s:
        err(f"{where}: audience는 impact 항목에만 쓸 수 있습니다")


def main(path: str) -> int:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        print(f"❌ 파일이 없습니다: {path}")
        return 1
    except json.JSONDecodeError as e:
        # 사람이 GitHub에서 직접 고치다 가장 흔히 내는 실수다.
        print(f"❌ JSON 문법 오류 — {e.lineno}행 {e.colno}열: {e.msg}")
        print("   쉼표 빠짐, 따옴표 짝 안 맞음, 마지막 항목 뒤 쉼표를 확인하세요.")
        return 1

    if not isinstance(d, dict):
        print("❌ 최상위가 객체(JSON object)여야 합니다")
        return 1

    # --- 필수 필드 ---
    for k in ("date", "publishedAt", "updatedAt", "version", "title",
              "summary", "whyItMatters", "impact", "timelineImpact", "sources"):
        need(k in d, f"필수 필드 누락: {k}")

    if isinstance(d.get("date"), str):
        need(bool(DATE_RE.match(d["date"])), f"date는 YYYY-MM-DD 형식이어야 합니다 (현재: {d['date']!r})")

    need(isinstance(d.get("version"), int) and d["version"] >= 1,
         f"version은 1 이상의 정수여야 합니다 (현재: {d.get('version')!r})")

    need(isinstance(d.get("title"), str) and bool(d.get("title", "").strip()),
         "title이 비어 있습니다")

    # kind는 선택 필드지만, 있으면 값이 맞아야 한다 (2026-08-17 신설)
    #
    # 앱이 이 값으로 요약 제목("오늘/이번 주 뭐가 바뀌었냐면")과 날짜 라벨을 가른다.
    # 오타를 통과시키면 라이브 앱이 그 콘텐츠를 통째로 거부해 옛날 콘텐츠가 남는다
    # (loadContent.ts의 isKind가 같은 기준으로 검사한다). 여기서 먼저 막는다.
    kind = d.get("kind")
    if kind is not None:
        need(kind in ("daily", "weekly"),
             f"kind는 'daily' 또는 'weekly'여야 합니다 (현재: {kind!r})")

    # status는 선택 필드지만, 있으면 형태가 맞아야 한다 (2026-08-13 신설)
    st = d.get("status")
    if st is not None:
        if need(isinstance(st, dict), "status는 객체여야 합니다"):
            need(isinstance(st.get("confirmed"), bool),
                 f"status.confirmed는 true/false여야 합니다 (현재: {st.get('confirmed')!r})")
            need(isinstance(st.get("label"), str) and bool(str(st.get("label", "")).strip()),
                 "status.label이 비어 있습니다")

    # summary는 정확히 3개 — 앱이 이걸로 폴백 여부를 가른다
    #
    # 2026-08-14: 1줄로 줄이는 안을 검토했다가 폐기했다(일주일 더 발행해보고 판단).
    # 만약 나중에 다시 꺼낸다면 **앱 번들이 먼저다** — 라이브 loadContent.ts가
    # `summary.length === 3`을 하드 검증하므로, 검증 완화 번들이 출시되기 전에
    # 1줄을 발행하면 앱이 조용히 폴백(옛날 콘텐츠)으로 떨어진다.
    s = d.get("summary")
    if need(isinstance(s, list), "summary는 배열이어야 합니다"):
        need(len(s) == 3, f"summary는 정확히 3개여야 합니다 (현재: {len(s)}개)")
        for i, line in enumerate(s):
            need(isinstance(line, str) and bool(line.strip()), f"summary[{i}]가 비어 있습니다")

    for key, allow_aud in (("whyItMatters", False), ("impact", True)):
        v = d.get(key)
        if need(isinstance(v, list), f"{key}는 배열이어야 합니다"):
            need(len(v) >= 1, f"{key}는 최소 1개가 필요합니다")
            for i, item in enumerate(v):
                check_statement(item, f"{key}[{i}]", allow_aud)

    check_statement(d.get("timelineImpact"), "timelineImpact")

    src = d.get("sources")
    if need(isinstance(src, list), "sources는 배열이어야 합니다"):
        need(len(src) >= 1, "sources는 최소 1개가 필요합니다")
        for i, item in enumerate(src):
            if not isinstance(item, dict) or not str(item.get("name", "")).strip():
                err(f"sources[{i}]: name이 비어 있습니다")

    # --- 문체 (docs/UXW_GUIDE.md) ---
    texts = [d.get("title", "")]
    if isinstance(st, dict) and isinstance(st.get("label"), str):
        texts.append(st["label"])
    texts += [x for x in (d.get("summary") or []) if isinstance(x, str)]
    for key in ("whyItMatters", "impact"):
        for item in (d.get(key) or []):
            if isinstance(item, dict):
                texts.append(str(item.get("text", "")))
                texts.append(str(item.get("audience", "")))
    ti = d.get("timelineImpact")
    if isinstance(ti, dict):
        texts.append(str(ti.get("text", "")))
    body = " ".join(texts)

    for word, why in FORBIDDEN.items():
        if word in body:
            err(f"문체 위반: '{word}' 사용 — {why}")

    # 출처 기관명: 2026-01-02부로 기획재정부 → 재정경제부
    all_text = body + " " + " ".join(str(x.get("name", "")) for x in (src or []) if isinstance(x, dict))
    if "기획재정부" in all_text:
        err("출처 기관명 오류: '기획재정부'는 2026-01-02부로 '재정경제부'로 바뀌었습니다")

    # 조언조로 흐르기 가장 쉬운 자리 — 경고만 (사람이 판단)
    if isinstance(ti, dict) and re.search(r"(하세요|해야 해요|하는 게 좋|유리해요)", str(ti.get("text", ""))):
        warnings.append("timelineImpact가 조언처럼 읽힙니다. '언제 무엇이 달라진다'까지만 쓰세요")

    # 제목 규칙 (2026-08-12 개정): 기본형은 '대상 + 핵심 변화 + (금액·날짜)'.
    # 질문형은 예외로만 허용하므로 자동으로 막지 않고 사람에게 되묻는다.
    #
    # ⚠️ '나요'를 그냥 넣으면 안 된다(2026-08-13 오탐으로 확인).
    # "대출 여력이 늘어나요"의 끝 두 글자가 '나요'라 평서문이 질문형으로 잡혔다.
    # '-나요'는 의문형('되나요?')과 평서형('늘어나요')이 같은 꼴이라 어미만으로는
    # 못 가른다. 그래서 물음표나 의문사가 함께 있을 때만 의문형으로 본다.
    # '까요/을까/ㄹ까'는 그 자체로 의문형이라 조건 없이 잡는다.
    title = str(d.get("title", ""))
    QUESTION_WORDS = ("뭐", "무엇", "얼마", "언제", "어디", "누가", "왜", "어떻게", "어떤")
    looks_interrogative = (
        re.search(r"(까요|을까|ㄹ까)\s*\??$", title)
        or (re.search(r"(나요|가요|는가)\s*\??$", title)
            and ("?" in title or any(w in title for w in QUESTION_WORDS)))
    )
    if looks_interrogative:
        warnings.append(
            "title이 질문형입니다. 질문 자체가 정보 전달에 더 효과적인 경우가 아니면 "
            "'대상 + 핵심 변화 + (금액·날짜)'로 바꾸세요 (content-schema.md 카피 작성 원칙)"
        )

    # 같은 수치를 여러 절에서 되풀이하면 읽을 덩어리만 늘어난다 (2026-08-12 외부 검토).
    # 3회 이상 나오면 알린다 — 2회는 요약과 본문에 한 번씩일 수 있어 정상이다.
    numbers = re.findall(r"\d[\d,]*\s*(?:억|만|천)?\s*(?:원|%|퍼센트)", body)
    seen: dict[str, int] = {}
    for n in numbers:
        key = n.replace(" ", "")
        seen[key] = seen.get(key, 0) + 1
    repeated = [f"{k}({v}번)" for k, v in seen.items() if v >= 3]
    if repeated:
        warnings.append(
            "같은 수치를 세 번 이상 설명하고 있어요: " + ", ".join(repeated) +
            " — 수치는 한 번만 설명하고 뒤에서는 되풀이하지 마세요"
        )

    for w in warnings:
        print(f"⚠️  {w}")
    if errors:
        print(f"\n❌ 검증 실패 — {len(errors)}건\n")
        for e in errors:
            print(f"  · {e}")
        return 1

    print(f"✅ 검증 통과 — {d['date']} · {d['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "content/latest.json"))
