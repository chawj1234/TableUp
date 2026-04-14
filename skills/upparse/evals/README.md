# UpParse 평가 시나리오

TDD 원칙: 스킬을 구현하기 전에 **"어떤 입력에 대해 어떤 결과가 나와야 하는가"** 를 먼저 정의한다. Upstage Ambassador 가이드의 품질 체크리스트에 따라 최소 3개 시나리오를 유지한다.

## 시나리오 개요

| # | 파일 | 검증 대상 | 난이도 |
|---|---|---|---|
| 1 | `scenario-01-complex-table.md` | 병합 셀·다단 헤더 있는 표 추출 | 중 |
| 2 | `scenario-02-chart-to-data.md` | 차트 이미지 → 구조화된 데이터 | 상 |
| 3 | `scenario-03-hwp-derived.md` | HWP에서 변환된 PDF 처리 | 중 |

## 실행 원칙

- 각 시나리오는 **재현 가능한 입력** 1개 이상을 명시한다. fixture 가 없으면 URL 에서 자동 다운로드.
- Pass 기준은 **정량 가능**해야 한다 (예: "정확히 N행", "오차 ±X%").
- Baseline 으로 **기존 도구**(Tabula, pdftotext, 등) 와 대조하여 개선 정도를 수치화한다.
- 실패 시 개선은 **SKILL.md Gotchas 또는 scripts/ 로직** 에 반영한다.
- **회귀 방지 체크**: 과거 버그(예: chart 파싱 실패 silent skip) 는 `run_evals.py` 에 명시 체크로 남겨 재발 시 즉시 FAIL 되도록 한다.

## 전체 실행

```bash
python scripts/run_evals.py             # 3개 시나리오 전부
python scripts/run_evals.py --only 1    # 시나리오 1만
```

출력은 `evals/results/<date>/` 에 저장된다.
