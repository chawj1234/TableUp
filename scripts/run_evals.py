#!/usr/bin/env python3
"""TableUp 3개 eval 시나리오 자동 실행 & 결과 보고서 생성.

Usage:
    python scripts/run_evals.py              # 전부
    python scripts/run_evals.py --only 1     # 시나리오 1만

환경변수 (옵션):
    TABLEUP_EVAL_BOK_AI     BoK AI 보고서 PDF 경로 (기본: evals/fixtures/bok_ai_report.pdf)
    TABLEUP_EVAL_BOK_MAIN   BoK 금융안정보고서 PDF 경로 (기본: evals/fixtures/bok_financial_stability_main.pdf)

fixtures PDF 가 없으면 BoK 공식 URL 에서 자동 다운로드합니다.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
FIXTURES = ROOT / "evals" / "fixtures"
RESULTS = ROOT / "evals" / "results"
TABLEUP = ROOT / "scripts" / "tableup.py"

# 기본 fixture 경로 (환경변수로 오버라이드 가능)
BOK_AI_PDF = Path(
    os.environ.get("TABLEUP_EVAL_BOK_AI", str(FIXTURES / "bok_ai_report.pdf"))
).expanduser()
BOK_MAIN_PDF = Path(
    os.environ.get(
        "TABLEUP_EVAL_BOK_MAIN", str(FIXTURES / "bok_financial_stability_main.pdf")
    )
).expanduser()

BOK_MAIN_URL = (
    "https://www.bok.or.kr/fileSrc/portal/"
    "4f1a9e7acede40168fde41d1e555d2f4/5/d9b3fe9fbcec4bee83171092b6da2654.pdf"
)
# BOK 이슈노트 [제2025-22호] AI의 빠른 확산과 생산성 효과
BOK_AI_URL = (
    "https://www.bok.or.kr/fileSrc/portal/"
    "4328064bf5fa45ac8b118692ba3c4644/1/dc9d59003d50427d8735ee8830d4b853.pdf"
)

SUBPROCESS_TIMEOUT = 900  # 15분

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
        return bool(self.checks) and all(c.passed for c in self.checks)

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append(Check(name, passed, detail))


# -------- 공용 헬퍼 --------


def _resolve_fixture(primary: Path, url: str | None) -> Path:
    """fixture 경로 → URL 다운로드 순으로 시도."""
    if primary.exists():
        return primary
    if url:
        import urllib.request

        primary.parent.mkdir(parents=True, exist_ok=True)
        print(f"  PDF 다운로드 중: {url}")
        req = urllib.request.Request(url, headers={"Referer": "https://www.bok.or.kr/"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            primary.write_bytes(resp.read())
        return primary
    raise SystemExit(
        f"❌ 필요한 fixture 파일이 없습니다: {primary}\n"
        f"   환경변수(TABLEUP_EVAL_BOK_AI / TABLEUP_EVAL_BOK_MAIN)로 경로를 지정하거나\n"
        f"   위 경로에 파일을 배치하세요."
    )


def run_tableup(pdf: Path, out_dir: Path, extra_args: list[str] | None = None) -> None:
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(TABLEUP), str(pdf), "--out", str(out_dir), "--no-source", "--force"]
    if extra_args:
        cmd += extra_args
    print(f"  실행: tableup.py --out {out_dir.name}")
    try:
        res = subprocess.run(
            cmd, capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        raise SystemExit(
            f"❌ tableup.py 가 {SUBPROCESS_TIMEOUT}초 내에 끝나지 않았습니다 (PDF: {pdf.name})."
        )
    if res.returncode != 0:
        print(res.stdout)
        print(res.stderr, file=sys.stderr)
        raise SystemExit(f"tableup 실행 실패 (exit {res.returncode})")


def load_meta(out_dir: Path) -> dict:
    return json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))


def load_raw(out_dir: Path) -> dict:
    return json.loads((out_dir / "_raw_response.json").read_text(encoding="utf-8"))


def _within_tolerance(actual: float, expected: float, tol: float = 0.05) -> bool:
    """상대 오차 비교. expected 0 일 때는 절대 오차로 분기."""
    if expected == 0:
        return abs(actual) < 1e-9
    return abs(actual - expected) / abs(expected) <= tol


# -------- Eval 1: 복잡 표 --------


def eval_complex_table() -> EvalResult:
    print("\n▶ Eval 1: 복잡 표 추출 (BoK 금융안정보고서 p.6 취약차주 표)")
    pdf = _resolve_fixture(BOK_MAIN_PDF, BOK_MAIN_URL)
    out_dir = RESULTS / "e01_complex_table"
    run_tableup(pdf, out_dir)

    result = EvalResult("Eval 1: 복잡 표 추출", "scenario-01-complex-table.md", out_dir)
    meta = load_meta(out_dir)

    p6_tables = [f for f in meta["files"] if f["type"] == "table" and f["page"] == 6]
    result.add("p.6 표 추출", len(p6_tables) >= 1, f"p6 tables={len(p6_tables)}")
    if not p6_tables:
        return result

    best = max(p6_tables, key=lambda f: f["rows"] * f["cols"])
    df = pd.read_csv(out_dir / best["path"])
    result.add(
        "다행·다열 표",
        df.shape[0] >= 5 and df.shape[1] >= 5,
        f"shape={df.shape}",
    )

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
    result.add(f"골든 값 {hits}/5 이상 발견", hits >= 4, f"{hits}/5 hit")

    korean_in_cols = any(re.search(r"[가-힣]", str(c)) for c in df.columns)
    korean_in_cells = any(re.search(r"[가-힣]", str(v)) for v in flat_values)
    result.add("한글 헤더/셀 보존", korean_in_cols or korean_in_cells, "")
    return result


# -------- Eval 2: 차트 → 데이터 --------


def eval_chart_to_data() -> EvalResult:
    print("\n▶ Eval 2: 차트→데이터 (BoK AI 보고서 p.5)")
    pdf = _resolve_fixture(BOK_AI_PDF, BOK_AI_URL)
    out_dir = RESULTS / "e02_chart_to_data"
    run_tableup(pdf, out_dir)

    result = EvalResult("Eval 2: 차트→데이터", "scenario-02-chart-to-data.md", out_dir)
    meta = load_meta(out_dir)

    charts = [f for f in meta["files"] if f["type"] == "chart"]
    result.add("차트 추출 개수", len(charts) >= 30, f"charts={len(charts)}")

    p5_charts = [c for c in charts if c["page"] == 5]
    if not p5_charts:
        result.add("p.5 차트 발견", False, "none")
        return result
    result.add("p.5 차트 발견", True, f"{len(p5_charts)}개")

    golden = {
        ("전체", "한국"): 63.5,
        ("전체", "미국"): 39.6,
        ("업무 내", "한국"): 51.8,
        ("업무 내", "미국"): 26.5,
        ("업무 외", "한국"): 60.1,
        ("업무 외", "미국"): 33.7,
    }

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
        if _within_tolerance(actual_f, expected, tol=0.05):
            hits += 1

    result.add(f"골든 값 정확도 {hits}/{total}", hits == total, f"{hits}/{total} within ±5%")
    return result


# -------- Eval 3: HWP 유래 PDF --------


def eval_hwp_derived() -> EvalResult:
    print("\n▶ Eval 3: HWP 유래 PDF 전체 처리 (BoK 금융안정보고서 77p)")
    pdf = _resolve_fixture(BOK_MAIN_PDF, BOK_MAIN_URL)
    out_dir = RESULTS / "e03_hwp_derived"
    run_tableup(pdf, out_dir)

    result = EvalResult("Eval 3: HWP 유래 PDF", "scenario-03-hwp-derived.md", out_dir)
    meta = load_meta(out_dir)
    raw = load_raw(out_dir)

    elements = raw["elements"]
    result.add("element 1000개 이상", len(elements) >= 1000, f"elements={len(elements)}")

    raw_tables = sum(1 for e in elements if e.get("category") == "table")
    raw_charts = sum(1 for e in elements if e.get("category") == "chart")
    result.add("원본 표 20개 이상", raw_tables >= 20, f"raw tables={raw_tables}")
    result.add("원본 차트 130개 이상", raw_charts >= 130, f"raw charts={raw_charts}")

    meta_total_data = meta["counts"]["tables"] + meta["counts"]["charts"]
    result.add(
        "데이터 자산 150개 이상",
        meta_total_data >= 150,
        f"tables+charts={meta_total_data} "
        f"(tables={meta['counts']['tables']}, charts={meta['counts']['charts']})",
    )

    all_md = raw.get("content", {}).get("markdown", "")
    korean_chars = len(re.findall(r"[가-힣]", all_md))
    broken = all_md.count("\ufffd") + all_md.count("�")
    result.add("한글 10,000자 이상", korean_chars >= 10000, f"korean={korean_chars}")
    result.add("깨진 문자 0개", broken == 0, f"broken={broken}")

    # 회귀 방지: chart 파싱 실패가 있어도 meta 에 흔적이 남아야 한다
    # (과거 except Exception: pass 로 조용히 누락되던 케이스)
    raw_charts = sum(1 for e in raw["elements"] if e.get("category") == "chart")
    extracted_charts = meta["counts"]["charts"]
    dropped = raw_charts - extracted_charts
    boundary_chart_failures = [
        c for c in meta.get("boundary_cases", []) if "chart parse failed" in c.get("reason", "")
    ]
    result.add(
        "chart 파싱 실패 silent skip 없음",
        dropped <= len(boundary_chart_failures),
        f"dropped={dropped}, recorded={len(boundary_chart_failures)}",
    )
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
