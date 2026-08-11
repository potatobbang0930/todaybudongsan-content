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
