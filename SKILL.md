---
name: tableup
description: PDF 또는 이미지 문서에서 복잡한 표와 차트 데이터를 CSV로 추출합니다. 병합 셀(rowspan/colspan), 다단 헤더, 회전·스캔 표, 다중 페이지 표, 차트 이미지를 데이터로 변환합니다. Upstage Document Parse Enhanced 모드를 사용합니다. "표 추출", "PDF 표 뽑아줘", "차트를 데이터로", "재무표 수치", "보고서 표 분석", "extract table", "chart to csv", "PDF 표를 엑셀로" 등의 요청에 사용합니다.
allowed-tools: Bash(python *), Read, Write, Glob
---

# TableUp — PDF 표/차트 데이터 추출기

## 언제 이 Skill을 사용하는가

- 표·차트가 포함된 PDF·이미지 문서에서 수치 데이터를 추출해야 할 때
- Tabula, Camelot, pdfplumber가 실패한 복잡한 표
- 차트 이미지를 데이터로 변환해야 할 때 (Claude vision은 숫자를 환각함)
- 한국은행·DART·정부·학술 보고서의 표
- HWP에서 변환된 PDF (공공기관·기업 문서)

## 실행 단계

1. 사용자에게서 **PDF 경로**와 **페이지 범위(선택)** 를 확인한다. 모호하면 질문한다.
2. `UPSTAGE_API_KEY` 환경변수를 확인한다. 없으면 다음과 같이 안내한다:
   > "`UPSTAGE_API_KEY` 환경변수를 설정해주세요. https://console.upstage.ai 에서 발급받을 수 있습니다."
3. 스크립트를 실행한다:
   ```bash
   python scripts/tableup.py <pdf_path> [옵션]
   ```
   옵션:
   - `--pages N-M`: 특정 페이지 범위만 처리
   - `--no-source`: 원본 페이지 PNG 생성 생략 (디스크 절약)
   - `--excel`: CSV와 함께 `.xlsx` 동시 생성
4. 스크립트 stdout의 **요약 섹션**을 사용자에게 전달한다 (표·차트 개수, 파일 목록).
5. 후속 분석 요청이 오면 `.tableup/index.md` 를 먼저 읽고, 필요한 CSV를 pandas로 로드한다.
6. 사용자가 수치의 정확성을 검증하고 싶어하면 `.tableup/sources/p<N>.png` 를 참조하도록 안내한다.

## 출력 구조

```
.tableup/
├── index.md                       # 마스터 맵 (추출된 모든 요소 개요)
├── t00_p3_<의미기반이름>.csv        # 실제 데이터 표 (prefix: t)
├── c00_p4_<의미기반이름>.csv        # 차트 유래 데이터 (prefix: c)
├── sources/p3.png                 # 원본 페이지 이미지 (검증용)
└── meta.json                      # 메타데이터 (각주·출처·모델 버전·SHA256)
```

## Gotchas

- **차트가 "표"로 오분류될 수 있음 (약 26%)**: Upstage API가 차트 시각화를 `category=table`로 반환하는 경우가 있다. 스크립트는 `<br>` 패턴과 축값 패턴으로 자동 재분류하지만, 모호한 경우 `index.md` "경계 케이스" 섹션에 표시된다.

- **각주·출처 표 분리**: `| 주:`, `| 자료:` 로 시작하는 항목은 실제 표가 아니다. 스크립트가 `meta.json` 의 `footnotes` 배열로 분리 저장한다.

- **HWP 유래 PDF의 음수 표기**: 한컴 PDF는 음수를 `▲` 또는 `▽`, 또는 괄호(`(123)`)로 표기하는 경우가 있다. 스크립트가 기본 변환하지만, 의심 시 `sources/p<N>.png` 로 검증하도록 안내한다.

- **Enhanced mode는 sync 엔드포인트 전용 (2026-04 기준)**: 본 Skill은 sync API 를 사용한다. async+enhanced 조합에 Upstage 서버 측 issue 가 있어 사용하지 않는다. 추후 해결되면 upstage_async.py 로 전환 가능.

- **100페이지 초과 PDF**: sync 엔드포인트는 100페이지 제한이 있다. 스크립트가 자동으로 100페이지 단위 chunk 로 분할해 순차 호출한다. 페이지 번호는 병합 시 올바르게 복원된다.

- **Enhanced mode 고정 사용**: 본 Skill은 품질을 위해 항상 `mode=enhanced` 를 사용한다 (비용은 standard 대비 높음). 선택된 설계이므로 사용자에게 재확인 불필요.

- **페이지당 약 2~5초**: 100페이지 PDF는 5~10분 소요된다. 긴 처리 시간을 사용자에게 미리 알려라. `--pages` 로 범위 지정 시 비례하여 단축된다.

- **Rate limit 2 RPS / 1,200 PPM**: 동시에 여러 PDF 처리 금지. 순차 실행.

- **한국어 OCR 95%+ 정확도**: 한글·한자·영문 혼재 문서 모두 정확. 단, 초저해상도 스캔(72dpi 미만)은 경고 후 진행.

## 평가 기준 (품질 점검)

이 Skill의 실제 성능은 `evals/` 디렉토리의 3개 시나리오로 검증한다:
- `scenario-01-complex-table.md` — 병합 셀·다단 헤더
- `scenario-02-chart-to-data.md` — 차트→데이터
- `scenario-03-hwp-derived.md` — HWP 변환 PDF

실행: `python scripts/run_evals.py`

## 참고

- `references/upstage-api.md` — Upstage Document Parse API 요약
- `references/classification-rules.md` — 표/차트/각주 분류 규칙
- `references/output-schema.md` — `.tableup/` 구조 상세
- `examples/bok-financial-stability.md` — 한국은행 보고서 추출 실제 사례
