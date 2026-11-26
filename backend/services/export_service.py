"""Phase 7: Term Pack export jobs.

POST /api/export enqueues a job and returns a jobId immediately. A daemon thread
builds the PDF/ZIP, writing progress into export_jobs so the frontend can poll
GET /api/export/{jobId} every 2s. Files live under exports/{teacherId}/{planId}/
and are auto-deleted after 30 days. A hard 120s timeout prevents hangs.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import db
from auth_service import current_owner_id, reset_owner, set_owner
from services import term_pack_pdf

BACKEND_ROOT = Path(__file__).resolve().parent.parent
EXPORTS_DIR = Path(os.environ.get("MWALIMU_EXPORTS_DIR", str(BACKEND_ROOT / "exports")))
MAX_BYTES = 50 * 1024 * 1024
TIMEOUT_S = 120
RETENTION_DAYS = 30

_LOCK = threading.Lock()

DEFAULT_INCLUDES: dict[str, Any] = {
    "cover": True,
    "coverage": True,
    "scheme": True,
    "plans": {"include": True, "mode": "all", "weeks": [], "lessonIds": []},
    "notes": {"include": True, "mode": "all", "weeks": [], "lessonIds": []},
    "row": True,
    "citations": True,
    "includeDrafts": False,
    "includesAnswers": False,
    "includeAnswers": False,
    "includeVersionHistory": False,
    # Phase 10: learner names are opt-in only, and require typed confirmation.
    "progress": False,
    "progressConfirm": "",
}


def normalize_includes(raw: dict[str, Any] | None) -> dict[str, Any]:
    inc = dict(DEFAULT_INCLUDES)
    for k, v in (raw or {}).items():
        if k in ("plans", "notes") and isinstance(v, dict):
            inc[k] = {**DEFAULT_INCLUDES[k], **v}
        else:
            inc[k] = v
    return inc


def _job_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"], "planId": row["plan_id"], "teacherId": row["teacher_id"],
        "includes": json.loads(row["includes_json"] or "{}"), "format": row["format"],
        "status": row["status"], "progress": int(row["progress"]),
        "progressText": row["progress_text"],
        "fileUrl": row["file_url"], "fileName": row["file_name"],
        "filePath": row["file_path"],
        "fileSize": int(row["file_size"]), "pageCount": int(row["page_count"]),
        "manifest": json.loads(row["manifest_json"] or "{}"),
        "error": row["error"], "createdAt": row["created_at"], "updatedAt": row["updated_at"],
    }


def get_job(job_id: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM export_jobs WHERE id = ?", (job_id,)).fetchone()
    return _job_dict(row) if row else None


def list_history(plan_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    with db.connect() as conn:
        if plan_id:
            rows = conn.execute(
                "SELECT * FROM export_jobs WHERE plan_id = ? AND owner_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (plan_id, current_owner_id(), limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM export_jobs WHERE owner_id = ? ORDER BY created_at DESC LIMIT ?",
                (current_owner_id(), limit),
            ).fetchall()
    return [_job_dict(r) for r in rows]


def _update(job_id: str, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    with _LOCK, db.connect() as conn:
        conn.execute(
            f"UPDATE export_jobs SET {cols}, updated_at = datetime('now') WHERE id = ?",
            (*fields.values(), job_id),
        )


def _cleanup_old() -> None:
    """Delete export files older than 30 days (and jobs pointing at them)."""
    cutoff = time.time() - RETENTION_DAYS * 86400
    try:
        for path in EXPORTS_DIR.rglob("*"):
            if path.is_file() and path.stat().st_mtime < cutoff:
                try:
                    path.unlink()
                except OSError:
                    pass
    except OSError:
        pass
    with db.connect() as conn:
        conn.execute(
            "DELETE FROM export_jobs WHERE created_at < datetime('now', ?)",
            (f"-{RETENTION_DAYS} days",),
        )


def delete_job(job_id: str) -> bool:
    job = get_job(job_id)
    if not job:
        return False
    path = Path(job.get("filePath") or "") if job.get("filePath") else None
    if path and path.exists():
        try:
            path.unlink()
        except OSError:
            pass
    with db.connect() as conn:
        conn.execute("DELETE FROM export_jobs WHERE id = ?", (job_id,))
    return True


def _file_for(job_id: str, teacher_id: str, plan_id: str, filename: str) -> Path:
    safe_t = "".join(c for c in (teacher_id or "teacher") if c.isalnum() or c in "-_") or "teacher"
    safe_p = "".join(c for c in plan_id if c.isalnum() or c in "-_") or "plan"
    d = EXPORTS_DIR / safe_t / safe_p
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{job_id[:8]}-{filename}"


def create_job(plan_id: str, includes: dict[str, Any] | None, format: str,
               teacher_id: str = "") -> dict[str, Any]:
    clean = normalize_includes(includes)
    fmt = "zip" if str(format).lower() == "zip" else "pdf"
    job_id = str(uuid.uuid4())
    with _LOCK, db.connect() as conn:
        conn.execute(
            """INSERT INTO export_jobs
               (id, plan_id, teacher_id, includes_json, format, status, progress, progress_text)
               VALUES (?, ?, ?, ?, ?, 'queued', 0, 'Queued')""",
            (job_id, plan_id, teacher_id or "", json.dumps(clean), fmt),
        )
    threading.Thread(
        target=_build_worker,
        args=(job_id, plan_id, clean, fmt, teacher_id, current_owner_id()),
        daemon=True, name=f"export-{job_id[:8]}",
    ).start()
    _cleanup_old()
    return get_job(job_id)  # type: ignore[return-value]


def _build_worker(job_id: str, plan_id: str, includes: dict[str, Any],
                  fmt: str, teacher_id: str, owner_id: str = "") -> None:
    start = time.time()
    # ContextVars do not cross thread boundaries. Restore the requesting teacher
    # so owner-scoped data (including opt-in learner progress) is visible here.
    token = set_owner(owner_id)

    def progress(pct: int, text: str) -> None:
        if time.time() - start > TIMEOUT_S:
            raise TimeoutError("timeout")
        _update(job_id, status="building", progress=min(99, int(pct)), progress_text=text)

    try:
        _update(job_id, status="building", progress=1, progress_text="Starting")
        # Cover identity comes from the teacher's My Space profile, never from a
        # school account. No profile fields are invented when they are blank.
        from auth_service import get_user
        profile = get_user(teacher_id) if teacher_id else None
        if fmt == "zip":
            data, manifest, filename, meta = term_pack_pdf.build_zip(plan_id, includes, progress, profile)
        else:
            data, manifest, filename, meta = term_pack_pdf.build_term_pack(
                plan_id, includes, fmt, progress, profile
            )
        if len(data) > MAX_BYTES:
            raise ValueError("Export too large (over 50MB) - try exporting Weeks 1-4 only, then 5-8, etc.")
        path = _file_for(job_id, teacher_id, plan_id, filename)
        path.write_bytes(data)
        url = f"/api/export/{job_id}/file"
        _update(
            job_id, status="done", progress=100, progress_text="Done",
            file_name=filename, file_path=str(path), file_url=url,
            file_size=len(data), page_count=int(manifest.get("totalPages", 0)),
            manifest_json=json.dumps(manifest, ensure_ascii=False), error="",
        )
    except TimeoutError:
        _update(job_id, status="failed", progress_text="Export too large - try exporting Weeks 1-4 only, then 5-8, etc.",
                error="Export too large - try exporting Weeks 1-4 only, then 5-8, etc.")
    except Exception as exc:  # noqa: BLE001 — surface any build failure to the UI
        msg = str(exc) or exc.__class__.__name__
        _update(job_id, status="failed", progress_text="Export failed", error=msg)
    finally:
        reset_owner(token)
