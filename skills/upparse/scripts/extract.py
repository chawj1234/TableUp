"""Upstage 응답 → 분류 → CSV 변환.

핵심 역할:
1. element 분류: real_table / chart / chart_misid / footnote / other
2. HTML 표 → pandas DataFrame (rowspan/colspan 은 pandas read_html 기본 동작에 위임 —
   병합 셀은 NaN·값 복제로 펼쳐지므로 원본 merge 구조는 보존되지 않음)
3. 의미 기반 파일명 생성 (캡션 슬러그화)
4. .upparse/ 출력 일체

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


_FIGURE_TYPE_RE = re.compile(
    r'<p[^>]*class="figure-type"[^>]*>(.*?)</p>', re.DOTALL | re.IGNORECASE
)
_FIGURE_DESC_RE = re.compile(
    r'<p[^>]*class="figure-description"[^>]*>(.*?)</p>', re.DOTALL | re.IGNORECASE
)


def parse_figure_content(el: dict) -> tuple[str, str]:
    """figure element 의 figcaption 에서 type·description 을 뽑는다.

    Upstage 는 figure 를 `<figure><img/><figcaption><p class="figure-type">...</p>
    <p class="figure-description">...</p></figcaption></figure>` 형태로 반환한다.
    둘 다 없으면 빈 문자열 반환.
    """
    html = el.get("content", {}).get("html", "") or ""
    ftype = ""
    fdesc = ""
    m = _FIGURE_TYPE_RE.search(html)
    if m:
        ftype = re.sub(r"\s+", " ", m.group(1)).strip()
    m = _FIGURE_DESC_RE.search(html)
    if m:
        fdesc = re.sub(r"\s+", " ", m.group(1)).strip()
    return ftype, fdesc


def classify_element(el: dict) -> str:
    """element 를 분류한다.

    반환: 'real_table' | 'chart' | 'chart_misid' | 'figure' | 'footnote' | 'other'
    """
    category = el.get("category", "")
    content = el.get("content", {})
    md = (content.get("markdown") or "").strip()

    if category == "chart":
        return "chart"

    if category == "figure":
        return "figure"

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
class ExtractedFigure:
    """데이터 표/차트 아닌 시각 자료 (다이어그램·플로차트·스키마·사진 등).

    Upstage 가 `category=figure` 로 반환한 요소를 수집해 meta.figures 로 기록한다.
    숫자 데이터가 없어 CSV 로 만들진 않지만, "p.N 에 뭐가 있었지?" 류 질문에 답하는
    근거로 사용된다. figure_type / description 은 Upstage 가 figcaption 으로 제공.
    """
    index: int
    page: int
    figure_type: str  # 예: "diagram,timeline,schematic"
    description: str
    caption: str | None


@dataclass
class ExtractionResult:
    tables: list[ExtractedItem] = field(default_factory=list)
    charts: list[ExtractedItem] = field(default_factory=list)
    figures: list[ExtractedFigure] = field(default_factory=list)
    footnotes: list[dict] = field(default_factory=list)
    boundary_cases: list[dict] = field(default_factory=list)

    def all_items(self) -> list[ExtractedItem]:
        return self.tables + self.charts

    def pages_with_visuals(self) -> set[int]:
        """표·차트·도식 중 하나라도 있는 페이지 집합."""
        pages = {item.page for item in self.all_items() if item.page}
        pages.update(f.page for f in self.figures if f.page)
        return pages


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
    figure_idx = 0

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

        elif kind == "figure":
            # 다이어그램·플로차트·사진 등 시각 자료. 데이터 테이블이 아니므로 CSV 미생성,
            # 단 meta/index 에 존재 자체를 남겨 사용자가 "p.N 에 뭐 있었지?" 에 답할 수 있게 한다.
            ftype, fdesc = parse_figure_content(el)
            caption = find_caption_before(elements, i)
            result.figures.append(
                ExtractedFigure(
                    index=figure_idx,
                    page=page,
                    figure_type=ftype,
                    description=fdesc,
                    caption=caption,
                )
            )
            figure_idx += 1

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
        "# UpParse 추출 결과",
        "",
        f"- 원본: `{source_name}`",
        f"- 총 페이지: {total_pages}",
        f"- 표: {len(result.tables)}, 차트: {len(result.charts)}, "
        f"도식: {len(result.figures)}, 각주: {len(result.footnotes)}",
        "",
    ]

    # 페이지별 요소 맵 — "p.N 에 뭐 있었지?" 를 index.md 한 곳에서 해결
    if total_pages and (result.tables or result.charts or result.figures):
        page_counts: dict[int, dict[str, int]] = {}
        for t in result.tables:
            page_counts.setdefault(t.page, {"t": 0, "c": 0, "f": 0})["t"] += 1
        for c in result.charts:
            page_counts.setdefault(c.page, {"t": 0, "c": 0, "f": 0})["c"] += 1
        for f in result.figures:
            page_counts.setdefault(f.page, {"t": 0, "c": 0, "f": 0})["f"] += 1
        if page_counts:
            lines.append("## 페이지별 요소 맵")
            lines.append("")
            lines.append("| 페이지 | 표 | 차트 | 도식 |")
            lines.append("|---:|---:|---:|---:|")
            for pno in sorted(page_counts):
                c = page_counts[pno]
                lines.append(f"| p.{pno} | {c['t']} | {c['c']} | {c['f']} |")
            lines.append("")

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

    if result.figures:
        lines.append("## 도식·다이어그램 (Figures)")
        lines.append("")
        lines.append("데이터 표가 아닌 시각 자료. CSV 는 만들어지지 않으며, 수치 확인이 필요하면")
        lines.append("`sources/p<페이지>.png` 를 직접 확인하세요.")
        lines.append("")
        lines.append("| 페이지 | 유형 | 제목 | 설명 (요약) |")
        lines.append("|---|---|---|---|")
        for f in result.figures:
            title = f.caption or "(제목 없음)"
            ftype = f.figure_type or "—"
            desc = (f.description or "").replace("|", "\\|")
            desc_short = desc[:80] + ("…" if len(desc) > 80 else "")
            lines.append(f"| p.{f.page} | {ftype} | {title} | {desc_short or '—'} |")
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
            "figures": len(result.figures),
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
        "figures": [
            {
                "index": f.index,
                "page": f.page,
                "figure_type": f.figure_type,
                "description": f.description,
                "caption": f.caption,
            }
            for f in result.figures
        ],
    }
    (output_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
