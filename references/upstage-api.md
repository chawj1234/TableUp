# Upstage Document Parse API 요약

TableUp 이 사용하는 Upstage API 핵심만. 전체 명세는 [공식 에이전트 문서](https://console.upstage.ai/api/docs/for-agents/raw) 참조.

## 엔드포인트 (TableUp 사용)

```
POST https://api.upstage.ai/v1/document-digitization
```

Sync 엔드포인트. 100페이지 제한. TableUp 은 100페이지 초과 시 클라이언트 측에서 chunk 분할 후 순차 호출한다.

## 필수 필드

| 필드 | 값 |
|---|---|
| `model` | `document-parse` |
| `document` | 지원 포맷의 multipart 파일 (PDF·이미지·DOCX·PPTX·XLSX·HWP·HWPX) |
| `mode` | **`auto` 기본** · `enhanced` · `standard` 중 선택. `auto` 는 페이지별 자동 분류 |
| `output_formats` | `["html", "markdown"]` |

## 품질 영향이 큰 옵션

| 필드 | TableUp 기본값 | 효과 |
|---|---|---|
| `chart_recognition` | `true` | 차트 이미지 → 데이터 표로 변환 (Upstage 고유) |
| `merge_multipage_tables` | `true` | 여러 페이지 걸친 표 자동 stitch |
| `coordinates` | `true` | bbox 정보 포함 (디버깅·검증용) |
| `ocr` | `auto` | 스캔본은 자동 OCR 전환 |

## 응답 구조 (발췌)

```json
{
  "model": "document-parse-260128",
  "usage": { "pages": 25 },
  "content": {
    "html": "...",
    "markdown": "...",
    "text": "..."
  },
  "elements": [
    {
      "category": "table|chart|caption|paragraph|heading1|footnote|...",
      "page": 3,
      "content": {
        "html": "<table>...</table>",
        "markdown": "| ... |"
      },
      "coordinates": [...]
    }
  ]
}
```

## 비동기 엔드포인트는 왜 안 쓰나

2026-04 기준, `/v1/document-digitization/async` 와 `mode=enhanced` 조합에서 "internal server error" 가 재현됨을 확인했다. `mode=standard` + async 는 정상 동작. Upstage 측 해결 시 `upstage_client.py` 에 async 경로 추가 예정.

## 제한

- 파일 크기: 50 MB
- 페이지: sync 100, async 1,000
- 배치: async 는 10페이지 단위로 자동 분할
- Rate limit: 2 RPS, 1,200 PPM

## 비용 (참고)

- standard: 페이지당 약 $0.01
- enhanced: 페이지당 약 $0.03
- 신규 가입 시 $10 무료 크레딧 제공
