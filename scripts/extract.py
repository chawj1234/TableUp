"""Upstage 응답 → 분류 → CSV 변환.

핵심 역할:
1. element 분류: real_table / chart / chart_misid / footnote / other
2. HTML 표 → pandas DataFrame (rowspan/colspan 은 pandas read_html 기본 동작에 위임 —
   병합 셀은 NaN·값 복제로 펼쳐지므로 원본 merge 구조는 보존되지 않음)
3. 의미 기반 파일명 생성 (캡션 슬러그화)
4. .tableup/ 출력 일체

참고: 현재 분류 규칙(각주 접두·축값 힌트)은 한국 공공·금융 문서를
기준으로 튜닝되어 있다. 다른 locale 문서에 적용 시 규칙 확장 필요.
"""
from __future__ import annotations

import io
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

# ----- 분류 -----

# 각주/출처 테이블 패턴 (실제 데이터 표가 아님)
FOOTNOTE_PREFIX = ("| 주:", "| 자료:", "주:", "자료:", "|주:", "|자료:")

# 차트 오분류 감지: <br> 과다 + 축값 패턴
CHART_LIKE_BR_THRESHOLD = 3
AXIS_HINTS = ("조원", "천조", "(%)", "(pp)", "/4")


def classify_element(el: dict) -> str:
    """element 를 분류한다.

    반환: 'real_table' | 'chart' | 'chart_misid' | 'footnote' | 'other'
    """
    category = el.get("category", "")
    content = el.get("content", {})
    md = (content.get("markdown") or "").strip()

    if category == "chart":
        return "chart"

    if category != "table":
        return "other"

    if md.startswith(FOOTNOTE_PREFIX):
        return "footnote"

    br_count = md.count("<br>")
    has_axis = any(hint in md for hint in AXIS_HINTS)
    if br_count >= CHART_LIKE_BR_THRESHOLD and has_axis:
        return "chart_misid"

    # 숫자 밀도가 극히 낮으면 데이터 표가 아닐 수 있음
    digit_ratio = sum(c.isdigit() for c in md) / max(len(md), 1)
    if digit_ratio < 0.01 and len(md) > 50:
        return "other"

    return "real_table"


# ----- HTML → DataFrame -----


def html_table_to_dataframe(html: str) -> pd.DataFrame:
    """HTML 문자열의 <table> 을 pandas DataFrame 으로 변환한다."""
    try:
        dfs = pd.read_html(io.StringIO(html), flavor="lxml")
    except (ValueError, ImportError):
        dfs = pd.read_html(io.StringIO(html), flavor="bs4")
    if not dfs:
        raise ValueError("표를 파싱할 수 없습니다.")
    return dfs[0]


# ----- 캡션 검색 & 슬러그 -----


def _element_text(el: dict) -> str:
    """caption/heading 등에서 표시용 텍스트를 꺼낸다. markdown 우선, text 폴백."""
    content = el.get("content", {})
    for key in ("markdown", "text", "html"):
        value = (content.get(key) or "").strip()
        if value:
            return value
    return ""


_CAPTION_PREFIX_RE = re.compile(r"^[<\[]?\s*(그림|표|차트|Figure|Table|Fig\.?)\s*[^>\]]*[>\]]?\s*")


def _clean_caption(raw: str) -> str:
    """캡션에서 슬러그에 불필요한 마커를 제거한다. <그림 1> 제목 → 제목."""
    cleaned = _CAPTION_PREFIX_RE.sub("", raw).strip()
    return cleaned or raw


def find_caption_before(elements: list[dict], index: int) -> str | None:
    """주어진 index 이전 10개 element 중 같은 페이지 안의 가장 가까운 caption 을 찾는다.

    페이지 경계를 넘어 이전 페이지의 caption 이 현재 표/차트에 잘못 붙는 오매칭을 방지한다.
    """
    target_page = elements[index].get("page")
    for j in range(index - 1, max(-1, index - 10), -1):
        cand = elements[j]
        if target_page is not None and cand.get("page") != target_page:
            break
        cat = cand.get("category")
        if cat == "caption":
            raw = _element_text(cand)
            if raw:
                return _clean_caption(raw)
        if cat == "heading1":
            raw = _element_text(cand)
            if raw and len(raw) < 50:
                return _clean_caption(raw)
    return None


_SLUG_BANNED = re.compile(r"[^0-9A-Za-z가-힣\- ]+")


def slugify(text: str, max_length: int = 40) -> str:
    """파일명 안전 슬러그를 만든다. 한글 유지, 공백 → -, 금지문자 제거."""
    if not text:
        return "untitled"
    text = unicodedata.normalize("NFC", text).strip()
    text = _SLUG_BANNED.sub("", text)
    text = re.sub(r"\s+", "-", text).strip("-")
    return text[:max_length] or "untitled"


# ----- 결과 구조 -----


@dataclass
class ExtractedItem:
    kind: str  # 'table' | 'chart'
    index: int
    page: int
    caption: str | None
    csv_path: Path
    n_rows: int
    n_cols: int


@dataclass
class ExtractionResult:
    tables: list[ExtractedItem] = field(default_factory=list)
    charts: list[ExtractedItem] = field(default_factory=list)
    footnotes: list[dict] = field(default_factory=list)
    boundary_cases: list[dict] = field(default_factory=list)

    def all_items(self) -> list[ExtractedItem]:
        return self.tables + self.charts


# ----- 메인 추출 -----


def _save_html_fallback(
    output_dir: Path,
    prefix: str,
    index: int,
    page: int,
    slug: str,
    html: str,
) -> Path:
    """파싱 실패 시 raw HTML 을 저장한다."""
    fname = f"{prefix}{index:02d}_p{page}_{slug}.html"
    path = output_dir / fname
    path.write_text(html, encoding="utf-8")
    return path


def extract_all(response: dict, output_dir: Path) -> ExtractionResult:
    """Upstage 응답을 분류·변환하여 output_dir 에 CSV 등을 저장한다."""
    output_dir.mkdir(parents=True, exist_ok=True)
    elements = response.get("elements", [])
    result = ExtractionResult()

    table_idx = 0
    chart_idx = 0

    for i, el in enumerate(elements):
        kind = classify_element(el)
        page = el.get("page", 0)
        html = el.get("content", {}).get("html", "")

        if kind == "real_table":
            caption = find_caption_before(elements, i)
            slug = slugify(caption or f"table-p{page}")
            fname = f"t{table_idx:02d}_p{page}_{slug}.csv"
            path = output_dir / fname
            try:
                df = html_table_to_dataframe(html)
                df.to_csv(path, index=False, encoding="utf-8-sig")
                result.tables.append(
                    ExtractedItem(
                        kind="table",
                        index=table_idx,
                        page=page,
                        caption=caption,
                        csv_path=path,
                        n_rows=len(df),
                        n_cols=len(df.columns),
                    )
                )
            except Exception as e:  # noqa: BLE001
                fb = _save_html_fallback(output_dir, "t", table_idx, page, slug, html)
                result.boundary_cases.append(
                    {
                        "page": page,
                        "index": table_idx,
                        "reason": f"table HTML parse failed: {type(e).__name__}",
                        "fallback_path": str(fb.relative_to(output_dir)),
                    }
                )
            finally:
                table_idx += 1

        elif kind in ("chart", "chart_misid"):
            caption = find_caption_before(elements, i)
            slug = slugify(caption or f"chart-p{page}")
            fname = f"c{chart_idx:02d}_p{page}_{slug}.csv"
            path = output_dir / fname
            try:
                df = html_table_to_dataframe(html)
                df.to_csv(path, index=False, encoding="utf-8-sig")
                result.charts.append(
                    ExtractedItem(
                        kind="chart",
                        index=chart_idx,
                        page=page,
                        caption=caption,
                        csv_path=path,
                        n_rows=len(df),
                        n_cols=len(df.columns),
                    )
                )
                if kind == "chart_misid":
                    result.boundary_cases.append(
                        {"page": page, "index": chart_idx, "reason": "chart-like table"}
                    )
                chart_idx += 1
            except Exception as e:  # noqa: BLE001
                # 차트 안에 데이터 표가 없는 케이스 (설명만 있음 / HTML 파싱 실패)
                # 조용히 스킵하면 사용자가 누락을 인지 못 하므로 boundary_cases 에 남긴다.
                fb = _save_html_fallback(output_dir, "c", chart_idx, page, slug, html)
                result.boundary_cases.append(
                    {
                        "page": page,
                        "index": chart_idx,
                        "reason": f"chart parse failed: {type(e).__name__}: {str(e)[:120]}",
                        "fallback_path": str(fb.relative_to(output_dir)),
                    }
                )
                chart_idx += 1

        elif kind == "footnote":
            result.footnotes.append(
                {
                    "page": page,
                    "markdown": (el.get("content", {}).get("markdown") or "").strip(),
                }
            )

    return result


# ----- index.md 생성 -----


def write_index_md(
    result: ExtractionResult, output_dir: Path, *, source_name: str, total_pages: int
) -> None:
    lines = [
        "# TableUp 추출 결과",
        "",
        f"- 원본: `{source_name}`",
        f"- 총 페이지: {total_pages}",
        f"- 표: {len(result.tables)}, 차트: {len(result.charts)}, 각주: {len(result.footnotes)}",
        "",
    ]

    if result.tables:
        lines.append("## 표 (Tables)")
        lines.append("")
        lines.append("| 파일 | 페이지 | 제목 | 크기 |")
        lines.append("|---|---|---|---|")
        for t in result.tables:
            title = t.caption or "(제목 없음)"
            lines.append(
                f"| `{t.csv_path.name}` | p.{t.page} | {title} | {t.n_rows}×{t.n_cols} |"
            )
        lines.append("")

    if result.charts:
        lines.append("## 차트 (Charts → Data)")
        lines.append("")
        lines.append("| 파일 | 페이지 | 제목 | 크기 |")
        lines.append("|---|---|---|---|")
        for c in result.charts:
            title = c.caption or "(제목 없음)"
            lines.append(
                f"| `{c.csv_path.name}` | p.{c.page} | {title} | {c.n_rows}×{c.n_cols} |"
            )
        lines.append("")

    if result.boundary_cases:
        lines.append("## 경계 케이스")
        lines.append("")
        for case in result.boundary_cases:
            reason = case.get("reason", "")
            fb = case.get("fallback_path")
            extra = f" → `{fb}`" if fb else ""
            lines.append(f"- 페이지 {case['page']}, #{case['index']}: {reason}{extra}")
        lines.append("")

    lines.append("## 검증용 원본 이미지")
    lines.append("")
    lines.append("`sources/p<페이지>.png` 로 원본을 확인할 수 있습니다 (PDF 처리 시 생성).")
    lines.append("")

    (output_dir / "index.md").write_text("\n".join(lines), encoding="utf-8")


def write_meta_json(
    result: ExtractionResult,
    output_dir: Path,
    *,
    source_sha256: str,
    source_name: str,
    model: str,
    total_pages: int,
) -> None:
    meta = {
        "source": {"name": source_name, "sha256": source_sha256, "pages": total_pages},
        "model": model,
        "counts": {
            "tables": len(result.tables),
            "charts": len(result.charts),
            "footnotes": len(result.footnotes),
        },
        "footnotes": result.footnotes,
        "boundary_cases": result.boundary_cases,
        "files": [
            {
                "type": item.kind,
                "path": str(item.csv_path.relative_to(output_dir)),
                "page": item.page,
                "caption": item.caption,
                "rows": item.n_rows,
                "cols": item.n_cols,
            }
            for item in result.all_items()
        ],
    }
    (output_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
