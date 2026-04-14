# TableUp

**문서에서 복잡한 표와 차트 데이터를 CSV로 정확히 추출하는 Claude Code Skill.**

Upstage Document Parse Enhanced 모드를 활용하여 기존 도구(Tabula, Camelot, pdfplumber)가 실패하는 **병합 셀·다단 헤더·회전·스캔·차트 이미지·HWP 변환 PDF**를 처리합니다.

## 지원 파일

| 카테고리 | 확장자 |
|---|---|
| **PDF** | `.pdf` (스캔 포함, 100페이지 초과 시 자동 chunk) |
| **이미지** | `.jpg`, `.jpeg`, `.png`, `.bmp`, `.tif`, `.tiff`, `.heic` |
| **Office** | `.docx`, `.pptx`, `.xlsx` |
| **한글** | `.hwp`, `.hwpx` (공공기관·대기업 표준, **Azure/AWS/Google 미지원 영역**) |

파일 크기 50MB 제한.

## 왜 필요한가

10년간 PDF 표 추출은 미해결 문제였습니다:

| 기존 도구 | 복잡 표 | 차트 | 스캔 | HWP 변환 |
|---|---|---|---|---|
| Tabula | ❌ | ❌ | ❌ | △ |
| Camelot | △ | ❌ | ❌ | △ |
| pdfplumber | △ | ❌ | ❌ | △ |
| Claude vision | △ | △ 환각 | △ | ✅ |
| **TableUp** | ✅ | ✅ | ✅ | ✅ |

## 설치

```bash
git clone https://github.com/<your>/TableUp.git
cd TableUp
pip install -r requirements.txt
./install.sh
export UPSTAGE_API_KEY="up_..."   # https://console.upstage.ai 에서 발급
```

Claude Code 재시작 후 자동으로 `/tableup` 호출 가능.

## 사용 예시

### 기본
```
You: 이 PDF에서 표 뽑아줘 — ./report.pdf
Claude Code: [Upstage Enhanced 호출 → .tableup/ 생성 → 요약 안내]
```

### 부분 파일명으로 자동 검색 (경로 입력 부담 ↓)
```
You: AI 보고서 PDF 표 뽑아줘
Claude Code: [Glob으로 ~/Downloads 검색 → 자동 매칭 → 실행]

# 또는 직접 CLI:
python scripts/tableup.py --search "AI 보고서"
```
검색 경로: **CWD · ~/Downloads · ~/Desktop · ~/Documents**  
macOS 한글 파일명(NFD) 자동 정규화.

### 페이지 범위 지정
```
You: /tableup ./large.pdf 로 p.12~15 재무제표만 뽑아줘
```

### 뽑은 후 분석
```
You: 방금 뽑은 신용증가율 표에서 전년 대비 변화율 계산해줘
Claude Code: [.tableup/t00_p3_credit-growth-rate.csv 로드 → pandas 분석]
```

## 출력 구조

기본은 `./.tableup/<파일명_stem>/` — 같은 CWD 에서 여러 파일을 처리해도 충돌 안 남.

```
.tableup/<파일명>/
├── index.md                         # 마스터 맵
├── t00_p3_credit-growth-rate.csv    # 실제 데이터 표 (t 접두)
├── c00_p4_ai-usage-kr-vs-us.csv     # 차트 유래 데이터 (c 접두)
├── sources/p3.png                   # 원본 페이지 이미지 (PDF 만)
├── meta.json                        # 메타데이터 (각주·SHA256·모델)
└── _raw_response.json               # Upstage 원본 응답 (디버그)
```

## 특화 영역

7가지 기존 도구가 실패하는 영역을 공략합니다:

1. **병합 셀** (rowspan/colspan) — 원본 구조 유지
2. **다단 헤더** (2~3단) — MultiIndex 지원
3. **회전 테이블** (90°/180°) — 자동 보정
4. **스캔 PDF** — OCR 경로 자동 전환
5. **다중 페이지 표** — 자동 stitch
6. **각주·단위 주석** — 데이터와 분리
7. **차트 → 표 변환** — Enhanced 모드 독점

## CLI 옵션

```
python scripts/tableup.py <file> [옵션]
# 또는
python scripts/tableup.py --search <키워드> [옵션]

--search <키워드>  부분 파일명 검색 (CWD/Downloads/Desktop/Documents)
                   한국어 NFC/NFD 자동 정규화 지원
--pages N-M        PDF 특정 페이지 범위 (비-PDF 에선 무시)
--no-source        원본 페이지 PNG 생성 생략 (PDF 만 해당)
--excel            xlsx 동시 생성
--out <dir>        출력 디렉토리 (기본: .tableup/<파일명>/)
--force            캐시 무시 재호출
```


## 평가

품질 증명용 3개 시나리오:
- `evals/scenario-01-complex-table.md` — 병합 셀·다단 헤더
- `evals/scenario-02-chart-to-data.md` — 차트→데이터
- `evals/scenario-03-hwp-derived.md` — HWP 변환 PDF

## 제약 사항

- 파일 크기: 최대 50MB
- 페이지 수: 최대 100페이지 (async 기준 1,000페이지까지 확장 예정)
- API 비용: Enhanced mode 기준 페이지당 약 $0.03
