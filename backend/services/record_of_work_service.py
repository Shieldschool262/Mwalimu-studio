"""Phase 6 - Record of Work (ROW): what WAS taught, not what was planned.

Non-negotiable rules (from the Phase 6 spec):

* Scheme = Plan (what SHOULD be taught); Lesson Plan = how I will teach it;
  Lesson Notes = what the learner will learn; ROW = what WAS taught, filled in
  by the teacher AFTER the lesson.
* Generation creates ONE row per scheme lesson, prefilled from the Scheme and
  the Lesson Plan. Work Done is a grey italic ``Planned: ...`` placeholder that
  the teacher MUST edit. Reflection is ALWAYS empty. Status is ALWAYS blank
  (never assume taught).
* Editing a ROW row NEVER mutates the Scheme, Lesson Plan, SourceChunk or
  Lesson Notes. This module only ever writes to ``record_of_work_*`` tables.
* AI is OFF by default, opt-in, and may ONLY suggest a Reflection from the
  teacher's own Work Done. It never writes Work Done, never sets Status and
  never marks a lesson as Taught.
* No web search is used anywhere in ROW.
* Versions are append-only snapshots of the whole ROW document. Restore writes
  a NEW version; old versions are never deleted.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from auth_service import current_owner_id
from db import connect, new_id
from services import ai_service
from services.library_service import VETTED
from services.lesson_plan_service import decomposition_for_section

# Blank is a valid (and the default) state: the teacher MUST choose a status.
STATUSES = (
    "",
    "Taught",
    "Not Taught - Carry Over",
    "Not Taught - Skipped",
    "Partially Taught",
)
GAP_STATUSES = (
    "Not Taught - Carry Over",
    "Not Taught - Skipped",
    "Partially Taught",
)
DOC_STATUSES = ("Draft", "Final")

SOURCE_AUTO = "auto-filled from Scheme"
SOURCE_EDITED = "teacher-edited"

ROW_AI_SYSTEM = (
    "You are a Kenyan CBE assistant helping a teacher write a retrospective "
    "reflection on a lesson they have already taught. Use ONLY the teacher's "
    "own words from Work Done. Never invent what happened. Never claim learners "
    "understood, enjoyed or completed anything unless the teacher said so. "
    "Write 2-3 plain sentences. Return JSON only."
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _json(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _today() -> str:
    return date.today().isoformat()


# ---------------------------------------------------------------------------
# Document + row helpers
# ---------------------------------------------------------------------------


def _plan_header(plan: Any) -> dict[str, str]:
    h = _json(plan["header"], {}) if "header" in plan.keys() else {}
    return {
        "school": str(h.get("institution") or ""),
        "institution": str(h.get("institution") or ""),
        "grade": str(h.get("grade") or plan["grade"] or ""),
        "learningArea": str(h.get("learningArea") or plan["subject"] or ""),
        "term": str(h.get("term") or plan["term"] or ""),
        "year": str(h.get("year") or ""),
        "teacher": str(h.get("teacherName") or ""),
        "tscNo": str(h.get("tscNo") or ""),
    }


def _load_doc(conn: Any, ident: str) -> Any:
    return conn.execute(
        "SELECT * FROM record_of_work_docs WHERE id = ? OR plan_id = ?",
        (ident, ident),
    ).fetchone()


def _ensure_doc(conn: Any, plan_id: str) -> Any:
    doc = _load_doc(conn, plan_id)
    if doc is not None:
        return doc
    plan = conn.execute(
        "SELECT * FROM plan_documents WHERE id = ?", (plan_id,)
    ).fetchone()
    if plan is None:
        return None
    header = _plan_header(plan)
    conn.execute(
        """INSERT INTO record_of_work_docs
           (id, plan_id, title, status, header_json, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?)""",
        (
            plan_id,
            plan_id,
            f"{plan['title']} - Record of Work",
            "Draft",
            json.dumps(header, ensure_ascii=False),
            _now(),
            _now(),
        ),
    )
    return _load_doc(conn, plan_id)


def resolve_doc_id(conn: Any, ident: str) -> str | None:
    """Accept a ROW document id, a scheme id or an individual ROW row id."""
    doc = _load_doc(conn, ident)
    if doc is not None:
        return str(doc["id"])
    row = conn.execute(
        "SELECT doc_id FROM record_of_work_rows WHERE id = ?", (ident,)
    ).fetchone()
    if row is not None:
        return str(row["doc_id"])
    plan = conn.execute(
        "SELECT id FROM plan_documents WHERE id = ?", (ident,)
    ).fetchone()
    if plan is not None:
        return str(plan["id"])
    return None


def _row(conn: Any, row_id: str) -> Any:
    return conn.execute(
        "SELECT * FROM record_of_work_rows WHERE id = ?", (row_id,)
    ).fetchone()


def _row_dict(r: Any) -> dict[str, Any]:
    planned = r["planned_work"] or ""
    work = r["work_done"] or ""
    d = r["date"] or ""
    return {
        "id": r["id"],
        "docId": r["doc_id"],
        "planId": r["plan_id"],
        "schemeRowId": r["scheme_row_id"],
        "lessonPlanId": r["lesson_plan_id"],
        "origin": r["origin"],
        "carryOverFromRowId": r["source_row_id"],
        "carryOverNote": r["carry_over_note"] or "",
        "date": d,
        "dateInFuture": bool(d and d > _today()),
        "week": int(r["week"]),
        "lesson": int(r["lesson"]),
        "strand": r["strand"] or "",
        "subStrand": r["sub_strand"] or "",
        "focusKeyword": r["focus_keyword"] or "",
        "plannedWork": planned,
        "workDone": work,
        "isPlanned": bool(work and work == planned and not r["edited"]),
        "reflection": r["reflection"] or "",
        "status": r["status"] or "",
        "carryOverTo": _json(r["carry_over_to"], None),
        "signature": r["signature"] or "",
        "source": r["source"],
        "teacherEdited": bool(r["edited"]),
        "aiDraft": r["ai_draft"] or None,
        "aiEnriched": bool(r["ai_enriched"]),
        "aiProvider": r["ai_provider"],
        "aiTimestamp": r["ai_timestamp"],
        "createdAt": r["created_at"],
        "updatedAt": r["updated_at"],
    }


def _is_final(conn: Any, doc_id: str) -> bool:
    doc = _load_doc(conn, doc_id)
    return bool(doc and doc["status"] == "Final")


# ---------------------------------------------------------------------------
# Coverage / gaps (always visible in the header)
# ---------------------------------------------------------------------------


def coverage(conn: Any, doc_id: str) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT * FROM record_of_work_rows WHERE doc_id = ? ORDER BY week, lesson, created_at",
        (doc_id,),
    ).fetchall()
    planned_rows = [r for r in rows if r["origin"] == "planned"]
    planned = len(planned_rows)
    taught = sum(1 for r in planned_rows if r["status"] == "Taught")
    partially = sum(1 for r in planned_rows if r["status"] == "Partially Taught")
    not_taught = sum(
        1 for r in planned_rows if (r["status"] or "").startswith("Not Taught")
    )
    carry_over = sum(
        1 for r in planned_rows if r["status"] == "Not Taught - Carry Over"
    )
    unrecorded = sum(1 for r in planned_rows if not (r["status"] or "").strip())
    pct = round(taught * 100 / planned) if planned else 0

    gaps: list[dict[str, Any]] = []
    for r in rows:
        if r["status"] not in GAP_STATUSES:
            continue
        reason = (r["reflection"] or "").strip() or (r["carry_over_note"] or "").strip()
        gaps.append(
            {
                "rowId": r["id"],
                "week": int(r["week"]),
                "lesson": int(r["lesson"]),
                "strand": r["strand"] or "",
                "subStrand": r["sub_strand"] or "",
                "focusKeyword": r["focus_keyword"] or "",
                "status": r["status"],
                "reason": reason,
                "carryOverTo": _json(r["carry_over_to"], None),
                "origin": r["origin"],
            }
        )

    warning = None
    if planned and taught < planned:
        warning = (
            f"Coverage {pct}% - {planned - taught} lessons not taught. See Gaps."
        )
    return {
        "planned": planned,
        "taught": taught,
        "partially": partially,
        "notTaught": not_taught,
        "carryOver": carry_over,
        "unrecorded": unrecorded,
        "coveragePct": pct,
        "coverageLabel": f"{taught}/{planned} ({pct}%)",
        "carryOverRows": len(rows) - planned,
        "gaps": gaps,
        "warning": warning,
    }


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def _versions(conn: Any, doc_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM record_of_work_versions WHERE doc_id = ? ORDER BY version_number DESC",
        (doc_id,),
    ).fetchall()
    return [
        {
            "id": v["id"],
            "versionNumber": int(v["version_number"]),
            "label": v["label"] or f"v{v['version_number']}",
            "comment": v["comment"],
            "kind": v["kind"],
            "createdAt": v["created_at"],
        }
        for v in rows
    ]


def get_document(ident: str, focus_row_id: str | None = None) -> dict[str, Any] | None:
    """Full ROW document for a scheme (or for a doc id / row id)."""
    with connect() as conn:
        doc_id = resolve_doc_id(conn, ident)
        if doc_id is None:
            return None
        doc = _ensure_doc(conn, doc_id)
        if doc is None:
            return None
        plan = conn.execute(
            "SELECT * FROM plan_documents WHERE id = ?", (doc["plan_id"],)
        ).fetchone()
        rows = conn.execute(
            """SELECT * FROM record_of_work_rows WHERE doc_id = ?
               ORDER BY week, lesson,
                        CASE origin WHEN 'planned' THEN 0 ELSE 1 END, created_at""",
            (doc_id,),
        ).fetchall()
        cov = coverage(conn, doc_id)
        versions = _versions(conn, doc_id)
        header = _json(doc["header_json"], {})
        if not header and plan is not None:
            header = _plan_header(plan)
        return {
            "id": doc["id"],
            "planId": doc["plan_id"],
            "title": doc["title"],
            "schemeTitle": plan["title"] if plan else "",
            "status": doc["status"],
            "finalVersionLabel": doc["final_version_label"],
            "header": header,
            "rowExists": bool(rows),
            "rows": [_row_dict(r) for r in rows],
            "coverage": cov,
            "versions": versions,
            "ai": ai_service.ai_status(),
            "createdAt": doc["created_at"],
            "updatedAt": doc["updated_at"],
            "focusRowId": focus_row_id,
        }


def get_row(row_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        r = _row(conn, row_id)
        return _row_dict(r) if r else None


def list_schemes() -> dict[str, Any]:
    """Scheme picker: show ROW state for every scheme without creating anything."""
    with connect() as conn:
        plans = conn.execute(
            "SELECT id, title, grade, subject, term, status FROM plan_documents "
            "WHERE owner_id = ? ORDER BY created_at DESC",
            (current_owner_id(),),
        ).fetchall()
        items = []
        for p in plans:
            doc = conn.execute(
                "SELECT * FROM record_of_work_docs WHERE plan_id = ?", (p["id"],)
            ).fetchone()
            row_count = 0
            taught = 0
            if doc:
                agg = conn.execute(
                    """SELECT COUNT(*) n, SUM(CASE WHEN status = 'Taught' THEN 1 ELSE 0 END) t
                       FROM record_of_work_rows WHERE doc_id = ? AND origin = 'planned'""",
                    (doc["id"],),
                ).fetchone()
                row_count = int(agg["n"] or 0)
                taught = int(agg["t"] or 0)
            sections = conn.execute(
                "SELECT COUNT(*) n FROM plan_sections WHERE plan_id = ?", (p["id"],)
            ).fetchone()
            items.append(
                {
                    "planId": p["id"],
                    "title": p["title"],
                    "grade": p["grade"],
                    "subject": p["subject"],
                    "term": p["term"],
                    "schemeStatus": p["status"],
                    "sectionCount": int(sections["n"] or 0),
                    "rowExists": row_count > 0,
                    "rowCount": row_count,
                    "taught": taught,
                    "rowStatus": doc["status"] if doc else "Draft",
                }
            )
        return {"schemes": items, "count": len(items)}


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def _section_vetted(conn: Any, section_id: str) -> bool:
    """A section is usable only when ALL of its cited chunks are Vetted."""
    chunks = conn.execute(
        """SELECT DISTINCT chunk_id FROM plan_citations
           WHERE section_id = ? AND chunk_id IS NOT NULL AND chunk_id != ''""",
        (section_id,),
    ).fetchall()
    if not chunks:
        return False
    for c in chunks:
        row = conn.execute(
            "SELECT vetting_status FROM source_chunks WHERE id = ?", (c["chunk_id"],)
        ).fetchone()
        if row is None or (row["vetting_status"] or "Pending") != VETTED:
            return False
    return True


def generate_rows(
    plan_id: str, add_missing_only: bool = False
) -> tuple[dict[str, Any] | None, list[str]]:
    """Create ONE ROW row per scheme lesson. Idempotent - never duplicates."""
    with connect() as conn:
        plan = conn.execute(
            "SELECT * FROM plan_documents WHERE id = ?", (plan_id,)
        ).fetchone()
        if plan is None:
            return None, ["Scheme not found."]
        if _is_final(conn, plan_id):
            return None, ["This record of work is Final. Press [Unlock to Edit] first."]
        sections = conn.execute(
            """SELECT * FROM plan_sections WHERE plan_id = ?
               ORDER BY week_start, ord, id""",
            (plan_id,),
        ).fetchall()
        if not sections:
            return None, ["This scheme has no rows to generate."]

        # Vetting guard: Pending chunks must never produce a Record of Work.
        pending = [
            f"Week {s['week_start'] or '?'}"
            for s in sections
            if not _section_vetted(conn, s["id"])
        ]
        if pending:
            return None, [
                "Cannot generate ROW for Pending chunks "
                f"({', '.join(pending[:6])}{'…' if len(pending) > 6 else ''}). "
                "Cannot generate ROW - source not Vetted. Fix in Library or unselect it."
            ]

        doc = _ensure_doc(conn, plan_id)
        header = _plan_header(plan)
        signature = " · ".join(
            x for x in (header.get("teacher"), header.get("tscNo")) if x
        )
        existing = {
            (r["scheme_row_id"], int(r["lesson"]))
            for r in conn.execute(
                """SELECT scheme_row_id, lesson FROM record_of_work_rows
                   WHERE doc_id = ? AND origin = 'planned'""",
                (doc["id"],),
            )
        }
        lesson_plans = {
            (r["section_id"], int(r["lesson"])): r
            for r in conn.execute(
                "SELECT * FROM lesson_plans WHERE plan_id = ?", (plan_id,)
            )
        }

        created = 0
        for s in sections:
            start = int(s["lesson_start"] or 1)
            end = int(s["lesson_end"] or start)
            count = max(1, end - start + 1)
            try:
                assignments = (decomposition_for_section(s).get("assignments") or [])
            except Exception:
                assignments = []
            for n in range(1, count + 1):
                if (s["id"], n) in existing:
                    continue
                lp = lesson_plans.get((s["id"], n))
                fallback_focus = ""
                if 0 <= n - 1 < len(assignments):
                    fallback_focus = str(assignments[n - 1].get("focus") or "")
                focus = (
                    (str(lp["focus"]) if lp and lp["focus"] else "")
                    or fallback_focus
                    or str(s["sub_strand"] or "")
                    or f"Lesson {n}"
                )
                planned_work = f"Planned: {focus} (Lesson {n})"
                conn.execute(
                    """INSERT INTO record_of_work_rows
                       (id, doc_id, plan_id, scheme_row_id, lesson_plan_id, origin,
                        week, lesson, date, strand, sub_strand, focus_keyword,
                        planned_work, work_done, reflection, status, signature,
                        source, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        new_id(),
                        doc["id"],
                        plan_id,
                        s["id"],
                        lp["id"] if lp else None,
                        "planned",
                        int(s["week_start"] or 1),
                        n,
                        (str(lp["date"]) if lp and lp["date"] else ""),
                        s["strand"],
                        s["sub_strand"],
                        focus,
                        planned_work,
                        planned_work,
                        "",  # Reflection ALWAYS empty on generation.
                        "",  # Status ALWAYS blank; never assume taught.
                        signature,
                        SOURCE_AUTO,
                        _now(),
                        _now(),
                    ),
                )
                created += 1
        conn.execute(
            "UPDATE record_of_work_docs SET header_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(header, ensure_ascii=False), _now(), doc["id"]),
        )

    document = get_document(plan_id)
    if document is None:
        return None, ["Could not load Record of Work after generation."]
    return {
        **document,
        "created": created,
        "addedMissingOnly": bool(add_missing_only),
        "message": (
            f"Created {created} ROW row(s)." if created else "No new rows - ROW is already complete."
        ),
    }, []


# ---------------------------------------------------------------------------
# Editing (never mutates Scheme / Lesson Plan / SourceChunk / Lesson Notes)
# ---------------------------------------------------------------------------


FIELD_COLUMN = {
    "date": "date",
    "workDone": "work_done",
    "reflection": "reflection",
    "status": "status",
    "signature": "signature",
}


def edit_row(row_id: str, patch: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    patch = patch or {}
    if not isinstance(patch, dict):
        return None, ["Invalid edit payload."]
    status = patch.get("status", None)
    if status is not None and status not in STATUSES:
        return None, [f"Unknown status '{status}'."]

    sets: list[str] = []
    args: list[Any] = []
    for key, column in FIELD_COLUMN.items():
        if key not in patch:
            continue
        value = patch[key]
        sets.append(f"{column} = ?")
        args.append("" if value is None else str(value))
    if "carryOverTo" in patch:
        target = patch["carryOverTo"]
        sets.append("carry_over_to = ?")
        args.append(json.dumps(target, ensure_ascii=False) if target else None)

    with connect() as conn:
        r = _row(conn, row_id)
        if r is None:
            return None, ["ROW row not found."]
        if _is_final(conn, r["doc_id"]):
            return None, ["This record of work is Final. Press [Unlock to Edit] first."]
        if not sets:
            return {"row": _row_dict(r), "coverage": coverage(conn, r["doc_id"])}, []
        sets += ["edited = 1", "source = ?", "updated_at = ?"]
        args += [SOURCE_EDITED, _now(), row_id]
        conn.execute(
            f"UPDATE record_of_work_rows SET {', '.join(sets)} WHERE id = ?",
            tuple(args),
        )
        conn.execute(
            "UPDATE record_of_work_docs SET updated_at = ? WHERE id = ?",
            (_now(), r["doc_id"]),
        )
        updated = _row(conn, row_id)
        return {
            "row": _row_dict(updated),
            "coverage": coverage(conn, r["doc_id"]),
        }, []


def reset_row(row_id: str) -> tuple[dict[str, Any] | None, list[str]]:
    """[Reset to Planned]: restore Work Done, clear Reflection, Status and AI draft."""
    with connect() as conn:
        r = _row(conn, row_id)
        if r is None:
            return None, ["ROW row not found."]
        if _is_final(conn, r["doc_id"]):
            return None, ["This record of work is Final. Press [Unlock to Edit] first."]
        conn.execute(
            """UPDATE record_of_work_rows
               SET work_done = planned_work, reflection = '', status = '',
                   carry_over_to = NULL, edited = 0, source = ?,
                   ai_draft = NULL, updated_at = ?
               WHERE id = ?""",
            (SOURCE_AUTO, _now(), row_id),
        )
        updated = _row(conn, row_id)
        return {
            "row": _row_dict(updated),
            "coverage": coverage(conn, r["doc_id"]),
        }, []


def bulk_status(
    ident: str, week: int, status: str
) -> tuple[dict[str, Any] | None, list[str]]:
    """[Mark All Week N as Taught] - changes Status ONLY, never Work Done/Reflection."""
    if status not in STATUSES or not status:
        return None, [f"Unknown status '{status}'."]
    with connect() as conn:
        doc_id = resolve_doc_id(conn, ident)
        if doc_id is None:
            return None, ["Record of Work not found."]
        if _is_final(conn, doc_id):
            return None, ["This record of work is Final. Press [Unlock to Edit] first."]
        # Carry-over rows keep their audit status; gaps must never be hidden.
        skipped = conn.execute(
            """SELECT COUNT(*) n FROM record_of_work_rows
               WHERE doc_id = ? AND week = ? AND origin = 'planned'
                 AND status = 'Not Taught - Carry Over'""",
            (doc_id, int(week)),
        ).fetchone()["n"]
        cur = conn.execute(
            """UPDATE record_of_work_rows SET status = ?, updated_at = ?
               WHERE doc_id = ? AND week = ? AND origin = 'planned'
                 AND status != 'Not Taught - Carry Over'""",
            (status, _now(), doc_id, int(week)),
        )
        conn.execute(
            "UPDATE record_of_work_docs SET updated_at = ? WHERE id = ?",
            (_now(), doc_id),
        )
    document = get_document(doc_id)
    extra = f" {skipped} carry-over row(s) kept for audit." if skipped else ""
    return {
        **(document or {}),
        "updated": cur.rowcount,
        "message": (
            f"Week {week}: {cur.rowcount} row(s) set to {status}. "
            "Work Done and Reflection were left untouched." + extra
        ),
    }, []


# ---------------------------------------------------------------------------
# Carry over (audit-safe: the original row is never deleted)
# ---------------------------------------------------------------------------


def carry_over(
    row_id: str, target_week: Any, target_lesson: Any
) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        week, lesson = int(target_week), int(target_lesson)
    except (TypeError, ValueError):
        return None, ["Carry-over target must be a week and lesson number."]
    if week < 1 or lesson < 1:
        return None, ["Carry-over target must be a positive week and lesson number."]

    with connect() as conn:
        src = _row(conn, row_id)
        if src is None:
            return None, ["ROW row not found."]
        if _is_final(conn, src["doc_id"]):
            return None, ["This record of work is Final. Press [Unlock to Edit] first."]
        duplicate = conn.execute(
            """SELECT id FROM record_of_work_rows
               WHERE source_row_id = ? AND week = ? AND lesson = ?""",
            (row_id, week, lesson),
        ).fetchone()
        if duplicate is not None:
            return None, [f"Carry-over to Week {week} Lesson {lesson} already exists."]

        label = src["focus_keyword"] or src["sub_strand"] or "the planned lesson"
        note = f"Carry-over from Week {src['week']} Lesson {src['lesson']}: {label}"
        conn.execute(
            """INSERT INTO record_of_work_rows
               (id, doc_id, plan_id, scheme_row_id, lesson_plan_id, origin,
                source_row_id, carry_over_note, week, lesson, date, strand,
                sub_strand, focus_keyword, planned_work, work_done, reflection,
                status, signature, source, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                new_id(),
                src["doc_id"],
                src["plan_id"],
                src["scheme_row_id"],
                None,
                "carry-over",
                row_id,
                note,
                week,
                lesson,
                "",
                src["strand"],
                src["sub_strand"],
                src["focus_keyword"],
                note,
                note,
                "",
                "",
                "",
                SOURCE_AUTO,
                _now(),
                _now(),
            ),
        )
        conn.execute(
            """UPDATE record_of_work_rows
               SET status = ?, carry_over_to = ?, edited = 1, source = ?, updated_at = ?
               WHERE id = ?""",
            (
                "Not Taught - Carry Over",
                json.dumps({"week": week, "lesson": lesson}),
                SOURCE_EDITED,
                _now(),
                row_id,
            ),
        )
        conn.execute(
            "UPDATE record_of_work_docs SET updated_at = ? WHERE id = ?",
            (_now(), src["doc_id"]),
        )
        original = _row(conn, row_id)
        created = conn.execute(
            """SELECT * FROM record_of_work_rows
               WHERE source_row_id = ? AND week = ? AND lesson = ?""",
            (row_id, week, lesson),
        ).fetchone()

    document = get_document(original["doc_id"])
    return {
        **(document or {}),
        "newRow": _row_dict(created),
        "originalRow": _row_dict(original),
        "message": f"{note} → Week {week} Lesson {lesson}. The original row was kept for audit.",
    }, []


def mark_taught(
    plan_id: str, week: Any, lesson: Any
) -> tuple[dict[str, Any] | None, list[str]]:
    """Entry point [→ Mark as Taught] from a Lesson Plan. Teacher-initiated only."""
    try:
        w, l = int(week), int(lesson)
    except (TypeError, ValueError):
        return None, ["Week and lesson must be numbers."]
    with connect() as conn:
        doc = _load_doc(conn, plan_id)
        has_rows = bool(
            doc
            and conn.execute(
                "SELECT 1 FROM record_of_work_rows WHERE doc_id = ? LIMIT 1", (doc["id"],)
            ).fetchone()
        )
    if not has_rows:
        _, errors = generate_rows(plan_id)
        if errors:
            return None, errors
    with connect() as conn:
        doc_id = resolve_doc_id(conn, plan_id)
        if doc_id is None:
            return None, ["Record of Work not found."]
        if _is_final(conn, doc_id):
            return None, ["This record of work is Final. Press [Unlock to Edit] first."]
        row = conn.execute(
            """SELECT * FROM record_of_work_rows
               WHERE doc_id = ? AND week = ? AND lesson = ? AND origin = 'planned'
               ORDER BY created_at LIMIT 1""",
            (doc_id, w, l),
        ).fetchone()
        if row is None:
            return None, [f"No ROW row for Week {w} Lesson {lesson}."]
        conn.execute(
            """UPDATE record_of_work_rows
               SET status = 'Taught', edited = 1, source = ?, updated_at = ?
               WHERE id = ?""",
            (SOURCE_EDITED, _now(), row["id"]),
        )
    document = get_document(doc_id, focus_row_id=row["id"])
    return {
        **(document or {}),
        "rowId": row["id"],
        "message": f"Week {w} Lesson {lesson} marked as Taught. Work Done and Reflection are still yours to fill.",
    }, []


# ---------------------------------------------------------------------------
# AI - opt-in, Reflection only, never Work Done / Status
# ---------------------------------------------------------------------------


def suggest_reflection(row_id: str) -> tuple[dict[str, Any] | None, list[str]]:
    status = ai_service.ai_status()
    if not status["available"]:
        return None, [status["message"]]
    with connect() as conn:
        r = _row(conn, row_id)
        if r is None:
            return None, ["ROW row not found."]
        if _is_final(conn, r["doc_id"]):
            return None, ["This record of work is Final. Press [Unlock to Edit] first."]
        work_done = (r["work_done"] or "").strip()
        if not work_done or work_done == (r["planned_work"] or ""):
            return None, [
                "Edit Work Done to describe what actually happened before suggesting a reflection."
            ]
    prompt = (
        "Based on Work Done: '" + work_done + "', suggest 2-3 sentences for Reflection. "
        "Do NOT invent what happened. Do NOT claim learners understood anything if the "
        "teacher did not say so. Use the teacher's words only. "
        'Return JSON: {"reflection": "..."}'
    )
    try:
        data = ai_service.post_ai_json(prompt, ROW_AI_SYSTEM)
        draft = str((data or {}).get("reflection") or "").strip()
    except (ai_service.AIError, ai_service.AIUnavailable) as e:
        return None, [str(e)]
    except Exception as e:  # pragma: no cover - provider-specific failures
        return None, [f"AI reflection failed: {e}"]
    if not draft:
        return None, ["AI returned an empty reflection."]

    provider = status.get("provider") or "ai"
    with connect() as conn:
        conn.execute(
            """UPDATE record_of_work_rows
               SET ai_draft = ?, ai_enriched = 1, ai_provider = ?, ai_timestamp = ?,
                   updated_at = ? WHERE id = ?""",
            (draft, provider, _now(), _now(), row_id),
        )
        updated = _row(conn, row_id)
    return {
        "row": _row_dict(updated),
        "draft": draft,
        "provider": provider,
        "message": "AI Draft - Not from source - Review. Accept, Edit or Reject it.",
    }, []


def accept_reflection(
    row_id: str, text: str | None = None
) -> tuple[dict[str, Any] | None, list[str]]:
    with connect() as conn:
        r = _row(conn, row_id)
        if r is None:
            return None, ["ROW row not found."]
        if _is_final(conn, r["doc_id"]):
            return None, ["This record of work is Final. Press [Unlock to Edit] first."]
        draft = (text or r["ai_draft"] or "").strip()
        if not draft:
            return None, ["There is no AI draft to accept."]
        conn.execute(
            """UPDATE record_of_work_rows
               SET reflection = ?, ai_draft = NULL, edited = 1, source = ?, updated_at = ?
               WHERE id = ?""",
            (draft, SOURCE_EDITED, _now(), row_id),
        )
        updated = _row(conn, row_id)
        return {"row": _row_dict(updated)}, []


def reject_reflection(row_id: str) -> tuple[dict[str, Any] | None, list[str]]:
    """Reject clears the pending draft only. Reflection stays empty if it was empty."""
    with connect() as conn:
        r = _row(conn, row_id)
        if r is None:
            return None, ["ROW row not found."]
        conn.execute(
            "UPDATE record_of_work_rows SET ai_draft = NULL, updated_at = ? WHERE id = ?",
            (_now(), row_id),
        )
        updated = _row(conn, row_id)
        return {"row": _row_dict(updated)}, []


# ---------------------------------------------------------------------------
# Versions - append-only snapshots of the ENTIRE ROW document
# ---------------------------------------------------------------------------


def _snapshot(doc_id: str) -> dict[str, Any]:
    doc = get_document(doc_id)
    if doc is None:
        return {}
    # Avoid nested version lists / live AI status inside the snapshot.
    return {k: v for k, v in doc.items() if k not in ("versions", "ai", "coverage")}


def create_version(
    ident: str, comment: str, kind: str = "version", label: str | None = None
) -> tuple[dict[str, Any] | None, list[str]]:
    comment = (comment or "").strip()
    if not comment:
        return None, ["A comment is required, e.g. 'Filled Week 2 after teaching'."]
    with connect() as conn:
        doc_id = resolve_doc_id(conn, ident)
    if doc_id is None:
        return None, ["Record of Work not found."]
    # Snapshot BEFORE opening the write transaction (avoids a nested connection).
    snapshot = _snapshot(doc_id)
    with connect() as conn:
        n = int(
            conn.execute(
                """SELECT COALESCE(MAX(version_number), 0) n
                   FROM record_of_work_versions WHERE doc_id = ?""",
                (doc_id,),
            ).fetchone()["n"]
            or 0
        ) + 1
        version_id = new_id()
        conn.execute(
            """INSERT INTO record_of_work_versions
               (id, doc_id, version_number, label, comment, kind, snapshot_json, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                version_id,
                doc_id,
                n,
                label or f"v{n}",
                comment,
                kind,
                json.dumps(snapshot, ensure_ascii=False),
                _now(),
            ),
        )
    return {
        "id": version_id,
        "versionNumber": n,
        "label": label or f"v{n}",
        "comment": comment,
        "kind": kind,
        "createdAt": _now(),
        "recordOfWork": get_document(doc_id),
    }, []


def list_versions(ident: str) -> dict[str, Any] | None:
    with connect() as conn:
        doc_id = resolve_doc_id(conn, ident)
        if doc_id is None:
            return None
        versions = _versions(conn, doc_id)
        return {"versions": versions, "count": len(versions)}


def get_version(ident: str, version_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        doc_id = resolve_doc_id(conn, ident)
        if doc_id is None:
            return None
        v = conn.execute(
            "SELECT * FROM record_of_work_versions WHERE id = ? AND doc_id = ?",
            (version_id, doc_id),
        ).fetchone()
        if v is None:
            return None
        return {
            "id": v["id"],
            "versionNumber": int(v["version_number"]),
            "label": v["label"],
            "comment": v["comment"],
            "kind": v["kind"],
            "createdAt": v["created_at"],
            "snapshot": _json(v["snapshot_json"], {}),
        }


def diff_version(ident: str, version_id: str) -> dict[str, Any] | None:
    version = get_version(ident, version_id)
    with connect() as conn:
        doc_id = resolve_doc_id(conn, ident)
    if version is None or doc_id is None:
        return None
    current = get_document(doc_id)
    if current is None:
        return None
    old_rows = {r["id"]: r for r in (version["snapshot"].get("rows") or [])}
    new_rows = {r["id"]: r for r in current["rows"]}
    fields = [
        "date",
        "workDone",
        "reflection",
        "status",
        "signature",
    ]
    cells: list[dict[str, Any]] = []
    for row_id in sorted(set(old_rows) | set(new_rows)):
        old = old_rows.get(row_id) or {}
        new = new_rows.get(row_id) or {}
        label = f"Week {new.get('week') or old.get('week')} · Lesson {new.get('lesson') or old.get('lesson')}"
        for field in fields:
            frm, to = str(old.get(field) or ""), str(new.get(field) or "")
            if frm == to:
                continue
            state = "removed" if frm and not to else "added" if not frm and to else "changed"
            cells.append(
                {
                    "field": f"{row_id}:{field}",
                    "label": f"{label} · {field}",
                    "from": frm,
                    "to": to,
                    "status": state,
                }
            )
    return {
        "version": {k: v for k, v in version.items() if k != "snapshot"},
        "from": version["label"],
        "to": "Current",
        "cells": cells[:200],
        "summary": {
            "changed": sum(1 for c in cells if c["status"] == "changed"),
            "added": sum(1 for c in cells if c["status"] == "added"),
            "removed": sum(1 for c in cells if c["status"] == "removed"),
        },
    }


def restore_version(ident: str, version_id: str) -> tuple[dict[str, Any] | None, list[str]]:
    """Restore applies the snapshot, then appends a NEW version. Nothing is deleted."""
    version = get_version(ident, version_id)
    if version is None:
        return None, ["Version not found."]
    with connect() as conn:
        doc_id = resolve_doc_id(conn, ident)
        if doc_id is None:
            return None, ["Record of Work not found."]
        if _is_final(conn, doc_id):
            return None, ["This record of work is Final. Press [Unlock to Edit] first."]
        snapshot = version["snapshot"] or {}
        rows = snapshot.get("rows") or []
        conn.execute("DELETE FROM record_of_work_rows WHERE doc_id = ?", (doc_id,))
        for r in rows:
            conn.execute(
                """INSERT INTO record_of_work_rows
                   (id, doc_id, plan_id, scheme_row_id, lesson_plan_id, origin,
                    source_row_id, carry_over_note, week, lesson, date, strand,
                    sub_strand, focus_keyword, planned_work, work_done, reflection,
                    status, carry_over_to, signature, source, edited, ai_draft,
                    ai_enriched, ai_provider, ai_timestamp, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    r.get("id") or new_id(),
                    doc_id,
                    r.get("planId") or doc_id,
                    r.get("schemeRowId") or "",
                    r.get("lessonPlanId"),
                    r.get("origin") or "planned",
                    r.get("carryOverFromRowId"),
                    r.get("carryOverNote") or "",
                    int(r.get("week") or 1),
                    int(r.get("lesson") or 1),
                    r.get("date") or "",
                    r.get("strand") or "",
                    r.get("subStrand") or "",
                    r.get("focusKeyword") or "",
                    r.get("plannedWork") or "",
                    r.get("workDone") or "",
                    r.get("reflection") or "",
                    r.get("status") or "",
                    json.dumps(r.get("carryOverTo"), ensure_ascii=False)
                    if r.get("carryOverTo")
                    else None,
                    r.get("signature") or "",
                    r.get("source") or SOURCE_AUTO,
                    1 if r.get("teacherEdited") else 0,
                    r.get("aiDraft"),
                    1 if r.get("aiEnriched") else 0,
                    r.get("aiProvider"),
                    r.get("aiTimestamp"),
                    r.get("createdAt") or _now(),
                    _now(),
                ),
            )
        conn.execute(
            "UPDATE record_of_work_docs SET updated_at = ? WHERE id = ?",
            (_now(), doc_id),
        )
    new, errors = create_version(
        doc_id, f"Restored from v{version['versionNumber']}", kind="restore"
    )
    if errors:
        return None, errors
    doc = get_document(doc_id)
    return {**(doc or {}), "restoredVersion": (new or {}).get("id")}, []


# ---------------------------------------------------------------------------
# Draft / Final lifecycle
# ---------------------------------------------------------------------------


def set_doc_status(ident: str, status: str) -> tuple[dict[str, Any] | None, list[str]]:
    if status not in DOC_STATUSES:
        return None, [f"Unknown status '{status}'."]
    with connect() as conn:
        doc_id = resolve_doc_id(conn, ident)
        if doc_id is None:
            return None, ["Record of Work not found."]
        doc = _load_doc(conn, doc_id)
        plan_id = doc["plan_id"]
        label = ""
        if status == "Final":
            blanks = conn.execute(
                """SELECT COUNT(*) n FROM record_of_work_rows
                   WHERE doc_id = ? AND (status IS NULL OR status = '')""",
                (doc_id,),
            ).fetchone()["n"]
            if blanks:
                return None, [
                    f"Cannot Mark Final: {blanks} row(s) still have an empty Status. "
                    "Select a status for every lesson."
                ]
            plan = conn.execute(
                "SELECT * FROM plan_documents WHERE id = ?", (plan_id,)
            ).fetchone()
            term = _plan_header(plan).get("term") if plan else ""
            label = f"Final - {term or (plan['term'] if plan else 'Term')}"
            conn.execute(
                """UPDATE record_of_work_docs
                   SET status = 'Final', final_version_label = ?, updated_at = ?
                   WHERE id = ?""",
                (label, _now(), doc_id),
            )
        else:
            conn.execute(
                "UPDATE record_of_work_docs SET status = 'Draft', updated_at = ? WHERE id = ?",
                (_now(), doc_id),
            )

    # Versioning happens after the status write commits, never inside its transaction.
    if status == "Final":
        _, errors = create_version(doc_id, f"Marked {label}", kind="final", label=label)
    else:
        _, errors = create_version(
            doc_id, "Unlocked from Final", kind="unlock", label="Unlocked from Final"
        )
    if errors:
        return None, errors
    return get_document(doc_id), []
