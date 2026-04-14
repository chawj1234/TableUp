# Eval 2: 차트 이미지 → 구조화된 데이터

## 목적

Tabula·Camelot 같은 기존 PDF 도구가 **완전히 실패**하고 Claude vision도 숫자를 **환각**하는 영역인 "차트를 데이터로 변환" 기능이 Upstage Enhanced mode 연동으로 정확히 작동하는지 검증한다.

## 입력

- **파일**: 한국은행 "AI의 빠른 확산과 생산성 효과" (25 페이지)
- **경로**: `/Users/chawj/Downloads/AI의 빠른 확산과 생산성 효과-한국은행.pdf`
- **옵션**: `--pages 5`

## 예상 출력

### Chart 정보
- **chart_type**: `bar chart`
- **caption**: 한국 vs 미국의 AI 사용률 비교

### 데이터 (golden)

| 구분 | 한국 | 미국 |
|---|---:|---:|
| 전체 | 63.5 | 39.6 |
| 업무 내 | 51.8 | 26.5 |
| 업무 외 | 60.1 | 33.7 |

## Pass 기준

| 기준 | 임계값 |
|---|---|
| 차트 타입 식별 | `bar chart` 또는 동의어 |
| 카테고리 추출 | 3개 전부 (`전체`, `업무 내`, `업무 외`) |
| 시리즈 추출 | 2개 전부 (`한국`, `미국`) |
| 숫자 정확도 | 6개 값 전부 오차 ±5% 이내 |
| 출력 파일 | `.tableup/c*_p5_*.csv` 생성 (차트 prefix `c`) |
| 메타 데이터 | `meta.json` 에 `chart_type` 필드 존재 |

## Baseline (대조군)

| 도구 | 예상 결과 |
|---|---|
| Tabula-py | 0% (차트 인식 불가) |
| Camelot | 0% |
| Claude vision (native) | 차트 타입은 OK, 숫자는 ±10% 환각 발생 |
| **TableUp** | **≥95% 정확도 목표** |

## 측정 스크립트

```python
# evals/check_scenario_02.py
import json
import pandas as pd

GOLDEN = {
    ("전체", "한국"): 63.5,
    ("전체", "미국"): 39.6,
    ("업무 내", "한국"): 51.8,
    ("업무 내", "미국"): 26.5,
    ("업무 외", "한국"): 60.1,
    ("업무 외", "미국"): 33.7,
}

def check():
    meta = json.load(open(".tableup/meta.json"))
    chart_files = [f for f in meta["files"] if f["type"] == "chart" and f["page"] == 5]
    assert any("bar" in c.get("chart_type", "").lower() for c in chart_files)

    df = pd.read_csv(chart_files[0]["path"])
    errors = []
    for (cat, series), expected in GOLDEN.items():
        actual = df.loc[df.iloc[:, 0] == cat, series].iloc[0]
        if abs(actual - expected) / expected > 0.05:
            errors.append((cat, series, expected, actual))
    return len(errors) == 0, errors
```

## Gotchas (실패 시 반영)

- 차트 설명 텍스트와 추출 데이터가 **불일치**할 때는 추출 데이터를 우선하되 경고 로그 남김
- 한국어 범례(`전체`/`업무 내`/`업무 외`) 순서가 원본과 다를 수 있음 — 정렬 비교 사용
- 단위 행(`(%)`)이 헤더로 잘못 들어올 수 있음 → skipping rule
