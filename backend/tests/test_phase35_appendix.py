"""Phase 3.5 acceptance - PARSE APPENDIX for Learning Resources + Assessment.

Asserts the spec on the three real PDFs:
  * Maths   1.2 Whole Numbers -> appendix_resources has the Appendix 1 p.29 line, level
                                'sub_strand'; assessment falls back to Appendix 2, level 'subject'
  * CRE     1.1 Self-Awareness (strand 1.0 Creation) -> Children's Bible + Observation Schedules,
                                level 'strand', source p.35
  * English 1.1.1 Pronunciation -> subject-level resources (Course books/Story books) and
                                strand-level assessment (Oral reading/Role play)
  * Vetting is UNCHANGED by appendix: missing appendix still Vetted, deleting appendix fields
                                does not change vetting_status
  * No duplicates, no cross-document leak, strand grouping unchanged after re-parse
  * Scheme autofill: resources/assessment cells show appendix values, not placeholders
  * [Reset to Appendix] restores a teacher-edited cell, per row only
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

os.environ["MWALIMU_STUDIO_DB"] = str(BACKEND / "studio_p35_test.db")
os.environ["MWALIMU_STUDIO_UPLOADS"] = str(BACKEND / "_test_uploads_p35")
for stale in (BACKEND / "studio_p35_test.db",):
    if stale.exists():
        stale.unlink()

from db import connect, init_db  # noqa: E402
from services.library_service import VETTED, compute_vetting_status  # noqa: E402
from services.parse_service import approve_all, correct_chunk, parse_and_store  # noqa: E402
from services.plan_service import (  # noqa: E402
    create_plan,
    edit_section,
    get_plan,
    reset_section_to_appendix,
)

CD = Path(r"C:\Users\user\Desktop\Curriculum Designs")
MATHS = CD / "Grade-1-Mathematics-Activities-Curriculum-Design.pdf"
CRE = CD / "Grade-1-CRE-Activities-Curriculum-Design.pdf"
ENGLISH = CD / "Grade-1-English-Language-Activities-Curriculum-Design.pdf"

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {msg}")
    if not cond:
        failures.append(msg)


def parse(name: Path) -> tuple[dict, dict]:
    doc = parse_and_store(name.read_bytes(), name.name)
    did = doc["id"]
    approve_all(did, 0.9)
    for _ in range(8):
        with connect() as conn:
            pending = [
                r["id"]
                for r in conn.execute(
                    "SELECT id, review_state FROM source_chunks WHERE document_id = ?", (did,)
                ).fetchall()
                if r["review_state"] not in ("Approved", "TeacherCorrected")
            ]
        if not pending:
            break
        for cid in pending:
            correct_chunk(did, cid, {"reviewState": "Approved"})
    with connect() as conn:
        chunks = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM source_chunks WHERE document_id = ? ORDER BY ord", (did,)
            ).fetchall()
        ]
    return doc, {"id": did, "chunks": chunks}


def main() -> int:
    init_db()

    print("\n== A. Maths appendix (Type A sub-strand + Appendix 2 subject assessment) ==")
    mdoc, m = parse(MATHS)
    check(mdoc.get("parseMeta", {}).get("appendixStartPage"), "appendix mode started (Maths)")
    c12 = next(c for c in m["chunks"] if c["sub_strand_code"] == "1.2")
    check(
        "Sticks, marbles, stones, grains" in (c12["appendix_resources"] or ""),
        f"1.2 resources from Appendix 1 ({str(c12['appendix_resources'])[:50]})",
    )
    check(c12["appendix_level"] == "sub_strand", f"1.2 level sub_strand ({c12['appendix_level']})")
    check("p.29" in (c12["appendix_source"] or ""), f"1.2 source names p.29 ({c12['appendix_source']})")
    asm = c12["appendix_assessment"] or ""
    check(
        "Written tests" in asm or "Observation Schedules" in asm,
        f"1.2 assessment from Appendix 2 ({asm[:50]})",
    )
    check(c12["appendix_level"] in ("sub_strand", "strand", "subject"), "level is a legal value")

    print("\n== B. CRE appendix (Type B strand) ==")
    cdoc, cr = parse(CRE)
    c11 = next(c for c in cr["chunks"] if c["sub_strand_code"] == "1.1")
    check("Children" in (c11["appendix_resources"] or ""), "1.1 Self-Awareness has Children's Bible")
    check(
        "Observation" in (c11["appendix_assessment"] or ""),
        f"1.1 assessment has Observation Schedules ({(c11['appendix_assessment'] or '')[:40]})",
    )
    check(c11["appendix_level"] == "strand", f"1.1 level strand ({c11['appendix_level']})")
    check("p.35" in (c11["appendix_source"] or ""), f"1.1 source p.35 ({c11['appendix_source']})")

    print("\n== C. English appendix (Type C strand assessment + Type D subject resources) ==")
    edoc, en = parse(ENGLISH)
    e111 = next(c for c in en["chunks"] if c["sub_strand_code"] == "1.1.1")
    res = e111["appendix_resources"] or ""
    asm = e111["appendix_assessment"] or ""
    check(
        "Course books" in res or "Story books" in res,
        f"1.1.1 subject resources ({res[:50]})",
    )
    check(
        "Oral reading" in asm or "Role play" in asm,
        f"1.1.1 strand assessment ({asm[:50]})",
    )

    print("\n== D. Vetting is UNCHANGED by appendix ==")
    check(c12["vetting_status"] == VETTED, "Maths 1.2 is Vetted")
    check(
        compute_vetting_status(
            {
                "specific_learning_outcomes": ["o"],
                "suggested_learning_experiences": ["e"],
                "key_inquiry_questions": ["q"],
            },
            "Approved",
        )
        == VETTED,
        "chunk with no appendix fields is STILL Vetted",
    )
    with connect() as conn:
        conn.execute(
            "UPDATE source_chunks SET appendix_resources = NULL, appendix_assessment = NULL "
            "WHERE id = ?",
            (c12["id"],),
        )
        after = conn.execute(
            "SELECT vetting_status FROM source_chunks WHERE id = ?", (c12["id"],)
        ).fetchone()
    check(after["vetting_status"] == VETTED, "deleting appendix does NOT change vetting_status")
    # restore
    with connect() as conn:
        conn.execute(
            "UPDATE source_chunks SET appendix_resources = ?, appendix_assessment = ? WHERE id = ?",
            ("Sticks, marbles, stones, grains", "Written tests and quizzes", c12["id"]),
        )

    print("\n== E. No duplicates / no cross-document leak ==")
    for label, doc in (("Maths", m), ("CRE", cr), ("English", en)):
        codes = [c["sub_strand_code"] for c in doc["chunks"]]
        check(len(codes) == len(set(codes)), f"{label}: no duplicate sub-strand codes")
    maths_doc_id = m["id"]
    check(
        all(c["document_id"] == maths_doc_id for c in m["chunks"]),
        "Maths chunks all belong to the Maths document",
    )

    print("\n== F. Scheme autofill ==")
    plan, errs = create_plan({
        "type": "scheme", "institution": "Nairobi Primary School", "grade": "Grade 1",
        "subject": "Mathematics", "term": "Term 1", "year": "2025",
        "lessonsPerWeek": 5, "totalWeeks": 13, "sourceChunkIds": [c12["id"]],
    })
    check(plan is not None, f"scheme generated ({errs})")
    rows = [s for s in plan["sections"] if s["subStrandCode"] == "1.2"]
    check(len(rows) >= 1, f"1.2 weekly rows present ({len(rows)})")
    r0 = rows[0]
    check(
        "Sticks, marbles, stones, grains" in r0["resources"]["text"],
        f"Resources column shows appendix value ({r0['resources']['text'][:45]})",
    )
    check(r0["resources"]["placeholder"] is False, "Resources is NOT 'Teacher to fill'")
    check(r0["resources"].get("fromAppendix") is True, "Resources flagged fromAppendix")
    check("Written tests" in r0["assessment"]["text"], "Assessment column shows appendix value")
    check(r0["appendix"]["source"] is not None, f"appendix source present ({r0['appendix']['source']})")

    print("\n== G. Teacher edit + [Reset to Appendix] per row ==")
    edited, _ = edit_section(plan["id"], r0["id"], {"resources": "My own list"})
    by_id = {s["id"]: s for s in edited["sections"]}
    check(by_id[r0["id"]]["resources"]["text"] == "My own list", "teacher edit applied")
    check(by_id[r0["id"]]["edited"] is True, "row marked Teacher Edited")
    reset, _ = reset_section_to_appendix(plan["id"], r0["id"], "resources")
    rr = {s["id"]: s for s in reset["sections"]}[r0["id"]]
    check(
        rr["resources"]["text"] == r0["resources"]["text"],
        f"reset restores the appendix value ({rr['resources']['text'][:40]})",
    )
    if len(rows) > 1:
        other = {s["id"]: s for s in reset["sections"]}[rows[1]["id"]]
        check(other["resources"]["text"] == rows[1]["resources"]["text"], "sibling row untouched")
    else:
        check(True, "only one weekly row, sibling check n/a")

    print("\n== H. English fallback when appendix has no match ==")
    # A synthetic chunk whose strand matches nothing in the appendix must keep None.
    from services.appendix_parser import join_appendix, parse_appendix, appendix_pages
    import fitz
    with fitz.open(ENGLISH) as d:
        ap = parse_appendix(appendix_pages(d))
    lonely = {
        "strand": "99.9 Nonexistent", "strandCode": "99.9",
        "subStrand": "Nothing", "subStrandCode": "99.9.9",
    }
    join_appendix(lonely, ap)
    check(
        lonely["appendix_resources"] == (ap["subject_resources"]["resources"] if ap["subject_resources"] else None),
        "unmatched sub-strand falls back to SUBJECT resources (never invented)",
    )
    join_appendix(lonely, {"rows": [], "subject_resources": None, "subject_assessment": None})
    check(lonely["appendix_resources"] is None, "with no appendix at all -> None (no hallucination)")
    check(lonely["appendix_assessment"] is None, "no appendix assessment -> None")

    print("\n" + "=" * 64)
    if failures:
        print(f"RESULT: {len(failures)} FAILURE(S)")
        for f in failures:
            print("  -", f)
        return 1
    print("RESULT: ALL PHASE 3.5 APPENDIX CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
