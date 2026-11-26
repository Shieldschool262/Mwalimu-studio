import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { CatalogChunk, CatalogDocument, PlanDocument } from "../types";
import { Badge } from "./ui";

const TERMS = ["Term 1", "Term 2", "Term 3"];

interface Props {
  onCreated: (plan: PlanDocument) => void;
  /** Leave the wizard without generating (back to My Schemes). */
  onCancel?: () => void;
  onToast: (msg: string) => void;
  onError: (msg: string) => void;
}

/** Mirror of the backend allocation so the preview matches what gets generated.
 *  ONE WEEK = ONE ROW: the week is a single integer and lessons restart at 1 each week. */
function previewAllocation(chunks: CatalogChunk[], perWeek: number, weeks: number) {
  let cursor = 1;
  const rows: {
    code: string;
    name: string;
    strand: string;
    lessons: number;
    assumed: boolean;
    weekLabel: string;
    lessonLabel: string;
    partLabel: string;
    resources: string | null;
    assessment: string | null;
    appendixLevel: string | null;
    appendixSource: string | null;
  }[] = [];

  for (const c of chunks) {
    const n = c.lessons && c.lessons > 0 ? c.lessons : 4;
    const nWeeks = Math.max(1, Math.ceil(n / perWeek));
    for (let i = 0; i < nWeeks; i++) {
      const remaining = n - i * perWeek;
      const end = Math.max(1, Math.min(perWeek, remaining));
      rows.push({
        code: c.subStrandCode ?? "",
        name: c.subStrand,
        strand: c.strand ?? "",
        lessons: n,
        assumed: !(c.lessons && c.lessons > 0),
        weekLabel: String(cursor + i),
        lessonLabel: end === 1 ? "1" : `1-${end}`,
        partLabel: `Part ${i + 1} of ${nWeeks}`,
        resources: c.appendixResources ?? null,
        assessment: c.appendixAssessment ?? null,
        appendixLevel: c.appendixLevel ?? null,
        appendixSource: c.appendixSource ?? null,
      });
    }
    cursor += nWeeks;
  }

  const total = chunks.reduce((a, c) => a + (c.lessons && c.lessons > 0 ? c.lessons : 4), 0);
  const capacity = perWeek * weeks;
  return { rows, total, capacity, fits: total <= capacity };
}

export default function CreateDocument({ onCreated, onCancel, onToast, onError }: Props) {
  const [step, setStep] = useState(1);

  // Step 2 - header / allocation inputs
  const [institution, setInstitution] = useState("");
  const [grade, setGrade] = useState("");
  const [subject, setSubject] = useState("");
  const [term, setTerm] = useState("");
  const [year, setYear] = useState(String(new Date().getFullYear()));
  const [lessonsPerWeek, setLessonsPerWeek] = useState(5);
  const [totalWeeks, setTotalWeeks] = useState(13);

  // Step 3 - sources
  const [docs, setDocs] = useState<CatalogDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState("");
  const [blockError, setBlockError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    api
      .planSources()
      .then((c) => setDocs(c.documents))
      .catch((e) => onError((e as Error).message))
      .finally(() => setLoading(false));
  }, [onError]);

  const grades = useMemo(
    () =>
      Array.from(new Set(docs.map((d) => d.grade).filter(Boolean))).sort(
        (a, b) =>
          (parseInt(a.replace(/\D/g, ""), 10) || 0) - (parseInt(b.replace(/\D/g, ""), 10) || 0),
      ),
    [docs],
  );
  const subjects = useMemo(
    () => Array.from(new Set(docs.map((d) => d.subject).filter(Boolean))).sort(),
    [docs],
  );

  // First available grade/subject is a sensible default.
  useEffect(() => {
    if (!grade && grades.length) setGrade(grades[0]);
    if (!subject && subjects.length) setSubject(subjects[0]);
  }, [grades, subjects, grade, subject]);

  const visibleDocs = useMemo(
    () => docs.filter((d) => (!grade || d.grade === grade) && (!subject || d.subject === subject)),
    [docs, grade, subject],
  );

  // Drop selections that no longer belong to the chosen grade/subject.
  useEffect(() => {
    setSelected((prev) => {
      const keep = new Set<string>();
      for (const d of visibleDocs) for (const c of d.chunks) if (c.selectable && prev.has(c.id)) keep.add(c.id);
      return keep;
    });
  }, [visibleDocs]);

  const allChunks = useMemo(() => visibleDocs.flatMap((d) => d.chunks), [visibleDocs]);

  const matches = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return null;
    return new Set(
      allChunks
        .filter((c) =>
          [c.subStrand, c.subStrandCode, c.strand, c.strandCode, ...(c.structuredFields.specific_learning_outcomes ?? [])]
            .filter(Boolean)
            .join(" ")
            .toLowerCase()
            .includes(q),
        )
        .map((c) => c.id),
    );
  }, [allChunks, filter]);

  // Keep the on-screen order identical to what the backend allocates.
  const selectedChunks = useMemo(
    () => allChunks.filter((c) => selected.has(c.id)),
    [allChunks, selected],
  );

  const preview = useMemo(
    () => previewAllocation(selectedChunks, lessonsPerWeek, totalWeeks),
    [selectedChunks, lessonsPerWeek, totalWeeks],
  );

  const headerReady = Boolean(institution.trim() && grade && subject && term && year.trim());
  const canGenerate = headerReady && selected.size >= 1 && !generating;

  const toggle = (c: CatalogChunk) => {
    if (!c.selectable) return;
    setBlockError(null);
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(c.id)) next.delete(c.id);
      else next.add(c.id);
      return next;
    });
  };

  const generate = async () => {
    if (!canGenerate) return;
    setGenerating(true);
    setBlockError(null);
    try {
      const plan = await api.createPlan({
        type: "scheme",
        institution: institution.trim(),
        grade,
        subject,
        term,
        year: year.trim(),
        lessonsPerWeek,
        totalWeeks,
        sourceChunkIds: Array.from(selected),
        templateVersion: "cbe-scheme-v1",
      });
      onToast(plan.allocation.warning ? "Generated (with a warning)" : `Generated ${plan.sectionCount} row(s)`);
      onCreated(plan);
    } catch (e) {
      const msg = (e as Error).message;
      setBlockError(msg);
      onError(msg);
    } finally {
      setGenerating(false);
    }
  };

  const steps = ["Type", "Details", "Sources", "Preview"];
  const stepOk = [true, headerReady, selected.size > 0, selected.size > 0];

  return (
    <div className="space-y-5" data-testid="create-document">
      <div className="flex items-center justify-between gap-3">
        <ol className="flex flex-wrap items-center gap-2 text-xs">
        {steps.map((label, i) => {
          const n = i + 1;
          const active = step === n;
          return (
            <li key={label} className="flex items-center gap-2">
              <button
                onClick={() => setStep(n)}
                className={`flex items-center gap-2 rounded-full border px-3 py-1.5 font-medium transition ${
                  active
                    ? "border-brand-500 bg-brand-50 text-brand-800"
                    : stepOk[i]
                      ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                      : "border-slate-200 bg-white text-slate-600"
                }`}
                data-testid={`step-${n}`}
              >
                <span
                  className={`grid h-4 w-4 place-items-center rounded-full text-[10px] ${
                    stepOk[i] && !active ? "bg-emerald-600 text-white" : "bg-slate-200 text-slate-700"
                  }`}
                >
                  {stepOk[i] && !active ? "✓" : n}
                </span>
                {label}
              </button>
              {i < steps.length - 1 ? <span className="text-slate-300">→</span> : null}
            </li>
          );
        })}
        </ol>
        {onCancel ? (
          <button
            className="btn-ghost px-3 py-1.5 text-xs"
            onClick={onCancel}
            data-testid="create-cancel"
          >
            Cancel
          </button>
        ) : null}
      </div>

      {/* Step 1 - type (Scheme only in Phase 3) */}
      {step === 1 ? (
        <section className="card p-4" data-testid="step-type">
          <h2 className="mb-1 text-sm font-semibold text-slate-800">What are you creating?</h2>
          <p className="mb-3 text-xs text-slate-500">
            Phase 3 builds the official KICD Scheme of Work. Lesson plans come later.
          </p>
          <button
            className="w-full rounded-xl border border-brand-500 bg-brand-50 p-4 text-left ring-2 ring-brand-200"
            onClick={() => setStep(2)}
            data-testid="type-scheme"
          >
            <span className="block text-sm font-semibold text-slate-900">Scheme of Work</span>
            <span className="mt-0.5 block text-xs text-slate-600">
              KICD 10-column format · landscape · one row per sub-strand with week/lesson allocation
            </span>
          </button>
          <p className="mt-3 text-[11px] text-slate-400">
            Lesson Plan and Assessment Tool are disabled until a later phase.
          </p>
        </section>
      ) : null}

      {/* Step 2 - details */}
      {step === 2 ? (
        <section className="card p-4" data-testid="step-details">
          <h2 className="mb-3 text-sm font-semibold text-slate-800">Scheme details</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="text-xs font-medium text-slate-600 sm:col-span-2">
              Institution / School *
              <input
                className="input mt-1 w-full"
                value={institution}
                onChange={(e) => setInstitution(e.target.value)}
                placeholder="e.g. Nairobi Primary School"
                data-testid="create-institution"
              />
            </label>
            <label className="text-xs font-medium text-slate-600">
              Grade *
              <select className="input mt-1 w-full" value={grade} onChange={(e) => setGrade(e.target.value)} data-testid="create-grade">
                <option value="">Select grade…</option>
                {grades.map((g) => (
                  <option key={g} value={g}>
                    {g}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs font-medium text-slate-600">
              Learning Area *
              <select className="input mt-1 w-full" value={subject} onChange={(e) => setSubject(e.target.value)} data-testid="create-subject">
                <option value="">Select learning area…</option>
                {subjects.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs font-medium text-slate-600">
              Term *
              <select className="input mt-1 w-full" value={term} onChange={(e) => setTerm(e.target.value)} data-testid="create-term">
                <option value="">Select term…</option>
                {TERMS.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs font-medium text-slate-600">
              Year *
              <input
                className="input mt-1 w-full"
                value={year}
                onChange={(e) => setYear(e.target.value)}
                placeholder="e.g. 2025"
                data-testid="create-year"
              />
            </label>
            <label className="text-xs font-medium text-slate-600">
              Lessons per week
              <input
                type="number"
                min={1}
                max={20}
                className="input mt-1 w-full"
                value={lessonsPerWeek}
                onChange={(e) => setLessonsPerWeek(Math.max(1, Number(e.target.value) || 1))}
                data-testid="create-lessons-per-week"
              />
            </label>
            <label className="text-xs font-medium text-slate-600">
              Total teaching weeks
              <input
                type="number"
                min={1}
                max={20}
                className="input mt-1 w-full"
                value={totalWeeks}
                onChange={(e) => setTotalWeeks(Math.max(1, Number(e.target.value) || 1))}
                data-testid="create-total-weeks"
              />
            </label>
          </div>
          <p className="mt-2 text-[11px] text-slate-500">
            Capacity: {lessonsPerWeek} × {totalWeeks} = <strong>{lessonsPerWeek * totalWeeks}</strong>{" "}
            lessons this term.
          </p>
          <div className="mt-3 flex justify-end">
            <button className="btn-primary" disabled={!headerReady} onClick={() => setStep(3)} data-testid="step2-next">
              Select sources →
            </button>
          </div>
        </section>
      ) : null}

      {/* Step 3 - sources */}
      {step === 3 ? (
        <section className="card p-4" data-testid="source-picker">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-semibold text-slate-800">Select sub-strands</h2>
            <Badge tone="slate">
              {grade || "Any grade"} · {subject || "Any learning area"}
            </Badge>
            <input
              className="input ml-auto w-64"
              placeholder="Search sub-strands… e.g. Whole Numbers"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              data-testid="source-search"
            />
          </div>
          <p className="mt-2 text-xs text-slate-500">
            Only <strong>Vetted</strong> sub-strands can be selected. Vetted means outcomes, experiences
            and Key Inquiry Questions all exist and a teacher has approved the sub-strand.
          </p>

          {loading ? (
            <p className="py-8 text-center text-sm text-slate-500">Loading sources…</p>
          ) : visibleDocs.length === 0 ? (
            <p className="py-8 text-center text-sm text-slate-500">
              No curriculum designs for this grade and learning area. Upload and approve one first.
            </p>
          ) : (
            <div className="mt-3 space-y-4">
              {visibleDocs.map((doc) => (
                <SourceDocument key={doc.documentId} doc={doc} selected={selected} matches={matches} onToggle={toggle} />
              ))}
            </div>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-slate-100 pt-3">
            <span className="text-xs text-slate-600" data-testid="selected-count">
              Selected: <strong>{selected.size}</strong> sub-strand{selected.size === 1 ? "" : "s"}
              {selected.size ? ` · ${preview.total} lessons` : ""}
            </span>
            <span className="ml-auto flex items-center gap-2">
              <button className="btn-ghost" onClick={() => setStep(2)}>
                ← Back
              </button>
              <button className="btn-primary" disabled={selected.size === 0} onClick={() => setStep(4)} data-testid="step3-next">
                Preview →
              </button>
            </span>
          </div>
        </section>
      ) : null}

      {/* Step 4 - preview + generate */}
      {step === 4 ? (
        <section className="card p-4" data-testid="step-preview">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-semibold text-slate-800">Preview</h2>
            <Badge tone="slate">
              {lessonsPerWeek}/week × {totalWeeks} weeks = {preview.capacity} lessons
            </Badge>
            <Badge tone={preview.fits ? "green" : "amber"} data-testid="preview-total">
              {preview.total} lessons needed
            </Badge>
          </div>

          {!preview.fits ? (
            <p className="mt-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900" data-testid="preview-warning">
              Selected sub-strands need {preview.total} lessons but term has {preview.capacity} - remove{" "}
              {preview.total - preview.capacity} lessons or extend weeks. Nothing will be truncated.
            </p>
          ) : null}

          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-left text-xs" data-testid="preview-table">
              <thead className="bg-slate-100 text-slate-700">
                <tr>
                  <th className="px-2 py-1.5">Week</th>
                  <th className="px-2 py-1.5">Lesson</th>
                  <th className="px-2 py-1.5">Strand</th>
                  <th className="px-2 py-1.5">Sub-Strand</th>
                  <th className="px-2 py-1.5">Lessons</th>
                  <th className="px-2 py-1.5">Learning Resources</th>
                  <th className="px-2 py-1.5">Assessment</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {preview.rows.map((r, i) => (
                  <tr key={`${r.code}-${i}`} data-testid={`preview-row-${r.code}`}>
                    <td className="px-2 py-1.5 font-mono" data-testid="preview-week">
                      {r.weekLabel}
                    </td>
                    <td className="px-2 py-1.5 font-mono" data-testid="preview-lesson">
                      {r.lessonLabel}
                    </td>
                    <td className="px-2 py-1.5 text-slate-600">{r.strand}</td>
                    <td className="px-2 py-1.5 font-medium text-slate-900">
                      {r.code} {r.name}
                      <div className="text-[10px] font-normal text-slate-500">{r.partLabel}</div>
                    </td>
                    <td className="px-2 py-1.5">
                      {r.lessons}
                      {r.assumed ? (
                        <span className="ml-1 text-amber-700" title="Lessons not in source - assumed 4, edit">
                          (assumed)
                        </span>
                      ) : null}
                    </td>
                    <td
                      className="max-w-[190px] px-2 py-1.5 align-top text-slate-700"
                      data-testid={`preview-resources-${r.code}`}
                      data-from-appendix={r.resources ? "yes" : "no"}
                      title={r.appendixSource ?? undefined}
                    >
                      {r.resources ? (
                        <>
                          <span className="mr-1 inline-block rounded bg-slate-100 px-1 py-[1px] text-[9px] font-medium uppercase text-slate-500">
                            Appendix
                          </span>
                          <span className="line-clamp-3">{r.resources}</span>
                        </>
                      ) : (
                        <span className="italic text-slate-400">— Teacher to fill</span>
                      )}
                    </td>
                    <td
                      className="max-w-[190px] px-2 py-1.5 align-top text-slate-700"
                      data-testid={`preview-assessment-${r.code}`}
                      data-from-appendix={r.assessment ? "yes" : "no"}
                      title={r.appendixSource ?? undefined}
                    >
                      {r.assessment ? (
                        <>
                          <span className="mr-1 inline-block rounded bg-slate-100 px-1 py-[1px] text-[9px] font-medium uppercase text-slate-500">
                            Appendix
                          </span>
                          <span className="line-clamp-3">{r.assessment}</span>
                        </>
                      ) : (
                        <span className="italic text-slate-400">Observation, oral questions</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {blockError ? (
            <div className="mt-3 rounded-xl border border-rose-300 bg-rose-50 p-3 text-sm text-rose-800" data-testid="generate-error" role="alert">
              {blockError.split(" | ").map((line) => (
                <p key={line}>{line}</p>
              ))}
            </div>
          ) : null}

          <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
            <span className="text-xs text-slate-500">
              {institution || "No school"} · {grade} · {term} {year}
            </span>
            <span className="ml-auto flex gap-2">
              <button className="btn-ghost" onClick={() => setStep(3)}>
                ← Back
              </button>
              <button className="btn-primary" disabled={!canGenerate} onClick={generate} data-testid="generate-btn">
                {generating ? "Generating…" : "Generate Scheme"}
              </button>
            </span>
          </div>
        </section>
      ) : null}
    </div>
  );
}

function SourceDocument({
  doc,
  selected,
  matches,
  onToggle,
}: {
  doc: CatalogDocument;
  selected: Set<string>;
  matches: Set<string> | null;
  onToggle: (c: CatalogChunk) => void;
}) {
  const strands = useMemo(() => {
    const map = new Map<string, { label: string; chunks: CatalogChunk[] }>();
    for (const c of doc.chunks) {
      const key = `${c.strandCode ?? ""}|${c.strand ?? ""}`;
      if (!map.has(key)) {
        map.set(key, {
          label: c.strand ? `${c.strandCode ? `${c.strandCode} ` : ""}${c.strand}` : "Unassigned",
          chunks: [],
        });
      }
      map.get(key)!.chunks.push(c);
    }
    return Array.from(map.values());
  }, [doc]);

  const visible = (list: CatalogChunk[]) => (matches ? list.filter((c) => matches.has(c.id)) : list);
  const shown = strands.filter((s) => visible(s.chunks).length > 0);
  if (matches && shown.length === 0) return null;

  return (
    <div className="rounded-xl border border-slate-200" data-testid={`source-doc-${doc.documentId}`}>
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 bg-slate-50 px-3 py-2">
        <span className="text-sm font-semibold text-slate-900">{doc.subject}</span>
        <Badge tone="slate">{doc.grade}</Badge>
        <Badge tone={doc.allVetted ? "green" : "amber"} data-testid="doc-vetting">
          Vetted {doc.vettedCount}/{doc.totalCount}
        </Badge>
        <span className="ml-auto truncate text-[11px] text-slate-500" title={doc.fileName}>
          {doc.fileName}
        </span>
      </div>
      <div className="divide-y divide-slate-100">
        {shown.map((strand, i) => {
          const chunks = visible(strand.chunks);
          const vetted = strand.chunks.filter((c) => c.selectable).length;
          return (
            <div key={`${strand.label}-${i}`} className="px-3 py-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold uppercase tracking-wide text-slate-700">{strand.label}</span>
                {vetted === strand.chunks.length ? (
                  <Badge tone="green">
                    Vetted {vetted}/{strand.chunks.length} ✓
                  </Badge>
                ) : (
                  <Badge tone="amber">
                    Vetted {vetted}/{strand.chunks.length} — some cannot be selected
                  </Badge>
                )}
              </div>
              <ul className="mt-1.5 space-y-1">
                {chunks.map((c) => {
                  const isSel = selected.has(c.id);
                  return (
                    <li key={c.id}>
                      <label
                        className={`flex cursor-pointer items-start gap-2 rounded-lg px-2 py-1.5 text-sm ${
                          c.selectable
                            ? isSel
                              ? "bg-brand-50 ring-1 ring-brand-200"
                              : "hover:bg-slate-50"
                            : "cursor-not-allowed bg-slate-50 opacity-70"
                        }`}
                        data-testid={`chunk-row-${c.id}`}
                        data-selectable={c.selectable ? "yes" : "no"}
                      >
                        <input
                          type="checkbox"
                          checked={isSel}
                          disabled={!c.selectable}
                          onChange={() => onToggle(c)}
                          className="mt-0.5 h-4 w-4 accent-brand-600"
                          data-testid={`chunk-check-${c.id}`}
                        />
                        <span className="min-w-0 flex-1">
                          <span className="flex flex-wrap items-center gap-1.5">
                            <span className="font-mono text-xs text-slate-500">{c.subStrandCode}</span>
                            <span className="font-medium text-slate-900">{c.subStrand}</span>
                            {c.lessons ? (
                              <span className="text-[11px] text-slate-400">{c.lessons} lessons</span>
                            ) : null}
                            {c.pageNumber ? <span className="text-[11px] text-slate-400">p.{c.pageNumber}</span> : null}
                            {c.selectable ? (
                              <Badge tone="green">Vetted</Badge>
                            ) : (
                              <Badge tone="amber" data-testid="pending-badge">
                                Missing {c.missingCore.map((m) => (m === "Key Inquiry Questions" ? "KIQs" : m)).join(", ")}
                              </Badge>
                            )}
                          </span>
                          {!c.selectable && c.missingCore.length ? (
                            <span className="mt-0.5 block text-[11px] text-amber-700">
                              Pending — cannot select. Fix in Library.
                            </span>
                          ) : null}
                        </span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </div>
    </div>
  );
}
