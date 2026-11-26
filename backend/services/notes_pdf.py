"""Render learner-facing Lesson Notes as a PORTRAIT A4 PDF.

The learner edition is deliberately different from a lesson plan: large type for primary,
short paragraphs, picture placeholders, numbered worked steps and practice answers that
are HIDDEN unless the teacher explicitly asks for them (``show_answers=True``).
"""
from __future__ import annotations

import textwrap
from typing import Any

import fitz
from services.lesson_templates import load_notes_template

PAGE_W, PAGE_H = 595.28, 841.89
MARGIN = 46.0
PAGE_BOTTOM = PAGE_H - MARGIN - 20

FONT = "helv"
FONT_BOLD = "hebo"
FONT_ITALIC = "heit"


def _wrap(text: str, width_pt: float, size: float) -> list[str]:
    if not text:
        return [""]
    char_w = size * 0.50
    max_chars = max(10, int(width_pt / char_w))
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


def _draw_compact_header(page: fitz.Page, note: dict[str, Any], size: float = 7.5) -> float:
    title = str(note.get("title") or "Lesson Notes")
    page.insert_text((MARGIN, MARGIN), "LESSON NOTES", fontname=FONT_BOLD, fontsize=size)
    label = f"Week {note.get('week')} · Lesson {note.get('lesson')} · {title}"
    page.insert_text(
        (MARGIN + 88, MARGIN), label[:110], fontname=FONT, fontsize=size,
        color=(0.35, 0.35, 0.35),
    )
    page.draw_line(
        fitz.Point(MARGIN, MARGIN + 6), fitz.Point(PAGE_W - MARGIN, MARGIN + 6), width=0.6
    )
    return MARGIN + 22


def _new_page(doc: fitz.Document, note: dict[str, Any], body: float) -> tuple[fitz.Page, float]:
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    return page, _draw_compact_header(page, note)


def _ensure(
    doc: fitz.Document,
    note: dict[str, Any],
    page: fitz.Page,
    y: float,
    need: float,
    body: float,
) -> tuple[fitz.Page, float]:
    if y + need > PAGE_BOTTOM:
        return _new_page(doc, note, body)
    return page, y


def _heading(page: fitz.Page, y: float, text: str, size: float) -> float:
    page.insert_text((MARGIN, y + size), text, fontname=FONT_BOLD, fontsize=size)
    return y + size + 6


def _para(
    doc: fitz.Document,
    note: dict[str, Any],
    page: fitz.Page,
    y: float,
    text: str,
    body: float,
    *,
    indent: float = 0.0,
    color: tuple[float, float, float] = (0.1, 0.1, 0.1),
    italic: bool = False,
    bold: bool = False,
) -> tuple[fitz.Page, float]:
    font = FONT_BOLD if bold else (FONT_ITALIC if italic else FONT)
    width = PAGE_W - MARGIN * 2 - indent
    for line in _wrap(text, width, body):
        page, y = _ensure(doc, note, page, y, body + 3, body)
        if line:
            page.insert_text(
                (MARGIN + indent, y + body), line, fontname=font, fontsize=body, color=color
            )
        y += body + 2.4
    return page, y


def _footer_pages(doc: fitz.Document, note: dict[str, Any]) -> None:
    for p in doc:
        p.insert_text(
            (MARGIN, PAGE_H - MARGIN + 6),
            f"{note.get('subject') or ''} · Week {note.get('week')} · Lesson {note.get('lesson')}",
            fontname=FONT,
            fontsize=6.5,
            color=(0.45, 0.45, 0.45),
        )
        p.insert_text(
            (PAGE_W - MARGIN - 28, PAGE_H - MARGIN + 6),
            f"p.{p.number + 1}",
            fontname=FONT,
            fontsize=6.5,
            color=(0.45, 0.45, 0.45),
        )


def render_notes_pdf(note: dict[str, Any], show_answers: bool = False) -> bytes:
    template = load_notes_template(note.get("templateVersion"), note.get("grade"))
    body = float(template.get("bodySize") or 11.0)
    head = float(template.get("headingSize") or 12.5)
    sections = note.get("sections") or []

    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    y = _draw_compact_header(page, note)

    title_section = next((s for s in sections if s.get("key") == "title"), None)
    if title_section:
        title = str(title_section.get("body") or note.get("title") or "Lesson Notes")
        y = _heading(page, y + 4, title, head + 6)
        meta = (
            f"Week {note.get('week')} · Lesson {note.get('lesson')} of "
            f"{note.get('lessonCount')} · Focus: {note.get('focus') or '—'}"
        )
        page, y = _para(doc, note, page, y, meta, body * 0.82, color=(0.35, 0.35, 0.35))
        y += 4

    for section in sections:
        key = str(section.get("key") or "")
        if key in ("title", "footer"):
            continue
        title = str(section.get("title") or key)
        text = str(section.get("body") or "")
        data = section.get("data") or {}

        if key == "vocabulary":
            page, y = _ensure(doc, note, page, y, 52, body)
            page = page
            y = _heading(page, y, title, head)
            items = data.get("items") or []
            if not items:
                page, y = _para(doc, note, page, y, "(No vocabulary yet.)", body, italic=True)
            for item in items:
                word = str(item.get("word") or "")
                definition = str(item.get("definition") or "")
                example = str(item.get("example") or "")
                source = str(item.get("source") or "")
                page, y = _ensure(doc, note, page, y, body * 3, body)
                page.insert_text(
                    (MARGIN + 4, y + body), f"{word}:", fontname=FONT_BOLD, fontsize=body
                )
                word_w = fitz.get_text_length(f"{word}: ", fontname=FONT_BOLD, fontsize=body)
                first = True
                for line in _wrap(definition, PAGE_W - MARGIN * 2 - 8 - word_w, body):
                    page.insert_text(
                        (MARGIN + 4 + word_w, y + body), line, fontname=FONT, fontsize=body
                    )
                    y += body + 2
                    first = False
                if first:
                    y += body + 2
                if example:
                    page, y = _para(
                        doc, note, page, y, f"Example: {example}", body * 0.95, indent=12,
                        italic=True,
                    )
                if source:
                    page, y = _para(
                        doc, note, page, y, f"[{source}]", body * 0.72, indent=12,
                        color=(0.45, 0.45, 0.45),
                    )
                y += 2
            y += 4
            continue

        if key == "whatIs":
            page, y = _ensure(doc, note, page, y, 54, body)
            y = _heading(page, y, title, head)
            paragraphs = [p for p in text.split("\n\n") if p.strip()]
            if not paragraphs:
                page, y = _para(doc, note, page, y, "(Teacher to complete)", body, italic=True)
            for para in paragraphs:
                page, y = _para(doc, note, page, y, para, body)
                y += 2
            y += 4
            continue

        if key == "examples":
            page, y = _ensure(doc, note, page, y, 46, body)
            y = _heading(page, y, title, head)
            items = data.get("items") or []
            if not items:
                page, y = _para(doc, note, page, y, "(No examples yet.)", body, italic=True)
            for item in items:
                item_text = str(item.get("text") if isinstance(item, dict) else item)
                is_placeholder = item_text.startswith("[")
                page, y = _para(
                    doc,
                    note,
                    page,
                    y,
                    ("- " if not is_placeholder else "") + item_text,
                    body * (0.95 if not is_placeholder else 0.9),
                    indent=6,
                    italic=is_placeholder,
                    color=(0.25, 0.25, 0.25) if is_placeholder else (0.1, 0.1, 0.1),
                )
                y += 1
            y += 4
            continue

        if key == "workedExample":
            page, y = _ensure(doc, note, page, y, 46, body)
            y = _heading(page, y, title, head)
            steps = data.get("steps") or []
            if not steps and text:
                steps = [ln.strip() for ln in text.splitlines() if ln.strip()]
            for i, step in enumerate(steps, 1):
                page, y = _para(doc, note, page, y, f"{i}. {step}", body, indent=6)
                y += 1
            if not steps:
                page, y = _para(doc, note, page, y, "(Teacher to complete)", body, italic=True)
            y += 4
            continue

        if key == "practice":
            page, y = _ensure(doc, note, page, y, 52, body)
            y = _heading(page, y, title, head)
            page, y = _para(
                doc,
                note,
                page,
                y,
                "Answers are hidden for practice. Ask your teacher to show them."
                if not show_answers
                else "Answers are shown below each question.",
                body * 0.8,
                italic=True,
                color=(0.4, 0.4, 0.4),
            )
            items = data.get("items") or []
            if not items:
                page, y = _para(doc, note, page, y, "(No questions yet.)", body, italic=True)
            for i, item in enumerate(items, 1):
                question = str(item.get("question") or "")
                answer = str(item.get("answer") or "")
                page, y = _para(doc, note, page, y, f"{i}. {question}", body, indent=4)
                if show_answers and answer:
                    page, y = _para(
                        doc,
                        note,
                        page,
                        y,
                        f"Answer: {answer}",
                        body * 0.9,
                        indent=18,
                        italic=True,
                        color=(0.15, 0.35, 0.2),
                    )
                y += 2
            y += 4
            continue

        if key == "remember":
            page, y = _ensure(doc, note, page, y, 48, body)
            y = _heading(page, y, title, head)
            box_h = max(30, len(_wrap(text, PAGE_W - MARGIN * 2 - 20, body)) * (body + 3) + 14)
            page.draw_rect(
                fitz.Rect(MARGIN, y, PAGE_W - MARGIN, y + box_h),
                color=(0.2, 0.45, 0.3),
                fill=(0.94, 0.98, 0.94),
                width=0.8,
            )
            page, y = _para(doc, note, page, y + 7, text, body, indent=10)
            y = y + 7
            continue

        # Generic text section (SLO and any future section).
        page, y = _ensure(doc, note, page, y, 44, body)
        y = _heading(page, y, title, head)
        display = text
        if key == "slo" and "able to:" in text.lower():
            display = text.split("able to:", 1)[-1].strip()
        if display:
            page, y = _para(doc, note, page, y, display, body)
        else:
            page, y = _para(doc, note, page, y, "(Teacher to complete)", body, italic=True)
        y += 4

    footer = str(note.get("footer") or "")
    if footer:
        page, y = _ensure(doc, note, page, y, 34, body)
        page.draw_line(
            fitz.Point(MARGIN, y), fitz.Point(PAGE_W - MARGIN, y), width=0.5,
            color=(0.6, 0.6, 0.6),
        )
        y += 6
        for line in _wrap(footer, PAGE_W - MARGIN * 2, 7.6):
            page, y = _ensure(doc, note, page, y, 10, body)
            page.insert_text(
                (MARGIN, y + 7.6), line, fontname=FONT, fontsize=7.6,
                color=(0.4, 0.4, 0.4),
            )
            y += 9.5

    _footer_pages(doc, note)
    out = doc.tobytes()
    doc.close()
    return out
