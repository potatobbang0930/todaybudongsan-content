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

## 파이프라인 (2026-08-12 — 비용 0 구성)

**수집만 자동이고, 글쓰기는 사람이 Claude Code에서 해요.** 사용자가 없는 단계에서
월 고정비를 만들지 않기 위한 선택이에요.

```
Claude Code에서 "오늘 콘텐츠 만들어줘"                 [구독으로 커버]
  → 자료 수집 (국내 IP에서 실행) → 선정 → 초안 → PR
  Merge = 발행
```

> ⚠️ **수집을 GitHub 예약 실행으로 돌리지 않는다.** 러너(미국 데이터센터)에서
> `.go.kr` 사이트 3곳에 접속이 막힌다. 2026-08-12 실행에서 후보가 21건 → 1건으로
> 줄었고, 남은 1건이 부동산과 무관한 자료였다. **부분 수집은 없는 것보다 나쁘다** —
> 결과만 보면 "그날 자료가 적었다"와 구분되지 않는다.
> 수집은 국내에서 실행하고, 실패하면 스크립트가 exit 1로 멈춘다.

| 스크립트 | 하는 일 | 비용 |
|---|---|---|
| `collect_sources.py` | 피드 6개 수집. 국토부는 본문이 hwpx 첨부에만 있어 내려받아 파싱하고, 금융위는 RSS에 날짜가 없어 상세 페이지에서 보완해요 | 없음 |
| `generate_draft.py` | Claude API로 초안 생성 (structured outputs로 스키마 보장) | **API 과금** |
| `render_draft.py` | PR 본문용 마크다운 렌더링 | 없음 |
| `validate_content.py` | 스키마·문체 검증 | 없음 |
| `archive_content.py` | 머지 후 날짜별 보관본·인덱스 생성 | 없음 |

### 워크플로

| 이름 | 자동 실행 | 비고 |
|---|---|---|
| **일일 수집** | ✅ 매일 22:00 KST | 자료만 모아요. 비용 없음 |
| **일일 초안 (API 과금)** | ❌ 수동만 | 켜려면 `ANTHROPIC_API_KEY` 등록 + schedule 주석 해제 |
| **콘텐츠 검증** | PR마다 | |
| **발행 후 보관** | main 머지 후 | |

### 자동 발행으로 바꿀 때

사용자가 생겨서 매일 발행이 중요해지면:

1. Settings → Secrets and variables → Actions에 `ANTHROPIC_API_KEY` 등록
2. `daily-draft.yml`의 `schedule` 주석 해제
3. `daily-collect.yml`의 `schedule` 주석 처리 (중복 수집 방지)

### 손으로 돌려보기

```sh
python3 scripts/collect_sources.py --date 2026-08-12   # → candidates.json (무료)
python3 scripts/validate_content.py content/latest.json

# 아래는 API 키가 있을 때만
pip install anthropic
python3 scripts/generate_draft.py --dry-run            # 호출 없이 요청만 확인
python3 scripts/generate_draft.py
```
