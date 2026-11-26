"""Strict acceptance tests - Phase 3 CORRECTED weekly-row rules.

Asserts the exact acceptance criteria from the corrected spec:
  * ONE WEEK = ONE ROW (single integer weeks, lessons restart each week)
  * SPLIT outcomes/experiences/KIQs across weekly rows (never repeated)
  * Nothing merged, no "1-4" / "6-10" anywhere
  * Teacher override: one row's edit never leaks to sibling rows
  * [Re-balance Outcomes] re-runs the split after edits
  * lessons=null -> 1 row, week = next available, lesson = 1-4, flag
  * PDF: 10 columns, landscape, one row per week, no merged week cells
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

os.environ["MWALIMU_STUDIO_DB"] = str(BACKEND / "studio_p3acc_test.db")
os.environ["MWALIMU_STUDIO_UPLOADS"] = str(BACKEND / "_test_uploads_p3acc")

for stale in (BACKEND / "studio_p3acc_test.db",):
    if stale.exists():
        stale.unlink()

from db import connect, init_db, new_id  # noqa: E402
from services.library_service import (  # noqa: E402
    VETTED,
    get_library_document,
)
from services.parse_service import (  # noqa: E402
    approve_all,
    correct_chunk,
    parse_and_store,
)
from services.plan_service import (  # noqa: E402
    create_plan,
    edit_section,
    load_template,
    rebalance_group,
)
from services.scheme_pdf import render_scheme_pdf  # noqa: E402

CD = Path(r"C:\Users\user\Desktop\Curriculum Designs")
MATHS = CD / "Grade-1-Mathematics-Activities-Curriculum-Design.pdf"

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {msg}")
    if not cond:
        failures.append(msg)


def vet_all(mid: str) -> dict:
    approve_all(mid, 0.9)
    for _ in range(8):
        d = get_library_document(mid)
        pending = [
            c for c in d["chunks"]
            if c["reviewState"] not in ("Approved", "TeacherCorrected")
        ]
        if not pending:
            return d
        for c in pending:
            correct_chunk(mid, c["id"], {"reviewState": "Approved"})
    return get_library_document(mid)


def main() -> int:
    init_db()

    print("\n== A. Template: 10 KICD columns in order, landscape ==")
    tpl = load_template("cbe-scheme-v1")
    check(
        [c["key"] for c in tpl["columns"]]
        == [
            "week", "lesson", "strand", "subStrand", "outcomes",
            "experiences", "kiqs", "resources", "assessment", "reflection",
        ],
        "10 KICD columns in order",
    )
    check(tpl.get("landscape") is True, "template is landscape")

    print("\n== B. Upload + vet Maths ==")
    maths = parse_and_store(MATHS.read_bytes(), MATHS.name)
    mid = maths["id"]
    d = vet_all(mid)
    check(all(c["vettingStatus"] == VETTED for c in d["chunks"]), "all chunks Vetted")
    c11 = next(c for c in d["chunks"] if c["subStrandCode"] == "1.1")
    check(c11["lessons"] == 20, f"1.1 lessons = 20 (got {c11['lessons']})")

    print("\n== C. ACCEPTANCE #1: 20 lessons @5/wk -> 4 rows, weeks 1,2,3,4, lesson 1-5 ==")
    plan, errs = create_plan({
        "type": "scheme", "institution": "Nairobi Primary School", "grade": "Grade 1",
        "subject": "Mathematics", "term": "Term 1", "year": "2025",
        "lessonsPerWeek": 5, "totalWeeks": 13, "sourceChunkIds": [c11["id"]],
    })
    check(plan is not None, f"generated ({errs})")
    rows = plan["sections"]
    check(len(rows) == 4, f"4 rows (got {len(rows)})")
    weeks = [r["week"] for r in rows]
    check(weeks == [1, 2, 3, 4], f"weeks single integers 1,2,3,4 (got {weeks})")
    check(
        [r["weekLabel"] for r in rows] == ["1", "2", "3", "4"],
        "weekLabels are single integers",
    )
    check(all("-" not in (r["weekLabel"] or "") for r in rows), "no week ranges")
    check(
        [r["lessonLabel"] for r in rows] == ["1-5", "1-5", "1-5", "1-5"],
        f"lessons reset to 1-5 each week (got {[r['lessonLabel'] for r in rows]})",
    )
    check(all(r["subStrandCode"] == "1.1" for r in rows), "same sub-strand on each row")
    check(all(r["strand"] == c11["strand"] for r in rows), "same strand on each row")

    print("\n== D. ACCEPTANCE #2: outcomes/experiences split, not repeated ==")
    o_sets = [tuple(r["outcomes"]) for r in rows]
    check(len(set(o_sets)) == len(o_sets), f"each week's outcomes distinct ({o_sets})")
    all_o = [o for r in rows for o in r["outcomes"]]
    check(len(all_o) == len(set(all_o)), f"no outcome duplicated across weeks ({all_o})")
    e_sets = [tuple(r["experiences"]) for r in rows]
    check(len(set(e_sets)) == len(e_sets), f"each week's experiences distinct ({e_sets})")
    all_e = [e for r in rows for e in r["experiences"]]
    check(len(all_e) == len(set(all_e)), f"no experience duplicated across weeks ({all_e})")
    kiq_counts = [len(r["kiqs"]) for r in rows]
    check(max(kiq_counts) <= 1, f"at most one KIQ per week ({kiq_counts})")
    src_kiqs = c11["structuredFields"]["key_inquiry_questions"]
    if len(src_kiqs) == 1:
        check(rows[0]["kiqs"] == [src_kiqs[0]], "single KIQ on week 1 only")
        check(
            all(r["kiqs"] == ["— See Week 1"] for r in rows[1:]),
            "later rows read '— See Week 1'",
        )
    print(f"        outcomes/wk: {[r['outcomes'] for r in rows]}")
    print(f"        experiences/wk: {[r['experiences'] for r in rows]}")
    print(f"        kiqs/wk: {[r['kiqs'] for r in rows]}")

    print("\n== E. ACCEPTANCE #3: lessons=null -> 1 row, week 1, lesson 1-4, flag ==")
    with connect() as conn:
        doc_id = new_id()
        conn.execute(
            """INSERT INTO source_documents
               (id, file_name, grade, subject, archetype, parser_version, status, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (doc_id, "english.pdf", "Grade 1", "English", "print", "test", "Approved",
             "2025-01-01"),
        )
        chunk_id = new_id()
        conn.execute(
            """INSERT INTO source_chunks
               (id, document_id, ord, page_number, strand, strand_code, sub_strand,
                sub_strand_code, lessons, structured_fields, review_state, created_at,
                vetting_status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                chunk_id, doc_id, 0, 10, "Listening and Speaking", "1.0", "Greetings",
                "1.1", None,
                json.dumps({
                    "specific_learning_outcomes": ["o1"],
                    "suggested_learning_experiences": ["e1"],
                    "key_inquiry_questions": ["q1"],
                }, ensure_ascii=False),
                "Approved", "2025-01-01", VETTED,
            ),
        )
    eplan, errs2 = create_plan({
        "type": "scheme", "institution": "Nairobi Primary School", "grade": "Grade 1",
        "subject": "English", "term": "Term 1", "year": "2025",
        "lessonsPerWeek": 5, "totalWeeks": 13, "sourceChunkIds": [chunk_id],
    })
    check(eplan is not None, f"English generated ({errs2})")
    erows = eplan["sections"]
    check(len(erows) == 1, f"1 row for lessons=null (got {len(erows)})")
    check(erows[0]["week"] == 1, f"week = next available 1 (got {erows[0]['week']})")
    check(
        erows[0]["lessonLabel"] == "1-4",
        f"lesson default 1-4 (got {erows[0]['lessonLabel']})",
    )
    check(
        any("Lessons not in source - assumed 4" in f for f in erows[0]["flags"]),
        f"flag set ({erows[0]['flags']})",
    )

    print("\n== F. ACCEPTANCE #4: edit Week 2 outcomes, Weeks 1 & 3 unchanged ==")
    r1, r2, r3 = rows[0], rows[1], rows[2]
    edited, errs3 = edit_section(
        plan["id"], r2["id"], {"outcomes": ["Teacher wrote this by hand"]}
    )
    check(edited is not None, f"edit saved ({errs3})")
    by_id = {s["id"]: s for s in edited["sections"]}
    check(
        by_id[r2["id"]]["outcomes"] == ["Teacher wrote this by hand"],
        "row 2 outcomes edited",
    )
    check(by_id[r2["id"]]["edited"] is True, "row 2 marked Teacher Edited")
    check(by_id[r1["id"]]["outcomes"] == rows[0]["outcomes"], "row 1 unchanged")
    check(by_id[r3["id"]]["outcomes"] == rows[2]["outcomes"], "row 3 unchanged")
    check(by_id[r1["id"]]["edited"] is False, "row 1 NOT marked edited")

    print("\n== G. ACCEPTANCE #5: [Re-balance] re-splits and resets edited ==")
    bal, errs4 = rebalance_group(plan["id"], "1.1", 5)
    check(bal is not None, f"rebalance ran ({errs4})")
    g_rows = [s for s in bal["sections"] if s["subStrandCode"] == "1.1"]
    check(len(g_rows) == 4, f"still 4 rows (got {len(g_rows)})")
    check(
        g_rows[1]["outcomes"] != ["Teacher wrote this by hand"],
        "teacher edit replaced by fresh split",
    )
    check(all(s["edited"] is False for s in g_rows), "rebalanced rows reset to not-edited")
    all_g = [o for s in g_rows for o in s["outcomes"]]
    check(len(all_g) == len(set(all_g)), f"no duplicates after rebalance ({all_g})")
    check(
        [s["lessonLabel"] for s in g_rows] == ["1-5", "1-5", "1-5", "1-5"],
        "lessons still 1-5 on every row after rebalance",
    )

    print("\n== G2. Re-balance at the SAME pace keeps per-row teacher edits ==")
    edit_section(plan["id"], g_rows[2]["id"], {"reflection": "Week 3 went well."})
    same, errs5 = rebalance_group(plan["id"], "1.1", 5)
    check(same is not None, f"rebalance at same pace ran ({errs5})")
    s_rows = [s for s in same["sections"] if s["subStrandCode"] == "1.1"]
    check(len(s_rows) == 4, f"still 4 rows (got {len(s_rows)})")
    check(
        s_rows[2]["reflection"]["text"] == "Week 3 went well.",
        "row 3 reflection survives a same-pace rebalance",
    )
    check(
        [s["week"] for s in s_rows] == [1, 2, 3, 4],
        f"weeks unchanged at same pace ({[s['week'] for s in s_rows]})",
    )

    print("\n== G3. Re-balance at a CHANGED pace re-splits weeks, clears reflection ==")
    fast, errs6 = rebalance_group(plan["id"], "1.1", 10)
    check(fast is not None, f"rebalance at 10/wk ran ({errs6})")
    f_rows = [s for s in fast["sections"] if s["subStrandCode"] == "1.1"]
    check(len(f_rows) == 2, f"20 lessons @10/wk -> 2 rows (got {len(f_rows)})")
    check(
        [s["lessonLabel"] for s in f_rows] == ["1-10", "1-10"],
        f"lesson range widens to 1-10 ({[s['lessonLabel'] for s in f_rows]})",
    )
    check(
        [s["week"] for s in f_rows] == [1, 2],
        f"weeks renumber from the first row ({[s['week'] for s in f_rows]})",
    )
    check(
        all(s["reflection"]["text"] == "" for s in f_rows),
        "reflection empty on every rebuilt row (RULE 3)",
    )
    f_all_o = [o for s in f_rows for o in s["outcomes"]]
    check(len(f_all_o) == len(set(f_all_o)), f"outcomes re-split without duplicates ({f_all_o})")

    # Restore the 5/week view for the PDF checks.
    restored, _ = rebalance_group(plan["id"], "1.1", 5)
    g_rows = [s for s in restored["sections"] if s["subStrandCode"] == "1.1"]

    print("\n== H. ACCEPTANCE #6: PDF landscape, one row per week, no merged weeks ==")
    import fitz

    pdf = render_scheme_pdf(restored)
    doc = fitz.open(stream=pdf, filetype="pdf")
    check(doc.page_count >= 1, f"pdf pages ({doc.page_count})")
    p0 = doc[0]
    w, h = p0.rect.width, p0.rect.height
    check(w > h, f"landscape ({w:.0f}x{h:.0f})")
    txt = "".join(p.get_text() for p in doc)
    check("Key Inquiry Question" in txt, "column headers present")
    check("Part 1 of 4" in txt, "part label rendered")
    check("6-10" not in txt, "no merged lesson ranges in PDF")
    check("Week 1-4" not in txt, "no merged week ranges in PDF")
    check(all(s["weekLabel"] in txt for s in g_rows), "each week number printed")
    doc.close()

    print("\n" + "=" * 62)
    if failures:
        print(f"RESULT: {len(failures)} FAILURE(S)")
        for f in failures:
            print("  -", f)
        return 1
    print("RESULT: ALL PHASE 3 CORRECTED ACCEPTANCE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
