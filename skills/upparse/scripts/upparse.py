#!/usr/bin/env python3
"""UpParse CLI entry — 문서의 표·차트·도식 데이터 추출기.

지원 파일: PDF · 이미지(JPEG, PNG, BMP, TIFF, HEIC) · Office(DOCX, PPTX, XLSX) · 한글(HWP, HWPX)

Usage:
    python scripts/upparse.py <file_path> [옵션]
    python scripts/upparse.py --search "<키워드>" [옵션]

옵션:
    --pages N-M         PDF 특정 페이지 범위 (비-PDF 에선 무시)
    --no-source         원본 페이지 PNG 생성 생략 (PDF 만 해당)
    --excel             .xlsx 파일도 함께 생성
    --out <dir>         출력 디렉토리 (기본: .upparse/<파일명>/)
    --force             캐시 무시 + 출력 디렉토리 덮어쓰기 허용
    --search <키워드>   CWD/Downloads/Desktop/Documents 에서 부분 파일명 검색

환경변수:
    UPSTAGE_API_KEY      필수. https://console.upstage.ai 에서 발급.
    UPPARSE_CACHE_DIR    캐시 경로 override (기본 ~/.cache/upparse)
    UPPARSE_MAX_WORKERS  chunk 병렬 호출 수 (기본 2)
    UPPARSE_CHUNK_SIZE   chunk 당 페이지 수 (기본 100)
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

sys.path.insert(0, str(Path(__file__).parent))


def _load_dotenv_if_present() -> None:
    """CWD 또는 스크립트 조상 디렉터리의 .env 를 환경변수에 최소 파싱으로 주입한다.

    이미 설정된 환경변수는 덮어쓰지 않는다. KEY=VALUE 한 줄 형식만 지원
    (따옴표·공백 trim, `#` 시작 주석 무시). python-dotenv 의존성 없이 동작.
    """
    candidates: list[Path] = [Path.cwd() / ".env"]
    here = Path(__file__).resolve().parent
    for parent in (here, *here.parents):
        candidates.append(parent / ".env")
        if (parent / ".git").exists():
            break
    seen: set[Path] = set()
    for p in candidates:
        if p in seen or not p.is_file():
            seen.add(p)
            continue
        seen.add(p)
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, v = s.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
        except OSError:
            continue


_load_dotenv_if_present()

from extract import extract_all, write_index_md, write_meta_json  # noqa: E402
from upstage_client import (  # noqa: E402
    UpstageError,
    is_pdf,
    run_pipeline,
    split_pdf_pages,
)


def _resolve_cache_dir() -> Path:
    """UPPARSE_CACHE_DIR override 지원. 기본은 ~/.cache/upparse."""
    env = os.environ.get("UPPARSE_CACHE_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".cache" / "upparse"


CACHE_DIR = _resolve_cache_dir()

SUPPORTED_EXTS = {
    ".pdf",
    ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".heic",
    ".docx", ".pptx", ".xlsx",
    ".hwp", ".hwpx",
}

# 한글 로케일의 Finder 는 Downloads/Desktop/Documents 를 현지화 표시만 하지만,
# 사용자가 직접 만든 `~/다운로드` 같은 디렉터리도 있을 수 있어 함께 후보에 둔다.
# 존재하지 않는 경로는 검색 루프에서 스킵된다.
DEFAULT_SEARCH_DIRS = (
    Path.cwd(),
    Path.home() / "Downloads",
    Path.home() / "Desktop",
    Path.home() / "Documents",
    Path.home() / "다운로드",
    Path.home() / "바탕화면",
    Path.home() / "문서",
)


# ----- 경로 해결 -----


def _normalize(s: str) -> str:
    """macOS NFD 파일명과 NFC 사용자 입력의 호환성을 위해 NFC 로 통일한다."""
    return unicodedata.normalize("NFC", s).lower()


def resolve_by_search(term: str) -> Path:
    """부분 파일명으로 지원 문서를 찾는다. 대소문자·NFD/NFC 무시, 최근 수정 순.

    검색 경로: CWD, ~/Downloads, ~/Desktop, ~/Documents
    확장자: SUPPORTED_EXTS 전부
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


# ----- 유틸 -----


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
    """특정 페이지 범위만 추출해 임시 PDF 로 저장한다.

    파일명에 원본 SHA256 접두를 포함하여 동명·다른 경로의 PDF 충돌을 방지한다.
    """
    src_sha = sha256_file(pdf_path)[:8]
    out_path = CACHE_DIR / "tmp" / f"{src_sha}_{pdf_path.stem}_p{start}-{end}.pdf"
    try:
        split_pdf_pages(pdf_path, start, end, out_path)
    except ValueError as e:
        raise SystemExit(f"❌ {e}")
    except ImportError:
        raise SystemExit(
            "pypdfium2 가 설치되지 않았습니다. `pip install pypdfium2` 후 재시도하세요."
        )
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


# ----- 캐시 -----


def get_cache_path(sha256: str, mode: str) -> Path:
    """모드별 별도 캐시. 모드를 바꾸면 재호출."""
    return CACHE_DIR / f"{sha256[:16]}_{mode}.json"


def load_cached_response(sha256: str, mode: str) -> dict | None:
    p = get_cache_path(sha256, mode)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    # 레거시 캐시(모드 없음)는 enhanced 요청 시에만 재사용
    if mode == "enhanced":
        legacy = CACHE_DIR / f"{sha256[:16]}.json"
        if legacy.exists():
            return json.loads(legacy.read_text(encoding="utf-8"))
    return None


def save_cached_response(sha256: str, mode: str, response: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise SystemExit(
            f"❌ 캐시 디렉터리 생성 실패: {CACHE_DIR}\n"
            f"   UPPARSE_CACHE_DIR 환경변수로 쓰기 가능한 경로를 지정하세요. ({e})"
        )
    get_cache_path(sha256, mode).write_text(
        json.dumps(response, ensure_ascii=False), encoding="utf-8"
    )


# ----- 진행바 & 요약 -----


def _is_tty() -> bool:
    try:
        return sys.stderr.isatty()
    except (AttributeError, ValueError):
        return False


def on_progress(done: int, total: int) -> None:
    """TTY 에서는 progress bar, non-TTY(캡처·파이프·CI)에서는 일반 줄 단위 출력."""
    if not total:
        print("  제출 완료, 처리 대기 중...", file=sys.stderr)
        return

    if _is_tty():
        bar_len = 30
        filled = int(bar_len * done / total)
        bar = "█" * filled + "░" * (bar_len - filled)
        print(
            f"\r  [{bar}] {done}/{total} 페이지 ({done * 100 // total}%)",
            end="",
            file=sys.stderr,
            flush=True,
        )
        if done == total:
            print("", file=sys.stderr)
    else:
        if done == 0 or done == total or done % max(1, total // 10) == 0:
            print(f"  {done}/{total} 페이지 ({done * 100 // total}%)", file=sys.stderr)


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
    if getattr(result, "figures", None):
        print()
        print(f"🖼️  도식·다이어그램 (Figures): {len(result.figures)} (데이터 표 아님)")
        for f in result.figures[:5]:
            ftype = f.figure_type or "figure"
            cap = (f.caption or "(제목 없음)")[:40]
            print(f"   p.{f.page}  [{ftype}]  {cap}")
        if len(result.figures) > 5:
            print(f"   ... 외 {len(result.figures) - 5}개 (index.md 참고)")
    if result.boundary_cases:
        print(f"\n⚠️  경계 케이스: {len(result.boundary_cases)} (meta.json 참고)")
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


# ----- 출력 디렉토리 안전성 -----


UPPARSE_MARKERS = ("_raw_response.json", "meta.json", "index.md")


def _looks_like_upparse_output(path: Path) -> bool:
    """기존 .upparse 출력 흔적이 있는지."""
    return any((path / m).exists() for m in UPPARSE_MARKERS)


def _is_dir_empty(path: Path) -> bool:
    try:
        next(path.iterdir())
    except StopIteration:
        return True
    except OSError:
        return False
    return False


def _prepare_output_dir(output_dir: Path, *, is_default_path: bool, force: bool) -> None:
    """출력 디렉토리 안전하게 준비. 사용자 데이터 덮어쓰기 방지.

    기본 경로(.upparse/<stem>/) 라도 마커 없이 사용자 데이터가 들어있을 수 있으므로
    동일하게 UpParse 출력 흔적·빈 디렉터리 여부를 확인한다. --force 는 모든 게이트를 뚫는다.
    """
    if not output_dir.exists():
        output_dir.mkdir(parents=True)
        return

    if not output_dir.is_dir():
        raise SystemExit(f"❌ --out 경로가 디렉토리가 아닙니다: {output_dir}")

    safe_to_overwrite = (
        _looks_like_upparse_output(output_dir) or _is_dir_empty(output_dir)
    )
    if safe_to_overwrite or force:
        shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True)
        return

    hint = " (기본 경로)" if is_default_path else ""
    raise SystemExit(
        f"❌ {output_dir}{hint} 는 비어있지 않고 UpParse 출력이 아닙니다.\n"
        f"   덮어쓰려면 --force 를 추가하거나 다른 --out 경로를 사용하세요."
    )


# ----- 오케스트레이션 (main 을 작은 단계로 분리) -----


def _default_output_dir(src: Path) -> Path:
    return Path(".upparse") / src.stem


def _resolve_source(args: argparse.Namespace) -> Path:
    """CLI 인자에서 최종 파일 경로 결정."""
    if not args.file and not args.search:
        raise SystemExit("❌ 파일 경로 또는 --search 중 하나는 반드시 필요합니다.")
    if args.search and args.file:
        print(
            "⚠️  파일 경로와 --search 를 모두 주셨습니다. 경로를 우선 사용합니다.",
            file=sys.stderr,
        )
    src = Path(args.file).expanduser().resolve() if args.file else resolve_by_search(args.search).resolve()

    if not src.exists():
        raise SystemExit(f"❌ 파일 없음: {src}")
    if src.stat().st_size > 50 * 1024 * 1024:
        raise SystemExit(
            f"❌ 파일이 50MB 를 초과합니다: {src.stat().st_size / 1024 / 1024:.1f}MB"
        )
    if src.suffix.lower() not in SUPPORTED_EXTS:
        raise SystemExit(
            f"❌ 지원하지 않는 확장자: {src.suffix}\n"
            f"   지원: {', '.join(sorted(SUPPORTED_EXTS))}"
        )
    return src


def _maybe_extract_range(
    src_path: Path, args: argparse.Namespace, src_is_pdf: bool
) -> tuple[Path, int]:
    """필요 시 페이지 범위 추출 후 업로드용 경로와 페이지 오프셋(start-1)을 반환.

    오프셋은 Upstage 응답의 element.page (슬라이스 기준 1-based) 를 원본 PDF 기준
    페이지로 환원하기 위해 사용된다. --pages 미사용 또는 비-PDF 면 offset 0.
    """
    if not args.pages:
        return src_path, 0
    if not src_is_pdf:
        print(
            f"⚠️  --pages 는 PDF 에서만 유효합니다. {src_path.suffix} 는 전체 처리됩니다.",
            file=sys.stderr,
        )
        return src_path, 0
    start, end = parse_page_range(args.pages)
    print(f"🔖 페이지 {start}-{end} 만 추출합니다", file=sys.stderr)
    return extract_page_range(src_path, start, end), start - 1


def _apply_page_offset(response: dict, offset: int) -> None:
    """응답 elements 의 page 번호에 offset 을 더해 원본 PDF 기준으로 환원한다.

    --pages N-M 사용 시 Upstage 는 슬라이스된 1페이지부터 번호를 매기므로,
    CSV 파일명·meta.json·sources/ PNG 렌더링이 모두 원본 페이지와 일치하도록
    상위에서 오프셋을 주입한다.
    """
    if not offset:
        return
    for el in response.get("elements", []):
        if "page" in el:
            el["page"] = el["page"] + offset


_EXTRACTION_MODE = "enhanced"  # 가장 정확한 추출을 항상 사용한다. 다른 값은 지원하지 않음.


def _run_or_cache(
    upload_path: Path, *, force: bool, on_progress_cb
) -> tuple[str, dict]:
    """캐시 조회 후 히트면 복원, 미스면 API 호출 후 캐시 저장. (sha, response) 반환."""
    sha = sha256_file(upload_path)
    if not force:
        cached = load_cached_response(sha, _EXTRACTION_MODE)
        if cached is not None:
            print("⚡ 캐시에서 복원 (API 호출 생략)", file=sys.stderr)
            return sha, cached

    print("🚀 Upstage Document Parse 호출 중...", file=sys.stderr)
    try:
        response = run_pipeline(
            upload_path, mode=_EXTRACTION_MODE, on_progress=on_progress_cb, source_sha=sha
        )
    except UpstageError as e:
        raise SystemExit(f"\n❌ {e}")
    if _is_tty():
        print("", file=sys.stderr)  # 진행바 개행
    save_cached_response(sha, _EXTRACTION_MODE, response)
    return sha, response


def _emit_outputs(
    response: dict,
    *,
    src_path: Path,
    src_is_pdf: bool,
    sha: str,
    output_dir: Path,
    render_sources: bool,
    make_excel: bool,
) -> None:
    result = extract_all(response, output_dir)

    (output_dir / "_raw_response.json").write_text(
        json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    total_pages = response.get("usage", {}).get("pages", 0)
    write_index_md(result, output_dir, source_name=src_path.name, total_pages=total_pages)
    write_meta_json(
        result,
        output_dir,
        source_sha256=sha,
        source_name=src_path.name,
        model=response.get("model", "document-parse"),
        total_pages=total_pages,
    )

    has_sources = False
    if src_is_pdf and render_sources:
        # 표·차트 뿐 아니라 figure 가 있는 페이지도 원본 PNG 를 만든다 (검증·vision 재확인용)
        pages_used = result.pages_with_visuals()
        if pages_used:
            print(f"🖼️  원본 페이지 {len(pages_used)}장 렌더링 중...", file=sys.stderr)
            render_source_pages(src_path, pages_used, output_dir)
            has_sources = True

    if make_excel and (result.tables or result.charts):
        write_excel_copies(result, output_dir)

    print_summary(src_path.name, result, output_dir, has_sources=has_sources)


def main() -> int:
    ap = argparse.ArgumentParser(description="UpParse — 문서 표·차트·도식 추출")
    ap.add_argument("file", nargs="?", help="처리할 파일 경로 (--search 사용 시 생략 가능)")
    ap.add_argument("--search", help="부분 파일명으로 검색 (CWD/Downloads/Desktop/Documents)")
    ap.add_argument("--pages", help="PDF 페이지 범위 (예: 12-15 또는 12). 비-PDF 에선 무시.")
    ap.add_argument("--no-source", action="store_true", help="원본 페이지 PNG 생성 생략")
    ap.add_argument("--excel", action="store_true", help="xlsx 파일도 생성")
    ap.add_argument("--out", help="출력 디렉토리 (기본: .upparse/<파일명>/)")
    ap.add_argument("--force", action="store_true", help="캐시 무시 + 출력 덮어쓰기 허용")
    args = ap.parse_args()

    # 1. 소스 파일 결정
    src_path = _resolve_source(args)
    src_is_pdf = is_pdf(src_path)

    # 2. (PDF + --pages) 면 임시 추출 + 페이지 오프셋 계산
    upload_path, page_offset = _maybe_extract_range(src_path, args, src_is_pdf)

    # 3. API 호출 또는 캐시 복원
    sha, response = _run_or_cache(
        upload_path, force=args.force, on_progress_cb=on_progress
    )

    # 3-b. --pages 슬라이스의 1-based 페이지 번호를 원본 PDF 기준으로 환원
    _apply_page_offset(response, page_offset)

    # 4. 출력 디렉토리 안전 준비
    is_default = args.out is None
    output_dir = (
        Path(args.out).resolve() if args.out else _default_output_dir(src_path).resolve()
    )
    _prepare_output_dir(output_dir, is_default_path=is_default, force=args.force)

    # 5. 결과 기록 + 요약 출력
    _emit_outputs(
        response,
        src_path=src_path,
        src_is_pdf=src_is_pdf,
        sha=sha,
        output_dir=output_dir,
        render_sources=not args.no_source,
        make_excel=args.excel,
    )

    # 6. 임시 페이지 범위 PDF 정리 (원본 SHA256 캐시는 유지)
    if args.pages and src_is_pdf and upload_path != src_path:
        try:
            upload_path.unlink(missing_ok=True)
        except OSError:
            pass

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except KeyboardInterrupt:
        print("\n중단됨.", file=sys.stderr)
        sys.exit(130)
