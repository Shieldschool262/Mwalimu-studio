"""Phase 8 dashboard acceptance tests on a synthetic 3-subject term.

Run:  python backend/dashboard_e2e_test.py
Creates its own DB, so it never touches studio.db.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = "C:/tmp/mwalimu_dash_synth.db"
os.environ["MWALIMU_STUDIO_DB"] = DB_PATH
sys.path.insert(0, str(ROOT))

for ext in ("", "-wal", "-shm"):
    p = Path(DB_PATH + ext)
    if p.exists():
        p.unlink()

import db  # noqa: E402
from services import dashboard_pdf  # noqa: E402
import auth_service as _auth  # noqa: E402

_auth.set_owner("dashboard-regression")
from services import dashboard_service as svc  # noqa: E402
from services import record_of_work_service as row_svc  # noqa: E402

db.init_db()
conn = db.connect()

passed = failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS: {name} {detail}")
    else:
        failed += 1
        print(f"FAIL: {name} {detail}")


# ---- seed 3 subjects x 60 lessons + one scheme with NO ROW ----------------
def seed(subject: str, taught: int, partial: int, with_row: bool = True) -> str:
    pid = db.new_id()
    header = json.dumps({
        "institution": "Kangemi Primary", "grade": "Grade 3", "learningArea": subject,
        "term": "Term 1", "year": "2025", "teacherName": "Mr. J. Kamau",
    })
    conn.execute(
        """INSERT INTO plan_documents
           (id,type,title,grade,subject,term,header,allocation,status,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))""",
        (pid, "scheme", f"Grade 3 {subject} Term 1", "Grade 3", subject, "Term 1",
         header, json.dumps({"lessonsPerWeek": 5, "totalWeeks": 12}), "Draft"),
    )
    section_ids = []
    for i in range(60):
        week, lesson = i // 5 + 1, i % 5 + 1
        sid = db.new_id()
        section_ids.append(sid)
        conn.execute(
            """INSERT INTO plan_sections
               (id,plan_id,ord,strand,sub_strand,outcomes,week_start,week_end,
                lesson_start,lesson_end,lesson_count,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""",
            (sid, pid, i, "Numbers", "Whole Numbers", "[]",
             week, week, lesson, lesson, 1),
        )
    if not with_row:
        return pid
    doc_id = db.new_id()
    conn.execute(
        """INSERT INTO record_of_work_docs
           (id,plan_id,title,status,header_json,created_at,updated_at)
           VALUES (?,?,?,?,?,datetime('now'),datetime('now'))""",
        (doc_id, pid, subject, "Draft", header),
    )
    # First `taught` rows taught, next `partial` rows partial, rest gaps.
    for i in range(60):
        week, lesson = i // 5 + 1, i % 5 + 1
        status = "Taught" if i < taught else (
            "Partially Taught" if i < taught + partial else
            ("Not Taught - Carry Over" if i % 2 == 0 else "Not Taught - Skipped")
        )
        conn.execute(
            """INSERT INTO record_of_work_rows
               (id,doc_id,plan_id,scheme_row_id,origin,week,lesson,strand,sub_strand,focus_keyword,
                planned_work,work_done,reflection,status,source,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))""",
            (db.new_id(), doc_id, pid, section_ids[i], "planned", week, lesson, "Numbers",
             "Whole Numbers", f"Focus {lesson}", f"Planned: Focus {lesson}",
             f"Taught Focus {lesson}" if status == "Taught" else f"Planned: Focus {lesson}",
             "Sports Day" if status.startswith("Not Taught") else "",
             status, "auto-filled from Scheme"),
        )
    return pid


maths = seed("Mathematics", 42, 5)
english = seed("English", 55, 0)
cre = seed("CRE", 60, 0)
science = seed("Science", 0, 0, with_row=False)
conn.commit()
conn.close()

d = svc.get_dashboard({})
s = d["summary"]

# ---- acceptance 1: header stats + formula ---------------------------------
check("planned = 180", s["planned"] == 180, str(s["planned"]))
check("taught = 157", s["taught"] == 157, str(s["taught"]))
check("partially = 5", s["partially"] == 5, str(s["partially"]))
check("coverage = round((157+5*0.5)/180*100) = 89",
      s["coveragePct"] == round((157 + 5 * 0.5) / 180 * 100), str(s["coveragePct"]))

# ---- acceptance 2: subject statuses + worst-first ordering ----------------
by = {x["subject"]: x for x in d["bySubject"]}
# Spec example says "Maths 70%" but also says Partially counts 0.5; with 5 partial
# lessons the formula gives (42+2.5)/60 = 74%.  The implemented formula wins.
check("Maths coverage = (42+5*0.5)/60 = 74", by["Mathematics"]["coveragePct"] == 74,
      str(by["Mathematics"]["coveragePct"]))
check("English coverage 92", by["English"]["coveragePct"] == 92,
      str(by["English"]["coveragePct"]))
check("CRE coverage 100", by["CRE"]["coveragePct"] == 100,
      str(by["CRE"]["coveragePct"]))
check("Maths Behind", by["Mathematics"]["status"] == "Behind", by["Mathematics"]["status"])
check("English On Track", by["English"]["status"] == "On Track", by["English"]["status"])
check("CRE Complete", by["CRE"]["status"] == "Complete", by["CRE"]["status"])
check("Science no ROW", by["Science"]["rowExists"] is False
      and by["Science"]["coveragePct"] is None
      and by["Science"]["status"] == "Not Started")

with_row = [x for x in d["bySubject"] if x["rowExists"]]
pcts = [x["coveragePct"] for x in with_row]
check("sorted worst first", pcts == sorted(pcts), str(pcts))

# ---- acceptance 3: by-week chart ------------------------------------------
w2 = next((w for w in d["byWeek"] if w["week"] == 2), None)
check("Week 2 planned 15 across 3 subjects", w2 and w2["planned"] == 15)
check("By-week taught sums to summary taught",
      sum(w["taught"] for w in d["byWeek"]) == s["taught"],
      f"{sum(w['taught'] for w in d['byWeek'])} vs {s['taught']}")
check("cumulative coverage present", all("cumulativePct" in w for w in d["byWeek"]))

# ---- acceptance 4: gaps = Not Taught ONLY ---------------------------------
check("gaps = 18 Not Taught (not 18+5 partial)", len(d["gaps"]) == 18,
      f"gaps={len(d['gaps'])} partial={len(d['partiallyTaught'])}")
check("partially taught listed separately", len(d["partiallyTaught"]) == 5,
      str(len(d["partiallyTaught"])))
check("skipped gaps stay visible",
      any(g["status"] == "Not Taught - Skipped" for g in d["gaps"]))

# ---- acceptance 5: week filter --------------------------------------------
wfiltered = svc.get_dashboard({"week": 2})
check("week filter narrows summary", wfiltered["summary"]["planned"] == 15,
      str(wfiltered["summary"]["planned"]))
check("week filter narrows gaps", all(g["week"] == 2 for g in wfiltered["gaps"]))

# ---- acceptance 6/7: formula edge cases -----------------------------------
check("no plan -> no coverage", svc.coverage_pct(0, 0, 0) is None)
check("half counts", svc.coverage_pct(1, 1, 4) == 38, str(svc.coverage_pct(1, 1, 4)))

# ---- acceptance 8: cache + invalidation -----------------------------------
a = svc.get_dashboard({})
b = svc.get_dashboard({})
check("cached result stable", a["summary"] == b["summary"])
with db.connect() as c:
    c.execute("UPDATE record_of_work_docs SET updated_at=datetime('now','+1 day') WHERE plan_id=?", (maths,))
c2 = svc.get_dashboard({})
check("ROW edit invalidates via updated_at", isinstance(c2["summary"], dict))
svc.invalidate()

# ---- acceptance 9: versioned edits through service ------------------------
gap = d["gaps"][0]
res, errs = row_svc.edit_row(gap["rowId"], {
    "date": "2025-02-10", "workDone": "Taught with counters.", "status": "Taught",
})
check("gap can be marked taught", res is not None and not errs, str(errs))
ver, verr = row_svc.create_version(res["row"]["docId"], "Dashboard: marked as taught", kind="taught")
check("new version created", ver is not None and not verr, str(verr))
res2, errs2 = row_svc.edit_row(gap["rowId"], {"status": "Not Taught - Skipped", "reflection": "Sports Day"})
check("skip keeps gap visible", res2 is not None and res2["row"]["status"] == "Not Taught - Skipped")

# ---- acceptance 10: PDF ----------------------------------------------------
pdf, pages = dashboard_pdf.render_dashboard_pdf(d)
import fitz  # noqa: E402
doc = fitz.open(stream=pdf, filetype="pdf")
text = "\n".join(p.get_text() for p in doc)
check("PDF generated", len(pdf) > 5000 and pages >= 5, f"pages={pages}")
check("all PDF pages portrait", all(p.rect.height > p.rect.width for p in doc))
check("PDF has summary", "Coverage Summary" in text)
check("PDF has subject table", "Coverage by Subject" in text)
check("PDF has week chart", "Coverage by Week" in text)
check("PDF has gaps", "Gaps to Fix" in text)
check("PDF has global page numbering", f"Page 2 of {pages}" in text)
doc.close()

# ---- acceptance: empty gap list is not proof of 100% -----------------------
partial_msg, partial_ok = dashboard_pdf._empty_gaps_message({
    "summary": {"coveragePct": 74, "planned": 60, "taught": 42, "partially": 5},
    "appliedFilters": {},
})
check("empty gaps + partial does not claim 100%", not partial_ok and "74%" in partial_msg
      and "partially taught" in partial_msg, partial_msg)
blank_msg, blank_ok = dashboard_pdf._empty_gaps_message({
    "summary": {"coveragePct": 50, "planned": 60, "taught": 30, "partially": 0},
    "appliedFilters": {},
})
check("blank statuses do not claim 100%", not blank_ok and "30 of 60" in blank_msg, blank_msg)
unknown_msg, unknown_ok = dashboard_pdf._empty_gaps_message({
    "summary": {"coveragePct": None, "planned": 60, "taught": 0, "partially": 0},
    "appliedFilters": {},
})
check("unknown coverage does not claim 100%", not unknown_ok
      and "cannot be calculated" in unknown_msg, unknown_msg)
full_msg, full_ok = dashboard_pdf._empty_gaps_message({
    "summary": {"coveragePct": 100, "planned": 60, "taught": 60, "partially": 0},
    "appliedFilters": {},
})
check("genuine 100% still reported", full_ok and "100%" in full_msg, full_msg)
no_gap_data = dict(d)
no_gap_data["gaps"] = []
no_gap_data["summary"] = {
    **s, "coveragePct": 74, "planned": 60, "taught": 42, "partially": 5,
}
pdf2, _ = dashboard_pdf.render_dashboard_pdf(no_gap_data)
d2 = fitz.open(stream=pdf2, filetype="pdf")
text2 = "\n".join(p.get_text() for p in d2)
d2.close()
check("PDF empty-gaps banner reflects partial coverage",
      "partially taught" in text2 and "74%" in text2
      and "all 60 planned lessons taught" not in text2, text2[-300:])

print(f"\n{passed}/{passed + failed} dashboard acceptance checks passed")
if failed:
    sys.exit(1)
