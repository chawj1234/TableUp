"""Upstage Document Parse 클라이언트.

설계 결정 (2026-04 기준):
- enhanced mode 는 현재 sync 엔드포인트만 안정적 (async+enhanced 는 server error 빈발)
- sync 엔드포인트는 100페이지 제한 → 이를 초과하면 클라이언트에서 chunk 단위로 나눠 순차 호출
- async 래퍼(poll/download)는 standard mode 용으로 upstage_async.py 에 별도 보존
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

API_BASE = "https://api.upstage.ai/v1/document-digitization"

SYNC_MAX_PAGES = 100
MAX_RETRIES = 4
REQUEST_TIMEOUT = 900  # 최대 15분 (100페이지 enhanced 기준 충분)
DEFAULT_MAX_WORKERS = 2  # Upstage rate limit 2 RPS 안전 범위


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
    boundary = f"----TableUpBoundary{int(time.time() * 1000)}"
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


def _split_pdf(pdf_path: Path, start: int, end: int, out_path: Path) -> Path:
    """pypdfium2 로 start..end (1-indexed, 포함) 범위만 추출해 새 PDF 로 저장."""
    import pypdfium2 as pdfium

    src = pdfium.PdfDocument(str(pdf_path))
    dst = pdfium.PdfDocument.new()
    dst.import_pages(src, list(range(start - 1, end)))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    dst.save(str(out_path))
    return out_path


def _call_sync(
    file_path: Path,
    *,
    mode: str = "enhanced",
    ocr: str = "auto",
    chart_recognition: bool = True,
    merge_multipage_tables: bool = True,
) -> dict:
    """Upstage sync 엔드포인트를 한 번 호출하여 전체 응답을 반환한다.

    PDF 외에 이미지·DOCX·PPTX·XLSX·HWP·HWPX 도 지원한다.
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
            msg = e.read().decode("utf-8", errors="replace")
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
            raise UpstageError(f"네트워크 오류: {e}") from e
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
    mode: str = "enhanced",
    on_progress: Callable[[int, int], None] | None = None,
    chunk_cache_dir: Path | None = None,
    chunk_size: int | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    **kwargs,
) -> dict:
    """문서를 처리하고 병합된 응답을 반환한다.

    - PDF 100페이지 이하 또는 비-PDF: sync 엔드포인트 단일 호출
    - PDF 100페이지 초과: chunk_size 단위로 자동 분할, **max_workers 개 병렬** 호출, 순서대로 병합
    - 분할한 chunk PDF 는 호출 성공 후 자동 정리
    - 병렬은 Upstage rate limit 2 RPS 안전 범위(max_workers=2)
    """
    file_path = Path(file_path)
    chunk_size = chunk_size or SYNC_MAX_PAGES

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

    # chunk 분할 (로컬, 빠름)
    chunk_cache_dir = chunk_cache_dir or (Path.home() / ".cache" / "tableup" / "chunks")
    chunk_cache_dir.mkdir(parents=True, exist_ok=True)

    chunk_specs: list[tuple[int, int, Path]] = []  # (start_page, end_page, chunk_path)
    for start in range(1, n_pages + 1, chunk_size):
        end = min(start + chunk_size - 1, n_pages)
        chunk_path = chunk_cache_dir / f"{file_path.stem}_p{start}-{end}.pdf"
        _split_pdf(file_path, start, end, chunk_path)
        chunk_specs.append((start, end, chunk_path))

    created_chunks = [p for _, _, p in chunk_specs]

    # 병렬 API 호출
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
        return start - 1, resp  # offset, resp

    # max_workers 개 동시 실행. 첫 번째 실패 시 다른 작업도 가능한 한 종료.
    results_by_offset: dict[int, dict] = {}
    failure: Exception | None = None

    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(chunk_specs)))) as ex:
        futures = {ex.submit(_process, spec): spec for spec in chunk_specs}
        for fut in as_completed(futures):
            try:
                offset, resp = fut.result()
                results_by_offset[offset] = resp
            except Exception as e:
                failure = e
                for other in futures:
                    other.cancel()
                break

    if failure is not None:
        # 실패 시에도 이미 만든 chunk 는 정리 (디스크 누수 방지)
        for p in created_chunks:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        raise failure

    # 원본 순서대로 정렬
    responses = [results_by_offset[o] for o in sorted(results_by_offset)]
    offsets = sorted(results_by_offset)

    for p in created_chunks:
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass

    return _merge_responses(responses, offsets)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python upstage_client.py <pdf_path>", file=sys.stderr)
        sys.exit(1)

    def _progress(done: int, total: int) -> None:
        print(f"  {done}/{total} 페이지", file=sys.stderr)

    result = run_pipeline(sys.argv[1], on_progress=_progress)
    print(json.dumps(result, ensure_ascii=False, indent=2)[:2000])
