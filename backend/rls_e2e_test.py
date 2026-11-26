#!/usr/bin/env python3
"""RLS acceptance (SQLite equivalent): DB guard + two-teacher isolation."""
import os
import sqlite3
import sys
from pathlib import Path

DB = "C:/tmp/mwalimu_rls_e2e.db"
for ext in ("", "-wal", "-shm"):
    p = Path(DB + ext)
    if p.exists():
        p.unlink()
os.environ["MWALIMU_STUDIO_DB"] = DB

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import auth_service as auth  # noqa: E402
import db  # noqa: E402
import main  # noqa: E402
from db import connect, new_id  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name} {detail}")


print("=== 1. DB-level policy registry (RLS equivalent) ===")
check("every policy is owner_id = mwalimu_owner()",
      all(v == "owner_id = mwalimu_owner()" for v in db.RLS_POLICIES.values()),
      str(db.RLS_POLICIES))
check("content tables registered", len(db.RLS_TABLES) >= 25, str(len(db.RLS_TABLES)))
source = (ROOT / "db.py").read_text(encoding="utf-8")
check("authorizer installed in connect()", "set_authorizer" in source and "SQLITE_DENY" in source)
check("JWT context powers mwalimu_owner()", "current_owner_id" in source and "ContextVar" in source)

with TestClient(main.app) as c:
    print("\n=== 2. DB guard without a teacher token ===")
    try:
        with connect() as conn:
            conn.execute("SELECT COUNT(*) FROM learners").fetchone()
        blocked = False
    except sqlite3.DatabaseError:
        blocked = True
    check("no-token DB read denied", blocked)
    try:
        with connect() as conn:
            conn.execute("INSERT INTO learners (id,first_name,last_name) VALUES (?,?,?)",
                         (new_id(), "X", "Y"))
        write_blocked = False
    except sqlite3.DatabaseError:
        write_blocked = True
    check("no-token DB write denied", write_blocked)
    with db.rls_bypass(), connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM learners").fetchone()[0]
    check("startup bypass still works", count == 0, str(count))
    with db.rls_bypass(), connect() as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")]
        owned = [t for t in tables if "owner_id" in
                 {r["name"] for r in conn.execute(f"PRAGMA table_info({t})")}]
    check("every owner_id table is guarded", set(owned) <= set(db.RLS_TABLES),
          str(sorted(set(owned) - set(db.RLS_TABLES))))

    print("\n=== 3. Seed Teacher A's content ===")
    A = c.post("/api/auth/signup", json={"name": "Teacher A", "email": "rls-a@test.com",
                                         "password": "Passw0rd"}).json()
    aid = A["id"]
    plan_id, learner_id, assessment_id, iep_id, export_id = [new_id() for _ in range(5)]
    t = auth.set_owner(aid)
    with connect() as conn:
        conn.execute("INSERT INTO plan_documents (id,type,title,grade,subject) "
                     "VALUES (?,'scheme','A Scheme','Grade 3','Mathematics')", (plan_id,))
        conn.execute("INSERT INTO learners (id,grade,learning_area,class_name,first_name,last_name) "
                     "VALUES (?,'Grade 3','Mathematics','3B','Achieng','Test')", (learner_id,))
        conn.execute("INSERT INTO assessment_records (id,learner_id,scheme_row_id,level) "
                     "VALUES (?,?,'row-1','Meets')", (assessment_id, learner_id))
        conn.execute("INSERT INTO ieps (id,learner_id,need,goal,support,review_date) "
                     "VALUES (?,?,'need','goal','support','2027-01-01')", (iep_id, learner_id))
        conn.execute("INSERT INTO export_jobs (id,plan_id) VALUES (?,?)", (export_id, plan_id))
    auth.reset_owner(t)
    check("A sees own scheme", c.get(f"/api/schemes/{plan_id}").status_code == 200)

    print("\n=== 4. Teacher B: 403 for every A resource ===")
    c.post("/api/auth/logout")
    B = c.post("/api/auth/signup", json={"name": "Teacher B", "email": "rls-b@test.com",
                                         "password": "Passw0rd"}).json()
    check("B signed up", bool(B.get("id")))
    for label, path in (
        ("scheme", f"/api/schemes/{plan_id}"),
        ("learner", f"/api/learners/{learner_id}"),
        ("assessment", f"/api/assessments/{assessment_id}"),
        ("IEP", f"/api/iep/{iep_id}"),
        ("export", f"/api/exports/{export_id}"),
    ):
        r = c.get(path)
        check(f"B cannot read A's {label}", r.status_code == 403, f"{r.status_code} {r.text[:80]}")
    check("B cannot query A's assessment",
          c.get("/api/assessments", params={"learnerId": learner_id}).status_code == 403)
    check("B cannot query A's audit",
          c.get("/api/assessments/audit", params={"learnerId": learner_id}).status_code == 403)

    print("\n=== 5. Teacher B's lists are empty ===")
    scheme_list = c.get("/api/schemes").json()
    check("B schemes count 0", scheme_list.get("count") == 0, str(scheme_list)[:160])
    check("B learners count 0", c.get("/api/learners").json()["count"] == 0)
    check("B assessments count 0", c.get("/api/assessments").json()["count"] == 0)
    check("B IEPs count 0", c.get("/api/iep").json()["count"] == 0)
    check("B exports count 0", c.get("/api/exports").json()["jobs"] == [])

    print("\n=== 6. Delete B removes only B's rows ===")
    bid = B["id"]
    b_plan, b_learner, b_export = new_id(), new_id(), new_id()
    t = auth.set_owner(bid)
    with connect() as conn:
        conn.execute("INSERT INTO plan_documents (id,type,title,grade,subject) "
                     "VALUES (?,'scheme','B Scheme','Grade 4','English')", (b_plan,))
        conn.execute("INSERT INTO learners (id,grade,learning_area,class_name,first_name,last_name) "
                     "VALUES (?,'Grade 4','English','4A','Zawadi','Test')", (b_learner,))
        conn.execute("INSERT INTO export_jobs (id,plan_id) VALUES (?,?)", (b_export, b_plan))
    auth.reset_owner(t)
    check("B has own rows before delete", c.get("/api/schemes").json()["count"] == 1)
    deleted = c.request("DELETE", "/api/auth/me", json={"confirmation": "DELETE"})
    check("account deleted", deleted.status_code == 200, deleted.text[:120])
    with db.rls_bypass(), connect() as conn:
        def n(table, ident):
            return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE id = ?", (ident,)).fetchone()[0]
        a_ok = n("plan_documents", plan_id) == 1 and n("learners", learner_id) == 1
        b_gone = (n("plan_documents", b_plan) == 0 and n("learners", b_learner) == 0
                  and n("export_jobs", b_export) == 0)
    check("A's rows untouched", a_ok)
    check("B's rows all deleted", b_gone)

print(f"\n{passed}/{passed + failed} RLS acceptance checks passed")
raise SystemExit(1 if failed else 0)
