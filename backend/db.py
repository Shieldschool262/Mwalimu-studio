"""SQLite persistence for Mwalimu Studio (studio.db).

Phase 2 adds: original text snapshots (for inline Undo), the NeedsReview status,
and the on-disk PDF store that every chunk links back to.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("MWALIMU_STUDIO_DB", BACKEND_ROOT / "studio.db"))
UPLOADS_DIR = Path(os.environ.get("MWALIMU_STUDIO_UPLOADS", BACKEND_ROOT / "uploads"))

_lock = threading.Lock()

PARSER_VERSION = "studio-parser-v1"

REVIEW_STATES = ("Parsed", "TeacherCorrected", "Approved")

# Document lifecycle:
#   Parsed      - engine finished, nothing reviewed yet
#   NeedsReview - teacher has started reviewing (any correction/approval)
#   Approved    - approved and saved to the library
#   Failed      - engine could not read the document
DOC_STATUSES = ("Parsed", "NeedsReview", "Approved", "Failed")

SCHEMA = """
-- Phase 9: individual teacher accounts. One user = one private Workspace.
-- There is deliberately no shared school view or multi-teacher entity.
CREATE TABLE IF NOT EXISTS users (
    id                   TEXT PRIMARY KEY,
    email                TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash        TEXT NOT NULL,
    name                 TEXT NOT NULL,
    role                 TEXT NOT NULL DEFAULT 'Teacher',
    tsc_no               TEXT NOT NULL DEFAULT '',
    county               TEXT NOT NULL DEFAULT '',
    school_name          TEXT NOT NULL DEFAULT '',
    grades_json          TEXT NOT NULL DEFAULT '[]',
    subjects_json        TEXT NOT NULL DEFAULT '[]',
    preferences_json     TEXT NOT NULL DEFAULT '{}',
    needs_profile_confirm INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    token_hash  TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at  TEXT NOT NULL,
    used        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_settings (
    owner_id      TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    settings_json TEXT NOT NULL DEFAULT '{}',
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS source_documents (
    id              TEXT PRIMARY KEY,
    file_name       TEXT NOT NULL,
    grade           TEXT NOT NULL,
    subject         TEXT NOT NULL,
    archetype       TEXT,
    archetype_confidence REAL,
    archetype_reason TEXT,
    parser_version  TEXT NOT NULL,
    status          TEXT NOT NULL,
    parse_meta      TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS source_chunks (
    id               TEXT PRIMARY KEY,
    document_id      TEXT NOT NULL REFERENCES source_documents(id) ON DELETE CASCADE,
    ord              INTEGER NOT NULL,
    page_number      INTEGER,
    theme            TEXT,
    theme_code       TEXT,
    strand           TEXT,
    strand_code      TEXT,
    sub_strand       TEXT NOT NULL,
    sub_strand_code  TEXT,
    lessons          INTEGER,
    structured_fields TEXT NOT NULL DEFAULT '{}',
    original_fields  TEXT NOT NULL DEFAULT '{}',
    confidence       REAL NOT NULL DEFAULT 1.0,
    flags            TEXT NOT NULL DEFAULT '[]',
    review_state     TEXT NOT NULL DEFAULT 'Parsed',
    appendix_resources  TEXT,
    appendix_assessment TEXT,
    appendix_source     TEXT,
    appendix_level      TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_chunk_doc_strand_sub
    ON source_chunks(document_id, strand_code, sub_strand_code, sub_strand);
CREATE INDEX IF NOT EXISTS ix_chunk_doc ON source_chunks(document_id, ord);

-- ---------------------------------------------------------------------------
-- Phase 3: planning workspace
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS plan_documents (
    id               TEXT PRIMARY KEY,
    type             TEXT NOT NULL,
    title            TEXT NOT NULL,
    grade            TEXT NOT NULL,
    subject          TEXT NOT NULL,
    term             TEXT,
    template_version TEXT NOT NULL DEFAULT 'cbe-scheme-v1',
    status           TEXT NOT NULL DEFAULT 'Draft',
    source_chunk_ids TEXT NOT NULL DEFAULT '[]',
    ai_expanded      INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS plan_sections (
    id            TEXT PRIMARY KEY,
    plan_id       TEXT NOT NULL REFERENCES plan_documents(id) ON DELETE CASCADE,
    ord           INTEGER NOT NULL,
    strand_code   TEXT,
    strand        TEXT,
    sub_strand    TEXT NOT NULL,
    sub_strand_code TEXT,
    outcomes      TEXT NOT NULL DEFAULT '[]',
    experiences   TEXT NOT NULL DEFAULT '[]',
    kiqs          TEXT NOT NULL DEFAULT '[]',
    competencies  TEXT,
    values_text   TEXT,
    pcis          TEXT,
    link_other    TEXT,
    resources     TEXT,
    assessment    TEXT,
    reflection    TEXT,
    edited        INTEGER NOT NULL DEFAULT 0,
    original      TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS plan_citations (
    id           TEXT PRIMARY KEY,
    plan_id      TEXT NOT NULL REFERENCES plan_documents(id) ON DELETE CASCADE,
    section_id   TEXT NOT NULL REFERENCES plan_sections(id) ON DELETE CASCADE,
    chunk_id     TEXT NOT NULL,
    page_number  INTEGER,
    field        TEXT NOT NULL,
    document_id  TEXT,
    sub_strand_code TEXT
);

CREATE INDEX IF NOT EXISTS ix_plan_section_plan ON plan_sections(plan_id, ord);
CREATE INDEX IF NOT EXISTS ix_plan_citation_plan ON plan_citations(plan_id);
CREATE INDEX IF NOT EXISTS ix_plan_citation_section ON plan_citations(section_id);

-- ---------------------------------------------------------------------------
-- Phase 4: version history, undo stack and KICD lesson plans
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS plan_versions (
    id              TEXT PRIMARY KEY,
    plan_id         TEXT NOT NULL REFERENCES plan_documents(id) ON DELETE CASCADE,
    version_number  INTEGER NOT NULL,
    label           TEXT NOT NULL DEFAULT '',
    comment         TEXT NOT NULL,
    kind            TEXT NOT NULL DEFAULT 'version',
    snapshot_json   TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS plan_edits (
    id          TEXT PRIMARY KEY,
    plan_id     TEXT NOT NULL REFERENCES plan_documents(id) ON DELETE CASCADE,
    section_id  TEXT,
    field       TEXT NOT NULL,
    prev_value  TEXT,
    prev_edited INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS lesson_plans (
    id                TEXT PRIMARY KEY,
    plan_id           TEXT NOT NULL REFERENCES plan_documents(id) ON DELETE CASCADE,
    section_id        TEXT NOT NULL REFERENCES plan_sections(id) ON DELETE CASCADE,
    chunk_id          TEXT,
    document_id       TEXT,
    lesson            INTEGER NOT NULL,
    lesson_count      INTEGER NOT NULL DEFAULT 5,
    week              INTEGER NOT NULL,
    strand            TEXT,
    sub_strand        TEXT,
    sub_strand_code   TEXT,
    focus             TEXT,
    focus_keyword     TEXT,
    source_experience TEXT,
    date              TEXT,
    time              TEXT,
    duration          INTEGER DEFAULT 35,
    class_size        INTEGER,
    status            TEXT NOT NULL DEFAULT 'Draft',
    header            TEXT NOT NULL DEFAULT '{}',
    source_json       TEXT NOT NULL DEFAULT '{}',
    assessment_json   TEXT NOT NULL DEFAULT '{}',
    ai_extras         TEXT NOT NULL DEFAULT '{}',
    ai_enriched       INTEGER NOT NULL DEFAULT 0,
    ai_provider       TEXT,
    ai_timestamp      TEXT,
    split_override    TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_lesson_plan_section_lesson
    ON lesson_plans(section_id, lesson);
CREATE INDEX IF NOT EXISTS ix_lesson_plan_plan ON lesson_plans(plan_id, week);

CREATE TABLE IF NOT EXISTS lesson_plan_sections (
    id              TEXT PRIMARY KEY,
    lesson_plan_id  TEXT NOT NULL REFERENCES lesson_plans(id) ON DELETE CASCADE,
    ord             INTEGER NOT NULL,
    key             TEXT NOT NULL,
    title           TEXT NOT NULL,
    body            TEXT NOT NULL DEFAULT '',
    placeholder     TEXT,
    hint            TEXT,
    provenance      TEXT NOT NULL DEFAULT 'empty',
    source_quote    TEXT,
    editable        INTEGER NOT NULL DEFAULT 1,
    ai_draft        TEXT,
    ai_assisted     INTEGER NOT NULL DEFAULT 0,
    ai_provider     TEXT,
    ai_timestamp    TEXT
);

CREATE INDEX IF NOT EXISTS ix_lesson_section_plan ON lesson_plan_sections(lesson_plan_id, ord);

CREATE TABLE IF NOT EXISTS lesson_plan_versions (
    id              TEXT PRIMARY KEY,
    lesson_plan_id  TEXT NOT NULL REFERENCES lesson_plans(id) ON DELETE CASCADE,
    version_number  INTEGER NOT NULL,
    label           TEXT NOT NULL DEFAULT '',
    comment         TEXT NOT NULL,
    snapshot_json   TEXT NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS lesson_plan_edits (
    id             TEXT PRIMARY KEY,
    lesson_plan_id TEXT NOT NULL REFERENCES lesson_plans(id) ON DELETE CASCADE,
    section_id     TEXT,
    field          TEXT NOT NULL,
    prev_value     TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- Phase 5: learner-facing Lesson Notes (one document per LESSON)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lesson_notes (
    id               TEXT PRIMARY KEY,
    lesson_plan_id   TEXT REFERENCES lesson_plans(id) ON DELETE SET NULL,
    plan_id          TEXT NOT NULL REFERENCES plan_documents(id) ON DELETE CASCADE,
    section_id       TEXT NOT NULL REFERENCES plan_sections(id) ON DELETE CASCADE,
    chunk_id         TEXT,
    document_id      TEXT,
    week             INTEGER NOT NULL,
    lesson           INTEGER NOT NULL,
    lesson_count     INTEGER NOT NULL DEFAULT 5,
    strand           TEXT,
    sub_strand       TEXT,
    sub_strand_code  TEXT,
    focus            TEXT,
    focus_keyword    TEXT,
    title            TEXT NOT NULL,
    grade            TEXT,
    subject          TEXT,
    term             TEXT,
    status           TEXT NOT NULL DEFAULT 'Draft',
    template_version TEXT NOT NULL DEFAULT 'cbe-lesson-notes-v1',
    source_json      TEXT NOT NULL DEFAULT '{}',
    ai_enriched      INTEGER NOT NULL DEFAULT 0,
    ai_provider      TEXT,
    ai_timestamp     TEXT,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_lesson_note_section_lesson
    ON lesson_notes(section_id, lesson);
CREATE INDEX IF NOT EXISTS ix_lesson_note_plan ON lesson_notes(plan_id, week, lesson);

CREATE TABLE IF NOT EXISTS lesson_note_sections (
    id             TEXT PRIMARY KEY,
    note_id        TEXT NOT NULL REFERENCES lesson_notes(id) ON DELETE CASCADE,
    ord            INTEGER NOT NULL,
    key            TEXT NOT NULL,
    title          TEXT NOT NULL,
    body           TEXT NOT NULL DEFAULT '',
    data_json      TEXT NOT NULL DEFAULT '{}',
    source_body    TEXT,
    source_data_json TEXT NOT NULL DEFAULT '{}',
    placeholder    TEXT,
    hint           TEXT,
    provenance     TEXT NOT NULL DEFAULT 'source',
    editable       INTEGER NOT NULL DEFAULT 1,
    ai_draft       TEXT,
    ai_data_json   TEXT NOT NULL DEFAULT '{}',
    ai_assisted    INTEGER NOT NULL DEFAULT 0,
    ai_provider    TEXT,
    ai_timestamp   TEXT
);

CREATE INDEX IF NOT EXISTS ix_lesson_note_section_note ON lesson_note_sections(note_id, ord);

CREATE TABLE IF NOT EXISTS lesson_note_versions (
    id             TEXT PRIMARY KEY,
    note_id        TEXT NOT NULL REFERENCES lesson_notes(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    label          TEXT NOT NULL DEFAULT '',
    comment        TEXT NOT NULL,
    kind           TEXT NOT NULL DEFAULT 'version',
    snapshot_json  TEXT NOT NULL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS lesson_note_sources (
    id         TEXT PRIMARY KEY,
    note_id    TEXT NOT NULL REFERENCES lesson_notes(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    title      TEXT,
    url        TEXT,
    text       TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_lesson_note_source_note ON lesson_note_sources(note_id, created_at);

-- Phase 6: Record of Work (ROW) - retrospective "what WAS taught".
-- ONE document per scheme (id = plan_id), ONE row per scheme lesson.
-- Generated rows carry origin='planned'; carry-overs are extra audit rows and never
-- replace the original.
CREATE TABLE IF NOT EXISTS record_of_work_docs (
    id                  TEXT PRIMARY KEY,
    plan_id             TEXT NOT NULL UNIQUE REFERENCES plan_documents(id) ON DELETE CASCADE,
    title               TEXT NOT NULL DEFAULT 'Record of Work',
    status              TEXT NOT NULL DEFAULT 'Draft',
    final_version_label TEXT,
    header_json         TEXT NOT NULL DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS record_of_work_rows (
    id              TEXT PRIMARY KEY,
    doc_id          TEXT NOT NULL REFERENCES record_of_work_docs(id) ON DELETE CASCADE,
    plan_id         TEXT NOT NULL,
    scheme_row_id   TEXT NOT NULL,
    lesson_plan_id  TEXT,
    origin          TEXT NOT NULL DEFAULT 'planned',
    source_row_id   TEXT,
    carry_over_note TEXT,
    week            INTEGER NOT NULL,
    lesson          INTEGER NOT NULL,
    date            TEXT NOT NULL DEFAULT '',
    strand          TEXT,
    sub_strand      TEXT,
    focus_keyword   TEXT,
    planned_work    TEXT NOT NULL DEFAULT '',
    work_done       TEXT NOT NULL DEFAULT '',
    reflection      TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT '',
    carry_over_to   TEXT,
    signature       TEXT NOT NULL DEFAULT '',
    source          TEXT NOT NULL DEFAULT 'auto-filled from Scheme',
    edited          INTEGER NOT NULL DEFAULT 0,
    ai_draft        TEXT,
    ai_enriched     INTEGER NOT NULL DEFAULT 0,
    ai_provider     TEXT,
    ai_timestamp    TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- A scheme lesson gets exactly ONE generated row. Carry-over rows are intentionally
-- excluded so the same target week/lesson can receive more than one carry-over.
CREATE UNIQUE INDEX IF NOT EXISTS ix_row_planned_lesson
    ON record_of_work_rows(doc_id, scheme_row_id, lesson) WHERE origin = 'planned';
CREATE INDEX IF NOT EXISTS ix_row_doc_week ON record_of_work_rows(doc_id, week, lesson);

CREATE TABLE IF NOT EXISTS record_of_work_versions (
    id             TEXT PRIMARY KEY,
    doc_id         TEXT NOT NULL REFERENCES record_of_work_docs(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    label          TEXT NOT NULL DEFAULT '',
    comment        TEXT NOT NULL,
    kind           TEXT NOT NULL DEFAULT 'version',
    snapshot_json  TEXT NOT NULL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_row_version_doc ON record_of_work_versions(doc_id, version_number);

-- Phase 7: Term Pack export jobs. Files live under exports/; metadata here enables
-- progress polling, history, DELETE, and 30-day cleanup.
CREATE TABLE IF NOT EXISTS export_jobs (
    id            TEXT PRIMARY KEY,
    plan_id       TEXT NOT NULL,
    teacher_id    TEXT NOT NULL DEFAULT '',
    includes_json TEXT NOT NULL DEFAULT '{}',
    format        TEXT NOT NULL DEFAULT 'pdf',
    status        TEXT NOT NULL DEFAULT 'queued',
    progress      INTEGER NOT NULL DEFAULT 0,
    progress_text TEXT NOT NULL DEFAULT '',
    file_name     TEXT NOT NULL DEFAULT '',
    file_path     TEXT NOT NULL DEFAULT '',
    file_url      TEXT NOT NULL DEFAULT '',
    file_size     INTEGER NOT NULL DEFAULT 0,
    page_count    INTEGER NOT NULL DEFAULT 0,
    manifest_json TEXT NOT NULL DEFAULT '{}',
    error         TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS ix_export_jobs_plan ON export_jobs(plan_id, created_at);

-- Phase 8: teacher-written TERM reflection (never AI-generated, never per-lesson).
CREATE TABLE IF NOT EXISTS term_reflections (
    id          TEXT PRIMARY KEY,
    plan_id     TEXT NOT NULL,
    teacher     TEXT NOT NULL DEFAULT '',
    term        TEXT NOT NULL DEFAULT '',
    year        TEXT NOT NULL DEFAULT '',
    reflection  TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(plan_id, term, year)
);

-- ---------------------------------------------------------------------------
-- Phase 10: My Learners, assessment records and IEPs.
-- All learner data is private to the teacher who entered it. There is no school,
-- headteacher or shared-class entity; no learner name ever enters a Term Pack by
-- default.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS learners (
    id            TEXT PRIMARY KEY,
    owner_id      TEXT NOT NULL DEFAULT '',
    grade         TEXT NOT NULL DEFAULT '',
    learning_area TEXT NOT NULL DEFAULT '',
    class_name    TEXT NOT NULL DEFAULT '',
    first_name    TEXT NOT NULL,
    last_name     TEXT NOT NULL,
    admission_no  TEXT NOT NULL DEFAULT '',
    gender        TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL DEFAULT 'Active',
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_learners_owner_class
    ON learners(owner_id, grade, learning_area, class_name, status);

CREATE TABLE IF NOT EXISTS assessment_records (
    id             TEXT PRIMARY KEY,
    owner_id       TEXT NOT NULL DEFAULT '',
    learner_id     TEXT NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    chunk_id       TEXT NOT NULL DEFAULT '',
    scheme_row_id  TEXT NOT NULL DEFAULT '',
    strand         TEXT NOT NULL DEFAULT '',
    sub_strand     TEXT NOT NULL DEFAULT '',
    focus_keyword  TEXT NOT NULL DEFAULT '',
    week           INTEGER NOT NULL DEFAULT 0,
    lesson         INTEGER NOT NULL DEFAULT 0,
    level          TEXT NOT NULL DEFAULT 'Not Assessed',
    evidence       TEXT NOT NULL DEFAULT '',
    date           TEXT NOT NULL DEFAULT '',
    source         TEXT NOT NULL DEFAULT 'Class Activity',
    ai_enriched    INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_assessment_lesson
    ON assessment_records(learner_id, scheme_row_id, week, lesson);
CREATE INDEX IF NOT EXISTS ix_assessment_owner ON assessment_records(owner_id, learner_id, date);

CREATE TABLE IF NOT EXISTS assessment_audit (
    id            TEXT PRIMARY KEY,
    owner_id      TEXT NOT NULL DEFAULT '',
    learner_id    TEXT NOT NULL,
    assessment_id TEXT NOT NULL DEFAULT '',
    old_level     TEXT NOT NULL DEFAULT '',
    new_level     TEXT NOT NULL DEFAULT '',
    changed_by    TEXT NOT NULL DEFAULT '',
    changed_at    TEXT NOT NULL DEFAULT (datetime('now')),
    reason        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_assessment_audit_learner
    ON assessment_audit(owner_id, learner_id, changed_at);

CREATE TABLE IF NOT EXISTS ieps (
    id           TEXT PRIMARY KEY,
    owner_id     TEXT NOT NULL DEFAULT '',
    learner_id   TEXT NOT NULL REFERENCES learners(id) ON DELETE CASCADE,
    need         TEXT NOT NULL DEFAULT '',
    goal         TEXT NOT NULL DEFAULT '',
    support      TEXT NOT NULL DEFAULT '',
    materials    TEXT NOT NULL DEFAULT '',
    review_date  TEXT NOT NULL DEFAULT '',
    review_week  INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'Active',
    ai_enriched  INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_ieps_owner ON ieps(owner_id, learner_id, status);

CREATE TABLE IF NOT EXISTS iep_reviews (
    id         TEXT PRIMARY KEY,
    owner_id   TEXT NOT NULL DEFAULT '',
    iep_id     TEXT NOT NULL REFERENCES ieps(id) ON DELETE CASCADE,
    date       TEXT NOT NULL DEFAULT '',
    note       TEXT NOT NULL DEFAULT '',
    new_level  TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_iep_reviews_iep ON iep_reviews(owner_id, iep_id, date);
"""

# Columns added after the first release; applied idempotently to old databases.
MIGRATIONS = [
    ("source_chunks", "original_fields", "TEXT NOT NULL DEFAULT '{}'"),
    ("source_chunks", "vetting_status", "TEXT NOT NULL DEFAULT 'Pending'"),
    # Phase 3 corrected: official KICD scheme needs per-row week/lesson allocation and a
    # document-level header (school, year, lessons/week, total weeks).
    ("plan_documents", "header", "TEXT NOT NULL DEFAULT '{}'"),
    ("plan_documents", "allocation", "TEXT NOT NULL DEFAULT '{}'"),
    ("plan_sections", "week_start", "INTEGER"),
    ("plan_sections", "week_end", "INTEGER"),
    ("plan_sections", "lesson_start", "INTEGER"),
    ("plan_sections", "lesson_end", "INTEGER"),
    ("plan_sections", "lesson_count", "INTEGER"),
    ("plan_sections", "flags", "TEXT NOT NULL DEFAULT '[]'"),
    # Phase 3.5: appendix-sourced Learning Resources + Assessment (autofill only, never vetting).
    ("source_chunks", "appendix_resources", "TEXT"),
    ("source_chunks", "appendix_assessment", "TEXT"),
    ("source_chunks", "appendix_source", "TEXT"),
    ("source_chunks", "appendix_level", "TEXT"),
    # Phase 4: rubric parsed from the design's Assessment Rubrics table (never part of vetting).
    ("source_chunks", "assessment_rubric", "TEXT"),
    # Phase 4: unsaved-edit indicator + last saved version label.
    ("plan_documents", "dirty", "INTEGER NOT NULL DEFAULT 0"),
    ("plan_documents", "final_version_label", "TEXT"),
    # Phase 4 correction: grade-aware lesson templates, per-field source history and
    # structured Lesson Development / Assessment data.
    ("lesson_plans", "template_version", "TEXT"),
    ("lesson_plans", "header_source", "TEXT NOT NULL DEFAULT '{}'"),
    ("lesson_plan_sections", "source_body", "TEXT"),
    ("lesson_plan_sections", "data_json", "TEXT NOT NULL DEFAULT '{}'"),
    ("lesson_plan_sections", "source_data_json", "TEXT NOT NULL DEFAULT '{}'"),
    # Phase 9: every content row belongs to exactly one teacher Workspace.
    ("source_documents", "owner_id", "TEXT NOT NULL DEFAULT ''"),
    ("plan_documents", "owner_id", "TEXT NOT NULL DEFAULT ''"),
    ("lesson_plans", "owner_id", "TEXT NOT NULL DEFAULT ''"),
    ("lesson_notes", "owner_id", "TEXT NOT NULL DEFAULT ''"),
    ("record_of_work_docs", "owner_id", "TEXT NOT NULL DEFAULT ''"),
    ("record_of_work_rows", "owner_id", "TEXT NOT NULL DEFAULT ''"),
    ("export_jobs", "owner_id", "TEXT NOT NULL DEFAULT ''"),
    ("term_reflections", "owner_id", "TEXT NOT NULL DEFAULT ''"),
    # Phase 10 RLS: every child table also carries its owner so the DB guard can
    # cover all content tables uniformly, not just the roots.
    ("source_chunks", "owner_id", "TEXT NOT NULL DEFAULT ''"),
    ("plan_sections", "owner_id", "TEXT NOT NULL DEFAULT ''"),
    ("plan_citations", "owner_id", "TEXT NOT NULL DEFAULT ''"),
    ("plan_versions", "owner_id", "TEXT NOT NULL DEFAULT ''"),
    ("plan_edits", "owner_id", "TEXT NOT NULL DEFAULT ''"),
    ("lesson_plan_sections", "owner_id", "TEXT NOT NULL DEFAULT ''"),
    ("lesson_plan_versions", "owner_id", "TEXT NOT NULL DEFAULT ''"),
    ("lesson_plan_edits", "owner_id", "TEXT NOT NULL DEFAULT ''"),
    ("lesson_note_sections", "owner_id", "TEXT NOT NULL DEFAULT ''"),
    ("lesson_note_versions", "owner_id", "TEXT NOT NULL DEFAULT ''"),
    ("lesson_note_sources", "owner_id", "TEXT NOT NULL DEFAULT ''"),
    ("record_of_work_versions", "owner_id", "TEXT NOT NULL DEFAULT ''"),
]

# Content root tables whose rows carry owner_id; used by migration and account deletion.
OWNED_TABLES = (
    ("source_documents", "Designs"),
    ("plan_documents", "Schemes"),
    ("lesson_plans", "Lesson Plans"),
    ("lesson_notes", "Lesson Notes"),
    ("record_of_work_docs", "ROW"),
    ("export_jobs", "Exports"),
    ("learners", "Learners"),
    ("assessment_records", "Assessments"),
    ("assessment_audit", "Assessment History"),
    ("ieps", "IEPs"),
    ("iep_reviews", "IEP Reviews"),
)

# ---------------------------------------------------------------------------
# RLS equivalent for SQLite (Phases 9-10).
#
# SQLite has no native CREATE POLICY. `mwalimu_owner()` is SQLite's equivalent of
# Supabase's auth.uid(): it reads the signed-in teacher from the request-scoped
# JWT context. Every content table is listed here with its ownership predicate,
# and `connect()` installs a DB-level authorizer that DENIES any read or write on
# these tables when no teacher context is present. Application queries still add
# `WHERE owner_id = ?` for clarity and performance, but the DB guard is the
# safety net if one endpoint forgets it.
# ---------------------------------------------------------------------------
RLS_POLICIES: dict[str, str] = {
    "source_documents": "owner_id = mwalimu_owner()",
    "source_chunks": "owner_id = mwalimu_owner()",
    "plan_documents": "owner_id = mwalimu_owner()",
    "plan_sections": "owner_id = mwalimu_owner()",
    "plan_citations": "owner_id = mwalimu_owner()",
    "plan_versions": "owner_id = mwalimu_owner()",
    "plan_edits": "owner_id = mwalimu_owner()",
    "lesson_plans": "owner_id = mwalimu_owner()",
    "lesson_plan_sections": "owner_id = mwalimu_owner()",
    "lesson_plan_versions": "owner_id = mwalimu_owner()",
    "lesson_plan_edits": "owner_id = mwalimu_owner()",
    "lesson_notes": "owner_id = mwalimu_owner()",
    "lesson_note_sections": "owner_id = mwalimu_owner()",
    "lesson_note_versions": "owner_id = mwalimu_owner()",
    "lesson_note_sources": "owner_id = mwalimu_owner()",
    "record_of_work_docs": "owner_id = mwalimu_owner()",
    "record_of_work_rows": "owner_id = mwalimu_owner()",
    "record_of_work_versions": "owner_id = mwalimu_owner()",
    "export_jobs": "owner_id = mwalimu_owner()",
    "term_reflections": "owner_id = mwalimu_owner()",
    "learners": "owner_id = mwalimu_owner()",
    "assessment_records": "owner_id = mwalimu_owner()",
    "assessment_audit": "owner_id = mwalimu_owner()",
    "ieps": "owner_id = mwalimu_owner()",
    "iep_reviews": "owner_id = mwalimu_owner()",
    "user_settings": "owner_id = mwalimu_owner()",
}
RLS_TABLES = frozenset(RLS_POLICIES)
# Backfill path for legacy child rows that predate owner_id columns.
CHILD_OWNER_SOURCE: dict[str, tuple[str, str]] = {
    "source_chunks": ("source_documents", "document_id"),
    "plan_sections": ("plan_documents", "plan_id"),
    "plan_citations": ("plan_documents", "plan_id"),
    "plan_versions": ("plan_documents", "plan_id"),
    "plan_edits": ("plan_documents", "plan_id"),
    "lesson_plan_sections": ("lesson_plans", "lesson_plan_id"),
    "lesson_plan_versions": ("lesson_plans", "lesson_plan_id"),
    "lesson_plan_edits": ("lesson_plans", "lesson_plan_id"),
    "lesson_note_sections": ("lesson_notes", "note_id"),
    "lesson_note_versions": ("lesson_notes", "note_id"),
    "lesson_note_sources": ("lesson_notes", "note_id"),
    "record_of_work_versions": ("record_of_work_docs", "doc_id"),
}
_RLS_ACTIONS = frozenset((
    sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_INSERT,
    sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
))
_rls_bypass: ContextVar[bool] = ContextVar("mwalimu_rls_bypass", default=False)


@contextmanager
def rls_bypass():
    """Only for startup schema work / legacy migration, never for request handling."""
    token = _rls_bypass.set(True)
    try:
        yield
    finally:
        _rls_bypass.reset(token)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Lets the AFTER INSERT triggers stamp the current teacher's owner_id without
    # touching every legacy INSERT statement in the service layer.
    def _owner() -> str:
        from auth_service import current_owner_id
        return current_owner_id()

    conn.create_function("mwalimu_owner", 0, _owner)

    def _rls_authorizer(action: int, table: str | None, _column: str | None,
                        _db: str | None, _source: str | None) -> int:
        # Same shape as a Postgres RLS policy: no teacher token => no content rows.
        if action in _RLS_ACTIONS and (table or "").lower() in RLS_TABLES:
            from auth_service import current_owner_id
            if not current_owner_id() and not _rls_bypass.get():
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    conn.set_authorizer(_rls_authorizer)
    return conn


def init_db() -> None:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    # Schema and legacy migration are the only operations allowed without a
    # teacher token. They run inside an explicit DB-guard bypass.
    with _lock, rls_bypass(), connect() as conn:
        conn.executescript(SCHEMA)
        for table, column, decl in MIGRATIONS:
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if column not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        # No data loss: inherit each legacy child row's owner from its parent.
        for child, (parent, fk) in CHILD_OWNER_SOURCE.items():
            conn.execute(
                f"UPDATE {child} SET owner_id = "
                f"(SELECT p.owner_id FROM {parent} p WHERE p.id = {child}.{fk}) "
                f"WHERE owner_id IS NULL OR owner_id = ''"
            )
        # Indexes and owner-stamping triggers for EVERY guarded content table.
        for table in sorted(RLS_TABLES):
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS ix_owner_{table} ON {table}(owner_id)"
            )
            key = "owner_id" if table == "user_settings" else "id"
            conn.execute(
                f"""CREATE TRIGGER IF NOT EXISTS trg_owner_{table}
                    AFTER INSERT ON {table}
                    WHEN NEW.owner_id IS NULL OR NEW.owner_id = ''
                    BEGIN
                        UPDATE {table} SET owner_id = mwalimu_owner() WHERE {key} = NEW.{key};
                    END"""
            )


def new_id() -> str:
    return str(uuid.uuid4())


def upload_path(document_id: str) -> Path:
    return UPLOADS_DIR / f"{document_id}.pdf"


def store_upload(document_id: str, pdf_bytes: bytes) -> Path:
    """Keep the original PDF forever - chunks link back to it for re-parse."""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    path = upload_path(document_id)
    path.write_bytes(pdf_bytes)
    return path


def delete_upload(document_id: str) -> bool:
    path = upload_path(document_id)
    if path.exists():
        path.unlink()
        return True
    return False


def row_to_document(row: sqlite3.Row, chunks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    doc = {
        "id": row["id"],
        "fileName": row["file_name"],
        "grade": row["grade"],
        "subject": row["subject"],
        "archetype": row["archetype"],
        "archetypeConfidence": row["archetype_confidence"],
        "archetypeReason": row["archetype_reason"],
        "parserVersion": row["parser_version"],
        "status": row["status"],
        "parseMeta": json.loads(row["parse_meta"] or "{}"),
        "createdAt": row["created_at"],
        "hasOriginalPdf": upload_path(row["id"]).exists(),
    }
    if chunks is not None:
        doc["chunks"] = chunks
    return doc


def row_to_chunk(row: sqlite3.Row) -> dict[str, Any]:
    structured = json.loads(row["structured_fields"] or "{}")
    original = json.loads(row["original_fields"] or "{}")
    return {
        "id": row["id"],
        "documentId": row["document_id"],
        "ord": row["ord"],
        "pageNumber": row["page_number"],
        "theme": row["theme"],
        "themeCode": row["theme_code"],
        "strand": row["strand"],
        "strandCode": row["strand_code"],
        "subStrand": row["sub_strand"],
        "subStrandCode": row["sub_strand_code"],
        "lessons": row["lessons"],
        "structuredFields": structured,
        "originalFields": original,
        # Review-state derived flags so the UI never has to guess.
        "isAutoApproved": row["review_state"] == "Approved" and float(row["confidence"] or 0) < 1.0,
        "confidence": row["confidence"],
        "flags": json.loads(row["flags"] or "[]"),
        "reviewState": row["review_state"],
        "vettingStatus": row["vetting_status"] if "vetting_status" in row.keys() else "Pending",
        # Phase 3.5: appendix-sourced autofill values (informational, never part of vetting).
        "appendixResources": (
            row["appendix_resources"] if "appendix_resources" in row.keys() else None
        ),
        "appendixAssessment": (
            row["appendix_assessment"] if "appendix_assessment" in row.keys() else None
        ),
        "appendixSource": row["appendix_source"] if "appendix_source" in row.keys() else None,
        "appendixLevel": row["appendix_level"] if "appendix_level" in row.keys() else None,
        # Phase 4: parsed rubric rows matched to this chunk (informational only).
        "assessmentRubric": (
            json.loads(row["assessment_rubric"])
            if "assessment_rubric" in row.keys() and row["assessment_rubric"]
            else []
        ),
    }


def list_chunks(conn: sqlite3.Connection, document_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM source_chunks WHERE document_id = ? ORDER BY ord ASC", (document_id,)
    ).fetchall()
    return [row_to_chunk(r) for r in rows]


def get_document(document_id: str, with_chunks: bool = True) -> dict[str, Any] | None:
    with _lock, connect() as conn:
        row = conn.execute("SELECT * FROM source_documents WHERE id = ?", (document_id,)).fetchone()
        if row is None:
            return None
        chunks = list_chunks(conn, document_id) if with_chunks else None
        return row_to_document(row, chunks)


def get_chunk(document_id: str, chunk_id: str) -> dict[str, Any] | None:
    with _lock, connect() as conn:
        row = conn.execute(
            "SELECT * FROM source_chunks WHERE id = ? AND document_id = ?", (chunk_id, document_id)
        ).fetchone()
        return row_to_chunk(row) if row else None


def refresh_document_status(conn: sqlite3.Connection, document_id: str) -> str:
    """Derive document status from chunk review states.

    Approved only counts once the teacher saves to the library, so an in-progress
    review always reports NeedsReview. A document with zero reviewed chunks keeps
    its Parsed status.
    """
    row = conn.execute(
        "SELECT status FROM source_documents WHERE id = ?", (document_id,)
    ).fetchone()
    current = row["status"] if row else None
    if current in ("Approved", "Failed"):
        return current or "Parsed"

    states = [
        r["review_state"]
        for r in conn.execute(
            "SELECT review_state FROM source_chunks WHERE document_id = ?", (document_id,)
        ).fetchall()
    ]
    if not states:
        status = "Parsed"
    elif all(s == "Parsed" for s in states):
        status = "Parsed"
    else:
        status = "NeedsReview"
    conn.execute("UPDATE source_documents SET status = ? WHERE id = ?", (status, document_id))
    return status


def delete_document(document_id: str) -> bool:
    with _lock, connect() as conn:
        row = conn.execute("SELECT id FROM source_documents WHERE id = ?", (document_id,)).fetchone()
        if row is None:
            return False
        conn.execute("DELETE FROM source_chunks WHERE document_id = ?", (document_id,))
        conn.execute("DELETE FROM source_documents WHERE id = ?", (document_id,))
    delete_upload(document_id)
    return True


def backup_db_to(path: Path) -> None:
    with connect() as conn:
        if path.exists():
            path.unlink()
        shutil.copyfile(DB_PATH, path)
