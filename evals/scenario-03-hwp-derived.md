# Eval 3: HWP에서 변환된 PDF 처리 (한국 특화)

## 목적

한국 공공기관·대기업에서 생산되는 문서는 대부분 **HWP 원본 → PDF 변환** 형태로 유통된다. 이 경우 폰트·문자 인코딩·레이아웃에 특수한 패턴이 발생한다. TableUp이 일반 PDF와 동등한 수준으로 처리하는지 검증한다.

## 입력

- **파일**: 한국은행 금융안정보고서 본문 (77 페이지)
- **URL**: https://www.bok.or.kr/fileSrc/portal/4f1a9e7acede40168fde41d1e555d2f4/5/d9b3fe9fbcec4bee83171092b6da2654.pdf
- **메타데이터**: `Creator: Hwp 2018 10.0.0.10640` + `Producer: Hancom PDF 1.3.0.538`
- **옵션**: 전체 페이지

## Pass 기준

| 기준 | 임계값 | 근거 |
|---|---|---|
| 처리 완료 | Upstage API 응답 `status=completed` | 기본 동작 |
| 총 요소 수 | ≥ 1000 | 사전 측정치(1108) 기반 |
| 표 개수 | ≥ 20 | 사전 측정치(23) |
| 차트 개수 | ≥ 130 | 사전 측정치(142) |
| 한국어 글자 깨짐 | 전체 텍스트 내 `?`, `�` 문자 0개 |
| 인코딩 문제 | 한글 유니코드 범위(가-힣) 문자 수 ≥ 10,000 |
| 처리 시간 | ≤ 400초 (= 페이지당 5.2초) |

## Baseline (대조군)

| 도구 | HWP 변환 PDF에서 | 한국어 |
|---|---|---|
| `pdftotext` | 레이아웃 깨짐 | 일부 깨짐 가능 |
| Claude native Read | OK (~15페이지 제한) | OK |
| Tabula | 구조 파괴 | — |
| Azure Document Intelligence | HWP 메타 인식 못함 | OK |
| **TableUp** | **전체 구조 + 차트/표 완전 추출** | **완벽** |

## 측정 스크립트

```python
# evals/check_scenario_03.py
import json
import re

def check():
    result = json.load(open(".tableup/_raw_response.json"))
    elements = result["elements"]

    # 1. 기본 처리
    assert len(elements) >= 1000, f"elements too few: {len(elements)}"

    # 2. 표/차트 개수
    n_tables = sum(1 for e in elements if e.get("category") == "table")
    n_charts = sum(1 for e in elements if e.get("category") == "chart")
    assert n_tables >= 20
    assert n_charts >= 130

    # 3. 한국어 완전성
    all_text = result.get("content", {}).get("markdown", "")
    korean_chars = len(re.findall(r"[가-힣]", all_text))
    broken_chars = all_text.count("�") + all_text.count("\ufffd")

    assert korean_chars >= 10000, f"Korean too few: {korean_chars}"
    assert broken_chars == 0, f"Broken chars found: {broken_chars}"

    return True
```

## Gotchas

- HWP에서 변환된 PDF는 **텍스트가 outline으로 변환된 경우**가 있다 — 이 때 OCR 필요. Upstage `ocr=auto` 가 자동 감지하지만 실패 시 `ocr=force` 옵션 안내 필요.
- 한컴 PDF Producer의 경우 **음수가 삼각형(▲/▽)** 으로 표기되는 경우가 있다 — 숫자 파싱 시 후처리 필요.
- 페이지 번호가 한자(一二三)로 찍힌 경우도 드물게 있음 — 영향 없음 확인 완료.
