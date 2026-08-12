# todaybudongsan-content

"오늘부동산무슨일" 앱인토스 미니앱이 매일 fetch하는 콘텐츠 JSON을 담는 저장소예요.
이 저장소는 콘텐츠 배포 전용이며, 앱 코드와 기획 문서는 별도의 비공개 저장소(로컬)에서 관리해요.

## 구조

```
content/
- latest.json        # 오늘의 최신 콘텐츠
- archive.json        # 발행된 콘텐츠의 날짜·제목 인덱스
- YYYY-MM-DD.json     # 날짜별 콘텐츠 원본
```

스키마 정의는 앱 저장소의 `content-schema.md`를 따른다.

## 배포 URL 패턴

```
https://raw.githubusercontent.com/<username>/todaybudongsan-content/main/content/latest.json
https://raw.githubusercontent.com/<username>/todaybudongsan-content/main/content/YYYY-MM-DD.json
https://raw.githubusercontent.com/<username>/todaybudongsan-content/main/content/archive.json
```

## 발행 방법

1. `content/YYYY-MM-DD.json` 파일 추가
2. 같은 내용으로 `content/latest.json` 갱신
3. `content/archive.json`에 `{ "date", "title" }` 항목 추가
4. 커밋 + push = 발행

## ⚠️ 현재 상태 (2026-08-11)

**지금 올라와 있는 콘텐츠는 전부 `[SAMPLE]` 표시된 가짜 데이터다.** 앱의 latest.json
요청·캐시·폴백 3단계 로직을 실제 URL로 검증하기 위해 Day 5에 발행한 것이며, 어떤 사실도
담고 있지 않다.

**출시 전 반드시 실제 콘텐츠로 교체해야 한다** (Day 8 발행 루틴). 교체 전에 앱이 출시되면
사용자에게 `[SAMPLE]` 문구가 그대로 노출된다.

## 발행 방식 (2026-08-12 확정)

**사람이 손대는 파일은 `content/latest.json` 하나뿐이에요.** 나머지는 자동으로 만들어져요.

```
매일 22:00  수집 → 초안 생성 → PR 생성          (latest.json 아직 그대로)
     22:30  PR을 읽고 Merge                     ← 이 순간이 '발행'
     직후   Action이 날짜별 보관본·인덱스 생성
```

| 파일 | 누가 만드나 | 쓰임 |
|---|---|---|
| `content/latest.json` | 사람 (PR로 검수·수정) | **앱이 읽는 유일한 파일** |
| `content/YYYY-MM-DD.json` | Action (머지 후 자동) | 주말 "주간 요약"을 쓸 때 그 주 콘텐츠를 읽는 용도 |
| `content/archive.json` | Action (머지 후 자동) | 날짜·제목 인덱스 |

### 자동 검사

`content/latest.json`을 건드리는 PR에는 검증이 자동으로 돌아요
(`scripts/validate_content.py`). **통과해야 Merge하세요.**

- JSON 문법 (쉼표 빠짐 등 — GitHub에서 직접 고칠 때 가장 흔한 실수)
- 스키마 (`summary` 정확히 3개, `type` 값, 필수 필드) — 어기면 앱이 폴백으로 내려가요
- 문체 ("당신"·"여러분"·해요체·AI 티 패턴·과장 표현)
- 출처 기관명 (기획재정부 → **재정경제부**, 2026-01-02 개편)

로컬에서 미리 돌려볼 수도 있어요.

```sh
python3 scripts/validate_content.py content/latest.json
```

## 자동 수집 파이프라인

매일 22시(KST)에 GitHub Actions가 공식 자료를 훑어 초안 PR을 만들어요.
**PR을 만드는 데까지가 자동이고, 발행은 사람이 Merge할 때 일어나요.**

| 스크립트 | 하는 일 |
|---|---|
| `collect_sources.py` | Tier 1 피드 6개 수집. 국토부는 본문이 hwpx 첨부에만 있어 내려받아 파싱하고, 금융위는 RSS에 날짜가 없어 상세 페이지에서 보완해요 |
| `generate_draft.py` | Claude API로 초안 생성. 출력 JSON은 structured outputs로 스키마가 보장돼요 |
| `render_draft.py` | PR 본문용 마크다운 렌더링 (검수자가 JSON 대신 글을 읽도록) |
| `validate_content.py` | 스키마·문체 검증 |
| `archive_content.py` | 머지 후 날짜별 보관본·인덱스 생성 |

### 필요한 설정

**저장소 Secrets에 `ANTHROPIC_API_KEY`를 추가해야 해요** (Settings → Secrets and
variables → Actions). 없으면 초안 생성 단계에서 실패해요.

### 손으로 돌려보기

```sh
pip install anthropic
python3 scripts/collect_sources.py --date 2026-08-12   # → candidates.json
python3 scripts/generate_draft.py --dry-run            # 키 없이 요청만 확인
python3 scripts/generate_draft.py                      # → content/latest.json
python3 scripts/validate_content.py content/latest.json
```

Actions 탭에서 **일일 초안 → Run workflow**로 날짜와 effort를 지정해 수동 실행할 수도 있어요.
