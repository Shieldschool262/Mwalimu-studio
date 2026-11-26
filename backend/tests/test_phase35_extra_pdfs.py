"""Phase 3.5 regression: appendix parsing on designs BEYOND the three acceptance PDFs.

These two exposed real gaps in the original appendix parser:

  * Grade 3 Mathematics - "APPENDIX 1: CSL GUIDELINES" sits between the appendix
    start and "APPENDIX 2: SUGGESTED LEARNING RESOURCES". Appendix mode used to stop
    on the CSL prose page, so the Type A resource table on p.50 was never reached.
  * Grade 1 Kiswahili - appendix headings are in Swahili (KIAMBATISHO, Nyenzo za
    Kufundishia, Mbinu za Kutathminia). No appendix page was detected at all. Its
    appendix is also a SUBJECT-WIDE summary organised by language skill while the
    main tables group sub-strands by theme, so strand-level joins cannot match.

Run: python tests/test_phase35_extra_pdfs.py
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

import fitz  # noqa: E402

from services.appendix_parser import (  # noqa: E402
    appendix_pages,
    join_appendix,
    parse_appendix,
)

CD = Path(r"C:\Users\user\Desktop\Curriculum Designs")
MATHS_G3 = CD / "Grade-3-Mathematics-Activities-Curriculum-Design.pdf"
KISWAHILI_G1 = CD / "Grade-1-Kiswahili-Activities-Curriculum-Design.pdf"

failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {msg}")
    if not cond:
        failures.append(msg)


def load(path: Path):
    doc = fitz.open(path)
    pages = appendix_pages(doc)
    data = parse_appendix(pages, verbose=False)
    return doc, pages, data


def main() -> int:
    if not MATHS_G3.exists() or not KISWAHILI_G1.exists():
        print("SKIP: extra curriculum PDFs are not available on this machine.")
        return 0

    print("\n== Grade 3 Mathematics: CSL pages must not stop appendix mode ==")
    doc, pages, data = load(MATHS_G3)
    page_nums = [p for p, _ in pages]
    check(46 in page_nums, "appendix mode starts at p.46 (CSL guidelines)")
    check(50 in page_nums, "run continues past CSL pages to p.50 (resources table)")
    type_a = [r for r in data["rows"] if r["type"] == "A"]
    check(len(type_a) >= 5, f"Type A sub-strand resource rows parsed ({len(type_a)})")
    whole = next(
        (r for r in type_a if "WHOLE NUMBERS" in (r.get("sub_strand") or "").upper()), None
    )
    check(whole is not None, "WHOLE NUMBERS resource row present")
    if whole:
        check("number line" in (whole.get("resources") or "").lower(), "value comes from the PDF cell")
        check(whole.get("level") == "sub_strand", "level is sub_strand")
        chunk = {
            "strand": "Numbers", "strandCode": "1.0",
            "subStrand": "Whole Numbers", "subStrandCode": "1.2",
        }
        join_appendix(chunk, data)
        check(chunk["appendix_resources"] is not None, "join fills a matching chunk's resources")
        check(chunk["appendix_assessment"] is not None, "Appendix 2 assessment fallback applies")
        check(chunk["appendix_level"] == "sub_strand", "joined level is sub_strand")
    doc.close()

    print("\n== Grade 1 Kiswahili: Swahili headings + subject-wide summary ==")
    doc, pages, data = load(KISWAHILI_G1)
    page_nums = [p for p, _ in pages]
    check(101 in page_nums, "Swahili KIAMBATISHO 3 detected as appendix (p.101)")
    type_b = [r for r in data["rows"] if r["type"] == "B"]
    check(len(type_b) >= 1, f"Swahili Type B table classified ({len(type_b)} row(s))")
    summary = data.get("subject_summary")
    check(summary is not None, "subject-level summary built from real appendix cells")
    if summary:
        check("Chati" in (summary.get("resources") or ""), "summary carries real resources")
        check("Kumakinikia" in (summary.get("assessment") or ""), "summary carries real assessment")
    lonely = {
        "strand": "DARASANI", "strandCode": "1.0",
        "subStrand": "Maamkuzi na Maagano", "subStrandCode": "1.1",
    }
    join_appendix(lonely, data)
    check(lonely["appendix_resources"] is not None, "chunk with no strand match still gets subject summary")
    check(lonely["appendix_assessment"] is not None, "chunk gets subject-level assessment too")
    check(lonely["appendix_level"] == "subject", "level is subject")
    check("p.101" in (lonely["appendix_source"] or ""), "source names the appendix page")
    doc.close()

    print("\n== No hallucination ==")
    empty = {
        "strand": "X", "strandCode": "9.0",
        "subStrand": "Nothing", "subStrandCode": "9.9",
    }
    join_appendix(empty, {"rows": [], "subject_resources": None, "subject_assessment": None})
    check(empty["appendix_resources"] is None, "no appendix at all -> resources None")
    check(empty["appendix_assessment"] is None, "no appendix at all -> assessment None")

    print("\n" + "=" * 60)
    if failures:
        print(f"RESULT: {len(failures)} FAILURE(S)")
        for f in failures:
            print("  -", f)
        return 1
    print("RESULT: ALL EXTRA-PDF APPENDIX CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
