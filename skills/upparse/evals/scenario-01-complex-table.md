# Eval 1: 복잡 표 추출 (병합 셀 · 다단 헤더)

## 목적

기존 Tabula/Camelot 이 실패하는 **병합 셀(rowspan)** 과 **다단 헤더** 가 있는 실제 한국 금융 보고서 표를 UpParse 이 정확히 추출하는지 검증한다.

## 입력

- **파일**: 한국은행 금융안정보고서 (2025년 12월) 본문 — `evals/fixtures/bok_financial_stability_main.pdf`
- **URL**: https://www.bok.or.kr/fileSrc/portal/4f1a9e7acede40168fde41d1e555d2f4/5/d9b3fe9fbcec4bee83171092b6da2654.pdf
- **처리 범위**: 전체 페이지 (p.6 의 취약차주 표를 meta 에서 필터링하여 검증)
- **옵션**: `--no-source --force` (run_evals.py 고정값)

## 예상 출력

### Table 구조 (p.6 취약차주 표)
- 헤더: 2단 구조 (연도 `23년`·`24년`·`25년`) × (분기 `1/4`·`2/4`·`3/4`)
- 행 그룹: 3개 (rowspan 원본 — pandas read_html 은 값 복제로 펼쳐 CSV 에 기록)
  - `취약차주`: 차주 수 / 대출금액
  - `신용 등급`: 저 / 중 / 고
  - `소득 수준`: 저 / 중 / 고

### 대표 셀 값 (golden)

| 그룹 | 항목 | 23년 | 24년 | 25년 1/4 | 25년 2/4 | 25년 3/4 |
|---|---|---:|---:|---:|---:|---:|
| 취약차주 | 차주 수 | 6.6 | 6.9 | 7.0 | 7.0 | 6.6 |
| 취약차주 | 대출금액 | 5.3 | 5.3 | 5.3 | 5.2 | 4.9 |
| 신용 등급 | 저 | 3.9 | 4.0 | 4.2 | 4.2 | 3.7 |
| 신용 등급 | 고 | 77.6 | 78.2 | 78.3 | 78.3 | 79.5 |
| 소득 수준 | 고 | 62.5 | 63.3 | 63.5 | 63.8 | 64.1 |

## Pass 기준 (run_evals.py `eval_complex_table` 에 해당)

| 기준 | 임계값 |
|---|---|
| p.6 표 추출 | `meta.files` 중 `type=table`·`page=6` 가 1개 이상 |
| 다행·다열 표 | 가장 큰 p.6 표가 5행 × 5열 이상 |
| 골든 값 5개 중 4개 이상 일치 | 위 표에서 6.6 / 5.3 / 79.5 / 63.5 / 18.5 (신용등급 중 23년) 중 ≥4 |
| 한글 보존 | column 또는 cell 에 `[가-힣]` 포함 |

## Baseline (대조군)

```bash
# Tabula-py 로 같은 페이지 추출
tabula-py --pages 6 --output tabula.csv <pdf>
```

예상 결과: 병합 셀이 NaN 으로 빠지거나 그룹 구조 파괴.

## 측정 (실제 실행 지점)

`scripts/run_evals.py::eval_complex_table` 가 위 기준을 그대로 확인한다. 별도 검증 스크립트는 없음.

## Gotchas (운용상 유의)

- **병합 셀은 보존이 아니라 펼침으로 처리됨**: Upstage HTML 의 `rowspan`/`colspan` 은 pandas `read_html` 이 값 복제·NaN 으로 펼친다. CSV 에서는 모든 셀이 채워진 플랫 테이블이 되므로 "원본 merge 구조" 는 `_raw_response.json` 의 HTML 에서만 확인 가능.
- 헤더가 2행일 때 Upstage 는 첫 두 행을 column 에 나누어 반환한다. 필요 시 후처리로 MultiIndex 재구성.
- 각주 참조 번호(`1)`, `2)`) 는 값으로 오인하지 않도록 숫자 파싱 시 주의.
