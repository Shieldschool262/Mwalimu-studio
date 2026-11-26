"""Phase 10 - Progress PDF (portrait A4, one section per class).

Uses the Term Pack's visual language (same fonts, colours, header rule and global
"Page X of Y" footer). This document contains learner names, so it is NEVER added
to a Term Pack unless the teacher explicitly opts in and types "I understand".
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

import fitz

from services.term_pack_pdf import (
    BOLD, BRAND, FONT, INK, MUTED, PH, PW, RULE,
    _centered, _new, _para, _rule, _text, _wrap,
)

RED = (0.72, 0.20, 0.20)
GREEN = (0.06, 0.48, 0.28)
DARK_GREEN = (0.03, 0.30, 0.18)
AMBER = (0.72, 0.48, 0.09)
GREY = (0.62, 0.65, 0.70)
LEFT, RIGHT = 40.0, PW - 40.0
WIDTH = RIGHT - LEFT
LEVEL_COLOR = {
    "Exceeds": DARK_GREEN, "Meets": GREEN, "Approaching": AMBER,
    "Below": RED, "Not Assessed": GREY,
}
MAX_FOCUS_COLUMNS = 4


def _header(page: fitz.Page, meta: dict[str, str]) -> None:
    left = f"Mwalimu Studio  |  {meta['learningArea']} Grade {meta['grade']}"
    right = f"{meta['term']}  •  {meta['date']}  •  {meta['teacher']}"
    _text(page, LEFT, 20, left, 7, FONT, MUTED)
    rw = fitz.get_text_length(right, fontname=FONT, fontsize=7)
    _text(page, RIGHT - rw, 20, right, 7, FONT, MUTED)
    _rule(page, LEFT, 24, RIGHT, RULE, 0.4)


def _footer(page: fitz.Page, index: int, total: int, generated: str) -> None:
    _text(page, LEFT, PH - 20, "Private - Contains learner names. Keep in My Space.", 7, BOLD, RED)
    _centered(page, PH - 20, f"Page {index + 1} of {total}", 7.5, BOLD, MUTED)
    stamp = f"Generated: {generated}"
    _text(page, RIGHT - fitz.get_text_length(stamp, fontname=FONT, fontsize=7), PH - 20,
          stamp, 7, FONT, MUTED)


def _summary(page: fitz.Page, y: float, counts: dict[str, Any]) -> float:
    _text(page, LEFT, y, "Class Summary", 12, BOLD, BRAND)
    y += 18
    order = ("Exceeds", "Meets", "Approaching", "Below", "Not Assessed")
    total = max(1, sum(int(counts.get(k) or 0) for k in order))
    for level in order:
        n = int(counts.get(level) or 0)
        _text(page, LEFT, y, level, 9, BOLD, LEVEL_COLOR[level])
        bar_w = (WIDTH - 150) * n / total
        if bar_w > 0:
            page.draw_rect(fitz.Rect(LEFT + 90, y - 9, LEFT + 90 + bar_w, y - 1),
                           color=None, fill=LEVEL_COLOR[level], overlay=True)
        _text(page, RIGHT - 40, y, str(n), 9, BOLD, INK)
        y += 15
    return y + 6


def _table(page: fitz.Page, y: float, learners: list[dict[str, Any]], focuses: list[str]) -> float:
    name_w = 108
    overall_w = 62
    support_w = 54
    col_w = max(52, min(92, int((WIDTH - name_w - overall_w - support_w) / max(1, len(focuses)))))
    headers = ["Learner"] + focuses + ["Overall", "Support"]
    widths = [name_w] + [col_w] * len(focuses) + [overall_w, support_w]
    row_h = 26

    def draw_header(at: float) -> float:
        page.draw_rect(fitz.Rect(LEFT, at, RIGHT, at + row_h), color=None, fill=(0.90, 0.94, 0.95))
        x = LEFT
        for text, width in zip(headers, widths):
            for line in _wrap(text, width - 8, 7.5, BOLD)[:2]:
                _text(page, x + 4, at + 9, line, 7.5, BOLD, INK)
                at += 8
            at -= 8 if len(_wrap(text, width - 8, 7.5, BOLD)) > 1 else 0
            x += width
        return at + row_h

    y = draw_header(y)
    for index, learner in enumerate(learners):
        if y + row_h > PH - 42:
            page = _new_page_holder["page"]
            y = draw_header(48)
        if index % 2 == 1:
            page.draw_rect(fitz.Rect(LEFT, y, RIGHT, y + row_h), color=None,
                           fill=(0.97, 0.98, 0.98))
        by_focus = {item["focus"]: item for item in learner.get("byFocus") or []}
        cells = [learner["name"]]
        for focus in focuses:
            item = by_focus.get(focus)
            cells.append(f"{item['level']}\n{item['date']}" if item else "—")
        cells.append(learner["overall"])
        cells.append("Yes" if learner.get("needsSupport") else "—")
        x = LEFT
        for col, (text, width) in enumerate(zip(cells, widths)):
            color = INK
            if col in range(1, len(focuses) + 1) or col == len(cells) - 2:
                color = LEVEL_COLOR.get(str(text).split("\n")[0], INK)
            if col == len(cells) - 1 and text == "Yes":
                color = RED
            lines = str(text).split("\n")[:2]
            for i, line in enumerate(lines):
                _text(page, x + 4, y + 12 + i * 8, line, 7.5 if i else 8,
                      BOLD if i == 0 else FONT, color)
            x += width
        page.draw_line(fitz.Point(LEFT, y + row_h), fitz.Point(RIGHT, y + row_h),
                       color=RULE, width=0.3)
        y += row_h
    return y


def build_progress_pdf(data: dict[str, Any], profile: dict[str, Any] | None = None,
                       filters: dict[str, Any] | None = None) -> bytes:
    profile = profile or {}
    filters = filters or {}
    meta = {
        "teacher": str(profile.get("name") or "Teacher"),
        "grade": str(filters.get("grade") or "All Grades"),
        "learningArea": str(filters.get("learningArea") or "All Learning Areas"),
        "term": str(filters.get("term") or "All Terms"),
        "date": _dt.date.today().isoformat(),
    }
    generated = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    master = fitz.open()
    groups: dict[str, list[dict[str, Any]]] = {}
    for learner in data.get("learners") or []:
        groups.setdefault(learner.get("className") or "Class", []).append(learner)

    if not groups:
        page = _new(master)
        _header(page, meta)
        _centered(page, 160, "No learners in this view yet.", 14, BOLD, MUTED)
        _centered(page, 184, "Add learners in My Learners to record progress.", 10, FONT, MUTED)

    for class_name, learners in sorted(groups.items()):
        page = _new(master)
        _new_page_holder["page"] = page
        _header(page, meta)
        y = 44
        y = _text(page, LEFT, y, f"{class_name} - Progress", 15, BOLD, BRAND) + 6
        y = _para(page, LEFT, y,
                  f"Teacher: {meta['teacher']}   |   Grade: {meta['grade']}   |   "
                  f"Learning Area: {meta['learningArea']}   |   Term: {meta['term']}   |   "
                  f"Date: {meta['date']}", WIDTH, 8, FONT, MUTED) + 8
        focuses: list[str] = []
        for learner in learners:
            for item in learner.get("byFocus") or []:
                if item["focus"] not in focuses:
                    focuses.append(item["focus"])
        focuses = focuses[:MAX_FOCUS_COLUMNS]
        counts = {level: 0 for level in LEVEL_COLOR}
        for learner in learners:
            counts[learner.get("overall", "Not Assessed")] += 1
        y = _summary(page, y, counts) + 4
        y = _table(page, y, learners, focuses)

    total = master.page_count
    for i, page in enumerate(master):
        _footer(page, i, total, generated)
    blob = master.tobytes()
    master.close()
    return blob


_new_page_holder: dict[str, fitz.Page] = {}
