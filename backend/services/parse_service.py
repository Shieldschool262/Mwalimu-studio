"""Parser-as-a-service adapter.

The parser engine (services/parser_engine.py) is COPIED VERBATIM and is never edited.
Everything the app needs (grade, subject, lesson counts, archetype labels, chunk shape)
is derived here from what the engine already returns.
"""
from __future__ import annotations

import json
import re
import traceback
from pathlib import Path
from typing import Any

from db import (
    PARSER_VERSION,
    REVIEW_STATES,
    connect,
    list_chunks,
    new_id,
    refresh_document_status,
    row_to_document,
    store_upload,
    upload_path,
)
from services.parser_engine import load_archetypes, parse_pdf
from services.appendix_parser import join_appendix
from services.repair import recover_experiences

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ARCHETYPES = load_archetypes(BACKEND_ROOT)

ARCHETYPE_LABEL = {
    "A-Language": "A · Language",
    "B-Religious": "B · Religious",
    "C-ScienceMaths": "C · Science / Maths",
    "D-Practical": "D · Practical",
}

# The engine hardcodes GRADE = "Grade 1"; the app reads it, never overrides it.
try:
    from services.parser_engine import GRADE as ENGINE_GRADE  # noqa: N811
except Exception:  # pragma: no cover
    ENGINE_GRADE = "Grade 1"

DEFAULT_SUBJECT = "Unknown Subject"


# Suffixes the KICD filenames use for the learning-area name itself.
SUBJECT_NOISE = re.compile(
    r"\b(?:Curriculum\s+Designs?|Activities|Language\s+Activities|Studies|Study)\b",
    flags=re.I,
)


def subject_from_filename(file_name: str) -> str:
    base = re.sub(r"\.pdf$", "", file_name, flags=re.I)
    s = base.replace("-", " ").replace("_", " ")
    s = re.sub(r"\bGrade\s*\d+\b", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" -:")
    # Drop the trailing boilerplate but keep the learning-area words that matter.
    s = re.sub(r"\bCurriculum\s+Designs?\b", "", s, flags=re.I)
    s = re.sub(r"\bLanguage\s+Activities\b", "", s, flags=re.I)
    s = re.sub(r"\bActivities\b", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" -:")
    return s or DEFAULT_SUBJECT


def grade_from_filename(file_name: str, fallback: str = ENGINE_GRADE) -> str:
    m = re.search(r"Grade[\s-]*(\d+)", file_name, flags=re.I)
    return f"Grade {m.group(1)}" if m else fallback


STRUCTURED_KEYS = (
    "specific_learning_outcomes",
    "suggested_learning_experiences",
    "key_inquiry_questions",
    "core_competencies",
    "values",
    "pcis",
    "link_to_other_learning_areas",
    "link_to_value",
)



def _sync_vetting(document_id: str, conn: Any = None) -> None:
    """Keep source_chunks.vetting_status in step with review state and field content.

    The vetting rule itself lives ONLY in services/library_service.py; this just calls it
    after every mutation so the stored column is never stale.
    """
    from services.library_service import recompute_document_vetting

    recompute_document_vetting(document_id, conn)

def structured_fields_from_record(rec: dict[str, Any]) -> dict[str, Any]:
    """Deep-copy so nothing in the DB aliases the engine's in-memory record."""
    out: dict[str, Any] = {}
    for k in STRUCTURED_KEYS:
        v = rec.get(k)
        if isinstance(v, list):
            out[k] = [str(x) for x in v]
        elif v is None:
            out[k] = [] if k in STRUCTURED_KEYS[:3] else None
        else:
            out[k] = str(v)
    return out


def parse_and_store(pdf_bytes: bytes, file_name: str) -> dict[str, Any]:
    """Run the verbatim engine for ONE document and persist it. Stateless per job."""
    document_id = new_id()
    jobs_dir = BACKEND_ROOT / "jobs"
    jobs_dir.mkdir(exist_ok=True)

    # The engine logs to stdout; keep a per-document transcript for debugging/marking.
    result = parse_pdf(pdf_bytes, BACKEND_ROOT, override_archetype=None, job_id=document_id)

    # Keep the original forever: /api/library/{id}/reparse reads it back.
    store_upload(document_id, pdf_bytes)

    grade = grade_from_filename(file_name)
    subject = subject_from_filename(file_name)
    archetype = result.get("archetype")
    records = result.get("records") or []

    # APP-SIDE strand repair: never edit the engine, never borrow another document.
    recovered = recover_strand_names(pdf_bytes, records)
    repaired = 0
    for rec in records:
        if (rec.get("strand") or "").strip():
            continue
        code = rec.get("strand_code") or ""
        major = code.split(".")[0]
        name = recovered.get(code) or recovered.get(f"{major}.0")
        if name:
            rec["strand"] = name
            rec["strand_code"] = f"{major}.0"
            rec["confidence"] = max(float(rec.get("confidence") or 0.0), 0.75)
            flags = [f for f in (rec.get("flags") or []) if "Parent not found" not in f]
            rec["flags"] = flags + ["Strand name recovered from page heading - verify"]
            repaired += 1

    # APP-SIDE gap recovery for a known engine column-span miss.
    experiences_recovered = recover_experiences(pdf_bytes, records)

    # PHASE 3.5: join Appendix resources/assessment onto each sub-strand record. Pure lookup of
    # parsed appendix cells - never invented, and never part of vetting.
    appendix = result.get("appendix") or {}
    appendix_matched = 0
    for rec in records:
        join_appendix(rec, appendix)
        if rec.get("appendix_resources") or rec.get("appendix_assessment"):
            appendix_matched += 1

    meta = {
        "archetypeName": result.get("archetypeName"),
        "archetypeLabel": ARCHETYPE_LABEL.get(archetype or "", archetype or "Unknown"),
        "experiencesRecovered": experiences_recovered,
        "detectionReason": result.get("detectionReason"),
        "mappingSource": result.get("mappingSource"),
        "tablesFound": result.get("tablesFound"),
        "tablesDetected": result.get("tablesDetected"),
        "rubricRowsSkipped": result.get("rubricRowsSkipped"),
        "duplicatesSkipped": result.get("duplicatesSkipped"),
        "backMatterStopPage": result.get("backMatterStopPage"),
        "appendixStartPage": result.get("appendixStartPage"),
        "appendixRows": len(appendix.get("rows") or []),
        "appendixMatched": appendix_matched,
        "warnings": result.get("warnings") or [],
        "strandsRecovered": repaired,
        "engineGrade": ENGINE_GRADE,
    }

    with connect() as conn:
        conn.execute(
            """INSERT INTO source_documents
               (id, file_name, grade, subject, archetype, archetype_confidence,
                archetype_reason, parser_version, status, parse_meta)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                document_id,
                file_name,
                grade,
                subject,
                archetype,
                float(result.get("confidence") or 0.0),
                result.get("detectionReason"),
                PARSER_VERSION,
                "Parsed",
                json.dumps(meta, ensure_ascii=False),
            ),
        )
        for ord_, rec in enumerate(records):
            structured = structured_fields_from_record(rec)
            conn.execute(
                """INSERT INTO source_chunks
                   (id, document_id, ord, page_number, theme, theme_code, strand, strand_code,
                    sub_strand, sub_strand_code, lessons, structured_fields, original_fields,
                    confidence, flags, review_state,
                    appendix_resources, appendix_assessment, appendix_source, appendix_level)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    new_id(),
                    document_id,
                    ord_,
                    rec.get("page_start"),
                    rec.get("theme"),
                    rec.get("theme_code"),
                    rec.get("strand"),
                    rec.get("strand_code"),
                    rec.get("sub_strand") or "",
                    rec.get("sub_strand_code"),
                    rec.get("lessons"),
                    json.dumps(structured, ensure_ascii=False),
                    json.dumps(structured, ensure_ascii=False),  # original snapshot for Undo
                    float(rec.get("confidence") or 0.0),
                    json.dumps(rec.get("flags") or [], ensure_ascii=False),
                    "Parsed",
                    rec.get("appendix_resources"),
                    rec.get("appendix_assessment"),
                    rec.get("appendix_source"),
                    rec.get("appendix_level"),
                ),
            )
        refresh_document_status(conn, document_id)
        _sync_vetting(document_id, conn)

    return get_job(document_id)


def get_job(document_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM source_documents WHERE id = ?", (document_id,)).fetchone()
        if row is None:
            return None
        chunks = list_chunks(conn, document_id)
        doc = row_to_document(row, chunks)
    return build_job_payload(doc)


def _chunk_sort_key(c: dict[str, Any]) -> tuple:
    code = c.get("subStrandCode") or ""
    parts = [int(p) if p.isdigit() else 0 for p in code.split(".")]
    return (parts, c.get("ord") or 0)


def strand_key(code: str | None, name: str | None) -> str:
    """Normalised grouping key.

    The engine emits the same strand with cosmetic variants across pages
    (`Pre - Technical`, `Pre-Technical`, `Pre\u2011Technical`) and sometimes only the code.
    The app groups on code + normalised name so a teacher sees ONE strand header.
    """
    norm = (name or "").lower()
    norm = norm.replace("\u2010", "-").replace("\u2011", "-").replace("\ufffd", "-")
    norm = re.sub(r"[^a-z0-9]+", "", norm)
    return f"{(code or '').strip()}|{norm}"


# ---------------------------------------------------------------------------
# Strand repair (APP-SIDE ONLY - services/parser_engine.py stays verbatim)
# ---------------------------------------------------------------------------
# Some designs (e.g. Kiswahili) carry no "STRAND" keyword and use all-caps headings
# ("1.0 DARASANI"). The engine leaves strand=None there, so every chunk comes back
# flagged "Parent not found". The app recovers the heading from the chunk's OWN page
# and marks the repair, so a teacher can verify it. Nothing is ever borrowed from
# another document.
_HEADING_RE = re.compile(r"^[ \t]*(\d+\.0)[ \t]+([A-Z][A-Z0-9'&(),\-/ ]{2,60})[ \t]*$", re.M)
_TABLE_HEADER_WORDS = {
    "MADA", "MADA NDONGO", "MATOKEO", "MATOKEO MAALUM", "SHUGHULI", "SWALI",
    "STRAND", "SUB STRAND", "SUBSTRAND", "SPECIFIC", "SUGGESTED", "KEY INQUIRY",
    "THEME", "CONTENTS", "TABLE OF CONTENTS",
}


def _page_texts(pdf_bytes: bytes, page_numbers: set[int]) -> dict[int, str]:
    import fitz  # already a hard dependency of the engine

    out: dict[int, str] = {}
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        for n in sorted(page_numbers):
            if 1 <= n <= doc.page_count:
                out[n] = doc[n - 1].get_text("text") or ""
    finally:
        doc.close()
    return out


def recover_strand_names(pdf_bytes: bytes, records: list[dict[str, Any]]) -> dict[str, str]:
    """Map 'X.0' -> strand name using only this document's own page headings."""
    bases = {int(r.get("page_start") or 0) for r in records} - {0}
    pages: set[int] = set()
    for p in bases:
        pages.update({p - 1, p, p + 1})
    texts = _page_texts(pdf_bytes, pages)

    found: dict[str, str] = {}
    for rec in records:
        major = (rec.get("strand_code") or "").split(".")[0]
        if not major:
            continue
        code = f"{major}.0"
        if code in found:
            continue
        base = int(rec.get("page_start") or 0)
        best = ""
        for n in (base, base - 1, base + 1):
            txt = texts.get(n)
            if not txt:
                continue
            for m in _HEADING_RE.finditer(txt):
                if m.group(1) != code:
                    continue
                cand = m.group(2).strip(" .")
                if cand.upper() in _TABLE_HEADER_WORDS:
                    continue
                cand = re.sub(r"\s+", " ", re.sub(r"\.{3,}.*$", "", cand)).strip()
                if len(cand) >= 3:
                    best = cand
            if best:
                break
        if best:
            found[code] = best
    return found


def build_tree(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group chunks by strand. Strand order follows curriculum numbering."""
    groups: dict[str, dict[str, Any]] = {}
    for c in chunks:
        key = strand_key(c.get("strandCode"), c.get("strand"))
        g = groups.get(key)
        if g is None:
            g = {
                "strandCode": c.get("strandCode"),
                "strand": (c.get("strand") or "Unassigned strand").strip(),
                "strandUnresolved": not bool((c.get("strand") or "").strip()),
                "theme": c.get("theme"),
                "themeCode": c.get("themeCode"),
                "chunks": [],
            }
            groups[key] = g
        elif len((c.get("strand") or "").strip()) > len(g["strand"]):
            g["strand"] = (c.get("strand") or "").strip()
        g["chunks"].append(c)

    def strand_order(g: dict[str, Any]) -> tuple:
        code = g.get("strandCode") or ""
        nums = [int(p) if p.isdigit() else 0 for p in re.findall(r"\d+", code)]
        return (nums or [999], g.get("strand") or "")

    tree = []
    for g in sorted(groups.values(), key=strand_order):
        g["chunks"].sort(key=_chunk_sort_key)
        g["chunkCount"] = len(g["chunks"])
        tree.append(g)
    return tree


def build_job_payload(doc: dict[str, Any]) -> dict[str, Any]:
    chunks = [enrich_chunk(c) for c in (doc.get("chunks") or [])]
    approved = sum(1 for c in chunks if c["reviewState"] == "Approved")
    corrected = sum(1 for c in chunks if c["reviewState"] == "TeacherCorrected")
    pending = sum(1 for c in chunks if c["reviewState"] == "Parsed")
    missing = sum(1 for c in chunks if c["missingFields"])
    needs_review = sum(1 for c in chunks if c["needsReview"])
    auto_ready = sum(
        1 for c in chunks if c["confidence"] >= AUTO_APPROVE_MIN_CONFIDENCE and not c["missingFields"]
    )
    ready_to_save = len(chunks) > 0 and needs_review == 0
    return {
        **doc,
        "chunks": chunks,
        "chunkCount": len(chunks),
        "reviewSummary": {
            "total": len(chunks),
            "approved": approved,
            "corrected": corrected,
            "pending": pending,
            "missing": missing,
            "needsReview": needs_review,
            "autoApprovable": auto_ready,
            "readyToApprove": ready_to_save,
            "readyToSave": ready_to_save,
        },
        "tree": build_tree(chunks),
    }


# ---------------------------------------------------------------------------
# Review helpers
# ---------------------------------------------------------------------------

AUTO_APPROVE_MIN_CONFIDENCE = 0.9

# Fields a teacher can edit inline. `field` accepts either the structured JSON key
# or a friendly alias the UI uses.
FIELD_ALIASES = {
    "outcomes": "specific_learning_outcomes",
    "specificLearningOutcomes": "specific_learning_outcomes",
    "specific_learning_outcomes": "specific_learning_outcomes",
    "experiences": "suggested_learning_experiences",
    "suggestedLearningExperiences": "suggested_learning_experiences",
    "suggested_learning_experiences": "suggested_learning_experiences",
    "kiqs": "key_inquiry_questions",
    "keyInquiryQuestions": "key_inquiry_questions",
    "key_inquiry_questions": "key_inquiry_questions",
    "core_competencies": "core_competencies",
    "coreCompetencies": "core_competencies",
    "values": "values",
    "pcis": "pcis",
    "link_to_other_learning_areas": "link_to_other_learning_areas",
    "linkToOtherLearningAreas": "link_to_other_learning_areas",
    "link_to_value": "link_to_value",
    "linkToValue": "link_to_value",
    "subStrand": "subStrand",
    "sub_strand": "subStrand",
    "lessons": "lessons",
}

LIST_FIELDS = ("specific_learning_outcomes", "suggested_learning_experiences", "key_inquiry_questions")

# A chunk is "ready" when nothing required is empty.
REQUIRED_FIELDS = {
    "specific_learning_outcomes": "Outcomes",
    "suggested_learning_experiences": "Experiences",
    "key_inquiry_questions": "KIQs",
}


def missing_fields(chunk: dict[str, Any]) -> list[str]:
    """Human labels for required fields that are empty. Drives the red 'Missing:' pill."""
    sf = chunk.get("structuredFields") or {}
    out = []
    for key, label in REQUIRED_FIELDS.items():
        val = sf.get(key)
        if isinstance(val, list):
            if not any(str(x).strip() for x in val):
                out.append(label)
        elif not str(val or "").strip():
            out.append(label)
    return out


def is_ready(chunk: dict[str, Any]) -> bool:
    """Reviewed AND nothing missing."""
    return chunk.get("reviewState") in ("Approved", "TeacherCorrected") and not missing_fields(chunk)


def enrich_chunk(chunk: dict[str, Any]) -> dict[str, Any]:
    chunk["missingFields"] = missing_fields(chunk)
    chunk["ready"] = is_ready(chunk)
    chunk["needsReview"] = not is_ready(chunk)
    return chunk


def _set_review(conn: Any, chunk_ids: list[str], document_id: str, state: str) -> int:
    if not chunk_ids:
        return 0
    marks = ",".join("?" for _ in chunk_ids)
    cur = conn.execute(
        f"UPDATE source_chunks SET review_state = ? WHERE document_id = ? AND id IN ({marks})",
        (state, document_id, *chunk_ids),
    )
    return cur.rowcount or 0


def approve_all(
    document_id: str, min_confidence: float = AUTO_APPROVE_MIN_CONFIDENCE
) -> tuple[dict[str, Any] | None, int, int]:
    """Approve every chunk whose engine confidence >= min_confidence.

    Low-confidence chunks stay 'Parsed' so they keep showing under 'Needs Review Only'.
    """
    with connect() as conn:
        row = conn.execute("SELECT id FROM source_documents WHERE id = ?", (document_id,)).fetchone()
        if row is None:
            return None, 0, 0
        rows = conn.execute(
            "SELECT id, confidence, structured_fields FROM source_chunks WHERE document_id = ?",
            (document_id,),
        ).fetchall()
        eligible: list[str] = []
        kept = 0
        for r in rows:
            sf = json.loads(r["structured_fields"] or "{}")
            empty = any(
                not (sf.get(k) and any(str(x).strip() for x in sf[k])) for k in LIST_FIELDS
            )
            if float(r["confidence"] or 0) >= min_confidence and not empty:
                eligible.append(r["id"])
            else:
                kept += 1
        _set_review(conn, eligible, document_id, "Approved")
        refresh_document_status(conn, document_id)
        _sync_vetting(document_id, conn)
    return get_job(document_id), len(eligible), kept


def approve_strand(
    document_id: str, strand_code: str | None, strand: str | None
) -> tuple[dict[str, Any] | None, int]:
    """Approve every chunk under one Strand header."""
    with connect() as conn:
        row = conn.execute("SELECT id FROM source_documents WHERE id = ?", (document_id,)).fetchone()
        if row is None:
            return None, 0
        rows = conn.execute(
            "SELECT id, strand_code, strand FROM source_chunks WHERE document_id = ?",
            (document_id,),
        ).fetchall()
        target_key = strand_key(strand_code, strand)
        ids = [r["id"] for r in rows if strand_key(r["strand_code"], r["strand"]) == target_key]
        n = _set_review(conn, ids, document_id, "Approved")
        refresh_document_status(conn, document_id)
        _sync_vetting(document_id, conn)
    return get_job(document_id), n


def correct_chunk(
    document_id: str,
    chunk_id: str,
    patch: dict[str, Any],
) -> dict[str, Any] | None:
    """Teacher inline correction.

    Two shapes are accepted:
      {field, newValue}          -> single-field edit, snapshots original for Undo
      {structuredFields: {...}}  -> whole-record edit (legacy form)

    Any edit sets review_state=TeacherCorrected and confidence=1.0 unless the caller
    explicitly asks for something else (e.g. {"reviewState": "Approved"}).
    """
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM source_chunks WHERE id = ? AND document_id = ?",
            (chunk_id, document_id),
        ).fetchone()
        if row is None:
            return None

        updates: dict[str, Any] = {}
        structured = json.loads(row["structured_fields"] or "{}")
        original = json.loads(row["original_fields"] or "{}")
        if not original:
            original = json.loads(row["structured_fields"] or "{}")

        def snapshot(key: str) -> None:
            if key not in original:
                original[key] = structured.get(key)

        def apply_field(field: str, value: Any) -> bool:
            if field == "subStrand":
                updates["sub_strand"] = str(value).strip()
                return True
            if field == "lessons":
                raw = str(value).strip()
                updates["lessons"] = int(raw) if raw.isdigit() else None
                return True
            if field in STRUCTURED_KEYS:
                snapshot(field)
                if field in LIST_FIELDS:
                    if isinstance(value, list):
                        items = [str(x).strip() for x in value]
                    else:
                        items = [ln.strip() for ln in str(value).splitlines()]
                    structured[field] = [x for x in items if x]
                else:
                    structured[field] = None if value is None else str(value).strip()
                updates["structured_fields"] = json.dumps(structured, ensure_ascii=False)
                return True
            return False

        touched = False

        # --- single field shape -------------------------------------------------
        field = patch.get("field")
        if isinstance(field, str) and field in FIELD_ALIASES:
            if apply_field(FIELD_ALIASES[field], patch.get("newValue")):
                touched = True

        # --- explicit undo ------------------------------------------------------
        undo_field = patch.get("undoField")
        if isinstance(undo_field, str) and undo_field in FIELD_ALIASES:
            key = FIELD_ALIASES[undo_field]
            if key in original:
                apply_field(key, original[key])
                touched = False

        # --- whole-record shape (legacy / bulk) ---------------------------------
        fields = patch.get("structuredFields")
        if isinstance(fields, dict):
            for k, v in fields.items():
                if k in STRUCTURED_KEYS and apply_field(k, v):
                    touched = True

        simple = {
            "strand": "strand",
            "strandCode": "strand_code",
            "subStrandCode": "sub_strand_code",
        }
        for api_key, col in simple.items():
            if api_key in patch and patch[api_key] is not None:
                updates[col] = str(patch[api_key]).strip()

        if "lessons" in patch and "lessons" not in updates:
            apply_field("lessons", patch["lessons"])

        state = patch.get("reviewState")
        if state in REVIEW_STATES:
            updates["review_state"] = state
        elif touched:
            updates["review_state"] = "TeacherCorrected"
            updates["confidence"] = 1.0

        if "confidence" not in updates and "review_state" in updates:
            # A teacher correction is by definition high confidence.
            if updates["review_state"] == "TeacherCorrected":
                updates["confidence"] = 1.0

        updates["original_fields"] = json.dumps(original, ensure_ascii=False)

        sets = ", ".join(f"{c} = ?" for c in updates)
        conn.execute(
            f"UPDATE source_chunks SET {sets} WHERE id = ? AND document_id = ?",
            (*updates.values(), chunk_id, document_id),
        )
        refresh_document_status(conn, document_id)
        _sync_vetting(document_id, conn)
    return get_job(document_id)


def save_to_library(document_id: str, save_with_gaps: bool) -> tuple[dict[str, Any] | None, list[str]]:
    """POST /api/library/save - flip the document to Approved and link it in the library.

    Blocked unless every chunk is Approved/TeacherCorrected with nothing missing,
    or the teacher ticked 'Save with gaps - I will fix later'.
    """
    with connect() as conn:
        row = conn.execute("SELECT * FROM source_documents WHERE id = ?", (document_id,)).fetchone()
        if row is None:
            return None, ["Document not found"]

        rows = conn.execute(
            "SELECT id, sub_strand, sub_strand_code, review_state, structured_fields "
            "FROM source_chunks WHERE document_id = ? ORDER BY ord",
            (document_id,),
        ).fetchall()
        if not rows:
            return None, ["This document has no parsed sub-strands to save."]

        blocking: list[str] = []
        for r in rows:
            sf = json.loads(r["structured_fields"] or "{}")
            empty = [
                REQUIRED_FIELDS[k]
                for k in LIST_FIELDS
                if not (sf.get(k) and any(str(x).strip() for x in sf[k]))
            ]
            reviewed = r["review_state"] in ("Approved", "TeacherCorrected")
            if not reviewed or empty:
                label = r["sub_strand_code"] or r["sub_strand"]
                blocking.append(f"{label} ({'unreviewed' if not reviewed else 'missing ' + '/'.join(empty)})")

        if blocking and not save_with_gaps:
            preview = ", ".join(blocking[:4])
            more = f" and {len(blocking) - 4} more" if len(blocking) > 4 else ""
            return None, [
                f"{len(blocking)} sub-strand(s) still need review: {preview}{more}. "
                "Finish them or tick 'Save with gaps - I will fix later'."
            ]

        conn.execute(
            "UPDATE source_chunks SET review_state = 'Approved' WHERE document_id = ?",
            (document_id,),
        )
        meta = json.loads(row["parse_meta"] or "{}")
        meta["savedWithGaps"] = bool(blocking)
        conn.execute(
            "UPDATE source_documents SET status = 'Approved', parse_meta = ? WHERE id = ?",
            (json.dumps(meta, ensure_ascii=False), document_id),
        )
        _sync_vetting(document_id, conn)
    return get_job(document_id), []


def reparse_document(document_id: str) -> tuple[dict[str, Any] | None, list[str]]:
    """Re-run the SAME verbatim engine on the stored original PDF, in place.

    Chunks are replaced atomically so nothing is duplicated. Review state resets
    because the parse itself changed.
    """
    path = upload_path(document_id)
    if not path.exists():
        return None, ["Original PDF is missing from backend/uploads - cannot re-parse."]

    with connect() as conn:
        row = conn.execute("SELECT * FROM source_documents WHERE id = ?", (document_id,)).fetchone()
        if row is None:
            return None, ["Document not found"]
        grade = row["grade"]
        subject = row["subject"]

    pdf_bytes = path.read_bytes()
    try:
        result = parse_pdf(pdf_bytes, BACKEND_ROOT, override_archetype=None, job_id=document_id)
    except Exception as exc:  # pragma: no cover - engine failure
        traceback.print_exc()
        return None, [f"Re-parse failed: {exc}"]

    records = result.get("records") or []
    recovered = recover_strand_names(pdf_bytes, records)
    for rec in records:
        if (rec.get("strand") or "").strip():
            continue
        code = rec.get("strand_code") or ""
        major = code.split(".")[0]
        name = recovered.get(code) or recovered.get(f"{major}.0")
        if name:
            rec["strand"] = name
            rec["strand_code"] = f"{major}.0"
            rec["confidence"] = max(float(rec.get("confidence") or 0.0), 0.75)
            flags = [f for f in (rec.get("flags") or []) if "Parent not found" not in f]
            rec["flags"] = flags + ["Strand name recovered from page heading - verify"]

    experiences_recovered = recover_experiences(pdf_bytes, records)

    # PHASE 3.5: appendix join on re-parse too, so Resources/Assessment stay autofilled.
    appendix = result.get("appendix") or {}
    appendix_matched = 0
    for rec in records:
        join_appendix(rec, appendix)
        if rec.get("appendix_resources") or rec.get("appendix_assessment"):
            appendix_matched += 1

    meta = {
        "archetypeName": result.get("archetypeName"),
        "experiencesRecovered": experiences_recovered,
        "archetypeLabel": ARCHETYPE_LABEL.get(
            result.get("archetype") or "", result.get("archetype") or "Unknown"
        ),
        "detectionReason": result.get("detectionReason"),
        "mappingSource": result.get("mappingSource"),
        "tablesFound": result.get("tablesFound"),
        "tablesDetected": result.get("tablesDetected"),
        "rubricRowsSkipped": result.get("rubricRowsSkipped"),
        "duplicatesSkipped": result.get("duplicatesSkipped"),
        "backMatterStopPage": result.get("backMatterStopPage"),
        "appendixStartPage": result.get("appendixStartPage"),
        "appendixRows": len(appendix.get("rows") or []),
        "appendixMatched": appendix_matched,
        "warnings": result.get("warnings") or [],
        "strandsRecovered": len(recovered),
        "engineGrade": ENGINE_GRADE,
        "reparsed": True,
    }

    with connect() as conn:
        conn.execute("DELETE FROM source_chunks WHERE document_id = ?", (document_id,))
        for ord_, rec in enumerate(records):
            structured = structured_fields_from_record(rec)
            conn.execute(
                """INSERT INTO source_chunks
                   (id, document_id, ord, page_number, theme, theme_code, strand, strand_code,
                    sub_strand, sub_strand_code, lessons, structured_fields, original_fields,
                    confidence, flags, review_state,
                    appendix_resources, appendix_assessment, appendix_source, appendix_level)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    new_id(),
                    document_id,
                    ord_,
                    rec.get("page_start"),
                    rec.get("theme"),
                    rec.get("theme_code"),
                    rec.get("strand"),
                    rec.get("strand_code"),
                    rec.get("sub_strand") or "",
                    rec.get("sub_strand_code"),
                    rec.get("lessons"),
                    json.dumps(structured, ensure_ascii=False),
                    json.dumps(structured, ensure_ascii=False),
                    float(rec.get("confidence") or 0.0),
                    json.dumps(rec.get("flags") or [], ensure_ascii=False),
                    "Parsed",
                    rec.get("appendix_resources"),
                    rec.get("appendix_assessment"),
                    rec.get("appendix_source"),
                    rec.get("appendix_level"),
                ),
            )
        conn.execute(
            """UPDATE source_documents
               SET archetype = ?, archetype_confidence = ?, archetype_reason = ?,
                   parser_version = ?, status = 'Parsed', parse_meta = ?, grade = ?, subject = ?
               WHERE id = ?""",
            (
                result.get("archetype"),
                float(result.get("confidence") or 0.0),
                result.get("detectionReason"),
                PARSER_VERSION,
                json.dumps(meta, ensure_ascii=False),
                grade,
                subject,
                document_id,
            ),
        )
        _sync_vetting(document_id, conn)
    return get_job(document_id), []


def safe_parse(pdf_bytes: bytes, file_name: str) -> dict[str, Any]:
    try:
        return parse_and_store(pdf_bytes, file_name)
    except Exception as exc:  # engine failure must not break the server process
        traceback.print_exc()
        doc_id = new_id()
        with connect() as conn:
            conn.execute(
                """INSERT INTO source_documents
                   (id, file_name, grade, subject, archetype, archetype_confidence,
                    archetype_reason, parser_version, status, parse_meta)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    doc_id,
                    file_name,
                    grade_from_filename(file_name),
                    subject_from_filename(file_name),
                    None,
                    0.0,
                    f"Parse failed: {exc}",
                    PARSER_VERSION,
                    "Failed",
                    json.dumps({"warnings": [f"Parse failed: {exc}"]}),
                ),
            )
        return {"id": doc_id, "status": "Failed", "error": str(exc), "chunks": []}
