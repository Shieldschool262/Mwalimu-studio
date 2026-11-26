"""Weekly row splitting for the KICD scheme (Phase 3 correction).

ONE WEEK = ONE ROW. A sub-strand spanning N weeks produces N rows. The Week column is a
single integer and the Lesson column is the range INSIDE that week (1-5), restarting every
week. Nothing is ever merged or repeated wholesale.

Curriculum facts are distributed, never duplicated:

  outcomes     -> dealt round-robin, one outcome per week, cycled when outcomes < weeks
  experiences  -> dealt in sequential contiguous blocks
  KIQs         -> the FULL source KIQ text is repeated on every weekly row. A printed
                  Week 5 must never depend on the teacher also having Week 1.

Everything here is pure: it takes a chunk dict and returns weekly row dicts.
"""
from __future__ import annotations

import math
from typing import Any

# Filler text when a field runs out of items before the weeks do.
CONSOLIDATION = "Consolidation / Revision of outcomes above"
PRACTICE = "Practice / Reinforcement"


def weeks_for(lessons: int, lessons_per_week: int) -> int:
    """How many weekly rows a sub-strand needs."""
    if lessons_per_week <= 0:
        lessons_per_week = 1
    return max(1, math.ceil(lessons / lessons_per_week))


def lesson_range_for(index: int, lessons: int, lessons_per_week: int) -> tuple[int, int]:
    """Lesson numbers INSIDE week `index` (0-based). The range RESETS every week.

    Week 1 of a 5-lesson week is "1-5"; week 2 is "1-5" again, NOT "6-10". The final week of
    a sub-strand may be short (e.g. "1-3") when the lesson count does not divide evenly.
    """
    if lessons_per_week <= 0:
        lessons_per_week = 1
    remaining = lessons - index * lessons_per_week
    end = min(lessons_per_week, remaining)
    return 1, max(1, end)


_BULLET_CHARS = ("●", "", "", "•", "▪", "·")


def _split_bullets(text: str) -> list[str]:
    """Split a single bullet-joined string back into its bullets.

    The engine sometimes returns every bullet of a cell as ONE string separated by U+F0B7 /
    U+25CF etc. Splitting gives the weekly distributor real items to spread across weeks.
    """
    s = text
    for ch in _BULLET_CHARS:
        s = s.replace(ch, "|BUL|")
    if "|BUL|" not in s:
        return [text.strip()] if text.strip() else []
    parts = []
    for piece in s.split("|BUL|"):
        # Bullets often carry a leading label such as "guided discovery:" - keep it attached.
        cleaned = piece.strip().strip(",;").strip()
        if cleaned:
            parts.append(cleaned)
    return parts


def _clean_list(value: Any) -> list[str]:
    """Normalise a field into individual items, expanding bullet-joined strings."""
    if not isinstance(value, list):
        if isinstance(value, str) and value.strip():
            return _split_bullets(value)
        return []
    out: list[str] = []
    for v in value:
        txt = str(v).strip()
        if not txt:
            continue
        pieces = _split_bullets(txt)
        out.extend(pieces if len(pieces) > 1 else [txt])
    return out


def split_outcomes(outcomes: list[str], weeks: int) -> list[list[str]]:
    """Deal outcomes one per week, cycling if there are fewer outcomes than weeks.

    With 4 outcomes and 4 weeks -> [a],[b],[c],[d].
    With 2 outcomes and 4 weeks -> [a],[b],[a],[b] but the extra cycles are labelled as
    revision so a teacher never mistakes a repeat for new content.
    """
    out: list[list[str]] = []
    if not outcomes:
        return [[CONSOLIDATION] for _ in range(weeks)]
    # Deal one per week; if there are MORE outcomes than weeks the surplus joins the last
    # week so nothing is ever dropped. If there are FEWER, the extra weeks consolidate.
    for w in range(weeks):
        if w < weeks - 1:
            block = [outcomes[w]] if w < len(outcomes) else [CONSOLIDATION]
        else:
            tail = outcomes[weeks - 1 :]
            block = tail if tail else [CONSOLIDATION]
        out.append(block)
    return out


def split_experiences(experiences: list[str], weeks: int) -> list[list[str]]:
    """Split the bullet list into sequential contiguous blocks across the weeks.

    6 experiences over 4 weeks -> [e1,e2],[e3,e4],[e5],[e6]
    2 experiences over 4 weeks -> [e1],[e2],[PRACTICE],[PRACTICE]
    """
    out: list[list[str]] = []
    if not experiences:
        return [[PRACTICE] for _ in range(weeks)]
    # Contiguous blocks, remainder spread over the FIRST weeks so every week gets at least
    # one real experience before any filler is used.
    #   6 items, 4 weeks -> [1,2],[3,4],[5],[6]
    #   2 items, 4 weeks -> [1],[2],[Practice],[Practice]
    n = len(experiences)
    base, extra = divmod(n, weeks)
    cursor = 0
    for w in range(weeks):
        take = base + (1 if w < extra else 0)
        block = experiences[cursor : cursor + take]
        cursor += take
        if not block:
            block = [PRACTICE]
        out.append(block)
    return out


def split_kiqs(kiqs: list[str], weeks: int) -> list[list[str]]:
    """Repeat the FULL KIQ text on every weekly row - never a cross-reference.

    A teacher prints Week 5 on its own; a "see Week 1" placeholder would leave
    that page with no inquiry question at all.  When the source lists several
    KIQs they stay joined in full on each row; the joined string produced by the
    parser is intentionally not split again here.
    """
    if not kiqs or weeks <= 0:
        return [[] for _ in range(max(0, weeks))]
    full = " ".join(str(k).strip() for k in kiqs if str(k).strip())
    return [[full] for _ in range(weeks)] if full else [[] for _ in range(weeks)]


def part_label(index: int, weeks: int) -> str:
    return f"Part {index + 1} of {weeks}"


def outcome_part_label(block: list[str], outcomes: list[str]) -> str:
    """'Outcomes a) - b)' style hint for the hover tooltip."""
    if not block or block == [CONSOLIDATION]:
        return "Consolidation"
    letters = []
    for item in block:
        head = item.split(")")[0].strip()
        if len(head) <= 2 and head.isalpha():
            letters.append(f"{head})")
    if len(letters) >= 2:
        return f"Outcomes {letters[0]} - {letters[-1]}"
    if len(letters) == 1:
        return f"Outcome {letters[0]}"
    return "Outcome"


def build_weekly_rows(
    chunk: dict[str, Any],
    lessons_per_week: int,
    start_week: int,
) -> list[dict[str, Any]]:
    """Expand ONE sub-strand into its weekly rows."""
    structured = chunk.get("structured") or {}
    lessons = chunk.get("lessons")
    assumed = False
    if not lessons or int(lessons) <= 0:
        lessons = 4
        assumed = True
    lessons = int(lessons)

    weeks = weeks_for(lessons, lessons_per_week)
    outcomes = _clean_list(structured.get("specific_learning_outcomes"))
    experiences = _clean_list(structured.get("suggested_learning_experiences"))
    kiqs = _clean_list(structured.get("key_inquiry_questions"))

    o_split = split_outcomes(outcomes, weeks)
    e_split = split_experiences(experiences, weeks)
    k_split = split_kiqs(kiqs, weeks)

    rows: list[dict[str, Any]] = []
    for i in range(weeks):
        start, end = lesson_range_for(i, lessons, lessons_per_week)
        flags: list[str] = []
        if assumed:
            flags.append("Lessons not in source - assumed 4, edit")
        rows.append(
            {
                "chunkId": chunk["id"],
                "structured": structured,
                "documentId": chunk.get("documentId"),
                "pageNumber": chunk.get("pageNumber"),
                "strand": chunk.get("strand"),
                "strandCode": chunk.get("strandCode"),
                "subStrand": chunk.get("subStrand"),
                "subStrandCode": chunk.get("subStrandCode"),
                # Allocation - ONE week per row, single integers.
                "week": start_week + i,
                "lessonStart": start,
                "lessonEnd": end,
                "lessonCount": lessons,
                "lessonsPerWeek": lessons_per_week,
                "weekIndex": i,
                "weekCount": weeks,
                "partLabel": part_label(i, weeks),
                "outcomePartLabel": outcome_part_label(o_split[i], outcomes),
                # Distributed content
                "outcomes": o_split[i],
                "experiences": e_split[i],
                "kiqs": k_split[i],
                "flags": flags,
                # Phase 3.5 appendix autofill, carried so scheme cells can be filled.
                "appendixResources": chunk.get("appendixResources"),
                "appendixAssessment": chunk.get("appendixAssessment"),
                "appendixSource": chunk.get("appendixSource"),
                "appendixLevel": chunk.get("appendixLevel"),
                "rubric": chunk.get("rubric") or [],
            }
        )
    return rows


def rebalance_outcomes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Re-run the split for one sub-strand's weekly rows.

    Works from the group's ORIGINAL full lists so a teacher edit that collapsed a cell does
    not permanently destroy content.
    """
    if not rows:
        return rows
    first = rows[0]
    weeks = len(rows)
    outcomes = _clean_list((first.get("original") or {}).get("outcomes"))
    experiences = _clean_list((first.get("original") or {}).get("experiences"))
    kiqs = _clean_list((first.get("original") or {}).get("kiqs"))

    o = split_outcomes(outcomes, weeks)
    e = split_experiences(experiences, weeks)
    k = split_kiqs(kiqs, weeks)

    out = []
    for i, row in enumerate(rows):
        new = dict(row)
        new["outcomes"] = o[i]
        new["experiences"] = e[i]
        new["kiqs"] = k[i]
        new["outcomePartLabel"] = outcome_part_label(o[i], outcomes)
        new["edited"] = False
        out.append(new)
    return out
