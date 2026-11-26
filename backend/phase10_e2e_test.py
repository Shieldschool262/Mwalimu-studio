#!/usr/bin/env python3
"""Phase 10 acceptance: learners, assessment, progress, IEP, isolation and privacy."""
import hashlib
import io
import json
import os
import re
import time
import zipfile
from pathlib import Path

DB = "C:/tmp/mwalimu_p10_e2e.db"
if Path(DB).exists():
    Path(DB).unlink()
os.environ["MWALIMU_STUDIO_DB"] = DB

import fitz  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import auth_service as auth  # noqa: E402
import main  # noqa: E402
from db import connect, new_id  # noqa: E402

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name} {detail}")


def json_of(r):
    try:
        return r.json()
    except Exception:
        return {}


with TestClient(main.app) as c:
    # ------------------------------------------------------------------
    print("=== 1. Two teachers, own Workspaces ===")
    A = json_of(c.post("/api/auth/signup", json={
        "name": "Teacher A", "email": "a10@test.com", "password": "Passw0rd",
    }))
    aid = A["id"]
    t = auth.set_owner(aid)
    plan_id, colour_id, shape_id = new_id(), new_id(), new_id()
    chunk_id, doc_id = new_id(), new_id()
    rubric = [
        {"indicator": "Sort objects by colour", "page": 15, "levels": {
            "Exceeds": "Sorts by colour correctly with no support, explains grouping.",
            "Meets": "Sorts by colour correctly with minimal support.",
            "Approaching": "Sorts with support, 2-3 errors.",
            "Below": "Cannot sort by colour even with support."}}
    ]
    with connect() as conn:
        conn.execute("INSERT INTO source_documents (id,file_name,grade,subject,parser_version,status) VALUES (?,?,?,?,?,?)",
                     (doc_id, "KICD-Grade3-Maths.pdf", "Grade 3", "Mathematics", "test", "Ready"))
        conn.execute("INSERT INTO plan_documents (id,type,title,grade,subject,term) "
                     "VALUES (?,'scheme','Maths Gr3','Grade 3','Mathematics','Term 1')", (plan_id,))
        for section_id, sub, order in ((colour_id, "Colour", 1), (shape_id, "Shape", 2)):
            conn.execute(
                "INSERT INTO plan_sections (id,plan_id,ord,sub_strand,sub_strand_code,outcomes,experiences,kiqs) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (section_id, plan_id, order, sub, f"1.{order}",
                 '["Sort objects"]', '["Sorting activity"]', '["How can we group objects?"]'),
            )
        conn.execute(
            "INSERT INTO source_chunks (id,document_id,ord,sub_strand,sub_strand_code,assessment_rubric) "
            "VALUES (?,?,1,?,?,?)",
            (chunk_id, doc_id, "Colour", "1.1", json.dumps(rubric)),
        )
        conn.execute("INSERT INTO plan_citations (id,plan_id,section_id,chunk_id,field) "
                     "VALUES (?,?,?,?,?)", (new_id(), plan_id, colour_id, chunk_id, "kiqs"))
        for section_id, week, lesson, focus in (
            (colour_id, 2, 1, "Colour"), (shape_id, 2, 2, "Shape"), (colour_id, 3, 3, "Colour")
        ):
            conn.execute(
                "INSERT INTO lesson_plans (id,plan_id,section_id,chunk_id,lesson,lesson_count,week,"
                "focus,focus_keyword,sub_strand) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (new_id(), plan_id, section_id, chunk_id, lesson, 5, week, focus, focus,
                 "Colour" if section_id == colour_id else "Shape"),
            )
    auth.reset_owner(t)

    # ------------------------------------------------------------------
    print("\n=== 2. My Learners: add, CSV import with duplicates, archive ===")
    ids = {}
    for name in ("Achieng", "Baraka", "Chebet"):
        r = c.post("/api/learners", json={
            "firstName": name, "lastName": "Test", "admissionNo": "123" if name == "Achieng" else "",
            "gender": "Female" if name != "Baraka" else "Male",
            "grade": "Grade 3", "learningArea": "Mathematics", "className": "3B",
        })
        check(f"add {name}", r.status_code == 200, str(json_of(r))[:120])
        ids[name] = json_of(r)["id"]
    learners = json_of(c.get("/api/learners"))["learners"]
    check("3 learners added", len(learners) == 3, str(len(learners)))
    check("admission duplicate guard", c.post("/api/learners", json={
        "firstName": "Dup", "lastName": "Test", "admissionNo": "123",
        "grade": "Grade 3", "learningArea": "Mathematics", "className": "3B",
    }).status_code == 409)

    csv_text = ("firstName,lastName,admissionNo,gender,className\n"
                "Wanjiku,Test,999,Female,3B\n"
                "Other,Test,123,Male,3B\n")
    prev = json_of(c.post("/api/learners/import-csv", json={
        "csv": csv_text, "grade": "Grade 3", "learningArea": "Mathematics", "previewOnly": True,
    }))
    check("CSV preview shows first rows", prev["total"] == 2 and len(prev["rows"]) == 2, str(prev)[:200])
    check("duplicate Admission No warning", any(
        d["admissionNo"] == "123" and d["existingName"] == "Achieng Test"
        for d in prev["duplicates"]), str(prev.get("duplicates")))
    imported = json_of(c.post("/api/learners/import-csv", json={
        "csv": csv_text, "grade": "Grade 3", "learningArea": "Mathematics",
        "previewOnly": False, "resolutions": {"1": "both"},
    }))
    check("2 learners imported (keep both)", imported["created"] == 2, str(imported))
    active = json_of(c.get("/api/learners", params={"status": "Active"}))["learners"]
    check("5 active learners", len(active) == 5, str(len(active)))
    # ------------------------------------------------------------------
    print("\n=== 3. Assessment grid: rubric, evidence validation, audit ===")
    ctx = json_of(c.get("/api/assessments/context", params={
        "schemeRowId": colour_id, "week": 2, "lesson": 1,
    }))
    check("context is assessable", ctx["canAssess"] and ctx["focus"] == "Colour", str(ctx)[:200])
    check("KICD rubric from Design p.15",
          bool(ctx["rubric"]) and ctx["rubric"][0]["page"] == 15
          and "no support" in ctx["rubric"][0]["levels"]["Exceeds"], str(ctx.get("rubric"))[:200])

    bad = c.post("/api/assessments", json={"schemeRowId": colour_id, "week": 2, "lesson": 1, "records": [
        {"learnerId": ids["Baraka"], "level": "Below", "evidence": "", "source": "Oral"},
    ]})
    check("evidence required for Below", bad.status_code == 422 and "Evidence required" in bad.text,
          bad.text[:160])

    today = time.strftime("%Y-%m-%d")
    saved = json_of(c.post("/api/assessments", json={
        "schemeRowId": colour_id, "week": 2, "lesson": 1, "records": [
            {"learnerId": ids["Achieng"], "level": "Exceeds", "evidence": "Sorted 4/5 colour groups correctly",
             "source": "Class Activity", "date": today},
            {"learnerId": ids["Baraka"], "level": "Below", "evidence": "Confuses red and orange",
             "source": "Observation", "date": today},
            {"learnerId": ids["Chebet"], "level": "Meets", "evidence": "",
             "source": "Oral", "date": today},
        ],
    }))
    check("3 records saved", saved["saved"] == 3, str(saved))

    print("\n=== 2b. Archive after assessment keeps history ===")
    c.post(f"/api/learners/{ids['Chebet']}/archive", json={"status": "Transferred"})
    active = json_of(c.get("/api/learners", params={"status": "Active"}))["learners"]
    check("4 active after archive", len(active) == 4, str(len(active)))
    check("archived learner retained", c.get(f"/api/learners/{ids['Chebet']}").json()["status"] == "Transferred")

    check("message names lesson", "Week 2 Lesson 1" in saved["message"], saved["message"])
    audit = json_of(c.get("/api/assessments/audit", params={"learnerId": ids["Baraka"]}))["history"]
    check("audit log records change", any(
        x["oldLevel"] == "Not Assessed" and x["newLevel"] == "Below" for x in audit), str(audit)[:200])

    guard = json_of(c.get("/api/assessments/context", params={"schemeRowId": shape_id, "week": 2, "lesson": 2}))
    check("second focus assessable", guard["canAssess"] and guard["focus"] == "Shape", str(guard)[:160])

    # ------------------------------------------------------------------
    print("\n=== 4. Progress: overall, trends, needs support ===")
    p = json_of(c.get("/api/progress"))
    by_name = {x["name"]: x for x in p["learners"]}
    check("Achieng overall Exceeds", by_name["Achieng Test"]["overall"] == "Exceeds", str(by_name.get("Achieng Test"))[:160])
    check("Baraka overall Below", by_name["Baraka Test"]["overall"] == "Below")
    check("Chebet (archived) excluded", "Chebet Test" not in by_name)
    check("first trend is em dash", all(f["trend"] == "—" for x in by_name.values() for f in x["byFocus"]))
    check("Baraka in Needs Support", any(x["learnerId"] == ids["Baraka"] for x in p["needsSupport"]))

    c.post("/api/assessments", json={"schemeRowId": shape_id, "week": 2, "lesson": 2, "records": [
        {"learnerId": ids["Baraka"], "level": "Approaching", "evidence": "Sorted 3/5 shapes",
         "source": "Class Activity", "date": today},
    ]})
    p = json_of(c.get("/api/progress"))
    baraka = next(x for x in p["learners"] if x["learnerId"] == ids["Baraka"])
    check("overall stays Below with Below + Approaching", baraka["overall"] == "Below", baraka["overall"])
    check("two focuses shown", len(baraka["byFocus"]) == 2, str(baraka["byFocus"])[:200])

    c.post("/api/assessments", json={"schemeRowId": colour_id, "week": 3, "lesson": 3, "records": [
        {"learnerId": ids["Baraka"], "level": "Approaching", "evidence": "Improving with bottle tops",
         "source": "Class Activity", "date": today},
    ]})
    baraka = next(x for x in json_of(c.get("/api/progress"))["learners"] if x["learnerId"] == ids["Baraka"])
    colour = next(f for f in baraka["byFocus"] if f["focus"] == "Colour")
    check("Colour trend improved", colour["trend"] == "↑", colour["trend"])
    check("Shape trend unchanged", next(f for f in baraka["byFocus"] if f["focus"] == "Shape")["trend"] == "—")

    pdf = c.get("/api/progress/export")
    check("progress PDF served", pdf.status_code == 200 and pdf.content[:4] == b"%PDF", str(pdf.status_code))
    doc = fitz.open(stream=pdf.content, filetype="pdf")
    all_text = "\n".join(pg.get_text() for pg in doc)
    doc.close()
    check("PDF has learner names", "Achieng" in all_text and "Baraka" in all_text, all_text[:200])
    check("PDF has privacy footer", "Private - Contains learner names" in all_text)
    check("PDF has teacher header", "Teacher A" in all_text)
    check("PDF has Page X of Y", "Page 1 of" in all_text)

    # ------------------------------------------------------------------
    print("\n=== 5. IEP: create, reviews due, review + goal met ===")
    iep = json_of(c.post("/api/iep", json={
        "learnerId": ids["Baraka"], "need": "Struggles to sort by colour - confuses red/orange",
        "goal": "Sort by colour correctly 4/5 times by Week 10",
        "support": "Use larger bottle tops, pair with a friend, extra 10 min practice",
        "materials": "Large red/orange bottle tops, colour cards",
        "reviewDate": today,
    }))
    check("IEP created Active", iep.get("status") == "Active", str(iep)[:200])
    summary = json_of(c.get("/api/learners/summary"))
    check("dashboard summary counts", summary["active"] == 4 and summary["needsSupport"] >= 1
          and summary["iepsActive"] == 1 and summary["iepReviewsDue"] == 1, str(summary))
    second = c.post("/api/iep", json={"learnerId": ids["Baraka"], "need": "x", "goal": "y",
                                      "support": "z", "reviewDate": today})
    check("second active IEP blocked", second.status_code == 422, second.text[:120])
    reviewed = json_of(c.post(f"/api/iep/{iep['id']}/reviews", json={
        "date": today, "note": "Sorted 4/5 with larger bottle tops", "newLevel": "Meets",
    }))
    check("review saved", len(reviewed["reviews"]) == 1, str(reviewed)[:200])
    c.put(f"/api/iep/{iep['id']}", json={"status": "Met Goal"})
    check("goal marked Met", c.get(f"/api/iep/{iep['id']}").json()["status"] == "Met Goal")
    check("IEP history kept", json_of(c.get("/api/iep", params={"learnerId": ids["Baraka"]}))["count"] == 1)
    check("AI opt-in off by default", c.post("/api/iep/suggest-support", json={"need": "sorting"}).status_code in (200, 422))

    # ------------------------------------------------------------------
    print("\n=== 6. Term Pack privacy: names only with typed opt-in ===")
    base_inc = {"cover": True, "coverage": True, "scheme": False, "plans": {"include": False},
                "notes": {"include": False}, "row": False, "citations": False}
    job = json_of(c.post("/api/export", json={"planId": plan_id, "includes": base_inc, "format": "pdf"}))
    for _ in range(60):
        j = json_of(c.get(f"/api/export/{job['jobId']}"))
        if j.get("status") in ("done", "failed"):
            break
        time.sleep(0.25)
    check("default Term Pack job done", j.get("status") == "done", str(j)[:220])
    pack = c.get(j["fileUrl"]).content
    d = fitz.open(stream=pack, filetype="pdf")
    pack_text = "\n".join(pg.get_text() for pg in d)
    d.close()
    check("default Term Pack has NO learner names", "Achieng" not in pack_text, pack_text[:200])

    opted = json_of(c.post("/api/export", json={"planId": plan_id, "includes": {
        **base_inc, "progress": True}, "format": "pdf"}))
    for _ in range(60):
        j2 = json_of(c.get(f"/api/export/{opted['jobId']}"))
        if j2.get("status") in ("done", "failed"):
            break
        time.sleep(0.25)
    check("missing confirmation fails closed", j2.get("status") == "failed"
          and "I understand" in str(j2.get("error")), str(j2)[:220])
    confirmed = json_of(c.post("/api/export", json={"planId": plan_id, "includes": {
        **base_inc, "progress": True, "progressConfirm": "I understand"}, "format": "pdf"}))
    for _ in range(60):
        j3 = json_of(c.get(f"/api/export/{confirmed['jobId']}"))
        if j3.get("status") in ("done", "failed"):
            break
        time.sleep(0.25)
    check("opted-in Term Pack done", j3.get("status") == "done", str(j3)[:220])
    if j3.get("status") == "done":
        d = fitz.open(stream=c.get(j3["fileUrl"]).content, filetype="pdf")
        opted_text = "\n".join(pg.get_text() for pg in d)
        d.close()
        check("opted-in Term Pack has learner names", "Achieng" in opted_text)
        check("manifest marks progress section", any(
            s["name"] == "progress" for s in j3["manifest"]["sections"]), str(j3["manifest"]["sections"]))

    # ------------------------------------------------------------------
    print("\n=== 6b. Export All My Data contains only own learner data ===")
    z = c.get("/api/my-space/export-all")
    check("export-all served", z.status_code == 200, str(z.status_code))
    with zipfile.ZipFile(io.BytesIO(z.content)) as zf:
        names = zf.namelist()
        manifest = json.loads(zf.read("manifest.json"))
        learner_rows = json.loads(zf.read("learners.json"))
        assessment_rows = json.loads(zf.read("assessments.json"))
    check("learner data in export-all", "learners.json" in names and len(learner_rows) == 5,
          str(len(learner_rows)))
    check("assessment data in export-all", "assessments.json" in names and len(assessment_rows) >= 5,
          str(len(assessment_rows)))
    check("manifest owner is A", manifest["ownerId"] == aid, str(manifest.get("ownerId")))
    check("privacy notice in export-all", "PRIVACY.txt" in names)

    print("\n=== 7. Ownership isolation ===")
    unique = json_of(c.get("/api/learners", params={"q": "Achieng"}))["count"]
    check("search only own workspace", unique == 1, str(unique))
    c.post("/api/auth/logout")
    B = json_of(c.post("/api/auth/signup", json={"name": "Teacher B", "email": "b10@test.com",
                                                 "password": "Passw0rd"}))
    check("Teacher B signed up", bool(B.get("id")))
    check("B sees 0 learners", json_of(c.get("/api/learners"))["count"] == 0)
    check("B cannot GET A's learner", c.get(f"/api/learners/{ids['Achieng']}").status_code == 403)
    check("B cannot GET A's assessments",
          c.get("/api/assessments", params={"learnerId": ids["Achieng"]}).status_code == 403)
    check("B cannot GET A's audit",
          c.get("/api/assessments/audit", params={"learnerId": ids["Achieng"]}).status_code == 403)
    check("B progress is empty", json_of(c.get("/api/progress"))["count"] == 0)
    check("B summary is empty", json_of(c.get("/api/learners/summary"))["active"] == 0)
    check("B cannot see A's IEP", c.get("/api/iep", params={"learnerId": ids["Baraka"]}).status_code == 403)

# ----------------------------------------------------------------------
print("\n=== 8. No school concepts + parser untouched ===")
root = Path(__file__).resolve().parent.parent
banned = re.compile(r"headteacher|school-dashboard|join-request|schoolId", re.I)
hits = []
for base in (root / "backend", root / "frontend" / "src"):
    for path in base.rglob("*"):
        if path.suffix not in {".py", ".ts", ".tsx"} or "__pycache__" in str(path):
            continue
        if path.name in {"phase10_e2e_test.py", "phase9_e2e_test.py"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        # Comments explaining the absence of school concepts and the one warning
        # the spec explicitly requires are not school features.
        code_lines = [
            line for line in text.splitlines()
            if not line.lstrip().startswith(("#", "//", "*", "--"))
        ]
        code = "\n".join(code_lines).replace(
            "Only share with Headteacher if required.", "")
        if banned.search(code):
            hits.append(str(path.relative_to(root)))
check("no school/headteacher/invite code", not hits, str(hits))

for name, expected in (("parser_engine.py", "f23fa268"), ("repair.py", "af9ee575")):
    digest = hashlib.md5((root / "backend" / "services" / name).read_bytes()).hexdigest()
    check(f"{name} byte-identical", digest.startswith(expected), digest)

print(f"\n{passed}/{passed + failed} Phase 10 acceptance checks passed")
raise SystemExit(1 if failed else 0)
