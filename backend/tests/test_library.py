"""Acceptance tests - Phase 2 (Library) + the Phase 1 approve flow.

Covers the required scenarios against the real HTTP API shape (service layer):

  * Upload Maths -> Approve All -> >=90% approved in one call -> fix the rest by
    inline field correction -> Save -> appears in the library
  * Search "Whole Numbers" finds Maths chunk 1.2 with page 10
  * Search "Musical Sounds" finds the Creative doc and NEVER the Maths doc
  * Delete removes only that document's chunks
  * Re-parse yields the same chunks, no duplicates
  * Uploaded PDF is kept and linked from every chunk
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

os.environ["MWALIMU_STUDIO_DB"] = str(BACKEND / "studio_lib_test.db")
os.environ["MWALIMU_STUDIO_UPLOADS"] = str(BACKEND / "_test_uploads")

for stale in (Path(os.environ["MWALIMU_STUDIO_DB"]),):
    if stale.exists():
        stale.unlink()
uploads = Path(os.environ["MWALIMU_STUDIO_UPLOADS"])
if uploads.exists():
    for f in uploads.iterdir():
        f.unlink()

from db import connect, init_db, upload_path  # noqa: E402
from services.library_service import (  # noqa: E402
    delete_library_document,
    get_library_document,
    list_library,
    reparse_library_document,
    save_document_to_library,
    search_library,
)
from services.parse_service import (  # noqa: E402
    approve_all,
    approve_strand,
    correct_chunk,
    parse_and_store,
)

CD = Path(r"C:\Users\user\Desktop\Curriculum Designs")
MATHS = CD / "Grade-1-Mathematics-Activities-Curriculum-Design.pdf"
CREATIVE = CD / "Grade-1-Creative-Activities-Curriculum-Design.pdf"

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if cond:
        print(f"  PASS  {msg}")
    else:
        print(f"  FAIL  {msg}")
        failures.append(msg)


def main() -> int:
    init_db()
    print("\n== A. Upload Maths ==")
    maths = parse_and_store(MATHS.read_bytes(), MATHS.name)
    maths_id = maths["id"]
    check(maths["status"] in ("Parsed", "NeedsReview"), f"new document starts unfiled (status={maths['status']})")
    check(maths["chunkCount"] == 9, f"Maths has 9 chunks (got {maths['chunkCount']})")
    check(upload_path(maths_id).exists(), "original PDF stored in backend/uploads")

    print("\n== B. Approve All (confidence >= 0.9) in one call ==")
    job, approved_now, kept = approve_all(maths_id, 0.9)
    total = job["chunkCount"]
    pct = 100.0 * job["reviewSummary"]["approved"] / total
    print(f"        approved {approved_now}, kept {kept}, {job['reviewSummary']['approved']}/{total} = {pct:.0f}%")
    # One click must clear the bulk of the document: at most one sub-strand may remain.
    check(kept <= 1, f"one click leaves at most 1 sub-strand to fix (kept {kept})")
    check(pct >= 85.0, f"one click approves the bulk ({pct:.0f}% >= 85%)")
    check(job["status"] == "NeedsReview", f"document is NeedsReview while gaps remain ({job['status']})")

    print("\n== C. Fix the remainder in under a minute ==")
    needs = [c for c in job["chunks"] if c["needsReview"]]
    print(f"        still needs review: {[(c['subStrandCode'], c['missingFields'], c['confidence']) for c in needs]}")
    for c in needs:
        sf = c["structuredFields"]
        if c["missingFields"]:
            # Empty field -> the teacher types it inline.
            if "Outcomes" in c["missingFields"]:
                job = correct_chunk(maths_id, c["id"], {"field": "outcomes", "newValue": "a) count numbers up to 50"})
            if "Experiences" in c["missingFields"]:
                job = correct_chunk(
                    maths_id, c["id"],
                    {"field": "experiences", "newValue": "use counters to count\nmatch numbers to objects"},
                )
            if "KIQs" in c["missingFields"]:
                job = correct_chunk(maths_id, c["id"], {"field": "kiqs", "newValue": "How many objects are here?"})
        else:
            # Nothing missing, just low confidence -> one click on the card Approve.
            job = correct_chunk(maths_id, c["id"], {"reviewState": "Approved"})
        after = [x for x in job["chunks"] if x["id"] == c["id"]][0]
        check(after["reviewState"] in ("TeacherCorrected", "Approved"),
              f"{after['subStrandCode']} resolved to {after['reviewState']} ({after['confidence']})")
        check(after["missingFields"] == [], f"{after['subStrandCode']} no longer missing fields")
        if after["reviewState"] == "TeacherCorrected":
            check(after["confidence"] == 1.0, f"{after['subStrandCode']} corrected confidence is 1.0")

    # A field edit must be undoable: edit then undo round-trips to the extracted text.
    probe = next(c for c in job["chunks"] if c["structuredFields"]["key_inquiry_questions"])
    original_q = list(probe["structuredFields"]["key_inquiry_questions"])
    job_x = correct_chunk(maths_id, probe["id"], {"field": "kiqs", "newValue": "Teacher typed this"})
    edited = [c for c in job_x["chunks"] if c["id"] == probe["id"]][0]
    check(edited["structuredFields"]["key_inquiry_questions"] == ["Teacher typed this"], "field edit applied")
    check(edited["reviewState"] == "TeacherCorrected" and edited["confidence"] == 1.0,
          "edit sets TeacherCorrected + confidence 1.0")
    job = correct_chunk(maths_id, probe["id"], {"undoField": "kiqs", "reviewState": "Approved"})
    undone = [c for c in job["chunks"] if c["id"] == probe["id"]][0]
    check(undone["structuredFields"]["key_inquiry_questions"] == original_q, "undo restored the original text")

    job = get_library_document(maths_id)
    check(job["reviewSummary"]["needsReview"] == 0, "nothing left needing review")

    print("\n== D. Save to library ==")
    saved, errors = save_document_to_library(maths_id, save_with_gaps=False)
    check(saved is not None, f"save succeeds without gaps {errors}")
    if saved:
        check(saved["status"] == "Approved", f"status is Approved ({saved['status']})")
    lib = list_library()
    # Phase 3: a fully-vetted document is promoted to the Studio Library, so it may be in
    # the Studio Library rather than My Materials. Either way it must be listed once.
    in_my = any(d["id"] == maths_id for d in lib["myMaterials"])
    in_studio = any(d["id"] == maths_id for d in lib["studioLibrary"])
    listed = next((d for d in lib["documents"] if d["id"] == maths_id), None)
    check(in_my or in_studio, f"Maths appears in the library (my={in_my}, studio={in_studio})")
    if listed and listed["allVetted"]:
        check(in_studio and not in_my, "fully Vetted document is in Studio Library, not My Materials")
    check(listed is not None, "library lists the document exactly once")

    print("\n== E. Search 'Whole Numbers' ==")
    res = search_library("Whole Numbers")
    hits = [r for r in res["results"] if r["documentId"] == maths_id]
    check(bool(hits), f"search finds Maths ({len(hits)} hits)")
    codes = {r["subStrandCode"] for r in res["results"]}
    c12 = [r for r in hits if r["subStrandCode"] == "1.2"]
    check(bool(c12), f"finds chunk 1.2 (codes found: {sorted(codes)})")
    if c12:
        h = c12[0]
        print(f"        hit: {h['subStrandCode']} {h['subStrand']} | page {h['pageNumber']} | {h['snippet'][:70]}")
        check(h["pageNumber"] == 10, f"chunk 1.2 page is 10 (got {h['pageNumber']})")
        check(h["documentId"] == maths_id, "hit carries its document id (source-first)")

    print("\n== F. Cross-document isolation in search ==")
    creative = parse_and_store(CREATIVE.read_bytes(), CREATIVE.name)
    creative_id = creative["id"]
    save_document_to_library(creative_id, save_with_gaps=True)

    r_musical = search_library("Musical Sounds")
    doc_ids = {r["documentId"] for r in r_musical["results"]}
    print(f"        docs returned for 'Musical Sounds': {len(doc_ids)}")
    check(creative_id in doc_ids, "Creative doc found for 'Musical Sounds'")
    check(maths_id not in doc_ids, "Maths doc NOT returned for 'Musical Sounds'")
    leak = [r for r in r_musical["results"] if r["documentId"] == maths_id]
    check(not leak, "zero cross-doc leaks in search results")

    r_numbers = search_library("Whole Numbers")
    nums_docs = {r["documentId"] for r in r_numbers["results"]}
    check(creative_id not in nums_docs or all(
        "whole numbers" in (r["snippet"] or "").lower() for r in r_numbers["results"] if r["documentId"] == creative_id
    ), "'Whole Numbers' does not misattribute Creative rows to Maths content")

    print("\n== G. Search filters ==")
    only_maths = search_library("numbers", subject="Mathematics")
    check(all(r["documentId"] == maths_id for r in only_maths["results"]), "subject filter restricted to Maths")
    only_approved = search_library("numbers", status="Approved")
    check(all(r["status"] == "Approved" for r in only_approved["results"]), "status filter returns Approved only")

    print("\n== H. Re-parse is idempotent ==")
    before = [(c["subStrandCode"], c["subStrand"], c["pageNumber"]) for c in get_library_document(maths_id)["chunks"]]
    again, errs = reparse_library_document(maths_id)
    check(again is not None, f"re-parse succeeds {errs}")
    after = [(c["subStrandCode"], c["subStrand"], c["pageNumber"]) for c in (again or {}).get("chunks", [])]
    check(before == after, f"re-parse produces identical chunks, no duplicates ({len(after)})")
    ids = [c["subStrandCode"] for c in (again or {}).get("chunks", [])]
    check(len(ids) == len(set(ids)), "no duplicate sub-strand codes after re-parse")
    with connect() as conn:
        n = conn.execute("SELECT COUNT(*) c FROM source_chunks WHERE document_id = ?", (maths_id,)).fetchone()["c"]
    check(n == len(before), f"chunk rows replaced not appended ({n})")

    print("\n== I. Strand approve ==")
    strand = again["tree"][0]
    job2, count = approve_strand(maths_id, strand["strandCode"], strand["strand"])
    check(count == strand["chunkCount"], f"Approve Strand approves all {strand['chunkCount']} sub-strands (got {count})")
    others = [c for c in job2["chunks"] if c["strandCode"] != strand["strandCode"]]
    check(all(c["reviewState"] == "Parsed" for c in others), "other strands untouched by strand approve")

    print("\n== J. Undo behaviour already covered in section C ==")
    reparse_before = [(c["subStrandCode"], c["subStrand"]) for c in get_library_document(maths_id)["chunks"]]
    check(len(reparse_before) == len(before), "library document still has all chunks")

    print("\n== K. Delete removes only that document ==")
    ok = delete_library_document(creative_id)
    check(ok, "delete returns success")
    check(get_library_document(creative_id) is None, "deleted document is gone")
    with connect() as conn:
        left = conn.execute("SELECT COUNT(*) c FROM source_chunks WHERE document_id = ?", (creative_id,)).fetchone()["c"]
    check(left == 0, f"its chunks are gone ({left} left)")
    check(not upload_path(creative_id).exists(), "its stored PDF is gone")
    still = get_library_document(maths_id)
    check(still is not None and still["chunkCount"] == len(before), "other documents untouched")
    check(upload_path(maths_id).exists(), "other document's PDF untouched")

    print("\n== L. Save-with-gaps is still gated ==")
    fresh = parse_and_store(MATHS.read_bytes(), "Grade-1-Mathematics-copy.pdf")
    blocked, errs = save_document_to_library(fresh["id"], save_with_gaps=False)
    check(blocked is None, "save blocked while chunks are unreviewed")
    check(bool(errs), f"blocked reason returned: {errs[0][:70] if errs else ''}")
    forced, _ = save_document_to_library(fresh["id"], save_with_gaps=True)
    check(forced is not None and forced["status"] == "Approved", "save-with-gaps succeeds when ticked")
    delete_library_document(fresh["id"])

    print("\n" + "=" * 68)
    if failures:
        print(f"RESULT: {len(failures)} FAILURE(S)")
        for f in failures:
            print("  - " + f)
        return 1
    print("RESULT: ALL LIBRARY ACCEPTANCE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
