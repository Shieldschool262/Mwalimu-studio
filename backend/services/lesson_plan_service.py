"""KICD Lesson Plan service (Phase 4 correction).

ONE WEEK = N LESSON PLANS.

A scheme row prints ``Week 2 | Lesson 1-5``; that is FIVE independent lesson plans. Every
plan has a single integer Lesson (never "1-5"), its own focused SLO, date, duration,
structured Lesson Development and its own version history.

Corrections applied here:
  * Lesson SLOs say "By the end of the lesson..." and focus on THAT lesson's atomic skill
    (``a) sort objects by colour only``), never the whole sub-strand.
  * Every lesson field is editable; edits never touch the SourceChunk.
  * Each field keeps its original source value, exposes "Edited from source" and can be
    reset independently.
  * Primary (PP1-Grade 6) and JSS (Grade 7-9) use separate templates, auto-selected by
    grade and switchable by the teacher.
  * Lesson Development steps are {time, teacherActivity, learnerActivity}; Assessment is
    {method, description, sampleItems, rubricIndicator}.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from auth_service import current_owner_id
from db import connect, new_id
from services import ai_service
from services.library_service import VETTED
from services.lesson_derive import assign_lessons, decompose_experiences, preview_labels
from services.lesson_templates import (
    JSS,
    effective_template_version,
    duration_for_mode,
    load_lesson_template,
    template_for_grade,
)
from services.rubric_service import ensure_chunk_rubric, format_planned_assessment

STATUSES = ("Draft", "Final")

LESSON_HEADING = "By the end of the lesson, the learner should be able to:"
SUB_STRAND_HEADING = "By the end of the sub-strand, the learner should be able to:"
SLO_WARNING = "Should be 'By the end of the lesson' for a lesson plan - Fix?"

STEP_KEYS = ("introduction", "step1", "step2", "step3", "conclusion")
SOURCE_KEYS = ("kiq", "competencies", "values", "pcis", "resources")

AI_KEY_TO_SECTION = {
    "slo": "outcomes",
    "introduction": "introduction",
    "step1": "step1",
    "step2": "step2",
    "step3": "step3",
    "extendedActivity": "extended",
    "conclusion": "conclusion",
}

HEADER_KEYS = (
    "school",
    "grade",
    "learningArea",
    "term",
    "year",
    "date",
    "time",
    "duration",
    "durationType",
    "classSize",
    "rollBoys",
    "rollGirls",
    "rollTotal",
    "teacherName",
    "tscNo",
    "strand",
    "subStrand",
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _items(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(x) for x in parsed if str(x).strip()]
        except Exception:
            pass
        return [ln.strip() for ln in value.splitlines() if ln.strip()]
    return []


def _json(value: str | None, default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except Exception:
        return default


def _section_source(section: Any) -> dict[str, Any]:
    original = _json(section["original"], {})
    return {
        "outcomes": _items(section["outcomes"]),
        "experiences": _items(section["experiences"]),
        "kiqs": _items(section["kiqs"]),
        "original": original,
    }


def _section_lesson_count(section: Any) -> int:
    start = section["lesson_start"] or 1
    end = section["lesson_end"] or start
    return max(1, int(end) - int(start) + 1)


def decomposition_for_section(section: Any) -> dict[str, Any]:
    src = _section_source(section)
    experiences = src["experiences"]
    if not experiences:
        experiences = [str(x) for x in src["original"].get("sourceExperiences") or []]
    count = _section_lesson_count(section)
    atoms = decompose_experiences(experiences)
    result = assign_lessons(
        atoms, count, source_quote=" ".join(experiences) if experiences else ""
    )
    result["preview"] = preview_labels(result)
    return result


# ---------------------------------------------------------------------------
# Lesson-specific SLO + deterministic activities
# ---------------------------------------------------------------------------


def _lower_first(text: str) -> str:
    text = (text or "").strip().rstrip(" .;,")
    if not text:
        return ""
    return text[0].lower() + text[1:]


def _atomic_text(assignment: dict[str, Any]) -> str:
    atomic = assignment.get("atomic") or {}
    return str(atomic.get("text") or assignment.get("focus") or "").strip()


def _slo_item(assignment: dict[str, Any]) -> str:
    kind = assignment.get("kind")
    if kind == "consolidation":
        body = str(assignment.get("focus") or "").split(": ", 1)[-1]
        return f"practise and consolidate {_lower_first(body)}"
    if kind == "assessment":
        body = str(assignment.get("focus") or "").split(": ", 1)[-1]
        return f"complete assessment / revision on {_lower_first(body)}"
    text = _lower_first(_atomic_text(assignment) or assignment.get("focus") or "")
    if text and " only" not in text.lower():
        text = f"{text} only"
    return text


def lesson_slo(assignment: dict[str, Any]) -> str:
    """Full lesson-plan SLO, focused on ONE atomic skill."""
    item = _slo_item(assignment)
    if item:
        return f"{LESSON_HEADING} a) {item}"
    return f"{LESSON_HEADING} a) —"


def _derive_teacher_activity(assignment: dict[str, Any]) -> str:
    kind = assignment.get("kind")
    if kind == "consolidation":
        body = str(assignment.get("focus") or "").split(": ", 1)[-1]
        return f"Facilitate practice and consolidation: {_lower_first(body)}."
    if kind == "assessment":
        body = str(assignment.get("focus") or "").split(": ", 1)[-1]
        return f"Administer assessment / revision: {_lower_first(body)}."
    text = _lower_first(_atomic_text(assignment))
    return f"Guide learners to {text}." if text else ""


def _derive_learner_activity(assignment: dict[str, Any]) -> str:
    kind = assignment.get("kind")
    if kind == "consolidation":
        body = str(assignment.get("focus") or "").split(": ", 1)[-1]
        return f"Learners practise and consolidate: {_lower_first(body)}."
    if kind == "assessment":
        body = str(assignment.get("focus") or "").split(": ", 1)[-1]
        return f"Learners complete assessment / revision: {_lower_first(body)}."
    text = _lower_first(_atomic_text(assignment))
    return f"Learners {text}." if text else ""


def _step_data(assignment: dict[str, Any], template: dict[str, Any]) -> dict[str, dict[str, str]]:
    dev = template.get("development") or {}
    intro_time = str((dev.get("introduction") or {}).get("time") or "5 min")
    conclusion_time = str((dev.get("conclusion") or {}).get("time") or "5 min")
    return {
        "introduction": {"time": intro_time, "teacherActivity": "", "learnerActivity": ""},
        "step1": {
            "time": "",
            "teacherActivity": _derive_teacher_activity(assignment),
            "learnerActivity": _derive_learner_activity(assignment),
        },
        "step2": {"time": "", "teacherActivity": "", "learnerActivity": ""},
        "step3": {"time": "", "teacherActivity": "", "learnerActivity": ""},
        "conclusion": {"time": conclusion_time, "teacherActivity": "", "learnerActivity": ""},
    }


def _assessment_data(
    template: dict[str, Any],
    scheme_assessment: str,
    planned: str,
    rubric: list[dict[str, Any]],
) -> dict[str, Any]:
    base = template.get("assessment") or {}
    indicator = str((rubric[0] or {}).get("indicator") or "") if rubric else ""
    method = (scheme_assessment or base.get("method") or "Observation, oral questions").strip()
    return {
        "method": method,
        "description": str(planned or base.get("description") or ""),
        "sampleItems": list(base.get("sampleItems") or []),
        "rubricIndicator": indicator,
    }


# ---------------------------------------------------------------------------
# Citations and vetting
# ---------------------------------------------------------------------------


def _chunk_for_section(conn: Any, plan_id: str, section_id: str) -> Any:
    cit = conn.execute(
        """SELECT * FROM plan_citations
           WHERE plan_id = ? AND section_id = ? AND field = 'specific_learning_outcomes'
           ORDER BY rowid LIMIT 1""",
        (plan_id, section_id),
    ).fetchone()
    if cit is None:
        cit = conn.execute(
            "SELECT * FROM plan_citations WHERE plan_id = ? AND section_id = ? ORDER BY rowid LIMIT 1",
            (plan_id, section_id),
        ).fetchone()
    return cit


def _chunk_vetting(chunk_id: str | None) -> str:
    if not chunk_id:
        return "Pending"
    with connect() as conn:
        row = conn.execute(
            "SELECT vetting_status FROM source_chunks WHERE id = ?", (chunk_id,)
        ).fetchone()
    if row is None:
        return "Pending"
    return row["vetting_status"] if "vetting_status" in row.keys() else "Pending"


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def _header_values(
    plan: Any,
    section: Any,
    header: dict[str, Any],
    *,
    template_version: str,
    duration: int,
    duration_type: str,
    class_size: int | None,
    date_value: str,
    time_text: str,
    lesson: int,
    count: int,
    focus: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    rolls = {
        "rollBoys": _opt_int(payload.get("rollBoys")),
        "rollGirls": _opt_int(payload.get("rollGirls")),
        "rollTotal": _opt_int(payload.get("rollTotal")),
    }
    if rolls["rollTotal"] is None and rolls["rollBoys"] is not None and rolls["rollGirls"] is not None:
        rolls["rollTotal"] = rolls["rollBoys"] + rolls["rollGirls"]
    return {
        **header,
        "school": header.get("institution") or "",
        "grade": plan["grade"],
        "learningArea": plan["subject"],
        "term": plan["term"],
        "year": header.get("year") or "",
        "date": date_value,
        "time": time_text,
        "duration": duration,
        "durationType": duration_type,
        "classSize": class_size,
        **rolls,
        "teacherName": header.get("teacherName") or "",
        "tscNo": header.get("tscNo") or "",
        "strand": section["strand"] or "",
        "subStrand": section["sub_strand"] or "",
        "week": section["week_start"],
        "lesson": lesson,
        "lessonOf": count,
        "focus": focus,
        "templateVersion": template_version,
    }


def _opt_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _section_source_value(
    key: str,
    template: dict[str, Any],
    assignment: dict[str, Any],
    source: dict[str, Any],
    step_data: dict[str, dict[str, str]],
    assessment_data: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    if key == "outcomes":
        return lesson_slo(assignment), {}
    if key == "kiq":
        return "\n".join(source.get("kiqs") or []) or "—", {}
    if key == "competencies":
        return str(source.get("competencies") or ""), {}
    if key == "values":
        return str(source.get("values") or ""), {}
    if key == "pcis":
        return str(source.get("pcis") or ""), {}
    if key == "resources":
        raw = source.get("resources") or source.get("appendixResources") or ""
        return str(raw or "— Not specified in source"), {}
    if key in STEP_KEYS:
        data = dict(step_data.get(key) or {})
        body = ""
        if key == "step1":
            body = str(data.get("learnerActivity") or "")
        return body, data
    if key == "assessment":
        return "", dict(assessment_data)
    return "", {}


def _default_provenance(key: str) -> str:
    if key == "outcomes":
        return "derived"
    if key == "step1":
        return "source-derived"
    if key in SOURCE_KEYS:
        return "source"
    if key == "assessment":
        return "source"
    return "empty"


def create_lesson_plans(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    section_id = str(payload.get("schemeRowId") or payload.get("sectionId") or "").strip()
    if not section_id:
        return [], ["schemeRowId is required."]
    raw_lessons = payload.get("lessons") or []
    if not isinstance(raw_lessons, list) or not raw_lessons:
        return [], ["Select at least one lesson."]
    try:
        lessons = sorted({int(x) for x in raw_lessons})
    except (TypeError, ValueError):
        return [], ["Lessons must be whole numbers."]

    with connect() as conn:
        section = conn.execute(
            "SELECT * FROM plan_sections WHERE id = ?", (section_id,)
        ).fetchone()
        if section is None:
            return [], ["Scheme row not found."]
        plan = conn.execute(
            "SELECT * FROM plan_documents WHERE id = ?", (section["plan_id"],)
        ).fetchone()
        if plan is None:
            return [], ["Scheme not found."]
        cit = _chunk_for_section(conn, plan["id"], section_id)
        chunk_id = cit["chunk_id"] if cit else None
        document_id = cit["document_id"] if cit else None
        page = cit["page_number"] if cit else None

    if _chunk_vetting(chunk_id) != VETTED:
        return [], ["Cannot create lesson plan - source not Vetted"]

    count = _section_lesson_count(section)
    if any(l < 1 or l > count for l in lessons):
        return [], [f"Lesson must be a single number from 1 to {count}."]

    template_version = effective_template_version(
        payload.get("templateVersion"), plan["grade"]
    )
    template = load_lesson_template(template_version)
    duration_type = str(payload.get("durationType") or ("Single" if template_version == JSS else "")).strip()
    try:
        duration = int(payload["duration"]) if payload.get("duration") not in (None, "") else duration_for_mode(
            template, duration_type
        )
    except (TypeError, ValueError):
        duration = duration_for_mode(template, duration_type)
    if duration < 1 or duration > 240:
        duration = duration_for_mode(template, duration_type)
    class_size = _opt_int(payload.get("classSize"))
    dates = payload.get("dates") or {}
    if not isinstance(dates, dict):
        dates = {}
    time_text = str(payload.get("time") or "").strip()

    src = _section_source(section)
    original = src["original"]
    decomposition = decomposition_for_section(section)
    assignments = decomposition["assignments"]

    rubric = original.get("rubric") or []
    if not rubric and chunk_id:
        rubric = ensure_chunk_rubric(chunk_id)
    scheme_assessment = section["assessment"] or original.get("assessment") or ""
    planned, differentiation = format_planned_assessment(rubric, scheme_assessment)

    scheme_header = _json(plan["header"], {})
    source = {
        "strand": section["strand"],
        "strandCode": section["strand_code"],
        "subStrand": section["sub_strand"],
        "subStrandCode": section["sub_strand_code"],
        "page": page,
        "documentId": document_id,
        "chunkId": chunk_id,
        "outcomes": src["outcomes"],
        "outcomesHeading": SUB_STRAND_HEADING,
        "experiences": src["experiences"],
        "kiqs": src["kiqs"],
        "competencies": section["competencies"],
        "values": section["values_text"],
        "pcis": section["pcis"],
        "linkOther": section["link_other"],
        "resources": section["resources"] or original.get("resources"),
        "appendixResources": original.get("appendixResources"),
        "appendixAssessment": original.get("appendixAssessment"),
        "appendixSource": original.get("appendixSource"),
        "rubric": rubric,
        "schemeAssessment": scheme_assessment,
        "sourceLabel": (
            f"{section['sub_strand'] or section['strand'] or 'Source'} p.{page}"
            if page
            else (section["sub_strand"] or "Source")
        ),
    }
    assessment = {
        "planned": planned,
        "differentiation": differentiation,
        "rubric": rubric,
    }

    created: list[dict[str, Any]] = []
    errors: list[str] = []
    with connect() as conn:
        existing = {
            r["lesson"]
            for r in conn.execute(
                "SELECT lesson FROM lesson_plans WHERE section_id = ?", (section_id,)
            ).fetchall()
        }
        for lesson in lessons:
            if lesson in existing:
                continue
            assignment = (
                assignments[lesson - 1]
                if 0 <= lesson - 1 < len(assignments)
                else {
                    "lesson": lesson,
                    "kind": "atomic",
                    "focus": f"Lesson {lesson}",
                    "focus_keyword": "",
                    "atomic": None,
                    "source_quote": "",
                }
            )
            lesson_id = new_id()
            date_value = dates.get(str(lesson)) or dates.get(lesson) or ""
            focus = assignment.get("focus") or f"Lesson {lesson}"
            header_out = _header_values(
                plan,
                section,
                scheme_header,
                template_version=template_version,
                duration=duration,
                duration_type=duration_type,
                class_size=class_size,
                date_value=date_value,
                time_text=time_text,
                lesson=lesson,
                count=count,
                focus=focus,
                payload=payload,
            )
            conn.execute(
                """INSERT INTO lesson_plans
                   (id, plan_id, section_id, chunk_id, document_id, lesson, lesson_count, week,
                    strand, sub_strand, sub_strand_code, focus, focus_keyword, source_experience,
                    date, time, duration, class_size, status, header, header_source, source_json,
                    assessment_json, template_version, ai_extras, ai_enriched, split_override,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    lesson_id,
                    plan["id"],
                    section_id,
                    chunk_id,
                    document_id,
                    lesson,
                    count,
                    section["week_start"] or 1,
                    section["strand"],
                    section["sub_strand"],
                    section["sub_strand_code"],
                    focus,
                    assignment.get("focus_keyword") or "",
                    assignment.get("source_quote") or "",
                    date_value,
                    time_text,
                    duration,
                    class_size,
                    "Draft",
                    json.dumps(header_out, ensure_ascii=False),
                    json.dumps(header_out, ensure_ascii=False),
                    json.dumps(source, ensure_ascii=False),
                    json.dumps(assessment, ensure_ascii=False),
                    template_version,
                    "{}",
                    0,
                    None,
                    _now(),
                    _now(),
                ),
            )
            _insert_sections(
                conn, lesson_id, template, assignment, source, planned, scheme_assessment, rubric
            )
            created.append(lesson_id)

        if not created:
            errors.append("These lesson plans already exist - nothing duplicated.")

    out = []
    for lesson_id in created:
        plan_payload = get_lesson_plan(lesson_id)
        if plan_payload:
            create_lesson_version(
                lesson_id,
                f"Initial version - Week {plan_payload['week']} Lesson {plan_payload['lesson']}",
                kind="initial",
            )
            out.append(get_lesson_plan(lesson_id) or plan_payload)
    return out, errors


def _insert_sections(
    conn: Any,
    lesson_id: str,
    template: dict[str, Any],
    assignment: dict[str, Any],
    source: dict[str, Any],
    planned: str,
    scheme_assessment: str,
    rubric: list[dict[str, Any]],
) -> None:
    step_data = _step_data(assignment, template)
    assessment_data = _assessment_data(template, scheme_assessment, planned, rubric)
    for ord_, spec in enumerate(template.get("sections") or []):
        key = str(spec.get("key") or "")
        body, data = _section_source_value(
            key, template, assignment, source, step_data, assessment_data
        )
        source_body = body if key in ("outcomes", "step1") or key in SOURCE_KEYS or key == "assessment" else ""
        source_data = data if key in STEP_KEYS or key == "assessment" else {}
        conn.execute(
            """INSERT INTO lesson_plan_sections
               (id, lesson_plan_id, ord, key, title, body, placeholder, hint, provenance,
                source_quote, editable, ai_draft, ai_assisted, source_body, data_json,
                source_data_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                new_id(),
                lesson_id,
                ord_,
                key,
                spec.get("title") or key,
                body,
                spec.get("placeholder"),
                spec.get("hint"),
                _default_provenance(key),
                assignment.get("source_quote") if key == "step1" else None,
                1,
                None,
                0,
                source_body,
                json.dumps(data, ensure_ascii=False),
                json.dumps(source_data, ensure_ascii=False),
            ),
        )


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def _lesson_row(conn: Any, lesson_id: str) -> Any:
    return conn.execute("SELECT * FROM lesson_plans WHERE id = ?", (lesson_id,)).fetchone()


def _section_dict(s: Any) -> dict[str, Any]:
    data = _json(s["data_json"] if "data_json" in s.keys() else "{}", {})
    source_body = s["source_body"] if "source_body" in s.keys() else None
    source_data = _json(
        s["source_data_json"] if "source_data_json" in s.keys() else "{}", {}
    )
    body = s["body"] or ""
    if source_body is None:
        source_body = body if str(s["provenance"] or "").startswith("source") else ""
    edited = body != (source_body or "") or data != (source_data or {})
    return {
        "id": s["id"],
        "ord": s["ord"],
        "key": s["key"],
        "title": s["title"],
        "body": body,
        "data": data,
        "sourceBody": source_body or "",
        "sourceData": source_data or {},
        "editedFromSource": edited,
        "placeholder": s["placeholder"],
        "hint": s["hint"],
        "provenance": s["provenance"],
        "sourceQuote": s["source_quote"],
        "editable": True,
        "aiDraft": s["ai_draft"],
        "aiAssisted": bool(s["ai_assisted"]),
        "aiProvider": s["ai_provider"],
        "aiTimestamp": s["ai_timestamp"],
    }


def get_lesson_plan(lesson_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = _lesson_row(conn, lesson_id)
        if row is None:
            return None
        sections = conn.execute(
            "SELECT * FROM lesson_plan_sections WHERE lesson_plan_id = ? ORDER BY ord",
            (lesson_id,),
        ).fetchall()
        versions = conn.execute(
            "SELECT * FROM lesson_plan_versions WHERE lesson_plan_id = ? ORDER BY version_number DESC",
            (lesson_id,),
        ).fetchall()

    header = _json(row["header"], {})
    if row["date"]:
        header["date"] = row["date"]
    if row["time"]:
        header["time"] = row["time"]
    header["duration"] = row["duration"]
    header["classSize"] = row["class_size"]
    header.setdefault("durationType", "Single" if row["template_version"] == JSS else "")

    template_version = effective_template_version(
        row["template_version"] if "template_version" in row.keys() else None,
        header.get("grade") or "",
    )
    template = load_lesson_template(template_version)

    strand = header.get("strand") or row["strand"]
    sub_strand = header.get("subStrand") or row["sub_strand"]
    header_source = _json(
        row["header_source"] if "header_source" in row.keys() else "{}", {}
    )
    if not header_source:
        header_source = dict(header)
    edited_headers = [
        key for key in HEADER_KEYS if str(header.get(key) or "") != str(header_source.get(key) or "")
    ]

    section_list = [_section_dict(s) for s in sections]
    outcomes_section = next((s for s in section_list if s["key"] == "outcomes"), None)
    slo_body = (outcomes_section or {}).get("body") or ""
    slo_warning = SLO_WARNING if "by the end of the sub-strand" in slo_body.lower() else None

    return {
        "id": row["id"],
        "templateVersion": template_version,
        "templateName": template.get("name"),
        "gradeBand": template.get("gradeBand"),
        "defaultDuration": template.get("defaultDuration"),
        "durationOptions": template.get("durationOptions") or [],
        "durationModes": template.get("durationModes") or {},
        "developmentHint": template.get("developmentHint"),
        "development": template.get("development") or {},
        "typeLabel": template.get("title", "LESSON PLAN"),
        "adminFields": (template.get("header") or {}).get("fields", []),
        "headerFields": (template.get("header") or {}).get("fields", []),
        "sectionTemplate": template.get("sections", []),
        "assessmentTemplate": template.get("assessment", {}),
        "sloHeading": template.get("outcomesHeading") or LESSON_HEADING,
        "sourceOutcomesHeading": template.get("sourceOutcomesHeading"),
        "sloWarning": slo_warning,
        "sloFixable": bool(slo_warning),
        "schemeId": row["plan_id"],
        "sectionId": row["section_id"],
        "chunkId": row["chunk_id"],
        "documentId": row["document_id"],
        "week": row["week"],
        "lesson": row["lesson"],
        "lessonCount": row["lesson_count"],
        "strand": strand,
        "subStrand": sub_strand,
        "subStrandCode": row["sub_strand_code"],
        "focus": row["focus"],
        "focusKeyword": row["focus_keyword"],
        "sourceExperience": row["source_experience"],
        "date": row["date"] or "",
        "time": row["time"] or "",
        "duration": row["duration"],
        "classSize": row["class_size"],
        "status": row["status"],
        "header": header,
        "headerSource": header_source,
        "headerEditedFields": edited_headers,
        "source": _json(row["source_json"], {}),
        "assessment": _json(row["assessment_json"], {}),
        "aiEnriched": bool(row["ai_enriched"]),
        "aiProvider": row["ai_provider"],
        "aiTimestamp": row["ai_timestamp"],
        "aiExtras": _json(row["ai_extras"], {}),
        "ai": ai_service.ai_status(),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "sections": section_list,
        "versions": [
            {
                "id": v["id"],
                "versionNumber": v["version_number"],
                "label": v["label"] or f"v{v['version_number']}",
                "comment": v["comment"],
                "createdAt": v["created_at"],
            }
            for v in versions
        ],
    }


def lesson_picker(section_id: str) -> tuple[dict[str, Any] | None, list[str]]:
    """Everything the [Create Lesson Plans] picker needs for ONE scheme row."""
    with connect() as conn:
        section = conn.execute(
            "SELECT * FROM plan_sections WHERE id = ?", (section_id,)
        ).fetchone()
        if section is None:
            return None, ["Scheme row not found."]
        plan = conn.execute(
            "SELECT grade FROM plan_documents WHERE id = ?", (section["plan_id"],)
        ).fetchone()
        existing_rows = conn.execute(
            "SELECT id, lesson, status, date, focus, template_version FROM lesson_plans WHERE section_id = ? ORDER BY lesson",
            (section_id,),
        ).fetchall()
        cit = _chunk_for_section(conn, section["plan_id"], section_id)

    count = _section_lesson_count(section)
    decomposition = decomposition_for_section(section)
    assignments = decomposition.get("assignments") or []
    by_lesson = {int(r["lesson"]): r for r in existing_rows}
    lessons = []
    for n in range(1, count + 1):
        assignment = assignments[n - 1] if 0 <= n - 1 < len(assignments) else {}
        existing = by_lesson.get(n)
        lessons.append(
            {
                "lesson": n,
                "focus": assignment.get("focus") or f"Lesson {n}",
                "kind": assignment.get("kind") or "atomic",
                "created": existing is not None,
                "lessonPlanId": existing["id"] if existing else None,
                "status": existing["status"] if existing else None,
                "date": (existing["date"] if existing and existing["date"] else ""),
            }
        )
    vetted = _chunk_vetting(cit["chunk_id"] if cit else None) == VETTED
    template_version = effective_template_version(None, plan["grade"] if plan else "")
    template = load_lesson_template(template_version)
    return {
        "sectionId": section_id,
        "planId": section["plan_id"],
        "week": section["week_start"],
        "strand": section["strand"],
        "subStrand": section["sub_strand"],
        "subStrandCode": section["sub_strand_code"],
        "lessonCount": count,
        "lessonRange": f"1-{count}",
        "sourceVetted": vetted,
        "vettingMessage": None if vetted else "Cannot create lesson plan - source not Vetted",
        "createdCount": sum(1 for item in lessons if item["created"]),
        "lessons": lessons,
        "decomposition": decomposition,
        "templateVersion": template_version,
        "gradeBand": template.get("gradeBand"),
        "defaultDuration": template.get("defaultDuration"),
        "durationOptions": template.get("durationOptions") or [],
        "developmentHint": template.get("developmentHint"),
    }, []


def list_lesson_plans(
    plan_id: str | None = None, section_id: str | None = None
) -> dict[str, Any]:
    where = []
    params: list[Any] = []
    if plan_id:
        where.append("lp.plan_id = ?")
        params.append(plan_id)
    if section_id:
        where.append("lp.section_id = ?")
        params.append(section_id)
    where.append("pd.owner_id = ?")
    params.append(current_owner_id())
    clause = f"WHERE {' AND '.join(where)}"
    with connect() as conn:
        rows = conn.execute(
            f"""SELECT lp.*, pd.title, pd.grade, pd.subject, pd.term
                FROM lesson_plans lp
                JOIN plan_documents pd ON pd.id = lp.plan_id
                {clause}
                ORDER BY lp.plan_id, lp.week, lp.lesson""",
            tuple(params),
        ).fetchall()
    plans = [
        {
            "id": r["id"],
            "planId": r["plan_id"],
            "planTitle": r["title"],
            "grade": r["grade"],
            "subject": r["subject"],
            "term": r["term"],
            "sectionId": r["section_id"],
            "week": r["week"],
            "lesson": r["lesson"],
            "lessonCount": r["lesson_count"],
            "strand": r["strand"],
            "subStrand": r["sub_strand"],
            "subStrandCode": r["sub_strand_code"],
            "focus": r["focus"],
            "status": r["status"],
            "date": r["date"] or "",
            "duration": r["duration"],
            "templateVersion": r["template_version"],
        }
        for r in rows
    ]
    groups: dict[str, dict[str, Any]] = {}
    for p in plans:
        key = f"{p['planId']}|{p['sectionId']}"
        g = groups.get(key)
        if g is None:
            g = {
                "planId": p["planId"],
                "planTitle": p["planTitle"],
                "grade": p["grade"],
                "subject": p["subject"],
                "term": p["term"],
                "sectionId": p["sectionId"],
                "week": p["week"],
                "strand": p["strand"],
                "subStrand": p["subStrand"],
                "subStrandCode": p["subStrandCode"],
                "lessonCount": p["lessonCount"],
                "lessons": [],
            }
            groups[key] = g
        g["lessons"].append(
            {
                "id": p["id"],
                "lesson": p["lesson"],
                "status": p["status"],
                "date": p["date"],
                "focus": p["focus"],
                "duration": p["duration"],
            }
        )
    return {"plans": plans, "groups": list(groups.values()), "count": len(plans)}


# ---------------------------------------------------------------------------
# Snapshot / versions
# ---------------------------------------------------------------------------


def _insert_sections_from_snapshot(conn: Any, lesson_id: str, sections: list[dict[str, Any]]) -> None:
    for s in sections:
        conn.execute(
            """INSERT INTO lesson_plan_sections
               (id, lesson_plan_id, ord, key, title, body, placeholder, hint, provenance,
                source_quote, editable, ai_draft, ai_assisted, ai_provider, ai_timestamp,
                source_body, data_json, source_data_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                s.get("id") or new_id(),
                lesson_id,
                int(s.get("ord") or 0),
                s.get("key"),
                s.get("title"),
                s.get("body") or "",
                s.get("placeholder"),
                s.get("hint"),
                s.get("provenance") or "empty",
                s.get("sourceQuote"),
                1,
                s.get("aiDraft"),
                1 if s.get("aiAssisted") else 0,
                s.get("aiProvider"),
                s.get("aiTimestamp"),
                s.get("sourceBody") or "",
                json.dumps(s.get("data") or {}, ensure_ascii=False),
                json.dumps(s.get("sourceData") or {}, ensure_ascii=False),
            ),
        )


def _apply_lesson_snapshot(conn: Any, lesson_id: str, snap: dict[str, Any]) -> None:
    conn.execute(
        """UPDATE lesson_plans SET
             focus = ?, focus_keyword = ?, source_experience = ?, date = ?, time = ?,
             duration = ?, class_size = ?, status = ?, header = ?, header_source = ?,
             source_json = ?, assessment_json = ?, template_version = ?, ai_extras = ?,
             ai_enriched = ?, ai_provider = ?, ai_timestamp = ?, updated_at = ?
           WHERE id = ?""",
        (
            snap.get("focus"),
            snap.get("focusKeyword"),
            snap.get("sourceExperience"),
            snap.get("date"),
            snap.get("time"),
            snap.get("duration"),
            snap.get("classSize"),
            snap.get("status") or "Draft",
            json.dumps(snap.get("header") or {}, ensure_ascii=False),
            json.dumps(snap.get("headerSource") or {}, ensure_ascii=False),
            json.dumps(snap.get("source") or {}, ensure_ascii=False),
            json.dumps(snap.get("assessment") or {}, ensure_ascii=False),
            snap.get("templateVersion"),
            json.dumps(snap.get("aiExtras") or {}, ensure_ascii=False),
            1 if snap.get("aiEnriched") else 0,
            snap.get("aiProvider"),
            snap.get("aiTimestamp"),
            _now(),
            lesson_id,
        ),
    )
    conn.execute("DELETE FROM lesson_plan_sections WHERE lesson_plan_id = ?", (lesson_id,))
    _insert_sections_from_snapshot(conn, lesson_id, snap.get("sections") or [])


# ---------------------------------------------------------------------------
# Edits, resets, SLO fix
# ---------------------------------------------------------------------------


def edit_lesson_section(
    lesson_id: str, section_id: str, patch: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[str]]:
    with connect() as conn:
        plan = _lesson_row(conn, lesson_id)
        if plan is None:
            return None, ["Lesson plan not found."]
        section = conn.execute(
            "SELECT * FROM lesson_plan_sections WHERE id = ? AND lesson_plan_id = ?",
            (section_id, lesson_id),
        ).fetchone()
        if section is None:
            return None, ["Section not found."]

        data = _json(section["data_json"] if "data_json" in section.keys() else "{}", {})
        body = section["body"] or ""
        provenance = section["provenance"] or "teacher"
        changed = False

        if patch.get("rejectAi"):
            conn.execute(
                "UPDATE lesson_plan_sections SET ai_draft = NULL WHERE id = ?", (section_id,)
            )
        elif patch.get("acceptAi"):
            if not section["ai_draft"]:
                return None, ["There is no AI draft to accept."]
            body = section["ai_draft"]
            provenance = "ai"
            if section["key"] in STEP_KEYS:
                data = dict(data or {})
                data["learnerActivity"] = body
                data.setdefault("time", "")
                data.setdefault("teacherActivity", "")
            conn.execute(
                """UPDATE lesson_plan_sections
                   SET body = ?, data_json = ?, provenance = 'ai', ai_assisted = 1,
                       ai_provider = ?, ai_timestamp = ?, ai_draft = NULL
                   WHERE id = ?""",
                (
                    body,
                    json.dumps(data, ensure_ascii=False),
                    ai_service.ai_status().get("provider") or "gemini",
                    _now(),
                    section_id,
                ),
            )
        else:
            if "body" in patch:
                body = str(patch.get("body") or "")
                provenance = "web" if patch.get("provenance") == "web" else (
                    "teacher" if body.strip() else "empty"
                )
                changed = True
            if isinstance(patch.get("data"), dict):
                for key, value in patch["data"].items():
                    data[key] = value
                if isinstance(data.get("sampleItems"), str):
                    data["sampleItems"] = [
                        ln.strip() for ln in str(data["sampleItems"]).splitlines() if ln.strip()
                    ]
                provenance = "teacher"
                changed = True
            if changed:
                conn.execute(
                    """UPDATE lesson_plan_sections
                       SET body = ?, data_json = ?, provenance = ?, ai_draft = NULL
                       WHERE id = ?""",
                    (body, json.dumps(data, ensure_ascii=False), provenance, section_id),
                )

        conn.execute(
            "UPDATE lesson_plans SET updated_at = ? WHERE id = ?", (_now(), lesson_id)
        )
    return get_lesson_plan(lesson_id), []


def reset_lesson_section(
    lesson_id: str, section_id: str
) -> tuple[dict[str, Any] | None, list[str]]:
    """Restore one field to its source value (or clear it for teacher-only fields)."""
    with connect() as conn:
        plan = _lesson_row(conn, lesson_id)
        if plan is None:
            return None, ["Lesson plan not found."]
        section = conn.execute(
            "SELECT * FROM lesson_plan_sections WHERE id = ? AND lesson_plan_id = ?",
            (section_id, lesson_id),
        ).fetchone()
        if section is None:
            return None, ["Section not found."]

        key = section["key"]
        source_body = section["source_body"] if "source_body" in section.keys() else None
        source_data = _json(
            section["source_data_json"] if "source_data_json" in section.keys() else "{}", {}
        )
        body = source_body if source_body is not None else ""
        data = source_data or {}
        conn.execute(
            """UPDATE lesson_plan_sections
               SET body = ?, data_json = ?, provenance = ?, ai_draft = NULL
               WHERE id = ?""",
            (
                body,
                json.dumps(data, ensure_ascii=False),
                _default_provenance(key),
                section_id,
            ),
        )
        conn.execute(
            "UPDATE lesson_plans SET updated_at = ? WHERE id = ?", (_now(), lesson_id)
        )
    return get_lesson_plan(lesson_id), []


def fix_lesson_slo(lesson_id: str) -> tuple[dict[str, Any] | None, list[str]]:
    """Convert a sub-strand SLO to the lesson-plan heading, in place."""
    with connect() as conn:
        plan = _lesson_row(conn, lesson_id)
        if plan is None:
            return None, ["Lesson plan not found."]
        section = conn.execute(
            "SELECT * FROM lesson_plan_sections WHERE lesson_plan_id = ? AND key = 'outcomes'",
            (lesson_id,),
        ).fetchone()
        if section is None:
            return None, ["Outcomes section not found."]
        body = section["body"] or ""
        fixed = re.sub(
            r"by the end of the sub-strand,\s*the learner should be able to\s*:?",
            LESSON_HEADING,
            body,
            flags=re.I,
        )
        if fixed == body:
            fixed = f"{LESSON_HEADING} {body}".strip()
        conn.execute(
            """UPDATE lesson_plan_sections SET body = ?, provenance = 'teacher', ai_draft = NULL
               WHERE id = ?""",
            (fixed, section["id"]),
        )
        conn.execute("UPDATE lesson_plans SET updated_at = ? WHERE id = ?", (_now(), lesson_id))
    payload = get_lesson_plan(lesson_id)
    if payload is not None:
        payload["fixed"] = True
    return payload, []


def edit_lesson_header(
    lesson_id: str, patch: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[str]]:
    with connect() as conn:
        plan = _lesson_row(conn, lesson_id)
        if plan is None:
            return None, ["Lesson plan not found."]
        header = _json(plan["header"], {})
        template_version = effective_template_version(
            plan["template_version"] if "template_version" in plan.keys() else None,
            header.get("grade") or "",
        )
        template = load_lesson_template(template_version)

        date_value = plan["date"] or ""
        time_value = plan["time"] or ""
        duration = plan["duration"]
        class_size = plan["class_size"]
        switched = False

        if "templateVersion" in patch:
            requested = str(patch.get("templateVersion") or "")
            if requested not in ("cbe-lesson-primary-v1", "cbe-lesson-jss-v1"):
                return None, ["Unknown lesson template."]
            if requested != template_version:
                template_version = requested
                template = load_lesson_template(template_version)
                switched = True
                header["templateVersion"] = template_version
                header["durationType"] = "Single" if template_version == JSS else ""
                if "duration" not in patch:
                    duration = duration_for_mode(template, header.get("durationType"))

        if "durationType" in patch:
            mode = str(patch.get("durationType") or "").strip()
            if template_version != JSS:
                mode = ""
            header["durationType"] = mode
            if mode and "duration" not in patch:
                duration = duration_for_mode(template, mode)
            if not mode and template_version == JSS and "duration" not in patch:
                duration = int(template.get("defaultDuration") or 40)

        for key in HEADER_KEYS:
            if key not in patch:
                continue
            value = patch[key]
            if key == "date":
                date_value = str(value or "")
                header["date"] = date_value
            elif key == "time":
                time_value = str(value or "")
                header["time"] = time_value
            elif key == "duration":
                try:
                    duration = int(value) if value not in (None, "") else duration
                except (TypeError, ValueError):
                    return None, ["Duration must be a number of minutes."]
                header["duration"] = duration
            elif key == "classSize":
                try:
                    class_size = int(value) if value not in (None, "") else None
                except (TypeError, ValueError):
                    class_size = None
                header["classSize"] = class_size
            elif key in ("rollBoys", "rollGirls", "rollTotal"):
                header[key] = _opt_int(value)
            elif key == "durationType":
                continue
            else:
                header[key] = str(value or "")

        if switched:
            for spec in template.get("sections") or []:
                conn.execute(
                    "UPDATE lesson_plan_sections SET title = ?, hint = ? WHERE lesson_plan_id = ? AND key = ?",
                    (spec.get("title"), spec.get("hint"), lesson_id, spec.get("key")),
                )
            conn.execute(
                "UPDATE lesson_plans SET template_version = ? WHERE id = ?",
                (template_version, lesson_id),
            )

        conn.execute(
            """UPDATE lesson_plans SET date = ?, time = ?, duration = ?, class_size = ?,
               header = ?, updated_at = ? WHERE id = ?""",
            (
                date_value,
                time_value,
                duration,
                class_size,
                json.dumps(header, ensure_ascii=False),
                _now(),
                lesson_id,
            ),
        )
    return get_lesson_plan(lesson_id), []


def reset_lesson_header(
    lesson_id: str, field: str
) -> tuple[dict[str, Any] | None, list[str]]:
    if field not in HEADER_KEYS and field != "templateVersion":
        return None, ["Unknown header field."]
    with connect() as conn:
        plan = _lesson_row(conn, lesson_id)
        if plan is None:
            return None, ["Lesson plan not found."]
        header = _json(plan["header"], {})
        header_source = _json(
            plan["header_source"] if "header_source" in plan.keys() else "{}", {}
        )
        source = _json(plan["source_json"], {})
        if field == "templateVersion":
            value = template_for_grade(header.get("grade") or "")
        elif field in header_source:
            value = header_source.get(field)
        elif field == "strand":
            value = source.get("strand") or ""
        elif field == "subStrand":
            value = source.get("subStrand") or ""
        else:
            value = ""
        header[field] = value

        date_value = plan["date"] or ""
        time_value = plan["time"] or ""
        duration = plan["duration"]
        class_size = plan["class_size"]
        if field == "date":
            date_value = str(value or "")
            header["date"] = date_value
        elif field == "time":
            time_value = str(value or "")
            header["time"] = time_value
        elif field == "duration":
            duration = _opt_int(value) or int(load_lesson_template(
                effective_template_version(plan["template_version"], header.get("grade") or "")
            ).get("defaultDuration") or 35)
            header["duration"] = duration
        elif field == "classSize":
            class_size = _opt_int(value)
            header["classSize"] = class_size
        elif field == "templateVersion":
            conn.execute(
                "UPDATE lesson_plans SET template_version = ? WHERE id = ?",
                (value, lesson_id),
            )

        conn.execute(
            """UPDATE lesson_plans SET date = ?, time = ?, duration = ?, class_size = ?,
               header = ?, updated_at = ? WHERE id = ?""",
            (
                date_value,
                time_value,
                duration,
                class_size,
                json.dumps(header, ensure_ascii=False),
                _now(),
                lesson_id,
            ),
        )
    return get_lesson_plan(lesson_id), []


def set_lesson_status(
    lesson_id: str, status: str
) -> tuple[dict[str, Any] | None, list[str]]:
    if status not in STATUSES:
        return None, [f"Unknown status '{status}'."]
    with connect() as conn:
        plan = _lesson_row(conn, lesson_id)
        if plan is None:
            return None, ["Lesson plan not found."]
        conn.execute(
            "UPDATE lesson_plans SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), lesson_id),
        )
    if status == "Final":
        create_lesson_version(lesson_id, "Marked Final", kind="final", label="Final")
    return get_lesson_plan(lesson_id), []


# ---------------------------------------------------------------------------
# Version history per lesson plan
# ---------------------------------------------------------------------------


def _next_lesson_version(conn: Any, lesson_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(version_number), 0) n FROM lesson_plan_versions WHERE lesson_plan_id = ?",
        (lesson_id,),
    ).fetchone()
    return int(row["n"] or 0) + 1


def create_lesson_version(
    lesson_id: str,
    comment: str,
    kind: str = "version",
    label: str | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    comment = (comment or "").strip()
    if not comment:
        return None, ["A comment is required, e.g. 'Added group work to Step 2'."]
    plan = get_lesson_plan(lesson_id)
    if plan is None:
        return None, ["Lesson plan not found."]
    with connect() as conn:
        n = _next_lesson_version(conn, lesson_id)
        version_id = new_id()
        conn.execute(
            """INSERT INTO lesson_plan_versions
               (id, lesson_plan_id, version_number, label, comment, snapshot_json, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                version_id,
                lesson_id,
                n,
                label or f"v{n}",
                comment,
                json.dumps(plan, ensure_ascii=False),
                _now(),
            ),
        )
        row = conn.execute(
            "SELECT * FROM lesson_plan_versions WHERE id = ?", (version_id,)
        ).fetchone()
    return {
        "id": row["id"],
        "versionNumber": row["version_number"],
        "label": row["label"],
        "comment": row["comment"],
        "createdAt": row["created_at"],
    }, []


def list_lesson_versions(lesson_id: str) -> dict[str, Any]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM lesson_plan_versions WHERE lesson_plan_id = ? ORDER BY version_number DESC",
            (lesson_id,),
        ).fetchall()
    return {
        "versions": [
            {
                "id": r["id"],
                "versionNumber": r["version_number"],
                "label": r["label"] or f"v{r['version_number']}",
                "comment": r["comment"],
                "createdAt": r["created_at"],
            }
            for r in rows
        ],
        "count": len(rows),
    }


def get_lesson_version(lesson_id: str, version_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM lesson_plan_versions WHERE id = ? AND lesson_plan_id = ?",
            (version_id, lesson_id),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "versionNumber": row["version_number"],
        "label": row["label"] or f"v{row['version_number']}",
        "comment": row["comment"],
        "createdAt": row["created_at"],
        "snapshot": _json(row["snapshot_json"], {}),
    }


def restore_lesson_version(
    lesson_id: str, version_id: str
) -> tuple[dict[str, Any] | None, list[str]]:
    version = get_lesson_version(lesson_id, version_id)
    if version is None:
        return None, ["Version not found."]
    with connect() as conn:
        if _lesson_row(conn, lesson_id) is None:
            return None, ["Lesson plan not found."]
        _apply_lesson_snapshot(conn, lesson_id, version["snapshot"])
    new_version, errors = create_lesson_version(
        lesson_id, f"Restored from v{version['versionNumber']}", kind="restore"
    )
    if errors:
        return None, errors
    plan = get_lesson_plan(lesson_id)
    return {**(plan or {}), "restoredVersion": new_version}, []


def diff_lesson_version(lesson_id: str, version_id: str) -> dict[str, Any] | None:
    version = get_lesson_version(lesson_id, version_id)
    current = get_lesson_plan(lesson_id)
    if version is None or current is None:
        return None
    old_sections = {s.get("key"): s for s in (version["snapshot"].get("sections") or [])}
    new_sections = {s.get("key"): s for s in (current.get("sections") or [])}
    diffs = []
    for key, old in old_sections.items():
        new = new_sections.get(key)
        frm = old.get("body") or ""
        to = (new or {}).get("body") or ""
        if frm == to:
            if (old.get("data") or {}) != ((new or {}).get("data") or {}):
                diffs.append(
                    {
                        "field": key,
                        "label": old.get("title") or key,
                        "from": json.dumps(old.get("data") or {}, ensure_ascii=False),
                        "to": json.dumps((new or {}).get("data") or {}, ensure_ascii=False),
                        "status": "changed",
                    }
                )
            continue
        status = "removed" if frm and not to else "added" if not frm and to else "changed"
        diffs.append(
            {
                "field": key,
                "label": old.get("title") or key,
                "from": frm,
                "to": to,
                "status": status,
            }
        )
    for key in HEADER_KEYS:
        frm = str((version["snapshot"].get("header") or {}).get(key) or "")
        to = str((current.get("header") or {}).get(key) or "")
        if frm != to:
            diffs.append(
                {
                    "field": f"header:{key}",
                    "label": f"Header · {key}",
                    "from": frm,
                    "to": to,
                    "status": "removed" if frm and not to else "added" if not to and to else "changed",
                }
            )
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


# ---------------------------------------------------------------------------
# AI enrichment + web examples (teacher initiated)
# ---------------------------------------------------------------------------


def ai_draft(lesson_id: str) -> tuple[dict[str, Any] | None, list[str]]:
    plan = get_lesson_plan(lesson_id)
    if plan is None:
        return None, ["Lesson plan not found."]
    if not ai_service.ai_status()["available"]:
        return None, [ai_service.ai_status()["message"]]
    source = plan.get("source") or {}
    context = {
        "strand": plan.get("strand"),
        "subStrand": plan.get("subStrand"),
        "outcomes": source.get("outcomes"),
        "experiences": [plan.get("focus")] + (source.get("experiences") or []),
        "kiq": (source.get("kiqs") or [""])[0],
        "resources": source.get("resources"),
        "rubric": source.get("rubric"),
        "grade": (plan.get("header") or {}).get("grade"),
        "duration": plan.get("duration"),
        "week": plan.get("week"),
        "lesson": plan.get("lesson"),
        "lessonCount": plan.get("lessonCount"),
        "focus": plan.get("focus"),
        "sloHeading": plan.get("sloHeading") or LESSON_HEADING,
    }
    try:
        draft = ai_service.draft_lesson(context)
    except ai_service.AIUnavailable as e:
        return None, [str(e)]
    except ai_service.AIError as e:
        return None, [str(e)]

    # AI is never allowed to reintroduce the sub-strand heading in a lesson plan.
    for key, value in list(draft.items()):
        if isinstance(value, str) and "by the end of the sub-strand" in value.lower():
            draft[key] = re.sub(
                r"by the end of the sub-strand,\s*the learner should be able to\s*:?",
                LESSON_HEADING,
                value,
                flags=re.I,
            )

    with connect() as conn:
        sections = conn.execute(
            "SELECT * FROM lesson_plan_sections WHERE lesson_plan_id = ?", (lesson_id,)
        ).fetchall()
        by_key = {s["key"]: s for s in sections}
        for ai_key, section_key in AI_KEY_TO_SECTION.items():
            section = by_key.get(section_key)
            if section is None:
                continue
            conn.execute(
                "UPDATE lesson_plan_sections SET ai_draft = ? WHERE id = ?",
                (draft.get(ai_key) or "", section["id"]),
            )
        extras = {
            "commonMisconception": draft.get("commonMisconception") or "",
            "teacherQuestions": draft.get("teacherQuestions") or "",
        }
        conn.execute(
            """UPDATE lesson_plans SET ai_extras = ?, ai_provider = ?, ai_timestamp = ?,
               ai_enriched = 1, updated_at = ? WHERE id = ?""",
            (json.dumps(extras, ensure_ascii=False), ai_service.ai_status().get("provider") or "ai", _now(), _now(), lesson_id),
        )
    return get_lesson_plan(lesson_id), []


def ai_split_suggest(lesson_id: str) -> tuple[dict[str, Any] | None, list[str]]:
    plan = get_lesson_plan(lesson_id)
    if plan is None:
        return None, ["Lesson plan not found."]
    if not ai_service.ai_status()["available"]:
        return None, [ai_service.ai_status()["message"]]
    experience = plan.get("sourceExperience") or plan.get("focus") or ""
    try:
        atoms = ai_service.suggest_split(
            {
                "experience": experience,
                "subStrand": plan.get("subStrand"),
                "grade": (plan.get("header") or {}).get("grade"),
            }
        )
    except ai_service.AIError as e:
        return None, [str(e)]
    return {
        "experience": experience,
        "atoms": atoms,
        "needsApproval": True,
        "message": "AI suggestions - review each piece. Nothing is applied automatically.",
    }, []


def search_examples(lesson_id: str, query: str) -> tuple[list[dict[str, Any]], list[str]]:
    plan = get_lesson_plan(lesson_id)
    if plan is None:
        return [], ["Lesson plan not found."]
    q = query or f"{plan.get('subStrand')} Grade 1 activity"
    return ai_service.search_examples(
        q,
        grade=str(plan.get("grade") or ""),
        focus=str(plan.get("focus") or ""),
        log_key=lesson_id,
    )


def delete_lesson_plan(lesson_id: str) -> bool:
    """Delete one generated lesson plan (sections / versions / edits cascade)."""
    with connect() as conn:
        row = conn.execute("SELECT id FROM lesson_plans WHERE id = ?", (lesson_id,)).fetchone()
        if row is None:
            return False
        conn.execute("DELETE FROM lesson_plans WHERE id = ?", (lesson_id,))
    return True
