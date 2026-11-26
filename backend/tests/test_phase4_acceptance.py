"""Phase 4 acceptance tests - scheme editing/history + KICD lesson plans.

Covers the strict Phase 4 contract:
  * inline scheme editing, Teacher Edited + Dirty - Unsaved, exact validation message
  * [Save Version] comments, append-only history, diff, restore -> NEW version
  * [Undo Last Edit], [Reset Row to Source] (keeps Reflection), bulk resources,
    [Clear All Reflections]
  * Mark Final -> "Final - Term 1", edit blocked, [Unlock to Edit] -> new Draft version
  * one week = N independent lesson plans, single integer Lesson, vetting guard
  * primary + JSS templates, focused lesson SLOs, fully editable fields with source history
  * deterministic decomposition, rubric-derived Planned Assessment, no duplicates
  * AI off message, web top-3, portrait lesson PDF / landscape scheme PDF
  * parser engine + repair.py unchanged during Phase 4
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

TEST_DB = BACKEND / "studio_p4acc_test.db"
TEST_UPLOADS = BACKEND / "_test_uploads_p4acc"
if TEST_DB.exists():
    TEST_DB.unlink()
if TEST_UPLOADS.exists():
    shutil.rmtree(TEST_UPLOADS, ignore_errors=True)

os.environ["MWALIMU_STUDIO_DB"] = str(TEST_DB)
os.environ["MWALIMU_STUDIO_UPLOADS"] = str(TEST_UPLOADS)
os.environ["GEMINI_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

import main as app_main  # noqa: E402
from db import connect, init_db, new_id  # noqa: E402
from services.library_service import VETTED, get_library_document  # noqa: E402
from services.lesson_derive import (  # noqa: E402
    assign_lessons,
    decompose_experience,
    decompose_experiences,
)
from services.lesson_pdf import load_lesson_template, render_lesson_pdf  # noqa: E402
from services.parse_service import approve_all, correct_chunk, parse_and_store  # noqa: E402
from services.plan_service import (  # noqa: E402
    create_plan_version,
    edit_section,
    get_plan,
    get_plan_version,
    list_plan_versions,
    validate_plan,
)
from services.rubric_service import (  # noqa: E402
    format_planned_assessment,
    match_rubrics,
    parse_rubric_tables,
)
from services.scheme_pdf import render_scheme_pdf  # noqa: E402

CD = Path(r"C:\Users\user\Desktop\Curriculum Designs")
MATHS = CD / "Grade-1-Mathematics-Activities-Curriculum-Design.pdf"

PARSER_ENGINE_MD5 = "f23fa26844aae2ff496c547d1f83a755"
REPAIR_MD5 = "af9ee575cd25ac4442fb482d3bc7d9d2"

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {msg}")
    if not cond:
        failures.append(msg)


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def vet_all(mid: str) -> dict:
    approve_all(mid, 0.9)
    for _ in range(8):
        d = get_library_document(mid)
        pending = [
            c for c in d["chunks"] if c["reviewState"] not in ("Approved", "TeacherCorrected")
        ]
        if not pending:
            return d
        for c in pending:
            correct_chunk(mid, c["id"], {"reviewState": "Approved"})
    return get_library_document(mid)


def run() -> int:  # noqa: C901
    init_db()

    print("\n== A. Parser engine is byte-identical; no Phase 4 repair patches ==")
    check(md5(BACKEND / "services" / "parser_engine.py") == PARSER_ENGINE_MD5,
          "parser_engine.py unchanged (md5)")
    check(md5(BACKEND / "services" / "repair.py") == REPAIR_MD5,
          "repair.py unchanged (md5, no new patches)")

    print("\n== B. Two lesson templates: primary vs JSS (11-part KICD order) ==")
    from services.lesson_templates import template_for_grade

    expected_keys = [
        "outcomes", "kiq", "competencies", "values", "pcis", "resources",
        "introduction", "step1", "step2", "step3", "conclusion",
        "extended", "assessment", "reflection",
    ]
    primary = load_lesson_template("cbe-lesson-primary-v1")
    jss = load_lesson_template("cbe-lesson-jss-v1")
    check(primary.get("landscape") is False and jss.get("landscape") is False,
          "both lesson templates are portrait")
    check([s["key"] for s in primary["sections"]] == expected_keys,
          "primary template has the 11-part KICD order")
    check([s["key"] for s in jss["sections"]] == expected_keys,
          "JSS template has the 11-part KICD order")
    check(primary["defaultDuration"] == 35 and primary["durationOptions"] == [35],
          "primary default duration 35 min")
    check("activity-based" in primary["developmentHint"].lower()
          and "song" in primary["developmentHint"].lower(),
          "primary hint is activity-based (song/play/manipulatives)")
    check(jss["defaultDuration"] == 40 and jss["durationOptions"] == [40, 80],
          "JSS duration options 40 / 80 min")
    check("experiment" in jss["developmentHint"].lower()
          and "project" in jss["developmentHint"].lower(),
          "JSS hint is experiment/project/investigation")
    check(primary["outcomesHeading"].startswith("By the end of the lesson"),
          "lesson SLO heading is lesson-based")
    check(primary["sourceOutcomesHeading"].startswith("Source: By the end of the sub-strand"),
          "side panel keeps sub-strand source heading")
    check(template_for_grade("Grade 1") == "cbe-lesson-primary-v1",
          "Grade 1 auto-selects primary")
    check(template_for_grade("Grade 8") == "cbe-lesson-jss-v1",
          "Grade 8 auto-selects JSS")
    check(primary["sidePanel"]["readOnly"] is True, "side panel read-only")

    print("\n== C. Deterministic lesson_derive ==")
    atoms = decompose_experience(
        "sort objects by colour, shape and size"
    )
    check([a["focus"] for a in atoms] == ["colour", "shape", "size"],
          f"attribute list -> 3 atoms ({[a['focus'] for a in atoms]})")
    verbs = decompose_experience("sort, group and match objects")
    check([a["focus"] for a in verbs] == ["sort", "group", "match"],
          "verb list -> 3 atoms")
    pair = decompose_experience(
        "in pairs or groups, recognize and read numbers 1 to 100 from number cards"
    )
    check([a["focus"] for a in pair] == ["recognize", "read"],
          "'in pairs or groups' prefix is stripped, not treated as a verb list")
    check(len(decompose_experience("count numbers 1 to 10")) == 1,
          "no pattern -> 1 atomic skill")
    many = decompose_experiences([
        "order objects by size, colour, shape and weight",
        "sort, group, match, classify and compare objects",
    ])
    nine = assign_lessons(many, 5, source_quote="all skills")
    check(len(nine["atoms"]) == len(many), "never drops a skill")
    check(bool(nine.get("warnings")) and bool(nine.get("spill")),
          f"overflow warns + spills ({nine.get('warnings')})")
    five = assign_lessons(
        decompose_experience("sort objects by colour, shape and size"), 5, source_quote="x"
    )
    kinds = [a["kind"] for a in five["assignments"]]
    check(kinds[:3] == ["atomic", "atomic", "atomic"], "first 3 lessons are atomic")
    check("consolidation" in kinds and "assessment" in kinds,
          "padded with consolidation + assessment")

    print("\n== D. Rubric extraction + planned assessment ==")
    rubrics = parse_rubric_tables(MATHS)
    check(len(rubrics) >= 1, f"rubric tables parsed ({len(rubrics)})")
    first = rubrics[0]
    check(first["page"] == 15 and len(first["levels"]) == 4,
          f"p.15 indicator with 4 levels ({first['page']}, {list(first['levels'])})")
    matched = match_rubrics(rubrics, "sort group and match objects according to attributes")
    check(matched and matched[0]["indicator"].startswith("Ability to sort"),
          "token-overlap match picks the right indicator")
    planned, differentiation = format_planned_assessment(matched, "Observation")
    check("Planned Assessment (from Rubric p.15):" in planned,
          "planned assessment label includes rubric page")
    check("Indicator:" in planned and all(
        level in planned for level in ("Exceeds", "Meets", "Approaches", "Below")
    ), "Indicator + all four levels")
    check("Support:" in differentiation and "Extension:" in differentiation,
          "differentiation Support/Extension")

    print("\n== E. Upload + vet Grade 1 Mathematics ==")
    maths = parse_and_store(MATHS.read_bytes(), MATHS.name)
    mid = maths["id"]
    d = vet_all(mid)
    check(all(c["vettingStatus"] == VETTED for c in d["chunks"]), "all chunks Vetted")
    c11 = next(c for c in d["chunks"] if c["subStrandCode"] == "1.1")
    check(c11["lessons"] == 20, "1.1 lessons = 20")

    client = TestClient(app_main.app)
    # Phase 9: legacy acceptance runs as one signed-in teacher. Direct service
    # calls below use the same owner scope as the authenticated HTTP client.
    import auth_service
    legacy_user = client.post("/api/auth/signup", json={
        "name": "Acceptance Teacher", "email": "acceptance@example.com", "password": "Passw0rd",
    }).json()
    auth_service.set_owner(legacy_user["id"])

    print("\n== F. Scheme generation + baseline version v1 ==")
    res = client.post("/api/plans", json={
        "type": "scheme", "institution": "Nairobi Primary School", "grade": "Grade 1",
        "subject": "Mathematics", "term": "Term 1", "year": "2025",
        "lessonsPerWeek": 5, "totalWeeks": 13, "sourceChunkIds": [c11["id"]],
    })
    check(res.status_code == 200, f"generate scheme ({res.status_code})")
    plan = res.json()
    pid = plan["id"]
    row = plan["sections"][0]
    row2 = plan["sections"][1]
    check(plan["dirty"] is False, "new plan is Saved, not Dirty")
    check(row["sourceVetted"] is True, "row knows its source is Vetted")
    check(row["weekLessonCount"] == 5, "row exposes 5 lessons")
    check("decomposition" in row and row["decomposition"]["preview"],
          "row exposes deterministic decomposition preview")

    vs = client.get(f"/api/plans/{pid}/versions").json()
    check(vs["count"] == 1 and vs["versions"][0]["versionNumber"] == 1,
          "baseline v1 created automatically")

    print("\n== G. Exact endpoint: GET versions / POST restore / GET diff ==")
    check(client.get(f"/api/plans/{pid}/versions").status_code == 200,
          "GET /api/plans/{id}/versions")
    d0 = client.get(f"/api/plans/{pid}/versions/{vs['versions'][0]['id']}/diff")
    check(d0.status_code == 200, "GET /api/plans/{id}/versions/{vid}/diff")
    check("cells" in d0.json() and "summary" in d0.json(), "diff payload has cells + summary")

    print("\n== H. Save Version: comment required, snapshot whole plan ==")
    bad = client.post(f"/api/plans/{pid}/versions", json={"comment": "   "})
    check(bad.status_code == 422, "empty comment rejected")
    saved = client.post(f"/api/plans/{pid}/versions", json={"comment": "Initial teacher save"})
    check(saved.status_code == 200, f"save version ({saved.status_code})")
    v2 = saved.json()
    check(v2["versionNumber"] == 2 and v2["label"] == "v2", "first save is v2")
    check(saved.json()["plan"]["dirty"] is False, "saving clears Dirty - Unsaved")
    snap = get_plan_version(pid, v2["id"])
    check(
        snap is not None
        and snap["snapshot"].get("header")
        and snap["snapshot"].get("sections")
        and snap["snapshot"]["sections"][0].get("citations") is not None,
        "snapshot contains the entire plan (header + sections + citations)",
    )

    print("\n== I. Inline edit: Teacher Edited + Dirty - Unsaved + validation ==")
    edited = client.post(
        f"/api/plans/{pid}/sections/{row['id']}/edit",
        json={"outcomes": ["Teacher wrote this by hand"]},
    )
    check(edited.status_code == 200, f"edit saved ({edited.status_code})")
    ep = edited.json()
    er = next(s for s in ep["sections"] if s["id"] == row["id"])
    check(er["outcomes"] == ["Teacher wrote this by hand"], "cell edited")
    check(er["edited"] is True, "row marked Teacher Edited")
    check(ep["dirty"] is True, "plan marked Dirty - Unsaved")

    empty = client.post(
        f"/api/plans/{pid}/sections/{row2['id']}/edit", json={"outcomes": []}
    )
    expected = (
        f"Week {row2['week']} Outcomes cannot be empty - this was Vetted from source. "
        "Restore from source or unselect row."
    )
    check(empty.status_code == 422 and empty.json()["detail"] == expected,
          f"exact empty-Outcomes message ({empty.json().get('detail')})")

    for bad_week in (0, 14):
        r = client.post(
            f"/api/plans/{pid}/sections/{row2['id']}/edit", json={"week": bad_week}
        )
        check(r.status_code == 422, f"Week {bad_week} rejected (1-13)")
    bad_lesson = client.post(
        f"/api/plans/{pid}/sections/{row2['id']}/edit", json={"lesson": "6-10"}
    )
    check(bad_lesson.status_code == 422, "Lesson outside 1-5 rejected")
    bad_format = client.post(
        f"/api/plans/{pid}/sections/{row2['id']}/edit", json={"lesson": "one-five"}
    )
    check(bad_format.status_code == 422, 'Lesson must match "1-5"')

    print("\n== J. [Undo Last Edit] ==")
    undone = client.post(f"/api/plans/{pid}/undo")
    check(undone.status_code == 200, "undo endpoint")
    ur = next(s for s in undone.json()["sections"] if s["id"] == row["id"])
    check(ur["outcomes"] == row["outcomes"], "undo restored the previous cell")
    check(ur["edited"] is False, "undo restored the Teacher Edited flag")

    print("\n== K. [Reset Row to Source] keeps Reflection ==")
    client.post(
        f"/api/plans/{pid}/sections/{row['id']}/edit", json={"reflection": "Keep this note"}
    )
    client.post(
        f"/api/plans/{pid}/sections/{row['id']}/edit", json={"outcomes": ["Changed again"]}
    )
    reset = client.post(f"/api/plans/{pid}/sections/{row['id']}/reset-source")
    check(reset.status_code == 200, "reset-source endpoint")
    rr = next(s for s in reset.json()["sections"] if s["id"] == row["id"])
    check(rr["reflection"]["text"] == "Keep this note", "Reflection kept")
    check(rr["outcomes"] == row["outcomes"], "Outcomes restored to source")
    check(rr["experiences"] == row["experiences"], "Experiences restored to source")
    check(rr["kiqs"] == row["kiqs"], "KIQs restored to source")
    check(rr["edited"] is False, "Teacher Edited cleared")

    print("\n== L. Bulk resources + [Clear All Reflections] ==")
    code = row["subStrandCode"]
    bulk = client.post(
        f"/api/plans/{pid}/bulk-resources",
        json={"subStrandCode": code, "resources": "Bulk resources for every week"},
    )
    check(bulk.status_code == 200, "bulk-resources endpoint")
    same_group = [s for s in bulk.json()["sections"] if s["subStrandCode"] == code]
    check(len(same_group) == 4 and all(
        s["resources"]["text"] == "Bulk resources for every week" for s in same_group
    ), "resources applied to all weeks of the sub-strand")
    check(all(s["edited"] is True for s in same_group), "bulk-edited rows marked Teacher Edited")

    clear = client.post(f"/api/plans/{pid}/clear-reflections")
    check(clear.status_code == 200, "clear-reflections endpoint")
    check(all(not s["reflection"]["text"] for s in clear.json()["sections"]),
          "every reflection cleared")

    print("\n== M. Restore appends a NEW version, never deletes ==")
    count_before = list_plan_versions(pid)["count"]
    restored = client.post(f"/api/plans/{pid}/versions/{v2['id']}/restore")
    check(restored.status_code == 200, "POST restore endpoint")
    payload = restored.json()
    check(payload["restoredVersion"]["versionNumber"] == count_before + 1,
          "restore created the next version number")
    check(list_plan_versions(pid)["count"] == count_before + 1,
          "version count grew (append-only)")
    check(any(v["id"] == v2["id"] for v in list_plan_versions(pid)["versions"]),
          "restored-from version still exists")

    print("\n== N. Mark Final -> 'Final - Term 1'; lock; Unlock to Edit ==")
    final = client.post(f"/api/plans/{pid}/status", json={"status": "Final"})
    check(final.status_code == 200, f"mark final ({final.status_code}) {final.text[:120]}")
    fplan = final.json()
    check(fplan["status"] == "Final", "status Final")
    check(fplan["finalVersionLabel"] == "Final - Term 1", "label 'Final - Term 1'")
    fversions = list_plan_versions(pid)["versions"]
    check(any(v["label"] == "Final - Term 1" for v in fversions),
          "a 'Final - Term 1' version was appended")

    locked = client.post(
        f"/api/plans/{pid}/sections/{row['id']}/edit", json={"resources": "nope"}
    )
    check(locked.status_code == 422
          and "Unlock to Edit" in locked.json()["detail"],
          "editing a Final scheme is blocked with [Unlock to Edit]")

    n_before = list_plan_versions(pid)["count"]
    unlocked = client.post(f"/api/plans/{pid}/unlock")
    check(unlocked.status_code == 200, f"unlock endpoint ({unlocked.status_code})")
    up = unlocked.json()
    check(up["status"] == "Draft", "unlock returns Draft")
    label = up["unlockedVersion"]["label"]
    check(re.fullmatch(rf"v{n_before + 1} - Unlocked from Final", label) is not None,
          f"unlock version label ({label})")

    print("\n== O. Vetting guard for lesson plans ==")
    # Use the Week 2 row: the acceptance fixture focuses Lesson 1 on colour and Lesson 2
    # on shape, so the row's experience list is the standard sorting example.
    section_id = row2["id"]
    with connect() as conn:
        conn.execute(
            "UPDATE source_chunks SET vetting_status = 'Pending' WHERE id = ?", (c11["id"],)
        )
    blocked, berrs = __import__(
        "services.lesson_plan_service", fromlist=["create_lesson_plans"]
    ).create_lesson_plans({"schemeRowId": section_id, "lessons": [1]})
    check(blocked == [] and berrs == ["Cannot create lesson plan - source not Vetted"],
          f"exact vetting guard message ({berrs})")
    with connect() as conn:
        conn.execute(
            "UPDATE source_chunks SET vetting_status = ? WHERE id = ?", (VETTED, c11["id"])
        )

    print("\n== P. Lesson picker + creation (one week = N independent plans) ==")
    with connect() as conn:
        original = json.loads(
            conn.execute(
                "SELECT original FROM plan_sections WHERE id = ?", (section_id,)
            ).fetchone()["original"]
        )
        original["sourceExperiences"] = ["sort objects by colour, shape and size"]
        conn.execute(
            "UPDATE plan_sections SET experiences = ?, original = ? WHERE id = ?",
            (
                json.dumps(["sort objects by colour, shape and size"], ensure_ascii=False),
                json.dumps(original, ensure_ascii=False),
                section_id,
            ),
        )
    picker = client.get(f"/api/plans/{pid}/sections/{section_id}/lessons")
    check(picker.status_code == 200, "lesson picker endpoint")
    pk = picker.json()
    check(pk["lessonCount"] == 5 and pk["lessonRange"] == "1-5", "picker offers 1-5")
    check(pk["sourceVetted"] is True, "picker reports Vetted")
    check(pk["templateVersion"] == "cbe-lesson-primary-v1"
          and pk["defaultDuration"] == 35,
          "picker auto-selects the primary template for Grade 1")
    check(all(not x["created"] for x in pk["lessons"]), "nothing created yet")

    created = client.post("/api/lesson-plans", json={
        "schemeRowId": section_id, "lessons": [1, 2],
        "dates": {"1": "2026-01-12"}, "time": "08:00", "classSize": 32,
    })
    check(created.status_code == 200, f"create lesson plans ({created.status_code})")
    cj = created.json()
    check(cj["count"] == 2, "created 2 lesson plans")
    lp1 = cj["created"][0]
    lp2 = cj["created"][1]
    check(isinstance(lp1["lesson"], int) and lp1["lesson"] == 1,
          "single integer Lesson (never '1-5')")
    check(lp1["week"] == row2["week"], "lesson inherits the row's week")
    check(lp1["header"]["date"] == "2026-01-12", "Date for Lesson 1 saved")
    check(lp1["header"]["duration"] == 35, "primary default duration 35 saved")
    check(lp1["templateVersion"] == "cbe-lesson-primary-v1"
          and lp1["gradeBand"] == "primary", "Grade 1 lesson uses the primary template")
    check(lp1["durationOptions"] == [35], "primary duration option 35")
    check("activity-based" in str(lp1["developmentHint"]).lower(),
          "primary activity hint exposed")

    by_key = {s["key"]: s for s in lp1["sections"]}
    keys = [s["key"] for s in lp1["sections"]]
    check(keys == expected_keys, f"stored 11-part KICD section order ({keys})")
    check(all(s["editable"] for s in lp1["sections"]),
          "every lesson field is editable")
    check(lp1["sections"][0]["body"].startswith(
        "By the end of the lesson, the learner should be able to:"),
        "SLO header is lesson-based")
    check("by colour only" in lp1["sections"][0]["body"].lower(),
          f"Lesson 1 SLO focuses on colour only ({lp1['sections'][0]['body']})")
    check("sub-strand" not in lp1["sections"][0]["body"].lower(),
          "Lesson 1 SLO never says 'sub-strand'")
    check("by shape only" in lp2["sections"][0]["body"].lower(),
          f"Lesson 2 SLO focuses on shape only ({lp2['sections'][0]['body']})")
    check(lp1["sections"][0]["body"] != lp2["sections"][0]["body"],
          "Lesson 1 and Lesson 2 have different focused SLOs")
    check(lp1["sloWarning"] is None, "valid lesson SLO has no warning")

    intro = by_key["introduction"]
    step1 = by_key["step1"]
    check(intro["data"].get("time") == "5 min", "Introduction time is 5 min")
    check(intro["data"].get("teacherActivity") == ""
          and intro["data"].get("learnerActivity") == "",
          "Introduction starts empty for the teacher")
    check(step1["data"].get("teacherActivity", "").strip() != ""
          and step1["data"].get("learnerActivity", "").strip() != "",
          "Step 1 derives Teacher Activity + Learner Activity separately")
    check("time" in step1["data"], "Step 1 exposes its own Time field")
    check(by_key["conclusion"]["data"].get("time") == "5 min",
          "Conclusion time is 5 min")
    check(by_key["kiq"]["body"] == (lp1["source"]["kiqs"] or ["—"])[0],
          "KIQ verbatim")
    check(by_key["resources"]["body"] == str(
        lp1["source"]["resources"] or "— Not specified in source"),
        "Resources verbatim")
    check(by_key["competencies"]["body"] == str(lp1["source"]["competencies"] or ""),
          "Core Competencies from source")
    check(by_key["values"]["body"] == str(lp1["source"]["values"] or ""),
          "Values from source")
    check(by_key["pcis"]["body"] == str(lp1["source"]["pcis"] or ""),
          "PCIs from source")
    planned = lp1["assessment"]["planned"]
    check("Planned Assessment (from Rubric p.15):" in planned,
          f"rubric planned assessment ({planned[:60]})")
    check("Indicator:" in planned and all(
        level in planned for level in ("Exceeds", "Meets", "Approaches", "Below")
    ), "planned assessment has indicator + 4 levels")
    assess = by_key["assessment"]["data"]
    check({"method", "description", "sampleItems", "rubricIndicator"} <= set(assess),
          "Assessment is structured (method/description/sampleItems/rubricIndicator)")
    check(bool(assess.get("rubricIndicator")), "Assessment carries the rubric indicator")

    print("\n== Q. Never duplicates; existing lessons show ✓ Created ==")
    again = client.post("/api/lesson-plans", json={"schemeRowId": section_id, "lessons": [1, 2]})
    check(again.status_code == 422, "creating the same lessons again is rejected")
    picker2 = client.get(f"/api/plans/{pid}/sections/{section_id}/lessons").json()
    check(picker2["lessons"][0]["created"] and picker2["lessons"][1]["created"],
          "picker marks existing lessons ✓ Created")
    check(not picker2["lessons"][2]["created"], "missing Lesson 3 stays uncreated")
    check(sum(1 for x in picker2["lessons"] if x["created"]) == 2, "still exactly 2 plans")

    only_missing = client.post("/api/lesson-plans", json={
        "schemeRowId": section_id, "lessons": [3, 4],
    })
    check(only_missing.status_code == 200 and only_missing.json()["count"] == 2,
          "Create Missing Only adds just the missing lessons")
    total = client.get(f"/api/lesson-plans?sectionId={section_id}").json()["count"]
    check(total == 4, "no duplicate lesson plans")

    print("\n== R. Every lesson field editable; badges; reset; versions; AI-off ==")
    lp_id = lp1["id"]
    intro = next(s for s in lp1["sections"] if s["key"] == "introduction")
    edit = client.post(
        f"/api/lesson-plans/{lp_id}/sections/{intro['id']}/edit",
        json={"data": {
            "time": "5 min",
            "teacherActivity": "Sing a colour-sorting song",
            "learnerActivity": "Learners join the song and point to colours",
        }},
    )
    check(edit.status_code == 200, "lesson structured step edit")
    ei = next(s for s in edit.json()["sections"] if s["id"] == intro["id"])
    check(ei["data"]["teacherActivity"] == "Sing a colour-sorting song",
          "teacher activity saved separately")
    check(ei["data"]["learnerActivity"].startswith("Learners join"),
          "learner activity saved separately")
    check(ei["editedFromSource"] is True, "edited step gets 'Edited from source'")

    # Edit Strand in the header -> persists, badge appears, reset restores source.
    before_chunk = next(
        c for c in get_library_document(mid)["chunks"] if c["id"] == c11["id"]
    )
    strand_edit = client.post(
        f"/api/lesson-plans/{lp_id}/header", json={"strand": "Numbers (edited)"}
    )
    check(strand_edit.status_code == 200, "edit Strand in lesson header")
    sj = strand_edit.json()
    check(sj["strand"] == "Numbers (edited)", "new Strand persists")
    check("strand" in sj["headerEditedFields"], "Strand shows 'Edited from source'")
    after_chunk = next(
        c for c in get_library_document(mid)["chunks"] if c["id"] == c11["id"]
    )
    check(after_chunk["strand"] == before_chunk["strand"],
          "SourceChunk Strand is unchanged (immutable)")
    reopen = client.get(f"/api/lesson-plans/{lp_id}").json()
    check(reopen["strand"] == "Numbers (edited)", "Strand survives reopen")
    rs = client.post(f"/api/lesson-plans/{lp_id}/header/reset", json={"field": "strand"})
    check(rs.status_code == 200 and rs.json()["strand"] == before_chunk["strand"],
          "[Reset to Source] restores the original Strand")
    check("strand" not in rs.json()["headerEditedFields"],
          "reset clears the 'Edited from source' badge")

    # SLO guard: saving a sub-strand heading warns, [Fix Automatically] converts it.
    out = next(s for s in lp1["sections"] if s["key"] == "outcomes")
    bad_slo = client.post(
        f"/api/lesson-plans/{lp_id}/sections/{out['id']}/edit",
        json={"body": (
            "By the end of the sub-strand, the learner should be able to: "
            "a) sort objects by colour only"
        )},
    )
    check(bad_slo.status_code == 200, "sub-strand SLO can be saved for correction")
    check(bad_slo.json()["sloWarning"]
          == "Should be 'By the end of the lesson' for a lesson plan - Fix?",
          "warning shown for sub-strand SLO")
    fixed = client.post(f"/api/lesson-plans/{lp_id}/slo/fix")
    check(fixed.status_code == 200, "[Fix Automatically] endpoint")
    fixed_body = next(s for s in fixed.json()["sections"] if s["key"] == "outcomes")["body"]
    check(fixed_body.startswith("By the end of the lesson, the learner should be able to:"),
          "Fix converts SLO to lesson heading")
    check("by colour only" in fixed_body.lower(), "Fix keeps the atomic focus")
    check(fixed.json()["sloWarning"] is None, "warning cleared after fix")

    check(len(client.get(f"/api/lesson-plans/{lp_id}/versions").json()["versions"]) == 1,
          "lesson starts with baseline version v1")
    sv = client.post(f"/api/lesson-plans/{lp_id}/versions", json={"comment": "Added intro hook"})
    check(sv.status_code == 200 and sv.json()["versionNumber"] == 2, "lesson Save Version -> v2")
    lv = client.get(f"/api/lesson-plans/{lp_id}/versions").json()["versions"]
    lr = client.post(f"/api/lesson-plans/{lp_id}/versions/{lv[-1]['id']}/restore")
    check(lr.status_code == 200, "lesson restore endpoint")
    check(len(client.get(f"/api/lesson-plans/{lp_id}/versions").json()["versions"]) == 3,
          "lesson restore appends a version")

    ai = client.post(f"/api/lesson-plans/{lp_id}/ai/draft")
    check(ai.status_code == 422 and ai.json()["detail"] == "AI enrichment needs GEMINI_API_KEY",
          "AI disabled with exact message")

    web = client.get(f"/api/lesson-plans/{lp_id}/web-examples?q=sorting objects")
    check(web.status_code == 200, "web examples endpoint")
    results = web.json()["results"]
    check(all({"title", "url", "snippet"} <= set(r) for r in results),
          "web returns only verified real results")
    check(len(results) == 0, "web returns no invented results when AI is unavailable")

    print("\n== R2. Grade 8 auto-selects the JSS template ==")
    with connect() as conn:
        conn.execute(
            "UPDATE plan_documents SET grade = 'Grade 8' WHERE id = ?", (pid,)
        )
    jss_created = client.post("/api/lesson-plans", json={
        "schemeRowId": section_id, "lessons": [5],
    })
    check(jss_created.status_code == 200, "create Grade 8 lesson plan")
    jp = jss_created.json()["created"][0]
    check(jp["templateVersion"] == "cbe-lesson-jss-v1" and jp["gradeBand"] == "jss",
          "Grade 8 auto-selects JSS template")
    check(jp["duration"] == 40 and jp["durationOptions"] == [40, 80],
          "JSS defaults to 40 min with 40/80 options")
    check("experiment" in str(jp["developmentHint"]).lower(),
          "JSS hint mentions experiment/project")
    double = client.post(
        f"/api/lesson-plans/{jp['id']}/header",
        json={"durationType": "Double", "duration": 80},
    )
    check(double.status_code == 200 and double.json()["duration"] == 80,
          "JSS Double lesson saves 80 min")
    with connect() as conn:
        conn.execute(
            "UPDATE plan_documents SET grade = 'Grade 1' WHERE id = ?", (pid,)
        )

    print("\n== S. PDFs: scheme landscape, lesson portrait, repeating header ==")
    scheme_pdf = render_scheme_pdf(get_plan(pid))
    lp_pdf = render_lesson_pdf(client.get(f"/api/lesson-plans/{lp_id}").json())
    import fitz

    sdoc = fitz.open(stream=scheme_pdf, filetype="pdf")
    check(sdoc[0].rect.width > sdoc[0].rect.height, "scheme PDF landscape A4")
    check("Key Inquiry Question" in "".join(p.get_text() for p in sdoc),
          "scheme header repeats")
    sdoc.close()

    ldoc = fitz.open(stream=lp_pdf, filetype="pdf")
    check(ldoc[0].rect.height > ldoc[0].rect.width, "lesson PDF portrait A4")
    ltxt = "".join(p.get_text() for p in ldoc)
    for title in (
        "LESSON PLAN", "1. Administrative Details", "2. Strand", "3. Sub-Strand",
        "4. Specific Learning Outcomes", "5. Key Inquiry Question(s)",
        "6. Core Competencies", "7. Values", "8. Pertinent & Contemporary Issues",
        "9. Learning Resources", "10. Lesson Development",
        "10. Lesson Development - Introduction", "10. Lesson Development - Step 1",
        "11. Extended Activities", "11. Assessment", "Reflection",
        "Teacher Activity", "Learner Activity", "Planned Assessment (from Rubric)",
    ):
        check(title in ltxt, f"lesson PDF contains {title}")
    check("By the end of the lesson, the learner should be able to:" in ltxt,
          "lesson PDF prints the lesson-based SLO heading")
    if ldoc.page_count > 1:
        check("LESSON PLAN" in ldoc[1].get_text(), "lesson header repeats on page 2")
    ldoc.close()

    print("\n== T. Whole-plan validation blocks Save Version ==")
    with connect() as conn:
        conn.execute(
            "UPDATE plan_sections SET outcomes = '[]' WHERE id = ?", (section_id,)
        )
    p_now = get_plan(pid)
    check(any("Outcomes cannot be empty" in e for e in validate_plan(p_now)),
          "validate_plan catches empty Outcomes")
    blocked_save = client.post(f"/api/plans/{pid}/versions", json={"comment": "should fail"})
    check(blocked_save.status_code == 422, "Save Version blocked by whole-plan validation")
    with connect() as conn:
        conn.execute(
            "UPDATE plan_sections SET outcomes = ? WHERE id = ?",
            (json.dumps(row2["outcomes"], ensure_ascii=False), section_id),
        )

    print("\n" + "=" * 64)
    if failures:
        print(f"RESULT: {len(failures)} FAILURE(S)")
        for f in failures:
            print("  -", f)
        return 1
    print("RESULT: ALL PHASE 4 ACCEPTANCE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
