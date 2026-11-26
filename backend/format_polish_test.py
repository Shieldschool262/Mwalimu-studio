"""Format-polish regression checks (Scheme + Lesson Plan rendering only).

Run: python backend/format_polish_test.py
Uses a throwaway backup of studio.db; never writes content or versions.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
DB = "C:/tmp/mwalimu_format_regression.db"
os.environ["MWALIMU_STUDIO_DB"] = DB

src = ROOT / "studio.db"
for ext in ("", "-wal", "-shm"):
    p = Path(DB + ext)
    if p.exists():
        p.unlink()
s = sqlite3.connect(str(src))
d = sqlite3.connect(DB)
s.backup(d)
d.close()
s.close()

import fitz  # noqa: E402
from services import plan_service, scheme_pdf, lesson_pdf, lesson_plan_service  # noqa: E402
from services.weekly_split import split_kiqs  # noqa: E402
import auth_service as _auth  # noqa: E402

# Direct service calls in this regression script have no HTTP token.
_auth.set_owner("format-regression")

passed = failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS: {name} {detail}")
    else:
        failed += 1
        print(f"FAIL: {name} {detail}")


# 1. KIQ distributor repeats full text; no cross-reference placeholders.
split = split_kiqs(["What objects are found at home?", "How can we group them?"], 5)
check("KIQ repeated in full on all weeks",
      len(split) == 5 and all(x == ["What objects are found at home? How can we group them?"] for x in split))
check("single KIQ also repeated",
      all(x == ["Only question?"] for x in split_kiqs(["Only question?"], 4)))

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
plan_ids = [r[0] for r in conn.execute("SELECT id FROM plan_documents WHERE type='scheme'")]
conn.close()

plan = None
for pid in plan_ids:
    candidate = plan_service.get_plan(pid)
    if candidate and candidate.get("sections"):
        plan = candidate
        break
check("scheme loaded", plan is not None)

if plan:
    rendered = "\n".join(
        str(x) for sec in plan["sections"] for key in ("kiqs", "outcomes", "experiences")
        for x in sec.get(key, [])
    )
    check("no cross-reference text in rendered scheme",
          not any(x in rendered.lower() for x in ("see week", "see above", "— do —")))
    # Force a 3+ page PDF from the same content (formatting only).
    long_plan = dict(plan)
    long_plan["sections"] = [
        dict(sec, id=f"{sec['id']}-{i}", ord=i) for i in range(8) for sec in plan["sections"]
    ]
    pdf = scheme_pdf.render_scheme_pdf(long_plan)
    d = fitz.open(stream=pdf, filetype="pdf")
    check("scheme PDF has 3+ pages", d.page_count >= 3, str(d.page_count))
    headers = ["Week", "Lesson", "Strand / Sub-Strand", "Specific Learning Outcomes",
               "Learning Experiences", "Key Inquiry Questions", "Learning Resources",
               "Assessment", "Reflection"]
    per_page = []
    for p in d:
        flat = " ".join(p.get_text().split())
        per_page.append(all(h in flat for h in headers))
    check("9 headers repeated on EVERY scheme page", all(per_page), str(per_page))
    d.close()
    check("scheme PDF has no cross-reference text",
          not any(x in str(pdf) for x in ("See Week", "see above", "— do —")))

# 2. Lesson PDF admin table + unnumbered stages.
conn = sqlite3.connect(DB)
row = conn.execute("SELECT id FROM lesson_plans LIMIT 1").fetchone()
conn.close()
if row:
    lp = lesson_plan_service.get_lesson_plan(row[0])
    pdf = lesson_pdf.render_lesson_pdf(lp)
    d = fitz.open(stream=pdf, filetype="pdf")
    text = "\n".join(p.get_text() for p in d)
    check("lesson PDF portrait", all(p.rect.height > p.rect.width for p in d))
    for label in ("School:", "Learning Area:", "Grade:", "Term:", "Year:", "Week:",
                  "Lesson", "Date:", "Time:", "Strand:", "Sub-Strand:", "Focus:",
                  "Teacher:", "TSC No.:"):
        check(f"admin label {label}", label in text)
    check("empty values show handwriting line", "________" in text)
    for stage in ("Introduction (5 min)", "Development (", "Conclusion (5 min)"):
        check(f"stage heading {stage}", stage in text)
    for bad in ("1. Introduction", "2. Development", "3. Conclusion",
                "1. Administrative Details", "1. Lesson Development", "11. Assessment"):
        check(f"no numbered heading: {bad}", bad not in text)
    d.close()

# 2b. Administrative Details belong only on the page where the lesson starts.
# Build a long synthetic lesson so the renderer must create continuation pages.
long_plan = {
    "templateVersion": "cbe-lesson-primary-v1",
    "duration": 35,
    "lesson": 1,
    "lessonCount": 5,
    "week": 3,
    "focus": "Sort objects by colour, size and shape",
    "header": {
        "school": "Test Primary School", "learningArea": "Mathematics",
        "grade": "Grade 1", "term": "Term 1", "year": "2026", "week": "3",
        "lesson": "1", "lessonCount": "5", "date": "12/03/2026",
        "time": "08:00", "duration": 35, "durationType": "Single",
        "strand": "Numbers", "subStrand": "Sorting and grouping",
        "focus": "Sort objects by colour, size and shape",
        "teacherName": "Mary Wanjiku", "tscNo": "123456",
        "classSize": "42", "rollBoys": "20", "rollGirls": "22", "rollTotal": "42",
    },
    "versions": [{"label": "v1.0"}],
    "sections": [
        {"key": "strand", "title": "2. Strand", "body": "Numbers", "data": {}},
        {"key": "subStrand", "title": "3. Sub-Strand", "body": "Sorting and grouping", "data": {}},
        {"key": "outcomes", "title": "4. Specific Learning Outcomes",
         "body": "By the end of the lesson, the learner should be able to sort objects by colour.", "data": {}},
        {"key": "kiq", "title": "5. Key Inquiry Question(s)",
         "body": "How can we group objects that are alike?", "data": {}},
        {"key": "step1", "title": "10. Lesson Development - Step 1", "body": "",
         "data": {
             "time": "25 min",
             "teacherActivity": "Guide learners to sort objects into groups. " * 80,
             "learnerActivity": "Learners sort the objects in pairs. " * 80,
         }},
    ],
    "assessment": {"planned": "Observe each group as they sort."},
    "createdAt": "2026-03-01T00:00:00",
}
ldoc = fitz.open(stream=lesson_pdf.render_lesson_pdf(long_plan), filetype="pdf")
check("long lesson spans 2+ pages", ldoc.page_count >= 2, str(ldoc.page_count))
admin_labels = (
    "School:", "Learning Area:", "Grade:", "Term:", "Year:", "Week:", "Date:",
    "Time:", "Duration:", "Strand:", "Sub-Strand:", "Focus:", "Teacher:",
    "TSC No.:", "Class Size:", "Roll B/G/T:",
)
page1 = ldoc[0].get_text()
check("page 1 has administrative details", all(x in page1 for x in admin_labels))
for i in range(1, ldoc.page_count):
    continuation = ldoc[i].get_text()
    found = [x for x in admin_labels if x in continuation]
    check(f"page {i + 1} has no administrative details", not found, str(found))
    check(f"page {i + 1} keeps a slim LESSON PLAN header",
          "LESSON PLAN" in continuation and "Lesson continued" in continuation)
ldoc.close()

print(f"\n{passed}/{passed + failed} format checks passed")
if failed:
    sys.exit(1)
