"""Phase 7: Term Pack (Export Bundle) PDF generation.

The Term Pack combines seven sections into ONE PDF with MIXED orientation:

  1. Cover            portrait  (rendered here)
  2. Coverage Summary portrait  (rendered here)
  3. Scheme of Work   landscape (reuse scheme_pdf.render_scheme_pdf)
  4. Lesson Plans     portrait  (reuse lesson_pdf.render_lesson_pdf)
  5. Lesson Notes     portrait  (reuse notes_pdf.render_notes_pdf, answers hidden)
  6. Record of Work   landscape (rendered here from ROW rows)
  7. Citations        portrait  (rendered here)

Design rule: DO NOT rebuild or modify the existing editors/PDF renderers. We insert
their already-rendered pages into a master fitz.Document, which preserves each
page's size (orientation). Cover / Coverage / ROW / Citations / Answers pages are
new packaging-only renderers. After assembly we strip each source renderer's local
"p.N" marker and draw a single global header/footer with "Page X of Y" (Y = whole
pack) on every page except the cover.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

import fitz  # PyMuPDF

from services import lesson_notes_service as _notes_svc
from services import lesson_plan_service as _plan_svc
from services import plan_service as _scheme_svc
from services import record_of_work_service as _row_svc

# Reuse the four existing renderers verbatim — this is packaging, not rebuilding.
from services.scheme_pdf import render_scheme_pdf
from services.lesson_pdf import render_lesson_pdf
from services.notes_pdf import render_notes_pdf

PW, PH = 595.28, 841.89           # A4 portrait
LW, LH = 841.89, 595.28           # A4 landscape
FONT, BOLD, ITAL = "helv", "hebo", "heit"
INK = (0.16, 0.18, 0.22)
MUTED = (0.42, 0.45, 0.50)
FAINT = (0.62, 0.65, 0.70)
RULE = (0.80, 0.82, 0.85)
BRAND = (0.11, 0.35, 0.42)
AMBER = (0.72, 0.48, 0.09)

Progress = Callable[[int, str], None]

_SEC_LABEL = {
    "cover": "Cover", "coverage": "Coverage Summary", "scheme": "Scheme of Work",
    "plans": "Lesson Plans", "notes": "Lesson Notes", "row": "Record of Work",
    "citations": "Citations / Sources", "answers": "Answers", "versions": "Version History",
    "progress": "Learner Progress (private)",
}


def _no_op(_p: int, _s: str) -> None:
    pass


# ---------------------------------------------------------------------------
# low-level drawing helpers
# ---------------------------------------------------------------------------

def _wrap(text: str, width: float, size: float, font: str = FONT) -> list[str]:
    if not text:
        return [""]
    lines: list[str] = []
    for para in str(text).split("\n"):
        if not para.strip():
            lines.append("")
            continue
        cur = ""
        for word in para.split():
            trial = f"{cur} {word}".strip()
            if cur and fitz.get_text_length(trial, fontname=font, fontsize=size) > width:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        if cur:
            lines.append(cur)
    return lines or [""]


def _text(page: fitz.Page, x: float, y: float, s: str, size: float = 10,
          font: str = FONT, color=INK) -> float:
    if s:
        page.insert_text((x, y), str(s), fontname=font, fontsize=size, color=color)
    return y + size * 1.35


def _para(page: fitz.Page, x: float, y: float, text: str, width: float, size: float = 10,
          font: str = FONT, color=INK, leading: float = 1.42) -> float:
    for line in _wrap(text, width, size, font):
        y = _text(page, x, y, line, size, font, color)
        y += size * (leading - 1)
    return y


def _rule(page: fitz.Page, x1: float, y: float, x2: float, color=RULE, width: float = 0.6) -> None:
    page.draw_line(fitz.Point(x1, y), fitz.Point(x2, y), color=color, width=width)


def _centered(page: fitz.Page, y: float, s: str, size: float, font: str = BOLD,
              color=INK, cx: float | None = None) -> None:
    """Draw text centred on the page, or on `cx` when a column centre is given."""
    w = fitz.get_text_length(s, fontname=font, fontsize=size)
    center = cx if cx is not None else page.rect.width / 2
    _text(page, center - w / 2, y, s, size, font, color)


def _new(master: fitz.Document, landscape: bool = False) -> fitz.Page:
    return master.new_page(width=LW if landscape else PW, height=LH if landscape else PH)


# ---------------------------------------------------------------------------
# metadata
# ---------------------------------------------------------------------------

def _meta(plan: dict[str, Any], row_doc: dict[str, Any] | None,
          profile: dict[str, Any] | None = None) -> dict[str, str]:
    h = dict(plan.get("header") or {})
    row_h = dict((row_doc or {}).get("header") or {})
    # The cover belongs to the teacher. A blank My Space school name stays blank
    # (printed as a handwriting line); it must not inherit a scheme's old school.
    profile = profile or {}
    school = str(profile.get("schoolName") or "") if profile else str(
        h.get("institution") or row_h.get("school") or ""
    )
    return {
        "school": school,
        "grade": str(plan.get("grade") or row_h.get("grade") or ""),
        "subject": str(plan.get("subject") or row_h.get("learningArea") or ""),
        "term": str(plan.get("term") or row_h.get("term") or ""),
        "year": str(h.get("year") or row_h.get("year") or ""),
        "teacher": str(profile.get("name") or h.get("teacherName") or row_h.get("teacher") or ""),
        "tscNo": str(profile.get("tscNo") or h.get("tscNo") or row_h.get("tscNo") or ""),
        "subCounty": str(profile.get("county") or h.get("subCounty") or ""),
    }


def _generated() -> str:
    now = _dt.datetime.now()
    return f"{now:%Y-%m-%d} {now:%H:%M}"


def _filename(meta: dict[str, str], fmt: str) -> str:
    slug = "-".join(x for x in (meta["grade"], meta["subject"], meta["term"]) if x)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", slug).strip("-") or "Term"
    return f"Term-Pack-{slug}.{fmt}"


# ---------------------------------------------------------------------------
# SECTION 1 — Cover (portrait)
# ---------------------------------------------------------------------------

def _draw_cover(master: fitz.Document, meta: dict[str, str], gen: str,
                has_draft: bool) -> None:
    page = _new(master)
    page.draw_rect(fitz.Rect(0, 0, PW, 8), color=None, fill=BRAND, overlay=True)
    _text(page, 46, 74, "CBC Curriculum Companion  •  Kenya Primary", 10, BOLD, BRAND)
    _text(page, PW - 46 - fitz.get_text_length("Term Pack", fontname=BOLD, fontsize=10),
          74, "Term Pack", 10, BOLD, MUTED)

    _centered(page, 250, meta["school"] or "School: ________", 24, BOLD, INK)
    _centered(page, 292, "SCHEME OF WORK & LESSON PLANS", 15, BOLD, BRAND)
    _centered(page, 322, "TERM PACK", 20, BOLD, INK)
    _rule(page, 150, 350, PW - 150, BRAND, 1.2)

    rows = [
        ("Learning Area", meta["subject"]), ("Grade", meta["grade"]),
        ("Term", meta["term"]), ("Year", meta["year"]),
        ("Teacher", meta["teacher"]), ("TSC No", meta["tscNo"]),
        ("School", meta["school"]), ("Sub-County", meta["subCounty"]),
    ]
    y = 396
    for label, value in rows:
        _text(page, 150, y, label, 10, BOLD, MUTED)
        blank = "________" if label in ("School", "Sub-County", "TSC No", "Teacher") else "—"
        _text(page, 300, y, value or blank, 10, FONT, INK)
        _rule(page, 150, y + 6, PW - 150, RULE, 0.4)
        y += 30

    _para(page, 60, PH - 96,
          "Prepared from KICD Curriculum Design "
          f"({meta['grade']} {meta['subject']})  |  Source-first, AI-assisted where labelled  |  "
          f"Generated: {gen}", PW - 120, 8.5, FONT, MUTED)
    if has_draft:
        _text(page, 60, PH - 66, "DRAFT - Not Final (draft content included)", 9, BOLD, AMBER)


# ---------------------------------------------------------------------------
# SECTION 2 — Coverage Summary (portrait)
# ---------------------------------------------------------------------------

def _draw_coverage(master: fitz.Document, meta: dict[str, str], gen: str,
                   row_doc: dict[str, Any] | None, cov: dict[str, Any] | None,
                   progress: Progress) -> fitz.Page:
    page = _new(master)
    progress(6, "Building Coverage Summary")
    _text(page, 40, 56, "Coverage Summary", 18, BOLD, INK)
    _text(page, 40, 78,
          f"{meta['grade']} {meta['subject']}  |  {meta['term']} {meta['year']}  |  {meta['teacher']}",
          9, FONT, MUTED)

    if not row_doc or cov is None:
        _text(page, 40, 130, "ROW not yet created - Coverage based on Scheme plan only", 12, BOLD, AMBER)
        _text(page, 40, 158, "Taught: 0%  |  No Record of Work rows recorded.", 10, FONT, INK)
        return page

    stats = [
        ("Planned", cov.get("planned", 0)), ("Taught", cov.get("taught", 0)),
        ("Partially", cov.get("partially", 0)), ("Not Taught", cov.get("notTaught", 0)),
        ("Carry Over", cov.get("carryOver", 0)), ("Coverage", f"{cov.get('coveragePct', 0)}%"),
    ]
    bx, by, bw, bh = 40, 108, 82, 56
    for i, (label, value) in enumerate(stats):
        x = bx + i * (bw + 8)
        page.draw_rect(fitz.Rect(x, by, x + bw, by + bh), color=RULE, fill=(0.97, 0.98, 0.99), width=0.6)
        _centered(page, by + 26, str(value), 17, BOLD, BRAND, cx=x + bw / 2)
        _centered(page, by + 45, label, 8, FONT, MUTED, cx=x + bw / 2)

    # Coverage by week bar chart (vector bars so it prints).
    y = 196
    _text(page, 40, y, "Coverage by Week", 11, BOLD, INK)
    y += 22
    by_week: dict[int, list[int]] = {}
    for r in row_doc.get("rows", []):
        if r.get("origin") != "planned":
            continue
        wk = int(r.get("week") or 0)
        by_week.setdefault(wk, [0, 0])
        by_week[wk][1] += 1
        if r.get("status") == "Taught":
            by_week[wk][0] += 1
    label_w, bar_w = 58, 330
    for wk in sorted(by_week):
        taught, total = by_week[wk]
        pct = (taught / total * 100) if total else 0
        _text(page, 40, y + 8, f"Week {wk}", 8, FONT, MUTED)
        page.draw_rect(fitz.Rect(40 + label_w, y, 40 + label_w + bar_w, y + 10),
                       color=RULE, fill=(0.95, 0.96, 0.97), width=0.4)
        page.draw_rect(fitz.Rect(40 + label_w, y, 40 + label_w + bar_w * pct / 100, y + 10),
                       color=None, fill=BRAND, overlay=True)
        _text(page, 40 + label_w + bar_w + 8, y + 9, f"{pct:.0f}%", 8, BOLD, INK)
        y += 15

    # Gaps table.
    gaps = cov.get("gaps") or []
    y = max(y + 8, 380)
    _text(page, 40, y, "Gaps (honest record)", 11, BOLD, INK)
    y += 18
    headers = [("Week", 44), ("Lesson", 52), ("Focus", 200), ("Status", 118), ("Carry Over To", 120)]
    x0 = 40
    page.draw_rect(fitz.Rect(x0, y, x0 + sum(w for _, w in headers), y + 18),
                   color=RULE, fill=(0.94, 0.95, 0.97), width=0.5)
    x = x0
    for label, w in headers:
        _text(page, x + 4, y + 12, label, 8, BOLD, INK)
        x += w
    y += 18
    for g in gaps[:24]:
        if y > PH - 96:
            page = _new(master)
            y = 56
        vals = [str(g.get("week") or ""), str(g.get("lesson") or ""),
                str(g.get("focusKeyword") or g.get("subStrand") or ""),
                str(g.get("status") or ""), str(g.get("carryOverTo") or "—")]
        lines = max(len(_wrap(val, w - 8, 7.5)) for (_, w), val in zip(headers, vals))
        need = max(16, 8 + lines * 7.5 * 1.3 + 4)
        if y + need > PH - 96:
            page = _new(master)
            y = 56
        x = x0
        for (label, w), val in zip(headers, vals):
            _para(page, x + 4, y + 9, val, w - 8, 7.5, FONT, INK)
            x += w
        _rule(page, x0, y + need, x0 + sum(w for _, w in headers), RULE, 0.4)
        y += need
    if not gaps:
        _text(page, x0 + 4, y + 12, "No gaps recorded.", 8, FONT, MUTED)

    note_y = PH - 74
    _para(page, 40, note_y,
          "Coverage is from Record of Work, not from the Scheme plan. Gaps are shown honestly.",
          PW - 80, 8, ITAL, MUTED)
    return page


# ---------------------------------------------------------------------------
# SECTION 6 — Record of Work (landscape, rendered here from ROW rows)
# ---------------------------------------------------------------------------

def _draw_row(master: fitz.Document, meta: dict[str, str], gen: str,
              row_doc: dict[str, Any] | None, progress: Progress) -> None:
    if not row_doc or not row_doc.get("rows"):
        page = _new(master, landscape=True)
        _centered(page, LH / 2 - 20, "Record of Work Covered", 18, BOLD, INK)
        _centered(page, LH / 2 + 14,
                  "ROW not yet created. Generate ROW from the Scheme to track what was taught.",
                  11, FONT, MUTED)
        return

    cols = [("Date", 58), ("Week / Lesson", 62), ("Strand / Sub-Strand", 140),
            ("Work Done", 250), ("Reflection", 130), ("Status", 96), ("Signature", 84)]
    total_w = sum(w for _, w in cols)
    scale = (LW - 48) / total_w
    cols = [(n, w * scale) for n, w in cols]
    x0, top, row_h = 24, 58, 15
    page = _new(master, landscape=True)
    y = top

    def header(pg: fitz.Page, yy: float) -> float:
        _text(pg, 24, 34,
              f"Record of Work Covered  |  {meta['grade']} {meta['subject']}  |  {meta['term']} {meta['year']}  |  {meta['teacher']}",
              9.5, BOLD, INK)
        pg.draw_rect(fitz.Rect(x0, yy, x0 + sum(w for _, w in cols), yy + row_h),
                     color=RULE, fill=(0.94, 0.95, 0.97), width=0.5)
        x = x0
        for name, w in cols:
            _text(pg, x + 3, yy + 11, name, 7.5, BOLD, INK)
            x += w
        return yy + row_h

    y = header(page, y)
    line_h = 6.6 * 1.32
    for idx, r in enumerate(row_doc["rows"]):
        vals = [
            str(r.get("date") or ""), f"W{r.get('week') or '-'} L{r.get('lesson') or '-'}",
            " / ".join(x for x in (r.get("strand"), r.get("subStrand")) if x),
            str(r.get("workDone") or ""), str(r.get("reflection") or ""),
            str(r.get("status") or ""), "",
        ]
        # Dynamic height: never let wrapped text collide with the next row.
        lines = max(len(_wrap(val, w - 6, 6.6)) for (_, w), val in zip(cols, vals))
        need = max(row_h, 8 + lines * line_h + 4)
        if y + need > LH - 62:
            page = _new(master, landscape=True)
            y = header(page, top)
        x = x0
        for (_, w), val in zip(cols, vals):
            font = ITAL if (val.startswith("Planned:") or not val) else FONT
            _para(page, x + 3, y + 9, val, w - 6, 6.6, font, INK)
            x += w
        _rule(page, x0, y + need, x0 + sum(w for _, w in cols), RULE, 0.35)
        y += need
        if (idx + 1) % 40 == 0:
            progress(72 + (idx + 1) // 4, f"Building ROW ({idx + 1}/{len(row_doc['rows'])})")

    last = master[-1]
    sy = LH - 52
    _text(last, 24, sy, "Teacher's Signature: _______________________     Date: ____________", 8, FONT, INK)
    _text(last, 24, sy + 16, "Checked by: ___________________     Date: ____________", 8, FONT, INK)


# ---------------------------------------------------------------------------
# SECTION 7 — Citations / Sources (portrait)
# ---------------------------------------------------------------------------

def _draw_citations(master: fitz.Document, meta: dict[str, str], gen: str,
                    plan: dict[str, Any], row_doc: dict[str, Any] | None,
                    ai_log: list[dict[str, Any]], web_log: list[dict[str, Any]],
                    textbook_refs: list[str], version_notes: list[dict[str, Any]],
                    include_versions: bool, progress: Progress) -> None:
    progress(80, "Building Sources & Transparency Log")
    page = _new(master)
    y = 56
    _text(page, 40, y, "Sources & Transparency Log", 16, BOLD, INK)
    y += 28

    def table(title: str, headers: list[tuple[str, float]], rows: list[list[str]], empty: str) -> float:
        nonlocal page, y
        if y > PH - 160:
            page = _new(master)
            y = 56
        _text(page, 40, y, title, 11, BOLD, BRAND)
        y += 16
        width = sum(w for _, w in headers)
        if y + 18 > PH - 60:
            page = _new(master); y = 56
        page.draw_rect(fitz.Rect(40, y, 40 + width, y + 17),
                       color=RULE, fill=(0.94, 0.95, 0.97), width=0.5)
        x = 40
        for label, w in headers:
            _text(page, x + 3, y + 11, label, 7.5, BOLD, INK)
            x += w
        y += 17
        if not rows:
            _text(page, 43, y + 10, empty, 7.5, ITAL, MUTED)
            y += 16
        for vals in rows:
            if y + 16 > PH - 60:
                page = _new(master); y = 56
            x = 40
            for (_, w), val in zip(headers, vals):
                _para(page, x + 3, y + 9, val, w - 6, 7, FONT, INK)
                x += w
            _rule(page, 40, y + 14, 40 + width, RULE, 0.35)
            y += 15
        return y + 14

    # Design sources.
    design_rows: list[list[str]] = []
    sources = plan.get("sources") or []
    for s in sources:
        design_rows.append([str(s), "KICD Design / Appendix / Rubric", "Cited in Scheme & Plans"])
    y = table("1. Design Sources", [("Source", 250), ("Pages", 170), ("Used For", 110)],
              design_rows or [["No design sources recorded", "—", "—"]], "")

    # AI log.
    ai_rows = [[a.get("date", ""), a.get("tool", ""), a.get("what", ""), a.get("decision", "")]
               for a in ai_log]
    y = table("2. AI Log", [("Date", 80), ("Tool", 70), ("What it did", 245), ("Teacher decision", 135)],
              ai_rows, "No AI content used in this Term Pack.")

    # Web log.
    web_rows = [[w.get("date", ""), w.get("query", ""), w.get("url", ""),
                 str(w.get("score", "")), w.get("inserted", "")] for w in web_log]
    y = table("3. Web Log", [("Date", 74), ("Query", 130), ("URL", 190), ("Score", 40), ("Inserted?", 96)],
              web_rows, "No Web content used in this Term Pack.")

    # Textbook refs.
    tb_rows = [[t] for t in textbook_refs]
    y = table("4. Textbook References", [("Reference", 530)],
              tb_rows, "No textbook references recorded.")

    if include_versions and version_notes:
        v_rows = [[v.get("date", ""), v.get("section", ""), v.get("label", ""), v.get("comment", "")]
                  for v in version_notes]
        y = table("Appendix - Version History", [("Date", 84), ("Section", 110), ("Version", 70), ("Comment", 266)],
                  v_rows, "")

    y += 6
    _para(page, 40, min(y, PH - 92),
          "This Term Pack was prepared from KICD Curriculum Designs. AI and Web content is labelled and was "
          "reviewed by the teacher. It is not an official KICD publication. "
          + ("No AI or Web content used in this Term Pack. All content from KICD Design + Teacher."
             if not ai_log and not web_log else ""),
          PW - 80, 8, ITAL, MUTED)


# ---------------------------------------------------------------------------
# Answers page (portrait) — separate last page per Notes doc
# ---------------------------------------------------------------------------

def _draw_answers(master: fitz.Document, note: dict[str, Any], meta: dict[str, str]) -> None:
    page = _new(master)
    y = 56
    _text(page, 40, y,
          f"Answers - Week {note.get('week')} Lesson {note.get('lesson')} (Teacher Only)",
          13, BOLD, INK)
    y += 20
    _text(page, 40, y, f"{meta['grade']} {meta['subject']}  |  {note.get('focus') or ''}", 8, FONT, MUTED)
    y += 22
    for sec in note.get("sections") or []:
        if sec.get("key") != "practice":
            continue
        items = ((sec.get("data") or {}).get("items")) or []
        for i, item in enumerate(items, 1):
            if y > PH - 70:
                page = _new(master)
                y = 56
            q = str(item.get("question") or "")
            a = str(item.get("answer") or "")
            y = _para(page, 40, y, f"{i}. {q}", PW - 80, 9.5, BOLD, INK) + 2
            y = _para(page, 56, y, f"Answer: {a or '(not provided)'}", PW - 96, 9, FONT, INK) + 8


# ---------------------------------------------------------------------------
# Global header / footer with Page X of Y (whole pack)
# ---------------------------------------------------------------------------

def _normalize_pages(master: fitz.Document, meta: dict[str, str], gen: str) -> None:
    total = master.page_count
    for i, page in enumerate(master):
        w, h = page.rect.width, page.rect.height
        # Cover is exempt from header/footer.
        if i == 0:
            continue
        # Erase each source renderer's local "p.N" marker, wherever it sits.
        try:
            for word in page.get_text("words"):
                if re.fullmatch(r"p\.\d+", word[4] or ""):
                    page.draw_rect(fitz.Rect(word[:4]), color=None, fill=(1, 1, 1), overlay=True)
        except Exception:
            pass
        left = f"Mwalimu Studio  |  {meta['subject']} Grade {meta['grade']}"
        right = f"{meta['term']}  •  {meta['year']}  •  {meta['teacher']}"
        _text(page, 12, 12, left, 7, FONT, FAINT)
        rw = fitz.get_text_length(right, fontname=FONT, fontsize=7)
        _text(page, w - 12 - rw, 12, right, 7, FONT, FAINT)
        _rule(page, 12, 16, w - 12, RULE, 0.4)

        footer_left = "Source: KICD Design  |  Term Pack"
        # Opt-in Learner Progress pages carry their own privacy footer.
        if "Private - Contains learner names" not in page.get_text():
            _text(page, 12, h - 10, footer_left, 7, FONT, FAINT)
        center = f"Page {i + 1} of {total}"
        cw = fitz.get_text_length(center, fontname=FONT, fontsize=7.5)
        _text(page, (w - cw) / 2, h - 10, center, 7.5, BOLD, MUTED)
        gr = f"Generated: {gen}"
        gw = fitz.get_text_length(gr, fontname=FONT, fontsize=7)
        _text(page, w - 12 - gw, h - 10, gr, 7, FONT, FAINT)


# ---------------------------------------------------------------------------
# helpers: gather logs / version notes / textbook refs (no new tables)
# ---------------------------------------------------------------------------

def _gather_logs(plan_id: str, plan: dict[str, Any], notes: list[dict[str, Any]]) -> tuple[list, list, list, list]:
    """Derive AI/Web logs, textbook refs and version notes from persisted provenance."""
    ai_log: list[dict[str, Any]] = []
    web_log: list[dict[str, Any]] = []
    textbook: list[str] = []

    # AI provenance from lesson plans / notes.
    for p in _plan_svc.list_lesson_plans(plan_id).get("plans", []):
        if p.get("status") and p.get("status") != "Draft":
            pass
    try:
        with __import__("db").connect() as conn:
            lp_rows = conn.execute(
                "SELECT id, ai_enriched, ai_provider, ai_timestamp, created_at, week, lesson "
                "FROM lesson_plans WHERE plan_id = ? AND ai_enriched = 1 ORDER BY week, lesson",
                (plan_id,),
            ).fetchall()
            for r in lp_rows:
                ai_log.append({
                    "date": (r["ai_timestamp"] or r["created_at"] or "")[:10],
                    "tool": r["ai_provider"] or "AI",
                    "what": f"Drafted content for Week {r['week']} Lesson {r['lesson']}",
                    "decision": "Teacher reviewed",
                })
            n_rows = conn.execute(
                "SELECT id, ai_enriched, ai_provider, ai_timestamp, created_at, week, lesson "
                "FROM lesson_notes WHERE plan_id = ? AND ai_enriched = 1 ORDER BY week, lesson",
                (plan_id,),
            ).fetchall()
            for r in n_rows:
                ai_log.append({
                    "date": (r["ai_timestamp"] or r["created_at"] or "")[:10],
                    "tool": r["ai_provider"] or "AI",
                    "what": f"AI-enriched notes for Week {r['week']} Lesson {r['lesson']}",
                    "decision": "Teacher reviewed",
                })
            # Textbook refs from appendix_source on cited chunks.
            refs = conn.execute(
                """SELECT DISTINCT sc.appendix_source FROM source_chunks sc
                   JOIN plan_citations pc ON pc.chunk_id = sc.id
                   WHERE pc.plan_id = ? AND sc.appendix_source IS NOT NULL AND sc.appendix_source != ''""",
                (plan_id,),
            ).fetchall()
            textbook = [str(r["appendix_source"]) for r in refs]
    except Exception:
        pass

    # Web search logs are in-process; collect from note ids that have one.
    for n in notes:
        try:
            log = _notes_svc.web_search_log(n["id"])
        except Exception:
            log = None
        if not log:
            continue
        web_log.append({
            "date": _dt.date.today().isoformat(),
            "query": str(log.get("query") or ""),
            "url": ", ".join(str(x) for x in (log.get("returned") or [])[:3]),
            "score": "",
            "inserted": "Yes" if log.get("status") == "ok" else "No",
        })

    version_notes: list[dict[str, Any]] = []
    for v in plan.get("versions") or []:
        version_notes.append({"date": str(v.get("createdAt") or "")[:10], "section": "Scheme",
                              "label": v.get("label") or "", "comment": v.get("comment") or ""})
    return ai_log, web_log, textbook, version_notes


def _selection(option: dict[str, Any], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter lesson plans/notes by mode: all | weeks | selected."""
    mode = option.get("mode", "all")
    if mode == "all":
        return items
    if mode == "weeks":
        weeks = {int(w) for w in (option.get("weeks") or [])}
        return [it for it in items if int(it.get("week") or 0) in weeks]
    if mode == "selected":
        ids = set(option.get("lessonIds") or [])
        return [it for it in items if it.get("id") in ids or it.get("lessonPlanId") in ids]
    return items


# ---------------------------------------------------------------------------
# PUBLIC: build one PDF
# ---------------------------------------------------------------------------

def build_term_pack(plan_id: str, includes: dict[str, Any], format: str = "pdf",
                    progress: Progress | None = None,
                    profile: dict[str, Any] | None = None) -> tuple[bytes, dict[str, Any], str, dict[str, str]]:
    """Return (pdf_bytes, manifest, filename, meta)."""
    progress = progress or _no_op
    plan = _scheme_svc.get_plan(plan_id)
    if not plan:
        raise ValueError("Scheme not found.")

    progress(2, "Gathering scheme data")
    row_doc = None
    if includes.get("row", True):
        try:
            row_doc = _row_svc.get_document(plan_id)
        except Exception:
            row_doc = None
    cov = (row_doc or {}).get("coverage")
    meta = _meta(plan, row_doc, profile)
    gen = _generated()

    all_plans = _plan_svc.list_lesson_plans(plan_id).get("plans", [])
    all_notes = _notes_svc.list_lesson_notes(plan_id).get("notes", [])
    sel_plans = _selection(includes.get("plans") or {}, all_plans)
    sel_notes = _selection(includes.get("notes") or {}, all_notes)
    include_drafts = bool(includes.get("includeDrafts", False))
    include_answers = bool(includes.get("includeAnswers", False))
    include_versions = bool(includes.get("includeVersionHistory", False))

    ai_log, web_log, textbook, version_notes = _gather_logs(plan_id, plan, all_notes)
    has_draft = include_drafts and any(
        (p.get("status") == "Draft") for p in (sel_plans + sel_notes)
    )

    master = fitz.open()
    manifest_sections: list[dict[str, Any]] = []

    def mark(name: str, start: int) -> None:
        pages = master.page_count - start
        orientation = "landscape" if name in ("scheme", "row") else "portrait"
        manifest_sections.append({"name": name, "pages": pages, "orientation": orientation})

    # 1. Cover
    start = master.page_count
    if includes.get("cover", True):
        _draw_cover(master, meta, gen, has_draft)
        mark("cover", start)

    # 2. Coverage
    start = master.page_count
    if includes.get("coverage", True):
        _draw_coverage(master, meta, gen, row_doc, cov, progress)
        mark("coverage", start)

    # 3. Scheme (landscape, reuse existing renderer)
    start = master.page_count
    if includes.get("scheme", True):
        progress(12, "Building Scheme")
        pdf = render_scheme_pdf(plan)
        src = fitz.open(stream=pdf, filetype="pdf")
        master.insert_pdf(src)
        src.close()
        mark("scheme", start)

    # 4. Lesson Plans (portrait, reuse existing renderer)
    start = master.page_count
    if includes.get("plans", {}).get("include", True):
        total = len(sel_plans)
        for i, item in enumerate(sel_plans, 1):
            progress(16 + int(44 * i / max(total, 1)), f"Building Plans ({i}/{total})")
            full = _plan_svc.get_lesson_plan(item["id"])
            if not full:
                continue
            pdf = render_lesson_pdf(full)
            src = fitz.open(stream=pdf, filetype="pdf")
            before = master.page_count
            master.insert_pdf(src)
            src.close()
            if has_draft and full.get("status") == "Draft":
                for pg in list(master)[before:]:
                    _watermark(pg)
        mark("plans", start)

    # 5. Lesson Notes (portrait, reuse existing renderer; answers hidden here)
    start = master.page_count
    if includes.get("notes", {}).get("include", True):
        total = len(sel_notes)
        for i, item in enumerate(sel_notes, 1):
            progress(60 + int(20 * i / max(total, 1)), f"Building Notes ({i}/{total})")
            full = _notes_svc.get_lesson_note(item["id"])
            if not full:
                continue
            pdf = render_notes_pdf(full, show_answers=False)
            src = fitz.open(stream=pdf, filetype="pdf")
            before = master.page_count
            master.insert_pdf(src)
            src.close()
            if has_draft and full.get("status") == "Draft":
                for pg in list(master)[before:]:
                    _watermark(pg)
            if include_answers:
                _draw_answers(master, full, meta)
        mark("notes", start)

    # 6. ROW (landscape, rendered here)
    start = master.page_count
    if includes.get("row", True):
        _draw_row(master, meta, gen, row_doc, progress)
        mark("row", start)

    # 7. Citations (portrait)
    start = master.page_count
    if includes.get("citations", True):
        _draw_citations(master, meta, gen, plan, row_doc, ai_log, web_log,
                        textbook, version_notes, include_versions, progress)
        mark("citations", start)

    # 8. Learner Progress - OPT-IN ONLY. Contains learner names and is never
    #    included by default. The typed confirmation is checked again here so a
    #    hand-crafted API call cannot silently leak names into a Term Pack.
    start = master.page_count
    if includes.get("progress"):
        if str(includes.get("progressConfirm") or "").strip() != "I understand":
            raise ValueError('Type "I understand" to include learner names in the Term Pack.')
        progress(85, "Building Learner Progress (private)")
        from services import learner_service as _learner_svc, progress_pdf as _progress_pdf
        filters = {"grade": str(plan.get("grade") or ""),
                   "learningArea": str(plan.get("subject") or ""),
                   "term": str(plan.get("term") or "")}
        data = _learner_svc.get_progress(filters)
        blob = _progress_pdf.build_progress_pdf(data, profile, filters)
        src = fitz.open(stream=blob, filetype="pdf")
        master.insert_pdf(src)
        src.close()
        mark("progress", start)

    progress(88, "Normalising headers & footers")
    _normalize_pages(master, meta, gen)

    out = master.tobytes()
    total_pages = master.page_count
    master.close()

    manifest = {
        "planId": plan_id,
        "grade": meta["grade"], "subject": meta["subject"], "term": meta["term"],
        "teacher": meta["teacher"], "generatedAt": gen,
        "totalPages": total_pages,
        "sections": [s for s in manifest_sections if s["pages"] > 0],
        "coverage": {"planned": cov.get("planned", 0) if cov else 0,
                     "taught": cov.get("taught", 0) if cov else 0,
                     "coveragePct": cov.get("coveragePct", 0) if cov else 0},
    }
    return out, manifest, _filename(meta, format), meta


def _watermark(page: fitz.Page) -> None:
    text = "DRAFT - Not Final"
    size = 42
    w = fitz.get_text_length(text, fontname=BOLD, fontsize=size)
    cx, cy = page.rect.width / 2, page.rect.height / 2
    morph = (fitz.Point(cx, cy), fitz.Matrix(45))
    page.insert_text((cx - w / 2, cy), text, fontname=BOLD, fontsize=size,
                     color=(0.86, 0.87, 0.88), morph=morph, overlay=True)


# ---------------------------------------------------------------------------
# PUBLIC: build ZIP (6 PDFs + manifest.json)
# ---------------------------------------------------------------------------

def build_zip(plan_id: str, includes: dict[str, Any],
              progress: Progress | None = None,
              profile: dict[str, Any] | None = None) -> tuple[bytes, dict[str, Any], str, dict[str, str]]:
    progress = progress or _no_op
    one, manifest, _name, meta = build_term_pack(plan_id, includes, "pdf", progress, profile)
    src = fitz.open(stream=one, filetype="pdf")

    # Split the master into exactly SIX PDFs (spec):
    #   01-Cover (cover + coverage), 02-Scheme, 03-Lesson-Plans,
    #   04-Lesson-Notes (with answers), 05-ROW, 06-Citations  + manifest.json
    groups = [
        ("01-Cover.pdf", ["cover", "coverage"]),
        ("02-Scheme.pdf", ["scheme"]),
        ("03-Lesson-Plans.pdf", ["plans"]),
        ("04-Lesson-Notes.pdf", ["notes", "answers"]),
        ("05-ROW.pdf", ["row"]),
        ("06-Citations.pdf", ["citations"]),
        ("07-learner-progress-PRIVATE.pdf", ["progress"]),
    ]
    by_name = {s["name"]: s for s in manifest["sections"]}
    files: list[dict[str, Any]] = []
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, members in groups:
            present = [by_name[m] for m in members if m in by_name]
            if not present:
                continue
            start = next(i for i, s in enumerate(manifest["sections"])
                         if s["name"] == present[0]["name"])
            pages = sum(s["pages"] for s in present)
            part = fitz.open()
            part.insert_pdf(src, from_page=start, to_page=start + pages - 1)
            data = part.tobytes()
            part.close()
            zf.writestr(fname, data)
            # Orientation: landscape only when a group is a single landscape section.
            orientation = "landscape" if len(present) == 1 and present[0]["orientation"] == "landscape" else "portrait"
            files.append({"name": fname, "pages": pages, "orientation": orientation})
        zm = dict(manifest)
        zm["files"] = files
        zf.writestr("manifest.json", json.dumps(zm, indent=2, ensure_ascii=False))
    src.close()
    return buf.getvalue(), zm, _filename(meta, "zip"), meta
