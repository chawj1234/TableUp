---
name: tableup
description: 문서에서 복잡한 표와 차트 데이터를 CSV로 정확히 추출합니다. 지원 포맷 — PDF, 이미지(JPEG·PNG·BMP·TIFF·HEIC), Office(DOCX·PPTX·XLSX), 한글(HWP·HWPX). 병합 셀, 다단 헤더, 회전·스캔 표, 차트 이미지, HWP 유래 PDF 까지 처리. Upstage Document Parse Enhanced 모드 사용. 사용자가 "표 추출", "PDF 표 뽑아줘", "차트를 데이터로", "엑셀로 뽑아줘", "재무표 수치", "다운로드에 있는 그 보고서 표", "어제 받은 기획서 표", "extract table", "chart to csv" 처럼 파일 경로를 모호하게 언급해도 트리거된다.
---

# TableUp — 문서 표·차트 데이터 추출기

## 지원 파일

Upstage Document Parse가 수용하는 전 포맷:
- **PDF** (스캔 포함)
- **이미지**: JPEG, PNG, BMP, TIFF, HEIC
- **Office**: DOCX, PPTX, XLSX
- **한글**: HWP, HWPX (한국 공공기관·대기업 표준)

파일 크기 50MB, PDF는 100페이지 초과 시 자동 chunk 분할.

## 언제 사용하는가

- 표·차트가 포함된 문서에서 수치 데이터를 추출해야 할 때
- Tabula·Camelot·pdfplumber 가 실패한 복잡한 표 (병합 셀·다단 헤더)
- 차트 이미지를 데이터로 변환 (Claude vision 은 숫자 환각 위험)
- 한국은행·DART·정부·학술 보고서의 표·차트
- HWP·HWPX 공공기관 문서 (Azure/AWS/Google 미지원 영역)

## 실행 단계

1. **파일 경로 확정**: 사용자가 명확한 경로를 줬으면 그대로 사용한다. 모호하면 아래 "파일 경로 해결" 로 이동한다.
2. **API 키 확인**: `UPSTAGE_API_KEY` 환경변수가 없으면 다음과 같이 안내한다:
   > "`UPSTAGE_API_KEY` 환경변수를 설정해주세요. https://console.upstage.ai 에서 발급받을 수 있습니다."
3. **스크립트 실행**:
   ```bash
   python scripts/tableup.py <file_path> [옵션]
   # 또는 부분 파일명 검색:
   python scripts/tableup.py --search "<키워드>"
   ```
   주요 옵션:
   - `--mode {auto,enhanced,standard}`: 처리 모드 (기본 `auto` — 페이지별 자동 분류로 비용 절감)
   - `--search <키워드>`: CWD/Downloads/Desktop/Documents 에서 부분 파일명 매칭
   - `--pages N-M`: PDF만 해당, 특정 페이지 범위
   - `--out <dir>`: 출력 디렉토리 (기본: `.tableup/<파일명_stem>/`)
   - `--no-source`: 원본 페이지 PNG 생략 (PDF만 해당)
   - `--excel`: CSV와 함께 .xlsx 동시 생성
4. stdout 의 요약(표·차트 개수, 파일 목록)을 사용자에게 전달한다.
5. 후속 분석 요청 시 `.tableup/<stem>/index.md` 를 먼저 읽는다.
6. 수치 검증이 필요하면 `.tableup/<stem>/sources/p<N>.png` 참조를 안내한다.

## 파일 경로 해결 (Progressive 전략)

사용자 입력이 모호하면 다음 순서로 해결한다. **각 단계에서 실패 시에만 다음 단계로 넘어간다.**

### 1단계: 기본 경로 검색 (Glob)
부분 파일명 기반 검색:
- `~/Downloads/*<키워드>*.<확장자>`
- `~/Desktop/*<키워드>*.<확장자>`
- CWD `./*<키워드>*.<확장자>`

확장자 후보: pdf, hwp, hwpx, docx, pptx, xlsx, png, jpg, jpeg, tiff, heic

스크립트 내장도 사용 가능: `--search "<키워드>"`

### 2단계: CWD 재귀 검색
1단계에서 0개일 때 현재 프로젝트 전체를 뒤진다:
- Glob: `**/*<키워드>*.<확장자>`

### 3단계: OS 인덱스 (PC 전체)
사용자가 "**PC 전체**", "**어디든**", "**모든 폴더**" 같은 표현을 쓰거나 2단계도 실패했을 때:

- **macOS**: `mdfind -name "<키워드>"` (Spotlight, 밀리초 단위)
- **Linux**: `locate "<키워드>"` (pre-indexed) 또는 `find ~ -iname "*<키워드>*"`

```bash
# macOS 예시
mdfind -name "금융안정" | grep -iE '\.(pdf|hwp|hwpx|docx)$'
```

### 결과 처리 규칙
- **0개**: 명시적 경로를 다시 요청한다.
- **1개**: 확인 없이 바로 실행한다.
- **2~10개**: 번호 리스트로 제시하고 선택을 받는다.
- **10개 초과**: 상위 10개만 보이고 키워드를 더 구체적으로 달라고 요청한다.

### "최근", "방금", "어제" 표현
`~/Downloads/` 내 수정시간 최근 3개를 나열하고 선택을 받는다.

## 출력 구조

```
.tableup/<파일명_stem>/
├── index.md                    # 마스터 맵 (먼저 읽을 것)
├── t00_p3_<slug>.csv           # 실제 데이터 표 (prefix: t)
├── c00_p4_<slug>.csv           # 차트 유래 데이터 (prefix: c)
├── sources/p<N>.png            # 원본 페이지 이미지 (PDF만)
├── meta.json                   # 메타데이터 (각주·SHA256·모델)
└── _raw_response.json          # Upstage 원본 응답 (디버그)
```

여러 파일을 한 CWD에서 처리해도 서로 덮어쓰지 않는다.

## Gotchas

- **Async + enhanced 조합 현재 미지원 (2026-04 기준)**: Upstage async 엔드포인트에서 enhanced/auto 가 internal server error 를 반환하는 서버 측 이슈 확인됨. 본 Skill 은 sync 만 사용하며, sync 의 100페이지 제한은 클라이언트 chunk 분할로 극복.

- **100페이지 초과 PDF 자동 chunk 분할 + 병렬 호출**: 100페이지 단위로 잘라 2-way 병렬로 API 호출, 결과 자동 병합 (Upstage rate limit 안전 범위). 실측 기준 순차 대비 **약 2.6배 빠름**. 페이지당 2~5초.

- **기본 모드는 `auto` (하이브리드)**: Upstage 가 페이지별로 standard/enhanced 를 자동 선택 → 30~60% 비용 절감. 품질 Eval 3/3 PASS 유지. 모든 페이지를 고품질로 강제하려면 `--mode enhanced`.

- **비-PDF 파일은 chunk·page-range·원본 PNG 미지원**: DOCX·HWP·이미지 등은 전체를 한 번에 처리. `--pages`·`--no-source` 는 PDF에만 의미가 있음.

- **차트가 "표"로 오분류 (약 26%)**: Upstage가 차트 시각화를 `category=table` 로 반환하는 경우. 후처리 분류기가 자동 재분류하며 `index.md` "경계 케이스" 섹션에 표시.

- **각주·출처 표 분리**: `| 주:`, `| 자료:` 로 시작하는 항목은 `meta.json` 의 `footnotes` 로 분리.

- **HWP 유래 PDF의 음수 표기**: 한컴 PDF는 음수를 `▲`/`▽` 또는 괄호로 쓰기도 한다. 의심 시 `sources/p<N>.png` 로 원본 확인.

- **macOS 파일명 NFD/NFC**: 한국어 파일명은 NFD(분해)로 저장되는데 사용자 입력은 NFC(조합)다. `--search` 플래그가 자동 정규화하지만 Glob 사용 시엔 유의.

- **Rate limit 2 RPS / 1,200 PPM**: 동시에 여러 파일 처리 금지, 순차 실행.

- **한국어 OCR 95%+ 정확도**: 한글·한자·영문 혼재 문서 모두 정확. 초저해상도 스캔(72dpi 미만)은 경고 후 진행.

## 평가 기준

`evals/` 의 3개 시나리오로 검증. 실행: `python scripts/run_evals.py`
- `scenario-01-complex-table.md` — 병합 셀·다단 헤더
- `scenario-02-chart-to-data.md` — 차트→데이터
- `scenario-03-hwp-derived.md` — HWP 유래 PDF

## 참고

- `references/upstage-api.md` — Upstage Document Parse API 요약
- `references/classification-rules.md` — 표/차트/각주 분류 규칙
- `references/output-schema.md` — `.tableup/` 구조 상세
- `examples/bok-financial-stability.md` — 한국은행 보고서 추출 사례
