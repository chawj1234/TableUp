# 출력 스키마

`.upparse/` 디렉토리 구조와 각 파일 형식.

## 디렉토리 레이아웃

```
.upparse/
├── index.md                    # 마스터 맵 (사람·LLM 모두 우선 읽을 것)
├── meta.json                   # 메타데이터 (기계가 읽는 사실)
├── _raw_response.json          # Upstage 원본 응답 (디버그용, 재사용 가능)
├── t00_p3_<slug>.csv           # 실제 데이터 표 (prefix: t)
├── c00_p4_<slug>.csv           # 차트 유래 데이터 (prefix: c)
└── sources/
    └── p<N>.png                # 원본 페이지 이미지 (검증용, DPI 150)
```

## 파일명 규칙

`{prefix}{index:02d}_p{page}_{slug}.csv`

- `prefix`: `t` (표) 또는 `c` (차트)
- `index`: 같은 prefix 안에서 0부터 증가
- `page`: 원본 PDF 페이지 번호 (1-indexed)
- `slug`: 캡션을 슬러그화한 것 (한글 유지, 공백→하이픈, 40자 제한, `<그림/표/Fig>` 접두 제거)

## index.md 구성

```markdown
# UpParse 추출 결과

- 원본: {파일명}
- 총 페이지: {N}
- 표: {X}, 차트: {Y}, 각주: {Z}

## 표 (Tables)
| 파일 | 페이지 | 제목 | 크기 |
...

## 차트 (Charts → Data)
| 파일 | 페이지 | 제목 | 크기 |
...

## 경계 케이스 (차트로 재분류된 항목)
- ...

## 검증용 원본 이미지
`sources/p<N>.png` 참조
```

LLM 이 항상 먼저 읽어야 하는 파일. "어떤 표가 있고 어디에 있는지" 를 개관할 수 있다.

## meta.json 스키마

```json
{
  "source": {
    "name": "보고서.pdf",
    "sha256": "e99833...",
    "pages": 25
  },
  "model": "document-parse-260128",
  "counts": {
    "tables": 15,
    "charts": 38,
    "footnotes": 2
  },
  "footnotes": [
    {"page": 39, "markdown": "| 주: | 대손충당금/..."}
  ],
  "boundary_cases": [
    {"page": 48, "index": 5, "reason": "chart-like table"}
  ],
  "files": [
    {
      "type": "table",
      "path": "t00_p3_credit-growth-rate.csv",
      "page": 3,
      "caption": "월별 신용 증가율",
      "rows": 6,
      "cols": 9
    }
  ]
}
```

## CSV 인코딩

- **UTF-8 with BOM** (`utf-8-sig`) — Excel 한글 호환을 위해
- 구분자: 콤마
- 헤더: pandas `read_html` 결과 그대로 (MultiIndex 는 "col1__col2" 로 평면화됨)

## 원본 페이지 이미지

- 요소가 등장한 페이지만 렌더링
- DPI 150, PNG 포맷
- `pypdfium2` 로 렌더링 (외부 프로세스 불필요)
- `--no-source` 플래그로 비활성화 가능

## 캐시

`~/.cache/upparse/{sha256[:16]}.json` 에 Upstage 응답 저장. SHA256 동일한 PDF 재호출 시 즉시 복원 (API 비용 0).
