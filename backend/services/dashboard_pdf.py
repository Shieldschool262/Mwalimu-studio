"""Phase 8 - Coverage Dashboard PDF (portrait A4).

Copies the Term Pack visual language (same colours, fonts, headers and global
"Page X of Y" footers) by importing its low-level drawing helpers.  No existing
Scheme / Plan / Notes / ROW / Export formatting module is modified.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

import fitz

from services.term_pack_pdf import (
    BOLD, BRAND, FONT, INK, ITAL, MUTED, PH, PW, RULE,
    _centered, _new, _para, _rule, _text, _wrap,
)

RED = (0.72, 0.20, 0.20)
GREEN = (0.06, 0.48, 0.28)
DARK_GREEN = (0.03, 0.30, 0.18)
AMBER = (0.72, 0.48, 0.09)
GREY = (0.62, 0.65, 0.70)
LEFT, RIGHT = 46.0, PW - 46.0
WIDTH = RIGHT - LEFT


def _empty_gaps_message(data: dict[str, Any]) -> tuple[str, bool]:
    """No gap rows does not imply 100% coverage; report what is actually known."""
    s = data.get("summary") or {}
    week = int((data.get("appliedFilters") or {}).get("week") or 0)
    scope = f" for Week {week}" if week else " in this view"
    pct = s.get("coveragePct")
    if pct is None:
        return (f"No gap statuses{scope}. Coverage cannot be calculated yet - "
                "generate a Record of Work first.", False)
    planned = int(s.get("planned") or 0)
    if planned == 0:
        return (f"No planned lessons{scope} - there is nothing to mark as taught.", False)
    taught = int(s.get("taught") or 0)
    partial = int(s.get("partially") or 0)
    if pct == 100 and partial == 0 and taught >= planned:
        return (f"No gaps{scope} - all {planned} planned lessons taught. Coverage 100%.", True)
    if partial > 0:
        return (f"No gap statuses{scope}. {partial} partially taught lesson(s) counted "
                f"at half; coverage {pct}%.", False)
    return (f"No gap statuses{scope}. {taught} of {planned} planned lessons marked "
            f"Taught; coverage {pct}%.", False)


def _tone(pct: int | None) -> tuple[Any, str]:
    if pct is None:
        return MUTED, "—"
    if pct == 100:
        return DARK_GREEN, "Complete"
    if pct >= 90:
        return GREEN, "On Track"
    if pct >= 70:
        return AMBER, "Behind"
    return RED, "Behind"


def _header(page: fitz.Page, data: dict[str, Any]) -> float:
    # Brand + right-hand filter stamp are drawn once by the global header pass
    # at the end, so this per-page helper only lays out the rule below them.
    _rule(page, LEFT, 38, RIGHT)
    return 56.0


def _stat(page: fitz.Page, x: float, y: float, w: float, value: Any, label: str,
          color=BRAND) -> None:
    h = 56.0
    page.draw_rect(fitz.Rect(x, y, x + w, y + h), color=RULE,
                   fill=(0.97, 0.98, 0.99), width=0.6)
    _centered(page, y + 26, str(value), 16, BOLD, color, cx=x + w / 2)
    _centered(page, y + 45, label, 7.5, FONT, MUTED, cx=x + w / 2)


def _section(page: fitz.Page, y: float, title: str, subtitle: str = "") -> float:
    _text(page, LEFT, y, title, 13, BOLD, BRAND)
    if subtitle:
        y = _text(page, LEFT, y + 17, subtitle, 8.5, FONT, MUTED)
    return y + 16


def render_dashboard_pdf(data: dict[str, Any]) -> tuple[bytes, int]:
    """Return (pdf bytes, page count).  Portrait A4 throughout."""
    s = data.get("summary") or {}
    master = fitz.open()
    gen = _dt.datetime.now()

    # ---- 1. Cover -----------------------------------------------------------
    page = _new(master)
    _centered(page, 92, "MWALIMU STUDIO", 11, BOLD, BRAND)
    _centered(page, 150, "COVERAGE DASHBOARD", 22, BOLD, INK)
    _centered(page, 174, "What was actually taught - from the Record of Work", 10, ITAL, MUTED)
    f = data.get("appliedFilters") or {}
    details = [
        ("Term", f.get("term") or "All terms"),
        ("Year", str(f.get("year") or "All years")),
        ("Grade", f.get("grade") or "All grades"),
        ("Learning Area", f.get("subject") or "All subjects"),
        ("Last updated from ROW", str(data.get("lastUpdated") or "—")),
    ]
    y = 250.0
    for k, v in details:
        _text(page, 132, y, k, 9.5, BOLD, MUTED)
        _text(page, 250, y, v, 9.5, FONT, INK)
        _rule(page, 132, y + 6, 470)
        y += 30
    cover = "unknown" if s.get("coveragePct") is None else f"{s.get('coveragePct')}%"
    _centered(page, 700, f"Coverage: {cover}  |  "
                          f"{s.get('taught', 0)} of {s.get('planned', 0)} lessons taught", 12, BOLD, BRAND)
    _centered(page, 762, f"Generated: {gen:%Y-%m-%d %H:%M}  |  "
                          "Prepared from KICD Curriculum Design - source-first, AI-assisted where labelled",
              7.5, FONT, MUTED)

    # ---- 2. Summary ---------------------------------------------------------
    page = _new(master)
    y = _header(page, data)
    y = _section(page, y, "Coverage Summary", "Coverage = (Taught + Partially Taught x 0.5) / Planned x 100")
    stats = [
        (s.get("planned", 0), "Planned"), (s.get("taught", 0), "Taught"),
        (s.get("partially", 0), "Partially"), (s.get("notTaught", 0), "Not Taught"),
        (s.get("carryOver", 0), "Carry Over"),
        (cover, "Coverage"),
    ]
    for i, (v, label) in enumerate(stats):
        col, row = i % 3, i // 3
        _stat(page, LEFT + col * (WIDTH / 3), y + row * 70, WIDTH / 3 - 10, v, label,
              BRAND if label != "Not Taught" else RED)
    y += 155
    _text(page, LEFT, y, "Subject health", 11, BOLD, BRAND)
    y += 20
    for label, key, colour in (("On Track", "onTrack", GREEN), ("Behind", "behind", AMBER),
                               ("Complete", "complete", DARK_GREEN)):
        _text(page, LEFT, y, f"{label}: {s.get(key, 0)}", 10, FONT, colour)
        y += 16
    _text(page, LEFT, y + 6,
          f"Gaps to fix this week: {s.get('gapsThisWeek', 0)}   |   "
          f"Subjects without ROW: {s.get('withoutRow', 0)} (coverage not invented)",
          9.5, BOLD, INK)
    _para(page, LEFT, y + 30,
          "Coverage is read from the Record of Work, never from the Scheme plan. "
          "Blank statuses and carry-over audit rows count as zero; Partially Taught counts as half.",
          WIDTH, 8.5, ITAL, MUTED)

    # ---- 3. By subject ------------------------------------------------------
    page = _new(master)
    y = _header(page, data)
    y = _section(page, y, "Coverage by Subject", "Worst first - red = 0-69%, amber = 70-89%, green = 90%+")
    cols = [("Learning Area", 110), ("Grade", 62), ("Planned", 52), ("Taught", 50),
            ("Part.", 42), ("Not Taught", 58), ("Coverage", 100), ("Status", 70)]
    def subject_head(pg: fitz.Page, yy: float) -> float:
        x = LEFT
        for label, w in cols:
            _text(pg, x + 3, yy, label, 7.5, BOLD, MUTED)
            x += w
        return _rule(pg, LEFT, yy + 5, LEFT + sum(w for _, w in cols)) or yy + 14

    y = subject_head(page, y)
    for row in data.get("bySubject") or []:
        if y > PH - 80:
            page = _new(master)
            y = _header(page, data)
            y = subject_head(page, y)
        pct = row.get("coveragePct")
        colour, _ = _tone(pct)
        label = f"{row.get('subject','')} {row.get('grade','')}".strip()
        if not row.get("rowExists"):
            label += " (ROW not created)"
        vals = [label[:32], str(row.get("grade") or ""), str(row.get("planned") or 0),
                str(row.get("taught") or 0), str(row.get("partially") or 0),
                str(row.get("notTaught") or 0),
                "—" if pct is None else f"{pct}%",
                str(row.get("status") or "")]
        x = LEFT
        for (name, w), val in zip(cols, vals):
            _text(page, x + 3, y, val, 7.5, FONT, colour if name in ("Coverage", "Status") else INK)
            x += w
        if pct is not None:
            bx = LEFT + sum(w for n, w in cols[:6]) + 3
            page.draw_rect(fitz.Rect(bx, y + 7, bx + 94, y + 12), color=RULE,
                           fill=(0.93, 0.94, 0.95), width=0.3)
            page.draw_rect(fitz.Rect(bx, y + 7, bx + 94 * pct / 100.0, y + 12),
                           color=colour, fill=colour, width=0.3)
        _rule(page, LEFT, y + 16, LEFT + sum(w for _, w in cols))
        y += 24

    # ---- 4. By week chart ---------------------------------------------------
    page = _new(master)
    y = _header(page, data)
    y = _section(page, y, "Coverage by Week", "Grey = Planned | Green = Taught | Amber = Partially Taught | Line = cumulative coverage %")
    weeks = data.get("byWeek") or []
    if weeks:
        base, chart_h = y + 210, 190
        max_n = max([int(w.get("planned") or 0) for w in weeks] + [1])
        n = len(weeks)
        slot = min(38.0, (RIGHT - LEFT) / n)
        bar_w = max(6.0, slot * 0.22)
        _rule(page, LEFT, base, RIGHT, color=(0.7, 0.72, 0.75))
        pts: list[fitz.Point] = []
        for i, w in enumerate(weeks):
            x = LEFT + i * slot + 5
            planned = int(w.get("planned") or 0)
            taught = int(w.get("taught") or 0)
            partial = int(w.get("partially") or 0)
            ph = planned / max_n * chart_h
            th = taught / max_n * chart_h
            ah = partial / max_n * chart_h
            page.draw_rect(fitz.Rect(x, base - ph, x + bar_w, base),
                           color=GREY, fill=(0.82, 0.84, 0.86), width=0.3)
            page.draw_rect(fitz.Rect(x + bar_w + 1, base - th, x + 2 * bar_w + 1, base),
                           color=GREEN, fill=(0.35, 0.70, 0.50), width=0.3)
            page.draw_rect(fitz.Rect(x + 2 * bar_w + 2, base - th - ah,
                                     x + 3 * bar_w + 2, base - th),
                           color=AMBER, fill=(0.88, 0.73, 0.38), width=0.3)
            _centered(page, base + 12, f"W{w.get('week')}", 7, FONT, MUTED,
                      cx=x + 1.5 * bar_w)
            if w.get("carryOver"):
                _centered(page, base - ph - 13, f"+{w['carryOver']} carry-over", 6.5, BOLD,
                          AMBER, cx=x + 1.5 * bar_w)
            pct = int(w.get("cumulativePct") or 0)
            pts.append(fitz.Point(x + 1.5 * bar_w, base - pct / 100.0 * chart_h))
        for a, b in zip(pts, pts[1:]):
            page.draw_line(a, b, color=BRAND, width=1.2)
        for pt in pts:
            page.draw_circle(pt, 2, color=BRAND, fill=BRAND)
        _text(page, LEFT, base + 34,
              "Cumulative coverage: " + "  ".join(
                  f"W{w.get('week')} {w.get('cumulativePct')}%" for w in weeks[:12]),
              8, FONT, BRAND)
    else:
        _text(page, LEFT, y, "No Record of Work data yet - coverage is unknown, not 100%.",
              10, ITAL, MUTED)

    # ---- 5. Gaps ------------------------------------------------------------
    gaps = data.get("gaps") or []
    gcols = [("Week/Lesson", 78), ("Subject", 78), ("Grade", 52),
             ("Strand / Focus", 130), ("Reason", 120), ("Carry Over To", 68)]
    gap_index = 0
    while True:
        page = _new(master)
        y = _header(page, data)
        y = _section(page, y, f"Gaps to Fix - {len(gaps)} lessons not taught",
                     "Partially Taught lessons are listed separately, never counted as gaps.")
        if not gaps:
            message, complete = _empty_gaps_message(data)
            colour = DARK_GREEN if complete else AMBER
            tint = (0.94, 0.99, 0.95) if complete else (0.99, 0.96, 0.89)
            page.draw_rect(fitz.Rect(LEFT, y, RIGHT, y + 70), color=colour,
                           fill=tint, width=1)
            for i, line in enumerate(_wrap(message, WIDTH - 20, 10)):
                _centered(page, y + 26 + i * 14, line, 10, BOLD, colour)
            break
        x = LEFT
        for label, w in gcols:
            _text(page, x + 3, y, label, 7.5, BOLD, MUTED)
            x += w
        _rule(page, LEFT, y + 5, LEFT + sum(w for _, w in gcols))
        y += 15
        while gap_index < len(gaps):
            g = gaps[gap_index]
            if y > PH - 80:
                break
            target = g.get("carryOverTo") or {}
            dest = f"W{target.get('week')} L{target.get('lesson')}" if target else "—"
            vals = [f"W{g.get('week')} L{g.get('lesson')}", str(g.get("subject") or ""),
                    str(g.get("grade") or ""),
                    " / ".join(v for v in (g.get("strand"), g.get("focus")) if v)[:40],
                    (g.get("reason") or "—")[:40], dest]
            x = LEFT
            bottom = y
            for (_, w), val in zip(gcols, vals):
                bottom = max(bottom, _para(page, x + 3, y, val, w - 6, 7.2, FONT, INK, leading=1.2))
                x += w
            y = bottom + 4
            _rule(page, LEFT, y, LEFT + sum(w for _, w in gcols))
            y += 6
            gap_index += 1
        if gap_index >= len(gaps):
            break

    # ---- global header/footer pass -----------------------------------------
    total = master.page_count
    for i in range(1, total):
        pg = master[i]
        _text(pg, LEFT, 22, f"Mwalimu Studio | Coverage Dashboard", 7.5, BOLD, BRAND)
        f2 = data.get("appliedFilters") or {}
        right_txt = " | ".join(str(f2.get(k) or "") for k in ("term", "year", "grade", "subject") if f2.get(k))
        _text(pg, RIGHT - fitz.get_text_length(right_txt, fontname=FONT, fontsize=7), 22,
              right_txt, 7, FONT, MUTED)
        _rule(pg, LEFT, PH - 40, RIGHT, color=RULE)
        _text(pg, LEFT, PH - 27, "Source: Record of Work | Dashboard v1", 7, FONT, MUTED)
        mid = f"Page {i + 1} of {total}"
        _centered(pg, PH - 27, mid, 7.5, BOLD, MUTED)
        stamp = f"Generated: {gen:%Y-%m-%d %H:%M}"
        _text(pg, RIGHT - fitz.get_text_length(stamp, fontname=FONT, fontsize=7), PH - 27,
              stamp, 7, FONT, MUTED)

    blob = master.tobytes()
    master.close()
    return blob, total


def filename_for(data: dict[str, Any]) -> str:
    f = data.get("appliedFilters") or {}
    parts = ["Coverage-Dashboard", str(f.get("term") or "All-Terms").replace(" ", ""),
             str(f.get("year") or ""), str(f.get("subject") or "All-Subjects").replace(" ", "-")]
    return "-".join(p for p in parts if p) + ".pdf"
