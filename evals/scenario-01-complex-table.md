# Eval 1: 복잡 표 추출 (병합 셀 · 다단 헤더)

## 목적

기존 Tabula/Camelot이 실패하는 **병합 셀(rowspan)** 과 **다단 헤더**가 있는 실제 한국 금융 보고서 표를 TableUp이 정확히 추출하는지 검증한다.

## 입력

- **파일**: 한국은행 금융안정보고서 (2025년 12월) 본문 p.6
- **URL**: https://www.bok.or.kr/fileSrc/portal/4f1a9e7acede40168fde41d1e555d2f4/5/d9b3fe9fbcec4bee83171092b6da2654.pdf
- **옵션**: `--pages 6`

## 예상 출력

### Table 구조
- 헤더: 2단 구조 (연도: `23년`, `24년`, `25년`) × (분기: `1/4`, `2/4`, `3/4`)
- 행 그룹: 3개 (rowspan 존재)
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

## Pass 기준

| 기준 | 임계값 |
|---|---|
| 행 수 추출 | 정확히 10행 (또는 그 이상 합리적 변형) |
| 숫자 일치 | 위 golden 모든 셀 100% 정확 |
| 그룹 구조 보존 | `취약차주`, `신용 등급`, `소득 수준` 그룹이 식별 가능 |
| 헤더 복원 | 연도와 분기 정보 모두 존재 |
| 출력 파일 | `.tableup/t*_p6_*.csv` 생성 |

## Baseline (대조군)

```bash
# Tabula-py 로 같은 페이지 추출
tabula-py --pages 6 --output tabula.csv <pdf>
```

예상 결과: 병합 셀이 NaN으로 빠지거나 그룹 구조 파괴.

## 측정 스크립트

```python
# evals/check_scenario_01.py
import pandas as pd

def check():
    df = pd.read_csv(".tableup/t01_p6_vulnerable-borrowers.csv")
    golden = {
        ("취약차주", "차주 수", "23년"): 6.6,
        ("취약차주", "대출금액", "24년"): 5.3,
        ("신용 등급", "고", "25년 3/4"): 79.5,
        ("소득 수준", "고", "25년 1/4"): 63.5,
    }
    mismatches = []
    for (group, item, period), expected in golden.items():
        # find and compare
        ...
    return len(mismatches) == 0
```

## Gotchas (실패 시 반영할 패턴)

- 병합 셀이 `NaN`으로 빠지면 — forward-fill을 적용하지 말고 **원본 rowspan 관계 유지**
- 헤더가 2행일 때 pandas `read_html` 의 `header=[0,1]` 옵션 필요
- 각주 참조 번호(`1)`, `2)`)는 값으로 오인하지 않기
