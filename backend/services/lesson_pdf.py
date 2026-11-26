"""Render a KICD lesson plan as a PORTRAIT A4 PDF.

Two templates drive the paper:

* ``cbe-lesson-primary-v1`` - PP1 to Grade 6 (activity-based, 35 min)
* ``cbe-lesson-jss-v1``     - Grade 7 to Grade 9 (40 min single / 80 min double)

The 11-part KICD order is fixed: Administrative Details; Strand; Sub-Strand; Specific
Learning Outcomes; KIQ; Core Competencies; Values; PCIs; Learning Resources; Lesson
Development (Introduction + 3 steps + Conclusion, each with Teacher Activity, Learner
Activity and Time); Extended Activities + Assessment + Reflection.

Lesson Development and Assessment are structured data, not one textbox. The full
Administrative Details table is printed only on the page where the lesson starts;
continuation pages carry a slim "LESSON PLAN / Lesson continued" running header so a
merged Term Pack stays readable without repeating the school/teacher letterhead.
"""
from __future__ import annotations

import textwrap
from typing import Any

import fitz  # PyMuPDF
from services.lesson_templates import load_lesson_template

# Portrait A4 in points.
PAGE_W, PAGE_H = 595.28, 841.89
MARGIN = 38.0

FONT = "helv"
FONT_BOLD = "hebo"
FONT_ITALIC = "heit"
TITLE_SIZE = 14.0
META_SIZE = 7.6
HEAD_SIZE = 9.2
BODY_SIZE = 8.6

PAGE_BOTTOM = PAGE_H - MARGIN - 16


def _wrap(text: str, width_pt: float, size: float) -> list[str]:
    if not text:
        return [""]
    char_w = size * 0.50
    max_chars = max(8, int(width_pt / char_w))
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


def _latest_version(plan: dict[str, Any]) -> str:
    versions = plan.get("versions") or []
    if not versions:
        return ""
    return str(versions[0].get("label") or "")


ADMIN_SIZE = 8.2
BLANK = "________"


def _admin_value(value: Any) -> str:
    """Empty admin cells get a handwriting line, never a dash/null/undefined."""
    s = str(value if value is not None else "").strip()
    if not s or s.lower() in ("null", "undefined", "none"):
        return BLANK
    return s


def _draw_header(page: fitz.Page, plan: dict[str, Any]) -> float:
    """Lesson-plan cover block: a real bordered label/value table (first page only)."""
    header = plan.get("header") or {}
    content_w = PAGE_W - MARGIN * 2
    y = MARGIN

    page.insert_text((MARGIN, y + TITLE_SIZE), "LESSON PLAN", fontname=FONT_BOLD, fontsize=TITLE_SIZE)
    if _latest_version(plan):
        label = f"Version {_latest_version(plan)}"
        w = fitz.get_text_length(label, fontname=FONT, fontsize=META_SIZE)
        page.insert_text((PAGE_W - MARGIN - w, y + TITLE_SIZE), label,
                         fontname=FONT, fontsize=META_SIZE, color=(0.35, 0.35, 0.35))
    y += TITLE_SIZE + 8

    duration = header.get("duration")
    duration_type = str(header.get("durationType") or "").strip()
    duration_text = f"{duration} min ({duration_type})" if duration_type and duration else duration

    lesson_no = header.get("lesson") or plan.get("lesson") or ""
    lesson_total = header.get("lessonCount") or plan.get("lessonCount") or ""
    lesson_cell = (
        f"Lesson {lesson_no} of {lesson_total}" if lesson_total else f"Lesson {lesson_no}"
    )

    # One visual row = two label/value pairs, or a single full-width cell.
    rows: list[list[tuple[str, Any]]] = [
        [("School", header.get("school")), ("Learning Area", header.get("learningArea"))],
        [("Grade", header.get("grade")), ("Term", header.get("term"))],
        [("Year", header.get("year")), ("Week", header.get("week"))],
        [(lesson_cell, ""), ("Date", header.get("date"))],
        [("Time", header.get("time")), ("Duration", duration_text)],
        [("Strand", header.get("strand")), ("Sub-Strand", header.get("subStrand"))],
        [("Focus", header.get("focus"))],
        [("Teacher", header.get("teacherName")), ("TSC No.", header.get("tscNo"))],
        [("Class Size", header.get("classSize")),
         ("Roll B/G/T", f"{_admin_value(header.get('rollBoys'))}/"
                        f"{_admin_value(header.get('rollGirls'))}/"
                        f"{_admin_value(header.get('rollTotal'))}")],
    ]

    col_w = content_w / 4.0
    for row in rows:
        full = len(row) == 1
        values = [v for _, v in row]
        widths = [(content_w - col_w / 2 - 10) if full else (col_w - 10) for _ in row]
        wrapped = [_wrap(_admin_value(v), w, ADMIN_SIZE) for v, w in zip(values, widths)]
        line_count = max(len(x) for x in wrapped)
        row_h = line_count * (ADMIN_SIZE + 2.5) + 8

        page.draw_rect(fitz.Rect(MARGIN, y, MARGIN + content_w, y + row_h),
                       color=(0.60, 0.62, 0.66), fill=(1, 1, 1), width=0.6)
        for i in range(1, 4):
            if full or i == 2:
                page.draw_line(fitz.Point(MARGIN + i * col_w, y),
                               fitz.Point(MARGIN + i * col_w, y + row_h),
                               color=(0.72, 0.74, 0.78), width=0.5)
        pairs = [row[0], ("", "")] if full else row
        for i, ((label, _), lines) in enumerate(zip(pairs, wrapped)):
            x0 = MARGIN + i * 2 * col_w
            label_w = 2 * col_w if full else col_w
            page.draw_rect(fitz.Rect(x0, y, x0 + label_w, y + row_h),
                           color=(0.82, 0.84, 0.86), fill=(0.95, 0.96, 0.97), width=0.4)
            if label and label != lesson_cell:
                page.insert_text((x0 + 4, y + ADMIN_SIZE + 3), f"{label}:",
                                 fontname=FONT_BOLD, fontsize=ADMIN_SIZE, color=(0.15, 0.17, 0.20))
            if label == lesson_cell:
                page.insert_text((x0 + 4, y + ADMIN_SIZE + 3), label,
                                 fontname=FONT, fontsize=ADMIN_SIZE)
            if not lines:
                continue
            vx = MARGIN + col_w / 2 + 4 if full else x0 + label_w + 4
            for j, line in enumerate(lines):
                page.insert_text((vx, y + ADMIN_SIZE + 3 + j * (ADMIN_SIZE + 2.5)),
                                 line, fontname=FONT, fontsize=ADMIN_SIZE)
        y += row_h
    return y + 6


CONTINUED_SIZE = 8.0


def _draw_continuation_header(page: fitz.Page) -> float:
    """Slim running header for pages after the lesson's first page.

    Administrative details belong only on the page where the lesson starts.
    Continuation pages get a compact title so a lesson merged into a Term Pack
    still reads clearly, but no repeated school/teacher/date/roll letterhead.
    """
    y = MARGIN
    page.insert_text(
        (MARGIN, y + TITLE_SIZE),
        "LESSON PLAN",
        fontname=FONT_BOLD,
        fontsize=TITLE_SIZE,
    )
    y += TITLE_SIZE + 4
    page.insert_text(
        (MARGIN, y + CONTINUED_SIZE),
        "Lesson continued",
        fontname=FONT_ITALIC,
        fontsize=CONTINUED_SIZE,
        color=(0.45, 0.45, 0.45),
    )
    y += CONTINUED_SIZE + 3
    page.draw_line(
        fitz.Point(MARGIN, y),
        fitz.Point(PAGE_W - MARGIN, y),
        color=(0.78, 0.80, 0.83),
        width=0.6,
    )
    return y + 10


def _new_page(
    doc: fitz.Document, plan: dict[str, Any], *, first: bool = False
) -> tuple[fitz.Page, float]:
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    y = _draw_header(page, plan) if first else _draw_continuation_header(page)
    return page, y


def _ensure(doc: fitz.Document, plan: dict[str, Any], page: fitz.Page, y: float, need: float):
    if y + need > PAGE_BOTTOM:
        return _new_page(doc, plan)
    return page, y


def _draw_section(
    page: fitz.Page,
    y: float,
    title: str,
    body: str,
    *,
    tone: str = "body",
    size: float | None = None,
) -> float:
    content_w = PAGE_W - MARGIN * 2
    heading_size = size or (HEAD_SIZE if tone == "heading" else BODY_SIZE)
    page.insert_text((MARGIN, y + heading_size), title, fontname=FONT_BOLD, fontsize=heading_size)
    y += heading_size + 4
    if body.strip():
        for line in _wrap(body, content_w - 8, BODY_SIZE):
            page.insert_text((MARGIN + 4, y + BODY_SIZE), line, fontname=FONT, fontsize=BODY_SIZE)
            y += BODY_SIZE + 2.4
    elif tone != "heading":
        page.insert_text(
            (MARGIN + 4, y + BODY_SIZE),
            "(Teacher to complete)",
            fontname=FONT_ITALIC,
            fontsize=BODY_SIZE,
            color=(0.55, 0.55, 0.55),
        )
        y += BODY_SIZE + 4
    return y + 6


def _draw_step(
    doc: fitz.Document,
    plan: dict[str, Any],
    page: fitz.Page,
    y: float,
    title: str,
    data: dict[str, Any],
    *,
    fallback_body: str = "",
) -> tuple[fitz.Page, float]:
    time_text = str(data.get("time") or "").strip()
    teacher = str(data.get("teacherActivity") or "").strip()
    learner = str(data.get("learnerActivity") or "").strip()
    if not teacher and not learner and fallback_body:
        learner = fallback_body
    need = 34
    page, y = _ensure(doc, plan, page, y, need)
    if title:
        page.insert_text(
            (MARGIN, y + HEAD_SIZE),
            title if not time_text else f"{title} ({time_text})",
            fontname=FONT_BOLD,
            fontsize=HEAD_SIZE,
        )
        y += HEAD_SIZE + 5
    for label, text in (("Teacher Activity", teacher), ("Learner Activity", learner)):
        page.insert_text(
            (MARGIN + 6, y + BODY_SIZE),
            f"{label}:",
            fontname=FONT_BOLD,
            fontsize=BODY_SIZE,
        )
        label_w = fitz.get_text_length(
            f"{label}: ", fontname=FONT_BOLD, fontsize=BODY_SIZE
        )
        lines = _wrap(text or "—", PAGE_W - MARGIN * 2 - 10 - label_w, BODY_SIZE)
        for i, line in enumerate(lines):
            page, y = _ensure(doc, plan, page, y, BODY_SIZE + 4)
            page.insert_text(
                (MARGIN + 6 + (label_w if i == 0 else label_w), y + BODY_SIZE),
                line,
                fontname=FONT,
                fontsize=BODY_SIZE,
            )
            y += BODY_SIZE + 2.2
        y += 2
    return page, y + 4


def _draw_assessment(
    doc: fitz.Document,
    plan: dict[str, Any],
    page: fitz.Page,
    y: float,
    section: dict[str, Any],
) -> tuple[fitz.Page, float]:
    data = section.get("data") or {}
    method = str(data.get("method") or "").strip()
    description = str(data.get("description") or "").strip()
    indicator = str(data.get("rubricIndicator") or "").strip()
    items = data.get("sampleItems") or []
    if isinstance(items, str):
        items = [ln.strip() for ln in items.splitlines() if ln.strip()]
    planned = str((plan.get("assessment") or {}).get("planned") or "").strip()
    differentiation = str((plan.get("assessment") or {}).get("differentiation") or "").strip()

    page, y = _ensure(doc, plan, page, y, 60)
    page.insert_text((MARGIN, y + HEAD_SIZE), "Assessment", fontname=FONT_BOLD, fontsize=HEAD_SIZE)
    y += HEAD_SIZE + 5
    if method:
        y = _draw_section(page, y, "Method", method)
    y = _draw_section(page, y, "Planned Assessment (from Rubric)", planned or description)
    if indicator:
        y = _draw_section(page, y, "Rubric Indicator", indicator)
    if differentiation:
        y = _draw_section(page, y, "Differentiation", differentiation)
    if items:
        y = _draw_section(page, y, "Sample Items", "\n".join(str(x) for x in items))
    return page, y


def render_lesson_pdf(plan: dict[str, Any]) -> bytes:
    template = load_lesson_template(plan.get("templateVersion") or "")
    sections = plan.get("sections") or []
    header = plan.get("header") or {}
    assessment = plan.get("assessment") or {}

    order = {s["key"]: s.get("index", 0) for s in template.get("sections", [])}
    sections = sorted(sections, key=lambda s: (order.get(s.get("key"), 99), s.get("ord", 0)))

    doc = fitz.open()
    page, y = _new_page(doc, plan, first=True)

    for section in sections:
        key = str(section.get("key") or "")
        title = str(section.get("title") or key)
        body = str(section.get("body") or "")
        data = section.get("data") or {}

        if key in ("introduction", "step1", "step2", "step3", "conclusion"):
            # Stage headings are names + time only, never "1. / Step 1 / Stage 1".
            step_title = title
            if key == "introduction":
                step_title = "Introduction"
                data = dict(data)
                data["time"] = str(data.get("time") or "5 min")
            elif key == "conclusion":
                step_title = "Conclusion"
                data = dict(data)
                data["time"] = str(data.get("time") or "5 min")
            elif key == "step1":
                step_title = "Development"
                data = dict(data)
                if not data.get("time"):
                    intro_t = str(
                        next((s.get("data") or {}).get("time") or ""
                             for s in sections if s.get("key") == "introduction")
                    ).strip()
                    conc_t = str(
                        next((s.get("data") or {}).get("time") or ""
                             for s in sections if s.get("key") == "conclusion")
                    ).strip()
                    total = plan.get("duration") or header.get("duration")
                    try:
                        mins = int(str(total).split()[0])
                        left = mins - int(intro_t.split()[0]) - int(conc_t.split()[0])
                        if left > 0:
                            data["time"] = f"{left} min"
                    except (ValueError, IndexError):
                        data["time"] = "25 min"
            elif key in ("step2", "step3"):
                step_title = ""  # sub-steps stay inside Development, unnumbered
            page, y = _draw_step(doc, plan, page, y, step_title, data, fallback_body=body)
            continue

        if key == "assessment":
            page, y = _draw_assessment(doc, plan, page, y, section)
            continue

        if key == "extended":
            page, y = _ensure(doc, plan, page, y, 36)
            page.insert_text(
                (MARGIN, y + HEAD_SIZE),
                "Extended Activities",
                fontname=FONT_BOLD,
                fontsize=HEAD_SIZE,
            )
            y += HEAD_SIZE + 4
            y = _draw_section(page, y, "Extended Activity", body)
            continue

        if key == "reflection":
            y = _draw_section(page, y, "Reflection", body)
            continue

        needed = 26 + len(_wrap(body, PAGE_W - MARGIN * 2 - 8, BODY_SIZE)) * (BODY_SIZE + 2.4)
        page, y = _ensure(doc, plan, page, y, min(needed, 90))
        y = _draw_section(page, y, title, body)

    if not sections:
        y = _draw_section(page, y, "Source", str(header.get("focus") or ""))

    # Planned assessment is shown by _draw_assessment; keep the fallback visible for legacy
    # plans whose only assessment lived on the plan payload.
    if not any(s.get("key") == "assessment" for s in sections) and assessment.get("planned"):
        page, y = _ensure(doc, plan, page, y, 50)
        y = _draw_section(page, y, "Planned Assessment (from Rubric)", str(assessment["planned"]))

    # Footer on every page.
    footer = template.get("footer") or {}
    for p in doc:
        fy = PAGE_H - MARGIN + 4
        template_line = str(footer.get("templateLine", "Template: {templateVersion}")).format(
            templateVersion=plan.get("templateVersion") or ""
        )
        generated_line = str(footer.get("generatedLine", "Generated: {generatedAt}")).format(
            generatedAt=(plan.get("createdAt") or "")[:10]
        )
        p.insert_text(
            (MARGIN, fy), template_line, fontname=FONT, fontsize=6.2, color=(0.45, 0.45, 0.45)
        )
        p.insert_text(
            (MARGIN + 150, fy),
            generated_line,
            fontname=FONT,
            fontsize=6.2,
            color=(0.45, 0.45, 0.45),
        )
        p.insert_text(
            (PAGE_W - MARGIN - 24, fy),
            f"p.{p.number + 1}",
            fontname=FONT,
            fontsize=6.2,
            color=(0.45, 0.45, 0.45),
        )

    out = doc.tobytes()
    doc.close()
    return out
