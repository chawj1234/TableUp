# TableUp

**문서의 복잡한 표와 차트를 CSV로 정확히 추출하는 Claude Code Skill.**

Upstage Document Parse Enhanced 모드를 활용해서, Tabula·Camelot·pdfplumber·Claude vision이 각자의 이유로 실패하는 **병합 셀·다단 헤더·회전 표·스캔 PDF·차트 이미지·HWP 문서** 를 처리합니다.

---

## 🔢 핵심 수치 (검증됨)

| 지표 | 수치 | 근거 |
|---|---:|---|
| 차트→데이터 정확도 | **100%** | 한국은행 AI 보고서 p.5 골든값 6/6 완전 일치 |
| 복잡 표(병합·다단) 정확도 | **5/5** | BoK 금융안정보고서 p.6 취약차주 표 |
| HWP 유래 PDF 한글 처리 | **깨짐 0개** | 77페이지에서 한글 67,029자 추출 |
| 대형 PDF 처리 속도 | **2.6×** | chunk 병렬화로 167.8s → 64.5s |
| 비용 절감 | **30~60%** | `mode=auto` 페이지별 자동 분류 |
| Eval 시나리오 | **3/3 PASS** | [결과 보고서](evals/results/2026-04-14/report.md) |

---

## 📂 지원 파일 (10 종)

| 카테고리 | 확장자 | 특이 |
|---|---|---|
| **PDF** | `.pdf` | 스캔 포함, 100페이지 초과 시 자동 chunk 분할·병렬 호출 |
| **이미지** | `.jpg`, `.jpeg`, `.png`, `.bmp`, `.tif`, `.tiff`, `.heic` | 표·차트가 있는 스크린샷 |
| **Office** | `.docx`, `.pptx`, `.xlsx` | 문서·슬라이드·스프레드시트 |
| **한글** | `.hwp`, `.hwpx` | **Azure/AWS/Google 미지원 영역** |

50MB 상한. HWP 원본을 PDF로 변환하지 않고 **직접** 처리합니다.

---

## 🎯 왜 필요한가

10년간 문서 표 추출은 미해결이었습니다:

| 도구 | 복잡 표 | 차트→데이터 | 스캔 | HWP 원본 | HWPX |
|---|---|---|---|---|---|
| Tabula / Camelot / pdfplumber | △ ~ ❌ | ❌ | ❌ | ❌ | ❌ |
| Claude vision (직접) | △ | △ 숫자 환각 | △ | ✅ | ✅ |
| Azure DI / AWS Textract | ✅ | △ | ✅ | ❌ | ❌ |
| Google Document AI | ✅ | △ | ✅ | ❌ | ❌ |
| **TableUp** | ✅ | ✅ | ✅ | ✅ | ✅ |

---

## 🚀 설치

```bash
git clone https://github.com/chawj1234/TableUp.git
cd TableUp
pip install -r requirements.txt
./install.sh
export UPSTAGE_API_KEY="up_..."   # https://console.upstage.ai 에서 발급
```

`install.sh`는 `~/.claude/skills/tableup/`에 심링크를 만듭니다. Claude Code를 재시작하면 자동 인식되고, **"표 뽑아줘"** 같은 자연어로 트리거됩니다.

---

## 💬 사용 예시

### 기본 (자연어)
```
You: 이 PDF에서 표 뽑아줘 — ./report.pdf
Claude Code: [Upstage auto 호출 → .tableup/report/ 생성 → 요약 안내]
```

### 부분 파일명 자동 검색 (경로 입력 부담 ↓)
```
You: AI 보고서 PDF 표 뽑아줘
Claude Code: [~/Downloads 자동 검색 → 매칭 → 실행]

# 또는 CLI:
python scripts/tableup.py --search "AI 보고서"
```

검색 경로: **CWD · ~/Downloads · ~/Desktop · ~/Documents**. macOS 한국어 파일명(NFD/NFC) 자동 정규화.

### "PC 전체" 검색
```
You: 내 컴퓨터 어디든 있는 '금융안정' PDF 찾아서 표 뽑아줘
Claude Code: [macOS mdfind / Linux locate 사용 → Spotlight 인덱스]
```

### HWP · Office · 이미지
```
You: 이 한글 기획서의 표 뽑아줘 — ~/Documents/기획서.hwp
You: 이 Excel 피벗 테이블 정리해줘 — ./sales.xlsx
You: 이 스크린샷 속 표 CSV로 뽑아줘 — ./screenshot.png
```

### 페이지 범위 지정 (PDF 만)
```
You: /tableup ./large.pdf 로 p.12~15 재무제표만 뽑아줘
```

### 뽑은 후 분석
```
You: 방금 뽑은 신용증가율 표에서 전년 대비 변화율 계산해줘
Claude Code: [.tableup/<파일명>/t00_p3_*.csv 로드 → pandas 분석]
```

---

## 📁 출력 구조

기본 경로는 `./.tableup/<파일명_stem>/` — 같은 CWD 에서 여러 문서를 처리해도 충돌하지 않습니다.

```
.tableup/<파일명>/
├── index.md                         # 마스터 맵 (LLM이 먼저 읽을 것)
├── t00_p3_credit-growth-rate.csv    # 데이터 표 (prefix: t)
├── c00_p4_ai-usage-kr-vs-us.csv     # 차트 유래 데이터 (prefix: c)
├── sources/p3.png                   # 원본 페이지 이미지 (PDF 만, 검증용)
├── meta.json                        # 각주·SHA256·모델·파일 인덱스
└── _raw_response.json               # Upstage 원본 응답 (디버그)
```

- 파일명은 캡션을 슬러그화 (한글 유지)
- CSV 는 UTF-8 BOM (Excel 한국어 호환)
- 캐시는 `~/.cache/tableup/<sha256>_<mode>.json` 에 저장 → 같은 파일 재처리 시 API 호출 0

---

## 🛠️ 특화 영역

기존 도구가 실패하는 7 가지 문제를 정확히 공략:

1. **병합 셀** (rowspan/colspan) — 원본 관계 유지
2. **다단 헤더** (2~3단) — MultiIndex 스타일 복원
3. **회전 테이블** (90°/180°) — 자동 보정
4. **스캔 PDF** — OCR 경로 자동 전환 (한국어 95%+ 정확도)
5. **다중 페이지 표** — 자동 stitch
6. **각주·단위 주석** (주:, 자료:, %) — 데이터와 분리
7. **차트 이미지 → 표** — Enhanced 모드의 독점 영역


---

## 🧪 평가 (Evals)

실행: `python scripts/run_evals.py`

| # | 시나리오 | Pass 기준 | 결과 |
|---|---|---|---|
| 1 | 복잡 표 (9×7 병합·다단) | 골든 값 5/5 정확 | ✅ PASS |
| 2 | 차트→데이터 변환 | 6/6 값 ±5% 이내 | ✅ PASS (100% 일치) |
| 3 | HWP 유래 PDF 77페이지 | 한글 완전성·추출률 | ✅ PASS (67,029자·깨짐 0) |



---

## ⚠️ 제약 사항

- **파일 크기**: 최대 50MB
- **페이지 수**: 100페이지 초과 시 자동 chunk 분할 + 2-way 병렬 호출 (사실상 무제한, 속도는 순차 대비 **~2.6× 개선**)
- **API 비용**: standard $0.01/p · enhanced $0.03/p. 기본 `auto` 모드가 페이지별 자동 선택으로 **30~60% 절감** (신규 가입 $10 무료 크레딧)
- **Rate limit**: 2 RPS, 1,200 PPM (여러 파일 동시 처리 금지 — 스크립트가 내부적으로 준수)


