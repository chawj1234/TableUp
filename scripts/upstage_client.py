"""Upstage Document Parse 클라이언트.

설계 결정 (2026-04 기준):
- Async + enhanced/auto 조합에 Upstage 서버 이슈 재현됨 → 본 클라이언트는 sync 만 사용
- Sync 엔드포인트의 100페이지 제한은 클라이언트에서 chunk 분할 + 2-way 병렬 호출로 극복
- 기본 모드는 `auto` (페이지별 자동 분류). `enhanced`, `standard` 도 선택 가능.

환경변수 오버라이드:
- UPPARSE_MAX_WORKERS: 동시 chunk 호출 수 (기본 2, Upstage rate limit 2 RPS 안전 범위)
- UPPARSE_CHUNK_SIZE: chunk 당 페이지 수 (기본 100, sync 엔드포인트 최대)
"""
from __future__ import annotations

import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

API_BASE = "https://api.upstage.ai/v1/document-digitization"

SYNC_MAX_PAGES = int(os.environ.get("UPPARSE_CHUNK_SIZE", "100"))
MAX_RETRIES = 4
REQUEST_TIMEOUT = 900  # 최대 15분
DEFAULT_MAX_WORKERS = int(os.environ.get("UPPARSE_MAX_WORKERS", "2"))


def _default_cache_dir() -> Path:
    """upparse.py 와 동일하게 UPPARSE_CACHE_DIR override 를 존중한다."""
    env = os.environ.get("UPPARSE_CACHE_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".cache" / "upparse"


class UpstageError(Exception):
    """Upstage API 호출 실패."""


def _require_api_key() -> str:
    key = os.environ.get("UPSTAGE_API_KEY")
    if not key:
        raise UpstageError(
            "UPSTAGE_API_KEY 환경변수가 설정되지 않았습니다. "
            "https://console.upstage.ai 에서 발급받으세요."
        )
    return key


def _mask_api_key(text: str) -> str:
    """에러 메시지 등에서 Upstage API 키 형태를 마스킹한다."""
    return re.sub(r"up_[A-Za-z0-9]{10,}", "up_***REDACTED***", text)


_CONTENT_TYPE_BY_EXT = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".heic": "image/heic",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".hwp": "application/vnd.hancom.hwp",
    ".hwpx": "application/vnd.hancom.hwpx",
}


def _content_type_for(path: Path) -> str:
    return _CONTENT_TYPE_BY_EXT.get(path.suffix.lower(), "application/octet-stream")


def is_pdf(path: Path) -> bool:
    return path.suffix.lower() == ".pdf"


def _build_multipart(
    fields: dict, filename: str, file_bytes: bytes, content_type: str
) -> tuple[bytes, str]:
    # 고유 boundary (병렬 호출 시 ms 해상도 충돌 방지)
    boundary = f"----UpParseBoundary{secrets.token_hex(16)}"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(f"--{boundary}".encode())
        parts.append(f'Content-Disposition: form-data; name="{name}"'.encode())
        parts.append(b"")
        parts.append(value.encode() if isinstance(value, str) else value)
    parts.append(f"--{boundary}".encode())
    parts.append(
        f'Content-Disposition: form-data; name="document"; filename="{filename}"'.encode()
    )
    parts.append(f"Content-Type: {content_type}".encode())
    parts.append(b"")
    parts.append(file_bytes)
    parts.append(f"--{boundary}--".encode())
    parts.append(b"")
    return b"\r\n".join(parts), boundary


def _pdf_page_count(pdf_path: Path) -> int:
    import pypdfium2 as pdfium

    return len(pdfium.PdfDocument(str(pdf_path)))


def split_pdf_pages(pdf_path: Path, start: int, end: int, out_path: Path) -> Path:
    """pypdfium2 로 start..end (1-indexed, 포함) 범위만 추출해 새 PDF 로 저장한다.

    upparse.py 의 페이지 범위 추출과 chunk 분할이 공유하는 단일 구현.
    """
    import pypdfium2 as pdfium

    src = pdfium.PdfDocument(str(pdf_path))
    n_total = len(src)
    if start < 1 or end > n_total or start > end:
        raise ValueError(f"페이지 범위 잘못됨 ({start}-{end}, PDF 총 {n_total}페이지)")
    dst = pdfium.PdfDocument.new()
    dst.import_pages(src, list(range(start - 1, end)))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dst.save(str(out_path))
    return out_path


def _call_sync(
    file_path: Path,
    *,
    mode: str,
    ocr: str = "auto",
    chart_recognition: bool = True,
    merge_multipage_tables: bool = True,
) -> dict:
    """Upstage sync 엔드포인트를 한 번 호출하여 전체 응답을 반환한다.

    PDF, 이미지(JPEG/PNG/BMP/TIFF/HEIC), Office(DOCX/PPTX/XLSX), 한글(HWP/HWPX) 모두 지원.
    """
    api_key = _require_api_key()
    file_bytes = file_path.read_bytes()
    content_type = _content_type_for(file_path)

    fields = {
        "model": "document-parse",
        "mode": mode,
        "ocr": ocr,
        "output_formats": '["html", "markdown"]',
        "coordinates": "true",
        "chart_recognition": "true" if chart_recognition else "false",
        "merge_multipage_tables": "true" if merge_multipage_tables else "false",
    }
    body, boundary = _build_multipart(fields, file_path.name, file_bytes, content_type)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }

    backoff = 5
    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(
                API_BASE, data=body, headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            msg = _mask_api_key(e.read().decode("utf-8", errors="replace"))
            if e.code == 429 or 500 <= e.code < 600:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
            raise UpstageError(f"HTTP {e.code}: {msg[:500]}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(backoff)
                backoff *= 2
                continue
            raise UpstageError(f"네트워크 오류: {_mask_api_key(str(e))}") from e
    raise UpstageError("최대 재시도 초과")


def _merge_responses(responses: list[dict], page_offsets: list[int]) -> dict:
    """여러 chunk 응답을 하나로 병합한다. page 번호를 offset 으로 조정한다."""
    merged: dict = {
        "elements": [],
        "content": {"html": "", "markdown": "", "text": ""},
        "model": None,
        "usage": {"pages": 0},
    }
    for resp, offset in zip(responses, page_offsets):
        for el in resp.get("elements", []):
            new_el = dict(el)
            if "page" in new_el:
                new_el["page"] = new_el["page"] + offset
            merged["elements"].append(new_el)
        for fmt in ("html", "markdown", "text"):
            part = resp.get("content", {}).get(fmt, "")
            if part:
                merged["content"][fmt] += part + "\n\n"
        merged["model"] = resp.get("model") or merged["model"]
        merged["usage"]["pages"] += resp.get("usage", {}).get("pages", 0)
    return merged


def run_pipeline(
    file_path: str | Path,
    *,
    mode: str = "auto",
    on_progress: Callable[[int, int], None] | None = None,
    chunk_cache_dir: Path | None = None,
    chunk_size: int | None = None,
    max_workers: int | None = None,
    source_sha: str | None = None,
    **kwargs,
) -> dict:
    """문서를 처리하고 병합된 응답을 반환한다.

    - 비-PDF 또는 chunk_size 이하 PDF: sync 엔드포인트 단일 호출
    - chunk_size 초과 PDF: 분할 후 max_workers 개 동시 호출, 결과는 페이지 순서대로 병합
    - 분할한 chunk PDF 는 성공·실패 모두에서 자동 정리 (finally)
    - source_sha: 제공 시 chunk 파일명에 prefix 로 포함하여 동명 PDF 충돌 방지
    """
    file_path = Path(file_path)
    chunk_size = chunk_size or SYNC_MAX_PAGES
    max_workers = max_workers or DEFAULT_MAX_WORKERS

    if not is_pdf(file_path):
        if on_progress:
            on_progress(0, 1)
        resp = _call_sync(file_path, mode=mode, **kwargs)
        if on_progress:
            on_progress(1, 1)
        return resp

    n_pages = _pdf_page_count(file_path)

    if n_pages <= chunk_size:
        if on_progress:
            on_progress(0, n_pages)
        resp = _call_sync(file_path, mode=mode, **kwargs)
        if on_progress:
            on_progress(n_pages, n_pages)
        return resp

    # chunk 분할
    chunk_cache_dir = chunk_cache_dir or (_default_cache_dir() / "chunks")
    try:
        chunk_cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise UpstageError(
            f"chunk 캐시 디렉터리 생성 실패: {chunk_cache_dir}\n"
            f"   UPPARSE_CACHE_DIR 환경변수로 쓰기 가능한 경로를 지정하세요. ({e})"
        ) from e
    prefix = f"{source_sha[:8]}_" if source_sha else ""

    chunk_specs: list[tuple[int, int, Path]] = []
    for start in range(1, n_pages + 1, chunk_size):
        end = min(start + chunk_size - 1, n_pages)
        chunk_path = chunk_cache_dir / f"{prefix}{file_path.stem}_p{start}-{end}.pdf"
        split_pdf_pages(file_path, start, end, chunk_path)
        chunk_specs.append((start, end, chunk_path))

    created_chunks = [p for _, _, p in chunk_specs]

    progress_lock = threading.Lock()
    pages_done = {"n": 0}
    if on_progress:
        on_progress(0, n_pages)

    def _process(spec: tuple[int, int, Path]) -> tuple[int, dict]:
        start, end, path = spec
        resp = _call_sync(path, mode=mode, **kwargs)
        with progress_lock:
            pages_done["n"] += end - start + 1
            if on_progress:
                on_progress(pages_done["n"], n_pages)
        return start - 1, resp

    results_by_offset: dict[int, dict] = {}
    try:
        with ThreadPoolExecutor(
            max_workers=max(1, min(max_workers, len(chunk_specs)))
        ) as ex:
            futures = {ex.submit(_process, spec): spec for spec in chunk_specs}
            first_error: Exception | None = None
            for fut in as_completed(futures):
                try:
                    offset, resp = fut.result()
                    results_by_offset[offset] = resp
                except Exception as e:
                    if first_error is None:
                        first_error = e
                    # 나머지 대기 중 작업은 취소 시도 (실행 중 작업은 불가피하게 진행됨)
                    for other in futures:
                        if not other.done():
                            other.cancel()
            if first_error is not None:
                raise first_error

        if len(results_by_offset) != len(chunk_specs):
            raise UpstageError(
                f"chunk 결과 누락: {len(results_by_offset)}/{len(chunk_specs)}"
            )

        responses = [results_by_offset[o] for o in sorted(results_by_offset)]
        offsets = sorted(results_by_offset)
        return _merge_responses(responses, offsets)
    finally:
        # 성공·실패 모두에서 chunk 임시 PDF cleanup
        for p in created_chunks:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python upstage_client.py <file_path>", file=sys.stderr)
        sys.exit(1)

    def _progress(done: int, total: int) -> None:
        print(f"  {done}/{total} 페이지", file=sys.stderr)

    result = run_pipeline(sys.argv[1], on_progress=_progress)
    print(json.dumps(result, ensure_ascii=False, indent=2)[:2000])
