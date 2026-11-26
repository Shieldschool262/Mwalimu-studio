"""Phase 10 - My Learners, assessment records, progress and IEPs.

Everything here is private to the logged-in teacher. There is no school/class
ownership other than the teacher's own Workspace: every query is filtered by
``owner_id`` and every identifier arriving from a request is checked against the
current owner before any row is read or written.

Assessment is deliberately separate from the Record of Work: it never changes
coverage. A rubric is read-only source material from the KICD Design.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import date, timedelta
from typing import Any

from fastapi import HTTPException

import auth_service as auth
import db
from services.rubric_service import ensure_chunk_rubric

LEVELS = ("Not Assessed", "Below", "Approaching", "Meets", "Exceeds")
SCORE = {"Below": 1, "Approaching": 2, "Meets": 3, "Exceeds": 4}
SCORE_TO_LEVEL = {1: "Below", 2: "Approaching", 3: "Meets", 4: "Exceeds"}
SOURCES = ("Class Activity", "Oral", "Written Task", "Rubric p.15", "Observation")
STATUSES = ("Active", "Transferred", "Left")
IEP_STATUSES = ("Active", "Met Goal", "Review Needed", "Closed")
CSV_TEMPLATE = "firstName,lastName,admissionNo,gender,className\n"


def _json(value: Any, default: Any) -> Any:
    try:
        data = json.loads(value or "")
        return data if data is not None else default
    except (TypeError, ValueError):
        return default


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _today() -> str:
    return date.today().isoformat()


def _as_date(value: str, fallback: str = "") -> date | None:
    raw = _clean(value)[:10] or _clean(fallback)[:10]
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _learner_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"], "ownerId": row["owner_id"],
        "grade": row["grade"], "learningArea": row["learning_area"],
        "className": row["class_name"], "firstName": row["first_name"],
        "lastName": row["last_name"], "admissionNo": row["admission_no"],
        "gender": row["gender"], "status": row["status"],
        "name": f"{row['first_name']} {row['last_name']}".strip(),
        "createdAt": row["created_at"], "updatedAt": row["updated_at"],
    }


def _assessment_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"], "ownerId": row["owner_id"], "learnerId": row["learner_id"],
        "chunkId": row["chunk_id"], "schemeRowId": row["scheme_row_id"],
        "strand": row["strand"], "subStrand": row["sub_strand"],
        "focusKeyword": row["focus_keyword"], "week": int(row["week"] or 0),
        "lesson": int(row["lesson"] or 0), "level": row["level"],
        "evidence": row["evidence"], "date": row["date"], "source": row["source"],
        "createdAt": row["created_at"], "updatedAt": row["updated_at"],
    }


def _iep_dict(row: Any, reviews: list[dict[str, Any]] | None = None,
              learner: dict[str, Any] | None = None) -> dict[str, Any]:
    status = row["status"]
    due = bool(status == "Active" and row["review_date"]
               and _as_date(row["review_date"]) and _as_date(row["review_date"]) <= date.today())
    out = {
        "id": row["id"], "ownerId": row["owner_id"], "learnerId": row["learner_id"],
        "need": row["need"], "goal": row["goal"], "support": row["support"],
        "materials": row["materials"], "reviewDate": row["review_date"],
        "reviewWeek": int(row["review_week"] or 0), "status": status,
        "reviewNeeded": due, "aiEnriched": bool(row["ai_enriched"]),
        "reviews": reviews or [], "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }
    if learner is not None:
        out["learner"] = learner
    return out


def _assert_learner(learner_id: str) -> None:
    """403 when a learner belongs to a different teacher; 404 when missing."""
    owner = auth.owner_of_resource("learners", learner_id)
    if owner is None:
        raise HTTPException(404, "Learner not found")
    if owner != auth.current_owner_id():
        raise HTTPException(403, "Not your content")


def _assert_iep(iep_id: str) -> Any:
    owner = auth.owner_of_resource("ieps", iep_id)
    if owner is None:
        raise HTTPException(404, "IEP not found")
    if owner != auth.current_owner_id():
        raise HTTPException(403, "Not your content")
    with db.connect() as conn:
        return conn.execute("SELECT * FROM ieps WHERE id = ?", (iep_id,)).fetchone()


# ---------------------------------------------------------------------------
# My Learners
# ---------------------------------------------------------------------------
def list_learners(params: dict[str, Any]) -> dict[str, Any]:
    owner = auth.current_owner_id()
    where = ["owner_id = ?"]
    args: list[Any] = [owner]
    for key, column in (("grade", "grade"), ("learningArea", "learning_area"),
                        ("className", "class_name"), ("status", "status")):
        value = _clean(params.get(key))
        if value:
            where.append(f"{column} = ?")
            args.append(value)
    q = _clean(params.get("q"))
    if q:
        where.append("(LOWER(first_name || ' ' || last_name) LIKE ? OR admission_no LIKE ?)")
        args.extend([f"%{q.lower()}%", f"%{q}%"])
    sql = ("SELECT * FROM learners WHERE " + " AND ".join(where) +
           " ORDER BY grade, learning_area, class_name, last_name, first_name")
    with db.connect() as conn:
        rows = conn.execute(sql, tuple(args)).fetchall()
    items = [_learner_dict(r) for r in rows]
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for item in items:
        groups.setdefault((item["grade"], item["learningArea"], item["className"]), []).append(item)
    return {
        "learners": items,
        "count": len(items),
        "groups": [
            {"grade": g, "learningArea": a, "className": c, "learners": members,
             "count": len(members)}
            for (g, a, c), members in sorted(groups.items())
        ],
    }


def get_learner(learner_id: str) -> dict[str, Any]:
    _assert_learner(learner_id)
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM learners WHERE id = ?", (learner_id,)).fetchone()
    return _learner_dict(row)


def create_learner(body: dict[str, Any]) -> dict[str, Any]:
    owner = auth.current_owner_id()
    first, last = _clean(body.get("firstName")), _clean(body.get("lastName"))
    if not first or not last:
        raise HTTPException(422, "First Name and Last Name are required")
    admission = _clean(body.get("admissionNo"))
    class_name = _clean(body.get("className"))
    if admission and class_name:
        with db.connect() as conn:
            clash = conn.execute(
                "SELECT first_name || ' ' || last_name nm FROM learners "
                "WHERE owner_id = ? AND class_name = ? AND admission_no = ? AND status = 'Active'",
                (owner, class_name, admission),
            ).fetchone()
        if clash:
            raise HTTPException(
                409, f"Admission No {admission} already exists for {clash['nm']} in {class_name}")
    gender = _clean(body.get("gender")) or "Prefer not to say"
    status = _clean(body.get("status")) or "Active"
    if status not in STATUSES:
        raise HTTPException(422, "Invalid learner status")
    ident = db.new_id()
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO learners
               (id, owner_id, grade, learning_area, class_name, first_name, last_name,
                admission_no, gender, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ident, owner, _clean(body.get("grade")), _clean(body.get("learningArea")),
             class_name, first, last, admission, gender, status),
        )
    return get_learner(ident)


def update_learner(learner_id: str, body: dict[str, Any]) -> dict[str, Any]:
    _assert_learner(learner_id)
    allowed = {
        "grade": "grade", "learningArea": "learning_area", "className": "class_name",
        "firstName": "first_name", "lastName": "last_name", "admissionNo": "admission_no",
        "gender": "gender", "status": "status",
    }
    patches = {column: _clean(body[key]) for key, column in allowed.items() if key in body}
    if "status" in patches and patches["status"] not in STATUSES:
        raise HTTPException(422, "Invalid learner status")
    if not patches:
        return get_learner(learner_id)
    assignments = ", ".join(f"{column} = ?" for column in patches)
    with db.connect() as conn:
        conn.execute(
            f"UPDATE learners SET {assignments}, updated_at = datetime('now') WHERE id = ?",
            tuple(patches.values()) + (learner_id,),
        )
    return get_learner(learner_id)


def archive_learner(learner_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Archive keeps every assessment and IEP for history; only the class list hides it."""
    status = _clean(body.get("status")) or "Transferred"
    if status not in ("Transferred", "Left"):
        raise HTTPException(422, "Archive status must be Transferred or Left")
    return update_learner(learner_id, {"status": status})


def delete_learner(learner_id: str, confirmation: str) -> dict[str, Any]:
    learner = get_learner(learner_id)
    if _clean(confirmation).lower() != learner["name"].lower():
        raise HTTPException(422, f"Type {learner['name']} to confirm")
    with db.connect() as conn:
        conn.execute("DELETE FROM assessment_audit WHERE learner_id = ?", (learner_id,))
        conn.execute("DELETE FROM assessment_records WHERE learner_id = ?", (learner_id,))
        conn.execute("DELETE FROM iep_reviews WHERE iep_id IN (SELECT id FROM ieps WHERE learner_id = ?)", (learner_id,))
        conn.execute("DELETE FROM ieps WHERE learner_id = ?", (learner_id,))
        conn.execute("DELETE FROM learners WHERE id = ?", (learner_id,))
    return {"ok": True, "deleted": learner["name"]}


# ---------------------------------------------------------------------------
# CSV import (preview first, then confirm with duplicate resolutions)
# ---------------------------------------------------------------------------
def _parse_csv(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text or ""))
    if not reader.fieldnames:
        raise HTTPException(422, "CSV file is empty")
    normalized = {name.strip().lower(): name for name in reader.fieldnames if name}
    required = {"firstname", "lastname"}
    if not required.issubset(normalized):
        raise HTTPException(422, "CSV needs firstName and lastName columns")
    out = []
    for raw in reader:
        def get(key: str) -> str:
            column = normalized.get(key)
            return _clean(raw.get(column)) if column else ""
        if not get("firstname") and not get("lastname"):
            continue
        out.append({
            "firstName": get("firstname"), "lastName": get("lastname"),
            "admissionNo": get("admissionno"), "gender": get("gender") or "Prefer not to say",
            "className": get("classname"),
        })
    return out


def _duplicates(rows: list[dict[str, str]], grade: str, area: str) -> list[dict[str, Any]]:
    owner = auth.current_owner_id()
    found: list[dict[str, Any]] = []
    seen: dict[tuple[str, str], str] = {}
    with db.connect() as conn:
        for index, row in enumerate(rows):
            admission, class_name = row["admissionNo"], row["className"]
            if not admission:
                continue
            key = (class_name, admission)
            if key in seen:
                found.append({"rowIndex": index, "admissionNo": admission,
                              "existingName": seen[key], "source": "file"})
                continue
            existing = conn.execute(
                "SELECT first_name || ' ' || last_name nm FROM learners "
                "WHERE owner_id = ? AND class_name = ? AND admission_no = ? AND status = 'Active'",
                (owner, class_name, admission),
            ).fetchone()
            if existing:
                found.append({"rowIndex": index, "admissionNo": admission,
                              "existingName": existing["nm"], "source": "workspace"})
            seen[key] = f"{row['firstName']} {row['lastName']}".strip()
    return found


def csv_preview(body: dict[str, Any]) -> dict[str, Any]:
    rows = _parse_csv(_clean(body.get("csv")))
    grade, area = _clean(body.get("grade")), _clean(body.get("learningArea"))
    return {
        "rows": rows[:5], "total": len(rows),
        "duplicates": _duplicates(rows, grade, area),
        "previewOnly": True,
    }


def csv_import(body: dict[str, Any]) -> dict[str, Any]:
    rows = _parse_csv(_clean(body.get("csv")))
    grade, area = _clean(body.get("grade")), _clean(body.get("learningArea"))
    resolutions = body.get("resolutions") or {}
    owner = auth.current_owner_id()
    created, skipped, replaced = 0, 0, 0
    with db.connect() as conn:
        for index, row in enumerate(rows):
            admission, class_name = row["admissionNo"], row["className"]
            existing = None
            if admission:
                existing = conn.execute(
                    "SELECT * FROM learners WHERE owner_id = ? AND class_name = ? "
                    "AND admission_no = ? AND status = 'Active' LIMIT 1",
                    (owner, class_name, admission),
                ).fetchone()
            choice = _clean(resolutions.get(str(index)) or resolutions.get(index))
            if existing:
                if choice == "skip":
                    skipped += 1
                    continue
                if choice == "replace":
                    conn.execute(
                        "UPDATE learners SET first_name = ?, last_name = ?, gender = ?, "
                        "updated_at = datetime('now') WHERE id = ?",
                        (row["firstName"], row["lastName"], row["gender"], existing["id"]),
                    )
                    replaced += 1
                    continue
                # "keep" (default) deliberately allows two rows with the same admission no.
            conn.execute(
                """INSERT INTO learners
                   (id, owner_id, grade, learning_area, class_name, first_name, last_name,
                    admission_no, gender, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Active')""",
                (db.new_id(), owner, grade, area, class_name, row["firstName"],
                 row["lastName"], admission, row["gender"]),
            )
            created += 1
    return {"created": created, "skipped": skipped, "replaced": replaced,
            "message": f"Imported {created} learners ({skipped} skipped, {replaced} replaced)."}


# ---------------------------------------------------------------------------
# Assessment context + records
# ---------------------------------------------------------------------------
def assess_options(grade: str = "", learning_area: str = "") -> dict[str, Any]:
    """Sub-strands a teacher can choose when assessing from a Learner profile."""
    where = ["p.owner_id = ?"]
    args: list[Any] = [auth.current_owner_id()]
    if _clean(grade):
        where.append("p.grade = ?")
        args.append(_clean(grade))
    if _clean(learning_area):
        where.append("p.subject = ?")
        args.append(_clean(learning_area))
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT s.id, s.sub_strand, s.sub_strand_code, s.strand_code, "
            "s.outcomes, s.experiences, s.kiqs, p.grade, p.subject AS learning_area, p.term "
            "FROM plan_sections s JOIN plan_documents p ON p.id = s.plan_id "
            "WHERE " + " AND ".join(where) + " ORDER BY p.term, s.ord", tuple(args),
        ).fetchall()
    items = []
    for row in rows:
        missing = [label for field, label in
                   (("outcomes", "Outcomes"), ("experiences", "Experiences"), ("kiqs", "KIQs"))
                   if not _json(row[field], [])]
        items.append({
            "schemeRowId": row["id"], "subStrand": row["sub_strand"],
            "code": _clean(row["sub_strand_code"]) or _clean(row["strand_code"]) or "1.1",
            "grade": row["grade"], "learningArea": row["learning_area"], "term": row["term"],
            "canAssess": not missing,
            "reason": "" if not missing else f"Cannot assess: missing {', '.join(missing)}. Fix in Library.",
        })
    return {"options": items, "count": len(items)}


def assessment_context(scheme_row_id: str, week: int = 0, lesson: int = 0) -> dict[str, Any]:
    """Read-only context for an assessment grid: scheme row, rubric and vetting guard."""
    with db.connect() as conn:
        sec = conn.execute(
            """SELECT s.*, p.grade, p.subject AS learning_area, p.term
               FROM plan_sections s JOIN plan_documents p ON p.id = s.plan_id
               WHERE s.id = ?""", (scheme_row_id,),
        ).fetchone()
        if sec is None:
            raise HTTPException(404, "Scheme row not found")
        lp = None
        if week or lesson:
            lp = conn.execute(
                "SELECT * FROM lesson_plans WHERE section_id = ? AND week = ? AND lesson = ? LIMIT 1",
                (scheme_row_id, week, lesson),
            ).fetchone()
        if lp is None:
            lp = conn.execute(
                "SELECT * FROM lesson_plans WHERE section_id = ? ORDER BY week, lesson LIMIT 1",
                (scheme_row_id,),
            ).fetchone()
        chunk_id = _clean(lp["chunk_id"] if lp else "")
        if not chunk_id:
            citation = conn.execute(
                "SELECT chunk_id FROM plan_citations WHERE section_id = ? "
                "AND chunk_id != '' LIMIT 1", (scheme_row_id,),
            ).fetchone()
            chunk_id = _clean(citation["chunk_id"]) if citation else ""
        vetting = "Pending"
        if chunk_id:
            chunk = conn.execute(
                "SELECT vetting_status, page_number, document_id FROM source_chunks WHERE id = ?",
                (chunk_id,),
            ).fetchone()
            if chunk:
                vetting = _clean(chunk["vetting_status"]) or "Pending"
            else:
                chunk_id = ""

    missing: list[str] = []
    for field, label in (("outcomes", "Outcomes"), ("experiences", "Experiences"), ("kiqs", "KIQs")):
        if not _json(sec[field], []):
            missing.append(label)
    code = _clean(sec["sub_strand_code"]) or _clean(sec["strand_code"]) or "1.1"
    focus = _clean(lp["focus_keyword"] if lp else "") or \
        _clean(lp["focus"] if lp else "") or _clean(sec["sub_strand"])
    can_assess = not missing
    reason = "" if can_assess else f"Cannot assess: {code} is missing {', '.join(missing)}. Fix in Library."
    rubric = ensure_chunk_rubric(chunk_id) if chunk_id else []
    return {
        "schemeRowId": scheme_row_id, "week": int(week or (lp["week"] if lp else 0) or 0),
        "lesson": int(lesson or (lp["lesson"] if lp else 0) or 0),
        "grade": sec["grade"], "learningArea": sec["learning_area"], "term": sec["term"],
        "strand": sec["strand"] or "", "subStrand": sec["sub_strand"] or "",
        "focus": focus, "chunkId": chunk_id, "vettingStatus": vetting,
        "canAssess": can_assess, "reason": reason, "rubric": rubric,
        "pageNumber": rubric[0].get("page") if rubric else None,
    }


def save_assessment(body: dict[str, Any]) -> dict[str, Any]:
    scheme_row_id = _clean(body.get("schemeRowId"))
    if not scheme_row_id:
        raise HTTPException(422, "schemeRowId is required")
    context = assessment_context(scheme_row_id, int(body.get("week") or 0),
                                 int(body.get("lesson") or 0))
    if not context["canAssess"]:
        raise HTTPException(422, context["reason"])
    records = body.get("records") or []
    if not isinstance(records, list) or not records:
        raise HTTPException(422, "No assessment records supplied")
    week, lesson = context["week"], context["lesson"]
    label = f"Week {week} Lesson {lesson}" if week or lesson else "this lesson"
    owner = auth.current_owner_id()
    user = auth.get_user(owner) or {}
    changed_by = _clean(user.get("name")) or _clean(user.get("email")) or owner
    saved, skipped = 0, 0
    with db.connect() as conn:
        for record in records:
            learner_id = _clean(record.get("learnerId"))
            if not learner_id:
                continue
            _assert_learner(learner_id)
            level = _clean(record.get("level")) or "Not Assessed"
            if level not in LEVELS:
                raise HTTPException(422, f"Invalid level: {level}")
            evidence = _clean(record.get("evidence"))
            if level in ("Below", "Approaching") and not evidence:
                raise HTTPException(422, "Evidence required for Below/Approaching")
            learner = conn.execute(
                "SELECT status FROM learners WHERE id = ?", (learner_id,)
            ).fetchone()
            if not learner or learner["status"] != "Active":
                skipped += 1
                continue
            source = _clean(record.get("source")) or "Class Activity"
            if source not in SOURCES:
                raise HTTPException(422, f"Invalid source: {source}")
            ass_date = _clean(record.get("date")) or _today()
            existing = conn.execute(
                """SELECT * FROM assessment_records
                   WHERE learner_id = ? AND scheme_row_id = ? AND week = ? AND lesson = ?""",
                (learner_id, scheme_row_id, week, lesson),
            ).fetchone()
            old_level = existing["level"] if existing else "Not Assessed"
            if existing:
                conn.execute(
                    """UPDATE assessment_records SET evidence = ?, level = ?, date = ?, source = ?,
                       strand = ?, sub_strand = ?, focus_keyword = ?, chunk_id = ?,
                       updated_at = datetime('now') WHERE id = ?""",
                    (evidence, level, ass_date, source, context["strand"], context["subStrand"],
                     context["focus"], context["chunkId"], existing["id"]),
                )
                record_id = existing["id"]
            else:
                record_id = db.new_id()
                conn.execute(
                    """INSERT INTO assessment_records
                       (id, owner_id, learner_id, chunk_id, scheme_row_id, strand, sub_strand,
                        focus_keyword, week, lesson, level, evidence, date, source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (record_id, owner, learner_id, context["chunkId"], scheme_row_id,
                     context["strand"], context["subStrand"], context["focus"], week, lesson,
                     level, evidence, ass_date, source),
                )
            if old_level != level:
                conn.execute(
                    """INSERT INTO assessment_audit
                       (id, owner_id, learner_id, assessment_id, old_level, new_level,
                        changed_by, changed_at, reason)
                       VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)""",
                    (db.new_id(), owner, learner_id, record_id, old_level, level, changed_by,
                     evidence[:200]),
                )
            saved += 1
    return {"saved": saved, "skipped": skipped, "message": f"Saved: {saved} records for {label}"}


def list_assessments(params: dict[str, Any]) -> dict[str, Any]:
    where = ["owner_id = ?"]
    args: list[Any] = [auth.current_owner_id()]
    for key, column in (("learnerId", "learner_id"), ("chunkId", "chunk_id"), ("week", "week")):
        value = params.get(key)
        if value not in (None, "", 0):
            where.append(f"{column} = ?")
            args.append(value)
    sql = ("SELECT * FROM assessment_records WHERE " + " AND ".join(where) +
           " ORDER BY date, created_at, id")
    with db.connect() as conn:
        rows = conn.execute(sql, tuple(args)).fetchall()
    return {"records": [_assessment_dict(r) for r in rows], "count": len(rows)}


def get_assessment(assessment_id: str) -> dict[str, Any]:
    """Single assessment record, owner-filtered at both API and DB layers."""
    owner = auth.owner_of_resource("assessments", assessment_id)
    if owner is None:
        raise HTTPException(404, "Assessment not found")
    if owner != auth.current_owner_id():
        raise HTTPException(403, "Not your content")
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM assessment_records WHERE id = ? AND owner_id = ?",
            (assessment_id, owner),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Assessment not found")
    return _assessment_dict(row)


def assessment_audit(learner_id: str) -> dict[str, Any]:
    _assert_learner(learner_id)
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM assessment_audit WHERE owner_id = ? AND learner_id = ? "
            "ORDER BY changed_at DESC, id DESC", (auth.current_owner_id(), learner_id),
        ).fetchall()
    return {"history": [
        {"learnerId": r["learner_id"], "oldLevel": r["old_level"], "newLevel": r["new_level"],
         "changedBy": r["changed_by"], "changedAt": r["changed_at"], "reason": r["reason"]}
        for r in rows
    ]}


# ---------------------------------------------------------------------------
# Progress aggregation
# ---------------------------------------------------------------------------
def _trend(old: str, new: str) -> str:
    old_score, new_score = SCORE.get(old, 0), SCORE.get(new, 0)
    if not old_score:
        return "—"
    return "↑" if new_score > old_score else ("↓" if new_score < old_score else "→")


def _overall(items: list[dict[str, Any]]) -> str:
    """Overall = average of the most recent level per focus, mapped 1-4 then
    rounded DOWN to a level (Exceeds=4, Meets=3, Approaching=2, Below=1;
    Not Assessed is ignored). Rounding down avoids inflating a learner who has
    one strong focus beside one weak focus; the level is always shown as text,
    never as a decimal score."""
    scores = [SCORE[item["level"]] for item in items if item["level"] in SCORE]
    if not scores:
        return "Not Assessed"
    average = sum(scores) / len(scores)
    return SCORE_TO_LEVEL.get(max(1, min(4, int(average))), "Not Assessed")


def get_progress(params: dict[str, Any]) -> dict[str, Any]:
    owner = auth.current_owner_id()
    where = ["owner_id = ?"]
    args: list[Any] = [owner]
    for key, column in (("grade", "grade"), ("learningArea", "learning_area"),
                        ("className", "class_name")):
        value = _clean(params.get(key))
        if value:
            where.append(f"{column} = ?")
            args.append(value)
    status = _clean(params.get("status")) or "Active"
    if status != "all":
        where.append("status = ?")
        args.append(status)
    with db.connect() as conn:
        learners = [dict(r) for r in conn.execute(
            "SELECT * FROM learners WHERE " + " AND ".join(where) +
            " ORDER BY grade, learning_area, class_name, last_name, first_name", tuple(args),
        ).fetchall()]
        records = [dict(r) for r in conn.execute(
            "SELECT * FROM assessment_records WHERE owner_id = ? ORDER BY date, week, lesson, created_at, id",
            (owner,),
        ).fetchall()]

    by_learner: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_learner.setdefault(record["learner_id"], []).append(_assessment_dict(record))

    cutoff = date.today() - timedelta(days=14)
    summary = {level: 0 for level in LEVELS}
    result: list[dict[str, Any]] = []
    for learner in learners:
        items = by_learner.get(learner["id"], [])
        focus_map: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            focus_map.setdefault(item["focusKeyword"] or item["subStrand"] or "Focus", []).append(item)
        by_focus = []
        for focus, sequence in sorted(focus_map.items()):
            latest = sequence[-1]
            previous = sequence[-2] if len(sequence) > 1 else None
            by_focus.append({
                "focus": focus, "level": latest["level"], "date": latest["date"],
                "trend": _trend(previous["level"] if previous else "", latest["level"]),
                "evidence": latest["evidence"], "source": latest["source"],
                "week": latest["week"], "lesson": latest["lesson"],
                "history": [
                    {"level": x["level"], "date": x["date"], "evidence": x["evidence"],
                     "source": x["source"]} for x in sequence[::-1]
                ],
            })
        overall = _overall(by_focus)
        summary[overall] += 1
        recent = []
        for item in items:
            parsed = _as_date(item["date"], item["createdAt"])
            if parsed and parsed >= cutoff:
                recent.append(item)
        needs_support = (any(x["level"] == "Below" for x in recent) or
                         sum(1 for x in recent if x["level"] == "Approaching") >= 2)
        result.append({
            "learnerId": learner["id"],
            "name": f"{learner['first_name']} {learner['last_name']}".strip(),
            "grade": learner["grade"], "learningArea": learner["learning_area"],
            "className": learner["class_name"], "byFocus": by_focus,
            "overall": overall, "needsSupport": needs_support,
        })
    needs_support_learners = [x for x in result if x["needsSupport"]]
    return {
        "learners": result, "count": len(result), "classSummary": summary,
        "needsSupport": needs_support_learners,
        "needsSupportCount": len(needs_support_learners),
    }


# ---------------------------------------------------------------------------
# IEP / Individual Support Plan
# ---------------------------------------------------------------------------
def _review_week(review_date: str, owner: str) -> int:
    """Derive the review week from the teacher's own term dates where possible."""
    parsed = _as_date(review_date)
    if parsed is None:
        return 0
    with db.connect() as conn:
        row = conn.execute(
            """SELECT r.week FROM record_of_work_rows r
               JOIN plan_documents p ON p.id = r.plan_id
               WHERE p.owner_id = ? AND r.date = ? ORDER BY r.week DESC LIMIT 1""",
            (owner, parsed.isoformat()),
        ).fetchone()
    return int(row["week"]) if row else 0


def list_ieps(params: dict[str, Any]) -> dict[str, Any]:
    owner = auth.current_owner_id()
    where = ["i.owner_id = ?"]
    args: list[Any] = [owner]
    learner_id = _clean(params.get("learnerId"))
    if learner_id:
        _assert_learner(learner_id)
        where.append("i.learner_id = ?")
        args.append(learner_id)
    status = _clean(params.get("status"))
    if status and status != "all":
        if status not in IEP_STATUSES:
            raise HTTPException(422, "Invalid IEP status")
        where.append("i.status = ?")
        args.append(status)
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT i.* FROM ieps i WHERE " + " AND ".join(where) +
            " ORDER BY i.updated_at DESC, i.id", tuple(args),
        ).fetchall()
        items = []
        for row in rows:
            reviews = [{"date": r["date"], "note": r["note"], "newLevel": r["new_level"]}
                       for r in conn.execute(
                           "SELECT * FROM iep_reviews WHERE owner_id = ? AND iep_id = ? ORDER BY date, id",
                           (owner, row["id"]),
                       ).fetchall()]
            learner = conn.execute("SELECT * FROM learners WHERE id = ?", (row["learner_id"],)).fetchone()
            items.append(_iep_dict(row, reviews, _learner_dict(learner) if learner else None))
    return {"ieps": items, "count": len(items)}


def get_iep(iep_id: str) -> dict[str, Any]:
    row = _assert_iep(iep_id)
    with db.connect() as conn:
        reviews = [{"date": r["date"], "note": r["note"], "newLevel": r["new_level"]}
                   for r in conn.execute(
                       "SELECT * FROM iep_reviews WHERE owner_id = ? AND iep_id = ? ORDER BY date, id",
                       (auth.current_owner_id(), iep_id),
                   ).fetchall()]
        learner = conn.execute("SELECT * FROM learners WHERE id = ?", (row["learner_id"],)).fetchone()
    return _iep_dict(row, reviews, _learner_dict(learner) if learner else None)


def create_iep(body: dict[str, Any]) -> dict[str, Any]:
    learner_id = _clean(body.get("learnerId"))
    _assert_learner(learner_id)
    for field in ("need", "goal", "support", "reviewDate"):
        if not _clean(body.get(field)):
            raise HTTPException(422, f"{field} is required")
    owner = auth.current_owner_id()
    with db.connect() as conn:
        active = conn.execute(
            "SELECT id FROM ieps WHERE owner_id = ? AND learner_id = ? AND status = 'Active'",
            (owner, learner_id),
        ).fetchone()
        if active:
            raise HTTPException(422, "Close the active IEP before creating a new one")
    review_date = _clean(body.get("reviewDate"))
    ident = db.new_id()
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO ieps
               (id, owner_id, learner_id, need, goal, support, materials, review_date,
                review_week, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Active')""",
            (ident, owner, learner_id, _clean(body.get("need")), _clean(body.get("goal")),
             _clean(body.get("support")), _clean(body.get("materials")), review_date,
             int(body.get("reviewWeek") or 0) or _review_week(review_date, owner)),
        )
    return get_iep(ident)


def update_iep(iep_id: str, body: dict[str, Any]) -> dict[str, Any]:
    _assert_iep(iep_id)
    allowed = {
        "need": "need", "goal": "goal", "support": "support", "materials": "materials",
        "reviewDate": "review_date", "reviewWeek": "review_week", "status": "status",
        "aiEnriched": "ai_enriched",
    }
    patches: dict[str, Any] = {}
    for key, column in allowed.items():
        if key not in body:
            continue
        value = body[key]
        if column == "ai_enriched":
            patches[column] = 1 if value else 0
        elif column == "review_week":
            patches[column] = int(value or 0)
        else:
            patches[column] = _clean(value)
    if "status" in patches and patches["status"] not in IEP_STATUSES:
        raise HTTPException(422, "Invalid IEP status")
    if not patches:
        return get_iep(iep_id)
    assignments = ", ".join(f"{column} = ?" for column in patches)
    with db.connect() as conn:
        conn.execute(
            f"UPDATE ieps SET {assignments}, updated_at = datetime('now') WHERE id = ?",
            tuple(patches.values()) + (iep_id,),
        )
    return get_iep(iep_id)


def add_iep_review(iep_id: str, body: dict[str, Any]) -> dict[str, Any]:
    _assert_iep(iep_id)
    note = _clean(body.get("note"))
    if not note:
        raise HTTPException(422, "Review note is required")
    new_level = _clean(body.get("newLevel"))
    if new_level and new_level not in LEVELS:
        raise HTTPException(422, "Invalid new level")
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO iep_reviews (id, owner_id, iep_id, date, note, new_level)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (db.new_id(), auth.current_owner_id(), iep_id,
             _clean(body.get("date")) or _today(), note, new_level),
        )
        conn.execute("UPDATE ieps SET updated_at = datetime('now') WHERE id = ?", (iep_id,))
    return get_iep(iep_id)


def close_iep(iep_id: str) -> dict[str, Any]:
    return update_iep(iep_id, {"status": "Closed"})


def suggest_support(body: dict[str, Any]) -> dict[str, Any]:
    """OPT-IN only. Never diagnoses, never invents learner data, AI off by default."""
    need = _clean(body.get("need"))
    if not need:
        raise HTTPException(422, "Enter the need first")
    iep_id = _clean(body.get("iepId"))
    if iep_id:
        _assert_iep(iep_id)
    from services import ai_service

    prompt = (
        "Teacher's own words describing a classroom need: '" + need + "'\n"
        "Suggest 2-3 practical, low-cost support ideas using ordinary Kenyan classroom "
        "materials. Do NOT invent learner data. Do NOT diagnose or label the learner. "
        "Return JSON: {\"ideas\": [\"...\"]}."
    )
    data = ai_service.post_ai_json(prompt)
    ideas = data.get("ideas") if isinstance(data, dict) else None
    if isinstance(ideas, str):
        ideas = [ideas]
    if not isinstance(ideas, list):
        ideas = [str(data)] if data else []
    ideas = [_clean(x) for x in ideas if _clean(x)][:3]
    if iep_id:
        with db.connect() as conn:
            conn.execute("UPDATE ieps SET ai_enriched = 1 WHERE id = ?", (iep_id,))
    return {"ideas": ideas, "aiEnriched": True}


def learner_summary() -> dict[str, Any]:
    """Read-only counts for the My Coverage dashboard card."""
    owner = auth.current_owner_id()
    with db.connect() as conn:
        active = conn.execute(
            "SELECT COUNT(*) n FROM learners WHERE owner_id = ? AND status = 'Active'", (owner,)
        ).fetchone()["n"]
        ieps_active = conn.execute(
            "SELECT COUNT(*) n FROM ieps WHERE owner_id = ? AND status = 'Active'", (owner,)
        ).fetchone()["n"]
        due = conn.execute(
            "SELECT COUNT(*) n FROM ieps WHERE owner_id = ? AND status = 'Active' "
            "AND review_date != '' AND review_date <= date('now')", (owner,)
        ).fetchone()["n"]
    needs = get_progress({})["needsSupportCount"]
    return {"active": active, "needsSupport": needs, "iepsActive": ieps_active,
            "iepReviewsDue": due}
