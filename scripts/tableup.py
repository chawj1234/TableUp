#!/usr/bin/env python3
"""TableUp CLI entry — PDF 표/차트 데이터 추출기.

Usage:
    python scripts/tableup.py <pdf_path> [옵션]

옵션:
    --pages N-M         특정 페이지 범위만 처리 (예: 12-15)
    --no-source         원본 페이지 PNG 생성 생략
    --excel             .xlsx 파일도 함께 생성
    --out <dir>         출력 디렉토리 (기본: ./.tableup)

환경변수:
    UPSTAGE_API_KEY     필수. https://console.upstage.ai 에서 발급.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

# scripts/ 를 경로에 추가하여 sibling 모듈을 import 가능하게 함
sys.path.insert(0, str(Path(__file__).parent))

from extract import extract_all, write_index_md, write_meta_json  # noqa: E402
from upstage_client import UpstageError, run_pipeline  # noqa: E402


CACHE_DIR = Path.home() / ".cache" / "tableup"


def parse_page_range(spec: str) -> tuple[int, int]:
    """'12-15' 또는 '12' 형식 파싱."""
    if "-" in spec:
        a, b = spec.split("-", 1)
        return int(a), int(b)
    n = int(spec)
    return n, n


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_page_range(pdf_path: Path, start: int, end: int) -> Path:
    """pypdfium2 로 특정 페이지 범위만 추출해 임시 PDF 로 저장한다."""
    try:
        import pypdfium2 as pdfium
    except ImportError as e:
        raise SystemExit(
            "pypdfium2 가 설치되지 않았습니다. `pip install pypdfium2` 후 재시도하세요."
        ) from e

    src = pdfium.PdfDocument(str(pdf_path))
    n_total = len(src)
    if start < 1 or end > n_total or start > end:
        raise SystemExit(f"페이지 범위가 잘못되었습니다 (PDF 총 {n_total} 페이지)")

    dst = pdfium.PdfDocument.new()
    dst.import_pages(src, list(range(start - 1, end)))

    out_path = CACHE_DIR / "tmp" / f"{pdf_path.stem}_p{start}-{end}.pdf"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dst.save(str(out_path))
    return out_path


def render_source_pages(
    pdf_path: Path, pages_used: set[int], output_dir: Path, *, dpi: int = 150
) -> None:
    """추출된 요소가 등장한 페이지의 PNG를 sources/ 에 저장한다."""
    try:
        import pypdfium2 as pdfium
    except ImportError:
        print("  (pypdfium2 없음 — 원본 페이지 이미지 생략)", file=sys.stderr)
        return

    doc = pdfium.PdfDocument(str(pdf_path))
    sources_dir = output_dir / "sources"
    sources_dir.mkdir(exist_ok=True)

    scale = dpi / 72
    for pno in sorted(pages_used):
        if pno < 1 or pno > len(doc):
            continue
        page = doc[pno - 1]
        bitmap = page.render(scale=scale)
        pil = bitmap.to_pil()
        pil.save(sources_dir / f"p{pno}.png")


def get_cache_path(sha256: str) -> Path:
    return CACHE_DIR / f"{sha256[:16]}.json"


def load_cached_response(sha256: str) -> dict | None:
    p = get_cache_path(sha256)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return None


def save_cached_response(sha256: str, response: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    get_cache_path(sha256).write_text(
        json.dumps(response, ensure_ascii=False), encoding="utf-8"
    )


def on_progress(done: int, total: int) -> None:
    if total:
        bar_len = 30
        filled = int(bar_len * done / total)
        bar = "█" * filled + "░" * (bar_len - filled)
        print(
            f"\r  [{bar}] {done}/{total} 페이지 ({done * 100 // total}%)",
            end="",
            file=sys.stderr,
            flush=True,
        )
    else:
        print("  제출 완료, 처리 대기 중...", file=sys.stderr)


def print_summary(pdf_name: str, result, output_dir: Path) -> None:
    print("\n✅ 추출 완료\n")
    print(f"📄 원본: {pdf_name}")
    print(f"📁 출력: {output_dir}/")
    print()
    print(f"📊 표 (Tables): {len(result.tables)}")
    for t in result.tables[:10]:
        cap = t.caption or "(제목 없음)"
        print(f"   {t.csv_path.name}  [{t.n_rows}×{t.n_cols}]  {cap[:40]}")
    if len(result.tables) > 10:
        print(f"   ... 외 {len(result.tables) - 10}개")
    print()
    print(f"📈 차트 (Charts → Data): {len(result.charts)}")
    for c in result.charts[:10]:
        cap = c.caption or "(제목 없음)"
        print(f"   {c.csv_path.name}  [{c.n_rows}×{c.n_cols}]  {cap[:40]}")
    if len(result.charts) > 10:
        print(f"   ... 외 {len(result.charts) - 10}개")
    if result.boundary_cases:
        print(f"\n⚠️  경계 케이스: {len(result.boundary_cases)} (차트로 재분류)")
    if result.footnotes:
        print(f"📝 각주·출처: {len(result.footnotes)} ({output_dir}/meta.json 에 저장)")
    print()
    print("👉 다음 단계:")
    print(f"   1. {output_dir}/index.md 를 먼저 읽으세요")
    print(f"   2. 필요한 CSV를 pd.read_csv() 로 로드하세요")
    print(f"   3. 수치 검증은 {output_dir}/sources/p<N>.png 참조")


def write_excel_copies(result, output_dir: Path) -> None:
    try:
        import pandas as pd
    except ImportError:
        return
    xlsx_path = output_dir / "all_tables.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        for item in result.all_items():
            df = pd.read_csv(item.csv_path)
            sheet = f"{item.kind[0]}{item.index:02d}_p{item.page}"[:31]
            df.to_excel(writer, sheet_name=sheet, index=False)


def main() -> int:
    ap = argparse.ArgumentParser(description="TableUp — PDF 표·차트 추출")
    ap.add_argument("pdf", help="처리할 PDF 경로")
    ap.add_argument("--pages", help="페이지 범위 (예: 12-15 또는 12)", default=None)
    ap.add_argument("--no-source", action="store_true", help="원본 페이지 PNG 생성 생략")
    ap.add_argument("--excel", action="store_true", help="xlsx 파일도 생성")
    ap.add_argument("--out", default=".tableup", help="출력 디렉토리 (기본: ./.tableup)")
    ap.add_argument("--force", action="store_true", help="캐시 무시")
    args = ap.parse_args()

    pdf_path = Path(args.pdf).expanduser().resolve()
    if not pdf_path.exists():
        print(f"❌ 파일 없음: {pdf_path}", file=sys.stderr)
        return 1
    if pdf_path.stat().st_size > 50 * 1024 * 1024:
        print(f"❌ 파일이 50MB 를 초과합니다: {pdf_path.stat().st_size / 1024 / 1024:.1f}MB", file=sys.stderr)
        return 1

    # 페이지 범위 처리
    if args.pages:
        start, end = parse_page_range(args.pages)
        print(f"🔖 페이지 {start}-{end} 만 추출합니다", file=sys.stderr)
        upload_path = extract_page_range(pdf_path, start, end)
    else:
        upload_path = pdf_path

    # 캐시 확인
    sha = sha256_file(upload_path)
    response = None
    if not args.force:
        response = load_cached_response(sha)
        if response:
            print("⚡ 캐시에서 복원 (API 호출 생략)", file=sys.stderr)

    # API 호출
    if response is None:
        print("🚀 Upstage Document Parse (enhanced) 호출 중...", file=sys.stderr)
        try:
            response = run_pipeline(upload_path, on_progress=on_progress)
        except UpstageError as e:
            print(f"\n❌ {e}", file=sys.stderr)
            return 2
        print("", file=sys.stderr)  # 진행바 개행
        save_cached_response(sha, response)

    # 출력 디렉토리 준비 (기존 것 청소)
    output_dir = Path(args.out).resolve()
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    # 추출·저장
    result = extract_all(response, output_dir)

    # 원본 JSON 백업 (디버깅용)
    (output_dir / "_raw_response.json").write_text(
        json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 메타·인덱스
    total_pages = response.get("usage", {}).get("pages", 0)
    write_index_md(
        result, output_dir, source_name=pdf_path.name, total_pages=total_pages
    )
    write_meta_json(
        result,
        output_dir,
        source_sha256=sha,
        source_name=pdf_path.name,
        model=response.get("model", "document-parse"),
        total_pages=total_pages,
    )

    # 원본 페이지 이미지
    if not args.no_source:
        pages_used = {item.page for item in result.all_items() if item.page}
        if pages_used:
            print(f"🖼️  원본 페이지 {len(pages_used)}장 렌더링 중...", file=sys.stderr)
            render_source_pages(pdf_path, pages_used, output_dir)

    # Excel 추가 출력
    if args.excel and (result.tables or result.charts):
        write_excel_copies(result, output_dir)

    # 요약 출력
    print_summary(pdf_path.name, result, output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
