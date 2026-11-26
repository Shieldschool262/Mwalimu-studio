"""One-shot (re-runnable) backfill of Phase 3.5 appendix fields on EXISTING documents.

Why this exists
---------------
Documents parsed before the appendix parser was added (or before the Swahili / CSL-page
fixes) have NULL appendix_resources / appendix_assessment. Using the UI's "Re-parse"
would fix that, but it also resets every chunk's review_state back to "Parsed" - losing
teacher approvals on saved documents.

This utility re-reads each document's ORIGINAL stored PDF, runs appendix parsing + join,
and updates ONLY the four appendix columns plus parse_meta. It never touches
review_state, vetting_status, status, structured_fields, or any plan.

Usage
-----
    python backfill_appendix.py              # backfill studio.db, print a report
    python backfill_appendix.py --dry-run   # report only, no writes
    python backfill_appendix.py --db path/to/other.db
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND))

import fitz  # noqa: E402

import db as db_module  # noqa: E402
from db import connect, init_db, upload_path  # noqa: E402
from services.appendix_parser import (  # noqa: E402
    appendix_pages,
    join_appendix,
    parse_appendix,
)


def backfill(db_path: Path, dry_run: bool = False, verbose: bool = True) -> dict:
    # db.connect() reads the module-level DB_PATH captured at import time, so override it
    # directly rather than relying on the environment variable being set late.
    db_module.DB_PATH = db_path
    init_db()

    report: dict = {"documents": 0, "chunks": 0, "filled": 0, "skipped": [], "details": []}

    with connect() as conn:
        docs = conn.execute(
            "SELECT id, file_name, parse_meta FROM source_documents ORDER BY created_at"
        ).fetchall()

        for doc in docs:
            doc_id, file_name = doc["id"], doc["file_name"]
            pdf_path = upload_path(doc_id)
            if not pdf_path.exists():
                report["skipped"].append(f"{file_name}: original PDF missing")
                continue

            try:
                with fitz.open(pdf_path) as pdf:
                    pages = appendix_pages(pdf)
                    appendix = parse_appendix(pages, verbose=verbose)
            except Exception as exc:  # pragma: no cover - corrupt PDF
                report["skipped"].append(f"{file_name}: appendix parse failed ({exc})")
                continue

            start_page = pages[0][0] if pages else None
            chunk_rows = conn.execute(
                "SELECT id, strand, strand_code, sub_strand, sub_strand_code "
                "FROM source_chunks WHERE document_id = ? ORDER BY ord",
                (doc_id,),
            ).fetchall()

            filled = 0
            updates: list[tuple] = []
            for row in chunk_rows:
                # Feed join_appendix the same camelCase shape the API uses.
                chunk = {
                    "strand": row["strand"],
                    "strandCode": row["strand_code"],
                    "subStrand": row["sub_strand"],
                    "subStrandCode": row["sub_strand_code"],
                }
                join_appendix(chunk, appendix)
                if chunk["appendix_resources"] or chunk["appendix_assessment"]:
                    filled += 1
                updates.append(
                    (
                        chunk["appendix_resources"],
                        chunk["appendix_assessment"],
                        chunk["appendix_source"],
                        chunk["appendix_level"],
                        row["id"],
                    )
                )

            if not dry_run:
                conn.executemany(
                    """UPDATE source_chunks
                       SET appendix_resources = ?, appendix_assessment = ?,
                           appendix_source = ?, appendix_level = ?
                       WHERE id = ?""",
                    updates,
                )
                meta = json.loads(doc["parse_meta"] or "{}")
                meta["appendixStartPage"] = start_page
                meta["appendixRows"] = len(appendix.get("rows") or [])
                meta["appendixMatched"] = filled
                meta["appendixBackfilled"] = True
                conn.execute(
                    "UPDATE source_documents SET parse_meta = ? WHERE id = ?",
                    (json.dumps(meta, ensure_ascii=False), doc_id),
                )

            report["documents"] += 1
            report["chunks"] += len(chunk_rows)
            report["filled"] += filled
            report["details"].append(
                {
                    "file": file_name,
                    "appendixStartPage": start_page,
                    "appendixRows": len(appendix.get("rows") or []),
                    "chunks": len(chunk_rows),
                    "filled": filled,
                }
            )
            if verbose:
                print(
                    f"  {file_name[:58]:58} p.{str(start_page):>4} "
                    f"rows={len(appendix.get('rows') or []):>3} "
                    f"chunks={len(chunk_rows):>3} filled={filled:>3}"
                )

    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill Phase 3.5 appendix fields without losing approvals")
    ap.add_argument("--db", default=str(db_module.DB_PATH), help="SQLite database path")
    ap.add_argument("--dry-run", action="store_true", help="Report only; do not write")
    ap.add_argument("--quiet", action="store_true", help="Suppress per-document parse logs")
    args = ap.parse_args()

    db_path = Path(args.db)
    print(f"{'DRY RUN  ' if args.dry_run else 'BACKFILL '} database: {db_path}")
    report = backfill(db_path, dry_run=args.dry_run, verbose=not args.quiet)
    print(
        f"\nDocuments: {report['documents']}  Chunks: {report['chunks']}  "
        f"With appendix data: {report['filled']}"
    )
    for s in report["skipped"]:
        print("  SKIPPED:", s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
