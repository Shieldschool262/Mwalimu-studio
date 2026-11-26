"""Phase 9 acceptance - individual teacher auth and Workspace isolation.

Run: python backend/phase9_e2e_test.py
Uses a throwaway copy of studio.db; the real database is never touched.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import sqlite3
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
DB = "C:/tmp/mwalimu_phase9_acceptance.db"
for ext in ("", "-wal", "-shm"):
    p = Path(DB + ext)
    if p.exists():
        p.unlink()
shutil.copyfile(ROOT / "studio.db", DB)
os.environ["MWALIMU_STUDIO_DB"] = DB

from fastapi.testclient import TestClient  # noqa: E402

import auth_service as auth  # noqa: E402

# Direct DB checks in this script run as the migrated Workspace owner.
auth.set_owner(auth.MIGRATED_ID)
import main  # noqa: E402
from db import connect, new_id  # noqa: E402

passed = failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS: {name} {detail}")
    else:
        failed += 1
        print(f"FAIL: {name} {detail}")


def make_plan(owner: str, title: str) -> str:
    token = auth.set_owner(owner)
    try:
        with connect() as conn:
            pid = new_id()
            conn.execute(
                """INSERT INTO plan_documents
                   (id, type, title, grade, subject, term, owner_id)
                   VALUES (?, 'Scheme', ?, 'Grade 3', 'Mathematics', 'Term 1', ?)""",
                (pid, title, owner),
            )
        return pid
    finally:
        auth.reset_owner(token)


def main_checks() -> None:
    # Count before init/migration using the raw source DB columns available.
    src = sqlite3.connect(ROOT / "studio.db")
    before = {
        t: src.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("source_documents", "plan_documents", "lesson_plans", "lesson_notes")
    }
    src.close()

    with TestClient(main.app) as a_client, TestClient(main.app) as b_client:
        print("\n== 1. Migration ==")
        with connect() as conn:
            migrated = conn.execute("SELECT * FROM users WHERE id = ?", (auth.MIGRATED_ID,)).fetchone()
            after = {
                t: conn.execute(f"SELECT COUNT(*) FROM {t} WHERE owner_id = ?", (auth.MIGRATED_ID,)).fetchone()[0]
                for t in before
            }
        check("migrated account created", migrated is not None)
        check("no data loss in migration", before == after, f"{before} vs {after}")
        # The teacher may have already confirmed/edited the name on the live DB;
        # migration only seeds "My Space" for a brand-new migrated account.
        check("migrated account has a teacher name", migrated and bool(migrated["name"]),
              str(migrated["name"] if migrated else ""))
        check("password hash never plain", migrated and "Teacher123" not in migrated["password_hash"])

        print("\n== 2. Signup ==")
        ra = a_client.post("/api/auth/signup", json={
            "name": "Teacher A", "email": "a@example.com", "password": "Passw0rd",
            "grades": ["Grade 3"], "subjects": ["Mathematics"],
        })
        rb = b_client.post("/api/auth/signup", json={
            "name": "Teacher B", "email": "b@example.com", "password": "Passw0rd",
        })
        check("A signup", ra.status_code == 200, str(ra.status_code))
        check("B signup", rb.status_code == 200, str(rb.status_code))
        A, B = ra.json(), rb.json()
        check("A has own id", A["id"] != B["id"])
        check("A role is Teacher", A["role"] == "Teacher")
        check("A empty library", a_client.get("/api/library").json()["counts"]["myMaterials"] == 0)
        check("B empty library", b_client.get("/api/library").json()["counts"]["myMaterials"] == 0)
        check("A empty schemes", a_client.get("/api/plans").json()["count"] == 0)
        check("me has no password hash", "password_hash" not in a_client.get("/api/auth/me").json())

        print("\n== 3. Isolation ==")
        a_plan = make_plan(A["id"], "Maths Gr3")
        check("A sees own scheme", a_client.get("/api/plans").json()["count"] == 1)
        check("B sees 0 schemes", b_client.get("/api/plans").json()["count"] == 0)
        r = b_client.get(f"/api/plans/{a_plan}")
        check("B GET A scheme is 403", r.status_code == 403, str(r.status_code))
        check("B GET A scheme has no content", "Maths Gr3" not in r.text)
        check("B GET A ROW is 403", b_client.get(f"/api/row/{a_plan}").status_code == 403)
        check("B GET A dashboard is empty", b_client.get("/api/dashboard").json()["summary"]["planned"] == 0)
        # Body-supplied identifiers must be guarded too.
        check("B export A scheme is 403", b_client.post("/api/export", json={"planId": a_plan}).status_code == 403)
        with connect() as conn:
            leaked = conn.execute(
                "SELECT COUNT(*) FROM export_jobs WHERE plan_id = ? AND owner_id = ?", (a_plan, B["id"])
            ).fetchone()[0]
        check("no export job created for B on A's scheme", leaked == 0)

        print("\n== 4. Login / logout on the same laptop ==")
        a_client.post("/api/auth/logout")
        b_client.post("/api/auth/logout")
        check("A after logout is 401", a_client.get("/api/auth/me").status_code == 401)
        a_client.post("/api/auth/login", json={"email": "a@example.com", "password": "Passw0rd"})
        b_client.post("/api/auth/login", json={"email": "b@example.com", "password": "Passw0rd"})
        check("A logs back in", a_client.get("/api/auth/me").json()["name"] == "Teacher A")
        check("B logs back in", b_client.get("/api/auth/me").json()["name"] == "Teacher B")
        check("A still sees own scheme", a_client.get("/api/plans").json()["count"] == 1)
        check("B still sees no schemes", b_client.get("/api/plans").json()["count"] == 0)
        wrong = a_client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "Passw0rd"})
        check("generic auth error", wrong.status_code == 401 and "Invalid email or password" in wrong.text)

        print("\n== 5. My Space profile and cover identity ==")
        upd = a_client.put("/api/auth/me", json={
            "name": "Mr. J. Kamau", "tscNo": "123456", "grades": ["Grade 3"], "schoolName": "",
        })
        check("profile saved", upd.status_code == 200 and upd.json()["name"] == "Mr. J. Kamau")
        check("top-bar identity available from /me", a_client.get("/api/auth/me").json()["name"] == "Mr. J. Kamau")
        check("dashboard scoping still works", a_client.get("/api/dashboard").status_code == 200)
        # Cover text comes from the profile; blank school stays a handwriting line.
        from services.term_pack_pdf import _meta
        meta = _meta({"header": {"teacherName": "Old Name", "institution": "Old School"}}, None, upd.json())
        check("cover teacher from profile", meta["teacher"] == "Mr. J. Kamau")
        check("cover TSC from profile", meta["tscNo"] == "123456")
        check("no invented school", meta["school"] == "")

        print("\n== 6. Export All My Data ==")
        zip_a = a_client.get("/api/my-space/export-all")
        check("export-all downloads", zip_a.status_code == 200 and zip_a.headers["content-type"].startswith("application/zip"))
        z = zipfile.ZipFile(io.BytesIO(zip_a.content))
        manifest = json.loads(z.read("manifest.json"))
        check("manifest ownerId is A", manifest["ownerId"] == A["id"])
        schemes = json.loads(z.read("schemes.json"))
        check("ZIP has only A's scheme", len(schemes) == 1 and schemes[0]["id"] == a_plan)
        check("ZIP has no B id", B["id"] not in z.read("manifest.json").decode("utf-8"))
        check("ZIP has required parts", all(n in z.namelist() for n in (
            "designs.json", "schemes.json", "lesson-plans.json", "lesson-notes.json",
            "row.json", "exports.json", "manifest.json")))

        print("\n== 7. Delete account ==")
        b_plan = make_plan(B["id"], "English Gr4")
        check("B has one scheme before delete", b_client.get("/api/plans").json()["count"] == 1)
        bad = b_client.request("DELETE", "/api/auth/me", json={"confirmation": "delete"})
        check("lowercase delete rejected", bad.status_code == 422)
        gone = b_client.request("DELETE", "/api/auth/me", json={"confirmation": "DELETE"})
        check("B account deleted", gone.status_code == 200)
        check("B logged out", b_client.get("/api/auth/me").status_code == 401)
        with connect() as conn:
            check("B user row gone", conn.execute("SELECT 1 FROM users WHERE id = ?", (B["id"],)).fetchone() is None)
            check("B content gone", conn.execute("SELECT 1 FROM plan_documents WHERE id = ?", (b_plan,)).fetchone() is None)
            check("A content intact", conn.execute("SELECT 1 FROM plan_documents WHERE id = ?", (a_plan,)).fetchone() is not None)
        check("A can still sign in", a_client.get("/api/auth/me").json()["name"] == "Mr. J. Kamau")

        print("\n== 8. Security ==")
        with TestClient(main.app) as rate_client:
            for _ in range(5):
                rate_client.post("/api/auth/login", json={"email": "rate@example.com", "password": "Wrong123"})
            limited = rate_client.post("/api/auth/login", json={"email": "rate@example.com", "password": "Wrong123"})
            check("5 failures then 429", limited.status_code == 429 and "Too many attempts" in limited.text,
                  str(limited.status_code))
        token = "expired-token-for-test"
        th = hashlib.sha256(token.encode()).hexdigest()
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        with connect() as conn:
            conn.execute(
                "INSERT INTO password_reset_tokens (token_hash, user_id, expires_at) VALUES (?,?,?)",
                (th, A["id"], past),
            )
        expired = a_client.post("/api/auth/reset", json={"token": token, "password": "NewPassw0rd"})
        check("expired reset token rejected", expired.status_code == 400)
        fresh_token = a_client.post("/api/auth/forgot", json={"email": "a@example.com"}).json()["resetToken"]
        check("reset link contains no password", "Passw0rd" not in fresh_token)
        check("fresh reset token works", a_client.post("/api/auth/reset", json={
            "token": fresh_token, "password": "NewPassw0rd"}).status_code == 200)
        check("reset token single use", a_client.post("/api/auth/reset", json={
            "token": fresh_token, "password": "NewPassw0rd"}).status_code == 400)
        check("change password accepts new password", a_client.post("/api/auth/change-password", json={
            "currentPassword": "NewPassw0rd", "newPassword": "FinalPass1"}).status_code == 200)

        print("\n== 9. No school concepts in code ==")
        offenders = []
        for base in (ROOT, ROOT / ".." / "frontend" / "src"):
            for path in Path(base).rglob("*"):
                if path.suffix not in {".py", ".ts", ".tsx"} or "__pycache__" in str(path):
                    continue
                if path.name in {"phase9_e2e_test.py", "phase10_e2e_test.py"}:
                    # This file names the banned terms only to assert they are absent.
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                # Ignore comments that state these concepts are absent, plus the
                # one privacy warning the Phase 10 spec explicitly requires.
                code_lines = [line for line in text.splitlines()
                              if not line.lstrip().startswith(("#", "//", "*", "--"))]
                low = "\n".join(code_lines).replace(
                    "Only share with Headteacher if required.", "").lower()
                for banned in ("headteacher", "school-dashboard", "invite", "schoolid", "join-request"):
                    if banned in low:
                        offenders.append(f"{path.name}:{banned}")
        check("no banned school concepts", not offenders, str(sorted(set(offenders))))

    print(f"\n{passed}/{passed + failed} Phase 9 checks passed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main_checks()
