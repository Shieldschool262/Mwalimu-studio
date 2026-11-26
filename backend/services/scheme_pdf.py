"""Render a scheme of work as a landscape A4 PDF.

Layout is driven by the plan's template (`columns` array), so column order and labels
always match templates/cbe-scheme-v1.json rather than being hardcoded here.

The document header (school, grade, learning area, term, year, teacher) is redrawn on
every page, which is what the spec asks for.
"""
from __future__ import annotations

import textwrap
from typing import Any

import fitz  # PyMuPDF

# Landscape A4 in points.
PAGE_W, PAGE_H = 841.89, 595.28
MARGIN = 24.0

FONT = "helv"
FONT_BOLD = "hebo"
BODY_SIZE = 6.2
HEAD_SIZE = 7.0
TITLE_SIZE = 13.0
META_SIZE = 7.4
PAD = 2.6


def _wrap(text: str, width_pt: float, size: float) -> list[str]:
    if not text:
        return [""]
    # Rough characters-per-point for Helvetica: ~0.5 * size per char.
    char_w = size * 0.50
    max_chars = max(6, int(width_pt / char_w))
    lines: list[str] = []
    for para in str(text).split("\n"):
        if not para.strip():
            lines.append("")
            continue
        lines.extend(
            textwrap.wrap(para, width=max_chars, break_long_words=True, break_on_hyphens=True)
            or [""]
        )
    return lines


def _cell_text(value: Any) -> str:
    """Turn a section value into the string the teacher sees in the PDF."""
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(str(v) for v in value)
    if isinstance(value, dict):
        return str(value.get("text") or "")
    return str(value)


def _column_value(section: dict[str, Any], col: dict[str, Any]) -> str:
    key = col["key"]
    if key == "week":
        return section.get("weekLabel") or ""
    if key == "lesson":
        return section.get("lessonLabel") or ""
    if key == "strand":
        strand = section.get("strand") or ""
        code = section.get("subStrandCode") or ""
        name = section.get("subStrand") or ""
        line = f"{strand}\n{code} {name}".strip() if strand else f"{code} {name}".strip()
        # Each weekly row is a slice of the same sub-strand - label the part on paper too.
        part = section.get("partLabel")
        return f"{line}\n{part}" if part and part != "Part 1 of 1" else line
    if key == "subStrand":
        code = section.get("subStrandCode") or ""
        name = section.get("subStrand") or ""
        line = f"{code} {name}".strip()
        part = section.get("partLabel")
        return f"{line}\n{part}" if part and part != "Part 1 of 1" else line
    if key in ("outcomes", "experiences", "kiqs"):
        return _cell_text(section.get(key))
    if key == "resources":
        return _cell_text(section.get("resources"))
    if key == "assessment":
        return _cell_text(section.get("assessment"))
    if key == "reflection":
        return _cell_text(section.get("reflection"))
    return _cell_text(section.get(key))


def _draw_header(page: fitz.Page, plan: dict[str, Any]) -> float:
    """Draw the repeating document header. Returns the y where the table may start."""
    header = plan.get("header") or {}
    y = MARGIN

    page.insert_text(
        (MARGIN, y + TITLE_SIZE),
        (plan.get("typeLabel") or "SCHEME OF WORK").upper(),
        fontname=FONT_BOLD,
        fontsize=TITLE_SIZE,
    )
    y += TITLE_SIZE + 6

    def meta_line(pairs: list[tuple[str, str]]) -> None:
        nonlocal y
        x = MARGIN
        for label, value in pairs:
            txt = f"{label}: "
            page.insert_text((x, y), txt, fontname=FONT_BOLD, fontsize=META_SIZE)
            x += fitz.get_text_length(txt, fontname=FONT_BOLD, fontsize=META_SIZE)
            val = str(value or "—")
            page.insert_text((x, y), val, fontname=FONT, fontsize=META_SIZE)
            x += fitz.get_text_length(val, fontname=FONT, fontsize=META_SIZE) + 16
        y += META_SIZE + 3

    meta_line(
        [
            ("Institution / School", header.get("institution")),
            ("Grade", header.get("grade")),
            ("Learning Area", header.get("learningArea")),
        ]
    )
    meta_line(
        [
            ("Term", header.get("term")),
            ("Year", header.get("year")),
            ("Teacher", header.get("teacherName")),
            ("TSC No.", header.get("tscNo")),
        ]
    )

    gen = (header.get("generalOutcomes") or "").strip()
    if gen:
        page.insert_text(
            (MARGIN, y), "General Term Instructional Learning Outcomes: ",
            fontname=FONT_BOLD, fontsize=META_SIZE,
        )
        label_w = fitz.get_text_length(
            "General Term Instructional Learning Outcomes: ", fontname=FONT_BOLD, fontsize=META_SIZE
        )
        for i, line in enumerate(_wrap(gen, PAGE_W - MARGIN * 2 - label_w, META_SIZE)):
            page.insert_text(
                (MARGIN + (label_w if i == 0 else 0), y),
                line, fontname=FONT, fontsize=META_SIZE,
            )
            y += META_SIZE + 1.5
        y += 1.5

    return y + 4


def _draw_table_header(page: fitz.Page, columns: list[dict[str, Any]], x0: float, y: float, widths: list[float]) -> float:
    """Dark-blue header row, repeated verbatim on every page of the scheme."""
    wrapped = [_wrap(col["label"], w - PAD * 2, HEAD_SIZE) for col, w in zip(columns, widths)]
    height = max(len(lines) * (HEAD_SIZE + 1.6) + PAD * 2 for lines in wrapped)
    # Draw the background FIRST so the white text is not painted over.
    page.draw_rect(
        fitz.Rect(x0, y, x0 + sum(widths), y + height),
        color=(0.12, 0.31, 0.47), fill=(0.12, 0.31, 0.47), width=0.5,
    )
    x = x0
    for w, lines in zip(widths, wrapped):
        for i, line in enumerate(lines):
            page.insert_text(
                (x + PAD, y + PAD + HEAD_SIZE + i * (HEAD_SIZE + 1.6)),
                line, fontname=FONT_BOLD, fontsize=HEAD_SIZE, color=(1, 1, 1),
            )
        page.draw_line(
            fitz.Point(x, y), fitz.Point(x, y + height),
            color=(0.75, 0.84, 0.92), width=0.4,
        )
        x += w
    page.draw_line(
        fitz.Point(x0 + sum(widths), y), fitz.Point(x0 + sum(widths), y + height),
        color=(0.75, 0.84, 0.92), width=0.4,
    )
    return y + height


def render_scheme_pdf(plan: dict[str, Any]) -> bytes:
    columns = plan.get("columns") or []
    sections = plan.get("sections") or []

    content_w = PAGE_W - MARGIN * 2
    total_pct = sum(float(c.get("width", "0").rstrip("%") or 0) for c in columns) or 100.0
    widths = [content_w * (float(c.get("width", "0").rstrip("%") or 0) / total_pct) for c in columns]

    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)

    y = _draw_header(page, plan)
    y = _draw_table_header(page, columns, MARGIN, y, widths)

    bottom_limit = PAGE_H - MARGIN - 14

    for section in sections:
        # Measure the tallest cell in this row.
        cell_lines: list[list[str]] = []
        for col, w in zip(columns, widths):
            lines = _wrap(_column_value(section, col), w - PAD * 2, BODY_SIZE)
            cell_lines.append(lines)
        row_h = max(len(l) for l in cell_lines) * (BODY_SIZE + 1.5) + PAD * 2

        if y + row_h > bottom_limit:
            page = doc.new_page(width=PAGE_W, height=PAGE_H)
            y = _draw_header(page, plan)
            y = _draw_table_header(page, columns, MARGIN, y, widths)

        x = MARGIN
        for col, w, lines in zip(columns, widths, cell_lines):
            for i, line in enumerate(lines):
                page.insert_text(
                    (x + PAD, y + PAD + BODY_SIZE + i * (BODY_SIZE + 1.5)),
                    line, fontname=FONT, fontsize=BODY_SIZE,
                )
            x += w

        # Row grid.
        page.draw_rect(
            fitz.Rect(MARGIN, y, MARGIN + sum(widths), y + row_h),
            color=(0, 0, 0), width=0.4,
        )
        x = MARGIN
        for w in widths:
            page.draw_line(fitz.Point(x, y), fitz.Point(x, y + row_h), color=(0.45, 0.45, 0.45), width=0.35)
            x += w
        page.draw_line(
            fitz.Point(MARGIN + sum(widths), y), fitz.Point(MARGIN + sum(widths), y + row_h),
            color=(0.45, 0.45, 0.45), width=0.35,
        )
        y += row_h

    # Footer on every page: sources + template + generated date.
    footer = plan.get("footer") or {}
    sources = ", ".join(plan.get("sources") or []) or "—"
    lines = [
        str(footer.get("sourceLine", "Sources: {sources}")).format(sources=sources),
        str(footer.get("templateLine", "Template: {templateVersion}")).format(
            templateVersion=plan.get("templateVersion") or "cbe-scheme-v1"
        ),
        str(footer.get("generatedLine", "Generated: {generatedAt}")).format(
            generatedAt=(plan.get("createdAt") or "")[:10]
        ),
        str(footer.get("citationNote", "")),
    ]
    for p in doc:
        fy = PAGE_H - MARGIN - 2
        for line in reversed([l for l in lines if l]):
            p.insert_text((MARGIN, fy), line, fontname=FONT, fontsize=5.2, color=(0.35, 0.35, 0.35))
            fy -= 6.2
        p.insert_text(
            (PAGE_W - MARGIN - 30, PAGE_H - MARGIN + 2), f"p.{p.number + 1}",
            fontname=FONT, fontsize=5.2, color=(0.35, 0.35, 0.35),
        )

    out = doc.tobytes()
    doc.close()
    return out
