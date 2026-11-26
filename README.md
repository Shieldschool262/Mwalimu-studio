# Mwalimu Studio

Offline-first PWA for Kenyan CBE teachers. **Built around the proven standalone parser**, which is
copied verbatim and never edited.

**This build contains Phase 0 + Phase 1 (+ polish) + Phase 2 (My Library) + Phase 3 (Planning) +
Phase 3.5 (Appendix autofill) + Phase 4 (Editing & Lesson Plans) + Phase 5 (Learner Lesson Notes).**
No Auth, Records of Work, or export workspace beyond the PDFs yet.

---

## Run it

Two terminals. Nothing leaves your machine. AI enrichment and web examples are **teacher-initiated
and optional**; without a `GEMINI_API_KEY` no AI request is ever made.

### 1. Backend (FastAPI + SQLite)

```bash
cd mwalimu-studio/backend
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000
```

- API: <http://127.0.0.1:8000>
- Health: <http://127.0.0.1:8000/health>
- Database: `backend/studio.db` (created on first start)

Optional AI enrichment (OFF by default): open **⚙ AI & Web Search** in the app to pick a provider
and paste a free API key, or use `backend/.env` as a fallback:

```bash
cd mwalimu-studio/backend
copy .env.example .env      # Windows
# edit .env -> GEMINI_API_KEY=...
```

Recommended free defaults (verified live): **Gemini `gemini-3.5-flash-lite`** for AI drafting and
**DuckDuckGo HTML** for web search (no key at all). Without an AI key every lesson-plan feature
still works and the Draft buttons explain what is missing. Web examples are teacher-initiated and
only ever show real URLs returned by the chosen provider.

### 2. Frontend (React + TypeScript + Vite + Tailwind)

```bash
cd mwalimu-studio/frontend
npm install
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` and `/health` to the backend on port 8000.

> If your Python is not on `PATH` as `python`, use `py -3 -m uvicorn main:app --reload --port 8000`.

---

## Acceptance tests

```bash
cd mwalimu-studio/backend
python tests/test_acceptance.py   # Phase 1 parser (5 designs, sequential)
python tests/test_library.py      # Phase 2 library + review flow
python tests/test_phase3_scheme.py # Phase 3 vetting guard + KICD scheme
python tests/test_phase3_acceptance.py # Phase 3 CORRECTED weekly-row rules
python tests/test_phase35_appendix.py  # Phase 3.5 appendix parsing / autofill
python tests/test_phase35_extra_pdfs.py # Phase 3.5 on the extra real designs
python tests/test_phase4_acceptance.py # Phase 4 editing, versions + lesson plans
python tests/test_phase5_acceptance.py # Phase 5 learner Lesson Notes (one doc per lesson)
```

On Windows, set `$env:PYTHONIOENCODING='utf-8'` first so the test output is not mangled.
Each suite uses its own `studio_*_test.db` and never touches `studio.db`.

Parses **Grade 1 English, CRE, Maths, Kiswahili and Grade 9 Pre-Technical sequentially in one
process** (exactly like a running server) and asserts:

| # | Check | Result |
|---|-------|--------|
| 1 | No duplicate sub-strand within a document | ✅ |
| 2 | No cross-document leak; unresolved strands are null + flagged, never borrowed | ✅ |
| 3 | No aliasing between chunks (deep-copied on the way in and out) | ✅ |
| 4 | KIQs joined into whole questions, no wrapped fragments | ✅ |
| 5 | Strand grouping correct, cosmetic name drift merged into one header | ✅ |
| 6 | English `1.1.1` KIQs: `Why do we greet people?` / `How do we greet people at different times of the day?` | ✅ |
| 7 | CRE `1.1` contains no rubric rows (engine skipped 5 rubric rows) | ✅ |
| 8 | Maths `1.2` has exactly 6 outcomes `a)–f)` | ✅ |
| 9 | Pre-Technical `1.1` has no second/phantom list | ✅ |
| 10 | Every chunk starts `Parsed`; Approve is blocked until reviewed | ✅ |

The test uses `studio_test.db` and never touches `studio.db`.

---

## Phase 1 polish - fast review

| Feature | Where |
|---|---|
| **Approve All (N/M ready)** — approves every chunk with confidence >= 0.9 | top toolbar |
| **Approve Strand** — approves every sub-strand under that strand | strand header |
| **Approve** — one sub-strand | each card |
| **Inline edit** — click the field text, it becomes a `textarea` in place | each field |
| Save on **Enter** or **click outside**, cancel on **Esc** | inline editor |
| **↩ Undo** on a corrected field restores the originally extracted text | each field |
| **Show Needs Review Only** (default) / **Show All** | top toolbar |
| `Auto-approved: N | Needs Review: N | Corrected: N` | top toolbar |
| Red **Missing: KIQs** pill + the empty field highlighted | each card |
| **Approve & Save to My Library** (gated, or "Save with gaps") | bottom bar |

Corrections post `{field, newValue}` and set `TeacherCorrected` + confidence `1.0`.

## Phase 2 - My Library

Source-first: every chunk keeps its document, page and original PDF.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/library` | list: `myMaterials` (Approved) + `needsReview` + `studioLibrary` placeholder |
| `GET` | `/api/library/{docId}` | one document with chunks grouped by strand |
| `GET` | `/api/library/search?q=` | search file name, subject, grade, strand, sub-strand, outcomes, experiences, KIQs, values |
| `POST` | `/api/library/save` | `{jobId, saveWithGaps}` → status `Approved` |
| `POST` | `/api/library/{docId}/reparse` | re-run the verbatim engine on the stored PDF |
| `DELETE` | `/api/library/{docId}` | delete document + chunks + stored PDF |
| `GET` | `/api/library/{docId}/export` | JSON download |
| `GET` | `/api/library/{docId}/file` | original PDF |

Search results always carry `documentId`, `pageNumber` and a snippet, so a hit is never
shown out of context. Searches are scoped per document row, so `Musical Sounds` can never
return a Maths chunk.

The original PDF is written to `backend/uploads/{docId}.pdf` at parse time and is only
removed when the teacher deletes the document.

## The parser

`backend/services/parser_engine.py` is a **byte-identical copy** of
`grade1-parser/parser_engine.py` (verified with `md5sum`). It also needs
`backend/profiles/archetypes.json`.

**The engine is never edited to fit the app. The app adapts to the engine:**

| Engine reality | How the app adapts |
|---|---|
| Records are plain dicts with snake_case keys | `services/parse_service.py` maps them to `SourceChunk` |
| One `ParseSession` per `parse_pdf()` call | One fresh session per uploaded document; nothing shared between jobs |
| Archetype is auto-detected (A/B/C/D) | Stored on `SourceDocument.archetype`, surfaced as a badge |
| Dedup is by `strand_code \| sub_strand_code` | Carried through; integrity re-checked by a DB unique index |
| `lessons` is only set when the PDF prints `(N lessons)` | `lessons` stays `null` otherwise — never invented |
| Teaches `GRADE = "Grade 1"` | App reads it for English/CRE/Maths/Kiswahili and derives the grade from the filename for Grade 9 |
| Emits strand name variants (`Pre - Technical` / `Pre–Technical`) | Grouping normalises punctuation so one strand = one header |
| Leaves strand `null` on designs with no `STRAND` keyword (e.g. Kiswahili) | App recovers the heading from that chunk's own page and flags it `Strand name recovered from page heading - verify`. Never borrowed from another document |
| Misses experiences when a header cell spans columns (Maths 3.2, p.27: header maps col 3, text sits in col 4) | `services/repair.py` re-reads that column, joins split bullets and flags `Experiences recovered from shifted table column - verify` |

---

## Phase 1 API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Status, parser version, archetypes |
| `POST` | `/api/parse` | Upload one PDF → `SourceDocument` + `SourceChunk`s (multipart `file`) |
| `GET` | `/api/parse/{jobId}` | Job payload: document, chunks, review summary, strand tree |
| `POST` | `/api/parse/{jobId}/chunks/{chunkId}/correct` | Inline teacher correction |
| `POST` | `/api/parse/{jobId}/approve` | Approve the document (`{"save_with_gaps": bool}`) |

### Models

```
SourceDocument { id, fileName, grade, subject, archetype, parserVersion="studio-parser-v1", status }
SourceChunk    { id, documentId, pageNumber, theme?, themeCode?, strand, strandCode,
                 subStrand, subStrandCode, lessons?, structuredFields JSON,
                 confidence, reviewState }
```

Review states: `Parsed` → `TeacherCorrected` → `Approved`.

### Approve rule

The **Approve document** button stays disabled until **every** chunk is
`TeacherCorrected`/`Approved`, **or** the teacher ticks **“Save with gaps”**.
The backend enforces the same rule and returns `409` otherwise.

---

## UI (Phase 1)

`frontend/src/components/UploadAndReview.tsx`

1. **Upload PDF** → spinner while parsing.
2. **`Detected: Archetype A · Language`** badge with confidence, plus sub-strand count,
   skipped rubric rows, back-matter stop page and duplicates skipped.
3. **Tree view** grouped by strand:
   - Strand header — `1.0 Numbers [3 Sub-Strands]`, expandable.
   - Sub-strand cards — page, lessons, confidence badge, outcomes / experiences / KIQs.
   - **Edit** opens an inline editor (sub-strand, lessons, one item per line for each list).
   - **Approve** marks a single chunk approved.
4. Toolbar shows approved / corrected / pending counts and the **Save with gaps** checkbox.

---

## Layout

```
mwalimu-studio/
├── backend/
│   ├── main.py                     FastAPI app (all phases)
│   ├── db.py                       SQLite schema + helpers (studio.db)
│   ├── requirements.txt
│   ├── .env.example                optional API-key fallbacks
│   ├── settings.json               local AI + web search config (gitignored)
│   ├── profiles/archetypes.json    required by the engine
│   ├── templates/                  cbe-scheme-v1, cbe-lesson-primary-v1, cbe-lesson-jss-v1,
│   │                               cbe-lesson-notes-v1, cbe-lesson-notes-jss-v1
│   ├── uploads/{docId}.pdf         original PDFs (never deleted except on Delete)
│   ├── services/
│   │   ├── parser_engine.py        COPIED VERBATIM - DO NOT EDIT
│   │   ├── parse_service.py        app-side adapter (mapping, persistence, tree, review)
│   │   ├── library_service.py      list / get / search / delete / reparse / save / vetting
│   │   ├── repair.py               app-side gap recovery (never edits the engine)
│   │   ├── plan_service.py         scheme generation, editing, versions, validation
│   │   ├── lesson_derive.py        deterministic atomic-skill decomposition
│   │   ├── rubric_service.py       rubric parse / match / planned assessment
│   │   ├── lesson_plan_service.py  KICD lesson plans, sections, versions, AI/web
│   │   ├── lesson_notes_service.py learner Lesson Notes, edits, AI review, versions
│   │   ├── notes_enrich.py         strict learner-notes prompt / normalization
│   │   ├── ai_service.py           provider-agnostic AI client + real web search
│   │   ├── settings_service.py     settings.json persistence + provider catalogues
│   │   ├── scheme_pdf.py           landscape A4 scheme PDF
│   │   ├── lesson_pdf.py           portrait A4 KICD lesson PDF
│   │   └── notes_pdf.py            portrait A4 learner notes PDF (answers hidden)
│   └── tests/
│       ├── test_acceptance.py      Phase 1 parser acceptance
│       ├── test_library.py         Phase 2 library acceptance
│       ├── test_phase3_*.py        Phase 3 scheme acceptance
│       ├── test_phase35_*.py       Phase 3.5 appendix acceptance
│       ├── test_phase4_acceptance.py Phase 4 editing + lesson plans
│       └── test_phase5_acceptance.py Phase 5 learner Lesson Notes
└── frontend/
    ├── src/App.tsx                 "Mwalimu Studio" header + health badge
    ├── src/api.ts
    ├── src/types.ts
    └── src/components/
        ├── UploadAndReview.tsx   upload + strand tree + inline editing
        ├── Library.tsx           search, filters, cards, actions
        ├── CreateDocument.tsx    type -> details -> vetted sources -> preview -> generate
        ├── PlanView.tsx          editable KICD scheme, versions, lesson + notes pickers
        ├── LessonPlanView.tsx    KICD lesson editor, AI drafts, web examples
        ├── LessonNotesEditor.tsx learner notes editor, AI review, web + teacher sources
        ├── NotesPickerModal.tsx  one folder per lesson: create / open notes
        ├── Settings.tsx          AI + web search providers, tests, free recommendations
        └── ui.tsx                badges, EditableField, Toast, ConfirmDialog
```

## Phase 3 - the vetting guard

Vetting is computed in **one place only**: `services/library_service.py`.

```python
CORE_VETTING_FIELDS = {
    "specific_learning_outcomes": "Outcomes",
    "suggested_learning_experiences": "Experiences",
    "key_inquiry_questions": "Key Inquiry Questions",
}
```

A chunk is `Vetted` when **all three** are non-empty **and** the review state is
`Approved` / `TeacherCorrected`. Everything else is `Pending`.

**Core competencies, values, PCIs, link to other learning areas and link to value are never
checked.** A design that does not print them is still fully vetted, and a plan generated from
it shows `— Not specified in source` in grey. Nothing is invented to fill the gap.

Consequences, enforced everywhere:

| Rule | Where |
|------|-------|
| Studio Library lists a document **only if every chunk is vetted** | `list_library` |
| One pending chunk keeps the whole document in My Materials | `list_library` |
| Card badge names the gap: `Vetting: 8/9 Vetted - 1 pending: Key Inquiry Questions (1.2)` | `vetting_summary` |
| Create screen only allows selecting vetted sub-strands; the rest are greyed out with the reason | `vetting_catalog` |
| Generation is **rejected** if any selected chunk is not vetted | `validate_sources` |

The block message names the sub-strand and the missing field:

> Cannot generate: Sub-strand 1.2 [Whole Numbers] is missing Key Inquiry Questions.
> Fix it in Library, or unselect it.

Unselecting it and generating from the remaining sub-strands succeeds. Vetting is recomputed
after every parse, approve, approve-all, approve-strand, correction and save, so the stored
column can never go stale.

## Phase 3 - official KICD Scheme of Work

Templates live in `backend/templates/cbe-scheme-v1.json`. **Column order, labels, widths,
fallbacks and the header fields are data, not code** — a future KICD revision is a new
template version, not a code change.

### The 10 columns, in KICD order

| # | Column | Where it comes from |
|---|--------|---------------------|
| 1 | Week | allocated (see below) |
| 2 | Lesson | allocated (see below) |
| 3 | Strand | `SourceChunk.strand` |
| 4 | Sub-Strand | `SourceChunk.subStrand` (+ page citation pill) |
| 5 | Specific Learning Outcomes | `specific_learning_outcomes` **verbatim** |
| 6 | Learning Experiences | `suggested_learning_experiences` **verbatim** |
| 7 | Key Inquiry Question (KIQ) | `key_inquiry_questions` **verbatim** |
| 8 | Learning Resources | source value, else `— Teacher to fill` (grey, editable, never blocks) |
| 9 | Assessment | appendix value (Phase 3.5), else printed source, else `Observation, oral questions` (editable, never blocks) |
| 10 | Reflection / Remarks | **always empty** on generation; placeholder `To be filled after lesson` |

### Week / lesson allocation - ONE WEEK = ONE ROW

Each sub-strand is **expanded into one row per week**. The Week cell is a single integer, and
the Lesson cell is the range *inside that week*, restarting at 1 every week:

```
Mathematics 1.1, 20 lessons at 5 lessons/week

Week  Lesson   Part          Outcomes        Experiences       KIQ
1     1-5      Part 1 of 4   a) sort ...     bullets 1-2       How can we group objects?
2     1-5      Part 2 of 4   b) match ...    bullets 3-4       How can we arrange objects?
3     1-5      Part 3 of 4   c) order ...    bullet 5          - See Week 1
4     1-5      Part 4 of 4   d) create ...   bullet 6          - See Week 1
```

Rules the allocator guarantees:

- **Week is never a range.** `2`, not `2-5`. The next sub-strand continues the numbering
  (`1.2` would start at Week 5).
- **Lesson resets every week.** Week 2 is `1-5`, not `6-10`. A short final week is `1-3`.
- **Content is split, never repeated.** Outcomes are dealt out one per week; surplus outcomes
  join the last week so **nothing is dropped**. Experiences are dealt in contiguous blocks.
  A single KIQ appears on Week 1 and later rows read `- See Week 1`.
- **Shared citation.** Every weekly row cites the *same* SourceChunk and page number, plus its
  part label, e.g. `p.10` and `Part 2 of 4`.
- **Strand / Sub-Strand / Resources / Assessment** stay constant across the weeks of a
  sub-strand. **Reflection is always empty.**
- **No printed lesson count** falls back to 4 with the flag `Lessons not in source - assumed 4, edit`.
- **Overflow warns, never truncates.** If the selection does not fit the term every row is still
  produced:

  > Selected sub-strands need 132 lessons but term has 65 - remove 67 lessons or extend weeks

Cells of each weekly row are edited independently: changing Week 2 leaves Week 1 and Week 3
untouched, and the edited row alone is marked `Teacher Edited`. If a teacher wants the content
re-spread they press **[Re-balance Outcomes]** for that sub-strand, which re-runs the split from
the sub-strand's original source lists (`POST /api/plans/{id}/rebalance`).

The split lives in one testable module, `services/weekly_split.py`.

### Vetting guard (unchanged, and the only place it lives)

`compute_vetting_status` in `services/library_service.py` checks exactly three core fields:
outcomes, experiences, KIQs. Competencies, values, PCIs, links, resources, assessment and
reflection **never** affect vetting. A pending chunk blocks generation:

> Cannot generate: 1.2 missing KIQs. Fix in Library or unselect it.

### API

| Endpoint | Purpose |
|----------|---------|
| `GET /api/plans/template/cbe-scheme-v1` | the template itself |
| `GET /api/plans/sources` | chunks for the Create screen, with vetting state |
| `POST /api/plans` | generate (422 + reason when the guard blocks) |
| `GET /api/plans`, `GET /api/plans/{id}` | list / full plan incl. columns, header, allocation |
| `POST /api/plans/{id}/header` | edit school/term/year/teacher |
| `POST /api/plans/{id}/sections/{sid}/edit` | edit one cell, or one weekly row's week/lesson |
| `POST /api/plans/{id}/rebalance` | `[Re-balance Outcomes]` - re-split one sub-strand's weekly rows |
| `POST /api/plans/{id}/duplicate` | copy for the next term (teacher cells cleared) |
| `POST /api/plans/{id}/status` | `Draft` / `Final` / `Archived` |
| `GET /api/plans/{id}/export.pdf` | **landscape A4**, header repeated on every page |
| `DELETE /api/plans/{id}` | remove a plan |

### Create screen

Step 1 type (Scheme only) → Step 2 school, grade, learning area, term, year, lessons/week,
total weeks → Step 3 sources (only Vetted selectable; pending greyed out showing the missing
field) → Step 4 preview table with the computed week/lesson ranges → **Generate Scheme**.

No LLM anywhere in generation; `test_phase3_scheme.py` asserts the plan service imports no AI
client. Reflection is never auto-filled.

## Phase 3.5 - appendix autofill

The parser also reads Appendix 1 (Learning Resources) and Appendix 2 (Assessment Methods) from
the design PDF. Matching is by sub-strand, then strand, then whole subject; an unmatched
sub-strand falls back to the subject-level value and no value is ever invented.

- Resources and Assessment cells in a generated scheme show the appendix value, flagged
  `fromAppendix`, instead of the grey placeholder.
- `[Reset to Appendix]` restores one edited cell from the appendix, per row only.
- Appendix parsing never changes vetting. A design with no appendix is still fully Vetted.
- Existing libraries can be backfilled with `python backfill_appendix.py`.

---

## Phase 4 - editing & lesson plans

Phase 4 changes only the app layer. `parser_engine.py` and `repair.py` stay byte-identical
(the acceptance test verifies both md5 hashes).

### Scheme editor

Every cell is inline-editable: click once to get a textarea, **Enter** saves and **Esc**
cancels. An edited row is marked `Teacher Edited`; the plan header shows `Dirty - Unsaved`
until **[Save Version]**.

Top action bar, exactly:

`[Save Version]` `[↩ Undo Last Edit]` `[Duplicate for Next Term]` `[Mark Final]` `[Export PDF]`

Per-row actions live in a toolbar row beneath each weekly row:

- source badge (`Vetted source` / `Pending source`)
- deterministic decomposition preview (`L1 colour · L2 shape · L3 size · L4 consolidation · L5 assessment`)
- spill warning + **[Extend to N lessons]** when atomic skills outnumber the week's lessons
- ✓ links to lesson plans already created for that row
- **[Create Lesson Plans]** picker
- **[↩ Reset Row to Source]** — restores Outcomes / Experiences / KIQs / Resources / Assessment,
  clears `Teacher Edited`, and **keeps the teacher's Reflection**

Bulk actions: **[Edit Resources for All Weeks]** per sub-strand (confirmed first) and
**[Clear All Reflections]**.

Validation runs on every edit, on Save Version and on Mark Final:

- Week must be a whole number 1-13
- Lesson must match `"1-5"` for a 5-lesson week
- Outcomes, Experiences and KIQs must not be emptied

Emptying a vetted cell returns the exact message:

> Week 2 Outcomes cannot be empty - this was Vetted from source. Restore from source or unselect row.

### Version history (append-only)

Every generated or duplicated scheme gets a baseline `v1` automatically. A plan created
before Phase 4 gets a lazy `Baseline snapshot` v1 the first time its history is opened.

`PlanVersion { id, planId, versionNumber, createdAt, comment, snapshotJson }`

- **[Save Version]** requires a comment and snapshots the **whole** plan (header, rows,
  citations, dirty flag).
- Restore never deletes history: it re-inserts the snapshot and appends a **new** version.
- The history drawer shows each version, its comment and a cell-by-cell diff.
- **[Mark Final]** validates, appends a version labelled `Final - Term 1`, and locks editing.
- While Final, edits are rejected with `This scheme is Final. Press [Unlock to Edit] first.`;
  **[Unlock to Edit]** returns to Draft and appends `v4 - Unlocked from Final`.

| Endpoint | Purpose |
|----------|---------|
| `GET /api/plans/{id}/versions` | history, newest first (creates baseline v1 if missing) |
| `POST /api/plans/{id}/versions` | `{comment}` → append a snapshot; 422 when invalid/empty comment |
| `GET /api/plans/{id}/versions/{versionId}/diff` | current plan vs that snapshot |
| `POST /api/plans/{id}/versions/{versionId}/restore` | restore content as a **new** version |
| `POST /api/plans/{id}/undo` | undo the most recent cell edit |
| `POST /api/plans/{id}/sections/{sid}/reset-source` | reset one row to its vetted source |
| `POST /api/plans/{id}/sections/{sid}/extend` | `{lessonCount}` for [Extend to N lessons] |
| `POST /api/plans/{id}/bulk-resources` | `{subStrandCode, resources}` for all weeks |
| `POST /api/plans/{id}/clear-reflections` | clear every row's Reflection |
| `POST /api/plans/{id}/unlock` | Final → Draft, recorded as a new version |

### Lesson plans - one week = N independent plans

Opening the picker for a row lists Lesson 1..N with checkboxes, **Select All** /
**Select Missing**, a date per lesson (at least Date for Lesson 1), Duration, Time and Class
Size. **[Create Selected]** stays disabled until at least one lesson is ticked. Lessons that
already exist show `✓ Created`; creating them again is impossible (unique
`section_id + lesson` index) and the picker offers **Create Missing Only**.

Each plan carries a single integer Lesson (`1`, never `1-5`), its own title, header and
sections. A Pending source is blocked with:

> Cannot create lesson plan - source not Vetted

#### Two templates, chosen by grade

| Template | Grades | Default | Lesson Development hint |
|----------|--------|---------|-------------------------|
| `cbe-lesson-primary-v1` | PP1 - Grade 6 | 35 min | activity-based: song, play, manipulatives, pair work |
| `cbe-lesson-jss-v1` | Grade 7 - Grade 9 | 40 min single / 80 min double | subject-specific: experiment, project, investigation, lab/workshop task |

Grade decides the default; the teacher can switch template in the header dropdown. The JSS
header exposes a **Single / Double** selector.

#### Focused SLOs - never the whole sub-strand

A scheme outcome says *"By the end of the sub-strand, the learner should be able to..."*.
A lesson plan must say:

> By the end of the lesson, the learner should be able to: a) sort objects by colour only

The SLO is derived from that lesson's atomic skill (`colour`, `shape`, `size`), so Lesson 1
and Lesson 2 differ. The full sub-strand outcome stays visible in the read-only side panel
under `Source: By the end of the sub-strand...`. Saving an SLO that still contains the
sub-strand heading shows:

> Should be 'By the end of the lesson' for a lesson plan - Fix? **[Fix Automatically]**

#### Every field is editable

Header (School, Grade, Learning Area, Term, Year, Date, Time, Duration, Class, Roll
Boys/Girls/Total, Teacher, TSC No), Strand, Sub-Strand, SLOs, KIQ, Core Competencies,
Values, PCIs, Learning Resources, Introduction, Steps 1-3, Conclusion, Extended Activities,
Assessment and Reflection are all inline-editable. Editing a lesson plan **never mutates the
SourceChunk**: the plan stores its own copy plus `sourceChunkId` and page number. Any field
whose value differs from its parsed/appendix value shows `Edited from source` and has its
own **[↩ Reset to Source]** (teacher-filled fields are cleared instead).

The 11-part KICD order is fixed:

1. Administrative Details
2. Strand
3. Sub-Strand
4. Specific Learning Outcomes
5. Key Inquiry Question(s)
6. Core Competencies
7. Values
8. Pertinent & Contemporary Issues (PCIs)
9. Learning Resources
10. Lesson Development - Introduction + Step 1/2/3 + Conclusion
11. Extended Activities + Assessment + Reflection

Each development step is structured, not one textbox:
`{time, teacherActivity, learnerActivity}`. Assessment is
`{method, description, sampleItems[], rubricIndicator}`. Planned Assessment from the
curriculum rubric is shown alongside it:

> Planned Assessment (from Rubric p.15): Indicator: Ability to sort...
> Exceeds / Meets / Approaches / Below
> Support: ... · Extension: ...

### Deterministic decomposition (`services/lesson_derive.py`)

No LLM. One compound experience is split into atomic skills using conservative rules:

- `by X, Y and Z` / `such as X, Y, Z` → one atom per attribute
- `sort, group and match objects` → one atom per verb
- `different X, Y and Z` → one atom per item
- no known pattern → exactly **one** atomic skill (never force-split)

`assign_lessons` puts one atom per lesson; spare lessons become Consolidation / Practice and
finish with Assessment / Revision. If there are more atoms than lessons, **nothing is
dropped**: the overflow is returned as `spill` with a warning and an estimated
`[Extend to N lessons]`.

### Rubric derivation (`services/rubric_service.py`)

PyMuPDF `find_tables()` reads the `Assessment Rubrics` pages, keeps the four levels
(Exceeds / Meets / Approaches / Below) and caches the matched indicators on
`source_chunks.assessment_rubric`. Matching uses token overlap against the row's sub-strand
and outcomes. The rubric only feeds planned assessment and differentiation; it never affects
vetting.

### Optional AI + web examples (configurable in AI & Web Search)

AI is opt-in and only runs on **[Draft with AI]** / **[Suggest split]**. Drafts appear in yellow
with **Accept / Edit / Reject** per field. AI never changes Outcomes, KIQ, Resources or vetting.

Open **⚙ AI & Web Search** (left nav or header) to configure both services. Settings are stored in
`backend/settings.json` (gitignored) and take priority over `.env`; API keys are masked in every
GET response. The page includes provider cards, model discovery, one-click connection tests, and
a table of free providers.

**AI providers:** Gemini (recommended `gemini-3.5-flash-lite`), OpenRouter (`openrouter/free`),
Groq, Cerebras, Ollama (local / offline), any OpenAI-compatible endpoint, or Off.
**Web search providers:** DuckDuckGo HTML (recommended, no key), Tavily (1,000 free/month),
Serper (2,500 free queries), Wikipedia, SearXNG, Gemini grounding, Auto (with no-key fallback),
or Off. Brave Search removed its free API plan in 2026 and is not offered.

Web examples are teacher-initiated only. The top results show title + URL + snippet and are
inserted as:

> `[Web Example - {source}] title: url`

If the provider fails, the editor now shows the real error instead of a silent empty list.

### Settings API

| Endpoint | Purpose |
|----------|---------|
| `GET /api/settings` | masked config, provider catalogues, AI + search status |
| `PUT /api/settings` | save provider, key, model, base URL, timeouts, limits |
| `POST /api/settings/reset` | delete `settings.json`, revert to defaults + `.env` |
| `POST /api/settings/test/ai` | one real tiny AI request; returns latency or the exact error |
| `POST /api/settings/test/search` | one real search; returns sample results or the exact error |
| `POST /api/settings/models` | list model IDs available to the current key |


### Lesson-plan API

| Endpoint | Purpose |
|----------|---------|
| `GET /api/plans/{id}/sections/{sid}/lessons` | picker: lessons 1-N, created ✓, vetting guard |
| `POST /api/lesson-plans` | `{schemeRowId, lessons:[...], dates, duration, durationType, templateVersion, time, classSize}` |
| `GET /api/lesson-plans?planId=&sectionId=` | list (optionally scoped) |
| `GET /api/lesson-plans/{id}` | full plan: header, sections, source sidebar, assessment |
| `POST /api/lesson-plans/{id}/sections/{sid}/edit` | edit any section, including structured step/assessment data |
| `POST /api/lesson-plans/{id}/sections/{sid}/reset` | `[Reset to Source]` for one field (or clear it) |
| `POST /api/lesson-plans/{id}/header` | any header field, template switch, Single/Double |
| `POST /api/lesson-plans/{id}/header/reset` | `{field}` reset one header field to source |
| `POST /api/lesson-plans/{id}/slo/fix` | `[Fix Automatically]` sub-strand heading → lesson heading |
| `POST /api/lesson-plans/{id}/status` | `Draft` / `Final` (Mark Final / Reopen) |
| `POST /api/lesson-plans/{id}/versions` | `{comment}` append version |
| `GET /api/lesson-plans/{id}/versions` | history |
| `GET /api/lesson-plans/{id}/versions/{vid}/diff` | diff |
| `POST /api/lesson-plans/{id}/versions/{vid}/restore` | restore as a new version |
| `POST /api/lesson-plans/{id}/ai/draft` | opt-in Gemini draft of teacher-owned fields |
| `POST /api/lesson-plans/{id}/ai/split` | opt-in split suggestion (never auto-applied) |
| `GET /api/lesson-plans/{id}/web-examples?q=` | top 3 teacher-initiated results |
| `GET /api/lesson-plans/{id}/export.pdf` | **portrait A4**, header repeated on every page |

Scheme PDFs remain **landscape A4** with the header repeated on every page.

---

## Phase 5 - learner Lesson Notes

**One notes document per LESSON.** A scheme row that prints `Week 2 | Lesson 1-5` produces five
separate documents, each with its own focus (sorting by colour, by shape, by size, consolidation,
assessment) - never one note per week and never the same compound sentence repeated.

Generate from either entry point:

- `[→ Lesson Notes (5)]` on a scheme row → notes picker.
- `[→ Generate Notes for This Lesson]` inside a Lesson Plan.

Notes reuse `lesson_derive.py` (no duplicated decomposition) and are learner-facing, not a plan:

- title `[Sub-Strand] - [Focus]`, e.g. `Pre-Number Activities - Sorting by Colour`
- SLO starts `By the end of the lesson, you will be able to:` and repeats the lesson's atomic skill
  verbatim; the word "sub-strand" never appears
- sections in order: title + Week/Lesson/Focus, SLO, Key Vocabulary (word + definition + example +
  `From source` / `AI` / `Web`), What is [Focus]?, Examples (Kenyan context, `[Picture: ...]` for
  primary, diagram descriptions for JSS), Worked Example (numbered steps), Try It Yourself (answers
  hidden by default), Remember, Source footer.

Every paragraph, vocabulary item, example, step and question is editable. Edits are stored on the
note with its own copy and `chunkId` / page number; the `SourceChunk` is never mutated.

Two templates, auto-selected by grade and switchable: `cbe-lesson-notes-v1` (PP1-Grade 6, short
sentences, larger PDF type, picture placeholders, 4 practice questions) and
`cbe-lesson-notes-jss-v1` (Grade 7-9, longer explanations, formulas/steps, diagram descriptions,
5 practice questions).

AI is opt-in and review-only: `[✨ Draft with AI]` needs `GEMINI_API_KEY`; drafts appear in yellow
`AI Draft - Not from source - Review` with **Accept / Reject per section** and **Accept All**.
Reject leaves the section empty. `ai_enriched`, `ai_provider` and `ai_timestamp` are logged.

Web is teacher-initiated only: `[🔍 Find Examples]` returns the top 3 title + URL + snippet and
nothing is inserted until **[Insert as Web Example]**, labelled `[Web Example - {URL}]`.
**[Add My Source]** stores a teacher URL/text as a Teacher Source and lists it in the footer.

| Endpoint | Purpose |
|----------|---------|
| `GET /api/plans/{id}/sections/{sid}/notes-picker` | lessons 1-N, focus, created/open, vetting guard |
| `POST /api/lesson-notes` | `{schemeRowId, lessons:[...]}` or `{lessonPlanId}` |
| `GET /api/lesson-notes?planId=&sectionId=` | list grouped Scheme → Week → Lesson |
| `GET /api/lesson-notes/{id}` | full note: sections, sources, footer, AI status |
| `POST /api/lesson-notes/{id}/sections/{sid}/edit` | body/data edits, `acceptAi`, `rejectAi` |
| `POST /api/lesson-notes/{id}/sections/{sid}/reset` | reset one section |
| `POST /api/lesson-notes/{id}/status` | `Draft` / `Final` |
| `POST /api/lesson-notes/{id}/versions` | `{comment}` append version |
| `GET /api/lesson-notes/{id}/versions/{vid}/diff` | preview changes |
| `POST /api/lesson-notes/{id}/versions/{vid}/restore` | restore as a NEW version |
| `POST /api/lesson-notes/{id}/ai/draft` | opt-in Gemini draft (review-only) |
| `POST /api/lesson-notes/{id}/ai/accept-all` | accept every pending AI section |
| `GET /api/lesson-notes/{id}/search-examples?q=` | teacher-initiated top 3 |
| `POST /api/lesson-notes/{id}/web-examples` | explicit `[Insert as Web Example]` |
| `POST /api/lesson-notes/{id}/sources` | `[Add My Source]` (Teacher Source) |
| `GET /api/lesson-notes/{id}/export.pdf` | portrait A4 learner PDF, answers hidden (`?answers=1` shows) |

---

## Phase 6 — Record of Work Covered (ROW)

Retrospective record of **what WAS taught** (Scheme=Plan, Lesson Plan=How, Notes=What, ROW=Did).
`POST /api/row {planId}` generates one row per Scheme lesson. Work Done is pre-filled as grey-italic
`Planned: …`; Reflection is ALWAYS empty; Status is BLANK — the app never assumes a lesson was taught.
Vetting guard refuses generation while any cited chunk is Pending. Teacher edits set a "Teacher Edited"
badge; `[Reset to Planned]` restores the planned text; `[Mark All Week X as Taught]` sets Status only
(never fills Reflection); Carry Over creates a NEW row and keeps the original. Version history requires
a comment on Save; Restore creates a new version; Mark Final / Unlock controls editing. AI "Suggest
Reflection" is OFF by default, opt-in only, writes to a yellow draft box and never touches Work Done or
Status. Coverage stats + Gaps drawer are computed from ROW, not the Scheme plan. PDF export is landscape
with a Gap Summary page and signature lines.

Endpoints: `POST/GET /api/row`, `POST /api/row/{id}/edit|reset|carry-over`,
`POST /api/row/{id}/ai/reflection|accept|reject`, `GET /api/row/coverage|schemes`,
`POST /api/row/{planId}/bulk-status|status|versions`, `GET /api/row/{planId}/versions/{vid}|diff`,
`POST /api/row/{planId}/versions/{vid}/restore`, `GET /api/row/{planId}/export.pdf`.

## Phase 7 — Term Pack (Export Bundle)

One download, ready for Headteacher / QASO / TSC inspection. Term Pack =
Cover + Coverage Summary + Scheme + All Lesson Plans + All Lesson Notes + ROW + Citations, in that order.
**Mixed orientation in one PDF** (Cover/Coverage/Plans/Notes/Citations portrait; Scheme/ROW landscape).
Entry points: Scheme top bar, approved Library card, and ROW editor — all open the same Export Modal.

The modal has all section checkboxes ON by default, plans/notes sub-options (All / Selected Weeks /
Selected Lessons), and three OFF-by-default options: Include Drafts (adds diagonal
`DRAFT - Not Final` watermark), Include Answers (separate "Answers – Teacher Only" page per Notes doc),
Include Version History (appendix of comments + dates). Format: one PDF or a ZIP of 6 PDFs +
`manifest.json`. Exports run as background jobs with live progress, a 120s timeout, 50MB cap and
30-day auto-delete.

Endpoints: `POST /api/export {planId, includes, format}` → `{jobId}`;
`GET /api/export/{jobId}` → status/progress/fileUrl/pageCount/fileSize;
`GET /api/export/history?planId=`; `GET /api/export/{jobId}/file`; `DELETE /api/export/{jobId}`;
`GET /api/export/plans-for-document?documentId=` (Library entry).

Implementation note: the four existing renderers (`scheme_pdf`, `lesson_pdf`, `notes_pdf`, `row_pdf`)
are inserted verbatim via `fitz.insert_pdf`, so orientation and content are preserved without touching
the editors or the parser engine. New packaging-only renderers draw Cover, Coverage, ROW landscape
table, Answers and Citations; a final pass normalises headers/footers to global `Page X of Y`.

---

## Phase 8 - Coverage Dashboard

Top-level route `#/dashboard` (main nav + Library header link). Read-only aggregate over Scheme + ROW;
coverage is **always** from ROW status, never inferred from the Scheme plan. Coverage formula:
`(Taught + Partially Taught × 0.5) / Planned × 100`. A scheme with no ROW shows `—` and
"ROW not yet created" — never 0% as though nothing had been taught.

Sections: header stats, sortable coverage-by-subject table (expand for per-week detail), CSS/SVG
coverage-by-week chart (click a week to filter gaps), gaps list (Not Taught only — Partially Taught
is tracked separately), next-week planner, and a teacher-written term reflection prompt for subjects
below 80% (AI never fills it).

Gap actions `Carry Over`, `Mark as Taught` (Date + Work Done required), `Skip` (Reason required) and
bulk variants all reuse Phase 6 ROW editing and create a **new** ROW version. Results are cached 60s
per filter set and auto-invalidated by the ROW `updated_at` stamp.

Endpoints: `GET /api/dashboard?term=&year=&grade=&subject=&week=&teacher=`;
`GET|PUT /api/dashboard/reflection`; `GET /api/dashboard/export` (portrait A4 PDF: Cover + Summary +
By Subject + By Week + Gaps); `POST /api/row/{id}/mark-taught`; `POST /api/row/{id}/skip`.
`POST /api/row/{id}/carry-over` now also records an audit version.

---

## Format polish - Scheme + Lesson Plan

Presentation only; no parser, content, data-model, ROW, Dashboard or Export logic changed.

- Scheme web/PDF: exactly nine sticky dark-blue headers (`Week … Reflection (Teacher to fill after
  teaching)`) with the specified widths. PDF repeats the header row on every landscape page.
- KIQs: the `— See Week 1` distributor was removed; full source KIQ text is rendered on every row,
  including existing schemes (expanded at read time from that row's own source snapshot).
- Lesson Plan web/PDF: admin details are a bordered label/value `<table>`, blank values show
  `________`, and stage headings are `Introduction (5 min)`, `Development (25 min)`,
  `Conclusion (5 min)` with no template numbering. Teacher-typed text is untouched.

`python backend/format_polish_test.py` checks the rendered PDFs; parser hashes remain byte-identical.

---

## Deliberately not built yet

Authentication. Everything else through Phase 8 (including Records of Work, the Term Pack export and
the Coverage Dashboard) is built.

## Known engine limitations handled app-side

Both are surfaced in the UI as amber "verify" badges, never silently:

1. **Kiswahili-style designs** with no `STRAND` keyword and all-caps headings (`1.0 DARASANI`)
   leave `strand` null in the engine. The app recovers the name from the chunk's own page.
2. **Shifted experience columns** (Maths 3.2) make the engine read an empty cell. The app
   re-reads the spanned column, joins bullets split across table rows, and flags the chunk.
   That chunk lands at confidence 0.85, so it stays in "Needs Review" for a human check.
