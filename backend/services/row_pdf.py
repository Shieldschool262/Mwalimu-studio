"""Portrait A4 PDF for the Record of Work (Phase 6).

The screen editor paginates for readability; the PDF always prints the WHOLE term.
A dedicated Gap Summary page is appended at the end. Every page carries the
school/teacher header and signature lines.
"""
from __future__ import annotations

import textwrap
from typing import Any

import fitz  # PyMuPDF

PAGE_W, PAGE_H = 595.28, 841.89  # Portrait A4
MARGIN = 24.0
FONT = "helv"
FONT_BOLD = "hebo"
FONT_ITALIC = "heit"
BODY_SIZE = 5.6
HEAD_SIZE = 5.7
TITLE_SIZE = 12.0
META_SIZE = 7.2
PAD = 2.2

COLUMNS: list[tuple[str, str, float]] = [
    ("Date", "date", 46.0),
    ("Week", "week", 25.0),
    ("Lesson", "lesson", 28.0),
    ("Strand / Sub-Strand", "strandSub", 88.0),
    ("Focus", "focus", 62.0),
    ("Work Done", "workDone", 104.0),
    ("Reflection", "reflection", 92.0),
    ("Status", "status", 56.0),
    ("Signature", "signature", 47.0),
]

STATUS_SHORT = {
    "Taught": "Taught",
    "Partially Taught": "Partially",
    "Not Taught - Carry Over": "Carry Over",
    "Not Taught - Skipped": "Skipped",
}


def _wrap(text: Any, width_pt: float, size: float) -> list[str]:
    text = "" if text is None else str(text)
    if not text.strip():
        return [""]
    char_w = size * 0.50
    max_chars = max(5, int(width_pt / char_w))
    lines: list[str] = []
    for para in text.split("\n"):
        if not para.strip():
            lines.append("")
            continue
        lines.extend(
            textwrap.wrap(
                para, width=max_chars, break_long_words=True, break_on_hyphens=True
            )
            or [""]
        )
    return lines


def _cell(row: dict[str, Any], key: str) -> str:
    if key == "strandSub":
        return " / ".join(
            x for x in (str(row.get("strand") or ""), str(row.get("subStrand") or "")) if x
        )
    if key == "focus":
        return str(row.get("focusKeyword") or "")
    if key == "status":
        return STATUS_SHORT.get(row.get("status") or "", str(row.get("status") or ""))
    if key == "date":
        return str(row.get("date") or "")
    if key in ("week", "lesson"):
        return str(row.get(key) or "")
    return str(row.get(key) or "")


def _draw_header(page: fitz.Page, doc: dict[str, Any], widths: list[float]) -> float:
    """School, Grade, Learning Area, Term, Year, Teacher, TSC No - on every page."""
    h = doc.get("header") or {}
    y = MARGIN
    page.insert_text(
        (MARGIN, y + TITLE_SIZE),
        "RECORD OF WORK",
        fontname=FONT_BOLD,
        fontsize=TITLE_SIZE,
    )
    status = doc.get("status") or "Draft"
    label = doc.get("finalVersionLabel") or status
    page.insert_text(
        (PAGE_W - MARGIN - fitz.get_text_length(label, fontname=FONT_BOLD, fontsize=META_SIZE), y + TITLE_SIZE),
        label,
        fontname=FONT_BOLD,
        fontsize=META_SIZE,
    )
    y += TITLE_SIZE + 6

    def meta_line(pairs: list[tuple[str, str]]) -> None:
        nonlocal y
        x = MARGIN
        for name, value in pairs:
            head = f"{name}: "
            page.insert_text((x, y), head, fontname=FONT_BOLD, fontsize=META_SIZE)
            x += fitz.get_text_length(head, fontname=FONT_BOLD, fontsize=META_SIZE)
            val = str(value or "—")
            page.insert_text((x, y), val, fontname=FONT, fontsize=META_SIZE)
            x += fitz.get_text_length(val, fontname=FONT, fontsize=META_SIZE) + 12
        y += META_SIZE + 3

    meta_line(
        [
            ("School", h.get("school") or h.get("institution")),
            ("Grade", h.get("grade")),
            ("Learning Area", h.get("learningArea")),
        ]
    )
    meta_line(
        [
            ("Term", h.get("term")),
            ("Year", h.get("year")),
            ("Teacher", h.get("teacher")),
            ("TSC No.", h.get("tscNo")),
        ]
    )
    return y + 3


def _draw_table_header(page: fitz.Page, widths: list[float], y: float) -> float:
    height = max(
        len(_wrap(col[0], w - PAD * 2, HEAD_SIZE)) * (HEAD_SIZE + 1.5) + PAD * 2
        for col, w in zip(COLUMNS, widths)
    )
    rect = fitz.Rect(MARGIN, y, MARGIN + sum(widths), y + height)
    page.draw_rect(rect, color=(0, 0, 0), fill=(0.90, 0.93, 0.90), width=0.5)
    x = MARGIN
    for col, w in zip(COLUMNS, widths):
        for i, line in enumerate(_wrap(col[0], w - PAD * 2, HEAD_SIZE)):
            page.insert_text(
                (x + PAD, y + PAD + HEAD_SIZE + i * (HEAD_SIZE + 1.5)),
                line,
                fontname=FONT_BOLD,
                fontsize=HEAD_SIZE,
            )
        page.draw_line(
            fitz.Point(x, y), fitz.Point(x, y + height), color=(0, 0, 0), width=0.4
        )
        x += w
    page.draw_line(
        fitz.Point(MARGIN + sum(widths), y),
        fitz.Point(MARGIN + sum(widths), y + height),
        color=(0, 0, 0),
        width=0.4,
    )
    return y + height


def _draw_footer(page: fitz.Page) -> None:
    bottom = PAGE_H - MARGIN
    page.draw_line(
        fitz.Point(MARGIN, bottom - 32),
        fitz.Point(PAGE_W - MARGIN, bottom - 32),
        color=(0.6, 0.6, 0.6),
        width=0.5,
    )
    page.insert_text(
        (MARGIN, bottom - 21),
        "Teacher's Signature: __________________________     Date: ______________",
        fontname=FONT,
        fontsize=6.4,
    )
    page.insert_text(
        (MARGIN, bottom - 10),
        "Checked by: _______________________     Date: ______________",
        fontname=FONT,
        fontsize=6.4,
    )
    page.insert_text(
        (PAGE_W - MARGIN - 30, bottom + 4),
        f"p.{page.number + 1}",
        fontname=FONT,
        fontsize=5.2,
        color=(0.35, 0.35, 0.35),
    )


def _new_page(doc: fitz.Document, document: dict[str, Any], widths: list[float]) -> tuple[fitz.Page, float]:
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    y = _draw_header(page, document, widths)
    return page, _draw_table_header(page, widths, y)


def _gap_summary_page(doc: fitz.Document, document: dict[str, Any]) -> None:
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    cov = document.get("coverage") or {}
    # The school/teacher header is repeated on the Gap Summary page too.
    y = _draw_header(page, document, [])
    page.insert_text(
        (MARGIN, y + TITLE_SIZE), "GAP SUMMARY", fontname=FONT_BOLD, fontsize=TITLE_SIZE
    )
    y += TITLE_SIZE + 14
    lines = [
        f"Planned: {cov.get('planned', 0)} lessons",
        f"Taught: {cov.get('taught', 0)}",
        f"Partially Taught: {cov.get('partially', 0)}",
        f"Not Taught: {cov.get('notTaught', 0)}",
        f"Carry Over: {cov.get('carryOver', 0)}",
        f"Coverage: {cov.get('coverageLabel', '0/0 (0%)')}",
    ]
    for line in lines:
        page.insert_text((MARGIN, y), line, fontname=FONT, fontsize=9.0)
        y += 13
    y += 8
    page.insert_text(
        (MARGIN, y), "Gaps (not taught / partially taught):", fontname=FONT_BOLD, fontsize=9.0
    )
    y += 14
    gaps = cov.get("gaps") or []
    if not gaps:
        page.insert_text(
            (MARGIN, y), "No gaps recorded.", fontname=FONT_ITALIC, fontsize=8.5
        )
        y += 12
    else:
        for g in gaps:
            reason = f" ({g['reason']})" if g.get("reason") else ""
            line = (
                f"Week {g.get('week')} Lesson {g.get('lesson')} - "
                f"{STATUS_SHORT.get(g.get('status'), g.get('status'))}{reason}"
            )
            for wrapped in _wrap(line, PAGE_W - MARGIN * 2, 8.5):
                page.insert_text((MARGIN, y), wrapped, fontname=FONT, fontsize=8.5)
                y += 12
                if y > PAGE_H - MARGIN - 45:
                    page = doc.new_page(width=PAGE_W, height=PAGE_H)
                    y = _draw_header(page, document, []) + 12
    if cov.get("warning"):
        y += 8
        page.insert_text(
            (MARGIN, y), str(cov["warning"]), fontname=FONT_BOLD, fontsize=8.5
        )


def render_row_pdf(document: dict[str, Any]) -> bytes:
    doc = fitz.open()
    content_w = PAGE_W - MARGIN * 2
    base_w = sum(w for _, _, w in COLUMNS)
    widths = [w * content_w / base_w for _, _, w in COLUMNS]

    page, y = _new_page(doc, document, widths)
    bottom_limit = PAGE_H - MARGIN - 42

    rows = document.get("rows") or []
    if not rows:
        page.insert_text(
            (MARGIN, y + 12),
            "No Record of Work rows generated yet.",
            fontname=FONT_ITALIC,
            fontsize=8.0,
        )

    for row in rows:
        cells = [
            _wrap(_cell(row, col[1]), w - PAD * 2, BODY_SIZE)
            for col, w in zip(COLUMNS, widths)
        ]
        row_h = max(len(c) for c in cells) * (BODY_SIZE + 1.5) + PAD * 2
        if y + row_h > bottom_limit:
            page, y = _new_page(doc, document, widths)

        x = MARGIN
        for (_, key, _), w, lines in zip(COLUMNS, widths, cells):
            font = FONT_ITALIC if key == "workDone" and row.get("isPlanned") else FONT
            for i, line in enumerate(lines):
                page.insert_text(
                    (x + PAD, y + PAD + BODY_SIZE + i * (BODY_SIZE + 1.5)),
                    line,
                    fontname=font,
                    fontsize=BODY_SIZE,
                    color=(0.45, 0.45, 0.45) if font == FONT_ITALIC else (0, 0, 0),
                )
            x += w
        page.draw_rect(
            fitz.Rect(MARGIN, y, MARGIN + sum(widths), y + row_h),
            color=(0, 0, 0),
            width=0.4,
        )
        x = MARGIN
        for w in widths:
            page.draw_line(
                fitz.Point(x, y),
                fitz.Point(x, y + row_h),
                color=(0.45, 0.45, 0.45),
                width=0.35,
            )
            x += w
        page.draw_line(
            fitz.Point(MARGIN + sum(widths), y),
            fitz.Point(MARGIN + sum(widths), y + row_h),
            color=(0.45, 0.45, 0.45),
            width=0.35,
        )
        y += row_h

    _gap_summary_page(doc, document)
    for p in doc:
        _draw_footer(p)
    out = doc.tobytes()
    doc.close()
    return out
