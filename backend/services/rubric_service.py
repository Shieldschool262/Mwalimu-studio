"""Assessment Rubric parsing (Phase 4).

The parser engine deliberately skips rubric rows when building a sub-strand. Phase 4 reads
them back from the ORIGINAL PDF as a separate, deterministic pass and attaches the matching
indicators to each chunk (`source_chunks.assessment_rubric`).

Rules:
  * Rubrics are informational. They NEVER affect vetting_status.
  * If the design has no rubric table the column stays `[]` (null semantics) and the lesson
    plan falls back to the scheme's Assessment cell.
  * Nothing is invented: indicator and level text are copied verbatim from the PDF.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import fitz

from db import connect, upload_path

LEVEL_KEYS = {
    "exceeds": "Exceeds",
    "meets": "Meets",
    "approaches": "Approaches",
    "below": "Below",
    # Kiswahili rubric headings seen in some designs.
    "kuzidi": "Exceeds",
    "kufikia": "Meets",
    "inakaribia": "Approaches",
    "chini": "Below",
}

_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "by", "from",
    "according", "similar", "different", "their", "they", "this", "that", "these", "those",
    "learners", "learner", "pupils", "pupil", "ability", "correctly", "consistently",
    "situations", "situation", "using", "use", "such", "as", "at", "is", "are", "be",
}


def _tokens(text: str) -> set[str]:
    return {
        t
        for t in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(t) > 2 and t not in _STOP
    }


def _level_map(header_cells: list[str]) -> dict[int, str]:
    out: dict[int, str] = {}
    for i, cell in enumerate(header_cells):
        low = (cell or "").lower()
        for needle, name in LEVEL_KEYS.items():
            if needle in low:
                out[i] = name
                break
    return out


def parse_rubric_tables(pdf_path: str | Path) -> list[dict[str, Any]]:
    """Extract every rubric indicator + its four levels from the design PDF."""
    path = Path(pdf_path)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        doc = fitz.open(path)
    except Exception:
        return []

    in_rubric_zone = False
    try:
        for page_index in range(doc.page_count):
            page = doc[page_index]
            text = page.get_text()
            if re.search(r"assessment\s+rubric|rubric\s+ya\s+tathmini|viwango\s+vya", text, re.I):
                in_rubric_zone = True
            if not in_rubric_zone:
                continue
            # A hard stop: the rubric section is over once the next appendix/index starts.
            if re.search(r"^\s*(appendix|glossary|references|bibliography|index)\b", text, re.I) and rows:
                in_rubric_zone = False
                continue
            try:
                tables = page.find_tables()
            except Exception:
                tables = None
            if tables is None:
                continue
            for table in getattr(tables, "tables", []):
                data = table.extract()
                if not data or len(data) < 2:
                    continue
                header = [str(c or "") for c in data[0]]
                levels = _level_map(header)
                if len(levels) < 3:
                    # Header may be split over two rows in some designs.
                    continue
                for raw in data[1:]:
                    cells = [str(c or "").strip() for c in raw]
                    if not cells or not cells[0]:
                        continue
                    indicator = re.sub(r"\s+", " ", cells[0]).strip()
                    if indicator.lower() in seen:
                        continue
                    entry: dict[str, Any] = {"indicator": indicator, "page": page_index + 1, "levels": {}}
                    for idx, name in levels.items():
                        if idx < len(cells) and cells[idx]:
                            entry["levels"][name] = re.sub(r"\s+", " ", cells[idx]).strip()
                    if len(entry["levels"]) >= 3:
                        seen.add(indicator.lower())
                        rows.append(entry)
    finally:
        doc.close()
    return rows


def match_rubrics(rubrics: list[dict[str, Any]], chunk_text: str, limit: int = 3) -> list[dict[str, Any]]:
    """Pick the rubric indicators that actually describe this sub-strand.

    Deterministic token overlap; no semantic guessing. A rubric row with no overlap is never
    attached, so a lesson can never quote a rubric indicator from another sub-strand.
    """
    if not rubrics:
        return []
    chunk_tokens = _tokens(chunk_text)
    scored: list[tuple[int, dict[str, Any]]] = []
    for r in rubrics:
        overlap = len(chunk_tokens & _tokens(r.get("indicator", "")))
        if overlap > 0:
            scored.append((overlap, r))
    scored.sort(key=lambda x: (-x[0], x[1].get("page") or 0))
    best = [r for score, r in scored if score >= 1][:limit]
    return best


def chunk_text_for_matching(row: Any) -> str:
    try:
        sf = json.loads(row["structured_fields"] or "{}")
    except Exception:
        sf = {}
    bits = [row["sub_strand"] or "", row["strand"] or ""]
    for key in (
        "specific_learning_outcomes",
        "suggested_learning_experiences",
        "key_inquiry_questions",
    ):
        val = sf.get(key)
        if isinstance(val, list):
            bits.extend(str(v) for v in val)
        elif val:
            bits.append(str(val))
    return " ".join(bits)


def ensure_document_rubrics(document_id: str) -> list[dict[str, Any]]:
    """Parse once per document and cache the match on every chunk that has no cache yet."""
    rubrics = parse_rubric_tables(upload_path(document_id))
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM source_chunks WHERE document_id = ? ORDER BY ord", (document_id,)
        ).fetchall()
        for row in rows:
            existing = row["assessment_rubric"] if "assessment_rubric" in row.keys() else None
            if existing not in (None, ""):
                continue
            matched = match_rubrics(rubrics, chunk_text_for_matching(row))
            conn.execute(
                "UPDATE source_chunks SET assessment_rubric = ? WHERE id = ?",
                (json.dumps(matched, ensure_ascii=False), row["id"]),
            )
    return rubrics


def ensure_chunk_rubric(chunk_id: str) -> list[dict[str, Any]]:
    """Return the chunk's cached rubric, parsing the source PDF on first use."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM source_chunks WHERE id = ?", (chunk_id,)).fetchone()
        if row is None:
            return []
        cached = row["assessment_rubric"] if "assessment_rubric" in row.keys() else None
        if cached not in (None, ""):
            try:
                data = json.loads(cached)
                return data if isinstance(data, list) else []
            except Exception:
                return []
        document_id = row["document_id"]
    ensure_document_rubrics(document_id)
    with connect() as conn:
        row = conn.execute(
            "SELECT assessment_rubric FROM source_chunks WHERE id = ?", (chunk_id,)
        ).fetchone()
        if row is None or not row["assessment_rubric"]:
            return []
        try:
            return json.loads(row["assessment_rubric"])
        except Exception:
            return []


def format_planned_assessment(
    rubrics: list[dict[str, Any]], scheme_assessment: str | None
) -> tuple[str, str]:
    """Return (planned assessment text, differentiation text) exactly as the teacher sees it."""
    lines: list[str] = []
    support = ""
    extension = ""
    if rubrics:
        r = rubrics[0]
        levels = r.get("levels") or {}
        page = r.get("page")
        head = f"Planned Assessment (from Rubric p.{page}): " if page else "Planned Assessment (from Rubric): "
        lines.append(head)
        lines.append(f"Indicator: {r.get('indicator', '')}")
        for name in ("Exceeds", "Meets", "Approaches", "Below"):
            if levels.get(name):
                lines.append(f"{name}: {levels[name]}")
        support = levels.get("Below", "")
        extension = levels.get("Exceeds", "")
    elif scheme_assessment:
        lines.append(f"Planned Assessment: {scheme_assessment}")
    assessment = "\n".join(lines).strip()
    diff_parts = []
    if support:
        diff_parts.append(f"Support: {support}")
    if extension:
        diff_parts.append(f"Extension: {extension}")
    return assessment, " · ".join(diff_parts)
