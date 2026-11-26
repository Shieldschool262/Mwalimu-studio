"""Phase 9 - teacher-owned data export.

Produces a portable ZIP containing every Design, Scheme, Lesson Plan, Lesson Note,
ROW document and Export belonging to one teacher, plus a manifest. Nothing from any
other Workspace is ever read here.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import db


def _rows(conn: Any, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def export_all_data(user: dict[str, Any]) -> tuple[bytes, str]:
    owner = user["id"]
    buffer = io.BytesIO()
    manifest: dict[str, Any] = {
        "ownerId": owner,
        "teacher": {"name": user["name"], "email": user["email"], "tscNo": user["tscNo"]},
        "exportedAt": datetime.now().isoformat(timespec="seconds"),
        "app": "Mwalimu Studio",
        "files": [],
        "counts": {},
    }

    groups = [
        ("designs", "source_documents", "SELECT * FROM source_documents WHERE owner_id = ? ORDER BY created_at"),
        ("schemes", "plan_documents", "SELECT * FROM plan_documents WHERE owner_id = ? ORDER BY created_at"),
        ("lesson-plans", "lesson_plans", "SELECT * FROM lesson_plans WHERE owner_id = ? ORDER BY created_at"),
        ("lesson-notes", "lesson_notes", "SELECT * FROM lesson_notes WHERE owner_id = ? ORDER BY created_at"),
        ("row", "record_of_work_docs", "SELECT * FROM record_of_work_docs WHERE owner_id = ? ORDER BY created_at"),
        ("exports", "export_jobs", "SELECT * FROM export_jobs WHERE owner_id = ? ORDER BY created_at"),
        # Phase 10: learner data is private and only leaves My Space in this
        # teacher-initiated export. It is never part of a Term Pack by default.
        ("learners", "learners", "SELECT * FROM learners WHERE owner_id = ? ORDER BY created_at"),
        ("assessments", "assessment_records", "SELECT * FROM assessment_records WHERE owner_id = ? ORDER BY created_at"),
        ("assessment-audit", "assessment_audit", "SELECT * FROM assessment_audit WHERE owner_id = ? ORDER BY changed_at"),
        ("ieps", "ieps", "SELECT * FROM ieps WHERE owner_id = ? ORDER BY created_at"),
        ("iep-reviews", "iep_reviews", "SELECT * FROM iep_reviews WHERE owner_id = ? ORDER BY created_at"),
    ]

    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        with db.connect() as conn:
            for label, _table, sql in groups:
                rows = _rows(conn, sql, (owner,))
                manifest["counts"][label] = len(rows)
                name = f"{label}.json"
                zf.writestr(name, json.dumps(rows, ensure_ascii=False, indent=2))
                manifest["files"].append({"path": name, "kind": label, "count": len(rows)})

                ids = [r["id"] for r in rows]
                if label == "designs" and ids:
                    children = [
                        dict(c)
                        for did in ids
                        for c in conn.execute(
                            "SELECT * FROM source_chunks WHERE document_id = ? ORDER BY ord", (did,)
                        ).fetchall()
                    ]
                    zf.writestr("design-chunks.json", json.dumps(children, ensure_ascii=False, indent=2))
                    manifest["files"].append(
                        {"path": "design-chunks.json", "kind": "design-chunks", "count": len(children)}
                    )
                if label == "schemes" and ids:
                    sections = [
                        dict(s)
                        for pid in ids
                        for s in conn.execute(
                            "SELECT * FROM plan_sections WHERE plan_id = ? ORDER BY ord", (pid,)
                        ).fetchall()
                    ]
                    zf.writestr("scheme-sections.json", json.dumps(sections, ensure_ascii=False, indent=2))
                    manifest["files"].append(
                        {"path": "scheme-sections.json", "kind": "scheme-sections", "count": len(sections)}
                    )
                if label == "row" and ids:
                    row_rows = [
                        dict(x)
                        for did in ids
                        for x in conn.execute(
                            "SELECT * FROM record_of_work_rows WHERE doc_id = ? ORDER BY week, lesson", (did,)
                        ).fetchall()
                    ]
                    zf.writestr("row-rows.json", json.dumps(row_rows, ensure_ascii=False, indent=2))
                    manifest["files"].append(
                        {"path": "row-rows.json", "kind": "row-rows", "count": len(row_rows)}
                    )

            reflections = _rows(
                conn, "SELECT * FROM term_reflections WHERE owner_id = ? ORDER BY updated_at", (owner,)
            )
            manifest["counts"]["reflections"] = len(reflections)
            zf.writestr("reflections.json", json.dumps(reflections, ensure_ascii=False, indent=2))
            manifest["files"].append(
                {"path": "reflections.json", "kind": "reflections", "count": len(reflections)}
            )

            for job in _rows(conn, "SELECT * FROM export_jobs WHERE owner_id = ?", (owner,)):
                stored = job.get("file_path") or ""
                if stored and Path(stored).exists():
                    arc = f"export-files/{Path(stored).name}"
                    zf.write(Path(stored), arc)
                    manifest["files"].append({"path": arc, "kind": "export-file", "jobId": job["id"]})

            zf.writestr(
                "PRIVACY.txt",
                "This file contains learner names and assessment records. Keep it private.\n"
                "Do NOT share it publicly. It belongs to the teacher named in manifest.json.\n",
            )
            manifest["files"].append({"path": "PRIVACY.txt", "kind": "notice"})
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in user["name"])[:40] or "teacher"
    return buffer.getvalue(), f"my-space-{safe}-{stamp}.zip"
