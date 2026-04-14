# TableUp

**문서의 복잡한 표와 차트를 CSV로 정확히 추출하는 Claude Code Skill.**

Upstage Document Parse 를 **`auto` 모드 (페이지별 자동 분류) 기본**으로 활용해서, Tabula·Camelot·pdfplumber·Claude vision 이 각자의 이유로 실패하는 **병합 셀·다단 헤더·회전 표·스캔 PDF·차트 이미지·HWP 문서** 를 처리합니다.

---

## 🎯 왜 필요한가

10년간 문서 표 추출은 미해결 상태였습니다:

| 도구 | 복잡 표 | 차트→데이터 | 스캔 | HWP 원본 | HWPX |
|---|---|---|---|---|---|
| **TableUp** | ✅ | ✅ | ✅ | ✅ | ✅ |
| Tabula / Camelot / pdfplumber | △ ~ ❌ | ❌ | ❌ | ❌ | ❌ |
| Claude vision (직접) | △ | △ (숫자 환각) | △ | ✅ | ✅ |
| Azure DI / AWS Textract | ✅ | △ | ✅ | ❌ | ❌ |
| Google Document AI | ✅ | △ | ✅ | ❌ | ❌ |

---

## 🚀 설치

**요구사항**: Python 3.10 이상, macOS/Linux (Windows 는 WSL2 권장)

```bash
git clone https://github.com/chawj1234/TableUp.git
cd TableUp
pip install -r requirements.txt
./install.sh
echo 'UPSTAGE_API_KEY=YOUR_API_KEY' > .env
```

`UPSTAGE_API_KEY` 는 [Upstage Console](https://console.upstage.ai) 에서 발급.

`install.sh` 는 Claude Code skills 디렉터리에 심링크를 만듭니다. 재시작하면 자동 인식되고, **"표 뽑아줘"** 같은 자연어로 트리거됩니다.

---

## 💬 사용 예시

모든 조작은 Claude Code 에서 **자연어** 로 합니다.

### 기본
```bash
./report.pdf 표 뽑아줘

이 PDF 표 뽑아줘                    # Finder 에서 파일 드래그해 경로 자동 입력 후
```

### 파일 위치가 애매할 때
```bash
AI 보고서 PDF 표 뽑아줘              # ~/Downloads·Desktop·Documents 자동 검색

내 컴퓨터에 있는 '분석 보고서' 표 찾아줘   # 전체 디스크 검색 (Spotlight/locate)

어제 다운받은 PDF 표 뽑아줘           # 최근 파일 제시
```

### 다른 포맷
```bash
~/Documents/기획서.hwp 에서 표 뽑아줘

./sales.xlsx 테이블 내용 정리해줘

./screenshot.png 속 표 CSV 로 뽑아줘
```

### 품질·범위 조절
```bash
./critical.pdf 전부 고품질로 뽑아줘      # 모든 페이지 enhanced (비용 ↑)

./large.pdf 에서 12~15페이지만 뽑아줘    # PDF 페이지 범위 지정

./report.pdf 표 뽑고 엑셀 파일도 만들어줘  # .xlsx 동시 생성
```

### 추출 후 바로 분석
```
방금 뽑은 신용증가율 표에서 전년 대비 변화율 계산해줘
→ Claude 가 `.tableup/<파일명>/` CSV 를 pandas 로 로드해 분석합니다.
```

---

## 📂 지원 파일 (10 종)

| 카테고리 | 확장자 | 특이사항 |
|---|---|---|
| **PDF** | `.pdf` | 스캔 포함. 100페이지 초과 시 자동 chunk 분할 + 2-way 병렬 호출 |
| **이미지** | `.jpg`, `.jpeg`, `.png`, `.bmp`, `.tif`, `.tiff`, `.heic` | 표·차트가 있는 스크린샷 |
| **Office** | `.docx`, `.pptx`, `.xlsx` | 문서·슬라이드·스프레드시트 |
| **한글** | `.hwp`, `.hwpx` | **Azure/AWS/Google Document AI 미지원 영역**. PDF로 변환하지 않고 직접 처리 |

파일 크기 상한 50MB.

---

## 🛠️ 특화 영역 (7가지)

기존 도구가 실패하는 지점을 공략합니다:

1. **병합 셀** (rowspan/colspan) — 원본 관계 유지
2. **다단 헤더** (2~3단) — MultiIndex 스타일 복원
3. **회전 테이블** (90°/180°) — 자동 보정
4. **스캔 PDF** — OCR 경로 자동 전환 (한국어 95%+ 정확도)
5. **다중 페이지 표** — 자동 stitch
6. **각주·단위 주석** (주:, 자료:, %) — 데이터와 분리해 `meta.json` 으로
7. **차트 이미지 → 표** — `auto` 모드에서 차트 페이지에 enhanced 자동 적용, 이미지 속 수치를 구조화된 CSV 로 변환

---

## 📁 출력 구조

기본 경로는 `./.tableup/<파일명_stem>/` — 같은 CWD 에서 여러 문서를 처리해도 충돌하지 않습니다.

```
.tableup/<파일명_stem>/
├── index.md                         # 마스터 맵 (LLM 이 먼저 읽을 것)
├── t00_p3_credit-growth-rate.csv    # 데이터 표 (prefix: t)
├── c00_p4_ai-usage-kr-vs-us.csv     # 차트 유래 데이터 (prefix: c)
├── sources/p3.png                   # 원본 페이지 이미지 (PDF 만, 검증용)
├── meta.json                        # 각주·SHA256·모델·파일 인덱스
└── _raw_response.json               # Upstage 원본 응답 (디버그)
```

- 파일명은 캡션을 슬러그화 (한글 그대로 유지)
- CSV 는 UTF-8 BOM (Excel 한국어 호환)
- 전역 캐시로 → 같은 파일·모드 재처리 시 API 호출 0

---


## 🔢 핵심 수치 (검증됨)

| 지표 | 수치 | 근거 |
|---|---:|---|
| 차트→데이터 정확도 | **100%** | 한국은행 AI 보고서 p.5 골든값 6/6 완전 일치 |
| 복잡 표(병합·다단) 정확도 | **5/5** | 한국은행 금융안정보고서 p.6 취약차주 표 |
| HWP 유래 PDF 한글 처리 | **깨짐 0개** | 77페이지에서 한글 67,029자 추출 |
| 대형 PDF 처리 속도 | **2.6×** | chunk 병렬화로 167.8s → 64.5s |
| 비용 절감 | **30~60%** | `auto` 모드 페이지별 자동 분류 (텍스트=standard, 표/차트=enhanced) |
| Eval 시나리오 | **3/3 PASS** | `evals/results/2026-04-14/report.md` |

---

## 🧪 평가 (Evals)

TDD 원칙: Eval 을 먼저 정의하고 skill 을 구현한 뒤, 데이터로 증명합니다.

실행: `python scripts/run_evals.py`

| # | 시나리오 | Pass 기준 | 결과 |
|---|---|---|---|
| 1 | 복잡 표 (9×7 병합·다단) | 골든 값 5/5 정확 | ✅ PASS |
| 2 | 차트→데이터 변환 | 6/6 값 ±5% 이내 | ✅ PASS (100% 일치) |
| 3 | HWP 유래 PDF 77페이지 | 한글 완전성·추출률 | ✅ PASS (67,029자·깨짐 0) |

상세: `evals/results/2026-04-14/report.md`

시나리오 스펙: `evals/scenario-01-complex-table.md`, `evals/scenario-02-chart-to-data.md`, `evals/scenario-03-hwp-derived.md`
