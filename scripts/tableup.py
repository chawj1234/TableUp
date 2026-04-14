#!/usr/bin/env python3
"""TableUp CLI entry — 문서 표·차트 데이터 추출기.

지원 파일: PDF · 이미지(JPEG, PNG, BMP, TIFF, HEIC) · Office(DOCX, PPTX, XLSX) · 한글(HWP, HWPX)

Usage:
    python scripts/tableup.py <file_path> [옵션]
    python scripts/tableup.py --search "<키워드>"

옵션:
    --pages N-M         PDF 특정 페이지 범위 (비-PDF 에선 무시)
    --no-source         원본 페이지 PNG 생성 생략 (PDF 만 해당)
    --excel             .xlsx 파일도 함께 생성
    --out <dir>         출력 디렉토리 (기본: .tableup/<파일명>/)
    --force             캐시 무시하고 재호출
    --search <키워드>   CWD/Downloads/Desktop/Documents 에서 부분 파일명 검색

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
import unicodedata
from pathlib import Path

# scripts/ 를 경로에 추가하여 sibling 모듈을 import 가능하게 함
sys.path.insert(0, str(Path(__file__).parent))

from extract import extract_all, write_index_md, write_meta_json  # noqa: E402
from upstage_client import UpstageError, is_pdf, run_pipeline  # noqa: E402


CACHE_DIR = Path.home() / ".cache" / "tableup"

SUPPORTED_EXTS = {
    ".pdf",
    ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".heic",
    ".docx", ".pptx", ".xlsx",
    ".hwp", ".hwpx",
}


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


def print_summary(src_name: str, result, output_dir: Path, *, has_sources: bool) -> None:
    print("\n✅ 추출 완료\n")
    print(f"📄 원본: {src_name}")
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
    if has_sources:
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


DEFAULT_SEARCH_DIRS = (
    Path.cwd(),
    Path.home() / "Downloads",
    Path.home() / "Desktop",
    Path.home() / "Documents",
)


def _normalize(s: str) -> str:
    """macOS NFD 파일명과 NFC 사용자 입력의 호환성을 위해 NFC 로 통일한다."""
    return unicodedata.normalize("NFC", s).lower()


def resolve_by_search(term: str) -> Path:
    """부분 파일명으로 지원 문서를 찾는다. 대소문자·NFD/NFC 무시, 최근 수정 순 정렬.

    검색 경로: CWD, ~/Downloads, ~/Desktop, ~/Documents
    검색 확장자: SUPPORTED_EXTS 전부 (PDF, 이미지, Office, HWP/HWPX)
    """
    term_n = _normalize(term)
    matches: list[Path] = []
    seen: set[Path] = set()
    for d in DEFAULT_SEARCH_DIRS:
        if not d.exists():
            continue
        for f in d.iterdir():
            if not f.is_file() or f.suffix.lower() not in SUPPORTED_EXTS:
                continue
            rp = f.resolve()
            if rp in seen:
                continue
            if term_n in _normalize(f.stem):
                seen.add(rp)
                matches.append(f)

    if not matches:
        raise SystemExit(
            f"❌ '{term}' 과 매칭되는 문서 없음.\n"
            f"   검색 경로: CWD, ~/Downloads, ~/Desktop, ~/Documents\n"
            f"   지원 확장자: PDF, 이미지, Office, HWP/HWPX"
        )

    matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    if len(matches) > 1:
        msg = [f"⚠️  '{term}' 과 매칭되는 문서가 여러 개입니다. 더 구체적인 키워드로 재시도하세요:"]
        for m in matches[:10]:
            msg.append(f"   • {m}")
        if len(matches) > 10:
            msg.append(f"   ... 외 {len(matches) - 10}개")
        raise SystemExit("\n".join(msg))

    print(f"🔍 찾은 파일: {matches[0]}", file=sys.stderr)
    return matches[0]


def _default_output_dir(src: Path) -> Path:
    """기본 출력 경로. 같은 CWD 에서 여러 문서를 처리해도 겹치지 않도록 stem 기반 하위 디렉토리 사용."""
    return Path(".tableup") / src.stem


def main() -> int:
    ap = argparse.ArgumentParser(description="TableUp — 문서 표·차트 추출")
    ap.add_argument("file", nargs="?", help="처리할 파일 경로 (--search 사용 시 생략 가능)")
    ap.add_argument("--search", help="부분 파일명으로 검색 (CWD/Downloads/Desktop/Documents)")
    ap.add_argument("--pages", help="PDF 페이지 범위 (예: 12-15 또는 12). 비-PDF 에선 무시.", default=None)
    ap.add_argument("--no-source", action="store_true", help="원본 페이지 PNG 생성 생략 (PDF 만 해당)")
    ap.add_argument("--excel", action="store_true", help="xlsx 파일도 생성")
    ap.add_argument("--out", help="출력 디렉토리 (기본: .tableup/<파일명>/)")
    ap.add_argument("--force", action="store_true", help="캐시 무시")
    args = ap.parse_args()

    if not args.file and not args.search:
        ap.error("파일 경로 또는 --search 중 하나는 반드시 필요합니다.")

    if args.search and args.file:
        print(
            "⚠️  파일 경로와 --search 를 모두 주셨습니다. 경로를 우선 사용합니다.",
            file=sys.stderr,
        )

    if args.file:
        src_path = Path(args.file).expanduser().resolve()
    else:
        src_path = resolve_by_search(args.search).resolve()

    if not src_path.exists():
        print(f"❌ 파일 없음: {src_path}", file=sys.stderr)
        return 1
    if src_path.stat().st_size > 50 * 1024 * 1024:
        print(
            f"❌ 파일이 50MB 를 초과합니다: {src_path.stat().st_size / 1024 / 1024:.1f}MB",
            file=sys.stderr,
        )
        return 1
    if src_path.suffix.lower() not in SUPPORTED_EXTS:
        print(
            f"❌ 지원하지 않는 확장자: {src_path.suffix}\n"
            f"   지원: {', '.join(sorted(SUPPORTED_EXTS))}",
            file=sys.stderr,
        )
        return 1

    src_is_pdf = is_pdf(src_path)

    # 페이지 범위 처리 (PDF 만)
    if args.pages:
        if not src_is_pdf:
            print(
                f"⚠️  --pages 는 PDF 에서만 유효합니다. {src_path.suffix} 는 전체 처리됩니다.",
                file=sys.stderr,
            )
            upload_path = src_path
        else:
            start, end = parse_page_range(args.pages)
            print(f"🔖 페이지 {start}-{end} 만 추출합니다", file=sys.stderr)
            upload_path = extract_page_range(src_path, start, end)
    else:
        upload_path = src_path

    # 캐시 확인 (sha256 기준)
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

    # 출력 디렉토리 결정 — 기본은 .tableup/<stem>/ (겹침 방지)
    if args.out:
        output_dir = Path(args.out).resolve()
    else:
        output_dir = _default_output_dir(src_path).resolve()

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    # 추출·저장
    result = extract_all(response, output_dir)

    (output_dir / "_raw_response.json").write_text(
        json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    total_pages = response.get("usage", {}).get("pages", 0)
    write_index_md(
        result, output_dir, source_name=src_path.name, total_pages=total_pages
    )
    write_meta_json(
        result,
        output_dir,
        source_sha256=sha,
        source_name=src_path.name,
        model=response.get("model", "document-parse"),
        total_pages=total_pages,
    )

    # 원본 페이지 이미지 (PDF 한정)
    has_sources = False
    if src_is_pdf and not args.no_source:
        pages_used = {item.page for item in result.all_items() if item.page}
        if pages_used:
            print(f"🖼️  원본 페이지 {len(pages_used)}장 렌더링 중...", file=sys.stderr)
            render_source_pages(src_path, pages_used, output_dir)
            has_sources = True

    if args.excel and (result.tables or result.charts):
        write_excel_copies(result, output_dir)

    # 임시 페이지 범위 PDF 정리 (원본 sha256 캐시는 유지)
    if args.pages and src_is_pdf and upload_path != src_path:
        try:
            upload_path.unlink(missing_ok=True)
        except OSError:
            pass

    print_summary(src_path.name, result, output_dir, has_sources=has_sources)
    return 0


if __name__ == "__main__":
    sys.exit(main())
