/** Phase 10 - My Learners, Assessment Grid, Progress and IEP.
 * Private to the signed-in teacher. No school, headteacher or sharing concepts.
 */
import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../api";
import type {
  AssessmentAuditEntry, AssessmentContext, AssessmentLevel, AssessOptions, AssessTarget,
  Iep, Learner, LearnersList, LearnerSummary, ProgressData,
} from "../types";

export type LearnersView = "list" | "progress" | "iep";

interface Props {
  view: LearnersView;
  assessTarget?: AssessTarget | null;
  onNavigate: (view: LearnersView) => void;
  onAssessed?: () => void;
  onToast: (msg: string) => void;
  onError: (msg: string) => void;
}

const LEVELS: AssessmentLevel[] = ["Not Assessed", "Below", "Approaching", "Meets", "Exceeds"];
const SOURCES = ["Class Activity", "Oral", "Written Task", "Rubric p.15", "Observation"];
const LEVEL_COLOR: Record<string, string> = {
  "Not Assessed": "bg-slate-100 text-slate-600",
  Below: "bg-rose-100 text-rose-800",
  Approaching: "bg-amber-100 text-amber-900",
  Meets: "bg-emerald-100 text-emerald-800",
  Exceeds: "bg-teal-800 text-white",
};
const today = () => new Date().toISOString().slice(0, 10);

function Modal({ title, children, onClose, wide = false, testId }: {
  title: string; children: ReactNode; onClose: () => void;
  wide?: boolean; testId?: string;
}) {
  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-4">
      <div className={`my-4 w-full ${wide ? "max-w-5xl" : "max-w-2xl"} rounded-xl bg-white p-5 shadow-2xl`}
           data-testid={testId}>
        <div className="mb-3 flex items-start justify-between gap-3">
          <h2 className="text-base font-bold text-ink">{title}</h2>
          <button className="text-lg leading-none text-muted hover:text-ink" onClick={onClose}
                  data-testid="modal-close">✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

function LevelBadge({ level }: { level: string }) {
  return <span className={`badge ${LEVEL_COLOR[level] || "bg-slate-100 text-slate-700"}`}>{level}</span>;
}

function SummaryCounts({ summary }: { summary: LearnerSummary | null }) {
  return (
    <p className="mt-1 text-xs text-muted" data-testid="ml-summary-counts">
      {summary
        ? `${summary.active} Active · ${summary.needsSupport} Needs Support · ${summary.iepsActive} IEPs Active · ${summary.iepReviewsDue} Reviews Due`
        : ""}
    </p>
  );
}

function Field({ label, value, onChange, required = false, type = "text", testId, placeholder }: {
  label: string; value: string; onChange: (v: string) => void; required?: boolean;
  type?: string; testId?: string; placeholder?: string;
}) {
  return (
    <label className="block">
      <span className="field-label">{label}{required ? " *" : ""}</span>
      <input className="input mt-1 w-full" type={type} value={value} placeholder={placeholder}
             onChange={(e) => onChange(e.target.value)} data-testid={testId} />
    </label>
  );
}

/* -------------------------------------------------------------------------- */
/* Learner list                                                                */
/* -------------------------------------------------------------------------- */
function LearnersList({ summary, onAssess, onIep, onToast, onError }: {
  summary: LearnerSummary | null;
  onAssess: (learner: Learner) => void;
  onIep: (learner: Learner) => void;
  onToast: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const [data, setData] = useState<LearnersList | null>(null);
  const [filters, setFilters] = useState({ q: "", grade: "", learningArea: "", className: "", status: "Active" });
  const [form, setForm] = useState<Learner | null>(null);
  const [deleting, setDeleting] = useState<Learner | null>(null);
  const [confirmName, setConfirmName] = useState("");
  const [csvOpen, setCsvOpen] = useState(false);

  const load = useCallback(() => {
    api.learners(filters).then(setData).catch((e) => onError((e as Error).message));
  }, [filters, onError]);
  useEffect(() => { load(); }, [load]);

  const remove = async () => {
    if (!deleting) return;
    try {
      const r = await api.deleteLearner(deleting.id, confirmName);
      onToast(`Deleted ${r.deleted} and their records.`);
      setDeleting(null); setConfirmName(""); load();
    } catch (e) { onError((e as Error).message); }
  };

  const exportClass = (group: { grade: string; learningArea: string; className: string; learners: Learner[] }) => {
    const lines = ["firstName,lastName,admissionNo,gender,className"];
    for (const l of group.learners) {
      lines.push([l.firstName, l.lastName, l.admissionNo, l.gender, l.className]
        .map((x) => `"${String(x).replace(/"/g, '""')}"`).join(","));
    }
    const url = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url; a.download = `class-${group.className || "list"}.csv`; a.click();
    URL.revokeObjectURL(url);
    onToast("Class list downloaded. Keep it private.");
  };

  return (
    <div className="space-y-4" data-testid="ml-root">
      <section className="card p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-extrabold text-ink">My Learners - Class Lists</h1>
            <p className="text-xs text-muted">Private to your My Space. No school account, no sharing.</p>
            <SummaryCounts summary={summary} />
          </div>
          <div className="flex gap-2">
            <button className="btn-ghost px-3 py-1.5 text-xs" onClick={() => setCsvOpen(true)}
                    data-testid="ml-import">Import CSV</button>
            <button className="btn-primary px-3 py-1.5 text-xs" onClick={() => setForm({
              id: "", firstName: "", lastName: "", name: "", grade: filters.grade || "Grade 3",
              learningArea: filters.learningArea || "Mathematics", className: filters.className || "",
              admissionNo: "", gender: "Prefer not to say", status: "Active", createdAt: "", updatedAt: "",
            })} data-testid="ml-add">+ Add Learner</button>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-end gap-2 border-t border-line pt-3">
          <Field label="Search" value={filters.q} onChange={(q) => setFilters({ ...filters, q })}
                 testId="ml-search" placeholder="Name or admission no" />
          <Field label="Grade" value={filters.grade} onChange={(grade) => setFilters({ ...filters, grade })}
                 testId="ml-filter-grade" placeholder="Grade 3" />
          <Field label="Learning Area" value={filters.learningArea}
                 onChange={(learningArea) => setFilters({ ...filters, learningArea })}
                 testId="ml-filter-area" placeholder="Mathematics" />
          <Field label="Class" value={filters.className} onChange={(className) => setFilters({ ...filters, className })}
                 testId="ml-filter-class" placeholder="3B" />
          <label className="block">
            <span className="field-label">Status</span>
            <select className="input mt-1" value={filters.status} data-testid="ml-filter-status"
                    onChange={(e) => setFilters({ ...filters, status: e.target.value })}>
              <option value="Active">Active</option><option value="Transferred">Transferred</option>
              <option value="Left">Left</option><option value="">All</option>
            </select>
          </label>
        </div>
      </section>

      {!data?.groups.length ? (
        <section className="card p-8 text-center text-sm text-muted" data-testid="ml-empty">
          No learners in this view. Add one or import a class list.
        </section>
      ) : data.groups.map((group) => (
        <section className="card overflow-hidden" key={`${group.grade}-${group.learningArea}-${group.className}`}>
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line bg-slate-50 px-4 py-3">
            <h2 className="text-sm font-bold text-ink" data-testid="ml-group-title">
              {group.grade || "All Grades"} {group.learningArea || "All Areas"} - {group.className || "Class"} ({group.count} learners)
            </h2>
            <div className="flex gap-2">
              <button className="btn-mini" onClick={() => exportClass(group)} data-testid="ml-export-class">Export Class List</button>
            </div>
          </div>
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 text-muted">
              <tr><th className="px-4 py-2">Learner</th><th>Admission No</th><th>Gender</th><th>Status</th><th className="text-right pr-4">Actions</th></tr>
            </thead>
            <tbody>
              {group.learners.map((l) => (
                <tr className="border-t border-line" key={l.id} data-testid="ml-learner-row">
                  <td className="px-4 py-2 font-semibold text-ink">{l.name}</td>
                  <td>{l.admissionNo || "—"}</td><td>{l.gender || "—"}</td>
                  <td><span className="badge bg-slate-100 text-slate-700">{l.status}</span></td>
                  <td className="pr-4 text-right">
                    <button className="btn-mini" onClick={() => onAssess(l)} data-testid="ml-assess">Assess</button>{" "}
                    <button className="btn-mini" onClick={() => onIep(l)} data-testid="ml-iep">IEP</button>{" "}
                    <button className="btn-mini" onClick={() => setForm(l)}>Edit</button>{" "}
                    <button className="btn-mini" onClick={() => api.archiveLearner(l.id, l.status === "Active" ? "Left" : "Active")
                      .then(load).catch((e) => onError((e as Error).message))} data-testid="ml-archive">
                      {l.status === "Active" ? "Archive" : "Restore"}
                    </button>{" "}
                    <button className="btn-mini !text-rose-700" onClick={() => { setDeleting(l); setConfirmName(""); }}
                            data-testid="ml-delete">Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}

      {form ? <LearnerForm learner={form} onClose={() => setForm(null)} onSaved={() => { setForm(null); load(); }}
                           onToast={onToast} onError={onError} /> : null}
      {csvOpen ? <CsvImportModal grade={filters.grade || "Grade 3"} area={filters.learningArea || "Mathematics"}
                                 onClose={() => setCsvOpen(false)} onDone={() => { setCsvOpen(false); load(); }}
                                 onToast={onToast} onError={onError} /> : null}
      {deleting ? (
        <Modal title="Delete learner?" onClose={() => setDeleting(null)} testId="ml-delete-modal">
          <p className="text-sm text-ink">
            This permanently deletes <strong>{deleting.name}</strong>, all their Assessment Records and IEPs.
            This cannot be undone.
          </p>
          <p className="mt-2 text-xs text-muted">Type <strong>{deleting.name}</strong> to confirm.</p>
          <input className="input mt-2 w-full" value={confirmName} onChange={(e) => setConfirmName(e.target.value)}
                 data-testid="ml-delete-confirm" />
          <div className="mt-4 flex justify-end gap-2">
            <button className="btn-ghost" onClick={() => setDeleting(null)}>Cancel</button>
            <button className="btn-primary !bg-rose-600" disabled={confirmName.trim().toLowerCase() !== deleting.name.toLowerCase()}
                    onClick={remove} data-testid="ml-delete-final">Delete</button>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}

function LearnerForm({ learner, onClose, onSaved, onToast, onError }: {
  learner: Learner; onClose: () => void; onSaved: () => void;
  onToast: (msg: string) => void; onError: (msg: string) => void;
}) {
  const [form, setForm] = useState(learner);
  const [busy, setBusy] = useState(false);
  const set = (key: keyof Learner, value: string) => setForm({ ...form, [key]: value });
  const save = async () => {
    setBusy(true);
    try {
      if (form.id) await api.updateLearner(form.id, form as unknown as Record<string, unknown>);
      else await api.createLearner(form as unknown as Record<string, unknown>);
      onToast(form.id ? "Learner updated." : "Learner added.");
      onSaved();
    } catch (e) { onError((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <Modal title={form.id ? "Edit Learner" : "Add Learner"} onClose={onClose} testId="ml-form">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="First Name" value={form.firstName} onChange={(v) => set("firstName", v)} required testId="ml-first" />
        <Field label="Last Name" value={form.lastName} onChange={(v) => set("lastName", v)} required testId="ml-last" />
        <Field label="Admission No" value={form.admissionNo} onChange={(v) => set("admissionNo", v)} testId="ml-admission" />
        <label className="block">
          <span className="field-label">Gender</span>
          <select className="input mt-1 w-full" value={form.gender} data-testid="ml-gender"
                  onChange={(e) => set("gender", e.target.value)}>
            <option>Prefer not to say</option><option>Female</option><option>Male</option>
          </select>
        </label>
        <Field label="Class" value={form.className} onChange={(v) => set("className", v)} testId="ml-class" placeholder="3B" />
        <Field label="Grade" value={form.grade} onChange={(v) => set("grade", v)} testId="ml-grade" />
        <Field label="Learning Area" value={form.learningArea} onChange={(v) => set("learningArea", v)} testId="ml-area" />
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <button className="btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn-primary" disabled={busy || !form.firstName.trim() || !form.lastName.trim()}
                onClick={save} data-testid="ml-save">Save</button>
      </div>
    </Modal>
  );
}

type CsvPreview = {
  rows: Record<string, string>[]; total: number;
  duplicates: { rowIndex: number; admissionNo: string; existingName: string; source: string }[];
};
function CsvImportModal({ grade, area, onClose, onDone, onToast, onError }: {
  grade: string; area: string; onClose: () => void; onDone: () => void;
  onToast: (m: string) => void; onError: (m: string) => void;
}) {
  const [csv, setCsv] = useState("");
  const [preview, setPreview] = useState<CsvPreview | null>(null);
  const [resolutions, setResolutions] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const doPreview = async () => {
    setBusy(true);
    try {
      const r = await api.importLearners(csv, grade, area, true);
      setPreview(r as CsvPreview);
    } catch (e) { onError((e as Error).message); } finally { setBusy(false); }
  };
  const confirm = async () => {
    setBusy(true);
    try {
      const r = await api.importLearners(csv, grade, area, false, resolutions);
      onToast(r.message || "CSV imported.");
      onDone();
    } catch (e) { onError((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <Modal title="Import CSV" onClose={onClose} wide testId="ml-csv-modal">
      <div className="flex flex-wrap items-center gap-2">
        <a className="btn-mini" href={api.csvTemplateUrl()} download data-testid="ml-csv-template">Download CSV Template</a>
        <input type="file" accept=".csv,text/csv" className="text-xs"
               onChange={(e) => { const f = e.target.files?.[0]; if (f) f.text().then(setCsv); }}
               data-testid="ml-csv-file" />
      </div>
      <textarea className="input mt-3 min-h-32 w-full font-mono text-xs" value={csv}
                onChange={(e) => setCsv(e.target.value)} placeholder="firstName,lastName,admissionNo,gender,className"
                data-testid="ml-csv-text" />
      <button className="btn-primary mt-2 px-3 py-1.5 text-xs" disabled={busy || !csv.trim()}
              onClick={doPreview} data-testid="ml-csv-preview">Preview</button>
      {preview ? (
        <div className="mt-4">
          <p className="text-xs text-muted">{preview.total} row(s) found. First 5 shown.</p>
          <table className="mt-2 w-full text-left text-xs">
            <thead className="bg-slate-50 text-muted"><tr><th className="px-2 py-1">First Name</th><th>Last Name</th><th>Admission No</th><th>Gender</th><th>Class</th></tr></thead>
            <tbody>{preview.rows.map((r, i) => (
              <tr className="border-t border-line" key={i} data-testid="ml-csv-row">
                <td className="px-2 py-1">{r.firstName}</td><td>{r.lastName}</td><td>{r.admissionNo}</td><td>{r.gender}</td><td>{r.className}</td>
              </tr>
            ))}</tbody>
          </table>
          {preview.duplicates.map((d) => (
            <div className="mt-3 rounded border border-amber-300 bg-amber-50 p-2 text-xs text-amber-900"
                 key={d.rowIndex} data-testid="ml-csv-duplicate">
              <p>Admission No {d.admissionNo} already exists for {d.existingName} - choose what to do.</p>
              <select className="input mt-1" value={resolutions[String(d.rowIndex)] || "both"}
                      onChange={(e) => setResolutions({ ...resolutions, [String(d.rowIndex)]: e.target.value })}
                      data-testid="ml-csv-resolution">
                <option value="skip">Skip</option><option value="replace">Replace</option><option value="both">Keep Both</option>
              </select>
            </div>
          ))}
          <div className="mt-4 flex justify-end gap-2">
            <button className="btn-ghost" onClick={onClose}>Cancel</button>
            <button className="btn-primary" disabled={busy} onClick={confirm} data-testid="ml-csv-confirm">Confirm Import</button>
          </div>
        </div>
      ) : null}
    </Modal>
  );
}

/* -------------------------------------------------------------------------- */
/* Assessment grid                                                             */
/* -------------------------------------------------------------------------- */
type GridRow = { learnerId: string; name: string; level: AssessmentLevel; evidence: string; date: string; source: string };
function AssessmentGrid({ target, onClose, onSaved, onToast, onError }: {
  target: AssessTarget; onClose: () => void; onSaved: () => void;
  onToast: (m: string) => void; onError: (m: string) => void;
}) {
  const [context, setContext] = useState<AssessmentContext | null>(null);
  const [effective, setEffective] = useState<AssessTarget>(target);
  const [options, setOptions] = useState<AssessOptions | null>(null);
  const [rows, setRows] = useState<GridRow[]>([]);
  const [history, setHistory] = useState<{ name: string; entries: AssessmentAuditEntry[] } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { setEffective(target); setContext(null); setOptions(null); }, [target]);

  useEffect(() => {
    if (!effective.schemeRowId) {
      api.assessOptions(effective.grade || "", effective.learningArea || "")
        .then(setOptions).catch((e) => onError((e as Error).message));
      return;
    }
    let alive = true;
    Promise.all([
      api.assessmentContext(effective),
      api.learners({
        ...(effective.grade ? { grade: effective.grade } : {}),
        ...(effective.learningArea ? { learningArea: effective.learningArea } : {}),
        ...(effective.className ? { className: effective.className } : {}),
        status: "Active",
      }),
    ]).then(([ctx, list]) => {
      if (!alive) return;
      setContext(ctx);
      setRows(list.learners.map((l) => ({
        learnerId: l.id, name: l.name, level: "Not Assessed" as AssessmentLevel,
        evidence: "", date: today(), source: "Class Activity",
      })));
    }).catch((e) => onError((e as Error).message));
    return () => { alive = false; };
  }, [effective, onError]);

  const patch = (id: string, data: Partial<GridRow>) =>
    setRows((prev) => prev.map((r) => r.learnerId === id ? { ...r, ...data } : r));

  const markAllMeets = () => setRows((prev) => prev.map((r) =>
    r.level === "Not Assessed" ? { ...r, level: "Meets" } : r));

  const copyPrevious = async () => {
    if (!context) return;
    try {
      const prev = await api.progress({ grade: context.grade, learningArea: context.learningArea,
                                        className: target.className || "" });
      setRows((current) => current.map((r) => {
        const match = prev.learners.find((x) => x.learnerId === r.learnerId);
        const focus = match?.byFocus.find((f) => f.focus === context.focus);
        return focus ? { ...r, level: focus.level } : r; // never copy evidence
      }));
      onToast("Levels copied from the previous assessment. Check and edit differences.");
    } catch (e) { onError((e as Error).message); }
  };

  const save = async () => {
    if (!context) return;
    const bad = rows.find((r) => (r.level === "Below" || r.level === "Approaching") && !r.evidence.trim());
    if (bad) { onError(`Evidence required for ${bad.name} (Below/Approaching).`); return; }
    setBusy(true);
    try {
      const r = await api.saveAssessment(context.schemeRowId, context.week, context.lesson,
        rows.map(({ learnerId, level, evidence, date, source }) => ({ learnerId, level, evidence, date, source })));
      onToast(r.message);
      onSaved(); onClose();
    } catch (e) { onError((e as Error).message); } finally { setBusy(false); }
  };

  const openHistory = async (row: GridRow) => {
    try {
      const r = await api.assessmentAudit(row.learnerId);
      setHistory({ name: row.name, entries: r.history });
    } catch (e) { onError((e as Error).message); }
  };

  return (
    <Modal title={`Assess This Lesson - ${context ? `Week ${context.week} Lesson ${context.lesson} · ${context.focus}` : "Loading…"}`}
           onClose={onClose} wide testId="assess-grid">
      {!effective.schemeRowId ? (
        <div data-testid="assess-picker">
          <p className="text-sm text-ink">Choose the Sub-Strand / Focus to assess for this learner.</p>
          {options?.options.length ? (
            <div className="mt-3 space-y-2">
              {options.options.map((o) => (
                <button key={o.schemeRowId} disabled={!o.canAssess}
                        className={`flex w-full justify-between rounded border px-3 py-2 text-left text-xs ${o.canAssess ? "border-line hover:bg-slate-50" : "border-rose-200 bg-rose-50 text-rose-700"}`}
                        data-testid="assess-option"
                        onClick={() => setEffective({ ...effective, schemeRowId: o.schemeRowId })}>
                  <span><strong>{o.code} {o.subStrand}</strong> <span className="text-muted">{o.grade} {o.learningArea} · {o.term}</span></span>
                  <span>{o.canAssess ? "Select →" : o.reason}</span>
                </button>
              ))}
            </div>
          ) : <p className="mt-3 text-sm text-muted">No sub-strands found for this learner's Grade / Learning Area.</p>}
        </div>
      ) : !context ? <p className="p-6 text-sm text-muted">Loading assessment context…</p> : (
        <div className="grid gap-4 lg:grid-cols-[1fr_280px]">
          <div className="min-w-0">
            {!context.canAssess ? (
              <div className="mb-3 rounded border border-rose-300 bg-rose-50 p-3 text-sm text-rose-800"
                   data-testid="assess-vetting-guard">{context.reason}</div>
            ) : null}
            <div className="mb-3 flex flex-wrap gap-2">
              <button className="btn-mini" onClick={markAllMeets} data-testid="assess-mark-all">Mark All as Meets</button>
              <button className="btn-mini" onClick={copyPrevious} data-testid="assess-copy-previous">Copy from Previous Lesson</button>
            </div>
            <div className="max-h-[60vh] overflow-auto">
              <table className="w-full text-left text-xs">
                <thead className="sticky top-0 bg-slate-50 text-muted">
                  <tr><th className="px-2 py-1">Learner</th><th>Level</th><th>Evidence</th><th>Date</th><th>Source</th><th></th></tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr className="border-t border-line align-top" key={r.learnerId}>
                      <td className="px-2 py-2 font-semibold">{r.name}</td>
                      <td>
                        <select className="input !py-1 text-xs" value={r.level} data-testid={`assess-level-${r.learnerId}`}
                                disabled={!context.canAssess} onChange={(e) => patch(r.learnerId, { level: e.target.value as AssessmentLevel })}>
                          {LEVELS.map((l) => <option key={l}>{l}</option>)}
                        </select>
                      </td>
                      <td>
                        <textarea className="input !py-1 text-xs" rows={2} value={r.evidence} placeholder="e.g. Sorted 4/5 colour groups correctly, 18 Feb"
                                  data-testid={`assess-evidence-${r.learnerId}`}
                                  onChange={(e) => patch(r.learnerId, { evidence: e.target.value })} />
                        {(r.level === "Below" || r.level === "Approaching") && !r.evidence.trim() ? (
                          <span className="text-[10px] text-rose-700">Evidence required for Below/Approaching</span>
                        ) : null}
                      </td>
                      <td><input className="input !py-1 text-xs" type="date" value={r.date}
                                 onChange={(e) => patch(r.learnerId, { date: e.target.value })} /></td>
                      <td>
                        <select className="input !py-1 text-xs" value={r.source}
                                onChange={(e) => patch(r.learnerId, { source: e.target.value })}>
                          {SOURCES.map((s) => <option key={s}>{s}</option>)}
                        </select>
                      </td>
                      <td><button className="btn-mini" onClick={() => openHistory(r)} data-testid="assess-history">History</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-3 flex justify-end gap-2">
              <button className="btn-ghost" onClick={onClose}>Cancel</button>
              <button className="btn-primary" disabled={busy || !context.canAssess || !rows.length}
                      onClick={save} data-testid="assess-save">Save Assessment</button>
            </div>
          </div>
          <aside className="rounded-lg border border-line bg-slate-50 p-3 text-xs" data-testid="assess-rubric">
            <h3 className="font-bold text-ink">KICD Rubric (read-only)</h3>
            <p className="mt-1 text-muted">{context.subStrand} · {context.vettingStatus}</p>
            {context.rubric.length ? context.rubric.map((item, i) => (
              <div className="mt-3 rounded border border-line bg-white p-2" key={i}>
                <p className="font-semibold text-ink">{item.indicator}</p>
                {Object.entries(item.levels || {}).map(([level, text]) => (
                  <p className="mt-1" key={level}><strong>{level}:</strong> {text}</p>
                ))}
                <p className="mt-1 text-[10px] text-muted">Design p.{item.page}</p>
              </div>
            )) : (
              <p className="mt-3 rounded border border-amber-300 bg-amber-50 p-2 text-amber-900"
                 data-testid="assess-no-rubric">Rubric not in Design - use your judgement.</p>
            )}
          </aside>
        </div>
      )}
      {history ? (
        <Modal title={`Assessment History - ${history.name}`} onClose={() => setHistory(null)}>
          {history.entries.length ? history.entries.map((h, i) => (
            <div className="border-b border-line py-2 text-xs" key={i}>
              <strong>{h.oldLevel} → {h.newLevel}</strong> · {h.changedBy} · {h.changedAt}
              {h.reason ? <p className="text-muted">{h.reason}</p> : null}
            </div>
          )) : <p className="text-sm text-muted">No level changes yet.</p>}
        </Modal>
      ) : null}
    </Modal>
  );
}

/* -------------------------------------------------------------------------- */
/* Progress view                                                               */
/* -------------------------------------------------------------------------- */
function ProgressView({ summary, onCreateIep, onError }: {
  summary: LearnerSummary | null;
  onCreateIep: (learnerId: string) => void;
  onError: (m: string) => void;
}) {
  const [filters, setFilters] = useState({ grade: "", learningArea: "", className: "", strand: "", fromWeek: "", toWeek: "" });
  const [data, setData] = useState<ProgressData | null>(null);
  const [cell, setCell] = useState<{ name: string; focus: string; evidence: string; source: string; history: { level: string; date: string; evidence: string; source: string }[] } | null>(null);
  const load = useCallback(() => {
    const params: Record<string, string> = {};
    for (const [k, v] of Object.entries(filters)) if (v) params[k] = v;
    api.progress(params).then(setData).catch((e) => onError((e as Error).message));
  }, [filters, onError]);
  useEffect(() => { load(); }, [load]);

  const classSummary = data?.classSummary;
  const total = Math.max(1, classSummary ? Object.values(classSummary).reduce((a, b) => a + b, 0) : 1);
  const exportUrl = api.progressExportUrl(Object.fromEntries(
    Object.entries(filters).filter(([k]) => ["grade", "learningArea", "className"].includes(k))));

  return (
    <div className="space-y-4" data-testid="progress-root">
      <section className="card p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div><h1 className="text-lg font-extrabold text-ink">My Learners - Progress</h1>
            <p className="text-xs text-muted">Assessment is separate from Coverage. Coverage never changes here.</p>
            <SummaryCounts summary={summary} />
          </div>
          <a className="btn-primary px-3 py-1.5 text-xs" href={exportUrl} target="_blank" rel="noreferrer"
             data-testid="progress-export">Export Progress PDF</a>
        </div>
        <p className="mt-2 text-xs text-rose-700">This PDF contains learner names. Keep it in My Space.</p>
        <div className="mt-3 flex flex-wrap items-end gap-2 border-t border-line pt-3">
          {([["grade", "Grade"], ["learningArea", "Learning Area"], ["className", "Class"], ["strand", "Strand"],
             ["fromWeek", "From Week"], ["toWeek", "To Week"]] as const).map(([key, label]) => (
            <Field key={key} label={label} value={filters[key]} onChange={(v) => setFilters({ ...filters, [key]: v })}
                   testId={`progress-filter-${key}`} />
          ))}
        </div>
      </section>

      {classSummary ? (
        <section className="card p-4" data-testid="progress-summary">
          <h2 className="text-sm font-bold text-ink">Class Summary</h2>
          <div className="mt-2 space-y-1.5">
            {LEVELS.map((level) => {
              const n = classSummary[level] || 0;
              return <div className="flex items-center gap-2 text-xs" key={level}>
                <span className="w-24 font-semibold">{level}</span>
                <span className="h-2 flex-1 rounded bg-slate-100">
                  <span className={`block h-2 rounded ${LEVEL_COLOR[level]}`} style={{ width: `${(n / total) * 100}%` }} />
                </span>
                <span className="w-6 text-right" data-testid={`progress-stat-${level}`}>{n}</span>
              </div>;
            })}
          </div>
        </section>
      ) : null}

      <section className="card p-4" data-testid="progress-needs-support">
        <h2 className="text-sm font-bold text-ink">Needs Support - {data?.needsSupportCount ?? 0} learners</h2>
        <p className="text-xs text-muted">Any Below, or 2+ Approaching in the last 2 weeks. No IEP is created automatically.</p>
        <div className="mt-2 flex flex-wrap gap-2">
          {(data?.needsSupport || []).map((l) => (
            <button key={l.learnerId} className="btn-mini" onClick={() => onCreateIep(l.learnerId)}
                    data-testid="progress-create-iep">Create IEP: {l.name}</button>
          ))}
          {!data?.needsSupportCount ? <span className="text-xs text-muted">None in this view.</span> : null}
        </div>
      </section>

      <section className="card overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="bg-slate-50 text-muted">
            <tr><th className="px-3 py-2">Learner</th><th>Overall</th><th>Trend</th><th>Focuses</th><th></th></tr>
          </thead>
          <tbody>
            {(data?.learners || []).map((l) => (
              <tr className="border-t border-line" key={l.learnerId} data-testid="progress-learner">
                <td className="px-3 py-2 font-semibold">{l.name}<span className="block text-[10px] text-muted">{l.className}</span></td>
                <td><LevelBadge level={l.overall} /></td>
                <td className="text-base" data-testid="progress-trend">
                  {l.byFocus.length ? l.byFocus.map((f) => f.trend).join(" ") : "—"}
                </td>
                <td>
                  <div className="flex flex-wrap gap-1">
                    {l.byFocus.map((f) => (
                      <button key={f.focus} className="rounded border border-line px-1.5 py-1 hover:bg-slate-50"
                              data-testid="progress-cell"
                              onClick={() => setCell({ name: l.name, focus: f.focus, evidence: f.evidence,
                                                       source: f.source, history: f.history })}>
                        <strong>{f.focus}:</strong> {f.level} <span className="text-muted">{f.date}</span>
                      </button>
                    ))}
                    {!l.byFocus.length ? <span className="text-muted">—</span> : null}
                  </div>
                </td>
                <td><button className="btn-mini" onClick={() => onCreateIep(l.learnerId)}>IEP</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      {cell ? (
        <Modal title={`${cell.name} - ${cell.focus}`} onClose={() => setCell(null)}>
          <p className="text-sm"><strong>Evidence:</strong> {cell.evidence || "—"}</p>
          <p className="mt-1 text-sm"><strong>Source:</strong> {cell.source}</p>
          <h3 className="mt-3 text-sm font-bold">History</h3>
          {cell.history.map((h, i) => (
            <p className="border-b border-line py-1 text-xs" key={i}>
              {h.level} · {h.date} · {h.source} · {h.evidence || "—"}
            </p>
          ))}
        </Modal>
      ) : null}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* IEP view                                                                    */
/* -------------------------------------------------------------------------- */
function IepView({ summary, learnerId, onToast, onError }: {
  summary: LearnerSummary | null;
  learnerId?: string; onToast: (m: string) => void; onError: (m: string) => void;
}) {
  const [status, setStatus] = useState("");
  const [items, setItems] = useState<Iep[]>([]);
  const [learners, setLearners] = useState<Learner[]>([]);
  const [form, setForm] = useState<Iep | null>(null);
  const [review, setReview] = useState<Iep | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => {
    api.ieps(status ? { status } : {}).then((r) => setItems(r.ieps)).catch((e) => onError((e as Error).message));
    api.learners({ status: "Active" }).then((r) => setLearners(r.learners)).catch(() => undefined);
  }, [status, onError]);
  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!learnerId || !learners.length) return;
    const learner = learners.find((l) => l.id === learnerId);
    if (!learner) return;
    setForm({
      id: "", learnerId, learner, need: "", goal: "", support: "", materials: "",
      reviewDate: "", reviewWeek: 0, status: "Active", reviewNeeded: false,
      aiEnriched: false, reviews: [], createdAt: "", updatedAt: "",
    });
  }, [learnerId, learners]);

  const save = async () => {
    if (!form) return;
    setBusy(true);
    try {
      if (form.id) await api.updateIep(form.id, form as unknown as Record<string, unknown>);
      else await api.createIep(form as unknown as Record<string, unknown>);
      onToast(form.id ? "IEP updated." : "IEP created. It stays in your My Space.");
      setForm(null); load();
    } catch (e) { onError((e as Error).message); } finally { setBusy(false); }
  };

  return (
    <div className="space-y-4" data-testid="iep-root">
      <section className="card p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div><h1 className="text-lg font-extrabold text-ink">My Learners - IEP</h1>
            <p className="text-xs text-muted">Teacher-written only. No diagnosis, no disability labels, AI off unless you opt in.</p>
            <SummaryCounts summary={summary} />
          </div>
          <div className="flex items-center gap-2">
            <select className="input" value={status} data-testid="iep-filter-status"
                    onChange={(e) => setStatus(e.target.value)}>
              <option value="">All</option><option>Active</option><option>Met Goal</option>
              <option>Review Needed</option><option>Closed</option>
            </select>
            <button className="btn-primary px-3 py-1.5 text-xs" data-testid="iep-create"
                    onClick={() => setForm({
                      id: "", learnerId: learners[0]?.id || "", need: "", goal: "", support: "",
                      materials: "", reviewDate: "", reviewWeek: 0, status: "Active",
                      reviewNeeded: false, aiEnriched: false, reviews: [], createdAt: "", updatedAt: "",
                    })}>+ New IEP</button>
          </div>
        </div>
      </section>
      <section className="card overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="bg-slate-50 text-muted">
            <tr><th className="px-3 py-2">Learner</th><th>Need</th><th>Goal</th><th>Review Date</th><th>Status</th><th></th></tr>
          </thead>
          <tbody>
            {items.map((i) => (
              <tr className="border-t border-line" key={i.id} data-testid="iep-row">
                <td className="px-3 py-2 font-semibold">{i.learner?.name || "Learner"}</td>
                <td className="max-w-52 truncate">{i.need}</td>
                <td className="max-w-52 truncate">{i.goal}</td>
                <td>{i.reviewDate || "—"} {i.reviewWeek ? `(W${i.reviewWeek})` : ""}</td>
                <td><span className="badge bg-slate-100 text-slate-700">{i.reviewNeeded ? "Review Needed" : i.status}</span></td>
                <td className="text-right">
                  <button className="btn-mini" onClick={() => setForm(i)}>Edit</button>{" "}
                  <button className="btn-mini" onClick={() => setReview(i)} data-testid="iep-review">Review</button>{" "}
                  <button className="btn-mini" disabled={i.status === "Closed"}
                          onClick={() => api.closeIep(i.id).then(load).catch((e) => onError((e as Error).message))}>Close</button>
                </td>
              </tr>
            ))}
            {!items.length ? <tr><td colSpan={6} className="px-3 py-6 text-center text-muted">No IEPs in this view.</td></tr> : null}
          </tbody>
        </table>
      </section>
      {form ? <IepForm form={form} setForm={setForm} learners={learners} busy={busy}
                       onClose={() => setForm(null)} onSave={save} onToast={onToast} onError={onError} /> : null}
      {review ? <IepReviewModal iep={review} onClose={() => setReview(null)} onSaved={() => { setReview(null); load(); }}
                                onToast={onToast} onError={onError} /> : null}
    </div>
  );
}

function IepForm({ form, setForm, learners, busy, onClose, onSave, onToast, onError }: {
  form: Iep; setForm: (i: Iep) => void; learners: Learner[]; busy: boolean;
  onClose: () => void; onSave: () => void; onToast: (m: string) => void; onError: (m: string) => void;
}) {
  const [ideas, setIdeas] = useState<string[]>([]);
  const [suggesting, setSuggesting] = useState(false);
  const set = (key: keyof Iep, value: string | number) => setForm({ ...form, [key]: value });
  const suggest = async () => {
    setSuggesting(true);
    try {
      const r = await api.suggestSupport(form.need, form.id || undefined);
      setIdeas(r.ideas);
      onToast("AI suggestions are ideas only. Reject leaves the field empty.");
    } catch (e) { onError((e as Error).message); } finally { setSuggesting(false); }
  };
  return (
    <Modal title={form.id ? "Edit IEP" : "New IEP"} onClose={onClose} wide testId="iep-form">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="field-label">Learner (read-only)</span>
          <select className="input mt-1 w-full" value={form.learnerId} disabled={Boolean(form.id)}
                  data-testid="iep-learner" onChange={(e) => {
                    const l = learners.find((x) => x.id === e.target.value);
                    setForm({ ...form, learnerId: e.target.value, learner: l });
                  }}>
            {learners.map((l) => <option value={l.id} key={l.id}>{l.name} - {l.className}</option>)}
          </select>
        </label>
        <Field label="Review Date" type="date" value={form.reviewDate} required
               onChange={(v) => set("reviewDate", v)} testId="iep-review-date" />
      </div>
      <div className="mt-3 space-y-3">
        {([["need", "Need", "e.g. Struggles to sort by colour - confuses red/orange", true],
           ["goal", "Goal", "e.g. Sort by colour correctly 4/5 times by Week 10", true],
           ["support", "Support", "e.g. Use larger bottle tops, pair with a friend, extra practice", true],
           ["materials", "Materials", "e.g. Large red/orange bottle tops, colour cards", false]] as const)
          .map(([key, label, placeholder, required]) => (
            <label className="block" key={key}>
              <span className="field-label">{label}{required ? " *" : ""}</span>
              <textarea className="input mt-1 min-h-16 w-full" value={String(form[key] || "")} placeholder={placeholder}
                        data-testid={`iep-${key}`} onChange={(e) => set(key, e.target.value)} />
            </label>
          ))}
      </div>
      <div className="mt-3">
        <button className="btn-ghost px-3 py-1.5 text-xs" onClick={suggest} disabled={suggesting || !form.need.trim()}
                data-testid="iep-ai-suggest">{suggesting ? "Suggesting…" : "✨ Suggest Support Ideas (opt-in)"}</button>
        <p className="mt-1 text-[10px] text-muted">AI is OFF by default. Ideas are not learner data and are not a diagnosis.</p>
        {ideas.length ? (
          <div className="mt-2 space-y-2 rounded border border-amber-400 bg-amber-50 p-3" data-testid="iep-ai-box">
            {ideas.map((idea, i) => (
              <div className="flex gap-2 text-xs text-amber-900" key={i} data-testid="iep-ai-idea">
                <span className="flex-1">{idea}</span>
                <button className="btn-mini" onClick={() => { set("support", form.support ? `${form.support} ${idea}` : idea);
                  set("aiEnriched", 1); }} data-testid="iep-ai-accept">Accept</button>
                <button className="btn-mini" onClick={() => set("support", idea)} data-testid="iep-ai-edit">Edit</button>
                <button className="btn-mini" onClick={() => setIdeas((p) => p.filter((_, j) => j !== i))}
                        data-testid="iep-ai-reject">Reject</button>
              </div>
            ))}
          </div>
        ) : null}
      </div>
      <div className="mt-4 flex justify-end gap-2">
        <button className="btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn-primary" disabled={busy || !form.need || !form.goal || !form.support || !form.reviewDate || !form.learnerId}
                onClick={onSave} data-testid="iep-save">Save IEP</button>
      </div>
    </Modal>
  );
}

function IepReviewModal({ iep, onClose, onSaved, onToast, onError }: {
  iep: Iep; onClose: () => void; onSaved: () => void;
  onToast: (m: string) => void; onError: (m: string) => void;
}) {
  const [dateValue, setDate] = useState(today());
  const [note, setNote] = useState(iep.reviews[iep.reviews.length - 1]?.note || "");
  const [newLevel, setNewLevel] = useState<AssessmentLevel>("Not Assessed");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      const updated = await api.addIepReview(iep.id, { date: dateValue, note, newLevel });
      if (newLevel === "Meets" || newLevel === "Exceeds") onToast("Review saved. You can now mark the goal as met.");
      else onToast("Review saved.");
      if (newLevel === "Meets" || newLevel === "Exceeds") {
        await api.updateIep(updated.id, { status: "Met Goal" });
        onToast("Goal marked as Met. The IEP is kept for history.");
      }
      onSaved();
    } catch (e) { onError((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <Modal title={`Review IEP - ${iep.learner?.name || "Learner"}`} onClose={onClose} testId="iep-review-modal">
      <Field label="Review Date" type="date" value={dateValue} onChange={setDate} testId="iep-review-date-input" />
      <label className="mt-3 block"><span className="field-label">Note *</span>
        <textarea className="input mt-1 min-h-20 w-full" value={note} onChange={(e) => setNote(e.target.value)}
                  data-testid="iep-review-note" /></label>
      <label className="mt-3 block"><span className="field-label">New Level</span>
        <select className="input mt-1 w-full" value={newLevel} data-testid="iep-review-level"
                onChange={(e) => setNewLevel(e.target.value as AssessmentLevel)}>
          {LEVELS.map((l) => <option key={l}>{l}</option>)}
        </select></label>
      {newLevel === "Meets" || newLevel === "Exceeds" ? (
        <p className="mt-2 text-xs text-emerald-800">Saving will mark this goal as Met.</p>
      ) : null}
      <div className="mt-4 flex justify-end gap-2">
        <button className="btn-ghost" onClick={onClose}>Cancel</button>
        <button className="btn-primary" disabled={busy || !note.trim()} onClick={save} data-testid="iep-review-save">Save Review</button>
      </div>
    </Modal>
  );
}

/* -------------------------------------------------------------------------- */
/* Root                                                                        */
/* -------------------------------------------------------------------------- */
export default function MyLearners({ view, assessTarget, onNavigate, onAssessed, onToast, onError }: Props) {
  const [target, setTarget] = useState<AssessTarget | null>(null);
  const [iepLearnerId, setIepLearnerId] = useState<string | undefined>();
  const [summary, setSummary] = useState<LearnerSummary | null>(null);

  useEffect(() => {
    api.learnerSummary().then(setSummary).catch(() => undefined);
  }, [view, assessTarget]);

  useEffect(() => {
    if (!assessTarget) return;
    setTarget(assessTarget);
  }, [assessTarget]);

  const openLearnerAssessment = (learner: Learner) => {
    setTarget({
      schemeRowId: "", week: 0, lesson: 0, grade: learner.grade,
      learningArea: learner.learningArea, className: learner.className,
    });
  };

  const clearAssessment = () => { setTarget(null); onAssessed?.(); };

  return (
    <div className="space-y-4">
      {view === "list" ? (
        <LearnersList summary={summary} onAssess={openLearnerAssessment}
                      onIep={(l) => { setIepLearnerId(l.id); onNavigate("iep"); }}
                      onToast={onToast} onError={onError} />
      ) : view === "progress" ? (
        <ProgressView summary={summary}
                      onCreateIep={(id) => { setIepLearnerId(id); onNavigate("iep"); }}
                      onError={onError} />
      ) : (
        <IepView summary={summary} learnerId={iepLearnerId} onToast={onToast} onError={onError} />
      )}
      {target ? (
        <AssessmentGrid target={target} onClose={clearAssessment}
                        onSaved={() => { setSummary(null); onAssessed?.(); }}
                        onToast={onToast} onError={onError} />
      ) : null}
    </div>
  );
}
