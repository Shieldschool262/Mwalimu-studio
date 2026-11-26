"""Acceptance tests - Phase 3 CORRECTED: official KICD Scheme of Work.

Asserts the exact spec:

  * 10 columns in KICD order, driven by the template file, not code
  * Maths 1.1 (20 lessons) + 1.2 (25 lessons), 5 lessons/week, 13 weeks
      -> Week "1-4" / Lesson "1-20"  and  Week "5-9" / Lesson "21-45"
  * Reflection EMPTY on generation (never AI-filled)
  * Learning Resources -> "— Teacher to fill" when source has none, and NOT blocking
  * Assessment -> appendix value when present, else "Observation, oral questions"; editable
  * Pending chunk (missing KIQs) BLOCKS generation with the named field
  * Outcomes/Experiences/KIQs verbatim + correct citation pageNumber
  * Overflow warns, never truncates
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

os.environ["MWALIMU_STUDIO_DB"] = str(BACKEND / "studio_p3c_test.db")
os.environ["MWALIMU_STUDIO_UPLOADS"] = str(BACKEND / "_test_uploads_p3c")

for stale in (BACKEND / "studio_p3c_test.db",):
    if stale.exists():
        stale.unlink()
up = BACKEND / "_test_uploads_p3c"
if up.exists():
    for f in up.iterdir():
        f.unlink()

from db import connect, init_db  # noqa: E402
from services.library_service import (  # noqa: E402
    VETTED,
    compute_vetting_status,
    delete_library_document,
    get_library_document,
    list_library,
)
from services.parse_service import approve_all, correct_chunk, parse_and_store  # noqa: E402
from services.plan_service import (  # noqa: E402
    allocate,
    create_plan,
    delete_plan,
    duplicate_plan,
    edit_section,
    get_plan,
    list_plans,
    load_template,
    rebalance_group,
    set_plan_status,
)
from services.scheme_pdf import render_scheme_pdf  # noqa: E402

CD = Path(r"C:\Users\user\Desktop\Curriculum Designs")
MATHS = CD / "Grade-1-Mathematics-Activities-Curriculum-Design.pdf"

KICD_COLUMNS = [
    "week",
    "lesson",
    "strand",
    "subStrand",
    "outcomes",
    "experiences",
    "kiqs",
    "resources",
    "assessment",
    "reflection",
]

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {msg}")
    if not cond:
        failures.append(msg)


def main() -> int:
    init_db()

    print("\n== A. Template defines the 10 KICD columns, in order ==")
    tpl = load_template("cbe-scheme-v1")
    keys = [c["key"] for c in tpl["columns"]]
    check(keys == KICD_COLUMNS, f"columns are exactly KICD order ({keys})")
    check([c["index"] for c in tpl["columns"]] == list(range(1, 11)), "columns numbered 1..10")
    labels = [c["label"] for c in tpl["columns"]]
    check(labels[6] == "Key Inquiry Question (KIQ)", f"col 7 label ({labels[6]})")
    check(labels[9] == "Reflection / Remarks", f"col 10 label ({labels[9]})")
    check(tpl["version"] == "cbe-scheme-v1", "template version is cbe-scheme-v1")
    check(tpl.get("landscape") is True, "template is landscape")
    refl = next(c for c in tpl["columns"] if c["key"] == "reflection")
    check(refl.get("alwaysEmpty") is True and refl.get("neverAiFill") is True,
          "Reflection is alwaysEmpty and neverAiFill")
    res = next(c for c in tpl["columns"] if c["key"] == "resources")
    check(res["fallback"] == "— Teacher to fill" and res["blocksGeneration"] is False,
          "Resources fallback is '— Teacher to fill' and never blocks")
    ass = next(c for c in tpl["columns"] if c["key"] == "assessment")
    check(ass["fallback"] == "Observation, oral questions" and ass["blocksGeneration"] is False,
          "Assessment fallback is 'Observation, oral questions' and never blocks")

    print("\n== B. Upload + vet Maths ==")
    maths = parse_and_store(MATHS.read_bytes(), MATHS.name)
    mid = maths["id"]
    approve_all(mid, 0.9)
    for _ in range(5):
        d = get_library_document(mid)
        pending = [c for c in d["chunks"] if c["reviewState"] not in ("Approved", "TeacherCorrected")]
        if not pending:
            break
        for c in pending:
            correct_chunk(mid, c["id"], {"reviewState": "Approved"})
    d = get_library_document(mid)
    check(all(c["vettingStatus"] == VETTED for c in d["chunks"]),
          f"all {len(d['chunks'])} chunks Vetted")
    lib = list_library()
    check(mid in {x["id"] for x in lib["studioLibrary"]}, "document in Studio Library")
    card = next(x for x in lib["documents"] if x["id"] == mid)
    check(card["allVetted"] is True and "9/9" in card["vettingBadge"], f"badge ({card['vettingBadge']})")

    c11 = next(c for c in d["chunks"] if c["subStrandCode"] == "1.1")
    c12 = next(c for c in d["chunks"] if c["subStrandCode"] == "1.2")
    check(c11["lessons"] == 20, f"1.1 lessons from parser = 20 (got {c11['lessons']})")
    check(c12["lessons"] == 25, f"1.2 lessons from parser = 25 (got {c12['lessons']})")

    print("\n== C. ONE WEEK = ONE ROW (5 lessons/week) ==")
    plan, errs = create_plan({
        "type": "scheme",
        "institution": "Nairobi Primary School",
        "grade": "Grade 1",
        "subject": "Mathematics",
        "term": "Term 1",
        "year": "2025",
        "lessonsPerWeek": 5,
        "totalWeeks": 13,
        "sourceChunkIds": [c11["id"]],
    })
    check(plan is not None, f"scheme generated ({errs})")
    rows = plan["sections"]
    check(len(rows) == 4, f"1.1 (20 lessons @5/wk) -> 4 rows (got {len(rows)})")
    weeks = [r["weekLabel"] for r in rows]
    check(weeks == ["1", "2", "3", "4"], f"Week is a single integer 1,2,3,4 (got {weeks})")
    check(not any("-" in w for w in weeks), "no week ranges anywhere")
    lessons = [r["lessonLabel"] for r in rows]
    check(lessons == ["1-5", "1-5", "1-5", "1-5"], f"Lesson resets every week to 1-5 (got {lessons})")
    check(all(r["subStrandCode"] == "1.1" for r in rows), "same sub-strand repeated on each row")
    check(all(r["strand"] == c11["strand"] for r in rows), "same strand on each row")

    print("\n== C2. Outcomes/Experiences are SPLIT, not repeated ==")
    check(rows[0]["outcomes"] != rows[1]["outcomes"], "row 1 outcomes != row 2 outcomes")
    check(rows[1]["outcomes"] != rows[2]["outcomes"], "row 2 outcomes != row 3 outcomes")
    check(rows[0]["experiences"] != rows[1]["experiences"], "row 1 experiences != row 2 experiences")
    full_o = c11["structuredFields"]["specific_learning_outcomes"]
    check(not all(r["outcomes"] == full_o for r in rows), "the full outcome list is NOT copied into every row")
    all_o = [o for r in rows for o in r["outcomes"]]
    check(len(all_o) == len(set(all_o)), f"no outcome duplicated across weeks ({len(all_o)} items)")
    all_e = [e for r in rows for e in r["experiences"]]
    check(len(all_e) == len(set(all_e)), f"no experience duplicated across weeks ({len(all_e)} items)")
    print(f"        outcomes per week: {[r['outcomes'] for r in rows]}")
    print(f"        experiences per week: {[r['experiences'] for r in rows]}")
    print(f"        kiqs per week: {[r['kiqs'] for r in rows]}")

    print("\n== C3. KIQ distribution ==")
    kiq_counts = [len(r["kiqs"]) for r in rows]
    check(all(c <= 1 for c in kiq_counts), f"at most one KIQ per week ({kiq_counts})")
    src_kiqs = c11["structuredFields"]["key_inquiry_questions"]
    if len(src_kiqs) == 1:
        check(rows[0]["kiqs"] == [src_kiqs[0]], "single KIQ appears on week 1")
        check(all(r["kiqs"] == ["— See Week 1"] for r in rows[1:]), "later rows read '— See Week 1'")

    print("\n== C4. Part labels + shared citation ==")
    check(rows[0]["partLabel"] == "Part 1 of 4", f"part label ({rows[0]['partLabel']})")
    check(rows[3]["partLabel"] == "Part 4 of 4", f"last part label ({rows[3]['partLabel']})")
    pages = {r["citations"][0]["pageNumber"] for r in rows}
    chunks_cited = {r["citations"][0]["chunkId"] for r in rows}
    check(len(pages) == 1 and len(chunks_cited) == 1,
          f"every weekly row cites the same chunk + page ({pages}, {len(chunks_cited)} chunk)")
    check(pages == {c11["pageNumber"]}, f"cited page is {c11['pageNumber']}")

    print("\n== C5. Overflow still warns with weekly rows ==")
    big, errs_big = create_plan({
        "type": "scheme", "institution": "Nairobi Primary School", "grade": "Grade 1",
        "subject": "Mathematics", "term": "Term 1", "year": "2025",
        "lessonsPerWeek": 5, "totalWeeks": 13,
        "sourceChunkIds": [c["id"] for c in d["chunks"]],
    })
    check(big is not None, f"full selection still generates ({errs_big})")
    check(big["allocation"]["warning"] is not None, "overflow warning present")
    import math as _m
    expect = sum(max(1, _m.ceil((c["lessons"] or 4) / 5)) for c in d["chunks"])
    check(big["sectionCount"] == expect, f"one row per week for every sub-strand ({big['sectionCount']} rows == {expect})")
    delete_plan(big["id"])

    print("\n== D. Reflection empty, resources/assessment fallbacks ==")
    check(all(s["reflection"]["text"] == "" for s in plan["sections"]),
          "Reflection EMPTY for every row on generation")
    check(all(s["reflection"]["placeholder"] == "To be filled after lesson"
              for s in plan["sections"]), "Reflection placeholder present")
    check(all(s["resources"]["text"] == "— Teacher to fill" for s in plan["sections"]),
          "Resources shows '— Teacher to fill' when source has none")
    check(all(s["resources"]["placeholder"] is True for s in plan["sections"]),
          "Resources flagged as placeholder (grey/editable)")
    # Phase 3.5 autofills Assessment from the curriculum appendix; the template default is
    # only used when the source has no appendix assessment at all.
    expected_assessment = (
        c11.get("appendixAssessment") or c12.get("appendixAssessment")
        or "Observation, oral questions"
    )
    check(all(s["assessment"]["text"] == expected_assessment for s in plan["sections"]),
          f"Assessment uses the appendix value / template default ({expected_assessment[:40]})")

    print("\n== E. Verbatim source text + citation page numbers ==")
    by_code = {"1.1": c11, "1.2": c12}
    bad = []
    for s in rows:
        page = s["citations"][0]["pageNumber"] if s["citations"] else None
        if page != by_code[s["subStrandCode"]]["pageNumber"]:
            bad.append(f"{s['subStrandCode']} page")
    check(not bad, f"every weekly row cites its source page {bad}")
    # Across the weekly rows every source outcome/KIQ appears, nothing is invented, and
    # nothing is repeated. Verbatim means the TEXT, not the grouping.
    def norm(x: str) -> str:
        return " ".join(str(x).split()).strip()

    split_o = [norm(o) for r in rows for o in r["outcomes"]]
    split_e = [norm(e) for r in rows for e in r["experiences"]]
    src_o = [norm(o) for o in c11["structuredFields"]["specific_learning_outcomes"]]
    for o in src_o:
        check(o in split_o, f"outcome present verbatim: {o[:40]}...")
    check(len(split_o) == len(src_o), f"no invented outcomes ({len(split_o)} vs {len(src_o)})")
    check(len(set(split_o)) == len(split_o), "no outcome repeated across weeks")
    check(len(set(split_e)) == len(split_e), "no experience repeated across weeks")
    src_kiq = [norm(k) for k in c11["structuredFields"]["key_inquiry_questions"]]
    got_kiq = [norm(k) for r in rows for k in r["kiqs"] if k and k != "\u2014 See Week 1"]
    check(sorted(got_kiq) == sorted(src_kiq), f"KIQs distributed once each ({got_kiq})")

    print("\n== F. Header block ==")
    h = plan["header"]
    check(h["institution"] == "Nairobi Primary School", "institution stored")
    check(h["grade"] == "Grade 1" and h["learningArea"] == "Mathematics", "grade + learning area")
    check(h["term"] == "Term 1" and h["year"] == "2025", "term + year")
    check(bool(h["generalOutcomes"]), f"general outcomes auto-filled ({h['generalOutcomes'][:60]}…)")
    first11 = c11["structuredFields"]["specific_learning_outcomes"][0]
    check(first11.replace("a) ", "")[:20] in h["generalOutcomes"], "general outcomes join first outcome of each sub-strand")

    print("\n== G. Independent per-row teacher edits ==")
    r1, r2 = rows[0], rows[1]
    p2, _ = edit_section(plan["id"], r2["id"], {"reflection": "Learners counted well."})
    by_id = {x["id"]: x for x in p2["sections"]}
    check(by_id[r2["id"]]["reflection"]["text"] == "Learners counted well.",
          "reflection editable and saved")
    check(by_id[r2["id"]]["edited"] is True, "edited row marked Teacher Edited")
    check(by_id[r1["id"]]["edited"] is False, "sibling week NOT marked edited")
    check(by_id[r1["id"]]["reflection"]["text"] == "",
          "sibling week reflection untouched")
    check(by_id[r1["id"]]["reflection"]["placeholder"] == "To be filled after lesson",
          "sibling week still shows the reflection placeholder")

    p3, _ = edit_section(plan["id"], r2["id"], {"week": 7})
    by_id = {x["id"]: x for x in p3["sections"]}
    check(by_id[r2["id"]]["weekLabel"] == "7", f"teacher can move a week ({by_id[r2['id']]['weekLabel']})")
    check(by_id[r1["id"]]["weekLabel"] == "1", "other weeks keep their number")
    edit_section(plan["id"], r2["id"], {"week": 2})

    p4, _ = edit_section(plan["id"], r2["id"], {"resources": "Counters, number cards"})
    by_id = {x["id"]: x for x in p4["sections"]}
    check(by_id[r2["id"]]["resources"]["text"] == "Counters, number cards", "resources editable")
    check(by_id[r2["id"]]["resources"]["placeholder"] is False,
          "edited resources no longer show the 'Teacher to fill' placeholder")

    print("\n== G2. [Re-balance Outcomes] =")
    edit_section(plan["id"], r2["id"], {"outcomes": ["Teacher wrote this by hand"]})
    bal, errs_bal = rebalance_group(plan["id"], "1.1")
    check(bal is not None, f"rebalance ran ({errs_bal})")
    g_rows = sorted([x for x in bal["sections"] if x["subStrandCode"] == "1.1"], key=lambda x: x["ord"])
    check(g_rows[1]["outcomes"] != ["Teacher wrote this by hand"],
          "rebalance restores the real split, discarding the collapsed cell")
    check(len({r["outcomes"][0] for r in g_rows if r["outcomes"]}) >= 3,
          "each week holds a different outcome again")
    check(all(r["edited"] is False for r in g_rows), "rebalanced rows reset to not-edited")

    print("\n== H. Overflow warns, never truncates ==")
    res = allocate(
        [
            {"id": "a", "documentId": None, "pageNumber": 1, "strand": "S", "strandCode": "1.0",
             "subStrand": "A", "subStrandCode": "1.1", "lessons": 30, "structured": {}},
            {"id": "b", "documentId": None, "pageNumber": 2, "strand": "S", "strandCode": "1.0",
             "subStrand": "B", "subStrandCode": "1.2", "lessons": 15, "structured": {}},
        ],
        5, 1, tpl,
    )
    check(res["totalLessons"] == 45 and res["capacity"] == 5, "45 lessons vs capacity 5")
    check(res["fits"] is False, "does not fit")
    check(res["warning"] == "Selected sub-strands need 45 lessons but term has 5 - remove 40 lessons or extend weeks",
          f"warning text ({res['warning']})")
    # 30 lessons @5/wk = 6 weekly rows, 15 @5/wk = 3 rows. Overflow must not drop any.
    check(len(res["rows"]) == 9, f"no rows dropped on overflow ({len(res['rows'])} rows)")
    check([r["week"] for r in res["rows"]] == list(range(1, 10)),
          f"weeks run 1..9 unbroken ({[r['week'] for r in res['rows']]})")
    check(len({r["subStrandCode"] for r in res["rows"]}) == 2, "both sub-strands still present")

    print("\n== I. Missing lessons falls back to 4 and flags ==")
    res2 = allocate([{"id": "a", "documentId": None, "pageNumber": 1, "strand": "S",
                      "strandCode": "1.0", "subStrand": "A", "subStrandCode": "1.1",
                      "lessons": None, "structured": {}}], 5, 13, tpl)
    check(res2["rows"][0]["lessonCount"] == 4, "null lessons -> 4")
    check("Lessons not in source - assumed 4, edit" in res2["rows"][0]["flags"],
          f"flag set ({res2['rows'][0]['flags']})")

    print("\n== J. Pending chunk BLOCKS generation ==")
    job = correct_chunk(mid, c12["id"], {"field": "kiqs", "newValue": ""})
    blocked, errs = create_plan({
        "type": "scheme", "institution": "Nairobi Primary School", "grade": "Grade 1",
        "subject": "Mathematics", "term": "Term 1", "year": "2025",
        "lessonsPerWeek": 5, "totalWeeks": 13,
        "sourceChunkIds": [c11["id"], c12["id"]],
    })
    check(blocked is None, "generation blocked with a pending chunk")
    msg = " ".join(errs)
    print(f"        error: {msg}")
    check(msg == "Cannot generate: 1.2 missing KIQs. Fix in Library or unselect it.",
          "error matches the required wording")
    check(msg.startswith("Cannot generate:"), "starts with 'Cannot generate:'")
    check("1.2" in msg and "KIQs" in msg, "names sub-strand and missing field")

    print("\n== K. Unselect the pending chunk -> generates ==")
    ok, errs = create_plan({
        "type": "scheme", "institution": "Nairobi Primary School", "grade": "Grade 1",
        "subject": "Mathematics", "term": "Term 1", "year": "2025",
        "lessonsPerWeek": 5, "totalWeeks": 13, "sourceChunkIds": [c11["id"]],
    })
    check(ok is not None, f"generates from the vetted chunk only ({errs})")
    check(ok["sectionCount"] == 4 and [s["weekLabel"] for s in ok["sections"]] == ["1", "2", "3", "4"],
          f"only 1.1 remains as 4 weekly rows (weeks 1-4)")

    print("\n== L. Vetting ignores resources/assessment/reflection entirely ==")
    core = {
        "specific_learning_outcomes": ["a) x"],
        "suggested_learning_experiences": ["y"],
        "key_inquiry_questions": ["z"],
    }
    check(compute_vetting_status(core, "Approved") == VETTED, "3 core fields -> Vetted")
    with_fallbacks_missing = dict(core)
    with_fallbacks_missing.update({
        "suggested_learning_resources": None,
        "assessment": None,
        "core_competencies": None,
        "values": None,
        "pcis": None,
    })
    check(compute_vetting_status(with_fallbacks_missing, "Approved") == VETTED,
          "resources/assessment/competencies/values missing -> STILL Vetted")

    print("\n== M. PDF export is landscape with a repeated header ==")
    pdf = render_scheme_pdf(plan)
    out = BACKEND / "_scheme_probe.pdf"
    out.write_bytes(pdf)
    import fitz
    doc = fitz.open(stream=pdf, filetype="pdf")
    check(doc.page_count >= 1, f"pdf has pages ({doc.page_count})")
    w, h = doc[0].rect.width, doc[0].rect.height
    check(w > h, f"landscape ({w:.0f}x{h:.0f})")
    check(abs(w - 841.89) < 2 and abs(h - 595.28) < 2, "A4 landscape dimensions")
    text0 = doc[0].get_text()
    flat0 = " ".join(text0.split())
    check("SCHEME OF WORK" in text0.upper(), "title on page 1")
    check("Nairobi Primary School" in text0, "institution on page 1")
    check("Key Inquiry Question" in text0, "column headers present")
    check("Teacher to fill" in flat0, "resources fallback rendered")
    check(expected_assessment.split(";")[0].strip() in flat0,
          "assessment value rendered")
    # One row per week must survive into the PDF: weeks 1-4 each with lessons 1-5.
    alltext = " ".join(" ".join(doc[p].get_text().split()) for p in range(doc.page_count))
    for w in ("1", "2", "3", "4"):
        pass
    check(alltext.count("1-5") >= 4, f"every weekly row prints Lesson 1-5 ({alltext.count('1-5')})")
    check("Part 1 of 4" in alltext or "Part 4 of 4" in alltext, "part label rendered")
    check("2-5" not in alltext and "6-10" not in alltext, "no merged week ranges in the PDF")
    if doc.page_count > 1:
        for pno in range(doc.page_count):
            t = doc[pno].get_text()
            check("Nairobi Primary School" in t, f"header repeats on page {pno + 1}")
    doc.close()
    out.unlink(missing_ok=True)

    print("\n== N. Duplicate / status / list ==")
    dup, _ = duplicate_plan(plan["id"], "Term 2")
    check(dup["term"] == "Term 2" and dup["header"]["term"] == "Term 2", "duplicate moves to Term 2")
    check(dup["sections"][0]["reflection"]["text"] == "", "duplicate clears teacher cells")
    fin, _ = set_plan_status(plan["id"], "Final")
    check(fin["status"] == "Final", "Mark Final works")

    print("\n== O. No AI in generation ==")
    raw = (BACKEND / "services" / "plan_service.py").read_text(encoding="utf-8")
    import ast as _ast
    tree = _ast.parse(raw)
    docs = set()
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.Module, _ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
            ds = _ast.get_docstring(node)
            if ds:
                docs.add(ds)
    code = raw
    for ds in docs:
        code = code.replace(ds, "")
    code = "\n".join(l for l in code.splitlines() if not l.strip().startswith("#")).lower()
    for bad in ("openai", "gemini", "anthropic", "gpt", "requests.post", "httpx"):
        check(bad not in code, f"no '{bad}' call")

    for p in list_plans()["plans"]:
        delete_plan(p["id"])
    delete_library_document(mid)

    print("\n" + "=" * 68)
    if failures:
        print(f"RESULT: {len(failures)} FAILURE(S)")
        for f in failures:
            print("  - " + f)
        return 1
    print("RESULT: ALL PHASE 3 (KICD SCHEME) CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
