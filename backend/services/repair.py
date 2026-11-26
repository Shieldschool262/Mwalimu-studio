"""App-side gap recovery for the verbatim engine.

The engine is never edited. Where it demonstrably misses content that is present in the
PDF, the app recovers it here and marks the chunk so a teacher can verify the recovery.

Known engine limitation (verified on Grade 1 Mathematics p.27, sub-strand 3.2):
the "Suggested Learning Experiences" header cell spans columns 3-5 while the row text
lands in column 4. `map_header_row` therefore maps experiences -> 3, reads an empty
cell and the chunk ends up with zero experiences although the PDF clearly has them.
"""
from __future__ import annotations

import re
from typing import Any

import fitz

from services.parser_engine import clean_cell

HEADER_HINTS = {
    "experiences": ("suggested learning experiences", "learning experiences", "shughuli"),
    "outcomes": ("specific learning outcomes", "learning outcomes", "matokeo"),
    "kiqs": ("key inquiry", "swali dadisi"),
}


def _classify(cell: str) -> str | None:
    c = cell.lower()
    for key, hints in HEADER_HINTS.items():
        if any(h in c for h in hints):
            return key
    return None


def _column_for(rows: list[list[str]], key: str) -> list[int]:
    """Columns whose data sits under the header cell for `key`, including span bleed."""
    for row in rows[:3]:
        for i, cell in enumerate(row):
            if _classify(cell) == key:
                # The header cell may span several columns; data can appear in any of them
                # until the next non-empty header cell.
                cols = [i]
                j = i + 1
                while j < len(row) and not clean_cell(row[j] or ""):
                    cols.append(j)
                    j += 1
                return cols
    return []


def recover_experiences(pdf_bytes: bytes, records: list[dict[str, Any]]) -> int:
    """Fill chunks that lost their experiences to a shifted table column."""
    targets = [
        r
        for r in records
        if not (r.get("suggested_learning_experiences") or [])
    ]
    if not targets:
        return 0

    pages = {int(r.get("page_start") or 0) for r in targets} - {0}
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    by_page: dict[int, list[list[list[str]]]] = {}
    try:
        for n in pages:
            if not (1 <= n <= doc.page_count):
                continue
            tables = []
            try:
                found = doc[n - 1].find_tables()
            except Exception:
                found = []
            for tab in getattr(found, "tables", []) or []:
                try:
                    rows = [[clean_cell(c or "") for c in row] for row in (tab.extract() or [])]
                except Exception:
                    continue
                if rows:
                    tables.append(rows)
            by_page[n] = tables
    finally:
        doc.close()

    recovered = 0
    for rec in targets:
        page_no = int(rec.get("page_start") or 0)
        code = rec.get("sub_strand_code") or ""
        collected: list[str] = []
        for rows in by_page.get(page_no, []):
            if not rows:
                continue
            cols = _column_for(rows, "experiences")
            if not cols:
                continue
            # Only trust this page if it actually holds this sub-strand.
            if code and code not in " ".join(" ".join(r) for r in rows):
                continue
            # The table splits one bullet across several rows, so join the column's rows
            # first and only then split on bullets - otherwise every line becomes an "item".
            lines: list[str] = []
            for row in rows:
                for c in cols:
                    if c < len(row):
                        cell = row[c]
                        if re.search(r"\d+\.\d+\.\d+|\d+\.\d+", cell) or _classify(cell):
                            continue
                        lines.append(cell)
            joined = " ".join(x.strip() for x in lines if x.strip())
            # PyMuPDF returns the design bullet as U+F0B7 / U+E006 / U+25CF depending on
            # the font; normalise every variant to one character before splitting.
            joined = re.sub(r"[\ue000-\uf8ff\u25cf\u25a0\u25aa]", "\u2022", joined)
            # The instruction line precedes the first bullet; drop it before splitting so
            # split_experiences() can index the bullets correctly.
            joined = re.sub(r"^\s*(?:the learners? (?:is|are) guided to|mwanafunzi aelekezwe)\s*:?\s*", "",
                            joined, flags=re.I)
            # Bullets are already normalised to '•' here, so split on them directly
            # instead of via split_experiences() (which expects ' • ' with a space).
            collected.extend(
                part.strip(" \u2022\u25cf\u25a0\u25aa-\u2013\t").strip()
                for part in re.split(r"\s*\u2022\s*", joined)
                if len(part.strip(" \u2022\u25cf\u25a0\u25aa-\u2013\t")) > 5
            )
        # Drop the instruction line ("The learners are guided to:") the way the engine does.
        items = [
            x for x in collected
            if len(x) > 5 and not re.fullmatch(r"the learners? (is|are) guided to:?", x.strip(), re.I)
        ]
        # De-duplicate, keeping order (cells repeat across row fragments).
        seen = set()
        unique = [x for x in items if not (x in seen or seen.add(x))]
        if unique:
            rec["suggested_learning_experiences"] = list(unique)
            rec["confidence"] = round(min(float(rec.get("confidence") or 0.0) or 0.75, 0.85), 2)
            flags = [f for f in (rec.get("flags") or []) if "Experiences recovered" not in f]
            rec["flags"] = flags + ["Experiences recovered from shifted table column - verify"]
            recovered += 1
    return recovered
