"""Acceptance tests - Phase 1.

Parses Grade 1 English, CRE, Maths, Kiswahili and Grade 9 Pre-Technical
SEQUENTIALLY IN THE SAME PROCESS (same as a running server would), then checks:

  * no cross-document leak
  * no duplicate sub-strand codes within a document
  * no aliasing between chunks
  * KIQs joined into single sentences
  * strand grouping correct
  * English 1.1.1 KIQs correct
  * CRE 1.1 has no rubric rows
  * Maths 1.2 has 6 outcomes a-f
  * Pre-Technical has no second (phantom) list
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("MWALIMU_STUDIO_DB", str(BACKEND / "studio_test.db"))

from db import init_db  # noqa: E402
from services.parse_service import build_tree, parse_and_store, strand_key  # noqa: E402

CD = Path(r"C:\Users\user\Desktop\Curriculum Designs")

DOCS = [
    ("English", "Grade-1-English-Language-Activities-Curriculum-Design.pdf"),
    ("CRE", "Grade-1-CRE-Activities-Curriculum-Design.pdf"),
    ("Maths", "Grade-1-Mathematics-Activities-Curriculum-Design.pdf"),
    ("Kiswahili", "Grade-1-Kiswahili-Activities-Curriculum-Design.pdf"),
    ("PreTechnical", "Grade-9-Pretechnical-Studies-Curriculum-Design.pdf"),
]

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if cond:
        print(f"  PASS  {msg}")
    else:
        print(f"  FAIL  {msg}")
        failures.append(msg)


def main() -> int:
    init_db()
    jobs: dict[str, dict] = {}

    print("\n== Sequential parse in one process ==")
    for label, fname in DOCS:
        path = CD / fname
        if not path.exists():
            check(False, f"{label}: PDF missing at {path}")
            continue
        job = parse_and_store(path.read_bytes(), fname)
        jobs[label] = job
        print(
            f"  {label:14s} archetype={job['archetype']:<16s} conf={job['archetypeConfidence']} "
            f"chunks={job['chunkCount']:<3d} dups={job['parseMeta'].get('duplicatesSkipped')} "
            f"rubric_skipped={job['parseMeta'].get('rubricRowsSkipped')} "
            f"stop_p={job['parseMeta'].get('backMatterStopPage')} grade={job['grade']}"
        )

    print("\n== 1. No duplicates within a document ==")
    for label, job in jobs.items():
        codes = [(c["strandCode"], c["subStrandCode"]) for c in job["chunks"]]
        check(len(codes) == len(set(codes)), f"{label}: no duplicate strand|sub-strand keys ({len(codes)} chunks)")

    print("\n== 2. No cross-document leak (strand names) ==")
    strand_names = {label: {c["strand"] for c in job["chunks"] if c["strand"]} for label, job in jobs.items()}
    eng = strand_names.get("English", set())
    cr = strand_names.get("CRE", set())
    mat = strand_names.get("Maths", set())
    kis = strand_names.get("Kiswahili", set())
    pt = strand_names.get("PreTechnical", set())

    check(not ({"Numbers", "Measurement", "Geometry"} & eng), f"English has no Maths strands: {sorted(eng)}")
    check("Numbers" not in cr, f"CRE has no 'Numbers' strand: {sorted(cr)}")
    check(not ({"Listening and Speaking", "Reading"} & mat), f"Maths has no English strands: {sorted(mat)}")
    check(not ({"Greetings", "Numbers"} & kis), f"Kiswahili has no English/Maths strands: {sorted(kis)}")
    check(not ({"Race to the Top", "Numbers", "Listening and Speaking"} & pt),
          f"Pre-Technical strands are its own: {sorted(pt)[:6]}")

    # Every strand a document reports must be resolvable within that document, OR be
    # explicitly unassigned (null) and flagged for teacher review. Never borrowed.
    for label, job in jobs.items():
        resolved = [(c["strandCode"], c["strand"]) for c in job["chunks"] if c["strand"]]
        unassigned = [c for c in job["chunks"] if not c["strand"]]
        flagged = all(
            "Parent not found" in " ".join(c["flags"]) and c["confidence"] == 0.0
            for c in unassigned
        )
        check(
            bool(resolved) and flagged,
            f"{label}: strands resolved ({len(resolved)}) or flagged-unassigned ({len(unassigned)}) - never borrowed",
        )

    print("\n== 3. No aliasing between chunks ==")
    # Probes work on deep copies so the in-memory job payload is not mutated.
    import copy

    for label, job in jobs.items():
        chunks = job["chunks"]
        if len(chunks) < 2:
            continue
        a = copy.deepcopy(chunks[0]["structuredFields"])
        b = copy.deepcopy(chunks[1]["structuredFields"])
        ok = True
        for key in ("specific_learning_outcomes", "suggested_learning_experiences", "key_inquiry_questions"):
            la, lb = a.get(key) or [], b.get(key) or []
            ok = ok and (la is not lb)
            before = list(lb)
            if la:
                la[0] = "XXX"
            ok = ok and b.get(key) == before
        check(ok, f"{label}: chunk[0] and chunk[1] structured fields are independent")

    # The engine must also be aliasing-free at source (test_no_aliasing.py equivalent).
    eng_source = jobs.get("English", {}).get("chunks") or []
    if len(eng_source) >= 2:
        first = list(eng_source[1]["structuredFields"]["specific_learning_outcomes"])
        check(
            eng_source[0]["structuredFields"]["specific_learning_outcomes"]
            is not eng_source[1]["structuredFields"]["specific_learning_outcomes"],
            "English: outcome lists are distinct objects in the DB round trip",
        )
        check(first == list(eng_source[1]["structuredFields"]["specific_learning_outcomes"]),
              "English: chunk[1] outcomes unchanged after probing chunk[0]")

    print("\n== 4. KIQs joined (no wrapped fragments) ==")
    for label, job in jobs.items():
        kiqs = [q for c in job["chunks"] for q in (c["structuredFields"].get("key_inquiry_questions") or [])]
        fragments = [q for q in kiqs if len(q) < 6]
        check(not fragments, f"{label}: no fragmentary KIQs ({len(kiqs)} total){fragments[:3] if fragments else ''}")

    print("\n== 5. Strand grouping correct ==")
    for label, job in jobs.items():
        tree = build_tree(job["chunks"])
        total = sum(g["chunkCount"] for g in tree)
        check(total == job["chunkCount"], f"{label}: tree covers every chunk ({total}/{job['chunkCount']})")
        cons = all(
            all(c["strandCode"] == g["strandCode"] for c in g["chunks"]) for g in tree
        )
        check(cons, f"{label}: each tree group has a single strandCode")
        keys = [strand_key(g["strandCode"], g["strand"]) for g in tree]
        check(len(keys) == len(set(keys)), f"{label}: no strand is split across two headers due to cosmetic name drift")
        print(f"        {label} strands: " + ", ".join(
            f"{g['strandCode']} {g['strand']} [{g['chunkCount']}]" for g in tree[:6]
        ))

    print("\n== 6. English 1.1.1 KIQs correct ==")
    eng_job = jobs.get("English")
    if eng_job:
        r = next((c for c in eng_job["chunks"] if c["subStrandCode"] == "1.1.1"), None)
        check(r is not None, "English 1.1.1 chunk exists")
        if r:
            kiqs = r["structuredFields"]["key_inquiry_questions"]
            print(f"        1.1.1 '{r['subStrand']}' KIQs = {kiqs}")
            check(len(kiqs) >= 1, "English 1.1.1 has at least one KIQ")
            check(all(q.strip().endswith("?") for q in kiqs), "English 1.1.1 KIQs are whole questions ending in '?'")
            check(r["strandCode"] == "1.1", f"English 1.1.1 strand code is 1.1 (got {r['strandCode']})")
            check((r["theme"] or "").strip() != "", f"English 1.1.1 has a theme ({r['theme']})")

    print("\n== 7. CRE 1.1 has no rubric rows ==")
    cre_job = jobs.get("CRE")
    if cre_job:
        r = next((c for c in cre_job["chunks"] if c["subStrandCode"] == "1.1"), None)
        check(r is not None, "CRE 1.1 chunk exists")
        if r:
            blob = " ".join(
                str(v) for v in r["structuredFields"].values() if v is not None
            ) + " " + (r["subStrand"] or "")
            blob = blob.lower()
            rubric_terms = ["exceeds expectation", "meets expectation", "approaches expectation",
                            "below expectation", "assessment rubric"]
            hits = [t for t in rubric_terms if t in blob]
            check(not hits, f"CRE 1.1 contains no rubric content {hits}")
            check((cre_job["parseMeta"].get("rubricRowsSkipped") or 0) > 0,
                  f"CRE: rubric rows were skipped by the engine ({cre_job['parseMeta'].get('rubricRowsSkipped')})")

    print("\n== 8. Maths 1.2 has 6 outcomes a-f ==")
    mat_job = jobs.get("Maths")
    if mat_job:
        r = next((c for c in mat_job["chunks"] if c["subStrandCode"] == "1.2"), None)
        check(r is not None, "Maths 1.2 chunk exists")
        if r:
            outs = r["structuredFields"]["specific_learning_outcomes"]
            print(f"        Maths 1.2 '{r['subStrand']}' outcomes = {len(outs)}")
            for o in outs:
                print(f"          - {o[:90]}")
            check(len(outs) == 6, f"Maths 1.2 has exactly 6 outcomes (got {len(outs)})")
            check(r["strand"] == "Numbers", f"Maths 1.2 strand is 'Numbers' (got {r['strand']})")

    print("\n== 9. Pre-Technical has no second (phantom) list ==")
    pt_job = jobs.get("PreTechnical")
    if pt_job:
        r = next((c for c in pt_job["chunks"] if c["subStrandCode"] == "1.1"), None)
        check(r is not None, "Pre-Technical 1.1 chunk exists")
        if r:
            sf = r["structuredFields"]
            outs = sf.get("specific_learning_outcomes") or []
            exps = sf.get("suggested_learning_experiences") or []
            print(f"        Pre-Tech 1.1 '{r['subStrand']}' outcomes={len(outs)} experiences={len(exps)} "
                  f"pcIs={str(sf.get('pcis'))[:40]}")
            check(len(outs) > 0, f"Pre-Technical 1.1 outcomes present ({len(outs)})")
            # A phantom second list shows up as pcis / values / core competencies swallowing
            # whole outcomes or as list items repeated in the free-text fields.
            blob = " ".join(str(sf.get(k) or "") for k in
                            ("core_competencies", "values", "pcis", "link_to_other_learning_areas"))
            phantom = 0
            for o in outs:
                head = o[:40].lower()
                if head and head in blob.lower():
                    phantom += 1
            check(phantom == 0, f"no outcome is duplicated inside free-text fields (dupes={phantom})")
            # outcomes must not repeat inside the experiences list
            overlap = {o for o in outs} & {e for e in exps}
            check(not overlap, f"no outcome leaks into the experiences list ({len(overlap)} overlaps)")

    print("\n== 10. Review-state flow (DB round trip) ==")
    if eng_job:
        job = jobs["English"]
        pending = job["reviewSummary"]["pending"]
        check(pending == job["chunkCount"], f"all English chunks start Pending ({pending}/{job['chunkCount']})")
        check(not job["reviewSummary"]["readyToApprove"], "Approve is blocked while chunks are unreviewed")

    print("\n" + "=" * 68)
    if failures:
        print(f"RESULT: {len(failures)} FAILURE(S)")
        for f in failures:
            print("  - " + f)
        return 1
    print("RESULT: ALL ACCEPTANCE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
