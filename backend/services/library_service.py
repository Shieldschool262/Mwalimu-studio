"""Library service - the teacher's private, source-first library.

Source-first means: the SourceDocument (the original PDF) is the unit a teacher sees and
acts on. Chunks are always reachable back to their document and page, and search hits
always name the document they came from so nothing is ever shown out of context.
"""
from __future__ import annotations

import json
import re
from typing import Any

from auth_service import current_owner_id
from db import connect, delete_document, list_chunks, row_to_document, upload_path
from services.parse_service import (
    ARCHETYPE_LABEL,
    build_job_payload,
    build_tree,
    enrich_chunk,
    reparse_document,
    save_to_library,
)

APPROVED = "Approved"
NEEDS_REVIEW = "NeedsReview"
OPEN_STATUSES = ("NeedsReview", "Parsed")

SNIPPET_LEN = 190


# ---------------------------------------------------------------------------
# VETTING GUARD (the only place vetting is computed)
# ---------------------------------------------------------------------------
# A chunk is vetted ONLY when it has the three core curriculum facts and a teacher has
# signed it off. Competencies, values, PCIs, link_to_other_learning_areas and
# link_to_value are NOT curriculum core facts for planning purposes: they are frequently
# absent from a design, and their absence must never block generation.
#
# DO NOT add them to this dict, and do not check them anywhere else.
CORE_VETTING_FIELDS = {
    "specific_learning_outcomes": "Outcomes",
    "suggested_learning_experiences": "Experiences",
    "key_inquiry_questions": "Key Inquiry Questions",
}

VETTED = "Vetted"
VETTING_PENDING = "Pending"
VETTING_REJECTED = "Rejected"

REVIEW_SIGNED_OFF = ("TeacherCorrected", "Approved")


def _field_has_value(sf: dict[str, Any], key: str) -> bool:
    val = sf.get(key)
    if isinstance(val, list):
        return any(str(x).strip() for x in val)
    return bool(str(val or "").strip())


def compute_vetting_status(structured: dict[str, Any], review_state: str) -> str:
    """Vetted only if the 3 core fields are present AND a teacher signed off.

    Competencies/values/PCIs/links are deliberately ignored.
    """
    if review_state not in REVIEW_SIGNED_OFF:
        return VETTING_PENDING
    for key in CORE_VETTING_FIELDS:
        if not _field_has_value(structured, key):
            return VETTING_PENDING
    return VETTED


def vetting_gaps(structured: dict[str, Any], review_state: str) -> list[dict[str, str]]:
    """Which core fields block vetting, with the short label the UI shows."""
    gaps: list[dict[str, str]] = []
    if review_state not in REVIEW_SIGNED_OFF:
        gaps.append({"field": "review", "label": "review"})
    for key, label in CORE_VETTING_FIELDS.items():
        if not _field_has_value(structured, key):
            gaps.append({"field": key, "label": label})
    return gaps


def recompute_document_vetting(document_id: str, conn: Any = None) -> dict[str, Any]:
    """Re-derive vetting_status for every chunk of a document and persist it.

    Called after any review/approve/save/edit so the stored column is never stale.
    Pass an open connection when the caller already holds a write transaction - opening a
    second one would deadlock SQLite.
    """
    if conn is None:
        with connect() as own:
            return recompute_document_vetting(document_id, own)

    rows = conn.execute(
        "SELECT id, structured_fields, review_state FROM source_chunks WHERE document_id = ?",
        (document_id,),
    ).fetchall()
    updated: dict[str, Any] = {}
    for r in rows:
        sf = json.loads(r["structured_fields"] or "{}")
        status = compute_vetting_status(sf, r["review_state"])
        updated[r["id"]] = status
        conn.execute(
            "UPDATE source_chunks SET vetting_status = ? WHERE id = ?",
            (status, r["id"]),
        )
    return updated


def recompute_chunk_vetting(chunk_id: str) -> str:
    with connect() as conn:
        row = conn.execute(
            "SELECT structured_fields, review_state FROM source_chunks WHERE id = ?", (chunk_id,)
        ).fetchone()
        if row is None:
            return VETTING_PENDING
        status = compute_vetting_status(
            json.loads(row["structured_fields"] or "{}"), row["review_state"]
        )
        conn.execute("UPDATE source_chunks SET vetting_status = ? WHERE id = ?", (status, chunk_id))
    return status


def vetting_summary(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts for the card badge: 'Vetting: 8/9 Vetted - 1 needs KIQs'."""
    total = len(chunks)
    vetted = 0
    problems: list[dict[str, Any]] = []
    for c in chunks:
        status = c.get("vettingStatus") or VETTING_PENDING
        if status == VETTED:
            vetted += 1
        else:
            gaps = vetting_gaps(c.get("structuredFields") or {}, c.get("reviewState") or "Parsed")
            labels = [g["label"] for g in gaps if g["field"] != "review"]
            problems.append(
                {
                    "chunkId": c["id"],
                    "subStrandCode": c.get("subStrandCode"),
                    "subStrand": c.get("subStrand"),
                    "pageNumber": c.get("pageNumber"),
                    "needs": labels or ["review"],
                    "reviewState": c.get("reviewState"),
                }
            )
    return {
        "total": total,
        "vetted": vetted,
        "pending": total - vetted,
        "allVetted": total > 0 and vetted == total,
        "problems": problems,
    }


def _summary_from_chunks(chunks: list[dict[str, Any]]) -> dict[str, int]:
    """Counts must match what the teacher sees in the tree.

    Language designs (archetype A) use X.0 as a THEME and X.Y as the STRAND, so the tree
    has one header per X.Y. Count tree groups so the card never contradicts the tree.
    """
    strand_keys = {
        (
            c.get("strandCode") or "",
            (c.get("strand") or "").strip().lower(),
        )
        for c in chunks
        if c.get("strandCode") or c.get("strand")
    }
    themes = {
        (c.get("themeCode") or "").strip()
        for c in chunks
        if (c.get("themeCode") or "").strip()
    }
    return {
        "strandCount": len(strand_keys),
        "subStrandCount": len(chunks),
        "themeCount": len(themes),
    }


def document_card(row: Any, chunks: list[dict[str, Any]]) -> dict[str, Any]:
    doc = row_to_document(row)
    counts = _summary_from_chunks(chunks)
    meta = doc.get("parseMeta") or {}
    vet = vetting_summary(chunks)
    return {
        **doc,
        "archetypeLabel": meta.get("archetypeLabel")
        or ARCHETYPE_LABEL.get(doc.get("archetype") or "", doc.get("archetype") or "Unknown"),
        "strandCount": counts["strandCount"],
        "subStrandCount": counts["subStrandCount"],
        "themeCount": counts["themeCount"],
        "hasOriginalPdf": upload_path(doc["id"]).exists(),
        "savedWithGaps": bool(meta.get("savedWithGaps")),
        # --- vetting (Phase 3) ---
        "vettedCount": vet["vetted"],
        "vettingTotal": vet["total"],
        "allVetted": vet["allVetted"],
        "vettingProblems": vet["problems"],
        "vettingBadge": _vetting_badge(vet),
    }


def _vetting_badge(vet: dict[str, Any]) -> str:
    """'Vetting: 8/9 Vetted - 1 needs KIQs' exactly as the teacher reads it."""
    if vet["total"] == 0:
        return "Vetting: 0/0"
    if vet["allVetted"]:
        return f"Vetting: {vet['vetted']}/{vet['total']} Vetted"
    parts = []
    for p in vet["problems"]:
        code = p["subStrandCode"] or p["subStrand"]
        needs = " + ".join(p["needs"])
        parts.append(f"{needs} ({code})")
    return f"Vetting: {vet['vetted']}/{vet['total']} Vetted - {len(vet['problems'])} pending: " + ", ".join(parts)


def list_library(status: str | None = None) -> dict[str, Any]:
    """All documents, split into library (Approved) and in-progress (NeedsReview)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM source_documents WHERE owner_id = ? "
            "ORDER BY datetime(created_at) DESC, created_at DESC",
            (current_owner_id(),),
        ).fetchall()
        approved: list[dict[str, Any]] = []
        needs_review: list[dict[str, Any]] = []
        for row in rows:
            chunks = list_chunks(conn, row["id"])
            card = document_card(row, chunks)
            if card["status"] == APPROVED:
                approved.append(card)
            elif card["status"] in OPEN_STATUSES:
                needs_review.append(card)

    if status == APPROVED:
        approved_only, needs_only = approved, []
    elif status in OPEN_STATUSES:
        approved_only, needs_only = [], needs_review
    else:
        approved_only, needs_only = approved, needs_review

    grades = sorted(
        {d["grade"] for d in approved + needs_review if d.get("grade")},
        key=lambda g: int(re.sub(r"\D", "", g) or 0),
    )
    subjects = sorted({d["subject"] for d in approved + needs_review if d.get("subject")})

    # STUDIO LIBRARY RULE: a document appears here ONLY when every one of its chunks is
    # vetted. One pending chunk keeps the whole document in My Materials / Still to review.
    #
    # Bucketing is driven by VETTING, not by the document status column: a teacher can sign
    # off every chunk without pressing "Save", and that fully-vetted document must still be
    # usable for planning. "Save with gaps" documents are explicitly NOT vetted, so they stay
    # out of the Studio Library either way.
    studio_library = [d for d in approved + needs_review if d.get("allVetted")]
    my_materials = [d for d in approved if not d.get("allVetted")]

    if status == APPROVED:
        all_docs = approved
    elif status in OPEN_STATUSES:
        all_docs = needs_review
    else:
        all_docs = approved + needs_review

    return {
        "myMaterials": my_materials,
        "needsReview": needs_review,
        "studioLibrary": studio_library,
        # Flat list so the library can render one grid with a vetted filter.
        "documents": [{**d, "inStudioLibrary": d.get("allVetted", False)} for d in all_docs],
        "facets": {"grades": grades, "subjects": subjects},
        "counts": {
            "myMaterials": len(my_materials),
            "needsReview": len(needs_review),
            "studioLibrary": len(studio_library),
        },
    }


def get_library_document(document_id: str) -> dict[str, Any] | None:
    """One document with its chunks grouped by strand (same shape as the review view)."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM source_documents WHERE id = ?", (document_id,)).fetchone()
        if row is None:
            return None
        chunks = list_chunks(conn, document_id)
        doc = row_to_document(row, chunks)
    payload = build_job_payload(doc)
    card = document_card(row, payload["chunks"])
    return {
        **payload,
        **{k: card[k] for k in ("archetypeLabel", "strandCount", "subStrandCount", "themeCount", "savedWithGaps")},
    }


def _snippet(text: str, query: str) -> str:
    clean = re.sub(r"\s+", " ", text or "").strip()
    low = clean.lower()
    q = query.lower()
    pos = low.find(q)
    if pos < 0:
        return clean[:SNIPPET_LEN] + ("…" if len(clean) > SNIPPET_LEN else "")
    start = max(0, pos - 60)
    end = min(len(clean), pos + len(query) + 120)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(clean) else ""
    return f"{prefix}{clean[start:end]}{suffix}"


FIELD_LABELS = {
    "specific_learning_outcomes": "Outcome",
    "suggested_learning_experiences": "Experience",
    "key_inquiry_questions": "KIQ",
    "core_competencies": "Core competency",
    "values": "Value",
    "pcis": "PCI",
    "link_to_other_learning_areas": "Link",
    "link_to_value": "Link to value",
}


def search_library(
    q: str,
    grade: str | None = None,
    subject: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Search documents AND chunk content. Every hit keeps its document + page context.

    Matching is always scoped per document row, so a query can never surface a chunk
    from a different document than the one it matched in.
    """
    query = (q or "").strip()
    results: list[dict[str, Any]] = []
    doc_hits: list[dict[str, Any]] = []
    seen_docs: set[str] = set()

    with connect() as conn:
        docs = conn.execute(
            "SELECT * FROM source_documents ORDER BY datetime(created_at) DESC, created_at DESC"
        ).fetchall()

        for row in docs:
            if grade and row["grade"] != grade:
                continue
            if subject and row["subject"] != subject:
                continue
            if status == APPROVED and row["status"] != APPROVED:
                continue
            if status in OPEN_STATUSES and row["status"] not in OPEN_STATUSES:
                continue

            chunks = [enrich_chunk(c) for c in list_chunks(conn, row["id"])]
            card = document_card(row, chunks)

            if not query:
                continue

            ql = query.lower()
            # Document-level match (file name / subject / grade / strand names)
            doc_level = (
                ql in (row["file_name"] or "").lower()
                or ql in (row["subject"] or "").lower()
                or ql in (row["grade"] or "").lower()
                or any(
                    ql in (c.get("strand") or "").lower() or ql in (c.get("strandCode") or "").lower()
                    for c in chunks
                )
            )

            matched_chunks: list[dict[str, Any]] = []
            for c in chunks:
                reasons: list[str] = []
                sf = c.get("structuredFields") or {}

                if ql in (c.get("subStrand") or "").lower():
                    reasons.append(f"Sub-strand: {c['subStrand']}")
                if ql in (c.get("subStrandCode") or "").lower():
                    reasons.append(f"Code: {c['subStrandCode']}")
                if ql in (c.get("strand") or "").lower():
                    reasons.append(f"Strand: {c['strand']}")
                if ql in (c.get("theme") or "").lower():
                    reasons.append(f"Theme: {c['theme']}")

                snippet = ""
                # Structured fields: outcomes, experiences, KIQs, values, ...
                for key, label in FIELD_LABELS.items():
                    val = sf.get(key)
                    items = val if isinstance(val, list) else ([val] if val else [])
                    for item in items:
                        text = str(item or "")
                        if ql in text.lower():
                            reasons.append(f"{label}: {_snippet(text, query)}")
                            if not snippet:
                                snippet = _snippet(text, query)
                            break

                if reasons:
                    matched_chunks.append(
                        {
                            **c,
                            "matchedOn": reasons,
                            "snippet": snippet or reasons[0],
                        }
                    )

            if matched_chunks or doc_level:
                if row["id"] not in seen_docs:
                    seen_docs.add(row["id"])
                    doc_hits.append({**card, "matchCount": len(matched_chunks)})
                for mc in matched_chunks:
                    results.append(
                        {
                            "documentId": row["id"],
                            "fileName": row["file_name"],
                            "subject": row["subject"],
                            "grade": row["grade"],
                            "status": row["status"],
                            "archetype": row["archetype"],
                            "archetypeLabel": card["archetypeLabel"],
                            "pageNumber": mc.get("pageNumber"),
                            "subStrandCode": mc.get("subStrandCode"),
                            "subStrand": mc.get("subStrand"),
                            "strand": mc.get("strand"),
                            "strandCode": mc.get("strandCode"),
                            "chunkId": mc.get("id"),
                            "reviewState": mc.get("reviewState"),
                            "matchedOn": mc["matchedOn"],
                            "snippet": mc["snippet"],
                        }
                    )

    return {
        "query": query,
        "results": results,
        "documents": doc_hits,
        "total": len(results),
    }


def delete_library_document(document_id: str) -> bool:
    return delete_document(document_id)


def reparse_library_document(document_id: str) -> tuple[dict[str, Any] | None, list[str]]:
    payload, errors = reparse_document(document_id)
    if payload is None:
        return None, errors
    return get_library_document(document_id), errors


def save_document_to_library(document_id: str, save_with_gaps: bool) -> tuple[dict[str, Any] | None, list[str]]:
    job, errors = save_to_library(document_id, save_with_gaps)
    if job is None:
        return None, errors
    return get_library_document(document_id), errors
