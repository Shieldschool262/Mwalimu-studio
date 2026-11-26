"""Appendix parser - Suggested Learning Resources + Suggested Assessment Methods.

KICD curriculum designs end with appendices that carry the *resources* and *assessment
methods* the main sub-strand tables do not. Phase 3.5 reads those appendices and joins them
back onto the parsed sub-strand chunks so the scheme's Resources and Assessment columns can be
auto-filled.

Nothing here invents content. Every value written onto a chunk comes from a parsed appendix
cell. When no appendix row matches a chunk, the chunk keeps ``None`` and the scheme falls back
to "— Teacher to fill" / the template default.

Four appendix shapes are recognised, all auto-detected from the table header (never hardcoded
per subject):

  Type A  Sub-Strand Resources      STRANDS | SUB-STRANDS | RESOURCES        (Maths p.29)
  Type B  Strand Resources+Assess   Strand | Suggested Assessment Methods |
                                    Suggested Learning Resources |
                                    Suggested Non-Formal Activities             (CRE p.35)
  Type C  Strand Assessment         <strand group names> -> assessment list  (Eng p.128)
  Type D  Subject Resources         Suggested Learning Resources |
                                    Non-digital | Digital                      (Eng p.129)

Plus a free-text "Suggested Assessment Methods and Tools" numbered list (Maths Appendix 2),
which supplies a subject-level assessment fallback.

The module is deliberately independent of parser_engine: it takes already-opened pages and
returns plain dicts, so the main parser only gains an "appendix mode" branch.
"""
from __future__ import annotations

import re
from typing import Any

import fitz  # PyMuPDF - needed for fitz.Rect in clip fallback

# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

# Markers that mean "appendix begins here". These NO LONGER stop parsing.
# Includes Swahili equivalents for Kiswahili curriculum designs.
APPENDIX_MARKERS = (
    "appendix",
    "appendices",
    "suggested learning resources",
    "suggested assessment methods",
    # Swahili (Kiswahili curriculum designs)
    "kiambatisho",          # Appendix
    "nyenzo za kufundishia", # Learning Resources
    "mbinu za kutathminia",  # Assessment Methods
)

# Swahili → English header mapping for appendix table classification.
_SWAHILI_HEADER_MAP = {
    "mada": "strand",                              # Strand/Topic
    "mbinu za kutathminia zilizopendekezwa": "suggested assessment methods",
    "nyenzo za kufundishia zilizopendekezwa": "suggested learning resources",
    "shughuli nyingine zilizoratibiwa za ujifunzaji zilizopendekezwa": "non formal activities",
    "mada ndogo": "sub strand",                    # Sub-Strand
    "mada  ndogo": "sub strand",  # PyMuPDF sometimes doubles the space
}

# Bullets used inside appendix cells (KICD mixes several).
_BULLETS = ("\ue006", "\uf0b7", "\uf0a7", "\u25cf", "\u2022", "\u25aa", "\u00b7", "●", "▪", "•")


def is_appendix_page(text: str) -> bool:
    """True if this page starts (or continues) appendix material.

    Tightened for two real-world traps:
      * A table of contents lists "Suggested Learning Resources ....... 129" - not an appendix.
      * Appendix pages carry a heading, usually near the top, rather than a dotted TOC line.

    Also recognises Swahili headings (KIAMBATISHO, Nyenzo za Kufundishia, etc.) for
    Kiswahili curriculum designs.
    """
    head = (text or "")[:800]
    low = head.lower()

    # A dotted leader line ("Suggested Assessment Methods .... 128") is a contents entry.
    def is_toc_line(marker: str) -> bool:
        for line in low.split("\n"):
            if marker in line and "...." in line:
                return True
        return False

    for marker in APPENDIX_MARKERS:
        if marker in low and not is_toc_line(marker):
            return True
    # A bare "APPENDIX"/"APPENDICES"/"KIAMBATISHO" heading anywhere on the page.
    if re.search(r"\bappendi(x|ces)\b", low) and not is_toc_line("appendi"):
        return True
    if "kiambatisho" in low and not is_toc_line("kiambatisho"):
        return True
    return False


def has_appendix_table(text: str) -> bool:
    """Cheap signal that a page holds an appendix-style TABLE (used for continuation pages).

    Continuation pages of an appendix table carry no heading, so appendix mode has to keep
    running across them. A page that is still inside a table but whose cells contain no
    heading vocabulary is still a continuation - it is only excluded when it opens a clearly
    different section (prose headings such as an assessment rubric that comes AFTER the
    appendix tables, not CSL guidelines which are PART of the appendix).

    Also recognises Swahili vocabulary for Kiswahili curriculum designs.
    """
    low = (text or "").lower()
    # A page that opens a new prose section ends the appendix run — but only after
    # the resource/assessment tables have been seen. CSL guidelines are part of the
    # appendix, so they do NOT stop the run. Assessment rubrics at the very end do.
    if re.search(r"\bassessment rubric\b", low) and not (
        "resources" in low or "strand" in low or "nyenzo" in low or "mada" in low
    ):
        return False
    has_res = (
        "resources" in low or "non-digital" in low or "non digital" in low
        or "nyenzo za kufundishia" in low  # Swahili
    )
    has_asm = (
        "assessment methods" in low or "assessment" in low
        or "mbinu za kutathminia" in low  # Swahili
    )
    has_strand = "strand" in low or "mada" in low  # Swahili for strand/topic
    if (has_res and (has_strand or has_asm)) or (has_strand and has_asm):
        return True
    # Swahili-specific combinations
    if "nyenzo" in low and ("mada" in low or "mbinu" in low):
        return True
    if "mada" in low and "mbinu" in low:
        return True
    # Headerless table continuation: short cells, no sentence punctuation, no prose.
    stripped = [ln.strip() for ln in low.split("\n") if ln.strip()]
    if not stripped:
        return False
    prose = sum(1 for ln in stripped if ln.endswith(".") and len(ln.split()) > 8)
    return prose == 0


def _space_camel(text: str) -> str:
    """Insert spaces between CamelCase words so PyMuPDF 2.x concatenated headers
    ('SuggestedAssessmentMethods') are recognised."""
    t = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    t = re.sub(r"\b([A-Z])\s(?=[A-Z]\s)", r"\1", t)
    return t


def _norm(text: str) -> str:
    """Normalise a label for matching: lowercase, collapse space, drop punctuation noise.

    Also spaces out CamelCase concatenation from PyMuPDF 2.x so
    'SuggestedAssessmentMethods' becomes 'suggested assessment methods'.

    Also maps Swahili appendix headers to their English equivalents so
    'Mbinu za Kutathminia Zilizopendekezwa' becomes 'suggested assessment methods'.
    """
    t = _space_camel(text or "")
    t = t.lower()
    t = t.replace("\u2019", "'").replace("\u2018", "'")
    t = t.replace("\u2013", "-").replace("\u2014", "-")
    t = re.sub(r"[^a-z0-9' ]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    # Map Swahili appendix header vocabulary to English equivalents.
    for sw, en in _SWAHILI_HEADER_MAP.items():
        if t == sw or t.startswith(sw):
            t = en
            break
    return t


def _core_word(text: str) -> str:
    """Last meaningful word of a label, e.g. 'WHOLE NUMBERS' -> 'numbers'."""
    words = [w for w in _norm(text).split() if len(w) > 2]
    return words[-1] if words else ""


def cell_items(raw: str) -> list[str]:
    """Split an appendix cell into individual bullet items.

    KICD cells arrive as one string with word-wrapped bullets. Each bullet may itself wrap
    across several lines, so a continuation line is attached to the bullet above it rather
    than being dropped.
    """
    if not raw:
        return []
    s = str(raw).replace("\r", "\n")
    for b in _BULLETS:
        s = s.replace(b, "\n<BUL>")

    grouped: list[list[str]] = []
    for line in s.split("\n"):
        if "<BUL>" in line:
            grouped.append([line.split("<BUL>", 1)[-1]])
        elif line.strip():
            if grouped:
                grouped[-1].append(line)  # continuation of the current bullet
            else:
                grouped.append([line])  # text before the first bullet

    items: list[str] = []
    for parts in grouped:
        txt = re.sub(r"\s+", " ", " ".join(parts)).strip().strip(",;").strip()
        if txt:
            items.append(txt)
    return items


def _join(items: list[str]) -> str | None:
    return "; ".join(items) if items else None


# ---------------------------------------------------------------------------
# Table classification
# ---------------------------------------------------------------------------


def classify_header(header: list[str]) -> str | None:
    """Return 'A' | 'B' | 'C' | 'D' | None for one table header row."""
    raw = [str(c or "") for c in header]
    # A row carrying strand/sub-strand codes (e.g. '1.1 Safety on Raised
    # Platforms' or '2.0 Communication in Pre-Technical Studies') is a data row,
    # never a header. Without this guard a mis-extracted continuation table whose
    # cells merely mention 'digital resources' was grabbed as a Type D table and
    # its heading labels were stored as subject-wide resources.
    if any(re.match(r"\s*\d+(?:\.\d+)+\s", c) for c in raw):
        return None
    cells = [_norm(c) for c in raw]
    joined = " ".join(cells)

    # Type D first: Non-digital | Digital (its cells are resource lists, not strand groups).
    if any(c.startswith("non digital") or c.startswith("nondigital") for c in cells) or any(
        c == "digital" for c in cells
    ):
        return "D"
    if "sub" in joined and "strand" in joined and "resources" in joined:
        # Type A: STRANDS | SUB-STRANDS | RESOURCES
        return "A"
    if "suggested assessment methods" in joined and "suggested learning resources" in joined:
        return "B"
    if "resources" in joined and ("non digital" in joined or "digital" in joined):
        return "D"
    if "suggested assessment methods" in joined and len(header) >= 2:
        return "C"
    return None


# Generic table headings that are not strand groups (Type C guard).
_NON_STRAND_HEADERS = {
    "milestone",
    "description",
    "step",
    "stage",
    "activity",
    "notes",
    "week",
    "lesson",
    "theme",
}


def _is_strand_group_name(g: str) -> bool:
    """A Type C group name is a short label ('Listening and Speaking'), never a
    prose sentence mis-picked from body text."""
    g = (g or "").strip()
    return bool(g) and len(g) <= 80 and len(g.split()) <= 10


# ---------------------------------------------------------------------------
# Per-type table readers
# ---------------------------------------------------------------------------


def _a_column_map(header: list[str] | None) -> dict[str, int | None]:
    """Map logical Type A columns to indices from the table header row.

    Some designs (e.g. Grade 9 Pre-Technical Studies) widen the table to
    STRANDS | SUB-STRANDS | SUGGESTED ASSESSMENT METHODS | SUGGESTED LEARNING
    RESOURCES | SUGGESTED NON-FORMAL ACTIVITIES, where column 2 holds assessment
    methods, not resources. Mapping by header text keeps those columns straight;
    with no header at all the legacy 3-column layout is assumed.
    """
    idx: dict[str, int | None] = {
        "strand": 0,
        "sub": 1,
        "assessment": None,
        "resources": None,
        "non_formal": None,
    }
    for i, c in enumerate(header or []):
        n = _norm(c)
        if not n:
            continue
        if "assessment" in n:
            if idx["assessment"] is None:
                idx["assessment"] = i
        elif "resource" in n:
            if idx["resources"] is None:
                idx["resources"] = i
        elif "non formal" in n or "nonformal" in n:
            if idx["non_formal"] is None:
                idx["non_formal"] = i
        elif "sub" in n and "strand" in n:
            idx["sub"] = i
    return idx


def _read_type_a(
    rows: list[list[str]], page: int, header: list[str] | None = None
) -> list[dict[str, Any]]:
    """Read a Strands | Sub-Strands | ... resources table.

    ``header`` is the table's header row when one exists; column positions are
    derived from it. Headerless continuations inherit the previous page's header
    so the same mapping applies.
    """
    out: list[dict[str, Any]] = []
    cols = _a_column_map(header) if header is not None else {
        "strand": 0,
        "sub": 1,
        "assessment": None,
        "resources": 2,
        "non_formal": None,
    }
    c_strand = cols["strand"] or 0
    c_sub = cols["sub"] if cols["sub"] is not None else 1
    c_res = cols["resources"] if cols["resources"] is not None else 2
    c_asm = cols["assessment"]
    c_nf = cols["non_formal"]
    need = max(i for i in (c_sub, c_res, c_asm if c_asm is not None else 0, c_nf if c_nf is not None else 0))
    strand = ""
    for r in rows:
        if len(r) <= need:
            continue
        st = str(r[c_strand] or "")
        if st:
            strand = re.sub(r"\s+", " ", st).strip()
        sub_clean = re.sub(r"\s+", " ", str(r[c_sub] or "")).strip()
        if not sub_clean:
            continue
        res_items = cell_items(r[c_res] or "")
        asm_items = cell_items(r[c_asm]) if c_asm is not None else []
        nf_items = cell_items(r[c_nf]) if c_nf is not None else []
        if not (res_items or asm_items):
            continue
        out.append(
            {
                "type": "A",
                "strand": strand,
                "sub_strand": sub_clean,
                "resources": _join(res_items) if res_items else None,
                "assessment": _join(asm_items) if asm_items else None,
                "non_formal": _join(nf_items) if nf_items else None,
                "page": page,
                "source": f"Appendix 1, p.{page}, Sub-Strand {sub_clean}",
                "level": "sub_strand",
            }
        )
    return out


def _read_type_b(rows: list[list[str]], page: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        if len(r) < 3:
            continue
        strand = re.sub(r"\s+", " ", str(r[0] or "")).strip()
        if not strand:
            continue
        assessment = _join(cell_items(r[1] or ""))
        resources = _join(cell_items(r[2] or ""))
        non_formal = _join(cell_items(r[3] or "")) if len(r) > 3 else None
        if not (assessment or resources):
            continue
        out.append(
            {
                "type": "B",
                "strand": strand,
                "sub_strand": None,
                "resources": resources,
                "assessment": assessment,
                "non_formal": non_formal,
                "page": page,
                "source": f"Appendix 1, p.{page}, Strand {strand}",
                "level": "strand",
            }
        )
    return out


def _read_type_c(rows: list[list[str]], page: int) -> list[dict[str, Any]]:
    """Header is a row of strand-group names; the row below is their assessment cells."""
    out: list[dict[str, Any]] = []
    for r in rows:
        names = [c for c in r if c and _norm(c)]
        if len(names) < 2:
            continue
        groups = [re.sub(r"\s+", " ", str(c)).strip() for c in r]
        return [
            {
                "type": "C",
                "strand_group": g,
                "strand": None,
                "sub_strand": None,
                "resources": None,
                "assessment": None,
                "page": page,
                "source": f"Appendix, p.{page}, {g}",
                "level": "strand",
                "_needs_cells": True,
                "_group_index": i,
            }
            for g in groups
        ]
    return out


_CODE_ITEM = re.compile(r"^\s*\d+(?:\.\d+)*\s+\S")


def _valid_resource_items(items: list[str]) -> list[str]:
    """Drop fragments that are really strand/sub-strand heading labels.

    A mis-read table can place heading cells such as '2.0 Communication in
    Pre-Technical Studies' into the resources columns; those are never
    resources, so they are rejected instead of being stored.
    """
    return [i for i in items if not _CODE_ITEM.match(i)]


def _read_type_d(rows: list[list[str]], page: int) -> list[dict[str, Any]]:
    """Header: Non-digital | Digital . Body: the two bullet lists side by side."""
    non_digital: list[str] = []
    digital: list[str] = []
    for r in rows:
        if len(r) < 2:
            continue
        non_digital.extend(cell_items(r[0] or ""))
        digital.extend(cell_items(r[1] or ""))
    non_digital = _valid_resource_items(non_digital)
    digital = _valid_resource_items(digital)
    merged = non_digital + digital
    if not merged:
        return []
    return [
        {
            "type": "D",
            "strand": None,
            "sub_strand": None,
            "resources": _join(merged),
            "assessment": None,
            "non_digital": _join(non_digital),
            "digital": _join(digital),
            "page": page,
            "source": f"Appendix, p.{page}, Subject resources",
            "level": "subject",
        }
    ]


def _read_numbered_assessment(text: str, page: int) -> dict[str, Any] | None:
    """Maths Appendix 2: '1. Written tests and quizzes' ... -> subject-level assessment."""
    items: list[str] = []
    for line in (text or "").split("\n"):
        m = re.match(r"\s*\d+[.)]\s+(.{3,120})", line)
        if m:
            item = re.sub(r"\s+", " ", m.group(1)).strip()
            if item and item.lower() not in {i.lower() for i in items}:
                items.append(item)
    if len(items) < 2:
        return None
    return {
        "type": "E",
        "strand": None,
        "sub_strand": None,
        "resources": None,
        "assessment": _join(items),
        "page": page,
        "source": f"Appendix 2, p.{page}",
        "level": "subject",
    }


# ---------------------------------------------------------------------------
# Space-preserving table extraction (PyMuPDF 2.x compatibility)
# ---------------------------------------------------------------------------


def _cell_bbox(cell_obj) -> tuple[float, float, float, float] | None:
    """Extract a bbox from a PyMuPDF 2.x cell object.

    PyMuPDF 2.x TableRow.cells contains plain tuples ``(x0, y0, x1, y1)``
    or ``None`` (for merged/empty cells). PyMuPDF 1.x returned objects with
    a ``.bbox`` attribute. Handle both transparently.
    """
    if cell_obj is None:
        return None
    if isinstance(cell_obj, (tuple, list)) and len(cell_obj) == 4:
        try:
            vals = tuple(float(v) for v in cell_obj)
            if vals[2] > vals[0] and vals[3] > vals[1]:
                return vals
        except (TypeError, ValueError):
            pass
        return None
    bbox = getattr(cell_obj, "bbox", None)
    if bbox is not None:
        try:
            return tuple(float(v) for v in bbox)
        except (TypeError, ValueError):
            pass
    return None


def _extract_cell_text(page: Any, cell_bbox) -> str:
    """Extract text from a cell's bounding box, preserving word spaces.

    PyMuPDF 2.x's ``tab.extract()`` concatenates text spans without spaces.
    Rebuilding from ``get_text('words')`` using each cell's bbox restores them.
    """
    if cell_bbox is None:
        return ""
    x0, y0, x1, y1 = cell_bbox
    words = page.get_text("words")
    cell_words = []
    for w in words:
        wx0, wy0, wx1, wy1, wtxt = w[:5]
        cx, cy = (wx0 + wx1) / 2, (wy0 + wy1) / 2
        if x0 - 1 <= cx <= x1 + 1 and y0 - 1 <= cy <= y1 + 1:
            cell_words.append((wy0, wx0, wtxt))
    if not cell_words:
        try:
            clipped = page.get_text("text", clip=fitz.Rect(x0, y0, x1, y1))
            if clipped and clipped.strip():
                return clipped
        except Exception:
            pass
        return ""
    cell_words.sort()
    lines = []
    cur_y = None
    cur_parts = []
    for wy, wx, wtxt in cell_words:
        if cur_y is None or abs(wy - cur_y) <= 3:
            cur_y = wy if cur_y is None else cur_y
            cur_parts.append((wx, wtxt))
        else:
            lines.append(" ".join(t for _, t in sorted(cur_parts)))
            cur_y = wy
            cur_parts = [(wx, wtxt)]
    if cur_parts:
        lines.append(" ".join(t for _, t in sorted(cur_parts)))
    return "\n".join(lines)


def _extract_rows(page: Any, tab) -> list[list[str]]:
    """Extract table rows with space-preserved cell text.

    PyMuPDF 2.x's ``tab.extract()`` concatenates words within a cell without spaces.
    This function rebuilds each cell from ``page.get_text('words')`` mapped to the
    cell's bounding box.

    Falls back to ``tab.extract()`` when cell bounding boxes are unavailable.
    """
    try:
        raw_rows = tab.extract() or []
    except Exception:
        return []
    if not raw_rows:
        return []
    rows_attr = getattr(tab, "rows", None)
    if rows_attr and hasattr(rows_attr, "__len__"):
        header = getattr(tab, "header", None)
        col_boundaries: list[tuple[float, float]] = []
        if header:
            header_cells = getattr(header, "cells", None)
            if header_cells:
                for hc in header_cells:
                    bbox = _cell_bbox(hc)
                    if bbox:
                        col_boundaries.append((bbox[0], bbox[2]))
        rebuilt = []
        for ri, row_obj in enumerate(rows_attr):
            if ri >= len(raw_rows):
                break
            raw = raw_rows[ri]
            row_bbox = _cell_bbox(row_obj) if not isinstance(row_obj, (tuple, list)) else None
            cells_attr = getattr(row_obj, "cells", None) if not isinstance(row_obj, (tuple, list)) else row_obj
            if not cells_attr:
                rebuilt.append(raw)
                continue
            new_cells = []
            for ci, cell_obj in enumerate(cells_attr):
                if ci >= len(raw):
                    break
                bbox = _cell_bbox(cell_obj)
                if bbox:
                    txt = _extract_cell_text(page, bbox)
                    new_cells.append(txt if txt else (raw[ci] if ci < len(raw) else ""))
                elif row_bbox and col_boundaries and ci < len(col_boundaries):
                    cx0, cx1 = col_boundaries[ci]
                    reconstructed = (cx0, row_bbox[1], cx1, row_bbox[3])
                    txt = _extract_cell_text(page, reconstructed)
                    new_cells.append(txt if txt else (raw[ci] if ci < len(raw) else ""))
                else:
                    new_cells.append(raw[ci] if ci < len(raw) else "")
            while len(new_cells) < len(raw):
                new_cells.append(raw[len(new_cells)])
            rebuilt.append(new_cells)
        return rebuilt
    return raw_rows


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def appendix_pages(doc: Any, start_from: int | None = None) -> list[tuple[int, Any]]:
    """Collect the appendix region of an open document.

    Starts at the first appendix heading (or ``start_from``) and keeps going through following
    pages that still carry appendix-table vocabulary, so continuation pages of a table (which
    have no heading of their own) are included. CSL guidelines and rubric pages that sit
    *between* appendix sections are skipped over rather than stopping the run — only a page
    that clearly exits the appendix (glossary, references, index) stops it.
    """
    out: list[tuple[int, Any]] = []
    active = False
    skip_prose = 0  # pages to skip (CSL guidelines etc.) without stopping
    for i, page in enumerate(doc):
        page_no = i + 1
        try:
            text = page.get_text("text") or ""
        except Exception:
            text = ""
        low = (text or "").lower()
        if not active:
            if start_from is not None and page_no < start_from:
                continue
            if is_appendix_page(text):
                active = True
            else:
                continue
        else:
            # Check for hard-stop markers: glossary, references, bibliography, index.
            if re.search(r"\b(glossary|references|bibliography|index)\b", low):
                break
            # Keep appendix mode while the page looks like an appendix table or heading.
            # CSL guidelines and rubrics are part of the appendix, so we skip over them
            # rather than stopping — the actual resource/assessment tables may come after.
            if is_appendix_page(text) or has_appendix_table(text):
                skip_prose = 0  # reset, we're back in table territory
            else:
                # This page doesn't look like an appendix table. Give it a few pages
                # of grace (CSL guidelines can span 3-4 pages) before stopping.
                skip_prose += 1
                if skip_prose > 5:
                    break
        out.append((page_no, page))
    return out


def _read_type_d_from_text(page: Any, raw_text: str, page_no: int) -> dict[str, Any] | None:
    """Parse a Non-digital | Digital resources layout when PyMuPDF finds no table.

    Some KICD PDFs lay out the subject resources as two columns of bullets without
    grid lines, so ``page.find_tables()`` returns nothing. This function uses
    ``get_text('words')`` and the x-position of the "Non-digital"/"Digital" headings
    to split the words into two columns.
    """
    low = (raw_text or "").lower()
    if "non-digital" not in low and "non digital" not in low:
        return None
    if "digital" not in low:
        return None

    words = page.get_text("words")
    if not words:
        return None

    # Find the x positions of "Non-digital" and "Digital" headings
    non_digital_x = None
    digital_x = None
    heading_y = None
    for w in words:
        wtxt_lower = w[4].lower()
        if wtxt_lower in ("non-digital", "non-digital"):
            non_digital_x = w[0]
            heading_y = w[1]
        if wtxt_lower == "digital" and w[1] < 120:  # heading position (top of page)
            digital_x = w[0]
            heading_y = w[1]

    if non_digital_x is None or digital_x is None:
        return None

    # The boundary between columns is the midpoint of the two headings
    col_boundary = (non_digital_x + digital_x) / 2

    # Gather bullet items in each column, below the heading row
    non_digital_items: list[str] = []
    digital_items: list[str] = []

    # Group words into lines by y-proximity, then split each line by column
    sorted_words = sorted(words, key=lambda w: (w[1], w[0]))
    lines: list[list[tuple[float, float, str]]] = []
    cur_y = None
    cur_line: list[tuple[float, float, str]] = []
    for w in sorted_words:
        wy = w[1]
        wx = w[0]
        wtxt = w[4]
        if cur_y is None or abs(wy - cur_y) <= 3:
            cur_y = wy if cur_y is None else cur_y
            cur_line.append((wx, wy, wtxt))
        else:
            lines.append(cur_line)
            cur_y = wy
            cur_line = [(wx, wy, wtxt)]
    if cur_line:
        lines.append(cur_line)

    for line in lines:
        if line[0][1] < (heading_y or 0) + 5:
            continue  # skip heading row
        left_words = [wtxt for wx, _, wtxt in line if wx < col_boundary]
        right_words = [wtxt for wx, _, wtxt in line if wx >= col_boundary]
        if left_words:
            txt = " ".join(left_words).strip()
            if txt and not txt.startswith("Non-digital"):
                non_digital_items.append(txt)
        if right_words:
            txt = " ".join(right_words).strip()
            if txt and not txt.startswith("Digital"):
                digital_items.append(txt)

    # Filter out empty/short fragments
    non_digital_items = [i for i in non_digital_items if len(i) > 2]
    digital_items = [i for i in digital_items if len(i) > 2]
    # Heading labels (e.g. '2.1 Oblique Projection') are never resources.
    non_digital_items = _valid_resource_items(non_digital_items)
    digital_items = _valid_resource_items(digital_items)

    merged = non_digital_items + digital_items
    if not merged:
        return None

    return {
        "type": "D",
        "strand": None,
        "sub_strand": None,
        "resources": _join(merged),
        "assessment": None,
        "non_digital": _join(non_digital_items),
        "digital": _join(digital_items),
        "page": page_no,
        "source": f"Appendix, p.{page_no}, Subject resources",
        "level": "subject",
    }


def parse_appendix(pages: list[tuple[int, Any]], verbose: bool = True) -> dict[str, Any]:
    """Parse appendix pages into structured appendix data.

    ``pages`` is a list of ``(page_number, fitz.Page)`` for the appendix region.
    Returns ``{"rows": [...], "subject_assessment": {...}|None, "subject_resources": ...}``.
    """
    rows: list[dict[str, Any]] = []
    subject_assessment: dict[str, Any] | None = None
    subject_resources: dict[str, Any] | None = None
    last_kind: str | None = None
    last_a_header: list[str] | None = None

    for page_no, page in pages:
        try:
            raw = page.get_text("text") or ""
        except Exception:
            raw = ""

        # Appendix 2 style numbered list.
        if re.search(r"suggested assessment methods and tools", raw, re.I):
            parsed = _read_numbered_assessment(raw, page_no)
            if parsed and subject_assessment is None:
                subject_assessment = parsed
                if verbose:
                    print(f"Appendix 2 assessment methods found on page {page_no}")
            continue

        try:
            tabs = page.find_tables()
            table_list = tabs.tables if hasattr(tabs, "tables") else (tabs or [])
        except Exception:
            table_list = []

        for tab in table_list:
            try:
                extracted = _extract_rows(page, tab)
            except Exception:
                continue
            if not extracted:
                continue
            clean = [[(c or "") for c in r] for r in extracted]

            # A table on a later page usually continues the previous page's table and has NO
            # header row. Remember the last kind so those rows are still read correctly.
            kind = classify_header(clean[0])
            had_header = kind is not None

            if kind is None and last_kind in ("A", "B"):
                # Headerless continuation of a Type A / Type B table.
                kind = last_kind
                body = clean
            elif kind is None:
                head = " ".join(_norm(c) for c in clean[0])
                if (
                    "assessment" not in head
                    and len([c for c in clean[0] if _norm(c)]) >= 2
                    and len(clean) >= 2
                ):
                    # Header row holds strand-group names (Type C). Generic table
                    # headings such as 'Milestone | Description' are not strand
                    # groups and must not feed the subject summary.
                    named = [_norm(c) for c in clean[0] if _norm(c)]
                    if not any(n in _NON_STRAND_HEADERS for n in named):
                        kind = "C"
                body = clean
            else:
                body = clean[1:]

            if kind == "A":
                header = clean[0] if had_header else last_a_header
                if had_header:
                    last_a_header = list(clean[0])
                rows.extend(_read_type_a(body, page_no, header))
            elif kind == "B":
                rows.extend(_read_type_b(body, page_no))
            elif kind == "D":
                got = _read_type_d(body, page_no)
                if got and subject_resources is None:
                    subject_resources = got[0]
                rows.extend(got)
            elif kind == "C":
                groups = [re.sub(r"\s+", " ", str(c)).strip() for c in clean[0] if _norm(c)]
                # A strand-group name is a short label ('Listening and Speaking');
                # prose picked up from body text is rejected so it never reaches
                # the subject summary.
                groups = [g for g in groups if _is_strand_group_name(g)]
                if not groups:
                    continue
                cells = clean[1] if len(clean) > 1 else []
                for i, g in enumerate(groups):
                    items = cell_items(cells[i]) if i < len(cells) else []
                    if not items:
                        continue
                    rows.append(
                        {
                            "type": "C",
                            "strand_group": g,
                            "strand": None,
                            "sub_strand": None,
                            "resources": None,
                            "assessment": _join(items),
                            "page": page_no,
                            "source": f"Appendix, p.{page_no}, {g}",
                            "level": "strand",
                        }
                    )

            if kind:
                last_kind = kind

        # Fallback: page has "Non-digital"/"Digital" headings but PyMuPDF found no table
        # (common when the resources are laid out as two-column bullets without grid lines).
        if not table_list and subject_resources is None:
            parsed_d = _read_type_d_from_text(page, raw, page_no)
            if parsed_d:
                subject_resources = parsed_d
                rows.append(parsed_d)
                if verbose:
                    print(f"Type D subject resources (text fallback) on page {page_no}")

    # Subject-wide summary built ONLY from real parsed appendix cells. Some designs
    # (e.g. Kiswahili "MUHTASARI WA MBINU ZA KUTATHMINI, NYENZO ZA KUFUNDISHIA")
    # organise their appendix by SKILL while the main tables group sub-strands by THEME,
    # so no strand-level join can ever match. Those appendix rows still describe the whole
    # subject, so aggregate them into a subject-level fallback. Nothing is invented: every
    # item below came out of a parsed appendix cell. Type A (sub-strand-specific) rows are
    # excluded so a strand's private resources never leak into a subject-wide value.
    summary_rows = [r for r in rows if r.get("level") in ("strand", "subject") and r.get("type") != "A"]

    def _aggregate(key: str) -> str | None:
        seen: set[str] = set()
        items: list[str] = []
        for r in summary_rows:
            for item in (r.get(key) or "").split(";"):
                item = item.strip()
                if item and item.lower() not in seen:
                    seen.add(item.lower())
                    items.append(item)
        return _join(items)

    summary_res = _aggregate("resources")
    summary_asm = _aggregate("assessment")
    subject_summary = None
    if summary_res or summary_asm:
        first_page = min((r.get("page") for r in summary_rows if r.get("page")), default=None)
        subject_summary = {
            "resources": summary_res,
            "assessment": summary_asm,
            "source": f"Appendix, p.{first_page}, Subject summary" if first_page else "Appendix, Subject summary",
            "level": "subject",
        }
        if verbose:
            print(f"Subject-level appendix summary: resources={'yes' if summary_res else 'no'}, "
                  f"assessment={'yes' if summary_asm else 'no'} (p.{first_page})")

    if verbose:
        print(
            f"Appendix parse: {len(rows)} row(s), "
            f"subject resources={'yes' if subject_resources else 'no'}, "
            f"subject assessment={'yes' if subject_assessment else 'no'}"
        )

    return {
        "rows": rows,
        "subject_resources": subject_resources,
        "subject_assessment": subject_assessment,
        "subject_summary": subject_summary,
    }


# ---------------------------------------------------------------------------
# Join
# ---------------------------------------------------------------------------

# English strand groups -> numeric strand suffix (Listening .1, Reading .2, Language .3, Writing .4).
_GROUP_SUFFIX = {
    "listening and speaking": ".1",
    "listening speaking": ".1",
    "reading": ".2",
    "reading skills": ".2",
    "language use": ".3",
    "grammar": ".3",
    "writing": ".4",
    "writing skills": ".4",
}


def _strand_suffix(strand: str, strand_code: str) -> str | None:
    """Derive '.N' from a strand name like '10.1 Listening and Speaking'."""
    m = re.match(r"\s*\d+\.(\d+)", strand_code or "")
    if m:
        return f".{m.group(1)}"
    low = _norm(strand)
    for key, suffix in _GROUP_SUFFIX.items():
        if low.endswith(key) or key in low:
            return suffix
    return None


def _type_c_for_type(row: dict[str, Any], strand: str, strand_code: str) -> bool:
    suffix = _strand_suffix(strand, strand_code)
    if not suffix:
        return False
    group = _norm(row.get("strand_group") or "")
    return _GROUP_SUFFIX.get(group) == suffix


def _strand_matches(row_strand: str, strand: str, strand_code: str) -> bool:
    """Type B strand match, e.g. row '1.0 Creation' vs chunk strand 'Creation' / '1.0'."""
    if not row_strand:
        return False
    rn = _norm(row_strand)
    sn = _norm(strand)
    code = (strand_code or "").strip()
    if rn == sn:
        return True
    m = re.match(r"\s*(\d+\.\d+)\s*(.*)$", row_strand)
    if m:
        row_code, row_name = m.group(1), _norm(m.group(2))
        if code and row_code == code:
            return True
        if row_name and sn:
            if row_name == sn or row_name in sn or sn.startswith(row_name):
                return True
            if _core_word(row_name) and _core_word(row_name) == _core_word(sn):
                return True
    return False


def _sub_matches(row_sub: str, sub: str, sub_code: str) -> bool:
    """Type A sub-strand match. Handles the appendix's two-word wraps and the
    code-prefixed row labels some designs use ('1.1 Safety on Raised Platforms'
    vs chunk sub-strand 'Safety on Raised Platforms')."""
    if not row_sub:
        return False
    rn = _norm(row_sub)
    sn = _norm(sub)
    if rn == sn:
        return True
    # Appendix may split 'NUMBER CONCEPT' across lines while the chunk says 'Number concept'.
    if rn.replace(" ", "") == sn.replace(" ", ""):
        return True
    m = re.match(r"\s*(\d+(?:\.\d+)+)\s+(.*)$", str(row_sub).strip())
    if m:
        row_code, row_name = m.group(1), _norm(m.group(2))
        code = (sub_code or "").strip()
        if code and row_code == code:
            return True
        if row_name and sn:
            if row_name == sn or row_name in sn or sn.startswith(row_name):
                return True
            if row_name.replace(" ", "") == sn.replace(" ", ""):
                return True
    return False


def join_appendix(chunk: dict[str, Any], appendix: dict[str, Any]) -> dict[str, Any]:
    """Attach appendix fields to one chunk dict (mutates and returns it).

    Precedence: sub-strand (A) -> strand (B, then C) -> subject (D / Appendix 2) -> None.
    """
    strand = chunk.get("strand") or ""
    strand_code = chunk.get("strandCode") or chunk.get("strand_code") or ""
    sub = chunk.get("subStrand") or chunk.get("sub_strand") or ""
    sub_code = chunk.get("subStrandCode") or chunk.get("sub_strand_code") or ""

    rows = appendix.get("rows") or []
    res = asm = src = lvl = None

    # 1) Type A: exact sub-strand.
    for row in rows:
        if row.get("type") != "A":
            continue
        if _sub_matches(row.get("sub_strand") or "", sub, sub_code):
            res = row.get("resources")
            asm = row.get("assessment")
            src = row.get("source")
            lvl = "sub_strand"
            break

    # 2) Type B: strand.
    if res is None and asm is None:
        for row in rows:
            if row.get("type") != "B":
                continue
            if _strand_matches(row.get("strand") or "", strand, strand_code):
                res = row.get("resources")
                asm = row.get("assessment")
                src = row.get("source")
                lvl = "strand"
                break

    # 3) Type C: strand group (English Listening/Reading/Language/Writing).
    if asm is None:
        for row in rows:
            if row.get("type") != "C":
                continue
            if _type_c_for_type(row, strand, strand_code):
                asm = row.get("assessment")
                if res is None:
                    src = row.get("source")
                    lvl = "strand"
                break

    # 4) Type D: subject resources.
    subject_res = appendix.get("subject_resources")
    if res is None and subject_res:
        res = subject_res.get("resources")
        if lvl is None:
            src = subject_res.get("source")
            lvl = "subject"

    # 5) Appendix 2: subject assessment fallback (only if nothing per-strand was found).
    if asm is None:
        subj = appendix.get("subject_assessment")
        if subj:
            asm = subj.get("assessment")
            if lvl is None:
                src = subj.get("source")
                lvl = "subject"

    # 6) Subject-wide appendix summary: used when the appendix is organised along a
    # different axis than the main tables (e.g. Kiswahili groups by language SKILL while
    # sub-strands group by THEME). Only real parsed cells, never invented content, and
    # only fills the fields that are still empty.
    if res is None and asm is None:
        summary = appendix.get("subject_summary")
        if summary:
            res = summary.get("resources")
            asm = summary.get("assessment")
            if res or asm:
                src = summary.get("source")
                lvl = "subject"

    chunk["appendix_resources"] = res
    chunk["appendix_assessment"] = asm
    chunk["appendix_source"] = src
    chunk["appendix_level"] = lvl
    return chunk
