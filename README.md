# TableUp

**PDF·이미지 문서에서 복잡한 표와 차트 데이터를 CSV로 정확히 추출하는 Claude Code Skill.**

Upstage Document Parse Enhanced 모드를 활용하여 기존 도구(Tabula, Camelot, pdfplumber)가 실패하는 **병합 셀·다단 헤더·회전·스캔·차트 이미지·HWP 변환 PDF**를 처리합니다.

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
Claude: [Upstage Enhanced 호출 → .tableup/ 생성 → 요약 안내]
```

### 페이지 범위 지정
```
You: /tableup ./large.pdf 로 p.12~15 재무제표만 뽑아줘
```

### 뽑은 후 분석
```
You: 방금 뽑은 신용증가율 표에서 전년 대비 변화율 계산해줘
Claude: [.tableup/t00_p3_credit-growth-rate.csv 로드 → pandas 분석]
```

## 출력 구조

```
.tableup/
├── index.md                         # 마스터 맵
├── t00_p3_credit-growth-rate.csv    # 실제 데이터 표 (t 접두)
├── c00_p4_ai-usage-kr-vs-us.csv     # 차트 유래 데이터 (c 접두)
├── sources/p3.png                   # 원본 페이지 이미지 (검증용)
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
python scripts/tableup.py <pdf> [옵션]

--pages N-M        특정 페이지 범위 (예: 12-15)
--no-source        원본 페이지 PNG 생성 생략
--excel            xlsx 동시 생성
--out <dir>        출력 디렉토리 (기본: ./.tableup)
--force            캐시 무시 재호출
```

## 캐싱

`~/.cache/tableup/` 에 SHA256 기준으로 저장됩니다. 같은 PDF 재호출 시 API 비용·시간 0.

## 평가

품질 증명용 3개 시나리오:
- `evals/scenario-01-complex-table.md` — 병합 셀·다단 헤더
- `evals/scenario-02-chart-to-data.md` — 차트→데이터
- `evals/scenario-03-hwp-derived.md` — HWP 변환 PDF

## 제약 사항

- 파일 크기: 최대 50MB
- 페이지 수: 최대 100페이지 (async 기준 1,000페이지까지 확장 예정)
- API 비용: Enhanced mode 기준 페이지당 약 $0.03

## 라이선스

MIT

## 감사의 말

- [Upstage](https://upstage.ai) — Document Parse Enhanced mode
- [Anthropic](https://anthropic.com) — Claude Code Skills 체계
- Upstage Edu Ambassador 2기 미션으로 제작됨
