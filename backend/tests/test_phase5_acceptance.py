"""Phase 5 acceptance tests - learner-facing Lesson Notes.

Covers the Phase 5 contract:
  * one notes document per LESSON (Week 2 = 5 docs: colour, shape, size,
    consolidation, assessment), never one per week
  * generated from a scheme row [-> Lesson Notes (5)] or a Lesson Plan
  * Vetted-source guard with the exact message
  * title "[Sub-Strand] - [Focus]" and SLO "By the end of the lesson, you will be able to:"
  * every paragraph / vocabulary item / example / question editable, SourceChunk immutable
  * primary and JSS notes templates, picture placeholders vs diagram descriptions
  * AI draft is review-only (yellow label), Accept / Reject / Accept All, no-key message
  * teacher-initiated web search, explicit insert with "[Web Example - URL]", teacher sources
  * append-only versions, Mark Final, portrait A4 learner PDF with hidden practice answers
  * parser_engine.py + repair.py unchanged
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

TEST_DB = BACKEND / "studio_p5acc_test.db"
TEST_UPLOADS = BACKEND / "_test_uploads_p5acc"
if TEST_DB.exists():
    TEST_DB.unlink()
if TEST_UPLOADS.exists():
    shutil.rmtree(TEST_UPLOADS, ignore_errors=True)

os.environ["MWALIMU_STUDIO_DB"] = str(TEST_DB)
os.environ["MWALIMU_STUDIO_UPLOADS"] = str(TEST_UPLOADS)
os.environ["GEMINI_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

import main as app_main  # noqa: E402
import fitz  # noqa: E402
from db import connect, init_db  # noqa: E402
from services import lesson_notes_service as lns  # noqa: E402
from services.library_service import VETTED, get_library_document  # noqa: E402
from services.lesson_templates import (  # noqa: E402
    load_notes_template,
    notes_template_for_grade,
)
from services.parse_service import approve_all, correct_chunk, parse_and_store  # noqa: E402
from services.notes_pdf import render_notes_pdf  # noqa: E402

CD = Path(r"C:\Users\user\Desktop\Curriculum Designs")
MATHS = CD / "Grade-1-Mathematics-Activities-Curriculum-Design.pdf"

PARSER_ENGINE_MD5 = "f23fa26844aae2ff496c547d1f83a755"
REPAIR_MD5 = "af9ee575cd25ac4442fb482d3bc7d9d2"
VETTING_MESSAGE = "Cannot generate notes - source not Vetted"
SLO_PREFIX = "By the end of the lesson, you will be able to:"
SECTION_ORDER = [
    "title",
    "slo",
    "vocabulary",
    "whatIs",
    "examples",
    "workedExample",
    "practice",
    "remember",
    "footer",
]

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


def chunk_fingerprint(mid: str, chunk_id: str) -> str:
    chunk = next(c for c in get_library_document(mid)["chunks"] if c["id"] == chunk_id)
    keep = {
        "id": chunk["id"],
        "subStrand": chunk["subStrand"],
        "lessons": chunk["lessons"],
        "structuredFields": chunk["structuredFields"],
        "pageNumber": chunk["pageNumber"],
        "vettingStatus": chunk["vettingStatus"],
    }
    return json.dumps(keep, sort_keys=True, ensure_ascii=False)


def section(note: dict, key: str) -> dict:
    return next(s for s in note["sections"] if s["key"] == key)


def run() -> int:  # noqa: C901
    init_db()
    client = TestClient(app_main.app)
    # Phase 9: run the legacy suite inside one teacher's private workspace.
    import auth_service
    legacy_user = client.post("/api/auth/signup", json={
        "name": "Acceptance Teacher", "email": "acceptance@example.com", "password": "Passw0rd",
    }).json()
    auth_service.set_owner(legacy_user["id"])

    print("\n== A. Parser + repair are byte-identical (no new patches) ==")
    check(md5(BACKEND / "services" / "parser_engine.py") == PARSER_ENGINE_MD5,
          "parser_engine.py unchanged (md5)")
    check(md5(BACKEND / "services" / "repair.py") == REPAIR_MD5,
          "repair.py unchanged (md5)")

    print("\n== B. Two notes templates: primary vs JSS (not the lesson-plan template) ==")
    primary = load_notes_template("cbe-lesson-notes-v1", "Grade 1")
    jss = load_notes_template("cbe-lesson-notes-jss-v1", "Grade 8")
    check(primary["kind"] == "lesson-notes" and jss["kind"] == "lesson-notes",
          "notes templates have their own kind")
    check([s["key"] for s in primary["sections"]] == SECTION_ORDER,
          "primary notes section order is exact")
    check([s["key"] for s in jss["sections"]] == SECTION_ORDER,
          "JSS notes section order is exact")
    check(primary.get("picturePlaceholders") is True,
          "primary uses [Picture: ...] placeholders")
    check(jss.get("picturePlaceholders") is False,
          "JSS does not use fake pictures")
    check(primary.get("shortSentences") is True and jss.get("shortSentences") is False,
          "primary short sentences; JSS longer explanations")
    check(primary.get("practiceCount") == 4 and jss.get("practiceCount") == 5,
          "primary 4 practice questions; JSS 5")
    check(primary["bodySize"] > jss["bodySize"], "primary PDF font is larger")
    check(notes_template_for_grade("Grade 1") == "cbe-lesson-notes-v1"
          and notes_template_for_grade("Grade 8") == "cbe-lesson-notes-jss-v1",
          "grade auto-selects the right notes template")
    check(primary["sloHeading"] == SLO_PREFIX, "notes SLO heading is learner-facing")

    print("\n== C. Upload + vet Grade 1 Mathematics ==")
    maths = parse_and_store(MATHS.read_bytes(), MATHS.name)
    mid = maths["id"]
    d = vet_all(mid)
    check(all(c["vettingStatus"] == VETTED for c in d["chunks"]), "all chunks Vetted")
    c11 = next(c for c in d["chunks"] if c["subStrandCode"] == "1.1")

    print("\n== D. Scheme with 5 lessons in Week 2 ==")
    res = client.post("/api/plans", json={
        "type": "scheme", "institution": "Nairobi Primary School", "grade": "Grade 1",
        "subject": "Mathematics", "term": "Term 1", "year": "2025",
        "lessonsPerWeek": 5, "totalWeeks": 13, "sourceChunkIds": [c11["id"]],
    })
    check(res.status_code == 200, f"generate scheme ({res.status_code})")
    plan = res.json()
    pid = plan["id"]
    row2 = plan["sections"][1]
    section_id = row2["id"]

    # Deterministic fixture: colour, shape, size -> consolidation, assessment.
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

    print("\n== E. Notes picker: one document per lesson + vetting guard ==")
    picker = client.get(f"/api/plans/{pid}/sections/{section_id}/notes-picker")
    check(picker.status_code == 200, "notes picker endpoint")
    pk = picker.json()
    check(pk["lessonCount"] == 5 and pk["lessonRange"] == "1-5",
          "picker offers a single lesson range 1-5")
    check(pk["sourceVetted"] is True and pk["vettingMessage"] is None,
          "picker reports a Vetted source")
    check(pk["templateVersion"] == "cbe-lesson-notes-v1"
          and pk["gradeBand"] == "primary", "picker auto-selects primary notes")
    check(len(pk["lessons"]) == 5 and all(not x["created"] for x in pk["lessons"]),
          "5 independent lessons, nothing created yet")

    with connect() as conn:
        conn.execute(
            "UPDATE source_chunks SET vetting_status = 'Pending' WHERE id = ?", (c11["id"],)
        )
    blocked = client.post("/api/lesson-notes", json={
        "schemeRowId": section_id, "lessons": [1],
    })
    check(blocked.status_code == 422 and blocked.json()["detail"] == VETTING_MESSAGE,
          f"exact vetting message ({blocked.json().get('detail')})")
    blocked_picker = client.get(
        f"/api/plans/{pid}/sections/{section_id}/notes-picker"
    ).json()
    check(blocked_picker["sourceVetted"] is False
          and blocked_picker["vettingMessage"] == VETTING_MESSAGE,
          "picker exposes the exact vetting message")
    with connect() as conn:
        conn.execute(
            "UPDATE source_chunks SET vetting_status = ? WHERE id = ?", (VETTED, c11["id"])
        )

    print("\n== F. Generate 5 notes from the scheme row ==")
    created = client.post("/api/lesson-notes", json={
        "schemeRowId": section_id, "lessons": [1, 2, 3, 4, 5],
    })
    check(created.status_code == 200, f"create lesson notes ({created.status_code}) {created.text[:120]}")
    notes = created.json()["created"]
    check(len(notes) == 5, "exactly 5 notes created")
    check([n["lesson"] for n in notes] == [1, 2, 3, 4, 5], "lessons stored as integers 1-5")
    check(len({n["id"] for n in notes}) == 5, "one distinct document per lesson")
    check(all(n["week"] == row2["week"] for n in notes), "every note keeps the scheme week")

    titles = [n["title"] for n in notes]
    check(titles[0].endswith("Sorting by Colour"), f"Lesson 1 title ({titles[0]})")
    check(titles[1].endswith("Sorting by Shape"), f"Lesson 2 title ({titles[1]})")
    check(titles[2].endswith("Sorting by Size"), f"Lesson 3 title ({titles[2]})")
    check(titles[3].endswith("Consolidation and Practice"), f"Lesson 4 title ({titles[3]})")
    check(titles[4].endswith("Assessment and Revision"), f"Lesson 5 title ({titles[4]})")
    check(all(" - " in t for t in titles), "title is [Sub-Strand] - [Focus]")

    n1 = notes[0]
    keys = [s["key"] for s in n1["sections"]]
    check(keys == SECTION_ORDER, f"stored notes section order ({keys})")
    slo = section(n1, "slo")["body"]
    check(slo.startswith(SLO_PREFIX), f"SLO starts with the exact learner heading ({slo[:60]}…)")
    check("colour" in slo.lower(), "Lesson 1 SLO keeps the atomic colour focus")
    check("sub-strand" not in slo.lower(), "SLO never says 'sub-strand'")
    check("shape" in section(notes[1], "slo")["body"].lower(),
          "Lesson 2 SLO uses its own atomic shape focus")
    check(slo != section(notes[1], "slo")["body"], "each lesson has its own SLO")

    vocab = section(n1, "vocabulary")["data"]["items"]
    check(vocab and all({"word", "definition", "example", "source"} <= set(v) for v in vocab),
          "vocabulary has word + definition + example + source label")
    check(all(v["source"] in ("From source", "AI", "Web") for v in vocab),
          "vocabulary source is From source / AI / Web")
    check(vocab[0]["word"] == "colour", "first vocabulary word is the focus keyword")
    examples = section(n1, "examples")["data"]["items"]
    check(any("bottle tops" in str(x["text"]).lower() for x in examples),
          "examples use Kenyan context (bottle tops)")
    check(any(str(x["text"]).startswith("[Picture:") for x in examples),
          "primary examples include a [Picture: ...] placeholder")
    check(any("banana" in str(x["text"]).lower() for x in examples),
          "examples use Kenyan fruits")
    steps = section(n1, "workedExample")["data"]["steps"]
    check(len(steps) >= 4, f"worked example has numbered steps ({len(steps)})")
    practice = section(n1, "practice")["data"]["items"]
    check(len(practice) == 4 and all("question" in p and "answer" in p for p in practice),
          "primary practice has 4 questions with answers")
    check(section(n1, "remember")["body"].strip() != "", "Remember section is filled")
    check(section(n1, "footer")["body"].startswith("Source:"),
          "source footer starts with 'Source:'")

    picker2 = client.get(f"/api/plans/{pid}/sections/{section_id}/notes-picker").json()
    check(picker2["createdCount"] == 5, "picker marks all 5 notes created")
    again = client.post("/api/lesson-notes", json={
        "schemeRowId": section_id, "lessons": [1, 2],
    })
    check(again.status_code == 409, "creating the same notes again is rejected (no duplicates)")

    print("\n== G. Notes list is grouped Scheme > Week > Lesson ==")
    listed = client.get(f"/api/lesson-notes?planId={pid}").json()
    check(listed["count"] == 5, "list returns 5 documents")
    scheme = listed["schemes"][0]
    check(scheme["planTitle"] == plan["title"], "grouped under the scheme")
    week = next(w for w in scheme["weeks"] if w["week"] == row2["week"])
    check([x["lesson"] for x in week["lessons"]] == [1, 2, 3, 4, 5],
          "grouped by week, then lesson")
    check(all(x["status"] == "Draft" for x in week["lessons"]), "new notes are Draft")
    check(all(x["aiEnriched"] is False for x in week["lessons"]), "AI badge off by default")

    print("\n== H. Edits persist; SourceChunk is immutable ==")
    fingerprint_before = chunk_fingerprint(mid, c11["id"])
    what = section(n1, "whatIs")
    original_what = what["body"]
    edited = client.post(
        f"/api/lesson-notes/{n1['id']}/sections/{what['id']}/edit",
        json={"body": "Teacher wrote this in simple English."},
    )
    check(edited.status_code == 200, "edit a paragraph")
    ej = edited.json()
    ew = section(ej, "whatIs")
    check(ew["body"] == "Teacher wrote this in simple English.", "new body persists")
    check(ew["editedFromSource"] is True, "section shows 'Edited'")
    check(chunk_fingerprint(mid, c11["id"]) == fingerprint_before,
          "SourceChunk is unchanged by a notes edit")
    check(client.get(f"/api/lesson-notes/{n1['id']}").json()["sections"][3]["body"]
          == "Teacher wrote this in simple English.", "edit survives reopen")

    vocab_section = section(ej, "vocabulary")
    new_items = vocab_section["data"]["items"] + [
        {"word": "bottle top", "definition": "A small round lid.", "example": "The bottle top is red.",
         "source": "From source"}
    ]
    ved = client.post(
        f"/api/lesson-notes/{n1['id']}/sections/{vocab_section['id']}/edit",
        json={"data": {"items": new_items}},
    )
    check(ved.status_code == 200, "edit vocabulary items")
    check(any(v["word"] == "bottle top"
              for v in section(ved.json(), "vocabulary")["data"]["items"]),
          "new vocabulary item persists")
    check(chunk_fingerprint(mid, c11["id"]) == fingerprint_before,
          "SourceChunk still unchanged after vocabulary edit")

    reset = client.post(f"/api/lesson-notes/{n1['id']}/sections/{what['id']}/reset")
    check(reset.status_code == 200
          and section(reset.json(), "whatIs")["body"] == original_what,
          "[Reset to Source] restores the generated paragraph")

    print("\n== I. Versions: comment required, append-only, restore creates a new version ==")
    versions = client.get(f"/api/lesson-notes/{n1['id']}/versions").json()
    check(versions["count"] == 1 and versions["versions"][0]["versionNumber"] == 1,
          "baseline v1 exists")
    bad = client.post(f"/api/lesson-notes/{n1['id']}/versions", json={"comment": "   "})
    check(bad.status_code == 422, "empty version comment is rejected")
    saved = client.post(
        f"/api/lesson-notes/{n1['id']}/versions", json={"comment": "Simplified the vocabulary"}
    )
    check(saved.status_code == 200 and saved.json()["versionNumber"] == 2,
          "Save Version -> v2")
    check(len(client.get(f"/api/lesson-notes/{n1['id']}/versions").json()["versions"]) == 2,
          "history is append-only (2 versions)")
    diff = client.get(
        f"/api/lesson-notes/{n1['id']}/versions/{versions['versions'][0]['id']}/diff"
    )
    check(diff.status_code == 200 and "cells" in diff.json(), "version diff endpoint")
    restored = client.post(
        f"/api/lesson-notes/{n1['id']}/versions/{versions['versions'][0]['id']}/restore"
    )
    check(restored.status_code == 200, "restore endpoint")
    check(restored.json()["restoredVersion"]["versionNumber"] == 3,
          "restore appends a NEW version")
    check(len(client.get(f"/api/lesson-notes/{n1['id']}/versions").json()["versions"]) == 3,
          "no version is deleted")

    print("\n== J. AI: no key message; draft is review-only; Accept / Reject / Accept All ==")
    ai_off = client.post(f"/api/lesson-notes/{n1['id']}/ai/draft")
    check(ai_off.status_code == 422
          and ai_off.json()["detail"] == "AI enrichment needs GEMINI_API_KEY",
          "AI disabled with the exact message")

    fake = {
        "vocabulary": [
            {"word": "attribute", "definition": "A feature of an object.",
             "example": "Colour is an attribute.", "source": "AI"}
        ],
        "whatIs": "AI paragraph one.\n\nAI paragraph two.",
        "examples": ["[AI Example] Red bottle tops in a basin."],
        "workedExample": {"steps": ["Pick the objects.", "Sort by colour."]},
        "practice": [{"question": "What is colour?", "answer": "How something looks."}],
        "remember": "Sort by one attribute at a time.",
    }
    original_draft = lns.notes_enrich.draft_notes
    lns.notes_enrich.draft_notes = lambda ctx: fake  # type: ignore[assignment]
    os.environ["GEMINI_API_KEY"] = "test-key-for-phase5"
    try:
        note_before = client.get(f"/api/lesson-notes/{n1['id']}").json()
        body_before = section(note_before, "whatIs")["body"]
        drafted = client.post(f"/api/lesson-notes/{n1['id']}/ai/draft")
        check(drafted.status_code == 200, "AI draft endpoint runs with a key")
        dj = drafted.json()
        check(bool(section(dj, "whatIs")["aiDraft"]), "AI draft is stored separately")
        check(section(dj, "whatIs")["body"] == body_before,
              "AI does not merge into the lesson notes before review")
        check(section(dj, "whatIs")["aiDraft"] == fake["whatIs"], "AI draft text matches")
        check(section(dj, "vocabulary")["aiData"]["items"][0]["source"] == "AI",
              "AI vocabulary is labelled AI")

        rejected = client.post(
            f"/api/lesson-notes/{n1['id']}/sections/{section(dj, 'whatIs')['id']}/edit",
            json={"rejectAi": True},
        )
        check(rejected.status_code == 200, "AI reject endpoint")
        rj = rejected.json()
        check(section(rj, "whatIs")["body"] == "" and not section(rj, "whatIs")["aiDraft"],
              "Reject leaves the section empty")

        accepted = client.post(
            f"/api/lesson-notes/{n1['id']}/sections/{section(rj, 'vocabulary')['id']}/edit",
            json={"acceptAi": True},
        )
        check(accepted.status_code == 200, "AI accept per section")
        aj = accepted.json()
        check(section(aj, "vocabulary")["aiAssisted"] is True, "accepted section is AI-assisted")
        check(any(v["word"] == "attribute"
                  for v in section(aj, "vocabulary")["data"]["items"]),
              "accepted AI vocabulary is merged")

        all_ok = client.post(f"/api/lesson-notes/{n1['id']}/ai/accept-all")
        check(all_ok.status_code == 200, "Accept All endpoint")
        fj = all_ok.json()
        check(fj["acceptedSections"] >= 1, "Accept All accepts the remaining drafts")
        check(fj["aiEnriched"] is True and fj["aiProvider"] == "gemini"
              and bool(fj["aiTimestamp"]), "ai_enriched / ai_provider / ai_timestamp logged")
        check("AI-enriched on" in section(fj, "footer")["body"]
              and "with Gemini" in section(fj, "footer")["body"],
              "footer records the AI enrichment date + provider")
    finally:
        lns.notes_enrich.draft_notes = original_draft  # type: ignore[assignment]
        os.environ["GEMINI_API_KEY"] = ""

    print("\n== K. Web: teacher-initiated, top 3, explicit insert, labelled URL ==")
    examples_before = len(section(
        client.get(f"/api/lesson-notes/{n1['id']}").json(), "examples"
    )["data"]["items"])
    web = client.get(f"/api/lesson-notes/{n1['id']}/search-examples?q=sorting bottle tops")
    check(web.status_code == 200, "search-examples endpoint")
    results = web.json()["results"]
    check(all({"title", "url", "snippet"} <= set(r) for r in results),
          "top 3 search returns only verified real results")
    check(len(results) == 0, "top 3 search returns no invented results when AI is unavailable")
    examples_after_search = len(section(
        client.get(f"/api/lesson-notes/{n1['id']}").json(), "examples"
    )["data"]["items"])
    check(examples_after_search == examples_before,
          "searching never auto-inserts an example")

    if results:
        target = results[0]
        inserted = client.post(
            f"/api/lesson-notes/{n1['id']}/web-examples",
            json={"title": target["title"], "url": target["url"], "snippet": target["snippet"]},
        )
        check(inserted.status_code == 200, "[Insert as Web Example] endpoint")
        ij = inserted.json()
        web_items = [x for x in section(ij, "examples")["data"]["items"]
                     if x.get("source") == "Web"]
        check(bool(web_items) and web_items[0]["text"].startswith(f"[Web Example - {target['url']}]"),
              "inserted example is labelled with the source URL")
        check(target["url"] in section(ij, "footer")["body"],
              "footer lists the web example URL")

    sourced = client.post(
        f"/api/lesson-notes/{n1['id']}/sources",
        json={"kind": "teacher", "title": "KICD Grade 1 Teacher Guide", "text": "Local activity"},
    )
    check(sourced.status_code == 200, "[Add My Source] endpoint")
    check("Teacher source: KICD Grade 1 Teacher Guide" in section(sourced.json(), "footer")["body"],
          "teacher source is shown in the footer")

    print("\n== L. Generate from a Lesson Plan ==")
    row3 = plan["sections"][2]
    lp_res = client.post("/api/lesson-plans", json={
        "schemeRowId": row3["id"], "lessons": [1],
    })
    check(lp_res.status_code == 200, "create one lesson plan")
    lp = lp_res.json()["created"][0]
    from_plan = client.post("/api/lesson-notes", json={"lessonPlanId": lp["id"]})
    check(from_plan.status_code == 200, "generate notes from a Lesson Plan")
    np = from_plan.json()["created"][0]
    check(np["lessonPlanId"] == lp["id"] and np["lesson"] == 1,
          "notes keep the Lesson Plan link and lesson number")
    check(np["focus"] == lp["focus"], "notes use the same focus as the Lesson Plan")
    check(lp["focus"].lower().split()[0] in section(np, "slo")["body"].lower(),
          "notes SLO reuses the Lesson Plan's atomic focus verbatim")
    dup_plan = client.post("/api/lesson-notes", json={"lessonPlanId": lp["id"]})
    check(dup_plan.status_code == 409, "one notes document per Lesson Plan lesson")

    print("\n== M. Grade 8 uses JSS notes: longer, 5 practice, diagrams ==")
    jss_plan = client.post("/api/plans", json={
        "type": "scheme", "institution": "Nairobi Junior School", "grade": "Grade 8",
        "subject": "Mathematics", "term": "Term 1", "year": "2025",
        "lessonsPerWeek": 5, "totalWeeks": 13, "sourceChunkIds": [c11["id"]],
    })
    check(jss_plan.status_code == 200, "generate a Grade 8 scheme")
    jpid = jss_plan.json()["id"]
    jrow = jss_plan.json()["sections"][0]
    jpicker = client.get(
        f"/api/plans/{jpid}/sections/{jrow['id']}/notes-picker"
    ).json()
    check(jpicker["templateVersion"] == "cbe-lesson-notes-jss-v1"
          and jpicker["gradeBand"] == "jss", "Grade 8 picker auto-selects JSS notes")
    jcreated = client.post("/api/lesson-notes", json={
        "schemeRowId": jrow["id"], "lessons": [1],
    })
    check(jcreated.status_code == 200, "create Grade 8 notes")
    jn = jcreated.json()["created"][0]
    check(jn["templateVersion"] == "cbe-lesson-notes-jss-v1"
          and jn["gradeBand"] == "jss", "Grade 8 notes use the JSS template")
    check(len(section(jn, "practice")["data"]["items"]) == 5,
          "JSS notes have 5 practice questions")
    check(section(jn, "whatIs")["body"].count("\n\n") >= 3,
          "JSS explanation is longer")
    check(any(str(x["text"]).startswith("[Diagram:") for x in section(jn, "examples")["data"]["items"]),
          "JSS examples include a diagram description")
    check(not any(str(x["text"]).startswith("[Picture:") for x in section(jn, "examples")["data"]["items"]),
          "JSS never fakes pictures")

    print("\n== N. Mark Final ==")
    final = client.post(f"/api/lesson-notes/{n1['id']}/status", json={"status": "Final"})
    check(final.status_code == 200 and final.json()["status"] == "Final",
          "Mark Final sets status Final")
    check(any(v["kind"] == "final" for v in
              client.get(f"/api/lesson-notes/{n1['id']}/versions").json()["versions"]),
          "Mark Final appends a final version")
    reopened = client.post(f"/api/lesson-notes/{n1['id']}/status", json={"status": "Draft"})
    check(reopened.status_code == 200 and reopened.json()["status"] == "Draft",
          "Reopen as Draft")

    print("\n== O. PDF: portrait A4, learner-friendly, answers hidden by default ==")
    note_now = client.get(f"/api/lesson-notes/{n1['id']}").json()
    practice_section = section(note_now, "practice")
    marker = "ANSWER-MARKER-42"
    items = [dict(x) for x in practice_section["data"]["items"]]
    items[0]["answer"] = marker
    client.post(
        f"/api/lesson-notes/{n1['id']}/sections/{practice_section['id']}/edit",
        json={"data": {"items": items}},
    )
    note_now = client.get(f"/api/lesson-notes/{n1['id']}").json()

    hidden = client.get(f"/api/lesson-notes/{n1['id']}/export.pdf")
    check(hidden.status_code == 200 and hidden.headers["content-type"] == "application/pdf",
          "export PDF endpoint")
    hdoc = fitz.open(stream=hidden.content, filetype="pdf")
    check(hdoc[0].rect.height > hdoc[0].rect.width, "notes PDF is portrait A4")
    htext = "".join(p.get_text() for p in hdoc)
    check("LESSON NOTES" in htext, "PDF has the learner notes header")
    check(note_now["title"] in htext or "Sorting by Colour" in htext, "PDF prints the notes title")
    check("[Picture:" in htext, "primary PDF keeps picture placeholders")
    check("Try It Yourself" in htext, "PDF prints Try It Yourself")
    check(marker not in htext, "practice answers are hidden by default")
    hdoc.close()

    shown = client.get(f"/api/lesson-notes/{n1['id']}/export.pdf?answers=1")
    sdoc = fitz.open(stream=shown.content, filetype="pdf")
    stext = "".join(p.get_text() for p in sdoc)
    check(marker in stext, "?answers=1 shows the practice answers")
    sdoc.close()

    direct = render_notes_pdf(note_now, show_answers=False)
    ddoc = fitz.open(stream=direct, filetype="pdf")
    check(ddoc[0].rect.height > ddoc[0].rect.width, "render_notes_pdf is portrait")
    ddoc.close()

    print("\n" + "=" * 64)
    if failures:
        print(f"RESULT: {len(failures)} FAILURE(S)")
        for f in failures:
            print("  -", f)
        return 1
    print("RESULT: ALL PHASE 5 ACCEPTANCE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
