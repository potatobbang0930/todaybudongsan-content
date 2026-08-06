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

아직 실제 콘텐츠 파일은 없다 (Day 5 네트워크 로직 테스트, Day 8 실제 운영 시작 예정).
