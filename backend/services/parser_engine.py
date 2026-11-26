import copy
import json
import os
import re
import sys
import unicodedata
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from services.appendix_parser import appendix_pages, is_appendix_page, parse_appendix

GRADE = "Grade 1"

CANONICAL_FIELDS = [
    "specific_learning_outcomes",
    "suggested_learning_experiences",
    "key_inquiry_questions",
    "core_competencies",
    "values",
    "pcis",
    "link_to_other_learning_areas",
    "link_to_value",
]

DEFAULT_STOP_MARKERS = [
    "appendix",
    "references",
    "glossary",
    "bibliography",
    "sample assessment",
    "index",
    "acknowledgement",
]

# Appendix markers END sub-strand parsing but START appendix mode (resources/assessment).
APPENDIX_STOP_MARKERS = ("appendix", "appendices")


@dataclass
class ParseSession:
    """Per-job state. NEVER reuse across parse jobs/documents."""

    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    theme: str | None = None
    theme_code: str | None = None
    strand: str | None = None
    strand_code: str | None = None
    strand_page: int | None = None
    theme_page: int | None = None
    current: dict[str, Any] | None = None
    records: list[dict[str, Any]] = field(default_factory=list)
    seen_codes: dict[str, int] = field(default_factory=dict)  # key -> first page
    duplicates_skipped: int = 0
    stopped_at: int | None = None
    appendix_start: int | None = None


def _space_camel(text: str) -> str:
    """Insert spaces between CamelCase/PascalCase words so concatenated headers
    from PyMuPDF 2.x (e.g. 'SpecificLearningOutcomes') are recognised.

    'SuggestedKeyInquiryQuestion(s)' -> 'Suggested Key Inquiry Question(s)'
    """
    t = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    # Acronyms: 'KICD' should not split into 'K I C D'.
    t = re.sub(r"\b([A-Z])\s(?=[A-Z]\s)", r"\1", t)
    return t


# PyMuPDF 2.x sometimes mangles sub-strand codes inside table cells:
#   '1.2 Whole Numbers' -> '12Whole . Numbers'  (period displaced after the 2)
#   '1.3 Addition'       -> '13Addition .'       (period at end)
#   '1 .1 Pre-Number'    -> '1 .1 Pre-Number'    (space before period)
# This pattern repairs those artifacts so extract_code_title can find \d+\.\d+ .
# Only applies at the START of a cell (the code position) to avoid corrupting body text.
_MANGLED_CODE_START_PAT = re.compile(r"^\s*(\d)(\d)([A-Za-z])")
_MANGLED_PERIOD_PAT = re.compile(r"\b(\d)\s*\.\s*(\d)\b")


def _fix_mangled_codes(text: str) -> str:
    """Repair sub-strand codes mangled by PyMuPDF 2.x table extraction.

    '12Whole . Numbers (25lessons)' -> '1.2 Whole . Numbers (25lessons)'
    '1 .1 Pre-Number'               -> '1.1 Pre-Number'
    '13Addition .'                  -> '1.3 Addition .'

    Only repairs the code at the start of the cell — body text like '(25lessons)'
    is left alone so '25' in '25lessons' does not become '2.5'.
    """
    # First: '1 .1' or '1 . 1' -> '1.1'  (space before period between digits)
    t = _MANGLED_PERIOD_PAT.sub(r"\1.\2", text)
    # Then: '12Whole' at start -> '1.2 Whole' (digit-digit-letter at cell start only)
    t = _MANGLED_CODE_START_PAT.sub(r"\1.\2 \3", t)
    return t


def clean_cell(text: str) -> str:
    t = (text or "").replace("\r", " ").replace("\n", " ")
    t = _fix_mangled_codes(t)
    t = _space_camel(t)
    t = re.sub(r"\s+", " ", t).strip()
    t = t.replace(" ,", ",").replace(" .", ".").replace(" ?", "?")
    return t


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("\u00a0", " ").replace("\r", " ")
    s = "".join(ch for ch in s if not (0xE000 <= ord(ch) <= 0xF8FF))
    s = s.replace("\n", " ")
    return re.sub(r"\s+", " ", s).strip()


def load_archetypes(root: Path) -> dict[str, Any]:
    path = root / "profiles" / "archetypes.json"
    return json.loads(path.read_text(encoding="utf-8"))["archetypes"]


def detect_archetype(pdf_text: str, archetypes: dict[str, Any], doc: fitz.Document | None = None) -> tuple[str, dict[str, Any], float, str]:
    t = clean_cell(pdf_text)
    t_low = t.lower()
    has_vocab = "suggested vocabulary" in t_low
    codes_xyz = re.findall(r"\b\d+\.\d+\.\d+\b", t)
    codes_xy = [c for c in re.findall(r"\b\d+\.\d+\b", t) if not re.search(r"\b\d+\.\d+\.\d+\b", c)]
    only_xy = bool(codes_xy) and not bool(codes_xyz)
    has_rubric = "assessment rubric" in t_low

    toc_has_strand_x0 = False
    if doc is not None:
        try:
            for i in range(min(8, doc.page_count)):
                pt = clean_cell(doc[i].get_text("text") or "")
                pl = pt.lower()
                if "contents" in pl or "table of contents" in pl:
                    if re.search(r"strand\s+\d+\.0\s*:", pt, re.I):
                        toc_has_strand_x0 = True
                        break
        except Exception:
            toc_has_strand_x0 = False
    if not toc_has_strand_x0:
        toc_has_strand_x0 = bool(re.search(r"strand\s+\d+\.0\s*:", t, re.I))

    if has_vocab and re.search(r"\b\d+\.\d+\.\d+\b", t):
        return "A-Language", archetypes["A-Language"], 0.95, "Suggested vocabulary + X.Y.Z codes"
    if has_rubric and not (toc_has_strand_x0 and only_xy):
        return "B-Religious", archetypes["B-Religious"], 0.92, "Assessment rubric detected"
    if toc_has_strand_x0 and only_xy:
        return "C-ScienceMaths", archetypes["C-ScienceMaths"], 0.93, "TOC STRAND X.0 with X.Y-only codes"
    return "D-Practical", archetypes["D-Practical"], 0.6, "Fallback to D, confidence 0.6"


def collect_header_strings(doc: fitz.Document) -> list[str]:
    headers: list[str] = []
    seen = set()
    for page in doc:
        try:
            tabs = page.find_tables()
        except Exception:
            continue
        for tab in tabs.tables:
            try:
                rows = extract_table_rows(page, tab) or []
            except Exception:
                continue
            for row in rows[:2]:
                for cell in (row or []):
                    h = clean_cell(cell or "")
                    if len(h) < 3 or len(h) > 120:
                        continue
                    k = h.lower()
                    if k not in seen:
                        seen.add(k)
                        headers.append(h)
    return headers[:80]


def fallback_map_header(header: str) -> str | None:
    # PyMuPDF 2.x may concatenate CamelCase header words without spaces
    # ('SpecificLearningOutcomes'). Space them out BEFORE lowering so the
    # camelCase boundaries are still visible.
    h = _space_camel(clean_cell(header)).lower()
    h = re.sub(r"\s+", " ", h).strip()
    if not h:
        return None
    if "rubric" in h or "exceeds expectation" in h or "meets expectation" in h or "approach" in h or "below expectation" in h:
        return "skip_rubric"
    if "competenc" in h or "umilisi" in h:
        return "core_competencies"
    if "value" in h and "link to value" not in h and "uhusiano" not in h and "maadili" not in h:
        return "values"
    if "maadili" in h and "uhusiano" not in h:
        return "values"
    if "pertinent" in h or "contemporary" in h or "pcis" in h or "masuala" in h:
        return "pcis"
    if "link to value" in h:
        return "link_to_value"
    if "link to other" in h or "uhusiano" in h or "link to subjects" in h or "other learning" in h:
        return "link_to_other_learning_areas"
    if "inquiry" in h and "question" in h:
        return "key_inquiry_questions"
    if "key inquiry" in h or "maswali" in h:
        return "key_inquiry_questions"
    if "suggested learning experiences" in h or "learning experiences" in h or "shughuli" in h:
        return "suggested_learning_experiences"
    if "specific learning outcomes" in h or "learning outcomes" in h or "matokeo" in h:
        return "specific_learning_outcomes"
    if "sub" in h and "strand" in h:
        return "sub_strand"
    if h in {"strand", "theme", "mkondo"} or (h.startswith("strand") and "sub" not in h):
        return "strand"
    return None


def gemini_header_mapping(headers: list[str]) -> dict[str, str] | None:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or not headers:
        return None
    try:
        from google import genai
        from google.genai import types

        prompt = (
            "Map these headers to canonical fields. Return JSON mapping only (object of header->canonical). "
            "Canonical fields: specific_learning_outcomes, suggested_learning_experiences, key_inquiry_questions, "
            "core_competencies, values, pcis, link_to_other_learning_areas, link_to_value, strand, sub_strand, skip_rubric, ignore. "
            "Map any assessment rubric headers (Exceeds Expectations/Meets/Approaches/Below) to skip_rubric. "
            "Headers: " + json.dumps(headers, ensure_ascii=False)
        )
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0, response_mime_type="application/json"),
        )
        data = json.loads(resp.text)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except Exception:
        return None
    return None


def map_header(header: str, mapping: dict[str, str] | None) -> str | None:
    if mapping:
        if header in mapping:
            return mapping[header]
        h = clean_cell(header).lower()
        for k, v in mapping.items():
            if clean_cell(k).lower() == h:
                return v
    return fallback_map_header(header)


def row_is_rubric(row: list[str], mapping: dict[str, str] | None) -> bool:
    for c in row:
        m = map_header(c, mapping)
        if m == "skip_rubric":
            return True
        h = clean_cell(c).lower()
        if "exceeds expectation" in h or "meets expectation" in h or "approaches expectation" in h or "below expectation" in h or "assessment rubric" in h:
            return True
    return False


def split_outcomes(cell: str) -> list[str]:
    t = clean_cell(cell)
    t = re.sub(r"^By the end of the (?:sub\s*-?\s*strand|strand).*?able to:\s*", "", t, flags=re.I)
    parts = re.split(r"\s*(?=[a-h]\)\s)", t)
    return [p.strip() for p in parts if len(p.strip()) > 5]


def split_experiences(cell: str) -> list[str]:
    t = clean_cell(cell)
    t = re.sub(r"^The learner is guided to:\s*", "", t, flags=re.I)
    # PyMuPDF recovers the design's bullet as a private-use glyph (Wingdings U+F0B7,
    # U+E006, ...). Without normalising it, the whole experience cell became one item.
    t = re.sub(r"[\ue000-\uf8ff]", "•", t)
    parts = re.split(r"\s*[•■▪\-–]\s+", t)
    return [p.strip().lstrip("•■▪-– ").strip() for p in parts if len(p.strip().lstrip("•■▪-– ").strip()) > 5]


def split_kiqs(cell: str) -> list[str]:
    t = clean_cell(cell)
    t = re.sub(r"(\d+)\.\s*", r"\1. ", t)
    parts = re.split(r"(?<=\?)\s+|(?=\d+\.\s)", t)
    result = []
    for p in parts:
        p = re.sub(r"^\d+\.\s*", "", clean_cell(p)).strip()
        if p:
            result.append(p)
    merged = []
    buffer = ""
    for item in result:
        buffer = (buffer + " " + item).strip() if buffer else item
        if "?" in buffer:
            qs = re.findall(r"[^?]+\?", buffer)
            if len(qs) > 1 and re.search(r"\d+\.\s", buffer):
                for q in qs:
                    q = clean_cell(q)
                    if len(q) > 5:
                        merged.append(q)
                buffer = ""
            elif buffer.endswith("?"):
                merged.append(buffer)
                buffer = ""
    if buffer:
        merged.append(buffer)
    return [m for m in merged if len(m) > 5]


def extract_code_title(cell: str, depth: int) -> tuple[str, str, int | None] | None:
    t = clean_cell(cell)
    pats = []
    if depth >= 3:
        pats.append(re.compile(r"\b(\d+\.\d+\.\d+)\b"))
    pats.append(re.compile(r"\b(\d+\.\d+)\b"))
    for pat in pats:
        m = pat.search(t)
        if not m:
            continue
        code = m.group(1)
        rest = clean_cell(t[m.end():]).strip(" :-")
        if not rest:
            rest = clean_cell(t[:m.start()]).strip(" :-")
        # PyMuPDF 2.x may leave a stray period between the title words
        # ('Whole. Numbers') from the displaced code period. Remove it.
        rest = re.sub(r"\.\s+", " ", rest)
        title = re.sub(r"\s*\(\s*\d+\s*lessons?\s*\)\s*$", "", rest, flags=re.I).strip()
        lessons = None
        lm = re.search(r"\(\s*(\d+)\s*lessons?\s*\)", clean_cell(cell), flags=re.I)
        if lm:
            lessons = int(lm.group(1))
        if len(title) < 5 or title.lower() == "the":
            continue
        return code, title, lessons
    return None


def map_header_row(row: list[str], mapping: dict[str, str] | None) -> dict[str, int] | None:
    idx: dict[str, int] = {}
    for i, cell in enumerate(row):
        m = map_header(cell, mapping)
        if m in CANONICAL_FIELDS and m not in idx:
            idx[m] = i
        elif m == "strand" and "strand" not in idx:
            idx["strand"] = i
        elif m == "sub_strand" and "sub_strand" not in idx:
            idx["sub_strand"] = i
    if "specific_learning_outcomes" not in idx and "suggested_learning_experiences" not in idx:
        return None
    idx.setdefault("strand", 0)
    idx.setdefault("sub_strand", 1)
    idx.setdefault("specific_learning_outcomes", 2)
    idx.setdefault("suggested_learning_experiences", 3)
    idx.setdefault("key_inquiry_questions", 4)
    return idx


def _cell_bbox(cell_obj) -> tuple[float, float, float, float] | None:
    """Extract a bbox from a PyMuPDF 2.x cell object.

    PyMuPDF 2.x TableRow.cells contains plain tuples ``(x0, y0, x1, y1)``
    or ``None`` (for merged/empty cells). PyMuPDF 1.x returned objects with
    a ``.bbox`` attribute. Handle both transparently.
    """
    if cell_obj is None:
        return None
    # PyMuPDF 2.x: cell is a plain tuple (x0, y0, x1, y1)
    if isinstance(cell_obj, (tuple, list)) and len(cell_obj) == 4:
        try:
            vals = tuple(float(v) for v in cell_obj)
            # Sanity check: bbox must have positive width and height
            if vals[2] > vals[0] and vals[3] > vals[1]:
                return vals
        except (TypeError, ValueError):
            pass
        return None
    # PyMuPDF 1.x: cell is an object with .bbox
    bbox = getattr(cell_obj, "bbox", None)
    if bbox is not None:
        try:
            return tuple(float(v) for v in bbox)
        except (TypeError, ValueError):
            pass
    return None


def _extract_cell_text(page: fitz.Page, cell_bbox) -> str:
    """Extract text from a cell's bounding box, preserving word spaces.

    PyMuPDF 2.x's ``tab.extract()`` concatenates text spans without spaces when they
    share a line (e.g. 'Bytheendofthesub'). Rebuilding from ``get_text('words')``
    using each cell's bbox restores the spaces.
    """
    if cell_bbox is None:
        return ""
    x0, y0, x1, y1 = cell_bbox
    words = page.get_text("words")
    # Gather words whose center falls inside the cell bbox.
    cell_words = []
    for w in words:
        wx0, wy0, wx1, wy1, wtxt = w[:5]
        cx, cy = (wx0 + wx1) / 2, (wy0 + wy1) / 2
        if x0 - 1 <= cx <= x1 + 1 and y0 - 1 <= cy <= y1 + 1:
            cell_words.append((wy0, wx0, wtxt))
    if not cell_words:
        # Fallback: use get_text('text') with clip
        try:
            clipped = page.get_text("text", clip=fitz.Rect(x0, y0, x1, y1))
            if clipped and clipped.strip():
                return clipped
        except Exception:
            pass
        return ""
    cell_words.sort()
    # Group into lines by y proximity, then join words left-to-right.
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


def extract_table_rows(page: fitz.Page, tab) -> list[list[str]]:
    """Extract table rows with space-preserved cell text.

    PyMuPDF 2.x's ``tab.extract()`` concatenates words within a cell without spaces
    (e.g. 'Bytheendofthesub'). This function rebuilds each cell from
    ``page.get_text('words')`` mapped to the cell's bounding box.

    Falls back to ``tab.extract()`` when cell bounding boxes are unavailable.
    """
    try:
        raw_rows = tab.extract() or []
    except Exception:
        return []
    if not raw_rows:
        return []
    # Try to get per-cell bboxes from the table's row objects.
    rows_attr = getattr(tab, "rows", None)
    if rows_attr and hasattr(rows_attr, "__len__"):
        # Also get header column boundaries as a fallback for merged cells.
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
                    # Merged cell: reconstruct bbox from row bbox + column boundary
                    cx0, cx1 = col_boundaries[ci]
                    reconstructed = (cx0, row_bbox[1], cx1, row_bbox[3])
                    txt = _extract_cell_text(page, reconstructed)
                    new_cells.append(txt if txt else (raw[ci] if ci < len(raw) else ""))
                else:
                    new_cells.append(raw[ci] if ci < len(raw) else "")
            # Pad to match raw row width
            while len(new_cells) < len(raw):
                new_cells.append(raw[len(new_cells)])
            rebuilt.append(new_cells)
        return rebuilt
    return raw_rows


def text_after_rect(page: fitz.Page, rect: fitz.Rect | None) -> str:
    words = page.get_text("words")
    if not rect:
        return clean_cell(page.get_text("text"))
    lines = []
    for w in words:
        x0, y0, x1, y1, txt = w[:5]
        if y0 > rect.y1 - 2:
            lines.append((y0, x0, txt))
    lines.sort()
    rows = []
    cur = {"y": None, "parts": []}
    for y, x, txt in lines:
        if cur["y"] is None or abs(y - cur["y"]) <= 3:
            cur["y"] = y if cur["y"] is None else cur["y"]
            cur["parts"].append((x, txt))
        else:
            rows.append(" ".join(t for _, t in sorted(cur["parts"])))
            cur = {"y": y, "parts": [(x, txt)]}
    if cur["parts"]:
        rows.append(" ".join(t for _, t in sorted(cur["parts"])))
    return clean_cell(" ".join(rows))


def parse_full_width(text: str, mapping: dict[str, str] | None) -> dict[str, str]:
    t = clean_cell(text)
    low = t.lower()
    candidates = [
        ("core_competencies", ["core competencies to be developed", "core competencies", "umilisi"]),
        ("values", ["values:", "values ", "maadili"]),
        ("pcis", ["pertinent and contemporary issues", "masuala ya kisasa", "pcis"]),
        ("link_to_other_learning_areas", ["link to other learning areas", "link to other subjects", "uhusiano"]),
        ("link_to_value", ["link to value", "link to values"]),
    ]
    found = []
    for key, names in candidates:
        for name in names:
            nm = name.lower().strip(": ")
            pos = low.find(nm)
            if pos >= 0:
                found.append((pos, key, nm))
                break
    best = {}
    for pos, key, nm in found:
        if key not in best or pos < best[key][0]:
            best[key] = (pos, nm)
    ordered = sorted(((p, k, n) for k, (p, n) in best.items()), key=lambda x: x[0])
    out = {k: "" for k in CANONICAL_FIELDS}
    for i, (pos, key, nm) in enumerate(ordered):
        start = pos + len(nm)
        if start < len(t) and t[start] == ":":
            start += 1
        end = ordered[i + 1][0] if i + 1 < len(ordered) else len(t)
        val = clean_cell(t[start:end])
        val = re.split(r"\s*\d+\.\d+(?:\.\d+)?\s+", val)[0].strip()
        val = re.split(r"\bExceeds Expectation|\bAssessment Rubric\b|\bMeets Expectation\b|\bApproaches Expectation\b|\bBelow Expectation\b", val, maxsplit=1, flags=re.I)[0].strip()
        # These full-width cells list several items with the same private-use bullet glyph;
        # keep the boundary so the API can store one value per item.
        val = re.sub(r"[\ue000-\uf8ff•■▪]+", "; ", val)
        val = re.sub(r"\s*;\s*", "; ", clean_cell(val)).strip("; ")
        out[key] = val
    return out


def detect_strand_heading(page_txt: str, page_no: int) -> tuple[str, str, int] | None:
    """Fallback strand detection BEFORE table parsing (Creative Arts / non-standard)."""
    m = re.search(r"(?im)^\s*STRAND\s+(\d+\.0)\s*[:\-]?\s*(.+?)\s*$", page_txt)
    if m:
        code = m.group(1)
        name = clean_cell(m.group(2))
        name = re.sub(r"\s*(Suggested|Strand|Sub strand|Specific).*$", "", name, flags=re.I).strip()
        if len(name) >= 2:
            print(f"Strand found via heading: {code} {name} on page {page_no}")
            return code, name, page_no
    m = re.search(r"(?im)^\s*(\d+\.0)\s+(Music|Art and Craft|Art|Dance|Drama|Performing Arts|Creative Arts|Physical Education)\b.*$", page_txt)
    if m:
        code = m.group(1)
        name = clean_cell(m.group(2))
        print(f"Strand found via heading: {code} {name} on page {page_no}")
        return code, name, page_no
    return None


def validate_parent(session: ParseSession, page_start: int, sub_strand_code: str) -> tuple[str | None, str | None, float, list[str]]:
    """Stronger page-proximity check. Never reuse old strand from previous job (session is per-job)."""
    flags: list[str] = []
    conf = 1.0
    strand = session.strand
    strand_code = session.strand_code
    if not strand or session.strand_page is None:
        return None, None, 0.0, ["Parent not found on nearby page - needs review"]
    if page_start - session.strand_page > 2:
        return None, None, 0.0, ["Parent not found on nearby page - needs review"]
    return strand, strand_code, conf, flags


def make_record(
    arch: dict[str, Any],
    scode: str,
    title: str,
    lessons_count: int | None,
    v_strand: str | None,
    v_strand_code: str | None,
    rec_theme: str | None,
    rec_theme_code: str | None,
    page_no: int,
    v_conf: float,
    v_flags: list[str],
    outcomes: list[str],
    experiences: list[str],
    kiqs: list[str],
    core: str | None,
    values: str | None,
    pcis: str | None,
    link: str | None,
    link_value: str | None,
) -> dict[str, Any]:
    """Create a fresh record with deep-copied lists (no aliasing)."""
    rec: dict[str, Any] = {
        "theme": rec_theme if arch.get("has_theme") else None,
        "theme_code": rec_theme_code if arch.get("has_theme") else None,
        "strand": v_strand,
        "strand_code": v_strand_code,
        "sub_strand": title,
        "sub_strand_code": scode,
        "lessons": lessons_count,
        "specific_learning_outcomes": list(outcomes),
        "suggested_learning_experiences": list(experiences),
        "key_inquiry_questions": list(kiqs),
        "core_competencies": core,
        "values": values,
        "pcis": pcis,
        "link_to_other_learning_areas": link,
        "link_to_value": link_value,
        "page_start": page_no,
        "confidence": round(v_conf, 2),
        "flags": list(v_flags),
    }
    return rec


def parse_pdf(pdf_bytes: bytes, root: Path, override_archetype: str | None = None, job_id: str | None = None) -> dict[str, Any]:
    archetypes = load_archetypes(root)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    session = ParseSession(job_id=job_id or str(uuid.uuid4()))
    try:
        full_text_parts = []
        theme_map: dict[str, str] = {}
        for page in doc:
            full_text_parts.append(page.get_text("text") or "")
        full_text = "\n".join(full_text_parts)
        for m in re.finditer(r"\b(\d+\.0)\s+([A-Za-z][A-Za-z ,&'()\-]{2,80})", clean_cell(full_text)):
            code, name = m.group(1), clean_cell(m.group(2))
            if "suggested vocabulary" in name.lower():
                continue
            for stop in [" Suggested", " Strand", " Sub strand", " Specific"]:
                if stop in name:
                    name = name.split(stop)[0].strip()
            theme_map.setdefault(code.split(".")[0], name)

        det_id, det_arch, det_conf, det_reason = detect_archetype(full_text, archetypes, doc)
        if override_archetype and override_archetype in archetypes:
            arch_id, arch = override_archetype, archetypes[override_archetype]
            confidence = det_conf
            reason = f"Teacher override ({override_archetype}); auto-detect suggested {det_id}"
        else:
            arch_id, arch, confidence, reason = det_id, det_arch, det_conf, det_reason

        headers = collect_header_strings(doc)
        mapping = gemini_header_mapping(headers)
        mapping_source = "gemini" if mapping else "fallback"

        tables_found = matched_tables = rubric_skipped = 0
        warnings = []
        stop_markers = arch.get("stop_markers") or DEFAULT_STOP_MARKERS

        for pi, page in enumerate(doc):
            if session.stopped_at is not None:
                break
            page_no = pi + 1
            raw_page = page.get_text("text") or ""

            # 3) Stop at back-matter. Appendix/appendices is NOT a stop: it starts APPENDIX MODE
            #    so Resources/Assessment can be auto-filled (Phase 3.5).
            head = raw_page[:500].lower()
            if session.records:
                if is_appendix_page(raw_page):
                    session.appendix_start = page_no
                    session.stopped_at = page_no
                    print(f"Appendix mode started on page {page_no}")
                    break
                for marker in stop_markers:
                    if marker in APPENDIX_STOP_MARKERS:
                        continue  # handled by is_appendix_page above
                    if marker in head:
                        # Exception: "assessment rubric" with archetype B -> skip rubric table but continue
                        if marker == "assessment rubric" and arch.get("has_rubric"):
                            continue
                        session.stopped_at = page_no
                        print(f"Stopped at back-matter marker '{marker}' on page {page_no}")
                        break
            if session.stopped_at is not None:
                break

            page_txt = clean_cell(raw_page)

            # Fallback strand detection BEFORE table parsing
            sh = detect_strand_heading(raw_page, page_no)
            if sh:
                sc, sn, sp = sh
                if not arch.get("has_theme"):
                    session.strand_code = sc
                    session.strand = sn
                    session.strand_page = sp
                else:
                    session.strand_code = sc
                    session.strand = f"{sc} {sn}".strip()
                    session.strand_page = sp

            # hierarchy markers
            if arch.get("has_theme"):
                for m0 in re.finditer(r"\b(\d+\.0)\s+([A-Za-z][A-Za-z ,&'()\-]{2,80})", page_txt):
                    val = clean_cell(f"{m0.group(1)} {m0.group(2)}")
                    if "suggested vocabulary" not in val.lower():
                        session.theme_code, session.theme = m0.group(1), val
                        session.theme_page = page_no
                for my in re.finditer(r"\b(\d+\.\d+)\s+([A-Za-z][A-Za-z ,&'()\-]{2,80})", page_txt):
                    if re.search(r"\b\d+\.\d+\.\d+\b", my.group(0)):
                        continue
                    code = my.group(1)
                    if code.endswith(".0"):
                        continue
                    session.strand_code, session.strand = code, clean_cell(f"{code} {my.group(2)}")
                    session.strand_page = page_no
            else:
                ms = re.search(r"STRAND\s+(\d+\.0)\s*:?\s*([A-Za-z][A-Za-z ,&'()\-]{2,80})", page_txt, re.I)
                if ms:
                    session.strand_code = ms.group(1)
                    raw = clean_cell(ms.group(2))
                    for stop in [" Strand", " Sub strand", " Specific", " Suggested", " Key Inquiry"]:
                        if stop in raw:
                            raw = raw.split(stop)[0].strip()
                    session.strand = raw
                    session.strand_page = page_no
                if not session.strand:
                    m0b = re.search(r"(?:STRAND\s+)?(\d+\.0)\s*:?\s*(NUMBERS|MEASUREMENT|GEOMETRY|MUSIC|ART|DANCE|DRAMA|PERFORMING ARTS|[A-Z][A-Za-z ]{2,40})", page_txt, re.I)
                    if m0b:
                        session.strand_code = m0b.group(1)
                        session.strand = clean_cell(m0b.group(2))
                        session.strand_page = page_no

            try:
                tabs = page.find_tables()
            except Exception:
                tabs = []
            page_had_main = False
            page_created_record = False
            last_main_rect = None
            table_list = tabs.tables if hasattr(tabs, "tables") else (tabs or [])
            for tab in table_list:
                if session.stopped_at is not None:
                    break
                tables_found += 1
                try:
                    rows = extract_table_rows(page, tab) or []
                except Exception:
                    continue
                if not rows:
                    continue
                crow = [clean_cell(c or "") for c in rows[0]]
                if arch.get("has_rubric") and row_is_rubric(crow, mapping):
                    rubric_skipped += 1
                    continue
                colmap = None
                header_idx = -1
                for ri, row in enumerate(rows[:3]):
                    rr = [clean_cell(c or "") for c in row]
                    if arch.get("has_rubric") and row_is_rubric(rr, mapping):
                        rubric_skipped += 1
                        colmap = None
                        header_idx = -2
                        break
                    m = map_header_row(rr, mapping)
                    if m:
                        colmap, header_idx = m, ri
                        break
                if header_idx == -2 or not colmap:
                    if session.current and any(re.search(r"\b\d+\.\d+(?:\.\d+)?\b", " ".join(clean_cell(c or '') for c in r)) for r in rows[:4]):
                        colmap = {"strand": 0, "sub_strand": 1, "specific_learning_outcomes": 2, "suggested_learning_experiences": 3, "key_inquiry_questions": 4}
                        header_idx = -1
                    else:
                        continue
                matched_tables += 1
                page_had_main = True
                last_main_rect = fitz.Rect(tab.bbox)

                for row in rows[header_idx + 1:]:
                    cells = [clean_cell(c or "") for c in row]
                    if not any(cells):
                        continue
                    if arch.get("has_rubric") and row_is_rubric(cells, mapping):
                        rubric_skipped += 1
                        continue

                    def g(k, d=""):
                        i = colmap.get(k, -99)
                        return cells[i] if 0 <= i < len(cells) else d

                    sub_cell = g("sub_strand")
                    strand_cell = g("strand")
                    all_joined = " ".join(cells)
                    if session.current:
                        fw = parse_full_width(all_joined, mapping)
                        attached = False
                        for k in CANONICAL_FIELDS:
                            if k in ["specific_learning_outcomes", "suggested_learning_experiences", "key_inquiry_questions"]:
                                continue
                            if fw.get(k) and not clean_cell(str(session.current.get(k) or "")):
                                session.current[k] = fw[k]
                                attached = True
                        if attached and not re.search(r"\b\d+\.\d+(?:\.\d+)?\b", sub_cell):
                            continue

                    ct = extract_code_title(sub_cell, int(arch.get("code_depth", 2)))
                    has_code = bool(re.search(r"\b\d+\.\d+(?:\.\d+)?\b", sub_cell))
                    if ct:
                        scode, stitle, lessons_count = ct
                        title = re.sub(r"\s*\d+\s+lessons?\s*$", "", stitle, flags=re.I).strip() or stitle

                        # strand from table cell (same document only)
                        if arch.get("has_theme"):
                            if strand_cell and re.search(r"\b\d+\.\d+\b", strand_cell):
                                msc = re.search(r"\b(\d+\.\d+)\b", strand_cell)
                                if msc and not msc.group(1).endswith(".0"):
                                    session.strand_code = msc.group(1)
                                    session.strand = clean_cell(strand_cell)
                                    session.strand_page = page_no
                        else:
                            scell = clean_cell(strand_cell)
                            ms0 = re.search(r"STRAND\s+(\d+\.0)\s*:?\s*([A-Za-z][A-Za-z ,&'()\-]{2,80})", scell, re.I)
                            if ms0:
                                session.strand_code = ms0.group(1)
                                sname = clean_cell(ms0.group(2))
                                for stop in [" Strand", " Sub strand", " Specific", " Suggested", " Key Inquiry"]:
                                    if stop in sname:
                                        sname = sname.split(stop)[0].strip()
                                session.strand = sname
                                session.strand_page = page_no
                            elif re.search(r"\b\d+\.0\b", scell):
                                m0c = re.search(r"\b(\d+\.0)\b", scell)
                                session.strand_code = m0c.group(1) if m0c else session.strand_code
                                sname = re.sub(r".*\b\d+\.0\b\s*:?\s*", "", scell, flags=re.I).strip()
                                for stop in [" Strand", " Sub strand", " Specific", " Suggested", " Key Inquiry"]:
                                    if stop in sname:
                                        sname = sname.split(stop)[0].strip()
                                if sname:
                                    session.strand = sname
                                    session.strand_page = page_no

                        v_strand, v_strand_code, v_conf, v_flags = validate_parent(session, page_no, scode)
                        if not arch.get("has_theme") and v_strand:
                            v_strand = re.sub(r"^STRAND\s*", "", clean_cell(v_strand), flags=re.I).strip()
                            v_strand = re.sub(r"^\d+\.0\s*:?\s*", "", v_strand).strip() or v_strand
                            if re.match(r"^\d+\.\d+\s", v_strand):
                                names = {"1": "Numbers", "2": "Measurement", "3": "Geometry", "4": "Data Handling"}
                                major = scode.split(".")[0]
                                v_strand = names.get(major, None)
                        if not arch.get("has_theme") and not v_strand_code:
                            v_strand_code = f"{scode.split('.')[0]}.0"

                        # 2) Dedup by code - keep first, discard repeats
                        dedup_strand = v_strand_code or session.strand_code or "0.0"
                        key = f"{dedup_strand}|{scode}"
                        if key in session.seen_codes:
                            session.duplicates_skipped += 1
                            print(f"Duplicate sub-strand {scode} on page {page_no} ignored - already seen on page {session.seen_codes[key]}")
                            session.current = None  # prevent continuation leaking into prior record
                            continue
                        session.seen_codes[key] = page_no

                        rec_theme = rec_theme_code = None
                        if arch.get("has_theme"):
                            maj = scode.split(".")[0]
                            if maj in theme_map:
                                rec_theme = theme_map[maj]
                                rec_theme_code = f"{maj}.0"
                            else:
                                rec_theme = session.theme
                                rec_theme_code = session.theme_code
                            if rec_theme:
                                rec_theme = re.sub(r"^\d+\.0\s+", "", rec_theme).strip() or rec_theme

                        out_list = list(split_outcomes(g("specific_learning_outcomes")))
                        exp_list = list(split_experiences(g("suggested_learning_experiences")))
                        kiq_list = list(split_kiqs(g("key_inquiry_questions")))

                        rec = make_record(
                            arch=arch,
                            scode=scode,
                            title=title,
                            lessons_count=lessons_count,
                            v_strand=(session.strand if arch.get("has_theme") else v_strand),
                            v_strand_code=(session.strand_code if arch.get("has_theme") else v_strand_code),
                            rec_theme=rec_theme,
                            rec_theme_code=rec_theme_code,
                            page_no=page_no,
                            v_conf=v_conf,
                            v_flags=v_flags,
                            outcomes=out_list,
                            experiences=exp_list,
                            kiqs=kiq_list,
                            core=clean_cell(g("core_competencies")) or None,
                            values=clean_cell(g("values")) or None,
                            pcis=clean_cell(g("pcis")) or None,
                            link=clean_cell(g("link_to_other_learning_areas")) or None,
                            link_value=clean_cell(g("link_to_value")) or None,
                        )
                        session.current = rec
                        session.records.append(rec)  # rec is fresh; no aliasing
                        page_created_record = True

                    elif session.current and not has_code and (g("specific_learning_outcomes") or g("suggested_learning_experiences") or g("key_inquiry_questions")):
                        # 4) Page-range validation: only attach from within [page_start, page_start+3]
                        start = int(session.current.get("page_start") or 0)
                        if start and page_no - start > 3:
                            print(f"Warning: rejected continuation from page {page_no} for sub-strand starting on page {start}")
                            continue
                        for x in split_outcomes(g("specific_learning_outcomes")):
                            if x not in session.current["specific_learning_outcomes"]:
                                session.current["specific_learning_outcomes"].append(x)
                        for x in split_experiences(g("suggested_learning_experiences")):
                            if x not in session.current["suggested_learning_experiences"]:
                                session.current["suggested_learning_experiences"].append(x)
                        for x in split_kiqs(g("key_inquiry_questions")):
                            if x not in session.current["key_inquiry_questions"]:
                                session.current["key_inquiry_questions"].append(x)

            if session.current and session.stopped_at is None:
                start = int(session.current.get("page_start") or 0)
                if not start or page_no - start <= 3:
                    # A continuation page repeats the table header at the bottom but adds no
                    # sub-strand row; the core competencies/values/PCIs sit *above* that header.
                    # Reading only after the table rect missed them, so use the whole page when
                    # this page created no record of its own.
                    after = page_txt if (page_had_main and not page_created_record) or not page_had_main \
                        else text_after_rect(page, last_main_rect)
                    fw = parse_full_width(after, mapping)
                    for k in CANONICAL_FIELDS:
                        if k in ["specific_learning_outcomes", "suggested_learning_experiences", "key_inquiry_questions"]:
                            continue
                        if fw.get(k) and not clean_cell(str(session.current.get(k) or "")):
                            session.current[k] = fw[k]

        cleaned = []
        for r in session.records:
            if not r.get("sub_strand") or len(str(r["sub_strand"])) < 5 or r.get("sub_strand") == "The":
                continue
            # deep-copy lists defensively in final output
            r["specific_learning_outcomes"] = list(r.get("specific_learning_outcomes") or [])
            r["suggested_learning_experiences"] = list(r.get("suggested_learning_experiences") or [])
            r["key_inquiry_questions"] = list(r.get("key_inquiry_questions") or [])
            r["flags"] = list(r.get("flags") or [])
            for k in ["specific_learning_outcomes", "suggested_learning_experiences", "key_inquiry_questions"]:
                seen = []
                out = []
                for x in r[k]:
                    if x and x not in seen:
                        seen.append(x)
                        out.append(x)
                r[k] = out
            cleaned.append(r)

        if not cleaned and matched_tables == 0:
            warnings.append("Layout not recognised - needs review")
            confidence = min(confidence, 0.2)

        # 4b) APPENDIX MODE - read the appendix tables so Resources/Assessment can be
        # auto-filled on the scheme. This never invents content: unmatched chunks keep None.
        appendix = {"rows": [], "subject_resources": None, "subject_assessment": None}
        if session.appendix_start:
            try:
                appendix = parse_appendix(appendix_pages(doc, session.appendix_start))
            except Exception as exc:  # appendix is an enhancement, never fatal
                warnings.append(f"Appendix could not be parsed: {exc}")

        # 5) Log duplicates / stop
        print(f"Total records: {len(cleaned)}, Duplicates skipped: {session.duplicates_skipped}, Back-matter stop page: {session.stopped_at}")
        sys.stdout.flush()

        result = {
            "jobId": session.job_id,
            "archetype": arch_id,
            "archetypeName": arch.get("name"),
            "confidence": round(float(confidence), 2),
            "detectionReason": reason,
            "mappingSource": mapping_source,
            "tablesFound": matched_tables,
            "tablesDetected": tables_found,
            "rubricRowsSkipped": rubric_skipped,
            "duplicatesSkipped": session.duplicates_skipped,
            "backMatterStopPage": session.stopped_at,
            "appendixStartPage": session.appendix_start,
            "appendix": appendix,
            "warnings": warnings,
            "records": cleaned,
        }
        return result
    finally:
        doc.close()
        # session is local and discarded (stateless per job)
