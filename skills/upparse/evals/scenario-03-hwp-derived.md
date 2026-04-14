# Eval 3: HWP 에서 변환된 PDF 처리 (한국 특화)

## 목적

한국 공공기관·대기업에서 생산되는 문서는 대부분 **HWP 원본 → PDF 변환** 형태로 유통된다. 이 경우 폰트·문자 인코딩·레이아웃에 특수한 패턴이 발생한다. UpParse 이 일반 PDF 와 동등한 수준으로 처리하는지 검증한다.

## 입력

- **파일**: 한국은행 금융안정보고서 본문 (77 페이지) — `evals/fixtures/bok_financial_stability_main.pdf`
- **URL**: https://www.bok.or.kr/fileSrc/portal/4f1a9e7acede40168fde41d1e555d2f4/5/d9b3fe9fbcec4bee83171092b6da2654.pdf
- **메타데이터**: `Creator: Hwp 2018 10.0.0.10640` + `Producer: Hancom PDF 1.3.0.538`
- **처리 범위**: 전체 페이지 (Eval 1 과 동일 PDF, sync 100page 제한은 chunk 자동 분할로 극복)

## Pass 기준 (run_evals.py `eval_hwp_derived` 에 해당)

| 기준 | 임계값 | 근거 |
|---|---|---|
| 총 element 수 | ≥ 1000 | 사전 측정치(1108) 기반 |
| 원본 표 category | ≥ 20 | 사전 측정치(23) |
| 원본 차트 category | ≥ 130 | 사전 측정치(142) |
| 데이터 자산(tables+charts) | ≥ 150 | 분류 후 meta 기준 |
| 한글 글자 수 | `[가-힣]` 문자 ≥ 10,000 | 인코딩 완전성 |
| 깨진 문자 | `\ufffd` / `�` 0 개 | 인코딩 완전성 |

※ Upstage sync 엔드포인트 응답에는 `status` 필드가 없다. 성공 여부는 HTTP 200 + `elements` 존재로 판단하며, `run_evals.py` 가 이를 전제로 체크한다.

## Baseline (대조군)

| 도구 | HWP 변환 PDF 에서 | 한국어 |
|---|---|---|
| `pdftotext` | 레이아웃 깨짐 | 일부 깨짐 가능 |
| Claude native Read | OK (~15페이지 제한) | OK |
| Tabula | 구조 파괴 | — |
| Azure Document Intelligence | HWP 메타 인식 못함 | OK |
| **UpParse** | **전체 구조 + 차트/표 완전 추출** | **완벽** |

## 측정 (실제 실행 지점)

`scripts/run_evals.py::eval_hwp_derived` 가 `_raw_response.json` 과 `meta.json` 을 열어 위 기준을 확인한다.

### 회귀 방지 체크 (구현됨)

- `meta.boundary_cases[*].reason` 에 `"chart parse failed"` 기록이 있으면 해당 차트들은 `fallback_path` 의 HTML 로 접근 가능. 과거에는 `except Exception: pass` 로 조용히 누락되던 케이스가 이제 전부 보인다.

## Gotchas (운용상 유의)

- HWP 에서 변환된 PDF 는 **텍스트가 outline 으로 변환된 경우**가 있다 — 이 때 OCR 필요. Upstage `ocr=auto` 가 자동 감지하지만 실패 시 `ocr=force` 옵션 안내 필요.
- 한컴 PDF Producer 의 경우 **음수가 삼각형(▲/▽)** 으로 표기되는 경우가 있다 — 숫자 파싱 시 후처리 필요.
- 페이지 번호가 한자(一二三) 로 찍힌 경우도 드물게 있음 — 영향 없음 확인 완료.
- **캡션 페이지 경계**: 같은 페이지 안에서만 이전 element 의 caption/heading1 을 가져오도록 바뀌어, 페이지 경계에서 앞 장 제목이 다음 장 표에 오매칭되던 문제는 해소.
