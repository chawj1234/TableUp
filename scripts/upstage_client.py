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
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

API_BASE = "https://api.upstage.ai/v1/document-digitization"

SYNC_MAX_PAGES = 100
MAX_RETRIES = 4
REQUEST_TIMEOUT = 900  # 최대 15분 (100페이지 enhanced 기준 충분)


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


def _build_multipart(fields: dict, filename: str, pdf_bytes: bytes) -> tuple[bytes, str]:
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
    parts.append(b"Content-Type: application/pdf")
    parts.append(b"")
    parts.append(pdf_bytes)
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
    pdf_path: Path,
    *,
    mode: str = "enhanced",
    ocr: str = "auto",
    chart_recognition: bool = True,
    merge_multipage_tables: bool = True,
) -> dict:
    """Upstage sync 엔드포인트를 한 번 호출하여 전체 응답을 반환한다."""
    api_key = _require_api_key()
    pdf_bytes = pdf_path.read_bytes()

    fields = {
        "model": "document-parse",
        "mode": mode,
        "ocr": ocr,
        "output_formats": '["html", "markdown"]',
        "coordinates": "true",
        "chart_recognition": "true" if chart_recognition else "false",
        "merge_multipage_tables": "true" if merge_multipage_tables else "false",
    }
    body, boundary = _build_multipart(fields, pdf_path.name, pdf_bytes)
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
    pdf_path: str | Path,
    *,
    mode: str = "enhanced",
    on_progress: Callable[[int, int], None] | None = None,
    chunk_cache_dir: Path | None = None,
    **kwargs,
) -> dict:
    """PDF 를 처리하고 병합된 응답을 반환한다.

    - 100페이지 이하: sync 엔드포인트 단일 호출
    - 100페이지 초과: SYNC_MAX_PAGES 단위로 자동 분할 후 순차 호출
    """
    pdf_path = Path(pdf_path)
    n_pages = _pdf_page_count(pdf_path)

    if n_pages <= SYNC_MAX_PAGES:
        if on_progress:
            on_progress(0, n_pages)
        resp = _call_sync(pdf_path, mode=mode, **kwargs)
        if on_progress:
            on_progress(n_pages, n_pages)
        return resp

    # chunk 모드
    chunk_cache_dir = chunk_cache_dir or (Path.home() / ".cache" / "tableup" / "chunks")
    chunk_cache_dir.mkdir(parents=True, exist_ok=True)

    responses: list[dict] = []
    offsets: list[int] = []
    pages_done = 0
    chunk_idx = 0
    for start in range(1, n_pages + 1, SYNC_MAX_PAGES):
        end = min(start + SYNC_MAX_PAGES - 1, n_pages)
        chunk_path = chunk_cache_dir / f"{pdf_path.stem}_p{start}-{end}.pdf"
        _split_pdf(pdf_path, start, end, chunk_path)
        if on_progress:
            on_progress(pages_done, n_pages)
        resp = _call_sync(chunk_path, mode=mode, **kwargs)
        responses.append(resp)
        offsets.append(start - 1)
        pages_done = end
        chunk_idx += 1
        if on_progress:
            on_progress(pages_done, n_pages)

    return _merge_responses(responses, offsets)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python upstage_client.py <pdf_path>", file=sys.stderr)
        sys.exit(1)

    def _progress(done: int, total: int) -> None:
        print(f"  {done}/{total} 페이지", file=sys.stderr)

    result = run_pipeline(sys.argv[1], on_progress=_progress)
    print(json.dumps(result, ensure_ascii=False, indent=2)[:2000])
