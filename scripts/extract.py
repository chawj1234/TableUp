"""Upstage 응답 → 분류 → CSV 변환.

핵심 역할:
1. element 분류: real_table / chart / chart_misid / footnote / other
2. HTML 표 → pandas DataFrame (rowspan/colspan 유지)
3. 의미 기반 파일명 생성 (캡션 슬러그화)
4. .tableup/ 출력 일체
"""
from __future__ import annotations

import io
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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

    # category == 'table' 인 경우 세부 분류
    if md.startswith(FOOTNOTE_PREFIX):
        return "footnote"

    br_count = md.count("<br>")
    has_axis = any(hint in md for hint in AXIS_HINTS)
    if br_count >= CHART_LIKE_BR_THRESHOLD and has_axis:
        return "chart_misid"

    # 숫자 밀도 기반 보수적 판정: 너무 적으면 데이터 표가 아닐 수 있음
    digit_ratio = sum(c.isdigit() for c in md) / max(len(md), 1)
    if digit_ratio < 0.01 and len(md) > 50:
        return "other"

    return "real_table"


# ----- HTML → DataFrame -----


def html_table_to_dataframe(html: str):
    """HTML 문자열의 <table> 을 pandas DataFrame 으로 변환."""
    import pandas as pd

    try:
        dfs = pd.read_html(io.StringIO(html), flavor="lxml")
    except ValueError:
        dfs = pd.read_html(io.StringIO(html), flavor="bs4")
    if not dfs:
        raise ValueError("표를 파싱할 수 없습니다.")
    return dfs[0]


# ----- 캡션 검색 & 슬러그 -----


def _element_text(el: dict) -> str:
    """caption/heading 등에서 표시용 텍스트를 꺼낸다. markdown 우선, text 폴백."""
    content = el.get("content", {})
    for field in ("markdown", "text", "html"):
        value = (content.get(field) or "").strip()
        if value:
            return value
    return ""


_CAPTION_PREFIX_RE = re.compile(r"^[<\[]?\s*(그림|표|차트|Figure|Table|Fig\.?)\s*[^>\]]*[>\]]?\s*")


def _clean_caption(raw: str) -> str:
    """캡션에서 슬러그에 불필요한 마커를 제거한다. <그림 1> 제목 → 제목."""
    cleaned = _CAPTION_PREFIX_RE.sub("", raw).strip()
    return cleaned or raw


def find_caption_before(elements: list[dict], index: int) -> str | None:
    """주어진 index 이전 10개 element 중 가장 가까운 caption 을 찾는다."""
    for j in range(index - 1, max(-1, index - 10), -1):
        cand = elements[j]
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
    preview: str  # 첫 몇 행 요약
    n_rows: int
    n_cols: int


@dataclass
class ExtractionResult:
    tables: list[ExtractedItem] = field(default_factory=list)
    charts: list[ExtractedItem] = field(default_factory=list)
    footnotes: list[dict] = field(default_factory=list)
    boundary_cases: list[dict] = field(default_factory=list)  # chart_misid 들

    def all_items(self) -> list[ExtractedItem]:
        return self.tables + self.charts


# ----- 메인 추출 -----


def extract_all(response: dict, output_dir: Path) -> ExtractionResult:
    """Upstage 응답을 분류·변환하여 output_dir 에 CSV 등을 저장한다."""
    import pandas as pd

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
                preview = df.head(3).to_markdown(index=False) if len(df) else "(빈 표)"
                result.tables.append(
                    ExtractedItem(
                        kind="table",
                        index=table_idx,
                        page=page,
                        caption=caption,
                        csv_path=path,
                        preview=preview,
                        n_rows=len(df),
                        n_cols=len(df.columns),
                    )
                )
                table_idx += 1
            except Exception as e:  # noqa: BLE001
                # 파싱 실패 시 raw HTML 로 저장
                (output_dir / fname.replace(".csv", ".html")).write_text(html, encoding="utf-8")

        elif kind in ("chart", "chart_misid"):
            caption = find_caption_before(elements, i)
            slug = slugify(caption or f"chart-p{page}")
            fname = f"c{chart_idx:02d}_p{page}_{slug}.csv"
            path = output_dir / fname
            # chart element 는 <figure> 안에 <table> 이 포함됨. 그걸 꺼냄.
            try:
                df = html_table_to_dataframe(html)
                df.to_csv(path, index=False, encoding="utf-8-sig")
                preview = df.head(3).to_markdown(index=False) if len(df) else "(빈 차트)"
                result.charts.append(
                    ExtractedItem(
                        kind="chart",
                        index=chart_idx,
                        page=page,
                        caption=caption,
                        csv_path=path,
                        preview=preview,
                        n_rows=len(df),
                        n_cols=len(df.columns),
                    )
                )
                if kind == "chart_misid":
                    result.boundary_cases.append({"page": page, "index": chart_idx, "reason": "chart-like table"})
                chart_idx += 1
            except Exception:  # noqa: BLE001
                # 차트인데 데이터 표 안 나온 경우 — 설명만 있는 차트
                pass

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
        f"# TableUp 추출 결과",
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
        lines.append("## 경계 케이스 (차트로 재분류된 항목)")
        lines.append("")
        for case in result.boundary_cases:
            lines.append(f"- 페이지 {case['page']}, 차트 #{case['index']}: {case['reason']}")
        lines.append("")

    lines.append("## 검증용 원본 이미지")
    lines.append("")
    lines.append("`sources/p<페이지>.png` 로 원본을 확인할 수 있습니다 (생성한 경우).")
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
