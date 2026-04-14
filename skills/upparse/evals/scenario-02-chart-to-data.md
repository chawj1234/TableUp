# Eval 2: 차트 이미지 → 구조화된 데이터

## 목적

Tabula·Camelot 같은 기존 PDF 도구가 **완전히 실패**하고 Claude vision 도 숫자를 **환각**하는 영역인 "차트를 데이터로 변환" 기능이 Upstage Document Parse 연동으로 정확히 작동하는지 검증한다.

## 입력

- **파일**: 한국은행 "AI 의 빠른 확산과 생산성 효과" 이슈노트 — `evals/fixtures/bok_ai_report.pdf`
- **URL**: https://www.bok.or.kr/fileSrc/portal/4328064bf5fa45ac8b118692ba3c4644/1/dc9d59003d50427d8735ee8830d4b853.pdf
- **처리 범위**: 전체 페이지 (p.5 한국 vs 미국 차트를 meta 에서 필터링하여 검증)
- **옵션**: `--no-source --force` (run_evals.py 고정값)

## 예상 출력

### Chart 정보 (p.5)
- **차트 유형**: 막대 그래프
- **caption**: 한국 vs 미국의 AI 사용률 비교

### 데이터 (golden)

| 구분 | 한국 | 미국 |
|---|---:|---:|
| 전체 | 63.5 | 39.6 |
| 업무 내 | 51.8 | 26.5 |
| 업무 외 | 60.1 | 33.7 |

## Pass 기준 (run_evals.py `eval_chart_to_data` 에 해당)

| 기준 | 임계값 |
|---|---|
| 차트 추출 개수 | `meta.files` 중 `type=chart` 가 **30개 이상** |
| p.5 차트 발견 | 위 차트 중 `page=5` 인 것 ≥1 |
| 한국 vs 미국 차트 매칭 | `columns` 에 `한국` 과 `미국` 동시 포함 |
| 골든 값 정확도 | 6개 셀 전부 상대오차 ±5% 이내 |

※ 현재 `meta.json` 에 `chart_type` 필드는 저장하지 않는다. 차트 판별은 파일 prefix (`c*.csv`) 와 `meta.files[i].type == "chart"` 로 수행한다.

## Baseline (대조군)

| 도구 | 예상 결과 |
|---|---|
| Tabula-py | 0% (차트 인식 불가) |
| Camelot | 0% |
| Claude vision (native) | 차트 타입은 OK, 숫자는 ±10% 환각 발생 |
| **UpParse** | **≥95% 정확도 목표** (실측 100%) |

## 측정 (실제 실행 지점)

`scripts/run_evals.py::eval_chart_to_data` 가 `meta.json` 과 `c*.csv` 를 열어 위 기준을 확인한다. `_within_tolerance(actual, expected, tol=0.05)` 로 상대오차 비교.

## Gotchas (운용상 유의)

- **차트 파싱 실패는 이제 조용히 누락되지 않는다**: `meta.json` 의 `boundary_cases` 에 `reason: "chart parse failed: ..."` 와 `fallback_path` 로 HTML 원본이 남는다. 차트 개수가 기대보다 적으면 `boundary_cases` 를 먼저 확인.
- 한국어 범례(`전체`/`업무 내`/`업무 외`) 순서가 원본과 다를 수 있음 — 정렬 비교 사용.
- 단위 행(`(%)`) 이 헤더로 잘못 들어올 수 있음 → 골든 비교 시 첫 번째 컬럼을 기준값으로 삼음.
- 캡션 매칭은 **같은 페이지의 이전 element** 에서만 수행되므로 앞 페이지 heading 이 끼어드는 현상은 방지됨.
