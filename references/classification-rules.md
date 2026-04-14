# 분류 규칙 (classification rules)

Upstage Document Parse 응답의 `element.category` 값만으로는 **실제 데이터 표**, **차트 이미지**, **각주·출처 메타**를 구분하기 어렵다. UpParse 은 다음 규칙으로 후처리 분류한다.

## 4가지 분류 라벨

| 라벨 | 설명 | 출력 파일 prefix |
|---|---|---|
| `real_table` | 실제 데이터 표 | `t` |
| `chart` | Upstage 가 차트로 분류한 요소 (올바른 경우) | `c` |
| `chart_misid` | `category=table` 이지만 차트 시각화인 경우 | `c` (차트와 동일 출력, `boundary_cases` 에 기록) |
| `footnote` | `주:`, `자료:` 로 시작하는 메타 표 | 출력 안 함. `meta.json` 의 `footnotes` 배열에 기록 |

## 판정 로직 (scripts/extract.py classify_element)

```
if category == "chart":
    return "chart"

if category != "table":
    return "other"   # paragraph, heading, etc.

# category == "table" 인 경우:
if markdown starts with ("| 주:", "| 자료:", "주:", "자료:"):
    return "footnote"

if br_count >= 3 and any("(%)", "조원", "천조", "(pp)", "/4") in markdown:
    return "chart_misid"

if digit_ratio < 0.01 and len(markdown) > 50:
    return "other"   # 설명문이 표로 오분류된 경우

return "real_table"
```

## 판정 근거 (검증에서 확인한 실제 분포)

한국은행 금융안정보고서(77p) 에서 `category=table` 반환 23개 중:
- real_table: 15 (65%)
- chart_misid: 6 (26%)
- footnote: 2 (9%)

## 경계 케이스

분류가 모호한 경우 `meta.json` 의 `boundary_cases` 배열에 기록되며, `index.md` 에도 별도 섹션으로 표시된다. 사용자가 수동 검증할 수 있도록 원본 페이지 이미지(`sources/p<N>.png`) 를 꼭 생성한다.

## 예외 처리

- HTML 파싱 실패 시: 원본 HTML 을 `*.html` 로 저장하고 CSV 는 생성하지 않음. `index.md` 에 "파싱 실패" 표시.
- 완전히 빈 `<table>` 요소: 건너뜀 (카운트 증가 없음).
