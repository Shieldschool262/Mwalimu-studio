"""Mwalimu Studio API - phases 0-10 (Phase 10: My Learners, Assessment and IEP)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import time

from fastapi import Body, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

import auth_service as auth
from db import PARSER_VERSION, init_db, upload_path
from services import (
    ai_service, dashboard_service, dashboard_pdf, export_service, learner_service,
    progress_pdf, record_of_work_service as row_service, settings_service,
)
from services.library_service import (
    delete_library_document,
    get_library_document,
    list_library,
    reparse_library_document,
    save_document_to_library,
    search_library,
)
from services.lesson_plan_service import (
    ai_draft,
    ai_split_suggest,
    create_lesson_plans,
    create_lesson_version,
    delete_lesson_plan,
    diff_lesson_version,
    edit_lesson_header,
    edit_lesson_section,
    fix_lesson_slo,
    get_lesson_plan,
    lesson_picker,
    list_lesson_plans,
    list_lesson_versions,
    reset_lesson_header,
    reset_lesson_section,
    restore_lesson_version,
    search_examples,
    set_lesson_status,
)
from services.lesson_notes_service import (
    add_note_source,
    ai_accept_all,
    ai_draft_note,
    create_lesson_notes,
    create_note_version,
    delete_lesson_note,
    diff_note_version,
    edit_note_header,
    edit_note_section,
    get_lesson_note,
    get_note_version,
    insert_web_example,
    list_lesson_notes,
    list_note_versions,
    notes_picker,
    reset_note_section,
    restore_note_version,
    search_note_examples,
    set_note_status,
    web_search_log,
)
from services.plan_service import (
    bulk_resources,
    clear_reflections,
    create_plan,
    create_plan_version,
    delete_plan,
    diff_plan_version,
    duplicate_plan,
    edit_header,
    edit_section,
    extend_row_lessons,
    rebalance_group,
    reset_section_to_appendix,
    reset_section_to_source,
    restore_plan_version,
    get_plan,
    get_plan_version,
    list_plan_versions,
    list_plans,
    load_template,
    set_plan_status,
    undo_last_edit,
    unlock_plan,
    validate_plan,
    vetting_catalog,
)
from services.parse_service import (
    ARCHETYPE_LABEL,
    ARCHETYPES,
    ENGINE_GRADE,
    approve_all,
    approve_strand,
    correct_chunk,
    get_job,
    safe_parse,
)

APP_ROOT = Path(__file__).resolve().parent

app = FastAPI(title="Mwalimu Studio API", version="1.0.0-phase9")

PUBLIC_API = {
    "/api/auth/signup", "/api/auth/login", "/api/auth/forgot", "/api/auth/reset",
}


@app.middleware("http")
async def workspace_gate(request: Request, call_next):
    """Authenticate every API call and refuse access to another teacher's resource."""
    path = request.url.path.rstrip("/") or "/"
    owner = ""
    if path.startswith("/api/") and path not in PUBLIC_API:
        payload = auth.decode_token(auth.token_from_request(request))
        user = auth.get_user(payload["sub"]) if payload else None
        if not user:
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        owner = user["id"]
    # The DB-level ownership guard needs the teacher context even while the
    # middleware resolves the URL resource, so set it before that lookup.
    ctx_token = auth.set_owner(owner)
    try:
        if owner:
            resource = auth.resource_for_path(path)
            if resource:
                actual = auth.owner_of_resource(*resource)
                if actual and actual != owner:
                    return JSONResponse({"detail": "Not your content"}, status_code=403)
        response = await call_next(request)
    finally:
        auth.reset_owner(ctx_token)
    # Refresh a near-expiry token on activity so active teachers stay signed in.
    if owner and payload:
        try:
            remaining = int(payload["exp"]) - int(time.time())
            if 0 < remaining < 24 * 3600:
                token, _max_age, _exp = auth.issue_token(
                    owner, payload.get("email", ""), bool(payload.get("remember"))
                )
                auth.set_session_cookie(response, token, bool(payload.get("remember")))
        except (KeyError, ValueError, TypeError):
            pass
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    message = auth.migrate_legacy_content()
    if message:
        print(f"[Phase 9] {message}", flush=True)


# ---------------------------------------------------------------------------
# Phase 9 - individual teacher auth. No shared school view or elevated roles.
# ---------------------------------------------------------------------------
def _current_user(request: Request) -> dict:
    user = auth.user_from_request(request)
    if not user:
        raise HTTPException(401, "Not authenticated")
    return user


def _assert_owned(kind: str, ident: str) -> None:
    """Guard identifiers supplied in a JSON body or query string, not in the URL."""
    if not ident:
        return
    actual = auth.owner_of_resource(kind, ident)
    if actual and actual != auth.current_owner_id():
        raise HTTPException(status_code=403, detail="Not your content")


@app.post("/api/auth/signup")
def auth_signup(body: dict = Body(default_factory=dict)) -> JSONResponse:
    user = auth.signup(body)
    token, _max_age, _exp = auth.issue_token(user["id"], user["email"], False)
    response = JSONResponse(user)
    auth.set_session_cookie(response, token, False)
    return response


@app.post("/api/auth/login")
def auth_login(request: Request, body: dict = Body(default_factory=dict)) -> JSONResponse:
    ip = request.client.host if request.client else "unknown"
    user, token, remember = auth.login(body, ip)
    response = JSONResponse(user)
    auth.set_session_cookie(response, token, remember)
    return response


@app.post("/api/auth/logout")
def auth_logout() -> JSONResponse:
    response = JSONResponse({"ok": True})
    auth.clear_session_cookie(response)
    return response


@app.post("/api/auth/forgot")
def auth_forgot(body: dict = Body(default_factory=dict)) -> JSONResponse:
    return JSONResponse(auth.forgot_password(str(body.get("email") or "")))


@app.post("/api/auth/reset")
def auth_reset(body: dict = Body(default_factory=dict)) -> JSONResponse:
    auth.reset_password(body)
    return JSONResponse({"ok": True})


@app.get("/api/auth/me")
def auth_me(request: Request) -> JSONResponse:
    return JSONResponse(_current_user(request))


@app.put("/api/auth/me")
def auth_update_me(request: Request, body: dict = Body(default_factory=dict)) -> JSONResponse:
    return JSONResponse(auth.update_profile(_current_user(request)["id"], body))


@app.post("/api/auth/change-password")
def auth_change_password(request: Request, body: dict = Body(default_factory=dict)) -> JSONResponse:
    auth.change_password(_current_user(request)["id"], body)
    return JSONResponse({"ok": True})


@app.delete("/api/auth/me")
def auth_delete_me(request: Request, body: dict = Body(default_factory=dict)) -> JSONResponse:
    auth.delete_account(_current_user(request)["id"], str(body.get("confirmation") or ""))
    response = JSONResponse({"ok": True})
    auth.clear_session_cookie(response)
    return response


@app.get("/api/my-space/export-all")
def my_space_export_all(request: Request) -> Response:
    from services.my_space_service import export_all_data

    user = _current_user(request)
    payload, filename = export_all_data(user)
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/navigation/status")
def navigation_status() -> JSONResponse:
    """Read-only prerequisite counts used only to enable Next buttons in the workflow."""
    import db as _db

    owner = auth.current_owner_id()
    with _db.connect() as conn:
        def count(sql: str) -> int:
            return int(conn.execute(sql, (owner,)).fetchone()[0])
        schemes = count(
            "SELECT COUNT(*) FROM plan_documents WHERE owner_id = ? AND type = 'scheme'")
        plans = count("SELECT COUNT(*) FROM lesson_plans WHERE owner_id = ?")
        notes = count("SELECT COUNT(*) FROM lesson_notes WHERE owner_id = ?")
        row = count("SELECT COUNT(*) FROM record_of_work_docs WHERE owner_id = ?")
    return JSONResponse({"schemes": schemes, "plans": plans, "notes": notes, "row": row})


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "app": "Mwalimu Studio",
        "phase": "0+1+2+3+4+5+6+7+8+9+10",
        "parserVersion": PARSER_VERSION,
        "engineGrade": ENGINE_GRADE,
        "archetypes": [
            {"id": k, "label": ARCHETYPE_LABEL.get(k, k), "name": v.get("name")}
            for k, v in ARCHETYPES.items()
        ],
    }


# ---------------------------------------------------------------------------
# Settings - AI providers + web search providers
# ---------------------------------------------------------------------------


def _settings_payload() -> dict:
    cfg = settings_service.public_settings()
    search_cfg = settings_service.get_settings()["search"]
    provider = str(search_cfg.get("provider") or "off")
    meta = settings_service.provider_by_id("search", provider)
    return {
        "settings": cfg,
        "catalog": settings_service.catalog(),
        "ai": ai_service.ai_status(),
        "search": {
            "provider": provider,
            "label": meta.get("label"),
            "available": provider != "off"
            and (not meta.get("keyRequired") or bool(search_cfg.get("apiKey"))),
            "message": (
                "Web search is turned off in Settings."
                if provider == "off"
                else f"Web search ready · {meta.get('label')}"
            ),
        },
    }


@app.get("/api/settings")
def settings_get() -> JSONResponse:
    """Masked settings + provider catalogues + live status."""
    return JSONResponse(_settings_payload())


@app.put("/api/settings")
def settings_put(body: dict = Body(default_factory=dict)) -> JSONResponse:
    """Persist AI / web search config to backend/settings.json."""
    try:
        settings_service.save_settings(body or {})
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return JSONResponse(_settings_payload())


@app.post("/api/settings/reset")
def settings_reset() -> JSONResponse:
    settings_service.reset_settings()
    return JSONResponse(_settings_payload())


@app.post("/api/settings/test/ai")
def settings_test_ai(body: dict = Body(default_factory=dict)) -> JSONResponse:
    """Send one tiny real request to the configured (or unsaved) AI provider."""
    override = (body or {}).get("ai")
    return JSONResponse(ai_service.test_ai(override if isinstance(override, dict) else None))


@app.post("/api/settings/test/search")
def settings_test_search(body: dict = Body(default_factory=dict)) -> JSONResponse:
    """Run one real search against the configured (or unsaved) search provider."""
    payload = body or {}
    override = payload.get("search")
    return JSONResponse(
        ai_service.test_search(
            str(payload.get("query") or ""),
            override if isinstance(override, dict) else None,
        )
    )


@app.post("/api/settings/models")
def settings_models(body: dict = Body(default_factory=dict)) -> JSONResponse:
    """List model IDs available to the current (or unsaved) key."""
    payload = body or {}
    provider = str(payload.get("provider") or "") or None
    override = payload.get("ai") if isinstance(payload.get("ai"), dict) else None
    try:
        return JSONResponse(ai_service.list_ai_models(provider, override))
    except (ai_service.AIError, ai_service.AIUnavailable) as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not list models: {e}") from e


# ---------------------------------------------------------------------------
# Phase 1 - parser as a service
# ---------------------------------------------------------------------------


@app.post("/api/parse")
async def parse(
    file: UploadFile = File(...),
    grade: Optional[str] = Form(None),
    subject: Optional[str] = Form(None),
    override_archetype: Optional[str] = Form(None),
):
    """Upload one curriculum design PDF -> parsed SourceDocument + SourceChunks."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Upload a PDF file.")
    if override_archetype and override_archetype not in ARCHETYPES:
        raise HTTPException(status_code=400, detail=f"Unknown archetype '{override_archetype}'.")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    job = safe_parse(data, file.filename)
    if job.get("status") == "Failed":
        raise HTTPException(status_code=422, detail=job.get("error") or "Parse failed.")

    if grade or subject:
        from db import connect

        with connect() as conn:
            conn.execute(
                "UPDATE source_documents SET grade = COALESCE(?, grade), subject = COALESCE(?, subject) WHERE id = ?",
                (grade or None, subject or None, job["id"]),
            )
        job = get_job(job["id"])

    return JSONResponse(job)


@app.get("/api/parse/{job_id}")
def fetch_job(job_id: str) -> JSONResponse:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Parse job not found.")
    return JSONResponse(job)


@app.post("/api/parse/{job_id}/chunks/{chunk_id}/correct")
def correct(job_id: str, chunk_id: str, patch: dict = Body(default_factory=dict)) -> JSONResponse:
    """Inline correction. Accepts {field, newValue} or {structuredFields:{...}} or {undoField}."""
    job = correct_chunk(job_id, chunk_id, patch or {})
    if job is None:
        raise HTTPException(status_code=404, detail="Chunk not found for this parse job.")
    return JSONResponse(job)


@app.post("/api/parse/{job_id}/approve-all")
def approve_everything(job_id: str, min_confidence: float = Body(0.9, embed=True)) -> JSONResponse:
    """Approve every chunk with confidence >= min_confidence (default 0.9)."""
    job, approved, kept = approve_all(job_id, float(min_confidence))
    if job is None:
        raise HTTPException(status_code=404, detail="Parse job not found.")
    return JSONResponse({**job, "approvedNow": approved, "stillNeedsReview": kept})


@app.post("/api/parse/{job_id}/approve-strand")
def approve_one_strand(job_id: str, body: dict = Body(default_factory=dict)) -> JSONResponse:
    """Approve every chunk under one strand header."""
    job, count = approve_strand(job_id, body.get("strandCode"), body.get("strand"))
    if job is None:
        raise HTTPException(status_code=404, detail="Parse job not found.")
    return JSONResponse({**job, "approvedNow": count})


@app.post("/api/parse/{job_id}/approve")
def approve(job_id: str, save_with_gaps: bool = Body(False, embed=True)) -> JSONResponse:
    """Approve the document (kept for Phase 1 clients)."""
    payload, errors = save_document_to_library(job_id, bool(save_with_gaps))
    if payload is None:
        raise HTTPException(status_code=409, detail=" ".join(errors) or "Cannot approve this document.")
    return JSONResponse(payload)


# ---------------------------------------------------------------------------
# Phase 2 - my library
# ---------------------------------------------------------------------------


@app.get("/api/library")
def library(status: Optional[str] = Query(None)) -> JSONResponse:
    return JSONResponse(list_library(status))


@app.get("/api/library/search")
def library_search(
    q: str = Query("", description="Free text: subject, strand, sub-strand, outcome, KIQ"),
    grade: Optional[str] = None,
    subject: Optional[str] = None,
    status: Optional[str] = None,
) -> JSONResponse:
    return JSONResponse(search_library(q, grade, subject, status))


@app.post("/api/library/save")
def library_save(body: dict = Body(default_factory=dict)) -> JSONResponse:
    job_id = body.get("jobId") or body.get("documentId")
    if not job_id:
        raise HTTPException(status_code=400, detail="jobId is required.")
    _assert_owned("source_documents", str(job_id))
    payload, errors = save_document_to_library(str(job_id), bool(body.get("saveWithGaps")))
    if payload is None:
        raise HTTPException(status_code=409, detail=" ".join(errors) or "Cannot save this document.")
    return JSONResponse(payload)


@app.get("/api/library/{doc_id}")
def library_document(doc_id: str) -> JSONResponse:
    doc = get_library_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return JSONResponse(doc)


@app.get("/api/library/{doc_id}/file")
def library_file(doc_id: str):
    """Serve the original PDF so the teacher can check any page."""
    path = upload_path(doc_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Original PDF not found.")
    return FileResponse(path, media_type="application/pdf", filename=f"{doc_id}.pdf")


@app.post("/api/library/{doc_id}/reparse")
def library_reparse(doc_id: str) -> JSONResponse:
    payload, errors = reparse_library_document(doc_id)
    if payload is None:
        raise HTTPException(status_code=404 if "not found" in " ".join(errors).lower() else 409,
                            detail=" ".join(errors) or "Re-parse failed.")
    return JSONResponse(payload)


@app.delete("/api/library/{doc_id}")
def library_delete(doc_id: str) -> JSONResponse:
    if not delete_library_document(doc_id):
        raise HTTPException(status_code=404, detail="Document not found.")
    return JSONResponse({"deleted": True, "documentId": doc_id})


@app.get("/api/library/{doc_id}/export")
def library_export(doc_id: str) -> JSONResponse:
    """Download-ready JSON of one document and its chunks."""
    doc = get_library_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return JSONResponse(
        {
            "document": {k: v for k, v in doc.items() if k not in ("chunks", "tree")},
            "strands": doc["tree"],
            "chunks": doc["chunks"],
        },
        headers={
            "Content-Disposition": f'attachment; filename="{doc_id}.json"',
        },
    )


# ---------------------------------------------------------------------------
# Phase 3 - planning workspace
# ---------------------------------------------------------------------------


@app.get("/api/plans/template/{version}")
def plan_template(version: str = "cbe-scheme-v1") -> JSONResponse:
    return JSONResponse(load_template(version))


@app.get("/api/plans/sources")
def plan_sources(grade: Optional[str] = None, subject: Optional[str] = None) -> JSONResponse:
    """Chunks available to build a plan from, with vetting state."""
    return JSONResponse(vetting_catalog(grade, subject))


@app.post("/api/plans")
def plans_create(body: dict = Body(default_factory=dict)) -> JSONResponse:
    for chunk_id in (body or {}).get("sourceChunkIds") or []:
        _assert_owned("chunk", str(chunk_id))
    plan, errors = create_plan(body or {})
    if plan is None:
        # 422: the generation guard refused (unvetted or missing core field).
        raise HTTPException(status_code=422, detail=" | ".join(errors) or "Cannot generate this plan.")
    return JSONResponse(plan)


@app.get("/api/plans")
def plans_list() -> JSONResponse:
    return JSONResponse(list_plans())


@app.get("/api/plans/{plan_id}")
def plans_get(plan_id: str) -> JSONResponse:
    plan = get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found.")
    return JSONResponse(plan)


# Phase 10 RLS acceptance uses the generic "schemes" naming. These aliases are
# read-only and resolve through the same owner-filtered service + URL guard.
@app.get("/api/schemes")
def schemes_list() -> JSONResponse:
    return JSONResponse(list_plans())


@app.get("/api/schemes/{plan_id}")
def schemes_get(plan_id: str) -> JSONResponse:
    plan = get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Scheme not found.")
    return JSONResponse(plan)


@app.delete("/api/plans/{plan_id}")
def plans_delete(plan_id: str) -> JSONResponse:
    if not delete_plan(plan_id):
        raise HTTPException(status_code=404, detail="Plan not found.")
    return JSONResponse({"deleted": True, "planId": plan_id})


@app.post("/api/plans/{plan_id}/duplicate")
def plans_duplicate(plan_id: str, body: dict = Body(default_factory=dict)) -> JSONResponse:
    plan, errors = duplicate_plan(plan_id, (body or {}).get("term"))
    if plan is None:
        raise HTTPException(status_code=404, detail=" ".join(errors) or "Plan not found.")
    return JSONResponse(plan)


@app.post("/api/plans/{plan_id}/status")
def plans_status(plan_id: str, body: dict = Body(default_factory=dict)) -> JSONResponse:
    plan, errors = set_plan_status(plan_id, (body or {}).get("status") or "Draft")
    if plan is None:
        raise HTTPException(status_code=404 if "not found" in " ".join(errors).lower() else 400,
                            detail=" ".join(errors))
    return JSONResponse(plan)


@app.post("/api/plans/{plan_id}/sections/{section_id}/edit")
def plans_edit_section(plan_id: str, section_id: str, body: dict = Body(default_factory=dict)) -> JSONResponse:
    plan, errors = edit_section(plan_id, section_id, body or {})
    if plan is None:
        raise HTTPException(
            status_code=404 if "not found" in " ".join(errors).lower() else 422,
            detail=" ".join(errors) or "Section not found.",
        )
    return JSONResponse(plan)


@app.post("/api/plans/{plan_id}/sections/{section_id}/reset-appendix")
def plans_reset_appendix(
    plan_id: str, section_id: str, body: dict = Body(default_factory=dict)
) -> JSONResponse:
    """[Reset to Appendix] - restore one row's Resources/Assessment from the appendix."""
    field = (body or {}).get("field") or ""
    plan, errors = reset_section_to_appendix(plan_id, section_id, field)
    if plan is None:
        raise HTTPException(status_code=404, detail=" ".join(errors) or "Section not found.")
    return JSONResponse(plan)


@app.post("/api/plans/{plan_id}/rebalance")
def plans_rebalance(plan_id: str, body: dict = Body(default_factory=dict)) -> JSONResponse:
    """[Re-balance Outcomes] - re-run the weekly split for one sub-strand."""
    code = (body or {}).get("subStrandCode") or ""
    if not code:
        raise HTTPException(status_code=400, detail="subStrandCode is required.")
    lp = (body or {}).get("lessonsPerWeek")
    plan, errors = rebalance_group(plan_id, code, int(lp) if lp else None)
    if plan is None:
        raise HTTPException(status_code=404, detail=" ".join(errors) or "Sub-strand not found.")
    return JSONResponse(plan)


@app.post("/api/plans/{plan_id}/header")
def plans_edit_header(plan_id: str, body: dict = Body(default_factory=dict)) -> JSONResponse:
    plan, errors = edit_header(plan_id, body or {})
    if plan is None:
        raise HTTPException(status_code=404, detail=" ".join(errors) or "Plan not found.")
    return JSONResponse(plan)


@app.get("/api/plans/{plan_id}/export.pdf")
def plans_export_pdf(plan_id: str) -> Response:
    """Landscape A4 PDF with the header repeated on every page."""
    plan = get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found.")
    from services.scheme_pdf import render_scheme_pdf

    pdf = render_scheme_pdf(plan)
    safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in plan["title"])[:60].strip()
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe or "scheme"}.pdf"'},
    )


# ---------------------------------------------------------------------------
# Phase 4 - scheme version history, undo, bulk edits, lesson plans
# ---------------------------------------------------------------------------


@app.post("/api/plans/{plan_id}/versions")
def plans_create_version(plan_id: str, body: dict = Body(default_factory=dict)) -> JSONResponse:
    """[Save Version] - snapshot the whole plan as an append-only version."""
    comment = str((body or {}).get("comment") or "").strip()
    if not comment:
        raise HTTPException(status_code=422, detail="A comment is required, e.g. 'Fixed Week 3 outcomes'.")
    plan = get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found.")
    errors = validate_plan(plan)
    if errors:
        raise HTTPException(status_code=422, detail=" | ".join(errors))
    version, errors = create_plan_version(plan_id, comment)
    if version is None:
        raise HTTPException(status_code=422, detail=" | ".join(errors))
    return JSONResponse({**version, "plan": get_plan(plan_id)})


@app.get("/api/plans/{plan_id}/versions")
def plans_list_versions(plan_id: str) -> JSONResponse:
    if get_plan(plan_id) is None:
        raise HTTPException(status_code=404, detail="Plan not found.")
    return JSONResponse(list_plan_versions(plan_id))


@app.get("/api/plans/{plan_id}/versions/{version_id}")
def plans_get_version(plan_id: str, version_id: str) -> JSONResponse:
    version = get_plan_version(plan_id, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    return JSONResponse(version)


@app.post("/api/plans/{plan_id}/versions/{version_id}/restore")
def plans_restore_version(plan_id: str, version_id: str) -> JSONResponse:
    """Restore content as a NEW version - older versions are never deleted."""
    plan, errors = restore_plan_version(plan_id, version_id)
    if plan is None:
        raise HTTPException(
            status_code=404 if "not found" in " ".join(errors).lower() else 422,
            detail=" | ".join(errors),
        )
    return JSONResponse(plan)


@app.get("/api/plans/{plan_id}/versions/{version_id}/diff")
def plans_diff_version(plan_id: str, version_id: str) -> JSONResponse:
    diff = diff_plan_version(plan_id, version_id)
    if diff is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    return JSONResponse(diff)


@app.post("/api/plans/{plan_id}/undo")
def plans_undo(plan_id: str) -> JSONResponse:
    """[↩ Undo Last Edit] - restore the previous value of the most recent edit."""
    plan, errors = undo_last_edit(plan_id)
    if plan is None:
        raise HTTPException(
            status_code=404 if "not found" in " ".join(errors).lower() else 422,
            detail=" | ".join(errors),
        )
    return JSONResponse(plan)


@app.post("/api/plans/{plan_id}/unlock")
def plans_unlock(plan_id: str) -> JSONResponse:
    """[Unlock to Edit] - Final -> Draft, recorded as a new version."""
    plan, errors = unlock_plan(plan_id)
    if plan is None:
        raise HTTPException(
            status_code=404 if "not found" in " ".join(errors).lower() else 422,
            detail=" | ".join(errors),
        )
    return JSONResponse(plan)


@app.post("/api/plans/{plan_id}/sections/{section_id}/reset-source")
def plans_reset_source(plan_id: str, section_id: str) -> JSONResponse:
    """[↩ Reset Row to Source] - restore vetted cells but keep the teacher's Reflection."""
    plan, errors = reset_section_to_source(plan_id, section_id)
    if plan is None:
        raise HTTPException(
            status_code=404 if "not found" in " ".join(errors).lower() else 422,
            detail=" | ".join(errors),
        )
    return JSONResponse(plan)


@app.post("/api/plans/{plan_id}/sections/{section_id}/extend")
def plans_extend_section(
    plan_id: str, section_id: str, body: dict = Body(default_factory=dict)
) -> JSONResponse:
    """[Extend to N lessons] - widen one row so no atomic skill spills into next week."""
    plan, errors = extend_row_lessons(plan_id, section_id, (body or {}).get("lessonCount"))
    if plan is None:
        raise HTTPException(
            status_code=404 if "not found" in " ".join(errors).lower() else 422,
            detail=" | ".join(errors),
        )
    return JSONResponse(plan)


@app.post("/api/plans/{plan_id}/bulk-resources")
def plans_bulk_resources(plan_id: str, body: dict = Body(default_factory=dict)) -> JSONResponse:
    """[Edit Resources for All Weeks] for one sub-strand (UI confirms first)."""
    plan, errors = bulk_resources(
        plan_id, str((body or {}).get("subStrandCode") or ""), str((body or {}).get("resources") or "")
    )
    if plan is None:
        raise HTTPException(
            status_code=404 if "not found" in " ".join(errors).lower() else 422,
            detail=" | ".join(errors),
        )
    return JSONResponse(plan)


@app.post("/api/plans/{plan_id}/clear-reflections")
def plans_clear_reflections(plan_id: str) -> JSONResponse:
    """[Clear All Reflections] - clears every row's teacher reflection."""
    plan, errors = clear_reflections(plan_id)
    if plan is None:
        raise HTTPException(
            status_code=404 if "not found" in " ".join(errors).lower() else 422,
            detail=" | ".join(errors),
        )
    return JSONResponse(plan)


@app.get("/api/plans/{plan_id}/sections/{section_id}/lessons")
def plans_lesson_picker(plan_id: str, section_id: str) -> JSONResponse:
    """Lesson picker data for one scheme row: lessons, focus, created ✓, vetting guard."""
    with_plan = get_plan(plan_id)
    if with_plan is None:
        raise HTTPException(status_code=404, detail="Plan not found.")
    picker, errors = lesson_picker(section_id)
    if picker is None:
        raise HTTPException(status_code=404, detail=" | ".join(errors))
    if picker["planId"] != plan_id:
        raise HTTPException(status_code=404, detail="Section not found in this plan.")
    return JSONResponse(picker)


# ---------------------------------------------------------------------------
# Phase 4 - KICD lesson plans (one week = N independent plans)
# ---------------------------------------------------------------------------


@app.post("/api/lesson-plans")
def lesson_plans_create(body: dict = Body(default_factory=dict)) -> JSONResponse:
    _assert_owned("plan_section", str((body or {}).get("schemeRowId") or (body or {}).get("sectionId") or ""))
    created, errors = create_lesson_plans(body or {})
    if not created:
        raise HTTPException(status_code=422, detail=" | ".join(errors) or "Cannot create lesson plan.")
    return JSONResponse({"created": created, "count": len(created), "errors": errors})


@app.get("/api/lesson-plans")
def lesson_plans_list(
    planId: Optional[str] = None, sectionId: Optional[str] = None
) -> JSONResponse:
    return JSONResponse(list_lesson_plans(planId, sectionId))


@app.get("/api/lesson-plans/{lesson_id}")
def lesson_plans_get(lesson_id: str) -> JSONResponse:
    plan = get_lesson_plan(lesson_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Lesson plan not found.")
    return JSONResponse(plan)


@app.delete("/api/lesson-plans/{lesson_id}")
def lesson_plans_delete(lesson_id: str) -> JSONResponse:
    if not delete_lesson_plan(lesson_id):
        raise HTTPException(status_code=404, detail="Lesson plan not found.")
    return JSONResponse({"deleted": True, "lessonId": lesson_id})


@app.post("/api/lesson-plans/{lesson_id}/sections/{section_id}/edit")
def lesson_plans_edit_section(
    lesson_id: str, section_id: str, body: dict = Body(default_factory=dict)
) -> JSONResponse:
    plan, errors = edit_lesson_section(lesson_id, section_id, body or {})
    if plan is None:
        raise HTTPException(
            status_code=404 if "not found" in " ".join(errors).lower() else 422,
            detail=" | ".join(errors),
        )
    return JSONResponse(plan)


@app.post("/api/lesson-plans/{lesson_id}/sections/{section_id}/reset")
def lesson_plans_reset_section(lesson_id: str, section_id: str) -> JSONResponse:
    """[Reset to Source] - restore one field, or clear a teacher-filled field."""
    plan, errors = reset_lesson_section(lesson_id, section_id)
    if plan is None:
        raise HTTPException(
            status_code=404 if "not found" in " ".join(errors).lower() else 422,
            detail=" | ".join(errors),
        )
    return JSONResponse(plan)


@app.post("/api/lesson-plans/{lesson_id}/sections/{section_id}/reset-source")
def lesson_plans_reset_section_source(lesson_id: str, section_id: str) -> JSONResponse:
    """Alias for [Reset to Source] used by the section toolbar."""
    return lesson_plans_reset_section(lesson_id, section_id)


@app.post("/api/lesson-plans/{lesson_id}/slo/fix")
@app.post("/api/lesson-plans/{lesson_id}/fix-slo")
def lesson_plans_fix_slo(lesson_id: str) -> JSONResponse:
    """[Fix Automatically] - convert a sub-strand SLO to the lesson-plan heading."""
    plan, errors = fix_lesson_slo(lesson_id)
    if plan is None:
        raise HTTPException(
            status_code=404 if "not found" in " ".join(errors).lower() else 422,
            detail=" | ".join(errors),
        )
    return JSONResponse(plan)


@app.post("/api/lesson-plans/{lesson_id}/header")
def lesson_plans_edit_header(lesson_id: str, body: dict = Body(default_factory=dict)) -> JSONResponse:
    plan, errors = edit_lesson_header(lesson_id, body or {})
    if plan is None:
        raise HTTPException(
            status_code=404 if "not found" in " ".join(errors).lower() else 422,
            detail=" | ".join(errors),
        )
    return JSONResponse(plan)


@app.post("/api/lesson-plans/{lesson_id}/header/reset")
def lesson_plans_reset_header(
    lesson_id: str, body: dict = Body(default_factory=dict)
) -> JSONResponse:
    """[Reset to Source] for one header field."""
    plan, errors = reset_lesson_header(lesson_id, str((body or {}).get("field") or ""))
    if plan is None:
        raise HTTPException(
            status_code=404 if "not found" in " ".join(errors).lower() else 422,
            detail=" | ".join(errors),
        )
    return JSONResponse(plan)


@app.post("/api/lesson-plans/{lesson_id}/status")
def lesson_plans_status(lesson_id: str, body: dict = Body(default_factory=dict)) -> JSONResponse:
    plan, errors = set_lesson_status(lesson_id, str((body or {}).get("status") or "Draft"))
    if plan is None:
        raise HTTPException(
            status_code=404 if "not found" in " ".join(errors).lower() else 422,
            detail=" | ".join(errors),
        )
    return JSONResponse(plan)


@app.post("/api/lesson-plans/{lesson_id}/versions")
def lesson_plans_create_version(
    lesson_id: str, body: dict = Body(default_factory=dict)
) -> JSONResponse:
    version, errors = create_lesson_version(
        lesson_id, str((body or {}).get("comment") or "")
    )
    if version is None:
        raise HTTPException(
            status_code=404 if "not found" in " ".join(errors).lower() else 422,
            detail=" | ".join(errors),
        )
    return JSONResponse({**version, "lessonPlan": get_lesson_plan(lesson_id)})


@app.get("/api/lesson-plans/{lesson_id}/versions")
def lesson_plans_list_versions(lesson_id: str) -> JSONResponse:
    if get_lesson_plan(lesson_id) is None:
        raise HTTPException(status_code=404, detail="Lesson plan not found.")
    return JSONResponse(list_lesson_versions(lesson_id))


@app.post("/api/lesson-plans/{lesson_id}/versions/{version_id}/restore")
def lesson_plans_restore_version(lesson_id: str, version_id: str) -> JSONResponse:
    plan, errors = restore_lesson_version(lesson_id, version_id)
    if plan is None:
        raise HTTPException(
            status_code=404 if "not found" in " ".join(errors).lower() else 422,
            detail=" | ".join(errors),
        )
    return JSONResponse(plan)


@app.get("/api/lesson-plans/{lesson_id}/versions/{version_id}/diff")
def lesson_plans_diff_version(lesson_id: str, version_id: str) -> JSONResponse:
    diff = diff_lesson_version(lesson_id, version_id)
    if diff is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    return JSONResponse(diff)


@app.post("/api/lesson-plans/{lesson_id}/ai/draft")
def lesson_plans_ai_draft(lesson_id: str) -> JSONResponse:
    """Opt-in AI enrichment. OFF by default; never touches Outcomes/KIQ/Resources."""
    plan, errors = ai_draft(lesson_id)
    if plan is None:
        raise HTTPException(status_code=422, detail=" | ".join(errors))
    return JSONResponse(plan)


@app.post("/api/lesson-plans/{lesson_id}/ai/split")
def lesson_plans_ai_split(lesson_id: str) -> JSONResponse:
    payload, errors = ai_split_suggest(lesson_id)
    if payload is None:
        raise HTTPException(status_code=422, detail=" | ".join(errors))
    return JSONResponse(payload)


@app.get("/api/lesson-plans/{lesson_id}/web-examples")
def lesson_plans_web_examples(lesson_id: str, q: str = Query("")) -> JSONResponse:
    """Teacher-initiated search via the provider chosen in Settings."""
    results, errors = search_examples(lesson_id, q)
    if errors:
        raise HTTPException(status_code=404, detail=" | ".join(errors))
    log = ai_service.get_web_search_log(lesson_id) or {}
    return JSONResponse(
        {
            "query": q,
            "results": results,
            "provider": log.get("provider") or "unavailable",
            "message": log.get("message") or (
                f"{len(results)} result(s) from {log.get('provider') or 'web search'}."
                if results else ai_service.WEB_SEARCH_UNAVAILABLE
            ),
        }
    )


@app.get("/api/lesson-plans/{lesson_id}/export.pdf")
def lesson_plans_export_pdf(lesson_id: str) -> Response:
    """Portrait A4 KICD lesson plan with the header repeated on every page."""
    plan = get_lesson_plan(lesson_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Lesson plan not found.")
    from services.lesson_pdf import render_lesson_pdf

    pdf = render_lesson_pdf(plan)
    title = f"{plan.get('subStrand') or 'lesson'}-w{plan.get('week')}-l{plan.get('lesson')}"
    safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in title)[:60].strip()
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe or "lesson"}.pdf"'},
    )


# ---------------------------------------------------------------------------
# Phase 5 - learner-facing Lesson Notes (one document per lesson)
# ---------------------------------------------------------------------------


@app.get("/api/plans/{plan_id}/sections/{section_id}/notes-picker")
def plans_notes_picker(plan_id: str, section_id: str) -> JSONResponse:
    """Lesson Notes picker for one scheme row: lessons, focus, created note, vetting."""
    with_plan = get_plan(plan_id)
    if with_plan is None:
        raise HTTPException(status_code=404, detail="Plan not found.")
    picker, errors = notes_picker(section_id)
    if picker is None:
        raise HTTPException(status_code=404, detail=" | ".join(errors))
    if picker["planId"] != plan_id:
        raise HTTPException(status_code=404, detail="Section not found in this plan.")
    return JSONResponse(picker)


@app.post("/api/lesson-notes")
def lesson_notes_create(body: dict = Body(default_factory=dict)) -> JSONResponse:
    _assert_owned("plan_section", str((body or {}).get("schemeRowId") or (body or {}).get("sectionId") or ""))
    created, errors = create_lesson_notes(body or {})
    if not created:
        detail = " | ".join(errors) or "Cannot generate notes."
        status = 422 if any("not Vetted" in e for e in errors) else 409
        raise HTTPException(status_code=status, detail=detail)
    return JSONResponse({"created": created, "count": len(created), "errors": errors})


@app.get("/api/lesson-notes")
def lesson_notes_list(
    planId: Optional[str] = None, sectionId: Optional[str] = None
) -> JSONResponse:
    return JSONResponse(list_lesson_notes(planId, sectionId))


@app.get("/api/lesson-notes/web-log")
def lesson_notes_web_log(lessonId: str = Query("")) -> JSONResponse:
    """Last teacher-initiated web search log for the notes of one lesson plan."""
    if not lessonId:
        raise HTTPException(status_code=400, detail="lessonId is required.")
    _assert_owned("lesson_plans", lessonId)
    log = web_search_log(lessonId)
    return JSONResponse({"found": log is not None, "log": log})

@app.get("/api/lesson-notes/{note_id}")
def lesson_notes_get(note_id: str) -> JSONResponse:
    note = get_lesson_note(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Lesson notes not found.")
    return JSONResponse(note)


@app.delete("/api/lesson-notes/{note_id}")
def lesson_notes_delete(note_id: str) -> JSONResponse:
    if not delete_lesson_note(note_id):
        raise HTTPException(status_code=404, detail="Lesson notes not found.")
    return JSONResponse({"deleted": True, "noteId": note_id})


@app.post("/api/lesson-notes/{note_id}/header")
def lesson_notes_edit_header(
    note_id: str, body: dict = Body(default_factory=dict)
) -> JSONResponse:
    note, errors = edit_note_header(note_id, body or {})
    if note is None:
        raise HTTPException(
            status_code=404 if "not found" in " ".join(errors).lower() else 422,
            detail=" | ".join(errors),
        )
    return JSONResponse(note)


@app.post("/api/lesson-notes/{note_id}/sections/{section_id}/edit")
def lesson_notes_edit_section(
    note_id: str, section_id: str, body: dict = Body(default_factory=dict)
) -> JSONResponse:
    note, errors = edit_note_section(note_id, section_id, body or {})
    if note is None:
        raise HTTPException(
            status_code=404 if "not found" in " ".join(errors).lower() else 422,
            detail=" | ".join(errors),
        )
    return JSONResponse(note)


@app.post("/api/lesson-notes/{note_id}/sections/{section_id}/reset")
def lesson_notes_reset_section(note_id: str, section_id: str) -> JSONResponse:
    note, errors = reset_note_section(note_id, section_id)
    if note is None:
        raise HTTPException(
            status_code=404 if "not found" in " ".join(errors).lower() else 422,
            detail=" | ".join(errors),
        )
    return JSONResponse(note)


@app.post("/api/lesson-notes/{note_id}/status")
def lesson_notes_status(
    note_id: str, body: dict = Body(default_factory=dict)
) -> JSONResponse:
    note, errors = set_note_status(note_id, str((body or {}).get("status") or "Draft"))
    if note is None:
        raise HTTPException(
            status_code=404 if "not found" in " ".join(errors).lower() else 422,
            detail=" | ".join(errors),
        )
    return JSONResponse(note)


@app.post("/api/lesson-notes/{note_id}/versions")
def lesson_notes_create_version(
    note_id: str, body: dict = Body(default_factory=dict)
) -> JSONResponse:
    version, errors = create_note_version(
        note_id, str((body or {}).get("comment") or "")
    )
    if version is None:
        raise HTTPException(
            status_code=404 if "not found" in " ".join(errors).lower() else 422,
            detail=" | ".join(errors),
        )
    return JSONResponse({**version, "lessonNote": get_lesson_note(note_id)})


@app.get("/api/lesson-notes/{note_id}/versions")
def lesson_notes_list_versions(note_id: str) -> JSONResponse:
    if get_lesson_note(note_id) is None:
        raise HTTPException(status_code=404, detail="Lesson notes not found.")
    return JSONResponse(list_note_versions(note_id))


@app.get("/api/lesson-notes/{note_id}/versions/{version_id}")
def lesson_notes_get_version(note_id: str, version_id: str) -> JSONResponse:
    version = get_note_version(note_id, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    return JSONResponse(version)


@app.get("/api/lesson-notes/{note_id}/versions/{version_id}/diff")
def lesson_notes_diff_version(note_id: str, version_id: str) -> JSONResponse:
    diff = diff_note_version(note_id, version_id)
    if diff is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    return JSONResponse(diff)


@app.post("/api/lesson-notes/{note_id}/versions/{version_id}/restore")
def lesson_notes_restore_version(note_id: str, version_id: str) -> JSONResponse:
    note, errors = restore_note_version(note_id, version_id)
    if note is None:
        raise HTTPException(
            status_code=404 if "not found" in " ".join(errors).lower() else 422,
            detail=" | ".join(errors),
        )
    return JSONResponse(note)


@app.post("/api/lesson-notes/{note_id}/ai/draft")
def lesson_notes_ai_draft(note_id: str) -> JSONResponse:
    """Opt-in AI draft. Yellow in the UI; nothing is merged until the teacher accepts."""
    note, errors = ai_draft_note(note_id)
    if note is None:
        raise HTTPException(status_code=422, detail=" | ".join(errors))
    return JSONResponse(note)


@app.post("/api/lesson-notes/{note_id}/ai/accept-all")
def lesson_notes_ai_accept_all(note_id: str) -> JSONResponse:
    note, errors = ai_accept_all(note_id)
    if note is None:
        raise HTTPException(status_code=422, detail=" | ".join(errors))
    return JSONResponse(note)


@app.get("/api/lesson-notes/{note_id}/search-examples")
def lesson_notes_search_examples(note_id: str, q: str = Query("")) -> JSONResponse:
    """Teacher-initiated search via the provider chosen in Settings."""
    results, errors = search_note_examples(note_id, q)
    if errors:
        raise HTTPException(status_code=404, detail=" | ".join(errors))
    log = ai_service.get_web_search_log(note_id) or {}
    return JSONResponse(
        {
            "query": q,
            "results": results,
            "provider": log.get("provider") or "unavailable",
            "message": log.get("message") or (
                f"{len(results)} result(s) from {log.get('provider') or 'web search'}."
                if results else ai_service.WEB_SEARCH_UNAVAILABLE
            ),
        }
    )



@app.post("/api/lesson-notes/{note_id}/sources")
def lesson_notes_add_source(
    note_id: str, body: dict = Body(default_factory=dict)
) -> JSONResponse:
    """[Add My Source] - teacher URL/text stored as Teacher Source and shown in the footer."""
    note, errors = add_note_source(note_id, body or {})
    if note is None:
        raise HTTPException(
            status_code=404 if "not found" in " ".join(errors).lower() else 422,
            detail=" | ".join(errors),
        )
    return JSONResponse(note)


@app.post("/api/lesson-notes/{note_id}/web-examples")
def lesson_notes_insert_web_example(
    note_id: str, body: dict = Body(default_factory=dict)
) -> JSONResponse:
    """[Insert as Web Example] - explicit teacher action, labelled with the source URL."""
    note, errors = insert_web_example(note_id, body or {})
    if note is None:
        raise HTTPException(
            status_code=404 if "not found" in " ".join(errors).lower() else 422,
            detail=" | ".join(errors),
        )
    return JSONResponse(note)


@app.get("/api/lesson-notes/{note_id}/export.pdf")
def lesson_notes_export_pdf(note_id: str, answers: bool = Query(False)) -> Response:
    """Portrait A4 learner-friendly notes. Practice answers are hidden unless ?answers=1."""
    note = get_lesson_note(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Lesson notes not found.")
    from services.notes_pdf import render_notes_pdf

    pdf = render_notes_pdf(note, show_answers=answers)
    title = f"{note.get('title') or 'lesson-notes'}-w{note.get('week')}-l{note.get('lesson')}"
    safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in title)[:70].strip()
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe or "lesson-notes"}.pdf"'},
    )


# ---------------------------------------------------------------------------
# Phase 6 - Record of Work (ROW). Retrospective, teacher-filled, after teaching.
# Static paths MUST stay above /api/row/{id} so they are not captured by it.
# ---------------------------------------------------------------------------


def _row_raise(errors: list[str]) -> None:
    text = " | ".join(errors or ["Record of Work operation failed."])
    raise HTTPException(
        status_code=404 if "not found" in text.lower() else 422, detail=text
    ) from None


@app.get("/api/row/schemes")
def row_schemes() -> JSONResponse:
    """Scheme picker with ROW state (no side effects)."""
    return JSONResponse(row_service.list_schemes())


@app.get("/api/row/coverage")
def row_coverage(planId: str = Query("")) -> JSONResponse:
    """{ planned, taught, partially, notTaught, carryOver, coveragePct, gaps }."""
    if not planId:
        raise HTTPException(status_code=400, detail="planId is required.")
    doc = row_service.get_document(planId)
    if doc is None:
        raise HTTPException(status_code=404, detail="Scheme not found.")
    return JSONResponse(doc["coverage"])


@app.post("/api/row/mark-taught")
def row_mark_taught(body: dict = Body(default_factory=dict)) -> JSONResponse:
    """[→ Mark as Taught] from a Lesson Plan. Generates rows first if needed."""
    payload = body or {}
    _assert_owned("plan_documents", str(payload.get("planId") or ""))
    doc, errors = row_service.mark_taught(
        str(payload.get("planId") or ""), payload.get("week"), payload.get("lesson")
    )
    if doc is None:
        _row_raise(errors)
    return JSONResponse(doc)


@app.post("/api/row")
def row_generate(body: dict = Body(default_factory=dict)) -> JSONResponse:
    """ONE ROW row per scheme lesson. Idempotent; never duplicates."""
    payload = body or {}
    _assert_owned("plan_documents", str(payload.get("planId") or ""))
    doc, errors = row_service.generate_rows(
        str(payload.get("planId") or ""), bool(payload.get("addMissingOnly"))
    )
    if doc is None:
        _row_raise(errors)
    return JSONResponse(doc)


@app.get("/api/row")
def row_get(planId: str = Query("")) -> JSONResponse:
    if not planId:
        raise HTTPException(status_code=400, detail="planId is required.")
    doc = row_service.get_document(planId)
    if doc is None:
        raise HTTPException(status_code=404, detail="Scheme not found.")
    return JSONResponse(doc)


@app.get("/api/row/{ident}")
def row_get_by_id(ident: str) -> JSONResponse:
    """Accepts a ROW document id, a scheme id, or a single ROW row id."""
    is_row = row_service.get_row(ident) is not None
    doc = row_service.get_document(ident, focus_row_id=ident if is_row else None)
    if doc is None:
        raise HTTPException(status_code=404, detail="Record of Work not found.")
    return JSONResponse(doc)


@app.post("/api/row/{row_id}/edit")
def row_edit(row_id: str, body: dict = Body(default_factory=dict)) -> JSONResponse:
    result, errors = row_service.edit_row(row_id, body or {})
    if result is None:
        _row_raise(errors)
    return JSONResponse(result)


@app.post("/api/row/{row_id}/reset")
def row_reset(row_id: str) -> JSONResponse:
    result, errors = row_service.reset_row(row_id)
    if result is None:
        _row_raise(errors)
    return JSONResponse(result)


@app.post("/api/row/{row_id}/carry-over")
def row_carry_over(row_id: str, body: dict = Body(default_factory=dict)) -> JSONResponse:
    payload = body or {}
    result, errors = row_service.carry_over(
        row_id, payload.get("week"), payload.get("lesson")
    )
    if result is None:
        _row_raise(errors)
    # Phase 8 audit: every carry-over creates a NEW ROW version (never overwrites).
    version, _verr = row_service.create_version(
        result["row"]["docId"],
        f"Carry-over to Week {payload.get('week')} Lesson {payload.get('lesson')}",
        kind="carry-over",
    )
    if version:
        result["version"] = version
    dashboard_service.invalidate()
    return JSONResponse(result)


@app.post("/api/row/{row_id}/ai/reflection")
def row_ai_reflection(row_id: str) -> JSONResponse:
    """OPT-IN only. AI may suggest a Reflection; never Work Done or Status."""
    result, errors = row_service.suggest_reflection(row_id)
    if result is None:
        _row_raise(errors)
    return JSONResponse(result)


@app.post("/api/row/{row_id}/ai/accept")
def row_ai_accept(row_id: str, body: dict = Body(default_factory=dict)) -> JSONResponse:
    result, errors = row_service.accept_reflection(
        row_id, str((body or {}).get("text") or "") or None
    )
    if result is None:
        _row_raise(errors)
    return JSONResponse(result)


@app.post("/api/row/{row_id}/ai/reject")
def row_ai_reject(row_id: str) -> JSONResponse:
    result, errors = row_service.reject_reflection(row_id)
    if result is None:
        _row_raise(errors)
    return JSONResponse(result)


@app.post("/api/row/{ident}/bulk-status")
def row_bulk_status(ident: str, body: dict = Body(default_factory=dict)) -> JSONResponse:
    """[Mark All Week N as Taught] - Status only, never Work Done / Reflection."""
    payload = body or {}
    result, errors = row_service.bulk_status(
        ident, payload.get("week"), str(payload.get("status") or "")
    )
    if result is None:
        _row_raise(errors)
    return JSONResponse(result)


@app.post("/api/row/{ident}/status")
def row_set_status(ident: str, body: dict = Body(default_factory=dict)) -> JSONResponse:
    """[Mark Final] -> 'Final - Term 1'; [Unlock to Edit] -> new Draft."""
    result, errors = row_service.set_doc_status(
        ident, str((body or {}).get("status") or "")
    )
    if result is None:
        _row_raise(errors)
    return JSONResponse(result)


@app.post("/api/row/{ident}/versions")
def row_create_version(ident: str, body: dict = Body(default_factory=dict)) -> JSONResponse:
    result, errors = row_service.create_version(
        ident, str((body or {}).get("comment") or "")
    )
    if result is None:
        _row_raise(errors)
    return JSONResponse(result)


@app.get("/api/row/{ident}/versions")
def row_list_versions(ident: str) -> JSONResponse:
    result = row_service.list_versions(ident)
    if result is None:
        raise HTTPException(status_code=404, detail="Record of Work not found.")
    return JSONResponse(result)


@app.get("/api/row/{ident}/versions/{version_id}")
def row_get_version(ident: str, version_id: str) -> JSONResponse:
    result = row_service.get_version(ident, version_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    return JSONResponse(result)


@app.get("/api/row/{ident}/versions/{version_id}/diff")
def row_diff_version(ident: str, version_id: str) -> JSONResponse:
    result = row_service.diff_version(ident, version_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Version not found.")
    return JSONResponse(result)


@app.post("/api/row/{ident}/versions/{version_id}/restore")
def row_restore_version(ident: str, version_id: str) -> JSONResponse:
    """Restore applies the snapshot and appends a NEW version; nothing is deleted."""
    result, errors = row_service.restore_version(ident, version_id)
    if result is None:
        _row_raise(errors)
    return JSONResponse(result)


@app.get("/api/row/{ident}/export.pdf")
def row_export_pdf(ident: str) -> Response:
    """Portrait A4, full term, all columns + Gap Summary + signature lines."""
    from services.row_pdf import render_row_pdf

    doc = row_service.get_document(ident)
    if doc is None:
        raise HTTPException(status_code=404, detail="Record of Work not found.")
    pdf = render_row_pdf(doc)
    title = f"record-of-work-{doc.get('header', {}).get('grade') or ''}-{doc.get('header', {}).get('term') or ''}"
    safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in title)[:70].strip()
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe or "record-of-work"}.pdf"'},
    )


# ---------------------------------------------------------------------------
# Phase 7: Term Pack export bundle
# ---------------------------------------------------------------------------

@app.post("/api/export")
def create_export(payload: dict = Body(...)):
    plan_id = str(payload.get("planId") or "")
    if not plan_id:
        raise HTTPException(status_code=400, detail="planId is required.")
    _assert_owned("plan_documents", plan_id)
    job = export_service.create_job(
        plan_id,
        payload.get("includes"),
        str(payload.get("format") or "pdf"),
        auth.current_owner_id(),
    )
    return JSONResponse({"jobId": job["id"], "status": job["status"], "progress": job["progress"]})


@app.get("/api/export/history")
def export_history(planId: Optional[str] = Query(None)):
    return JSONResponse({"jobs": export_service.list_history(planId)})


@app.get("/api/exports")
def exports_list(planId: Optional[str] = Query(None)) -> JSONResponse:
    """RLS acceptance alias: only the signed-in teacher's export jobs."""
    return JSONResponse({"jobs": export_service.list_history(planId)})


@app.get("/api/exports/{job_id}")
def exports_get(job_id: str) -> JSONResponse:
    job = export_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Export not found.")
    return JSONResponse(job)


@app.get("/api/export/plans-for-document")
def plans_for_document(documentId: str = Query(...)):
    """Library cards know documentId, not planId - find schemes citing that document."""
    _assert_owned("source_documents", documentId)
    import db as _db
    with _db.connect() as conn:
        rows = conn.execute(
            """SELECT DISTINCT pd.id, pd.title, pd.grade, pd.subject, pd.term
               FROM plan_citations pc JOIN plan_documents pd ON pd.id = pc.plan_id
               WHERE pc.document_id = ? ORDER BY pd.created_at DESC""",
            (documentId,),
        ).fetchall()
    return JSONResponse({"plans": [dict(r) for r in rows]})


@app.get("/api/export/{job_id}")
def export_status(job_id: str):
    job = export_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Export job not found.")
    return JSONResponse(job)


@app.get("/api/export/{job_id}/file")
def export_file(job_id: str):
    job = export_service.get_job(job_id)
    if not job or not job.get("filePath"):
        raise HTTPException(status_code=404, detail="Export file not ready.")
    path = Path(job["filePath"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Export file not found.")
    media = "application/zip" if job["format"] == "zip" else "application/pdf"
    return FileResponse(path, media_type=media, filename=job["fileName"] or path.name)


@app.get("/api/export/{job_id}/download")
def export_download_url(job_id: str):
    job = export_service.get_job(job_id)
    if not job or not job.get("filePath"):
        raise HTTPException(status_code=404, detail="Export file not ready.")
    return JSONResponse({"url": job["fileUrl"], "fileName": job["fileName"],
                         "fileSize": job["fileSize"], "pageCount": job["pageCount"]})


@app.delete("/api/export/{job_id}")
def export_delete(job_id: str):
    if not export_service.delete_job(job_id):
        raise HTTPException(status_code=404, detail="Export job not found.")
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Phase 8: Coverage Dashboard (read-only aggregate + gap actions)
# ---------------------------------------------------------------------------

@app.get("/api/dashboard")
def dashboard_get(
    term: str = Query(""), year: str = Query(""), grade: str = Query(""),
    subject: str = Query(""), week: int = Query(0), teacher: str = Query(""),
) -> JSONResponse:
    return JSONResponse(dashboard_service.get_dashboard({
        "term": term, "year": year, "grade": grade, "subject": subject,
        "week": week, "teacher": teacher,
    }))


@app.get("/api/dashboard/reflection")
def dashboard_reflection_get(
    planId: str = Query(...), term: str = Query(""), year: str = Query(""),
) -> JSONResponse:
    _assert_owned("plan_documents", planId)
    return JSONResponse(dashboard_service.get_reflection(planId, term, year))


@app.put("/api/dashboard/reflection")
def dashboard_reflection_put(body: dict = Body(default_factory=dict)) -> JSONResponse:
    payload = body or {}
    plan_id = str(payload.get("planId") or "")
    if not plan_id:
        raise HTTPException(status_code=400, detail="planId is required.")
    _assert_owned("plan_documents", plan_id)
    return JSONResponse(dashboard_service.save_reflection(
        plan_id,
        str(payload.get("term") or ""),
        str(payload.get("year") or ""),
        str(payload.get("reflection") or ""),
    ))


@app.get("/api/dashboard/export")
def dashboard_export(
    term: str = Query(""), year: str = Query(""), grade: str = Query(""),
    subject: str = Query(""), week: int = Query(0), teacher: str = Query(""),
) -> Response:
    data = dashboard_service.get_dashboard({
        "term": term, "year": year, "grade": grade, "subject": subject,
        "week": week, "teacher": teacher,
    })
    pdf, _pages = dashboard_pdf.render_dashboard_pdf(data)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="{dashboard_pdf.filename_for(data)}"'},
    )


def _gap_action(row_id: str, body: dict, action: str) -> JSONResponse:
    """Shared audit-safe gap action: validate, edit via Phase 6, snapshot a version."""
    payload = body or {}
    date = str(payload.get("date") or "").strip()
    work_done = str(payload.get("workDone") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    if action == "taught":
        if not date:
            raise HTTPException(status_code=422, detail="Date required.")
        if not work_done:
            raise HTTPException(status_code=422, detail="Work Done required.")
        patch = {"date": date, "workDone": work_done, "status": "Taught"}
        comment = f"Dashboard: marked Week {payload.get('week', '?')} Lesson {payload.get('lesson', '?')} as Taught"
    else:
        if not reason:
            raise HTTPException(status_code=422, detail="Reason required.")
        patch = {"reflection": reason, "status": "Not Taught - Skipped"}
        comment = f"Dashboard: skipped Week {payload.get('week', '?')} Lesson {payload.get('lesson', '?')} - {reason[:80]}"
    result, errors = row_service.edit_row(row_id, patch)
    if result is None:
        _row_raise(errors)
    version, _verr = row_service.create_version(result["row"]["docId"], comment, kind=action)
    if version:
        result["version"] = version
    dashboard_service.invalidate()
    return JSONResponse(result)


@app.post("/api/row/{row_id}/mark-taught")
def dashboard_mark_taught(row_id: str, body: dict = Body(default_factory=dict)) -> JSONResponse:
    """[Mark as Taught] from the Dashboard: Date + Work Done are mandatory."""
    return _gap_action(row_id, body, "taught")


@app.post("/api/row/{row_id}/skip")
def dashboard_skip(row_id: str, body: dict = Body(default_factory=dict)) -> JSONResponse:
    """[Skip] from the Dashboard: Reason is mandatory; the gap stays visible."""
    return _gap_action(row_id, body, "skip")


# ---------------------------------------------------------------------------
# Phase 10 - My Learners, assessment records, progress and IEPs.
# No school, headteacher or sharing concept: every route is scoped to the signed-in
# teacher by the middleware and by learner_service's owner filters.
# ---------------------------------------------------------------------------
@app.get("/api/learners/csv-template")
def learners_csv_template() -> Response:
    return Response(
        content=learner_service.CSV_TEMPLATE,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="learners-template.csv"'},
    )


@app.post("/api/learners/import-csv")
def learners_import_csv(body: dict = Body(default_factory=dict)) -> JSONResponse:
    preview = bool(body.get("previewOnly", True))
    return JSONResponse(
        learner_service.csv_preview(body) if preview else learner_service.csv_import(body)
    )


@app.get("/api/learners/summary")
def learners_summary() -> JSONResponse:
    return JSONResponse(learner_service.learner_summary())


@app.post("/api/learners")
def learners_create(body: dict = Body(default_factory=dict)) -> JSONResponse:
    return JSONResponse(learner_service.create_learner(body))


@app.get("/api/learners")
def learners_list(
    grade: str = Query(""), learningArea: str = Query(""), className: str = Query(""),
    status: str = Query(""), q: str = Query(""),
) -> JSONResponse:
    return JSONResponse(learner_service.list_learners({
        "grade": grade, "learningArea": learningArea, "className": className,
        "status": status, "q": q,
    }))


@app.get("/api/learners/{learner_id}")
def learners_get(learner_id: str) -> JSONResponse:
    return JSONResponse(learner_service.get_learner(learner_id))


@app.put("/api/learners/{learner_id}")
def learners_update(learner_id: str, body: dict = Body(default_factory=dict)) -> JSONResponse:
    return JSONResponse(learner_service.update_learner(learner_id, body))


@app.post("/api/learners/{learner_id}/archive")
def learners_archive(learner_id: str, body: dict = Body(default_factory=dict)) -> JSONResponse:
    return JSONResponse(learner_service.archive_learner(learner_id, body))


@app.delete("/api/learners/{learner_id}")
def learners_delete(learner_id: str, body: dict = Body(default_factory=dict)) -> JSONResponse:
    return JSONResponse(learner_service.delete_learner(
        learner_id, str(body.get("confirmation") or "")
    ))


@app.get("/api/assess-options")
def assessments_options(grade: str = Query(""), learningArea: str = Query("")) -> JSONResponse:
    """Sub-strand picker when assessment starts from a Learner profile."""
    return JSONResponse(learner_service.assess_options(grade, learningArea))


@app.get("/api/assessments/context")
def assessments_context(
    schemeRowId: str = Query(...), week: int = Query(0), lesson: int = Query(0),
) -> JSONResponse:
    _assert_owned("plan_section", schemeRowId)
    return JSONResponse(learner_service.assessment_context(schemeRowId, week, lesson))


@app.get("/api/assessments/audit")
def assessments_audit(learnerId: str = Query(...)) -> JSONResponse:
    return JSONResponse(learner_service.assessment_audit(learnerId))


@app.post("/api/assessments")
def assessments_save(body: dict = Body(default_factory=dict)) -> JSONResponse:
    return JSONResponse(learner_service.save_assessment(body))


@app.get("/api/assessments")
def assessments_list(
    learnerId: str = Query(""), chunkId: str = Query(""), week: int = Query(0),
) -> JSONResponse:
    if learnerId:
        _assert_owned("learners", learnerId)
    return JSONResponse(learner_service.list_assessments({
        "learnerId": learnerId, "chunkId": chunkId, "week": week,
    }))


@app.get("/api/assessments/{assessment_id}")
def assessments_get(assessment_id: str) -> JSONResponse:
    return JSONResponse(learner_service.get_assessment(assessment_id))


@app.get("/api/progress")
def progress_view(
    grade: str = Query(""), learningArea: str = Query(""), className: str = Query(""),
    strand: str = Query(""), fromWeek: int = Query(0), toWeek: int = Query(0),
) -> JSONResponse:
    return JSONResponse(learner_service.get_progress({
        "grade": grade, "learningArea": learningArea, "className": className,
        "strand": strand, "fromWeek": fromWeek, "toWeek": toWeek,
    }))


@app.get("/api/progress/export")
def progress_export(
    request: Request, grade: str = Query(""), learningArea: str = Query(""),
    className: str = Query(""), term: str = Query(""),
) -> Response:
    user = _current_user(request)
    filters = {"grade": grade, "learningArea": learningArea, "className": className}
    data = learner_service.get_progress(filters)
    pdf = progress_pdf.build_progress_pdf(data, user, {**filters, "term": term})
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="my-learners-progress.pdf"'},
    )


@app.post("/api/iep")
def iep_create(body: dict = Body(default_factory=dict)) -> JSONResponse:
    return JSONResponse(learner_service.create_iep(body))


@app.get("/api/iep")
def iep_list(learnerId: str = Query(""), status: str = Query("")) -> JSONResponse:
    return JSONResponse(learner_service.list_ieps({"learnerId": learnerId, "status": status}))


@app.post("/api/iep/suggest-support")
def iep_suggest_support(body: dict = Body(default_factory=dict)) -> JSONResponse:
    return JSONResponse(learner_service.suggest_support(body))


@app.get("/api/iep/{iep_id}")
def iep_get(iep_id: str) -> JSONResponse:
    return JSONResponse(learner_service.get_iep(iep_id))


@app.put("/api/iep/{iep_id}")
def iep_update(iep_id: str, body: dict = Body(default_factory=dict)) -> JSONResponse:
    return JSONResponse(learner_service.update_iep(iep_id, body))


@app.post("/api/iep/{iep_id}/reviews")
def iep_add_review(iep_id: str, body: dict = Body(default_factory=dict)) -> JSONResponse:
    return JSONResponse(learner_service.add_iep_review(iep_id, body))


@app.post("/api/iep/{iep_id}/close")
def iep_close(iep_id: str) -> JSONResponse:
    return JSONResponse(learner_service.close_iep(iep_id))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
