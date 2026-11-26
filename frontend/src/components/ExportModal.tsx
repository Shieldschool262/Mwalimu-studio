import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type {
  ExportFormat,
  ExportIncludes,
  ExportJob,
  ExportPlanOption,
  ExportSelection,
  ExportSelectionMode,
} from "../types";

type Props = {
  planId: string | null;
  documentId?: string | null;
  onClose: () => void;
  onToast: (msg: string) => void;
  onError: (msg: string) => void;
};

const defaultSelection = (): ExportSelection => ({
  include: true, mode: "all", weeks: [], lessonIds: [],
});

const defaultIncludes = (): ExportIncludes => ({
  cover: true, coverage: true, scheme: true,
  plans: defaultSelection(), notes: defaultSelection(),
  row: true, citations: true,
  includeDrafts: false, includeAnswers: false, includeVersionHistory: false,
  progress: false, progressConfirm: "",
});

const humanSize = (n: number) => {
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${n} B`;
};

/** Phase 7: Term Pack export modal. Reached from Scheme, Library and ROW views. */
export default function ExportModal({ planId, documentId, onClose, onError }: Props) {
  const [includes, setIncludes] = useState<ExportIncludes>(defaultIncludes);
  const [format, setFormat] = useState<ExportFormat>("pdf");
  const [job, setJob] = useState<ExportJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [weeks, setWeeks] = useState<number[]>([]);
  const [lessonOptions, setLessonOptions] = useState<{ id: string; label: string; kind: "plan" | "note" }[]>([]);
  const [planOptions, setPlanOptions] = useState<ExportPlanOption[]>([]);
  const [chosenPlan, setChosenPlan] = useState<string | null>(planId);
  /** Phase 10: learner names must be explicitly opted into and confirmed. */
  const [progressConfirm, setProgressConfirm] = useState("");

  useEffect(() => {
    if (planId) setChosenPlan(planId);
  }, [planId]);

  // Library entry: a card only knows the documentId - resolve candidate schemes.
  useEffect(() => {
    if (!documentId) return;
    let alive = true;
    api.exportPlansForDocument(documentId)
      .then((r) => { if (alive) {
        setPlanOptions(r.plans || []);
        if (!chosenPlan && r.plans?.length) setChosenPlan(r.plans[0].id);
      }})
      .catch(() => { if (alive) setPlanOptions([]); });
    return () => { alive = false; };
  }, [documentId, chosenPlan]);

  // Load weeks + lesson ids for the "selected weeks / lessons" sub-options.
  useEffect(() => {
    if (!chosenPlan) return;
    let alive = true;
    Promise.all([
      api.lessonPlans({ planId: chosenPlan }).catch(() => ({ plans: [] })),
      api.lessonNotes({ planId: chosenPlan }).catch(() => ({ notes: [] })),
    ]).then(([pl, nt]) => {
      if (!alive) return;
      const w = new Set<number>();
      for (const p of pl.plans || []) if (p.week) w.add(Number(p.week));
      for (const n of nt.notes || []) if (n.week) w.add(Number(n.week));
      setWeeks([...w].sort((a, b) => a - b));
      setLessonOptions([
        ...(pl.plans || []).map((p) => ({ id: p.id, label: `Week ${p.week} Lesson ${p.lesson} · ${p.focus || p.subStrand || ""}`, kind: "plan" as const })),
        ...(nt.notes || []).map((n) => ({ id: n.id, label: `Week ${n.week} Lesson ${n.lesson} · ${n.focus || n.subStrand || ""}`, kind: "note" as const })),
      ]);
    });
    return () => { alive = false; };
  }, [chosenPlan]);

  const selection = (key: "plans" | "notes") => includes[key];

  const setSelection = (key: "plans" | "notes", patch: Partial<ExportSelection>) =>
    setIncludes((prev) => ({ ...prev, [key]: { ...prev[key], ...patch } }));

  const toggle = (key: keyof ExportIncludes) =>
    setIncludes((prev) => ({ ...prev, [key]: !prev[key] }));

  // Poll the job every 2s while building.
  useEffect(() => {
    if (!job || (job.status !== "queued" && job.status !== "building")) return;
    let alive = true;
    const timer = window.setInterval(() => {
      api.exportJob(job.id)
        .then((next) => { if (alive) setJob(next); })
        .catch(() => { if (alive) setJob((p) => p && ({ ...p, status: "failed", error: "Could not check export status." })); });
    }, 2000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [job?.id, job?.status]);

  const start = useCallback(async () => {
    if (!chosenPlan) { onError("Choose a scheme to export."); return; }
    if (includes.progress && progressConfirm.trim() !== "I understand") {
      onError('Type "I understand" to include learner names in the Term Pack.');
      return;
    }
    setBusy(true);
    setJob(null);
    try {
      const started = await api.exportStart(chosenPlan,
        { ...includes, progressConfirm: includes.progress ? progressConfirm.trim() : "" }, format);
      const fresh = await api.exportJob(started.jobId);
      setJob(fresh);
    } catch (e) {
      onError(e instanceof Error ? e.message : "Could not start export.");
    } finally {
      setBusy(false);
    }
  }, [chosenPlan, includes, format, onError, progressConfirm]);

  const done = job?.status === "done";
  const failed = job?.status === "failed";
  const building = job?.status === "queued" || job?.status === "building";

  const sectionsSummary = useMemo(() => {
    const s = job?.manifest?.sections || [];
    return s.map((x) => `${x.name} ${x.pages}p`).join(" · ");
  }, [job]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" data-testid="export-modal">
      <div className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-card bg-white p-5 shadow-xl">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-lg font-semibold text-slate-900">📦 Export Term Pack</h3>
            <p className="mt-0.5 text-xs text-slate-500">
              One file, ready to share for inspection. Parser engine and editors are untouched.
            </p>
          </div>
          <button className="btn-ghost px-2 py-1 text-xs" onClick={onClose} data-testid="export-close">Close</button>
        </div>

        {planOptions.length > 0 && (
          <label className="mt-4 block text-xs font-medium text-slate-600">
            Scheme
            <select className="input mt-1 w-full" value={chosenPlan || ""}
              onChange={(e) => setChosenPlan(e.target.value)} data-testid="export-plan-select">
              <option value="">Choose a scheme…</option>
              {planOptions.map((p) => (
                <option key={p.id} value={p.id}>{p.title}</option>
              ))}
            </select>
          </label>
        )}

        <div className="mt-4 rounded-card border border-line bg-slate-50 p-3">
          <p className="section-label mb-2">What to include</p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            <Check label="Cover Page" checked={includes.cover} onChange={() => toggle("cover")} testId="export-inc-cover" />
            <Check label="Coverage Summary" checked={includes.coverage} onChange={() => toggle("coverage")} testId="export-inc-coverage" />
            <Check label="Scheme of Work (12 weeks)" checked={includes.scheme} onChange={() => toggle("scheme")} testId="export-inc-scheme" />
            <Check label="Record of Work (60 rows)" checked={includes.row} onChange={() => toggle("row")} testId="export-inc-row" />
            <Check label="Citations / Sources" checked={includes.citations} onChange={() => toggle("citations")} testId="export-inc-citations" />
            <Check label="Include Progress (contains learner names)" checked={Boolean(includes.progress)}
              onChange={() => toggle("progress")} testId="export-inc-progress" />
          </div>
          {includes.progress ? (
            <div className="mt-2 rounded border border-rose-300 bg-rose-50 p-2 text-xs text-rose-800"
                 data-testid="export-progress-warning">
              Term Pack will contain learner names. Only share with Headteacher if required.
              Type <strong>I understand</strong> to confirm.
              <input className="input mt-1 w-full" value={progressConfirm}
                     onChange={(e) => setProgressConfirm(e.target.value)}
                     placeholder="I understand" data-testid="export-progress-confirm" />
            </div>
          ) : null}

          <SelectionRow
            title="Lesson Plans"
            selection={selection("plans")}
            weeks={weeks}
            lessonOptions={lessonOptions.filter((o) => o.kind === "plan")}
            onChange={(patch) => setSelection("plans", patch)}
            testId="plans"
          />
          <SelectionRow
            title="Lesson Notes"
            selection={selection("notes")}
            weeks={weeks}
            lessonOptions={lessonOptions.filter((o) => o.kind === "note")}
            onChange={(patch) => setSelection("notes", patch)}
            testId="notes"
          />
        </div>

        <div className="mt-4 rounded-card border border-line p-3">
          <p className="section-label mb-2">Options (off by default)</p>
          <Check label="Include Drafts? (adds “DRAFT - Not Final” watermark)" checked={includes.includeDrafts}
            onChange={() => toggle("includeDrafts")} testId="export-inc-drafts" />
          <Check label="Include Answers in Lesson Notes? (separate “Teacher Only” page)" checked={includes.includeAnswers}
            onChange={() => toggle("includeAnswers")} testId="export-inc-answers" />
          <Check label="Include Version History? (appendix of comments + dates)" checked={includes.includeVersionHistory}
            onChange={() => toggle("includeVersionHistory")} testId="export-inc-versions" />
        </div>

        <div className="mt-4 rounded-card border border-line p-3">
          <p className="section-label mb-2">Format</p>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="radio" name="export-format" checked={format === "pdf"}
              onChange={() => setFormat("pdf")} data-testid="export-format-pdf" />
            <span><strong>One PDF</strong> (Term Pack.pdf) — mixed orientation, recommended</span>
          </label>
          <label className="mt-1.5 flex items-center gap-2 text-sm text-slate-700">
            <input type="radio" name="export-format" checked={format === "zip"}
              onChange={() => setFormat("zip")} data-testid="export-format-zip" />
            <span><strong>ZIP</strong> — 6 PDFs + manifest.json</span>
          </label>
        </div>

        {building && (
          <div className="mt-4 rounded-card border border-brand-200 bg-brand-50 p-3" data-testid="export-progress">
            <div className="flex items-center justify-between text-xs font-medium text-brand-800">
              <span>{job?.progressText || "Preparing…"}</span><span>{job?.progress ?? 0}%</span>
            </div>
            <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-brand-100">
              <div className="h-full bg-brand-600 transition-all" style={{ width: `${job?.progress ?? 0}%` }} />
            </div>
          </div>
        )}

        {failed && (
          <div className="mt-4 rounded-card border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800" data-testid="export-error">
            <strong>Export failed:</strong> {job?.error || "Unknown error."}
          </div>
        )}

        {done && (
          <div className="mt-4 rounded-card border border-green-200 bg-green-50 p-3" data-testid="export-done">
            <p className="text-sm font-medium text-green-900">Ready — {job?.fileName}</p>
            <p className="mt-0.5 text-xs text-green-800">
              {job?.pageCount} pages · {humanSize(job?.fileSize || 0)} · {sectionsSummary}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <a className="btn-primary px-2.5 py-1.5 text-xs" href={api.exportFileUrl(job!.id)} download data-testid="export-download">
                Download {format === "zip" ? "Term Pack.zip" : "Term Pack.pdf"}
              </a>
              <button className="btn-ghost px-2.5 py-1.5 text-xs" onClick={() => void start()} data-testid="export-again">
                Download Again (rebuild)
              </button>
            </div>
          </div>
        )}

        <div className="mt-5 flex justify-end gap-2 border-t border-line pt-4">
          <button className="btn-ghost px-3 py-1.5 text-sm" onClick={onClose} data-testid="export-cancel">
            {done ? "Close" : "Cancel"}
          </button>
          {!done && (
            <button className="btn-primary px-3 py-1.5 text-sm" onClick={() => void start()}
              disabled={busy || building || !chosenPlan || (includes.progress && progressConfirm.trim() !== "I understand")}
              data-testid="export-start">
              {busy || building ? "Building…" : "Export"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function Check({ label, checked, onChange, testId }: {
  label: string; checked: boolean; onChange: () => void; testId: string;
}) {
  return (
    <label className="flex items-start gap-2 text-sm text-slate-700" data-testid={testId}>
      <input type="checkbox" checked={checked} onChange={onChange} className="mt-0.5" />
      <span>{label}</span>
    </label>
  );
}

function SelectionRow({ title, selection, weeks, lessonOptions, onChange, testId }: {
  title: string;
  selection: ExportSelection;
  weeks: number[];
  lessonOptions: { id: string; label: string }[];
  onChange: (patch: Partial<ExportSelection>) => void;
  testId: string;
}) {
  const [picker, setPicker] = useState(false);
  const mode = selection.mode;
  return (
    <div className="mt-3 rounded border border-line bg-white p-2.5" data-testid={`export-${testId}`}>
      <div className="flex items-center gap-2">
        <input type="checkbox" checked={selection.include}
          onChange={(e) => onChange({ include: e.target.checked })}
          data-testid={`export-${testId}-include`} />
        <span className="text-sm font-medium text-slate-800">{title}</span>
      </div>
      {selection.include && (
        <div className="mt-2 pl-6">
          <div className="flex flex-wrap gap-3 text-xs text-slate-700">
            {(["all", "weeks", "selected"] as ExportSelectionMode[]).map((m) => (
              <label key={m} className="flex items-center gap-1">
                <input type="radio" name={`${testId}-mode`} checked={mode === m}
                  onChange={() => onChange({ mode: m })} data-testid={`export-${testId}-mode-${m}`} />
                <span>{m === "all" ? "All" : m === "weeks" ? "Selected Weeks" : "Selected Lessons"}</span>
              </label>
            ))}
          </div>
          {mode === "weeks" && (
            <div className="mt-2 flex flex-wrap gap-2">
              {weeks.length === 0 && <span className="text-xs text-slate-400">No weeks found yet.</span>}
              {weeks.map((w) => (
                <label key={w} className="flex items-center gap-1 rounded border border-line px-1.5 py-0.5 text-xs">
                  <input type="checkbox" checked={selection.weeks.includes(w)}
                    onChange={(e) => onChange({
                      weeks: e.target.checked ? [...selection.weeks, w] : selection.weeks.filter((x) => x !== w),
                    })} data-testid={`export-${testId}-week-${w}`} />
                  W{w}
                </label>
              ))}
            </div>
          )}
          {mode === "selected" && (
            <div className="mt-2">
              <button className="btn-ghost px-2 py-1 text-xs" onClick={() => setPicker((p) => !p)}
                data-testid={`export-${testId}-picker`}>
                {picker ? "Hide lessons" : `Choose lessons (${selection.lessonIds.length} selected)`}
              </button>
              {picker && (
                <div className="mt-1 max-h-40 overflow-y-auto rounded border border-line p-2">
                  {lessonOptions.length === 0 && <p className="text-xs text-slate-400">No lessons generated yet.</p>}
                  {lessonOptions.map((o) => (
                    <label key={o.id} className="flex items-center gap-2 py-0.5 text-xs text-slate-700">
                      <input type="checkbox" checked={selection.lessonIds.includes(o.id)}
                        onChange={(e) => onChange({
                          lessonIds: e.target.checked
                            ? [...selection.lessonIds, o.id]
                            : selection.lessonIds.filter((x) => x !== o.id),
                        })} />
                      {o.label}
                    </label>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
