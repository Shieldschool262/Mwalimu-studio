"""Planning service - OFFICIAL KICD SCHEME OF WORK (cbe-scheme-v1).

Non-negotiable rules:

* Curriculum facts (outcomes, experiences, KIQs) are copied VERBATIM from the selected
  SourceChunk.structuredFields. No LLM is involved anywhere in this module.
* A scheme can only be generated from chunks whose vetting_status == "Vetted".
  Vetting depends on outcomes + experiences + KIQs only. Resources, assessment and
  reflection NEVER affect vetting and NEVER block generation.
* Reflection / Remarks is ALWAYS empty on generation and is never AI-filled.
* Week/Lesson allocation warns on overflow and NEVER silently truncates.

Column definitions live in templates/cbe-scheme-v1.json, not in this file.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from auth_service import current_owner_id
from db import connect, list_chunks, new_id
from services.library_service import CORE_VETTING_FIELDS, VETTED
from services.lesson_derive import preview_for_ui
from services.rubric_service import ensure_chunk_rubric
from services.weekly_split import build_weekly_rows, rebalance_outcomes

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = BACKEND_ROOT / "templates"
DEFAULT_TEMPLATE = "cbe-scheme-v1"

SCHEME = "scheme"

NOT_IN_SOURCE = "— Not specified in source"


def load_template(version: str = DEFAULT_TEMPLATE) -> dict[str, Any]:
    path = TEMPLATES_DIR / f"{version}.json"
    if not path.exists():
        path = TEMPLATES_DIR / f"{DEFAULT_TEMPLATE}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Generation guard (vetting)
# ---------------------------------------------------------------------------


def _has(sf: dict[str, Any], key: str) -> bool:
    val = sf.get(key)
    if isinstance(val, list):
        return any(str(x).strip() for x in val)
    return bool(str(val or "").strip())


def validate_sources(chunk_ids: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (usable chunks in selection order, errors). Blocks on ANY non-vetted chunk."""
    if not chunk_ids:
        return [], ["Select at least one sub-strand."]

    with connect() as conn:
        marks = ",".join("?" for _ in chunk_ids)
        rows = conn.execute(
            f"SELECT * FROM source_chunks WHERE id IN ({marks})", tuple(chunk_ids)
        ).fetchall()
    by_id = {r["id"]: r for r in rows}

    errors: list[str] = []
    usable: list[dict[str, Any]] = []
    for idx, cid in enumerate(chunk_ids):
        row = by_id.get(cid)
        if row is None:
            errors.append(f"Cannot generate: sub-strand no longer exists. Unselect it.")
            continue
        sf = json.loads(row["structured_fields"] or "{}")
        status = row["vetting_status"] if "vetting_status" in row.keys() else "Pending"
        if status != VETTED:
            code = row["sub_strand_code"] or row["sub_strand"]
            missing = [
                CORE_VETTING_FIELDS[k] for k in CORE_VETTING_FIELDS if not _has(sf, k)
            ]
            if missing:
                # Exact wording required by the spec.
                short = ["KIQs" if m == "Key Inquiry Questions" else m for m in missing]
                errors.append(
                    f"Cannot generate: {code} missing {' and '.join(short)}. "
                    "Fix in Library or unselect it."
                )
            else:
                errors.append(
                    f"Cannot generate: {code} is not approved. Fix in Library or unselect it."
                )
            continue
        usable.append(
            {
                "id": row["id"],
                "documentId": row["document_id"],
                "pageNumber": row["page_number"],
                "strand": row["strand"],
                "strandCode": row["strand_code"],
                "subStrand": row["sub_strand"],
                "subStrandCode": row["sub_strand_code"],
                "lessons": row["lessons"],
                "structured": sf,
                # Phase 3.5 appendix autofill values (never part of vetting).
                "appendixResources": (
                    row["appendix_resources"] if "appendix_resources" in row.keys() else None
                ),
                "appendixAssessment": (
                    row["appendix_assessment"] if "appendix_assessment" in row.keys() else None
                ),
                "appendixSource": (
                    row["appendix_source"] if "appendix_source" in row.keys() else None
                ),
                "appendixLevel": (
                    row["appendix_level"] if "appendix_level" in row.keys() else None
                ),
                # Phase 4: deterministic rubric match for lesson plans (never vetting).
                "rubric": ensure_chunk_rubric(row["id"]),
                "order": idx,
            }
        )
    usable.sort(key=lambda c: c["order"])
    return usable, errors


# ---------------------------------------------------------------------------
# Week / lesson allocation
# ---------------------------------------------------------------------------


def allocate(
    chunks: list[dict[str, Any]],
    lessons_per_week: int,
    total_weeks: int,
    template: dict[str, Any],
    start_week: int = 1,
) -> dict[str, Any]:
    """Expand each selected sub-strand into ONE ROW PER WEEK.

    Week numbers are single integers, lessons restart at 1 every week, and outcomes /
    experiences / KIQs are distributed across the weekly rows rather than repeated
    (see services/weekly_split.py). Nothing is truncated: if the selection does not fit the
    term a warning is returned and every row is still produced.
    """
    rows: list[dict[str, Any]] = []
    cursor = start_week
    total_lessons = 0

    for c in chunks:
        weekly = build_weekly_rows(c, lessons_per_week, cursor)
        rows.extend(weekly)
        cursor += len(weekly)
        total_lessons += int(c.get("lessons") or 0) if c.get("lessons") else 4

    capacity = lessons_per_week * total_weeks
    warning = None
    if total_lessons > capacity:
        warning = (
            f"Selected sub-strands need {total_lessons} lessons but term has {capacity} "
            f"- remove {total_lessons - capacity} lessons or extend weeks"
        )

    return {
        "rows": rows,
        "totalLessons": total_lessons,
        "capacity": capacity,
        "fits": total_lessons <= capacity,
        "warning": warning,
        "lessonsPerWeek": lessons_per_week,
        "totalWeeks": total_weeks,
        "weeksUsed": cursor - start_week,
    }


def _week_label(row: dict[str, Any]) -> str:
    """A single integer. Weeks are never merged into ranges."""
    w = row.get("week")
    return "" if w is None else str(w)


def _lesson_label(row: dict[str, Any]) -> str:
    a, b = row["lessonStart"], row["lessonEnd"]
    return f"{a}-{b}" if a != b else str(a)


def _general_outcomes(rows: list[dict[str, Any]]) -> str:
    """Join the first outcome of each selected sub-strand, in order."""
    picked: list[str] = []
    seen: set[str] = set()
    for r in rows:
        code = r.get("subStrandCode") or ""
        if code in seen:
            continue
        seen.add(code)
        outs = r["structured"].get("specific_learning_outcomes") or []
        for o in outs:
            txt = str(o).strip()
            if txt:
                picked.append(re.sub(r"^[a-z]\)\s*", "", txt))
                break
    return "; ".join(picked)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def create_plan(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    plan_type = (payload.get("type") or SCHEME).strip()
    template_version = payload.get("templateVersion") or DEFAULT_TEMPLATE
    template = load_template(template_version)

    grade = (payload.get("grade") or "").strip()
    subject = (payload.get("subject") or "").strip()
    term = (payload.get("term") or "").strip()
    year = str(payload.get("year") or "").strip()
    institution = (payload.get("institution") or "").strip()

    errors: list[str] = []
    if not institution:
        errors.append("Institution / School is required.")
    if not grade:
        errors.append("Grade is required.")
    if not subject:
        errors.append("Learning Area is required.")
    if not term:
        errors.append("Term is required.")
    if not year:
        errors.append("Year is required.")

    try:
        lessons_per_week = int(payload.get("lessonsPerWeek") or 5)
    except (TypeError, ValueError):
        lessons_per_week = 5
    try:
        total_weeks = int(payload.get("totalWeeks") or 13)
    except (TypeError, ValueError):
        total_weeks = 13
    if lessons_per_week <= 0:
        lessons_per_week = 5
    if total_weeks <= 0:
        total_weeks = 13

    chunk_ids = payload.get("sourceChunkIds") or []
    usable, guard_errors = validate_sources(chunk_ids)
    errors.extend(guard_errors)
    if errors:
        return None, errors

    result = allocate(usable, lessons_per_week, total_weeks, template)

    header = {
        "institution": institution,
        "grade": grade,
        "learningArea": subject,
        "term": term,
        "year": year,
        "teacherName": (payload.get("teacherName") or "").strip(),
        "tscNo": (payload.get("tscNo") or "").strip(),
        "generalOutcomes": _general_outcomes(result["rows"]),
    }
    allocation = {
        "lessonsPerWeek": lessons_per_week,
        "totalWeeks": total_weeks,
        "totalLessons": result["totalLessons"],
        "capacity": result["capacity"],
        "fits": result["fits"],
        "warning": result["warning"],
        "startWeek": int(payload.get("termStartWeek") or 1),
        "lessonMode": "sequential",
    }

    title = (
        (payload.get("title") or "").strip()
        or f"{grade} {subject} - {term} {year} - {template.get('title', 'SCHEME OF WORK').title()}"
    )

    plan_id = new_id()
    with connect() as conn:
        conn.execute(
            """INSERT INTO plan_documents
               (id, type, title, grade, subject, term, template_version, status,
                source_chunk_ids, ai_expanded, header, allocation, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                plan_id,
                plan_type,
                title,
                grade,
                subject,
                term,
                template.get("version", DEFAULT_TEMPLATE),
                "Draft",
                json.dumps(chunk_ids),
                0,
                json.dumps(header, ensure_ascii=False),
                json.dumps(allocation, ensure_ascii=False),
                _now(),
                _now(),
            ),
        )

        for ord_, row in enumerate(result["rows"]):
            sf = row["structured"]
            section_id = new_id()
            # Distributed across the week, NOT the full sub-strand list.
            outcomes = [str(x) for x in row["outcomes"]]
            experiences = [str(x) for x in row["experiences"]]
            kiqs = [str(x) for x in row["kiqs"]]

            # Resources: appendix value first (Phase 3.5), then any printed source value, else the
            # template fallback. Missing appendix NEVER blocks generation or vetting.
            res_raw = sf.get("suggested_learning_resources")
            resources = None
            if isinstance(res_raw, list):
                resources = "; ".join(str(x) for x in res_raw if str(x).strip()) or None
            elif res_raw:
                resources = str(res_raw).strip() or None
            if not resources and row.get("appendixResources"):
                resources = str(row["appendixResources"]).strip() or None

            # Assessment: appendix value first, then printed source, else the template default.
            assess_raw = sf.get("assessment")
            assessment = None
            if isinstance(assess_raw, list):
                assessment = "; ".join(str(x) for x in assess_raw if str(x).strip()) or None
            elif assess_raw:
                assessment = str(assess_raw).strip() or None
            if not assessment and row.get("appendixAssessment"):
                assessment = str(row["appendixAssessment"]).strip() or None

            # Keep the sub-strand's FULL source lists so [Re-balance] can always re-split,
            # even after a teacher trims a single weekly row.
            original = {
                "outcomes": [str(x) for x in (sf.get("specific_learning_outcomes") or [])],
                "experiences": [str(x) for x in (sf.get("suggested_learning_experiences") or [])],
                "kiqs": [str(x) for x in (sf.get("key_inquiry_questions") or [])],
                "week": row["week"],
                "lessonStart": row["lessonStart"],
                "lessonEnd": row["lessonEnd"],
                "lessonCount": row["lessonCount"],
                "lessonsPerWeek": row.get("lessonsPerWeek"),
                "appendixResources": row.get("appendixResources"),
                "appendixAssessment": row.get("appendixAssessment"),
                "appendixSource": row.get("appendixSource"),
                "appendixLevel": row.get("appendixLevel"),
                "partLabel": row["partLabel"],
                "outcomePartLabel": row.get("outcomePartLabel"),
                "weekCount": row["weekCount"],
                "resources": resources,
                "assessment": assessment,
                # Phase 4: the row's own source slice, so [Reset Row to Source] can restore
                # exactly what this week had (not the whole sub-strand).
                "sourceOutcomes": outcomes,
                "sourceExperiences": experiences,
                "sourceKiqs": kiqs,
                "rubric": row.get("rubric") or [],
            }

            conn.execute(
                """INSERT INTO plan_sections
                   (id, plan_id, ord, strand_code, strand, sub_strand, sub_strand_code,
                    outcomes, experiences, kiqs, competencies, values_text, pcis, link_other,
                    resources, assessment, reflection, edited, original,
                    week_start, week_end, lesson_start, lesson_end, lesson_count, flags, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    section_id,
                    plan_id,
                    ord_,
                    row["strandCode"],
                    row["strand"],
                    row["subStrand"],
                    row["subStrandCode"],
                    json.dumps(outcomes, ensure_ascii=False),
                    json.dumps(experiences, ensure_ascii=False),
                    json.dumps(kiqs, ensure_ascii=False),
                    None,
                    None,
                    None,
                    None,
                    resources,
                    assessment,
                    None,  # Reflection ALWAYS empty on generation.
                    0,
                    json.dumps(original, ensure_ascii=False),
                    row["week"],
                    row["week"],
                    row["lessonStart"],
                    row["lessonEnd"],
                    row["lessonCount"],
                    json.dumps(row["flags"], ensure_ascii=False),
                    _now(),
                ),
            )

            for field in (
                "specific_learning_outcomes",
                "suggested_learning_experiences",
                "key_inquiry_questions",
            ):
                conn.execute(
                    """INSERT INTO plan_citations
                       (id, plan_id, section_id, chunk_id, page_number, field, document_id, sub_strand_code)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        new_id(),
                        plan_id,
                        section_id,
                        row["chunkId"],
                        row["pageNumber"],
                        field,
                        row["documentId"],
                        row["subStrandCode"],
                    ),
                )

    # Phase 4: every generated scheme starts with a baseline version v1, so the very first
    # [Save Version] is v2 and history can always be compared and restored.
    create_plan_version(plan_id, "Initial generated version", kind="initial")
    return get_plan(plan_id), []


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def get_plan(plan_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        doc = conn.execute("SELECT * FROM plan_documents WHERE id = ?", (plan_id,)).fetchone()
        if doc is None:
            return None
        sections = conn.execute(
            "SELECT * FROM plan_sections WHERE plan_id = ? ORDER BY ord", (plan_id,)
        ).fetchall()
        cites = conn.execute(
            "SELECT * FROM plan_citations WHERE plan_id = ?", (plan_id,)
        ).fetchall()

    by_section: dict[str, list[dict[str, Any]]] = {}
    for c in cites:
        by_section.setdefault(c["section_id"], []).append(
            {
                "id": c["id"],
                "chunkId": c["chunk_id"],
                "documentId": c["document_id"],
                "pageNumber": c["page_number"],
                "field": c["field"],
                "subStrandCode": c["sub_strand_code"],
            }
        )

    template = load_template(doc["template_version"])
    header = json.loads(doc["header"] or "{}")
    allocation = json.loads(doc["allocation"] or "{}")

    built = [_row_to_section(r, by_section.get(r["id"], []), template) for r in sections]

    # Phase 4: vetting state of each row's source chunk (lesson plans are blocked when Pending)
    # and the deterministic decomposition preview shown on hover.
    chunk_ids = sorted({c["chunkId"] for s in built for c in s["citations"] if c["chunkId"]})
    vetting: dict[str, str] = {}
    if chunk_ids:
        with connect() as conn:
            marks = ",".join("?" for _ in chunk_ids)
            for r in conn.execute(
                f"SELECT id, vetting_status FROM source_chunks WHERE id IN ({marks})",
                tuple(chunk_ids),
            ):
                vetting[r["id"]] = (
                    r["vetting_status"] if "vetting_status" in r.keys() else "Pending"
                )
    for s in built:
        cid = next((c["chunkId"] for c in s["citations"] if c["chunkId"]), None)
        s["sourceVettingStatus"] = vetting.get(cid) if cid else "Pending"
        s["sourceVetted"] = s["sourceVettingStatus"] == VETTED
        live = s["experiences"] or []
        count = max(1, (s.get("lessonEnd") or s.get("lessonStart") or 1) - (s.get("lessonStart") or 1) + 1)
        s["weekLessonCount"] = count
        s["decomposition"] = preview_for_ui(live, count)

    # Source document names for the footer line.
    doc_ids = sorted({c["documentId"] for s in built for c in s["citations"] if c["documentId"]})
    sources: list[str] = []
    if doc_ids:
        with connect() as conn:
            marks = ",".join("?" for _ in doc_ids)
            for r in conn.execute(
                f"SELECT id, file_name, subject, grade FROM source_documents WHERE id IN ({marks})",
                tuple(doc_ids),
            ):
                sources.append(f"{r['subject']} {r['grade']} ({r['file_name']})")

    return {
        "id": doc["id"],
        "type": doc["type"],
        "typeLabel": template.get("title", "Scheme of Work"),
        "title": doc["title"],
        "grade": doc["grade"],
        "subject": doc["subject"],
        "term": doc["term"],
        "templateVersion": doc["template_version"],
        "status": doc["status"],
        "aiExpanded": bool(doc["ai_expanded"]),
        "dirty": bool(doc["dirty"]) if "dirty" in doc.keys() else False,
        "finalVersionLabel": (
            doc["final_version_label"] if "final_version_label" in doc.keys() else None
        ),
        "createdAt": doc["created_at"],
        "updatedAt": doc["updated_at"],
        "sourceChunkIds": json.loads(doc["source_chunk_ids"] or "[]"),
        "sectionCount": len(built),
        # Template-driven presentation:
        "columns": template.get("columns", []),
        "headerFields": template.get("header", {}).get("fields", []),
        "footer": template.get("footer", {}),
        "landscape": bool(template.get("landscape")),
        # Scheme data:
        "header": header,
        "allocation": allocation,
        "sources": sources,
        "sections": built,
        "tree": _tree(built),
    }


def _tree(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for s in sections:
        key = f"{s['strandCode']}|{s['strand']}"
        g = groups.get(key)
        if g is None:
            g = {
                "strandCode": s["strandCode"],
                "strand": s["strand"] or "Unassigned strand",
                "sections": [],
            }
            groups[key] = g
        g["sections"].append(s)

    def order(g: dict[str, Any]) -> tuple:
        nums = [int(p) for p in re.findall(r"\d+", g.get("strandCode") or "")]
        return (nums or [999], g["strand"])

    tree = sorted(groups.values(), key=order)
    for g in tree:
        g["sectionCount"] = len(g["sections"])
    return tree


def _row_to_section(
    row: Any, citations: list[dict[str, Any]], template: dict[str, Any]
) -> dict[str, Any]:
    def as_list(v: Any) -> list[str]:
        try:
            out = json.loads(v or "[]")
        except Exception:
            return []
        return [str(x) for x in out] if isinstance(out, list) else []

    keys = {c["key"]: c for c in template.get("columns", [])}

    def fallback(key: str) -> str:
        return (keys.get(key) or {}).get("fallback") or NOT_IN_SOURCE

    resources = row["resources"]
    assessment = row["assessment"]
    reflection = row["reflection"]
    original = json.loads(row["original"] or "{}")

    def full_from_source(value: Any, source_key: str) -> list[str]:
        """Expand legacy cross-reference cells using this row's own source snapshot.

        Older schemes stored "— See Week 1" instead of repeating a KIQ.  The
        full source list is still kept in `original`; nothing is written back
        to the database or to the SourceChunk, this only affects rendering.
        """
        current = as_list(value)
        stale = ("see week", "see above", "— do —", "- do -", "ditto")
        if current and not any(m in str(v).lower() for m in stale for v in current):
            return current
        source = [
            str(x).strip() for x in (original.get(source_key) or [])
            if str(x).strip() and not any(m in str(x).lower() for m in stale)
        ]
        return [" ".join(source)] if source else current

    return {
        "id": row["id"],
        "planId": row["plan_id"],
        "ord": row["ord"],
        "strandCode": row["strand_code"],
        "strand": row["strand"],
        "subStrandCode": row["sub_strand_code"],
        "subStrand": row["sub_strand"],
        # Allocation - ONE week per row, single integer, lessons restart each week.
        "week": row["week_start"],
        "weekLabel": _week_label({"week": row["week_start"]}),
        "lessonStart": row["lesson_start"],
        "lessonEnd": row["lesson_end"],
        "lessonCount": row["lesson_count"],
        "lessonLabel": _range(row["lesson_start"], row["lesson_end"]),
        "partLabel": original.get("partLabel"),
        "outcomePartLabel": original.get("outcomePartLabel"),
        "weekCount": original.get("weekCount"),
        "flags": json.loads(row["flags"] or "[]"),
        # Verbatim from source
        "outcomes": full_from_source(row["outcomes"], "outcomes"),
        "experiences": full_from_source(row["experiences"], "experiences"),
        "kiqs": full_from_source(row["kiqs"], "kiqs"),
        "competencies": row["competencies"],
        "valuesText": row["values_text"],
        "pcis": row["pcis"],
        "linkOther": row["link_other"],
        # Fallback-driven, never blocking
        "resources": {
            "text": resources if resources else fallback("resources"),
            "fromSource": bool(resources),
            "placeholder": not bool(resources),
            # True when the value came from the appendix rather than the sub-strand table.
            "fromAppendix": bool(original.get("appendixResources"))
            and resources == original.get("appendixResources"),
        },
        "assessment": {
            "text": assessment if assessment else fallback("assessment"),
            "fromSource": bool(assessment),
            "placeholder": not bool(assessment),
            "fromAppendix": bool(original.get("appendixAssessment"))
            and assessment == original.get("appendixAssessment"),
        },
        # Phase 3.5 appendix provenance for the pill, tooltip and [Reset to Appendix].
        "appendix": {
            "resources": original.get("appendixResources"),
            "assessment": original.get("appendixAssessment"),
            "source": original.get("appendixSource"),
            "level": original.get("appendixLevel"),
        },
        # Always empty on generation, never AI-filled
        "reflection": {
            "text": reflection or "",
            "placeholder": (keys.get("reflection") or {}).get(
                "placeholder", "To be filled after lesson"
            ),
            "fromSource": False,
        },
        "edited": bool(row["edited"]),
        "original": json.loads(row["original"] or "{}"),
        "citations": citations,
    }


def _range(a: Any, b: Any) -> str:
    if a is None and b is None:
        return ""
    if a is None:
        return str(b)
    if b is None or a == b:
        return str(a)
    return f"{a}-{b}"


def list_plans() -> dict[str, Any]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM plan_documents WHERE owner_id = ? "
            "ORDER BY datetime(created_at) DESC, created_at DESC",
            (current_owner_id(),),
        ).fetchall()
        out = []
        for r in rows:
            n = conn.execute(
                "SELECT COUNT(*) c FROM plan_sections WHERE plan_id = ?", (r["id"],)
            ).fetchone()["c"]
            alloc = json.loads(r["allocation"] or "{}")
            out.append(
                {
                    "id": r["id"],
                    "type": r["type"],
                    "title": r["title"],
                    "grade": r["grade"],
                    "subject": r["subject"],
                    "term": r["term"],
                    "status": r["status"],
                    "templateVersion": r["template_version"],
                    "createdAt": r["created_at"],
                    "sectionCount": n,
                    "totalLessons": alloc.get("totalLessons"),
                    "warning": alloc.get("warning"),
                }
            )
    return {"plans": out, "count": len(out)}


def delete_plan(plan_id: str) -> bool:
    with connect() as conn:
        row = conn.execute("SELECT id FROM plan_documents WHERE id = ?", (plan_id,)).fetchone()
        if row is None:
            return False
        conn.execute("DELETE FROM plan_citations WHERE plan_id = ?", (plan_id,))
        conn.execute("DELETE FROM plan_sections WHERE plan_id = ?", (plan_id,))
        conn.execute("DELETE FROM plan_documents WHERE id = ?", (plan_id,))
    return True


def set_plan_status(plan_id: str, status: str) -> tuple[dict[str, Any] | None, list[str]]:
    if status not in ("Draft", "Final", "Archived"):
        return None, [f"Unknown status '{status}'."]
    plan = get_plan(plan_id)
    if plan is None:
        return None, ["Plan not found."]
    if plan["status"] == STATUS_FINAL and status not in ("Final", "Archived"):
        return None, ["This scheme is Final. Press [Unlock to Edit] first."]
    if status == "Final":
        errors = validate_plan(plan)
        if errors:
            return None, errors
        label = f"Final - {plan.get('term') or 'Term'}"
        with connect() as conn:
            conn.execute(
                "UPDATE plan_documents SET status = ?, final_version_label = ?, dirty = 0, updated_at = ? WHERE id = ?",
                (status, label, _now(), plan_id),
            )
        create_plan_version(plan_id, label, kind="final", label=label)
        return get_plan(plan_id), []
    with connect() as conn:
        conn.execute(
            "UPDATE plan_documents SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), plan_id),
        )
    return get_plan(plan_id), []


def duplicate_plan(
    plan_id: str, term: str | None = None, year: str | None = None
) -> tuple[dict[str, Any] | None, list[str]]:
    """Duplicate for the next term: same rows, same allocation, teacher cells cleared."""
    with connect() as conn:
        doc = conn.execute("SELECT * FROM plan_documents WHERE id = ?", (plan_id,)).fetchone()
        if doc is None:
            return None, ["Plan not found."]
        sections = conn.execute(
            "SELECT * FROM plan_sections WHERE plan_id = ? ORDER BY ord", (plan_id,)
        ).fetchall()
        cites = conn.execute("SELECT * FROM plan_citations WHERE plan_id = ?", (plan_id,)).fetchall()

        new_plan_id = new_id()
        new_term = (term or "").strip() or _next_term(doc["term"] or "")
        header = json.loads(doc["header"] or "{}")
        header["term"] = new_term
        if year:
            header["year"] = str(year)
        allocation = json.loads(doc["allocation"] or "{}")

        title = doc["title"]
        if doc["term"]:
            title = title.replace(doc["term"], new_term)
        if year and doc["term"] is None:
            title = f"{title} {year}"

        conn.execute(
            """INSERT INTO plan_documents
               (id, type, title, grade, subject, term, template_version, status,
                source_chunk_ids, ai_expanded, header, allocation, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                new_plan_id,
                doc["type"],
                title,
                doc["grade"],
                doc["subject"],
                new_term,
                doc["template_version"],
                "Draft",
                doc["source_chunk_ids"],
                doc["ai_expanded"],
                json.dumps(header, ensure_ascii=False),
                json.dumps(allocation, ensure_ascii=False),
                _now(),
                _now(),
            ),
        )

        id_map: dict[str, str] = {}
        for s in sections:
            new_sid = new_id()
            id_map[s["id"]] = new_sid
            conn.execute(
                """INSERT INTO plan_sections
                   (id, plan_id, ord, strand_code, strand, sub_strand, sub_strand_code,
                    outcomes, experiences, kiqs, competencies, values_text, pcis, link_other,
                    resources, assessment, reflection, edited, original,
                    week_start, week_end, lesson_start, lesson_end, lesson_count, flags, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    new_sid,
                    new_plan_id,
                    s["ord"],
                    s["strand_code"],
                    s["strand"],
                    s["sub_strand"],
                    s["sub_strand_code"],
                    s["outcomes"],
                    s["experiences"],
                    s["kiqs"],
                    s["competencies"],
                    s["values_text"],
                    s["pcis"],
                    s["link_other"],
                    # Teacher cells start clean in the new term.
                    None,
                    None,
                    None,
                    s["edited"],
                    s["original"],
                    s["week_start"],
                    s["week_end"],
                    s["lesson_start"],
                    s["lesson_end"],
                    s["lesson_count"],
                    s["flags"],
                    _now(),
                ),
            )
        for c in cites:
            conn.execute(
                """INSERT INTO plan_citations
                   (id, plan_id, section_id, chunk_id, page_number, field, document_id, sub_strand_code)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    new_id(),
                    new_plan_id,
                    id_map.get(c["section_id"], c["section_id"]),
                    c["chunk_id"],
                    c["page_number"],
                    c["field"],
                    c["document_id"],
                    c["sub_strand_code"],
                ),
            )
    create_plan_version(new_plan_id, f"Duplicated from {doc['title']}", kind="initial")
    return get_plan(new_plan_id), []


def _next_term(term: str) -> str:
    m = re.search(r"(\d+)", term or "")
    if not m:
        return "Term 1"
    return f"Term {(int(m.group(1)) % 3) + 1}"


# ---------------------------------------------------------------------------
# Editing (header + per-row)
# ---------------------------------------------------------------------------

SECTION_FIELDS = {
    "outcomes": "outcomes",
    "experiences": "experiences",
    "kiqs": "kiqs",
    "resources": "resources",
    "assessment": "assessment",
    "reflection": "reflection",
    "week": "week_start",
    "weekStart": "week_start",
    "weekEnd": "week_end",
    "lessonStart": "lesson_start",
    "lessonEnd": "lesson_end",
    "lessonCount": "lesson_count",
}

HEADER_FIELDS = ("institution", "term", "year", "teacherName", "tscNo", "generalOutcomes")

CORE_FIELD_LABELS = {
    "outcomes": "Outcomes",
    "experiences": "Experiences",
    "kiqs": "Key Inquiry Questions",
}

STATUS_FINAL = "Final"


def _as_items(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x) for x in value]
    return [ln.strip() for ln in str(value or "").splitlines() if ln.strip()]


def _plan_row(conn: Any, plan_id: str) -> Any:
    return conn.execute("SELECT * FROM plan_documents WHERE id = ?", (plan_id,)).fetchone()


def _mark_dirty(conn: Any, plan_id: str) -> None:
    conn.execute(
        "UPDATE plan_documents SET dirty = 1, updated_at = ? WHERE id = ?", (_now(), plan_id)
    )


def _set_dirty_after_commit(plan_id: str) -> None:
    with connect() as conn:
        _mark_dirty(conn, plan_id)


def _log_edit(
    conn: Any,
    plan_id: str,
    section_id: str | None,
    field: str,
    prev_value: Any,
    prev_edited: int = 0,
) -> None:
    conn.execute(
        """INSERT INTO plan_edits
           (id, plan_id, section_id, field, prev_value, prev_edited, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (
            new_id(),
            plan_id,
            section_id,
            field,
            json.dumps(prev_value, ensure_ascii=False),
            int(prev_edited),
            _now(),
        ),
    )


def validate_section_values(
    row: Any, updates: dict[str, Any], lessons_per_week: int
) -> list[str]:
    """The Phase 4 save rules, applied on every edit and again on Save Version."""
    errors: list[str] = []
    week = updates.get("week_start", row["week_start"])
    try:
        week_int = int(week)
    except (TypeError, ValueError):
        week_int = -1
    if week_int < 1 or week_int > 13:
        errors.append("Week must be a whole number from 1 to 13.")

    start = updates.get("lesson_start", row["lesson_start"])
    end = updates.get("lesson_end", row["lesson_end"])
    if "lesson_start" in updates or "lesson_end" in updates:
        try:
            s = int(start)
            e = int(end if end is not None else start)
        except (TypeError, ValueError):
            errors.append(f'Lesson must match "1-{lessons_per_week}".')
        else:
            max_end = max(lessons_per_week, int(row["lesson_end"] or 0))
            if s < 1 or e < s or e > max_end:
                errors.append(f'Lesson must match "1-{lessons_per_week}".')

    for key, label in CORE_FIELD_LABELS.items():
        if key not in updates:
            continue
        try:
            items = json.loads(updates[key]) if isinstance(updates[key], str) else updates[key]
        except Exception:
            items = []
        if not [x for x in (items or []) if str(x).strip()]:
            errors.append(
                f"Week {week_int if week_int > 0 else '?'} {label} cannot be empty - "
                "this was Vetted from source. Restore from source or unselect row."
            )
    return errors


def validate_plan(plan: dict[str, Any]) -> list[str]:
    """Whole-plan validation used by [Save Version] and [Mark Final]."""
    errors: list[str] = []
    lessons_per_week = int((plan.get("allocation") or {}).get("lessonsPerWeek") or 5)
    for s in plan.get("sections") or []:
        week = s.get("week")
        if not isinstance(week, int) or week < 1 or week > 13:
            errors.append(f"Week {week!r} must be a whole number from 1 to 13.")
        start, end = s.get("lessonStart"), s.get("lessonEnd")
        if start is None or end is None or int(start) < 1 or int(end) < int(start):
            errors.append(f'Week {week} Lesson must match "1-{lessons_per_week}".')
        for key, label in CORE_FIELD_LABELS.items():
            if not [x for x in (s.get(key) or []) if str(x).strip()]:
                errors.append(
                    f"Week {week} {label} cannot be empty - this was Vetted from source. "
                    "Restore from source or unselect row."
                )
    return errors


def edit_section(
    plan_id: str, section_id: str, patch: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[str]]:
    """Teacher edit. Marks the row Teacher Edited, the plan Dirty, and keeps an undo entry."""
    with connect() as conn:
        doc = _plan_row(conn, plan_id)
        if doc is None:
            return None, ["Plan not found."]
        if doc["status"] == STATUS_FINAL:
            return None, ["This scheme is Final. Press [Unlock to Edit] first."]
        row = conn.execute(
            "SELECT * FROM plan_sections WHERE id = ? AND plan_id = ?", (section_id, plan_id)
        ).fetchone()
        if row is None:
            return None, ["Section not found."]

        updates: dict[str, Any] = {}
        for key, col in SECTION_FIELDS.items():
            if key not in patch:
                continue
            val = patch[key]
            if key in ("outcomes", "experiences", "kiqs"):
                updates[col] = json.dumps(_as_items(val), ensure_ascii=False)
            elif key == "week":
                try:
                    w = int(val)
                except (TypeError, ValueError):
                    return None, ["Week must be a whole number from 1 to 13."]
                updates["week_start"] = w
                updates["week_end"] = w
            elif key in ("weekStart", "weekEnd", "lessonStart", "lessonEnd", "lessonCount"):
                try:
                    updates[col] = int(val) if val not in (None, "") else None
                except (TypeError, ValueError):
                    return None, [f"{key} must be a number."]
            else:
                updates[col] = None if val is None else str(val)

        # The Lesson cell edits the whole range ("1-5"), not two separate numbers.
        if "lesson" in patch:
            raw = str(patch.get("lesson") or "").strip()
            m = re.fullmatch(r"(\d+)\s*(?:-\s*(\d+))?", raw)
            if not m:
                return None, ['Lesson must match "1-5".']
            s = int(m.group(1))
            e = int(m.group(2) or s)
            updates["lesson_start"] = s
            updates["lesson_end"] = e

        if not updates:
            return get_plan(plan_id), []

        lessons_per_week = int(
            (json.loads(doc["allocation"] or "{}") or {}).get("lessonsPerWeek") or 5
        )
        errors = validate_section_values(row, updates, lessons_per_week)
        if errors:
            return None, errors

        # Remember the previous values for [↩ Undo Last Edit].
        for col in {c for c in updates if c != "edited"}:
            prev = row[col]
            try:
                prev_val = json.loads(prev) if isinstance(prev, str) and prev.startswith("[") else prev
            except Exception:
                prev_val = prev
            _log_edit(conn, plan_id, section_id, col, prev_val, int(row["edited"] or 0))

        updates["edited"] = 1
        sets = ", ".join(f"{c} = ?" for c in updates)
        conn.execute(
            f"UPDATE plan_sections SET {sets} WHERE id = ? AND plan_id = ?",
            (*updates.values(), section_id, plan_id),
        )
        _mark_dirty(conn, plan_id)
    return get_plan(plan_id), []


def rebalance_group(
    plan_id: str, sub_strand_code: str, lessons_per_week: int | None = None
) -> tuple[dict[str, Any] | None, list[str]]:
    """[Re-balance Outcomes] for one sub-strand's weekly rows.

    Re-runs the same split algorithm over the sub-strand's FULL original source lists, so
    teacher edits are re-distributed rather than lost. Optionally re-splits the weeks when the
    teacher changed lessons per week.
    """
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM plan_sections WHERE plan_id = ? AND sub_strand_code = ? ORDER BY ord",
            (plan_id, sub_strand_code),
        ).fetchall()
        if not rows:
            return None, [f"Sub-strand {sub_strand_code} not found in this plan."]

        first = rows[0]
        # The pace the group was built at lives in `original`, not in lesson_count (which is
        # the sub-strand's TOTAL lessons, e.g. 20).
        stored = json.loads(first["original"] or "{}")
        current_pace = stored.get("lessonsPerWeek")
        if lessons_per_week and lessons_per_week > 0 and lessons_per_week != current_pace:
            # Rebuild the whole group with the new pace, keeping the first row's week number.
            chunk = {
                "id": first["id"],
                "documentId": None,
                "pageNumber": None,
                "strand": first["strand"],
                "strandCode": first["strand_code"],
                "subStrand": first["sub_strand"],
                "subStrandCode": first["sub_strand_code"],
                # lesson_count is the sub-strand's TOTAL lesson count (e.g. 20), not the
                # lessons each week.
                "lessons": first["lesson_count"],
                "structured": {
                    "specific_learning_outcomes": json.loads(first["original"] or "{}").get(
                        "outcomes", []
                    ),
                    "suggested_learning_experiences": json.loads(first["original"] or "{}").get(
                        "experiences", []
                    ),
                    "key_inquiry_questions": json.loads(first["original"] or "{}").get("kiqs", []),
                },
                # Phase 3.5: keep the appendix autofill values across a re-balance.
                "appendixResources": stored.get("appendixResources"),
                "appendixAssessment": stored.get("appendixAssessment"),
                "appendixSource": stored.get("appendixSource"),
                "appendixLevel": stored.get("appendixLevel"),
                "rubric": stored.get("rubric") or [],
            }
            new_rows = build_weekly_rows(chunk, lessons_per_week, first["week_start"] or 1)
            conn.execute(
                "DELETE FROM plan_sections WHERE plan_id = ? AND sub_strand_code = ?",
                (plan_id, sub_strand_code),
            )
            conn.execute(
                "DELETE FROM plan_citations WHERE plan_id = ? AND sub_strand_code = ?",
                (plan_id, sub_strand_code),
            )
            base_ord = first["ord"]
            for i, r in enumerate(new_rows):
                original = {
                    "outcomes": chunk["structured"]["specific_learning_outcomes"],
                    "experiences": chunk["structured"]["suggested_learning_experiences"],
                    "kiqs": chunk["structured"]["key_inquiry_questions"],
                    "week": r["week"],
                    "lessonStart": r["lessonStart"],
                    "lessonEnd": r["lessonEnd"],
                    "lessonCount": r["lessonCount"],
                    "lessonsPerWeek": r.get("lessonsPerWeek"),
                    "appendixResources": r.get("appendixResources"),
                    "appendixAssessment": r.get("appendixAssessment"),
                    "appendixSource": r.get("appendixSource"),
                    "appendixLevel": r.get("appendixLevel"),
                    "partLabel": r["partLabel"],
                    "outcomePartLabel": r.get("outcomePartLabel"),
                    "weekCount": r["weekCount"],
                    "resources": first["resources"],
                    "assessment": first["assessment"],
                    # Phase 4: the row's own slice + rubric for derivation/reset.
                    "sourceOutcomes": r["outcomes"],
                    "sourceExperiences": r["experiences"],
                    "sourceKiqs": r["kiqs"],
                    "rubric": r.get("rubric") or [],
                }
                conn.execute(
                    """INSERT INTO plan_sections
                       (id, plan_id, ord, strand_code, strand, sub_strand, sub_strand_code,
                        outcomes, experiences, kiqs, competencies, values_text, pcis, link_other,
                        resources, assessment, reflection, edited, original,
                        week_start, week_end, lesson_start, lesson_end, lesson_count, flags, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        new_id(), plan_id, base_ord + i, r["strandCode"], r["strand"],
                        r["subStrand"], r["subStrandCode"],
                        json.dumps(r["outcomes"], ensure_ascii=False),
                        json.dumps(r["experiences"], ensure_ascii=False),
                        json.dumps(r["kiqs"], ensure_ascii=False),
                        None, None, None, None,
                        # Resources/Assessment are the sub-strand's per RULE 3; Reflection is
                        # NEVER carried over - it is a per-lesson teacher cell.
                        first["resources"], first["assessment"], None,
                        0, json.dumps(original, ensure_ascii=False),
                        r["week"], r["week"], r["lessonStart"], r["lessonEnd"],
                        r["lessonCount"], json.dumps(r["flags"], ensure_ascii=False), _now(),
                    ),
                )
        else:
            # Same weeks, re-deal the content from the original lists.
            sections = [
                {
                    "outcomes": json.loads(r["outcomes"] or "[]"),
                    "experiences": json.loads(r["experiences"] or "[]"),
                    "kiqs": json.loads(r["kiqs"] or "[]"),
                    "original": json.loads(r["original"] or "{}"),
                    "edited": bool(r["edited"]),
                }
                for r in rows
            ]
            balanced = rebalance_outcomes(sections)
            for r, b in zip(rows, balanced):
                # Keep the stored part labels in step with the fresh split (tooltip source).
                original = json.loads(r["original"] or "{}")
                original["outcomePartLabel"] = b.get("outcomePartLabel")
                original["sourceOutcomes"] = b["outcomes"]
                original["sourceExperiences"] = b["experiences"]
                original["sourceKiqs"] = b["kiqs"]
                conn.execute(
                    """UPDATE plan_sections
                       SET outcomes = ?, experiences = ?, kiqs = ?, edited = ?, original = ?
                       WHERE id = ?""",
                    (
                        json.dumps(b["outcomes"], ensure_ascii=False),
                        json.dumps(b["experiences"], ensure_ascii=False),
                        json.dumps(b["kiqs"], ensure_ascii=False),
                        1 if b["edited"] else 0,
                        json.dumps(original, ensure_ascii=False),
                        r["id"],
                    ),
                )
        conn.execute("UPDATE plan_documents SET updated_at = ? WHERE id = ?", (_now(), plan_id))

    _set_dirty_after_commit(plan_id)
    return get_plan(plan_id), []


def reset_section_to_appendix(
    plan_id: str, section_id: str, field: str
) -> tuple[dict[str, Any] | None, list[str]]:
    """[Reset to Appendix] - restore one cell from its stored appendix value.

    Affects ONLY this weekly row. When the chunk had no appendix match the cell falls back to
    the template default rather than inventing anything.
    """
    if field not in ("resources", "assessment"):
        return None, ["Only resources and assessment can be reset to the appendix."]
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM plan_sections WHERE id = ? AND plan_id = ?", (section_id, plan_id)
        ).fetchone()
        if row is None:
            return None, ["Section not found."]
        original = json.loads(row["original"] or "{}")
        key = "appendixResources" if field == "resources" else "appendixAssessment"
        value = original.get(key)
        _log_edit(conn, plan_id, section_id, field, row[field], int(row["edited"] or 0))
        conn.execute(
            f"UPDATE plan_sections SET {field} = ?, edited = 1 WHERE id = ? AND plan_id = ?",
            (None if value is None else str(value), section_id, plan_id),
        )
        _mark_dirty(conn, plan_id)
    return get_plan(plan_id), []


def _source_slice(row: Any) -> dict[str, list[str]]:
    """The row's own source values, with a fallback for plans created before Phase 4."""
    original = json.loads(row["original"] or "{}")
    if original.get("sourceOutcomes") is not None:
        return {
            "outcomes": [str(x) for x in original.get("sourceOutcomes") or []],
            "experiences": [str(x) for x in original.get("sourceExperiences") or []],
            "kiqs": [str(x) for x in original.get("sourceKiqs") or []],
        }
    # Older plans: rebuild this row's weekly slice from the sub-strand's original lists.
    try:
        chunk = {
            "id": row["id"],
            "lessons": row["lesson_count"],
            "strand": row["strand"],
            "strandCode": row["strand_code"],
            "subStrand": row["sub_strand"],
            "subStrandCode": row["sub_strand_code"],
            "structured": {
                "specific_learning_outcomes": original.get("outcomes") or [],
                "suggested_learning_experiences": original.get("experiences") or [],
                "key_inquiry_questions": original.get("kiqs") or [],
            },
        }
        pace = int(original.get("lessonsPerWeek") or 5)
        rows = build_weekly_rows(chunk, pace, int(row["week_start"] or 1))
        idx = max(0, int(row["week_start"] or 1) - int(rows[0]["week"] if rows else 1))
        picked = rows[idx] if idx < len(rows) else rows[-1]
        return {
            "outcomes": [str(x) for x in picked["outcomes"]],
            "experiences": [str(x) for x in picked["experiences"]],
            "kiqs": [str(x) for x in picked["kiqs"]],
        }
    except Exception:
        return {"outcomes": [], "experiences": [], "kiqs": []}


def reset_section_to_source(
    plan_id: str, section_id: str
) -> tuple[dict[str, Any] | None, list[str]]:
    """[Reset Row to Source] - restore the vetted curriculum cells for ONE row.

    Outcomes / Experiences / KIQs / Resources / Assessment go back to their source/appendix
    values. The teacher's Reflection is intentionally KEPT.
    """
    with connect() as conn:
        doc = _plan_row(conn, plan_id)
        if doc is None:
            return None, ["Plan not found."]
        if doc["status"] == STATUS_FINAL:
            return None, ["This scheme is Final. Press [Unlock to Edit] first."]
        row = conn.execute(
            "SELECT * FROM plan_sections WHERE id = ? AND plan_id = ?", (section_id, plan_id)
        ).fetchone()
        if row is None:
            return None, ["Section not found."]
        original = json.loads(row["original"] or "{}")
        source = _source_slice(row)
        resources = original.get("resources")
        assessment = original.get("assessment")
        updates = {
            "outcomes": json.dumps(source["outcomes"], ensure_ascii=False),
            "experiences": json.dumps(source["experiences"], ensure_ascii=False),
            "kiqs": json.dumps(source["kiqs"], ensure_ascii=False),
            "resources": resources,
            "assessment": assessment,
            "edited": 0,
            # reflection deliberately untouched
        }
        for col in ("outcomes", "experiences", "kiqs", "resources", "assessment"):
            prev = row[col]
            try:
                prev_val = (
                    json.loads(prev) if isinstance(prev, str) and prev.startswith("[") else prev
                )
            except Exception:
                prev_val = prev
            _log_edit(conn, plan_id, section_id, col, prev_val, int(row["edited"] or 0))
        sets = ", ".join(f"{c} = ?" for c in updates)
        conn.execute(
            f"UPDATE plan_sections SET {sets} WHERE id = ? AND plan_id = ?",
            (*updates.values(), section_id, plan_id),
        )
        _mark_dirty(conn, plan_id)
    return get_plan(plan_id), []


def bulk_resources(
    plan_id: str, sub_strand_code: str, value: str
) -> tuple[dict[str, Any] | None, list[str]]:
    """[Edit Resources for All Weeks] for one sub-strand."""
    if not sub_strand_code:
        return None, ["subStrandCode is required."]
    with connect() as conn:
        doc = _plan_row(conn, plan_id)
        if doc is None:
            return None, ["Plan not found."]
        if doc["status"] == STATUS_FINAL:
            return None, ["This scheme is Final. Press [Unlock to Edit] first."]
        rows = conn.execute(
            "SELECT * FROM plan_sections WHERE plan_id = ? AND sub_strand_code = ? ORDER BY ord",
            (plan_id, sub_strand_code),
        ).fetchall()
        if not rows:
            return None, [f"Sub-strand {sub_strand_code} not found in this plan."]
        for row in rows:
            _log_edit(
                conn, plan_id, row["id"], "resources", row["resources"], int(row["edited"] or 0)
            )
            conn.execute(
                "UPDATE plan_sections SET resources = ?, edited = 1 WHERE id = ?",
                (str(value or ""), row["id"]),
            )
        _mark_dirty(conn, plan_id)
    return get_plan(plan_id), []


def clear_reflections(plan_id: str) -> tuple[dict[str, Any] | None, list[str]]:
    """[Clear All Reflections] - clears every weekly row's teacher reflection."""
    with connect() as conn:
        doc = _plan_row(conn, plan_id)
        if doc is None:
            return None, ["Plan not found."]
        if doc["status"] == STATUS_FINAL:
            return None, ["This scheme is Final. Press [Unlock to Edit] first."]
        rows = conn.execute(
            "SELECT * FROM plan_sections WHERE plan_id = ?", (plan_id,)
        ).fetchall()
        for row in rows:
            if row["reflection"]:
                _log_edit(
                    conn, plan_id, row["id"], "reflection", row["reflection"],
                    int(row["edited"] or 0),
                )
                conn.execute(
                    "UPDATE plan_sections SET reflection = NULL WHERE id = ?", (row["id"],)
                )
        _mark_dirty(conn, plan_id)
    return get_plan(plan_id), []


_UNDO_COLUMNS = {
    "outcomes",
    "experiences",
    "kiqs",
    "resources",
    "assessment",
    "reflection",
    "week_start",
    "week_end",
    "lesson_start",
    "lesson_end",
    "lesson_count",
}


def undo_last_edit(plan_id: str) -> tuple[dict[str, Any] | None, list[str]]:
    """[↩ Undo Last Edit] - restore the previous value of the most recent cell/header edit."""
    with connect() as conn:
        doc = _plan_row(conn, plan_id)
        if doc is None:
            return None, ["Plan not found."]
        if doc["status"] == STATUS_FINAL:
            return None, ["This scheme is Final. Press [Unlock to Edit] first."]
        log = conn.execute(
            "SELECT * FROM plan_edits WHERE plan_id = ? ORDER BY datetime(created_at) DESC, rowid DESC LIMIT 1",
            (plan_id,),
        ).fetchone()
        if log is None:
            return get_plan(plan_id), []
        field = log["field"]
        prev = json.loads(log["prev_value"]) if log["prev_value"] is not None else None
        if field.startswith("header:"):
            header = json.loads(doc["header"] or "{}")
            header[field.split(":", 1)[1]] = prev
            conn.execute(
                "UPDATE plan_documents SET header = ? WHERE id = ?",
                (json.dumps(header, ensure_ascii=False), plan_id),
            )
        elif field in _UNDO_COLUMNS and log["section_id"]:
            value = (
                json.dumps(prev, ensure_ascii=False)
                if isinstance(prev, (list, dict))
                else prev
            )
            conn.execute(
                f"UPDATE plan_sections SET {field} = ?, edited = ? WHERE id = ? AND plan_id = ?",
                (value, int(log["prev_edited"] or 0), log["section_id"], plan_id),
            )
        conn.execute("DELETE FROM plan_edits WHERE id = ?", (log["id"],))
        _mark_dirty(conn, plan_id)
    return get_plan(plan_id), []


def extend_row_lessons(
    plan_id: str, section_id: str, count: int
) -> tuple[dict[str, Any] | None, list[str]]:
    """[Extend to N lessons] - widen ONE weekly row so no atomic skill spills next week."""
    try:
        count = int(count)
    except (TypeError, ValueError):
        return None, ["Lesson count must be a number."]
    if count < 1 or count > 13:
        return None, ["Lesson count must be between 1 and 13."]
    with connect() as conn:
        doc = _plan_row(conn, plan_id)
        if doc is None:
            return None, ["Plan not found."]
        if doc["status"] == STATUS_FINAL:
            return None, ["This scheme is Final. Press [Unlock to Edit] first."]
        row = conn.execute(
            "SELECT * FROM plan_sections WHERE id = ? AND plan_id = ?", (section_id, plan_id)
        ).fetchone()
        if row is None:
            return None, ["Section not found."]
        start = int(row["lesson_start"] or 1)
        _log_edit(conn, plan_id, section_id, "lesson_end", row["lesson_end"], int(row["edited"] or 0))
        conn.execute(
            "UPDATE plan_sections SET lesson_end = ?, edited = 1 WHERE id = ?",
            (start + count - 1, section_id),
        )
        _mark_dirty(conn, plan_id)
    return get_plan(plan_id), []


def edit_header(plan_id: str, patch: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    with connect() as conn:
        doc = conn.execute("SELECT * FROM plan_documents WHERE id = ?", (plan_id,)).fetchone()
        if doc is None:
            return None, ["Plan not found."]
        if doc["status"] == STATUS_FINAL:
            return None, ["This scheme is Final. Press [Unlock to Edit] first."]
        header = json.loads(doc["header"] or "{}")
        changed = False
        for key in HEADER_FIELDS:
            if key in patch:
                new_val = str(patch[key] or "")
                old_val = header.get(key, "")
                if new_val != old_val:
                    _log_edit(conn, plan_id, None, f"header:{key}", old_val)
                    changed = True
                header[key] = new_val
        conn.execute(
            "UPDATE plan_documents SET header = ?, updated_at = ? WHERE id = ?",
            (json.dumps(header, ensure_ascii=False), _now(), plan_id),
        )
        if changed:
            _mark_dirty(conn, plan_id)
    return get_plan(plan_id), []


# ---------------------------------------------------------------------------
# Version history (Phase 4)
# ---------------------------------------------------------------------------


def _next_version_number(conn: Any, plan_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(version_number), 0) n FROM plan_versions WHERE plan_id = ?",
        (plan_id,),
    ).fetchone()
    return int(row["n"] or 0) + 1


def _version_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "planId": row["plan_id"],
        "versionNumber": row["version_number"],
        "label": row["label"] or f"v{row['version_number']}",
        "comment": row["comment"],
        "kind": row["kind"],
        "createdAt": row["created_at"],
    }


def create_plan_version(
    plan_id: str,
    comment: str,
    kind: str = "version",
    label: str | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Snapshot the ENTIRE plan (header + sections + citations) as a NEW version.

    Versions are append-only: nothing is ever overwritten or deleted.
    """
    comment = (comment or "").strip()
    if not comment:
        return None, ["A comment is required, e.g. 'Fixed Week 3 outcomes'."]
    plan = get_plan(plan_id)
    if plan is None:
        return None, ["Plan not found."]
    snapshot = json.dumps(plan, ensure_ascii=False)
    with connect() as conn:
        doc = _plan_row(conn, plan_id)
        if doc is None:
            return None, ["Plan not found."]
        n = _next_version_number(conn, plan_id)
        version_id = new_id()
        final_label = label or f"v{n}"
        conn.execute(
            """INSERT INTO plan_versions
               (id, plan_id, version_number, label, comment, kind, snapshot_json, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (version_id, plan_id, n, final_label, comment, kind, snapshot, _now()),
        )
        if kind != "initial":
            conn.execute(
                "UPDATE plan_documents SET dirty = 0, updated_at = ? WHERE id = ?",
                (_now(), plan_id),
            )
        row = conn.execute("SELECT * FROM plan_versions WHERE id = ?", (version_id,)).fetchone()
    return _version_dict(row), []


def list_plan_versions(plan_id: str) -> dict[str, Any]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM plan_versions WHERE plan_id = ? ORDER BY version_number DESC",
            (plan_id,),
        ).fetchall()
    if not rows and get_plan(plan_id) is not None:
        # Plans generated before Phase 4 had no baseline. Give them v1 now so the first
        # [Save Version] is v2 and history can always be compared/restored.
        create_plan_version(plan_id, "Baseline snapshot", kind="initial")
        return list_plan_versions(plan_id)
    return {"versions": [_version_dict(r) for r in rows], "count": len(rows)}


def get_plan_version(plan_id: str, version_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM plan_versions WHERE id = ? AND plan_id = ?", (version_id, plan_id)
        ).fetchone()
    if row is None:
        return None
    return {**_version_dict(row), "snapshot": json.loads(row["snapshot_json"] or "{}")}


def _cell_value(section: dict[str, Any], field: str) -> str:
    if field == "week":
        return str(section.get("week") if section.get("week") is not None else "")
    if field == "lesson":
        return str(section.get("lessonLabel") or "")
    if field in ("outcomes", "experiences", "kiqs"):
        return "\n".join(str(x) for x in (section.get(field) or []))
    if field in ("resources", "assessment"):
        cell = section.get(field)
        return str(cell.get("text") if isinstance(cell, dict) else (cell or ""))
    if field == "reflection":
        cell = section.get("reflection")
        return str(cell.get("text") if isinstance(cell, dict) else (cell or ""))
    return str(section.get(field) or "")


SECTION_DIFF_FIELDS = (
    ("week", "Week"),
    ("lesson", "Lesson"),
    ("strand", "Strand"),
    ("subStrand", "Sub-Strand"),
    ("outcomes", "Specific Learning Outcomes"),
    ("experiences", "Learning Experiences"),
    ("kiqs", "Key Inquiry Question (KIQ)"),
    ("resources", "Learning Resources"),
    ("assessment", "Assessment"),
    ("reflection", "Reflection / Remarks"),
)


def _plan_cells(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cells: dict[str, dict[str, Any]] = {}
    order = 0
    for key, label in (
        ("institution", "Institution / School"),
        ("grade", "Grade"),
        ("learningArea", "Learning Area"),
        ("term", "Term"),
        ("year", "Year"),
        ("teacherName", "Teacher Name"),
        ("tscNo", "TSC No."),
        ("generalOutcomes", "General Term Outcomes"),
    ):
        order += 1
        cells[f"header|{key}"] = {
            "sectionId": None,
            "week": None,
            "field": key,
            "label": f"Header · {label}",
            "from": str((plan.get("header") or {}).get(key) or ""),
            "order": order,
        }
    for i, s in enumerate(plan.get("sections") or []):
        for field, label in SECTION_DIFF_FIELDS:
            order += 1
            cells[f'{s.get("id")}|{field}'] = {
                "sectionId": s.get("id"),
                "week": s.get("week"),
                "field": field,
                "label": label,
                "from": _cell_value(s, field),
                "order": order + i * 100,
            }
    return cells


def diff_plan_version(plan_id: str, version_id: str) -> dict[str, Any] | None:
    """Compare a saved version against the CURRENT plan (version -> current)."""
    version = get_plan_version(plan_id, version_id)
    if version is None:
        return None
    current = get_plan(plan_id)
    if current is None:
        return None
    old = _plan_cells(version["snapshot"])
    new = _plan_cells(current)
    diffs: list[dict[str, Any]] = []
    for key, cell in old.items():
        to_cell = new.get(key)
        to_val = to_cell["from"] if to_cell else ""
        from_val = cell["from"]
        if from_val == to_val:
            continue
        if not from_val and to_val:
            status = "added"
        elif from_val and not to_val:
            status = "removed"
        else:
            status = "changed"
        diffs.append(
            {
                "sectionId": cell["sectionId"],
                "week": cell["week"],
                "field": cell["field"],
                "label": cell["label"],
                "from": from_val,
                "to": to_val,
                "status": status,
                "order": cell["order"],
            }
        )
    # Fields that only exist in the current plan.
    for key, cell in new.items():
        if key in old:
            continue
        diffs.append(
            {
                "sectionId": cell["sectionId"],
                "week": cell["week"],
                "field": cell["field"],
                "label": cell["label"],
                "from": "",
                "to": cell["from"],
                "status": "added",
                "order": cell["order"],
            }
        )
    diffs.sort(key=lambda d: d["order"])
    for d in diffs:
        d.pop("order", None)
    return {
        "version": {k: v for k, v in version.items() if k != "snapshot"},
        "from": version["label"],
        "to": "Current",
        "cells": diffs,
        "summary": {
            "changed": sum(1 for d in diffs if d["status"] == "changed"),
            "added": sum(1 for d in diffs if d["status"] == "added"),
            "removed": sum(1 for d in diffs if d["status"] == "removed"),
        },
    }


def _apply_plan_snapshot(conn: Any, plan_id: str, snap: dict[str, Any]) -> None:
    conn.execute(
        """UPDATE plan_documents
           SET title = ?, grade = ?, subject = ?, term = ?, template_version = ?,
               source_chunk_ids = ?, header = ?, allocation = ?, dirty = 1, updated_at = ?
           WHERE id = ?""",
        (
            snap.get("title") or "Scheme of Work",
            snap.get("grade") or "",
            snap.get("subject") or "",
            snap.get("term") or "",
            snap.get("templateVersion") or DEFAULT_TEMPLATE,
            json.dumps(snap.get("sourceChunkIds") or [], ensure_ascii=False),
            json.dumps(snap.get("header") or {}, ensure_ascii=False),
            json.dumps(snap.get("allocation") or {}, ensure_ascii=False),
            _now(),
            plan_id,
        ),
    )
    conn.execute("DELETE FROM plan_citations WHERE plan_id = ?", (plan_id,))
    conn.execute("DELETE FROM plan_sections WHERE plan_id = ?", (plan_id,))
    for s in snap.get("sections") or []:
        res = s.get("resources") or {}
        ass = s.get("assessment") or {}
        ref = s.get("reflection") or {}
        conn.execute(
            """INSERT INTO plan_sections
               (id, plan_id, ord, strand_code, strand, sub_strand, sub_strand_code,
                outcomes, experiences, kiqs, competencies, values_text, pcis, link_other,
                resources, assessment, reflection, edited, original,
                week_start, week_end, lesson_start, lesson_end, lesson_count, flags, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                s.get("id") or new_id(),
                plan_id,
                int(s.get("ord") or 0),
                s.get("strandCode"),
                s.get("strand"),
                s.get("subStrand") or "",
                s.get("subStrandCode"),
                json.dumps(s.get("outcomes") or [], ensure_ascii=False),
                json.dumps(s.get("experiences") or [], ensure_ascii=False),
                json.dumps(s.get("kiqs") or [], ensure_ascii=False),
                s.get("competencies"),
                s.get("valuesText"),
                s.get("pcis"),
                s.get("linkOther"),
                res.get("text") if isinstance(res, dict) else s.get("resources"),
                ass.get("text") if isinstance(ass, dict) else s.get("assessment"),
                ref.get("text") if isinstance(ref, dict) else s.get("reflection"),
                1 if s.get("edited") else 0,
                json.dumps(s.get("original") or {}, ensure_ascii=False),
                s.get("week"),
                s.get("week"),
                s.get("lessonStart"),
                s.get("lessonEnd"),
                s.get("lessonCount"),
                json.dumps(s.get("flags") or [], ensure_ascii=False),
                _now(),
            ),
        )
        for c in s.get("citations") or []:
            conn.execute(
                """INSERT INTO plan_citations
                   (id, plan_id, section_id, chunk_id, page_number, field, document_id, sub_strand_code)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    new_id(),
                    plan_id,
                    s.get("id") or new_id(),
                    c.get("chunkId"),
                    c.get("pageNumber"),
                    c.get("field"),
                    c.get("documentId"),
                    c.get("subStrandCode"),
                ),
            )


def restore_plan_version(
    plan_id: str, version_id: str
) -> tuple[dict[str, Any] | None, list[str]]:
    """Restore a version's content into the working plan and create a NEW version.

    The restored version is never deleted or mutated; a fresh version number is appended.
    """
    with connect() as conn:
        doc = _plan_row(conn, plan_id)
        if doc is None:
            return None, ["Plan not found."]
        if doc["status"] == STATUS_FINAL:
            return None, ["This scheme is Final. Press [Unlock to Edit] first."]
        row = conn.execute(
            "SELECT * FROM plan_versions WHERE id = ? AND plan_id = ?", (version_id, plan_id)
        ).fetchone()
        if row is None:
            return None, ["Version not found."]
        snap = json.loads(row["snapshot_json"] or "{}")
        _apply_plan_snapshot(conn, plan_id, snap)
        source_number = row["version_number"]
    new_version, errors = create_plan_version(
        plan_id, f"Restored from v{source_number}", kind="restore"
    )
    if errors:
        return None, errors
    plan = get_plan(plan_id)
    return {**(plan or {}), "restoredVersion": new_version}, []


def unlock_plan(plan_id: str) -> tuple[dict[str, Any] | None, list[str]]:
    """[Unlock to Edit] - Final -> Draft, recorded as a new version."""
    with connect() as conn:
        doc = _plan_row(conn, plan_id)
        if doc is None:
            return None, ["Plan not found."]
        if doc["status"] != STATUS_FINAL:
            return get_plan(plan_id), []
        conn.execute(
            "UPDATE plan_documents SET status = 'Draft', dirty = 1, updated_at = ? WHERE id = ?",
            (_now(), plan_id),
        )
        n = _next_version_number(conn, plan_id)
    version, errors = create_plan_version(
        plan_id,
        "Unlocked from Final",
        kind="unlock",
        label=f"v{n} - Unlocked from Final",
    )
    if errors:
        return None, errors
    plan = get_plan(plan_id)
    return {**(plan or {}), "unlockedVersion": version}, []





def vetting_catalog(grade: str | None = None, subject: str | None = None) -> dict[str, Any]:
    """Chunks on the Create screen with vetting state. Only Vetted are selectable."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM source_documents WHERE owner_id = ? "
            "ORDER BY datetime(created_at) DESC, created_at DESC",
            (current_owner_id(),),
        ).fetchall()
        docs_out = []
        for row in rows:
            if grade and row["grade"] != grade:
                continue
            if subject and row["subject"] != subject:
                continue
            chunks = list_chunks(conn, row["id"])
            if not chunks:
                continue
            enriched = []
            for c in chunks:
                sf = c.get("structuredFields") or {}
                status = (
                    c.get("vettingStatus")
                    or ("Vetted" if _has(sf, "key_inquiry_questions") else "Pending")
                )
                missing = [CORE_VETTING_FIELDS[k] for k in CORE_VETTING_FIELDS if not _has(sf, k)]
                enriched.append(
                    {
                        **c,
                        "vettingStatus": status,
                        "missingCore": missing,
                        "selectable": status == VETTED,
                    }
                )
            vetted = sum(1 for c in enriched if c["selectable"])
            docs_out.append(
                {
                    "documentId": row["id"],
                    "fileName": row["file_name"],
                    "grade": row["grade"],
                    "subject": row["subject"],
                    "archetype": row["archetype"],
                    "status": row["status"],
                    "vettedCount": vetted,
                    "totalCount": len(enriched),
                    "allVetted": vetted == len(enriched) and len(enriched) > 0,
                    "chunks": enriched,
                }
            )
    return {"documents": docs_out}
