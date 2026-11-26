"""Phase 8 - Coverage Dashboard.

Read-only aggregate over existing Scheme + Record of Work data.  Coverage is
NEVER inferred from the Scheme plan: a plan with no ROW is reported as
``ROW not yet created`` with ``coveragePct = None`` and is excluded from the
coverage numerator/denominator rather than silently counted as 0%.

The heavy lifting is a single GROUP BY aggregate query.  The only other reads
are a small gap-row query (gap statuses only) and a lesson-count query for
schemes that do not have a ROW yet.  Nothing is sent to the browser for
counting in JavaScript.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any

import db
from auth_service import current_owner_id

# Teacher-scoped, 60-second in-memory cache.  The cache key includes the latest
# record_of_work_docs / term_reflections updated_at, so ANY ROW edit,
# carry-over, mark-taught, skip, or reflection save naturally invalidates it
# without touching the Phase 6 service.
_TTL_SECONDS = 60.0
_CACHE: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()

GAP_STATUSES = ("Not Taught - Carry Over", "Not Taught - Skipped")


def _j(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, (dict, list)) else default
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def coverage_pct(taught: int, partially: int, planned: int) -> int | None:
    """Coverage = (Taught + Partially * 0.5) / Planned * 100.

    Acceptance example: (157 + 5 * 0.5) / 180 = 88.6% -> 89%.
    Partially Taught counts as HALF a lesson; blank statuses and carry-over
    audit rows count as zero.  No plan -> no coverage (None), never 100%.
    """
    if not planned:
        return None
    return round((float(taught) + 0.5 * float(partially)) * 100.0 / float(planned))


def _status(
    row: dict[str, Any], coverage: int | None, current_week: int
) -> str:
    if not row["rowExists"]:
        return "Not Started"
    if row["planned"] and row["taught"] == row["planned"] and row["notTaught"] == 0:
        return "Complete"
    lag = None if row["last_taught_week"] is None else current_week - int(row["last_taught_week"])
    if coverage is not None and coverage >= 90 and lag is not None and lag <= 1:
        return "On Track"
    return "Behind"


def _normalise_filters(params: dict[str, Any]) -> dict[str, Any]:
    def clean(key: str) -> str:
        value = str(params.get(key) or "").strip()
        return "" if value.lower() in ("", "all", "me") else value

    try:
        week = int(params.get("week") or 0)
    except (TypeError, ValueError):
        week = 0
    return {
        "term": clean("term"),
        "year": clean("year"),
        "grade": clean("grade"),
        "subject": clean("subject"),
        "teacher": clean("teacher"),
        "week": week if 1 <= week <= 52 else 0,
    }


def _cache_stamp(conn: Any) -> str:
    vals = []
    for table in ("record_of_work_docs", "term_reflections"):
        try:
            r = conn.execute(f"SELECT MAX(updated_at) v FROM {table}").fetchone()
            vals.append(str(r["v"] if r and r["v"] else ""))
        except Exception:
            vals.append("")
    return "|".join(vals)


def get_dashboard(params: dict[str, Any]) -> dict[str, Any]:
    """Return a filtered dashboard payload.  Cached for 60s per filter set."""
    filters = _normalise_filters(params)
    with db.connect() as conn:
        stamp = _cache_stamp(conn)
    # Owner is part of the key: two teachers with identical filters must never
    # receive each other's cached dashboard.
    key = (current_owner_id(), tuple(sorted(filters.items())), stamp)
    now = time.monotonic()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < _TTL_SECONDS:
            return json.loads(json.dumps(hit[1]))
    payload = _compute(filters)
    with _CACHE_LOCK:
        # Keep the cache small; stale filter combinations are cheap to rebuild.
        if len(_CACHE) > 64:
            _CACHE.clear()
        _CACHE[key] = (now, payload)
    return payload


def invalidate() -> None:
    """Explicitly drop cached results (also happens automatically on ROW edits)."""
    with _CACHE_LOCK:
        _CACHE.clear()


def _compute(f: dict[str, Any]) -> dict[str, Any]:
    where: list[str] = ["pd.type = 'scheme'", "pd.owner_id = ?"]
    args: list[Any] = [current_owner_id()]
    if f["term"]:
        where.append("pd.term = ?")
        args.append(f["term"])
    if f["year"]:
        where.append("COALESCE(json_extract(pd.header, '$.year'), '') = ?")
        args.append(f["year"])
    if f["grade"]:
        where.append("pd.grade = ?")
        args.append(f["grade"])
    if f["subject"]:
        where.append("pd.subject = ?")
        args.append(f["subject"])
    if f["teacher"]:
        where.append("COALESCE(json_extract(pd.header, '$.teacherName'), '') = ?")
        args.append(f["teacher"])
    where_sql = " AND ".join(where)

    # ---- ONE aggregate query: all planned/taught/partial/gap counts ----------
    sql = f"""
        SELECT pd.id AS plan_id, pd.title, pd.grade, pd.subject, pd.term,
               COALESCE(json_extract(pd.header, '$.year'), '') AS year,
               COALESCE(json_extract(pd.header, '$.teacherName'), '') AS teacher,
               rd.id AS doc_id,
               COUNT(CASE WHEN r.origin = 'planned' THEN 1 END) AS planned,
               SUM(CASE WHEN r.origin = 'planned' AND r.status = 'Taught'
                        THEN 1 ELSE 0 END) AS taught,
               SUM(CASE WHEN r.origin = 'planned' AND r.status = 'Partially Taught'
                        THEN 1 ELSE 0 END) AS partially,
               SUM(CASE WHEN r.origin = 'planned' AND r.status LIKE 'Not Taught%'
                        THEN 1 ELSE 0 END) AS not_taught,
               SUM(CASE WHEN r.origin = 'planned'
                             AND r.status = 'Not Taught - Carry Over'
                        THEN 1 ELSE 0 END) AS carry_over,
               SUM(CASE WHEN r.origin = 'carry-over' THEN 1 ELSE 0 END) AS carry_over_rows,
               MAX(CASE WHEN r.origin = 'planned' AND r.status = 'Taught'
                        THEN r.week END) AS last_taught_week,
               MAX(CASE WHEN r.origin = 'planned' THEN r.week END) AS last_planned_week
        FROM plan_documents pd
        LEFT JOIN record_of_work_docs rd ON rd.plan_id = pd.id
        LEFT JOIN record_of_work_rows r ON r.doc_id = rd.id
        WHERE {where_sql}
        GROUP BY pd.id
        ORDER BY pd.grade, pd.subject, pd.term
    """
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute(sql, args).fetchall()]

        # Week filter narrows the counts inside the aggregate result (cheap,
        # no extra row fetch).  We re-run the same query shape with a week
        # predicate only when the user picked a specific week.
        if f["week"]:
            # Append the week placeholder last, matching args order (owner first).
            sql_week = sql.replace(
                f"WHERE {where_sql}",
                f"WHERE {where_sql} AND r.week = ?",
            )
            rows = [dict(r) for r in conn.execute(sql_week, args + [f["week"]]).fetchall()]

        # Schemes without a ROW: show a lesson count for context, but no coverage.
        no_row_ids = [r["plan_id"] for r in rows if not r["doc_id"]]
        section_counts: dict[str, int] = {}
        for pid in no_row_ids:
            r = conn.execute(
                """SELECT COALESCE(SUM(COALESCE(lesson_count, 1)), COUNT(*)) n
                   FROM plan_sections WHERE plan_id = ?""",
                (pid,),
            ).fetchone()
            section_counts[pid] = int(r["n"] if r and r["n"] else 0)

        # Only gap-status rows are fetched; blank/taught rows are never shipped.
        gap_sql = f"""
            SELECT r.*, pd.subject, pd.grade, pd.term, pd.title AS plan_title
            FROM record_of_work_rows r
            JOIN plan_documents pd ON pd.id = r.plan_id
            WHERE {where_sql}
              AND r.status IN ('Not Taught - Carry Over', 'Not Taught - Skipped')
        """
        gap_args = list(args)
        if f["week"]:
            gap_sql += " AND r.week = ?"
            gap_args.append(f["week"])
        gap_rows = [dict(r) for r in conn.execute(gap_sql, gap_args).fetchall()]

        # Partially-taught rows are reported separately, never as gaps.
        partial_sql = gap_sql.replace(
            "r.status IN ('Not Taught - Carry Over', 'Not Taught - Skipped')",
            "r.status = 'Partially Taught'",
        )
        partial_rows = [dict(r) for r in conn.execute(partial_sql, gap_args).fetchall()]

        # Per-week distribution (including cumulative coverage) - one query.
        week_sql = f"""
            SELECT r.week,
                   SUM(CASE WHEN r.origin = 'planned' THEN 1 ELSE 0 END) AS planned,
                   SUM(CASE WHEN r.origin = 'planned' AND r.status = 'Taught'
                            THEN 1 ELSE 0 END) AS taught,
                   SUM(CASE WHEN r.origin = 'planned' AND r.status = 'Partially Taught'
                            THEN 1 ELSE 0 END) AS partially,
                   SUM(CASE WHEN r.origin = 'carry-over' THEN 1 ELSE 0 END) AS carry_over
            FROM record_of_work_rows r
            JOIN plan_documents pd ON pd.id = r.plan_id
            WHERE {where_sql}
            GROUP BY r.week ORDER BY r.week
        """
        week_rows = [dict(r) for r in conn.execute(week_sql, args).fetchall()]

        last_updated = ""
        r = conn.execute(
            """SELECT MAX(rd.updated_at) v FROM record_of_work_docs rd
               JOIN plan_documents pd ON pd.id = rd.plan_id WHERE pd.owner_id = ?""",
            (current_owner_id(),),
        ).fetchone()
        if r and r["v"]:
            last_updated = str(r["v"])

        # Distinct filter options (used to populate the filter dropdowns).
        catalog: dict[str, list[str]] = {}
        for key, expr in (
            ("terms", "pd.term"),
            ("years", "json_extract(pd.header, '$.year')"),
            ("grades", "pd.grade"),
            ("subjects", "pd.subject"),
            ("teachers", "json_extract(pd.header, '$.teacherName')"),
        ):
            vals = conn.execute(
                f"SELECT DISTINCT {expr} v FROM plan_documents pd "
                "WHERE pd.type='scheme' AND pd.owner_id = ? "
                "AND v IS NOT NULL AND v != '' ORDER BY v",
                (current_owner_id(),),
            ).fetchall()
            catalog[key] = [str(x["v"]) for x in vals]
        max_week = conn.execute(
            """SELECT MAX(r.week) w FROM record_of_work_rows r
               JOIN plan_documents pd ON pd.id = r.plan_id WHERE pd.owner_id = ?""",
            (current_owner_id(),),
        ).fetchone()
        catalog["weeks"] = [str(i) for i in range(1, int(max_week["w"] or 12) + 1)]

    # ---- assemble -----------------------------------------------------------
    by_subject: list[dict[str, Any]] = []
    for row in rows:
        is_real = bool(row["doc_id"])
        planned = int(row["planned"] or 0) if is_real else section_counts.get(row["plan_id"], 0)
        taught = int(row["taught"] or 0)
        partially = int(row["partially"] or 0)
        not_taught = int(row["not_taught"] or 0)
        carry_over = int(row["carry_over"] or 0)
        pct = coverage_pct(taught, partially, planned) if is_real else None
        entry = {
            "planId": row["plan_id"],
            "subject": row["subject"] or "",
            "grade": row["grade"] or "",
            "term": row["term"] or "",
            "year": row["year"] or "",
            "teacher": row["teacher"] or "",
            "rowExists": is_real,
            "planned": planned,
            "taught": taught,
            "partially": partially,
            "notTaught": not_taught,
            "carryOver": carry_over,
            "coveragePct": pct,
            "status": _status(
                {**row, "rowExists": is_real, "planned": planned,
                 "taught": taught, "notTaught": not_taught},
                pct,
                int(row["last_planned_week"] or 1),
            ),
            "lastTaughtWeek": row["last_taught_week"],
            "byWeek": [],
        }
        by_subject.append(entry)

    # Per-subject week breakdown comes from the small week aggregate, sliced by
    # plan using a single grouped query (no per-row JS counting).
    with db.connect() as conn:
        subj_week_sql = f"""
            SELECT r.plan_id, r.week,
                   SUM(CASE WHEN r.origin='planned' THEN 1 ELSE 0 END) planned,
                   SUM(CASE WHEN r.origin='planned' AND r.status='Taught'
                            THEN 1 ELSE 0 END) taught
            FROM record_of_work_rows r
            JOIN plan_documents pd ON pd.id = r.plan_id
            WHERE {where_sql} AND r.origin = 'planned'
            GROUP BY r.plan_id, r.week ORDER BY r.week
        """
        sw_rows = [dict(x) for x in conn.execute(subj_week_sql, args).fetchall()]
    sw_map: dict[str, list[dict[str, Any]]] = {}
    for x in sw_rows:
        sw_map.setdefault(x["plan_id"], []).append(
            {"week": int(x["week"] or 0), "planned": int(x["planned"] or 0),
             "taught": int(x["taught"] or 0)}
        )
    for entry in by_subject:
        entry["byWeek"] = sw_map.get(entry["planId"], [])

    by_week: list[dict[str, Any]] = []
    cum_planned = cum_taught = cum_partial = 0
    for w in week_rows:
        planned = int(w["planned"] or 0)
        taught = int(w["taught"] or 0)
        partially = int(w["partially"] or 0)
        cum_planned += planned
        cum_taught += taught
        cum_partial += partially
        by_week.append({
            "week": int(w["week"] or 0),
            "planned": planned,
            "taught": taught,
            "partially": partially,
            "carryOver": int(w["carry_over"] or 0),
            "cumulativePct": coverage_pct(cum_taught, cum_partial, cum_planned) or 0,
        })

    def gap_dict(r: dict[str, Any]) -> dict[str, Any]:
        target = _j(r.get("carry_over_to"), None)
        reason = (r.get("reflection") or "").strip() or (r.get("carry_over_note") or "").strip()
        focus = r.get("focus_keyword") or r.get("sub_strand") or ""
        part = r.get("strand") or ""
        return {
            "rowId": r["id"],
            "planId": r["plan_id"],
            "subject": r["subject"] or "",
            "grade": r["grade"] or "",
            "term": r["term"] or "",
            "week": int(r["week"] or 0),
            "lesson": int(r["lesson"] or 0),
            "focus": focus,
            "strand": part,
            "status": r["status"],
            "reason": reason,
            "carryOverTo": target,
            "origin": r["origin"],
        }

    gaps = [gap_dict(r) for r in gap_rows]
    partials = [gap_dict(r) for r in partial_rows]

    # Next week planner -------------------------------------------------------
    current_week = max(
        [int(r["last_planned_week"] or 0) for r in rows] + [int(w["week"] or 0) for w in week_rows] + [0]
    )
    next_week = current_week + 1 if current_week else 1
    with db.connect() as conn:
        np = conn.execute(
            """SELECT COUNT(*) n FROM record_of_work_rows r
               JOIN plan_documents pd ON pd.id=r.plan_id
               WHERE r.week=? AND r.origin='planned' AND pd.owner_id = ? AND r.plan_id IN (
                   SELECT id FROM plan_documents WHERE type='scheme' AND owner_id = ?)""",
            (next_week, current_owner_id(), current_owner_id()),
        ).fetchone()
        nc = conn.execute(
            """SELECT COUNT(*) n FROM record_of_work_rows r
               JOIN plan_documents pd ON pd.id=r.plan_id
               WHERE r.week=? AND r.origin='carry-over' AND pd.owner_id = ?""",
            (next_week, current_owner_id()),
        ).fetchone()
    planned_next = int(np["n"] if np else 0)
    carry_next = int(nc["n"] if nc else 0)
    next_total = planned_next + carry_next

    total_planned = sum(e["planned"] for e in by_subject if e["rowExists"])
    total_taught = sum(e["taught"] for e in by_subject if e["rowExists"])
    total_partial = sum(e["partially"] for e in by_subject if e["rowExists"])
    total_not = sum(e["notTaught"] for e in by_subject if e["rowExists"])
    total_carry = sum(e["carryOver"] for e in by_subject if e["rowExists"])
    no_row = [e for e in by_subject if not e["rowExists"]]
    statuses = [e["status"] for e in by_subject]
    summary = {
        "planned": total_planned,
        "taught": total_taught,
        "partially": total_partial,
        "notTaught": total_not,
        "carryOver": total_carry,
        "coveragePct": coverage_pct(total_taught, total_partial, total_planned),
        "onTrack": statuses.count("On Track"),
        "behind": statuses.count("Behind"),
        "complete": statuses.count("Complete"),
        "gapsThisWeek": len([g for g in gaps if g["week"] == current_week]),
        "withoutRow": len(no_row),
    }

    # Teacher term reflections (one per plan/term/year).
    with db.connect() as conn:
        refl_rows = conn.execute(
            "SELECT plan_id, term, year, reflection, updated_at FROM term_reflections "
            "WHERE owner_id = ?",
            (current_owner_id(),),
        ).fetchall()
    reflections = [
        {"planId": x["plan_id"], "term": x["term"], "year": x["year"],
         "reflection": x["reflection"], "updatedAt": x["updated_at"]}
        for x in refl_rows
    ]

    return {
        "summary": summary,
        "bySubject": sorted(by_subject, key=lambda e: (
            e["coveragePct"] is None, e["coveragePct"] if e["coveragePct"] is not None else 0,
            e["subject"],
        )),
        "byWeek": by_week,
        "gaps": gaps,
        "partiallyTaught": partials,
        "nextWeek": {
            "week": next_week,
            "planned": planned_next,
            "carryOver": carry_next,
            "total": next_total,
            "overloaded": next_total > planned_next + 3,
        },
        "filters": catalog,
        "appliedFilters": f,
        "currentWeek": current_week,
        "reflections": reflections,
        "lastUpdated": last_updated,
    }


# ---------------------------------------------------------------------------
# Teacher term reflection (read/write - the only write outside gap actions)
# ---------------------------------------------------------------------------


def get_reflection(plan_id: str, term: str = "", year: str = "") -> dict[str, Any]:
    with db.connect() as conn:
        r = conn.execute(
            "SELECT * FROM term_reflections WHERE plan_id=? AND term=? AND year=? AND owner_id=?",
            (plan_id, term, year, current_owner_id()),
        ).fetchone()
    return {
        "planId": plan_id, "term": term, "year": year,
        "reflection": r["reflection"] if r else "",
        "updatedAt": r["updated_at"] if r else "",
    }


def save_reflection(plan_id: str, term: str, year: str, reflection: str) -> dict[str, Any]:
    text = (reflection or "").strip()
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO term_reflections
               (id, plan_id, teacher, term, year, reflection, created_at, updated_at)
               VALUES (?,?,?,?,?,?,datetime('now'),datetime('now'))
               ON CONFLICT(plan_id, term, year) DO UPDATE SET
                 reflection=excluded.reflection, updated_at=datetime('now')""",
            (db.new_id(), plan_id, "", term, year, text),
        )
    invalidate()
    return get_reflection(plan_id, term, year)
