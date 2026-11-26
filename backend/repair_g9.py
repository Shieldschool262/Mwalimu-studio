"""One-off repair for the appendix mis-mapping contamination.

1. Re-parse every document's appendix with the FIXED appendix_parser and re-join
   appendix resources/assessment onto every chunk (updates source_chunks).
2. For every scheme row that was auto-filled (edited=0) in a plan that uses a
   changed chunk, recompute Resources/Assessment exactly like plan_service does
   at creation time, and refresh the row's `original` appendix metadata.
3. Regenerate unedited lesson-plan `resources` sections for changed chunks.
4. Regenerate unedited lesson-note content sections with the new source-derived
   fallbacks (no more early-years sorting text for unknown keywords).
"""
import sys, os, json, sqlite3
sys.path.insert(0, '.')

import fitz
from services.appendix_parser import appendix_pages, parse_appendix, join_appendix
from services import lesson_notes_service as lns
from services.lesson_templates import load_notes_template

DB = 'studio.db'
BACKUP = 'studio.db.bak-before-contam-fix'
UPLOADS = 'uploads'

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
cur = con.cursor()

# Old (pre-repair) appendix values from the backup, used to detect contaminated
# text inside teacher-EDITED rows: only the exact bogus string is replaced.
old_appendix: dict[str, tuple[str | None, str | None]] = {}
if os.path.exists(BACKUP):
    bcon = sqlite3.connect(BACKUP)
    bcon.row_factory = sqlite3.Row
    for r in bcon.execute("SELECT id, appendix_resources, appendix_assessment FROM source_chunks"):
        old_appendix[r['id']] = (r['appendix_resources'], r['appendix_assessment'])
    bcon.close()

# ---------------------------------------------------------------------------
# 1. Re-parse appendix for every document and re-join onto its chunks
# ---------------------------------------------------------------------------
changed_chunks: dict[str, dict[str, str | None]] = {}

docs = cur.execute("SELECT id FROM source_documents").fetchall()
for d in docs:
    doc_id = d['id']
    pdf = os.path.join(UPLOADS, f'{doc_id}.pdf')
    if not os.path.exists(pdf):
        print(f'skip {doc_id}: no pdf')
        continue
    try:
        fdoc = fitz.open(pdf)
        pages = appendix_pages(fdoc)
        app = parse_appendix(pages, verbose=False) if pages else {'rows': []}
    except Exception as e:
        print(f'skip {doc_id}: parse error {e}')
        continue
    chunks = cur.execute(
        "SELECT id, strand, strand_code, sub_strand, sub_strand_code, "
        "appendix_resources, appendix_assessment, appendix_source, appendix_level "
        "FROM source_chunks WHERE document_id=?", (doc_id,)
    ).fetchall()
    for c in chunks:
        cd = {
            'strand': c['strand'], 'strandCode': c['strand_code'],
            'subStrand': c['sub_strand'], 'subStrandCode': c['sub_strand_code'],
        }
        join_appendix(cd, app)
        new = (cd.get('appendix_resources'), cd.get('appendix_assessment'),
               cd.get('appendix_source'), cd.get('appendix_level'))
        old = (c['appendix_resources'], c['appendix_assessment'],
               c['appendix_source'], c['appendix_level'])
        if new != old:
            cur.execute(
                "UPDATE source_chunks SET appendix_resources=?, appendix_assessment=?, "
                "appendix_source=?, appendix_level=? WHERE id=?",
                (*new, c['id']),
            )
            changed_chunks[c['id']] = {
                'resources': new[0], 'assessment': new[1],
                'source': new[2], 'level': new[3],
                'sub_strand_code': c['sub_strand_code'],
                'strand_code': c['strand_code'],
                'structured_fields': None,
            }
            print(f"chunk {c['sub_strand_code']}: {str(old[0])[:60]!r} -> {str(new[0])[:70]!r}")

print(f'\nchanged chunks: {len(changed_chunks)}')

# structured fields for the changed chunks (needed for printed-resource precedence)
for cid in changed_chunks:
    row = cur.execute("SELECT structured_fields FROM source_chunks WHERE id=?", (cid,)).fetchone()
    changed_chunks[cid]['structured_fields'] = row['structured_fields']


def printed_join(raw) -> str | None:
    if isinstance(raw, list):
        return '; '.join(str(x) for x in raw if str(x).strip()) or None
    if raw:
        return str(raw).strip() or None
    return None


# ---------------------------------------------------------------------------
# 2. Scheme rows (plan_sections) of plans whose chunks have appendix values
# ---------------------------------------------------------------------------
plans = cur.execute("SELECT id, source_chunk_ids FROM plan_documents").fetchall()
sections_fixed = 0
for p in plans:
    try:
        chunk_ids = json.loads(p['source_chunk_ids'] or '[]')
    except Exception:
        chunk_ids = []
    hit = [c for c in chunk_ids if c in changed_chunks or c in old_appendix]
    if not hit:
        continue
    info_by_chunk = {}
    for cid in chunk_ids:
        row = cur.execute(
            "SELECT strand_code, sub_strand_code, structured_fields, appendix_resources, "
            "appendix_assessment, appendix_source, appendix_level FROM source_chunks WHERE id=?",
            (cid,),
        ).fetchone()
        if row is None:
            continue
        info_by_chunk[cid] = {
            'resources': row['appendix_resources'],
            'assessment': row['appendix_assessment'],
            'source': row['appendix_source'],
            'level': row['appendix_level'],
            'sub_strand_code': row['sub_strand_code'],
            'strand_code': row['strand_code'],
            'structured_fields': row['structured_fields'],
        }
    by_code = {}
    for cid, info in info_by_chunk.items():
        by_code[(info['strand_code'], info['sub_strand_code'])] = cid
        by_code.setdefault((None, info['sub_strand_code']), cid)
    rows = cur.execute(
        "SELECT id, strand_code, sub_strand_code, resources, assessment, edited, original "
        "FROM plan_sections WHERE plan_id=?", (p['id'],)
    ).fetchall()
    for r in rows:
        cid = by_code.get((r['strand_code'], r['sub_strand_code'])) or by_code.get((None, r['sub_strand_code']))
        if not cid:
            continue
        info = info_by_chunk[cid]
        sf = json.loads(info['structured_fields'] or '{}')
        resources = printed_join(sf.get('suggested_learning_resources')) or info['resources']
        assessment = printed_join(sf.get('assessment')) or info['assessment']
        original = json.loads(r['original'] or '{}')
        original['appendixResources'] = info['resources']
        original['appendixAssessment'] = info['assessment']
        original['appendixSource'] = info['source']
        original['appendixLevel'] = info['level']
        if not r['edited']:
            if (r['resources'] or '') != (resources or '') or (r['assessment'] or '') != (assessment or ''):
                original['resources'] = resources
                original['assessment'] = assessment
                cur.execute(
                    "UPDATE plan_sections SET resources=?, assessment=?, original=? WHERE id=?",
                    (resources, assessment, json.dumps(original, ensure_ascii=False), r['id']),
                )
                sections_fixed += 1
        else:
            # Teacher owns the cell text; refresh only the appendix metadata.
            cur.execute(
                "UPDATE plan_sections SET original=? WHERE id=?",
                (json.dumps(original, ensure_ascii=False), r['id']),
            )
            # ...but if the Resources cell still holds the exact OLD bogus
            # appendix autofill, that is contamination, not teacher content.
            old = old_appendix.get(cid)
            if old and (r['resources'] or '').strip() == (old[0] or '').strip():
                cur.execute("UPDATE plan_sections SET resources=? WHERE id=?", (resources, r['id']))
                sections_fixed += 1
print(f'plan_sections touched: {sections_fixed}')

# ---------------------------------------------------------------------------
# 3. Lesson-plan resources sections for changed chunks (unedited only)
# ---------------------------------------------------------------------------
lps = cur.execute("SELECT id, chunk_id, source_json FROM lesson_plans").fetchall()
lp_fixed = 0
for lp in lps:
    if lp['chunk_id'] not in changed_chunks:
        continue
    info = changed_chunks[lp['chunk_id']]
    src = json.loads(lp['source_json'] or '{}')
    src['appendixResources'] = info['resources']
    src['appendixAssessment'] = info['assessment']
    src['appendixSource'] = info['source']
    src['appendixLevel'] = info['level']
    cur.execute("UPDATE lesson_plans SET source_json=? WHERE id=?",
                (json.dumps(src, ensure_ascii=False), lp['id']))
    secs = cur.execute(
        "SELECT id, key, provenance, body, source_body, data_json, source_data_json, ai_assisted "
        "FROM lesson_plan_sections WHERE lesson_plan_id=?", (lp['id'],)
    ).fetchall()
    for s in secs:
        if s['ai_assisted']:
            continue
        if (s['body'] or '') != (s['source_body'] or '') or (s['data_json'] or '{}') != (s['source_data_json'] or '{}'):
            continue  # teacher/AI edited - never touch
        if s['key'] == 'resources':
            body = str(info['resources'] or '— Not specified in source')
            cur.execute(
                "UPDATE lesson_plan_sections SET body=?, source_body=? WHERE id=?",
                (body, body, s['id']),
            )
            lp_fixed += 1
print(f'lesson_plan_sections fixed: {lp_fixed}')

# ---------------------------------------------------------------------------
# 4. Lesson notes: regenerate UNEDITED content sections with the new builders
# ---------------------------------------------------------------------------
REGEN_KEYS = ('vocabulary', 'whatIs', 'examples', 'workedExample', 'practice', 'remember')
notes = cur.execute(
    "SELECT id, grade, template_version, focus, focus_keyword, source_json FROM lesson_notes"
).fetchall()
notes_fixed = 0
for n in notes:
    template = load_notes_template(n['template_version'], n['grade'])
    source = json.loads(n['source_json'] or '{}')
    assignment = {'focus': n['focus'], 'focus_keyword': n['focus_keyword']}
    title = lns.notes_title(source.get('subStrand'), assignment)
    changed = False
    sections = cur.execute(
        "SELECT id, key, provenance, body, data_json, source_body, source_data_json, ai_assisted "
        "FROM lesson_note_sections WHERE note_id=?", (n['id'],)
    ).fetchall()
    for s in sections:
        if s['key'] not in REGEN_KEYS:
            continue
        if s['ai_assisted'] or (s['body'] or '') != (s['source_body'] or '') \
                or (s['data_json'] or '{}') != (s['source_data_json'] or '{}'):
            continue  # teacher/AI edited - never touch
        body, data = lns._section_values(s['key'], template, title, '', assignment, source)
        body_s = json.dumps(data, ensure_ascii=False)
        if body == (s['body'] or '') and body_s == (s['data_json'] or '{}'):
            continue
        cur.execute(
            "UPDATE lesson_note_sections SET body=?, data_json=?, source_body=?, "
            "source_data_json=? WHERE id=?",
            (body, body_s, body, body_s, s['id']),
        )
        changed = True
    if changed:
        cur.execute("UPDATE lesson_notes SET updated_at=datetime('now') WHERE id=?", (n['id'],))
        notes_fixed += 1
        print(f"note {n['id'][:8]} regenerated")
print(f'notes fixed: {notes_fixed}')

con.commit()
con.close()
print('\nREPAIR COMPLETE')
