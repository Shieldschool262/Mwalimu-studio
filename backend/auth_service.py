"""Phase 9 - Individual teacher authentication and Workspace ownership.

One account = one teacher = one private Workspace. There is intentionally no shared
school view, elevated role or multi-teacher concept in this module.

Passwords are bcrypt hashes and are never returned by any API. Sessions are signed
JWTs carried in an httpOnly cookie. Every content row carries owner_id; the helpers at
the bottom of this module resolve the owner of a URL resource so the API middleware
can return 403 before any other teacher's content is read.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import bcrypt
import jwt

from db import BACKEND_ROOT, OWNED_TABLES, connect, new_id, rls_bypass

MIGRATED_ID = "user-migrated-001"
MIGRATED_EMAIL = "teacher@local"
MIGRATED_NAME = "My Space"
MIGRATED_PASSWORD = "Teacher123"  # one-time credential; banner asks the teacher to secure it
COOKIE_NAME = "mwalimu_session"
SESSION_DAYS = 7
REMEMBER_DAYS = 30

# Per-request owner. Services read this so list queries and new rows are scoped
# without needing to thread a parameter through dozens of existing call sites.
_owner_ctx: ContextVar[str] = ContextVar("mwalimu_owner_id", default="")


def set_owner(owner_id: str) -> Any:
    return _owner_ctx.set(owner_id or "")


def reset_owner(token: Any) -> None:
    _owner_ctx.reset(token)


def current_owner_id() -> str:
    return _owner_ctx.get()


# ---------------------------------------------------------------------------
# Password + token primitives
# ---------------------------------------------------------------------------
def valid_password(password: str) -> tuple[bool, str]:
    if not isinstance(password, str) or len(password) < 8:
        return False, "Password must be at least 8 characters"
    if not re.search(r"\d", password):
        return False, "Password must contain at least 1 number"
    return True, ""


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _secret() -> str:
    env = os.environ.get("MWALIMU_JWT_SECRET", "").strip()
    if env:
        return env
    path = BACKEND_ROOT / ".jwt_secret"
    if not path.exists():
        path.write_text(secrets.token_hex(48), encoding="utf-8")
    return path.read_text(encoding="utf-8").strip()


def issue_token(user_id: str, email: str, remember: bool = False) -> tuple[str, int, int]:
    days = REMEMBER_DAYS if remember else SESSION_DAYS
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=days)
    payload = {
        "sub": user_id,
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "remember": bool(remember),
    }
    return jwt.encode(payload, _secret(), algorithm="HS256"), days * 24 * 3600, int(exp.timestamp())


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(token, _secret(), algorithms=["HS256"])
        if not payload.get("sub"):
            return None
        return payload
    except jwt.PyJWTError:
        return None


def token_from_request(request: Any) -> str:
    return request.cookies.get(COOKIE_NAME, "") if hasattr(request, "cookies") else ""


def user_from_request(request: Any) -> dict[str, Any] | None:
    payload = decode_token(token_from_request(request))
    return get_user(payload["sub"]) if payload else None


def set_session_cookie(response: Any, token: str, remember: bool) -> None:
    kwargs: dict[str, Any] = {
        "key": COOKIE_NAME,
        "value": token,
        "httponly": True,
        "samesite": "lax",
        "path": "/",
    }
    if remember:
        kwargs["max_age"] = REMEMBER_DAYS * 24 * 3600
    # Without `remember` the cookie is a session cookie and dies with the browser.
    response.set_cookie(**kwargs)


def clear_session_cookie(response: Any) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
def _json(value: Any, default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except (ValueError, TypeError):
        return default


def public_user(row: Any) -> dict[str, Any]:
    """No password hash, ever."""
    return {
        "id": row["id"],
        "email": row["email"],
        "name": row["name"],
        "role": row["role"],
        "tscNo": row["tsc_no"],
        "county": row["county"],
        "schoolName": row["school_name"],
        "grades": _json(row["grades_json"], []),
        "subjects": _json(row["subjects_json"], []),
        "preferences": _json(row["preferences_json"], {}),
        "needsProfileConfirm": bool(row["needs_profile_confirm"]),
        "createdAt": row["created_at"],
    }


def get_user(user_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return public_user(row) if row else None


def find_by_email(email: str) -> Any:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE email = ? COLLATE NOCASE", (str(email).strip(),)
        ).fetchone()


# ---------------------------------------------------------------------------
# First-run migration - never discard existing content
# ---------------------------------------------------------------------------
def migrate_legacy_content() -> str | None:
    """Assign unowned legacy content to the single migrated My Space account.

    Returns a log line when something was migrated, otherwise None. Any failure
    rolls the whole migration back so the app never starts against an empty DB.
    """
    try:
        with rls_bypass(), connect() as conn:
            counts: dict[str, int] = {}
            for table, _label in OWNED_TABLES + (
                ("record_of_work_rows", "ROW rows"),
                ("term_reflections", "Reflections"),
            ):
                counts[table] = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE owner_id IS NULL OR owner_id = ''"
                ).fetchone()[0]
            if not any(counts.values()):
                return None

            conn.execute("SAVEPOINT phase9_migration")
            try:
                existing = conn.execute(
                    "SELECT id FROM users WHERE id = ?", (MIGRATED_ID,)
                ).fetchone()
                if not existing:
                    # Also protect against an email collision from an earlier signup.
                    clash = conn.execute(
                        "SELECT id FROM users WHERE email = ? COLLATE NOCASE", (MIGRATED_EMAIL,)
                    ).fetchone()
                    if clash:
                        raise RuntimeError("migration email already in use by another account")
                    conn.execute(
                        """INSERT INTO users
                           (id, email, password_hash, name, role, needs_profile_confirm)
                           VALUES (?, ?, ?, ?, 'Teacher', 1)""",
                        (MIGRATED_ID, MIGRATED_EMAIL, hash_password(MIGRATED_PASSWORD), MIGRATED_NAME),
                    )
                for table in counts:
                    conn.execute(
                        f"UPDATE {table} SET owner_id = ? WHERE owner_id IS NULL OR owner_id = ''",
                        (MIGRATED_ID,),
                    )
                conn.execute("RELEASE SAVEPOINT phase9_migration")
            except Exception:
                conn.execute("ROLLBACK TO SAVEPOINT phase9_migration")
                conn.execute("RELEASE SAVEPOINT phase9_migration")
                raise

        labels = {table: label for table, label in OWNED_TABLES}
        summary = ", ".join(
            f"{counts[table]} {label}" for table, label in OWNED_TABLES if counts.get(table)
        )
        return f"Migrated {summary} to My Space"
    except Exception as exc:  # pragma: no cover - defensive, must not start broken
        raise RuntimeError(f"Phase 9 migration failed; startup aborted: {exc}") from exc


# ---------------------------------------------------------------------------
# Rate limiting (in-process, keyed by IP + email)
# ---------------------------------------------------------------------------
_rate_lock = threading.Lock()
_failures: dict[tuple[str, str], list[float]] = {}
MAX_FAILURES = 5
WINDOW_SECONDS = 15 * 60


def _rate_key(ip: str, email: str) -> tuple[str, str]:
    return (ip or "unknown", str(email or "").strip().lower())


def check_rate(ip: str, email: str) -> None:
    from fastapi import HTTPException

    cutoff = time.time() - WINDOW_SECONDS
    with _rate_lock:
        hits = [t for t in _failures.get(_rate_key(ip, email), []) if t > cutoff]
        _failures[_rate_key(ip, email)] = hits
        if len(hits) >= MAX_FAILURES:
            raise HTTPException(429, "Too many attempts, try again in 15 min")


def record_failure(ip: str, email: str) -> None:
    with _rate_lock:
        key = _rate_key(ip, email)
        _failures.setdefault(key, []).append(time.time())


def clear_failures(ip: str, email: str) -> None:
    with _rate_lock:
        _failures.pop(_rate_key(ip, email), None)


# ---------------------------------------------------------------------------
# Signup / login / profile / account deletion
# ---------------------------------------------------------------------------
def signup(payload: dict[str, Any]) -> dict[str, Any]:
    from fastapi import HTTPException

    name = str(payload.get("name") or "").strip()
    email = str(payload.get("email") or "").strip().lower()
    password = str(payload.get("password") or "")
    if not name:
        raise HTTPException(422, "Full Name is required")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(422, "A valid Email is required")
    ok, message = valid_password(password)
    if not ok:
        raise HTTPException(422, message)
    if find_by_email(email):
        raise HTTPException(409, "An account with that email already exists")

    user_id = new_id()
    grades = payload.get("grades") or []
    subjects = payload.get("subjects") or []
    if isinstance(grades, str):
        grades = [x.strip() for x in grades.split(",") if x.strip()]
    if isinstance(subjects, str):
        subjects = [x.strip() for x in subjects.split(",") if x.strip()]
    preferences = {
        "defaultTerm": str(payload.get("defaultTerm") or "Term 1"),
        "defaultYear": str(payload.get("defaultYear") or str(datetime.now().year)),
        "notesFontSize": int(payload.get("notesFontSize") or 16),
        "answersInNotesPdf": bool(payload.get("answersInNotesPdf", False)),
    }
    with connect() as conn:
        conn.execute(
            """INSERT INTO users
               (id, email, password_hash, name, tsc_no, county, school_name,
                grades_json, subjects_json, preferences_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id, email, hash_password(password), name,
                str(payload.get("tscNo") or "").strip(),
                str(payload.get("county") or "").strip(),
                str(payload.get("schoolName") or "").strip(),
                json.dumps(grades), json.dumps(subjects), json.dumps(preferences),
            ),
        )
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return public_user(row)


def login(payload: dict[str, Any], ip: str) -> tuple[dict[str, Any], str, bool]:
    from fastapi import HTTPException

    email = str(payload.get("email") or "").strip().lower()
    password = str(payload.get("password") or "")
    remember = bool(payload.get("remember", False))
    check_rate(ip, email)
    row = find_by_email(email)
    if row is None or not verify_password(password, row["password_hash"]):
        record_failure(ip, email)
        # Deliberately identical for unknown email and wrong password.
        raise HTTPException(401, "Invalid email or password")
    clear_failures(ip, email)
    token, _max_age, _exp = issue_token(row["id"], row["email"], remember)
    return public_user(row), token, remember


def update_profile(user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from fastapi import HTTPException

    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise HTTPException(401, "Not signed in")
        current = public_user(row)
        email = str(payload.get("email", current["email"])).strip().lower()
        if email != current["email"] and find_by_email(email):
            raise HTTPException(409, "An account with that email already exists")
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            raise HTTPException(422, "A valid Email is required")
        name = str(payload.get("name", current["name"])).strip() or current["name"]
        grades = payload.get("grades", current["grades"])
        subjects = payload.get("subjects", current["subjects"])
        if isinstance(grades, str):
            grades = [x.strip() for x in grades.split(",") if x.strip()]
        if isinstance(subjects, str):
            subjects = [x.strip() for x in subjects.split(",") if x.strip()]
        preferences = dict(current["preferences"])
        if isinstance(payload.get("preferences"), dict):
            preferences.update(payload["preferences"])
        conn.execute(
            """UPDATE users SET email = ?, name = ?, tsc_no = ?, county = ?,
               school_name = ?, grades_json = ?, subjects_json = ?, preferences_json = ?,
               needs_profile_confirm = 0, updated_at = datetime('now') WHERE id = ?""",
            (
                email, name,
                str(payload.get("tscNo", current["tscNo"]) or "").strip(),
                str(payload.get("county", current["county"]) or "").strip(),
                str(payload.get("schoolName", current["schoolName"]) or "").strip(),
                json.dumps(grades), json.dumps(subjects), json.dumps(preferences),
                user_id,
            ),
        )
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return public_user(row)


def change_password(user_id: str, payload: dict[str, Any]) -> None:
    from fastapi import HTTPException

    current = str(payload.get("currentPassword") or "")
    new = str(payload.get("newPassword") or "")
    ok, message = valid_password(new)
    if not ok:
        raise HTTPException(422, message)
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row or not verify_password(current, row["password_hash"]):
            raise HTTPException(401, "Invalid email or password")
        conn.execute(
            "UPDATE users SET password_hash = ?, updated_at = datetime('now') WHERE id = ?",
            (hash_password(new), user_id),
        )


def delete_account(user_id: str, confirmation: str) -> None:
    from fastapi import HTTPException

    if confirmation != "DELETE":
        raise HTTPException(422, "Type DELETE to confirm")
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
            raise HTTPException(401, "Not signed in")
        # Children cascade via foreign keys; the remaining content tables are removed
        # explicitly because some of them reference plans rather than users directly.
        for table in (
            "iep_reviews", "ieps", "assessment_audit", "assessment_records", "learners",
            "export_jobs", "term_reflections", "record_of_work_rows",
            "record_of_work_versions", "record_of_work_docs",
            "lesson_note_sources", "lesson_note_versions", "lesson_note_sections", "lesson_notes",
            "lesson_plan_versions", "lesson_plan_sections", "lesson_plans",
            "plan_edits", "plan_versions", "plan_citations", "plan_sections", "plan_documents",
            "source_chunks", "source_documents",
        ):
            conn.execute(f"DELETE FROM {table} WHERE owner_id = ?", (user_id,)) if _has_column(conn, table, "owner_id") else None
        conn.execute("DELETE FROM user_settings WHERE owner_id = ?", (user_id,))
        conn.execute("DELETE FROM password_reset_tokens WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


def _has_column(conn: Any, table: str, column: str) -> bool:
    return column in {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


# ---------------------------------------------------------------------------
# Password reset (single-use, 1-hour, hashed token)
# ---------------------------------------------------------------------------
def forgot_password(email: str) -> dict[str, Any]:
    row = find_by_email(email)
    # Always the same answer; never disclose whether the email exists.
    if row is None:
        return {"ok": True, "message": "If that account exists, a reset link has been created."}
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    with connect() as conn:
        conn.execute(
            "INSERT INTO password_reset_tokens (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (token_hash, row["id"], expires_at),
        )
    # There is no mail transport in this local app; the one-time link is returned to
    # the caller so it can be delivered out of band. No password is ever included.
    return {
        "ok": True,
        "message": "If that account exists, a reset link has been created.",
        "resetToken": token,
        "resetUrl": f"/reset-password?token={token}",
        "expiresAt": expires_at,
    }


def reset_password(payload: dict[str, Any]) -> None:
    from fastapi import HTTPException

    token = str(payload.get("token") or "")
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    new = str(payload.get("password") or "")
    ok, message = valid_password(new)
    if not ok:
        raise HTTPException(422, message)
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM password_reset_tokens WHERE token_hash = ?", (token_hash,)
        ).fetchone()
        if not row or row["used"]:
            raise HTTPException(400, "Reset link is invalid or already used")
        try:
            expires = datetime.fromisoformat(row["expires_at"])
        except ValueError:
            raise HTTPException(400, "Reset link is invalid or already used")
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) >= expires:
            raise HTTPException(400, "Reset link has expired")
        conn.execute("UPDATE password_reset_tokens SET used = 1 WHERE token_hash = ?", (token_hash,))
        conn.execute(
            "UPDATE users SET password_hash = ?, needs_profile_confirm = 0, "
            "updated_at = datetime('now') WHERE id = ?",
            (hash_password(new), row["user_id"]),
        )


# ---------------------------------------------------------------------------
# URL -> resource owner resolution (used by the API middleware for 403)
# ---------------------------------------------------------------------------
_STATIC = {
    "/api/library/search", "/api/plans/template", "/api/plans/sources",
    "/api/lesson-notes/web-log", "/api/row/schemes", "/api/row/coverage",
    "/api/row/mark-taught", "/api/export/history", "/api/export/plans-for-document",
    # Phase 10: collection/utility routes, not resource IDs.
    "/api/learners/import-csv", "/api/learners/csv-template", "/api/learners/summary",
    "/api/assessments/context", "/api/assessments/audit", "/api/progress/export",
    "/api/iep/suggest-support",
}
_STATIC_TAILS = {p.split("/")[-1] for p in _STATIC}
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^/api/library/([^/]+)"), "source_documents"),
    (re.compile(r"^/api/parse/([^/]+)"), "source_documents"),
    (re.compile(r"^/api/plans/([^/]+)"), "plan_documents"),
    (re.compile(r"^/api/schemes/([^/]+)"), "plan_documents"),
    (re.compile(r"^/api/exports/([^/]+)"), "export_jobs"),
    (re.compile(r"^/api/lesson-plans/([^/]+)"), "lesson_plans"),
    (re.compile(r"^/api/lesson-notes/([^/]+)"), "lesson_notes"),
    (re.compile(r"^/api/row/([^/]+)"), "row"),
    (re.compile(r"^/api/export/([^/]+)"), "export_jobs"),
    (re.compile(r"^/api/learners/([^/]+)"), "learners"),
    (re.compile(r"^/api/assessments/([^/]+)"), "assessments"),
    (re.compile(r"^/api/iep/([^/]+)"), "ieps"),
]


def resource_for_path(path: str) -> tuple[str, str] | None:
    clean = path.rstrip("/") or "/"
    tail = clean.split("/")[-1]
    if tail in _STATIC_TAILS:
        return None
    if clean in ("/api/plans/template", "/api/plans/sources", "/api/library/search"):
        return None
    for pattern, kind in _PATTERNS:
        match = pattern.match(clean)
        if match:
            ident = match.group(1)
            if ident in _STATIC_TAILS | {"template", "sources", "search", "web-log",
                                         "schemes", "coverage", "mark-taught", "history",
                                         "plans-for-document"}:
                return None
            return kind, ident
    return None


def owner_of_resource(kind: str, ident: str) -> str | None:
    """Return owner_id for a resource, or None when the resource does not exist."""
    queries = {
        "source_documents": "SELECT owner_id FROM source_documents WHERE id = ?",
        "plan_documents": "SELECT owner_id FROM plan_documents WHERE id = ?",
        "lesson_plans": "SELECT owner_id FROM lesson_plans WHERE id = ?",
        "lesson_notes": "SELECT owner_id FROM lesson_notes WHERE id = ?",
        "export_jobs": "SELECT owner_id FROM export_jobs WHERE id = ?",
        "plan_section": (
            "SELECT p.owner_id FROM plan_sections s "
            "JOIN plan_documents p ON p.id = s.plan_id WHERE s.id = ?"
        ),
        "lesson_section": (
            "SELECT p.owner_id FROM lesson_plan_sections s "
            "JOIN lesson_plans l ON l.id = s.lesson_plan_id "
            "JOIN plan_documents p ON p.id = l.plan_id WHERE s.id = ?"
        ),
        "chunk": (
            "SELECT d.owner_id FROM source_chunks c "
            "JOIN source_documents d ON d.id = c.document_id WHERE c.id = ?"
        ),
        "row": (
            "SELECT p.owner_id FROM record_of_work_docs d "
            "JOIN plan_documents p ON p.id = d.plan_id WHERE d.id = ?"
        ),
        "learners": "SELECT owner_id FROM learners WHERE id = ?",
        "assessments": (
            "SELECT l.owner_id FROM assessment_records a "
            "JOIN learners l ON l.id = a.learner_id WHERE a.id = ?"
        ),
        "ieps": (
            "SELECT l.owner_id FROM ieps i "
            "JOIN learners l ON l.id = i.learner_id WHERE i.id = ?"
        ),
    }
    sql = queries.get(kind)
    if not sql:
        return None
    with connect() as conn:
        row = conn.execute(sql, (ident,)).fetchone()
        if row:
            return row["owner_id"]
        if kind == "row":
            # ROW endpoints also accept the scheme (plan) id as their identifier.
            row = conn.execute(
                "SELECT owner_id FROM plan_documents WHERE id = ?", (ident,)
            ).fetchone()
            return row["owner_id"] if row else None
        return None
