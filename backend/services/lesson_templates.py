"""Lesson-plan template selection for Phase 4.

Two templates, never one for every grade:

* ``cbe-lesson-primary-v1`` - PP1 to Grade 6 (35 min, activity-based)
* ``cbe-lesson-jss-v1``     - Grade 7 to Grade 9 (40 min single / 80 min double)

The grade decides the default; the teacher can still switch in the header.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = BACKEND_ROOT / "templates"

PRIMARY = "cbe-lesson-primary-v1"
JSS = "cbe-lesson-jss-v1"
LEGACY = "cbe-lesson-v1"
DEFAULT = PRIMARY
KNOWN = (PRIMARY, JSS, LEGACY)

# Phase 5 - learner-facing Lesson Notes have their OWN templates.
NOTES_PRIMARY = "cbe-lesson-notes-v1"
NOTES_JSS = "cbe-lesson-notes-jss-v1"
NOTES_KNOWN = (NOTES_PRIMARY, NOTES_JSS)


def load_lesson_template(version: str = DEFAULT) -> dict[str, Any]:
    name = version if version in KNOWN else DEFAULT
    path = TEMPLATES_DIR / f"{name}.json"
    if not path.exists():
        path = TEMPLATES_DIR / f"{DEFAULT}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def notes_template_for_grade(grade: str | None) -> str:
    """PP1-Grade 6 -> primary notes; Grade 7-9 -> JSS notes."""
    n = grade_number(grade)
    if n is None:
        return NOTES_PRIMARY
    return NOTES_JSS if 7 <= n <= 9 else NOTES_PRIMARY


def effective_notes_template(version: str | None, grade: str | None) -> str:
    if version in NOTES_KNOWN:
        return str(version)
    return notes_template_for_grade(grade)


def load_notes_template(version: str | None = None, grade: str | None = None) -> dict[str, Any]:
    name = effective_notes_template(version, grade)
    path = TEMPLATES_DIR / f"{name}.json"
    if not path.exists():
        path = TEMPLATES_DIR / f"{NOTES_PRIMARY}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def grade_number(grade: str | None) -> int | None:
    text = str(grade or "").strip().lower()
    if re.search(r"\b(pp\s*1|pp\s*2|pre[- ]?primary)\b", text):
        return 0
    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else None


def template_for_grade(grade: str | None) -> str:
    """PP1-Grade 6 -> primary; Grade 7-9 -> JSS. Unknown falls back to primary."""
    n = grade_number(grade)
    if n is None:
        return PRIMARY
    return JSS if 7 <= n <= 9 else PRIMARY


def effective_template_version(version: str | None, grade: str | None) -> str:
    """Map the legacy single template to the right band instead of reusing it everywhere."""
    if version in (PRIMARY, JSS):
        return str(version)
    return template_for_grade(grade)


def duration_for_mode(template: dict[str, Any], mode: str | None) -> int:
    modes = template.get("durationModes") or {}
    if mode in modes:
        return int(modes[mode])
    return int(template.get("defaultDuration") or 35)


def development_total(template: dict[str, Any], mode: str | None = None) -> int | str | None:
    total = (template.get("development") or {}).get("totalMinutes")
    if isinstance(total, dict):
        return total.get(mode or "Single")
    return total
