#!/usr/bin/env python3
"""TableUp 3개 eval 시나리오 자동 실행 & 결과 보고서 생성.

Usage:
    python scripts/run_evals.py              # 전부
    python scripts/run_evals.py --only 1     # 시나리오 1만
"""
from __future__ import annotations

import argparse
import datetime
import io
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).parent.parent
FIXTURES = ROOT / "evals" / "fixtures"
RESULTS = ROOT / "evals" / "results"
TABLEUP = ROOT / "scripts" / "tableup.py"

# -------- Fixtures --------

BOK_AI_PDF = Path("/Users/chawj/Downloads/AI의 빠른 확산과 생산성 효과-한국은행.pdf")
BOK_MAIN_PDF = Path("/tmp/tableup_test2/main.pdf")  # 금융안정보고서 본문
BOK_MAIN_URL = (
    "https://www.bok.or.kr/fileSrc/portal/"
    "4f1a9e7acede40168fde41d1e555d2f4/5/d9b3fe9fbcec4bee83171092b6da2654.pdf"
)

# -------- 결과 구조 --------


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class EvalResult:
    name: str
    scenario: str
    output_dir: Path
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append(Check(name, passed, detail))


# -------- 공용 헬퍼 --------


def ensure_pdf(path: Path, url: str | None = None) -> Path:
    if path.exists():
        return path
    if not url:
        raise SystemExit(f"PDF 없음: {path}")
    import urllib.request

    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"  PDF 다운로드 중: {url}")
    req = urllib.request.Request(url, headers={"Referer": "https://www.bok.or.kr/"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        path.write_bytes(resp.read())
    return path


def run_tableup(pdf: Path, out_dir: Path, extra_args: list[str] | None = None) -> None:
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(TABLEUP), str(pdf), "--out", str(out_dir), "--no-source"]
    if extra_args:
        cmd += extra_args
    print(f"  실행: tableup.py --out {out_dir.name}")
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if res.returncode != 0:
        print(res.stdout)
        print(res.stderr, file=sys.stderr)
        raise SystemExit(f"tableup 실행 실패 (exit {res.returncode})")


def load_meta(out_dir: Path) -> dict:
    return json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))


def load_raw(out_dir: Path) -> dict:
    return json.loads((out_dir / "_raw_response.json").read_text(encoding="utf-8"))


# -------- Eval 1: 복잡 표 --------


def eval_complex_table() -> EvalResult:
    print("\n▶ Eval 1: 복잡 표 추출 (BoK 금융안정보고서 p.6 취약차주 표)")
    pdf = ensure_pdf(BOK_MAIN_PDF, BOK_MAIN_URL)
    out_dir = RESULTS / "e01_complex_table"
    # 페이지 범위 대신 전체 PDF (캐시 공유하기 위해)
    run_tableup(pdf, out_dir)

    result = EvalResult("Eval 1: 복잡 표 추출", "scenario-01-complex-table.md", out_dir)
    meta = load_meta(out_dir)

    # p.6 에 있는 표만 필터
    p6_tables = [f for f in meta["files"] if f["type"] == "table" and f["page"] == 6]
    result.add("p.6 표 추출", len(p6_tables) >= 1, f"p6 tables={len(p6_tables)}")
    if not p6_tables:
        return result

    # 가장 큰 표 선택 (취약차주 다단 헤더 표)
    import pandas as pd

    best = max(p6_tables, key=lambda f: f["rows"] * f["cols"])
    df = pd.read_csv(out_dir / best["path"])
    result.add(
        "다행·다열 표",
        df.shape[0] >= 5 and df.shape[1] >= 5,
        f"shape={df.shape}",
    )

    # 골든 값 중 몇 개라도 발견되는지 (정확 매칭은 표 구조에 따라 달라질 수 있으므로 값 단위로 검사)
    flat_values = [str(v) for v in df.values.flatten()]
    flat_joined = " ".join(flat_values)
    goldens = [
        ("취약차주 차주수 23년=6.6", "6.6"),
        ("취약차주 대출금액 24년=5.3", "5.3"),
        ("신용등급 고 25년3/4=79.5", "79.5"),
        ("소득수준 고 25년1/4=63.5", "63.5"),
        ("신용등급 중 23년=18.5", "18.5"),
    ]
    hits = sum(1 for _, v in goldens if v in flat_joined)
    result.add(
        f"골든 값 {hits}/5 이상 발견",
        hits >= 4,
        f"{hits}/5 hit",
    )

    # 한글 헤더/셀 존재
    korean_in_cols = any(re.search(r"[가-힣]", str(c)) for c in df.columns)
    korean_in_cells = any(re.search(r"[가-힣]", str(v)) for v in flat_values)
    result.add("한글 헤더/셀 보존", korean_in_cols or korean_in_cells, "")
    return result


# -------- Eval 2: 차트 → 데이터 --------


def eval_chart_to_data() -> EvalResult:
    print("\n▶ Eval 2: 차트→데이터 (BoK AI 보고서 p.5)")
    out_dir = RESULTS / "e02_chart_to_data"
    run_tableup(BOK_AI_PDF, out_dir)

    result = EvalResult("Eval 2: 차트→데이터", "scenario-02-chart-to-data.md", out_dir)
    meta = load_meta(out_dir)

    charts = [f for f in meta["files"] if f["type"] == "chart"]
    result.add("차트 추출 개수", len(charts) >= 30, f"charts={len(charts)}")

    # p.5 차트들 중 한국 vs 미국 찾기
    import pandas as pd

    p5_charts = [c for c in charts if c["page"] == 5]
    if not p5_charts:
        result.add("p.5 차트 발견", False, "none")
        return result
    result.add("p.5 차트 발견", True, f"{len(p5_charts)}개")

    # 골든: 전체 한국 63.5, 미국 39.6 등
    golden = {
        ("전체", "한국"): 63.5,
        ("전체", "미국"): 39.6,
        ("업무 내", "한국"): 51.8,
        ("업무 내", "미국"): 26.5,
        ("업무 외", "한국"): 60.1,
        ("업무 외", "미국"): 33.7,
    }

    # 한국 vs 미국 차트 찾기 (열 이름 기준)
    best_match = None
    for c in p5_charts:
        df = pd.read_csv(out_dir / c["path"])
        if "한국" in df.columns and "미국" in df.columns:
            best_match = df
            break

    if best_match is None:
        result.add("한국 vs 미국 차트 매칭", False, "")
        return result
    result.add("한국 vs 미국 차트 매칭", True, "")

    first_col = best_match.columns[0]
    hits = 0
    total = len(golden)
    for (cat, country), expected in golden.items():
        row = best_match.loc[best_match[first_col] == cat]
        if row.empty:
            continue
        actual = row.iloc[0][country]
        try:
            actual_f = float(actual)
        except (TypeError, ValueError):
            continue
        if abs(actual_f - expected) / expected <= 0.05:
            hits += 1

    result.add(f"골든 값 정확도 {hits}/{total}", hits == total, f"{hits}/{total} within ±5%")
    return result


# -------- Eval 3: HWP 유래 PDF --------


def eval_hwp_derived() -> EvalResult:
    print("\n▶ Eval 3: HWP 유래 PDF 전체 처리 (BoK 금융안정보고서 77p)")
    pdf = ensure_pdf(BOK_MAIN_PDF, BOK_MAIN_URL)
    out_dir = RESULTS / "e03_hwp_derived"
    run_tableup(pdf, out_dir)

    result = EvalResult("Eval 3: HWP 유래 PDF", "scenario-03-hwp-derived.md", out_dir)
    meta = load_meta(out_dir)
    raw = load_raw(out_dir)

    elements = raw["elements"]
    result.add("element 1000개 이상", len(elements) >= 1000, f"elements={len(elements)}")

    # Upstage 원본 카테고리 집계 (분류 전)
    raw_tables = sum(1 for e in elements if e.get("category") == "table")
    raw_charts = sum(1 for e in elements if e.get("category") == "chart")
    result.add("원본 표 20개 이상", raw_tables >= 20, f"raw tables={raw_tables}")
    result.add("원본 차트 130개 이상", raw_charts >= 130, f"raw charts={raw_charts}")

    # 분류 후 데이터 자산 총량
    meta_total_data = meta["counts"]["tables"] + meta["counts"]["charts"]
    result.add(
        "데이터 자산 150개 이상",
        meta_total_data >= 150,
        f"tables+charts={meta_total_data} (tables={meta['counts']['tables']}, charts={meta['counts']['charts']})",
    )

    # 한국어 완전성
    all_md = raw.get("content", {}).get("markdown", "")
    korean_chars = len(re.findall(r"[가-힣]", all_md))
    broken = all_md.count("\ufffd") + all_md.count("�")
    result.add("한글 10,000자 이상", korean_chars >= 10000, f"korean={korean_chars}")
    result.add("깨진 문자 0개", broken == 0, f"broken={broken}")
    return result


# -------- 보고서 --------


def write_report(results: list[EvalResult], out: Path) -> None:
    lines = [
        f"# TableUp Eval 결과 ({datetime.date.today()})",
        "",
        f"- 총 시나리오: {len(results)}",
        f"- Pass: {sum(1 for r in results if r.passed)}",
        f"- Fail: {sum(1 for r in results if not r.passed)}",
        "",
    ]
    for r in results:
        mark = "✅ PASS" if r.passed else "❌ FAIL"
        lines += [
            f"## {mark} — {r.name}",
            "",
            f"- 시나리오 문서: `{r.scenario}`",
            f"- 출력: `{r.output_dir.relative_to(ROOT)}/`",
            "",
            "| 검증 항목 | 결과 | 상세 |",
            "|---|---|---|",
        ]
        for c in r.checks:
            m = "✅" if c.passed else "❌"
            lines.append(f"| {c.name} | {m} | {c.detail} |")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n📝 보고서: {out}")


# -------- main --------


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, help="특정 시나리오만 실행 (1/2/3)")
    args = ap.parse_args()

    FIXTURES.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()
    report_dir = RESULTS / today
    report_dir.mkdir(parents=True, exist_ok=True)

    all_evals = [eval_complex_table, eval_chart_to_data, eval_hwp_derived]
    if args.only:
        all_evals = [all_evals[args.only - 1]]

    results = [fn() for fn in all_evals]
    write_report(results, report_dir / "report.md")

    n_fail = sum(1 for r in results if not r.passed)
    print(f"\n총 {len(results)}개 중 {len(results) - n_fail} PASS, {n_fail} FAIL")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
