import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { ROW_STATUSES } from "../types";
import type {
  AssessTarget,
  PlanVersion,
  RecordOfWorkDoc,
  RecordOfWorkRow,
  RowDiff,
  RowEntryStatus,
  RowGap,
  RowSchemeList,
  RowVersionPreview,
} from "../types";
import { AIDraftLabel, Badge } from "./ui";

type Patch = {
  date?: string;
  workDone?: string;
  reflection?: string;
  status?: string;
  signature?: string;
  carryOverTo?: { week: number; lesson: number } | null;
};

type Props = {
  planId?: string | null;
  focus?: { week: number; lesson: number } | null;
  onToast: (msg: string) => void;
  onError: (msg: string) => void;
  onOpenRow: (planId: string) => void;
  onExportTermPack?: (planId: string) => void;
  onAssess?: (target: AssessTarget) => void;
  onBack: () => void;
};

const PAGE_SIZE = 10;

/** Retrospective Record of Work: scheme picker when no planId, editor when there is one. */
export default function RecordOfWork(props: Props) {
  if (props.planId) {
    return (
      <RowEditor
        key={props.planId}
        planId={props.planId}
        focus={props.focus || null}
        onToast={props.onToast}
        onError={props.onError}
        onBack={props.onBack}
        onExportTermPack={props.onExportTermPack}
        onAssess={props.onAssess}
      />
    );
  }
  return (
    <RowList
      onToast={props.onToast}
      onError={props.onError}
      onOpenRow={props.onOpenRow}
    />
  );
}

/* -------------------------------------------------------------------------- */
/* Scheme picker                                                              */
/* -------------------------------------------------------------------------- */

function RowList({
  onToast,
  onError,
  onOpenRow,
}: {
  onToast: (msg: string) => void;
  onError: (msg: string) => void;
  onOpenRow: (planId: string) => void;
}) {
  const [data, setData] = useState<RowSchemeList | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.rowSchemes());
      onError("");
    } catch (e) {
      setData({ schemes: [], count: 0 });
      onError((e as Error).message);
    }
  }, [onError]);

  useEffect(() => {
    void load();
  }, [load]);

  const generate = async (planId: string, addMissingOnly: boolean, openAfter: boolean) => {
    setBusyId(planId);
    try {
      const doc = await api.rowGenerate(planId, addMissingOnly);
      onError("");
      onToast(doc.message || (doc.created ? `Created ${doc.created} ROW rows.` : "ROW is already complete."));
      await load();
      if (openAfter) onOpenRow(planId);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusyId(null);
    }
  };

  if (data === null) {
    return <div className="card p-6 text-sm text-muted" data-testid="row-list-loading">Loading schemes…</div>;
  }

  return (
    <div className="space-y-4" data-testid="row-list">
      <div className="card">
        <h2 className="text-lg font-extrabold text-ink">Record of Work</h2>
        <p className="mt-1 max-w-3xl text-xs leading-relaxed text-muted">
          <strong>What WAS taught</strong> — filled in by the teacher after teaching. Generation creates one
          row per scheme lesson, prefilled from the Scheme and Lesson Plan. Work Done starts as a grey
          italic <em>Planned: …</em> placeholder you must edit; Reflection always starts empty and Status
          always starts blank. Editing a row never changes the Scheme, Lesson Plan or Lesson Notes.
        </p>
        <p className="mt-2 text-[11px] text-muted">
          Source chunks must be <strong>Vetted</strong> before a Record of Work can be generated. No web
          search is used here — this is about your classroom.
        </p>
      </div>

      {data.count === 0 ? (
        <div className="card p-6 text-sm text-muted" data-testid="row-list-empty">
          No schemes yet. Create a Scheme of Work first.
        </div>
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {data.schemes.map((s) => (
            <div
              key={s.planId}
              className="card space-y-2"
              data-testid={`row-scheme-${s.planId}`}
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <h3 className="truncate text-sm font-bold text-ink">{s.title}</h3>
                  <p className="mt-0.5 text-[11px] text-muted">
                    {s.grade} · {s.subject} · {s.term} · {s.sectionCount} scheme rows
                  </p>
                </div>
                {s.rowExists ? (
                  <Badge tone="green" data-testid={`row-created-${s.planId}`}>✓ ROW Created</Badge>
                ) : (
                  <Badge tone="slate">Not created</Badge>
                )}
              </div>
              {s.rowExists ? (
                <p className="text-[11px] text-muted">
                  {s.rowCount} rows · {s.taught} taught · {s.rowStatus}
                </p>
              ) : null}
              <div className="flex flex-wrap gap-2 pt-1">
                {s.rowExists ? (
                  <>
                    <button
                      className="btn-primary px-2.5 py-1.5 text-xs"
                      onClick={() => onOpenRow(s.planId)}
                      data-testid={`row-view-${s.planId}`}
                    >
                      View ROW
                    </button>
                    <button
                      className="btn-ghost px-2.5 py-1.5 text-xs"
                      disabled={busyId === s.planId}
                      onClick={() => void generate(s.planId, true, false)}
                      data-testid={`row-add-missing-${s.planId}`}
                    >
                      {busyId === s.planId ? "Checking…" : "Add Missing Rows Only"}
                    </button>
                  </>
                ) : (
                  <button
                    className="btn-primary px-2.5 py-1.5 text-xs"
                    disabled={busyId === s.planId}
                    onClick={() => void generate(s.planId, false, true)}
                    data-testid={`row-generate-${s.planId}`}
                  >
                    {busyId === s.planId ? "Generating…" : "Generate ROW for Term"}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Editor                                                                     */
/* -------------------------------------------------------------------------- */

type Handlers = {
  save: (rowId: string, patch: Patch) => void;
  reset: (rowId: string) => void;
  ai: (rowId: string) => void;
  accept: (rowId: string, text?: string) => void;
  reject: (rowId: string) => void;
  carry: (rowId: string, week: number, lesson: number) => void;
};

function RowEditor({
  planId,
  focus,
  onToast,
  onError,
  onBack,
  onExportTermPack,
  onAssess,
}: {
  planId: string;
  focus: { week: number; lesson: number } | null;
  onToast: (msg: string) => void;
  onError: (msg: string) => void;
  onBack: () => void;
  onExportTermPack?: (planId: string) => void;
  onAssess?: (target: AssessTarget) => void;
}) {
  const [doc, setDoc] = useState<RecordOfWorkDoc | null>(null);
  const [busy, setBusy] = useState(false);
  const [page, setPage] = useState(0);
  const [weekFilter, setWeekFilter] = useState("all");
  const [gapsOpen, setGapsOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [versions, setVersions] = useState<PlanVersion[]>([]);
  const [diff, setDiff] = useState<RowDiff | null>(null);
  const [preview, setPreview] = useState<RowVersionPreview | null>(null);
  const [restoreTarget, setRestoreTarget] = useState<PlanVersion | null>(null);
  const [commentOpen, setCommentOpen] = useState(false);
  const [comment, setComment] = useState("");
  const [commentError, setCommentError] = useState<string | null>(null);
  const [bulkWeek, setBulkWeek] = useState(1);
  const [aiBusyId, setAiBusyId] = useState<string | null>(null);
  const [highlightId, setHighlightId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const d = await api.rowDoc(planId);
      setDoc(d);
      onError("");
      if (d.rows.length) setBulkWeek(d.rows[0].week);
      if (focus) {
        setWeekFilter(String(focus.week));
        const match = d.rows.find((r) => r.week === focus.week && r.lesson === focus.lesson);
        if (match) {
          setHighlightId(match.id);
          const idx = d.rows.filter((r) => r.week === focus.week).findIndex((r) => r.id === match.id);
          setPage(Math.max(0, Math.floor(idx / PAGE_SIZE)));
        }
      }
    } catch (e) {
      onError((e as Error).message);
    }
  }, [planId, focus?.week, focus?.lesson, onError]);

  useEffect(() => {
    void load();
  }, [load]);

  const weeks = useMemo(
    () => Array.from(new Set((doc?.rows || []).map((r) => r.week))).sort((a, b) => a - b),
    [doc],
  );
  const filtered = useMemo(
    () => (doc?.rows || []).filter((r) => weekFilter === "all" || r.week === Number(weekFilter)),
    [doc, weekFilter],
  );
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const visible = filtered.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE);

  const withBusy = async (fn: () => Promise<RecordOfWorkDoc | null>, message?: string) => {
    setBusy(true);
    try {
      const next = await fn();
      if (next) setDoc(next);
      onError("");
      if (message) onToast(message);
      else if (next?.message) onToast(next.message);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const generate = (addMissingOnly: boolean) =>
    void withBusy(async () => await api.rowGenerate(planId, addMissingOnly));

  const save = async (rowId: string, patch: Patch) => {
    try {
      const res = await api.rowEdit(rowId, patch);
      setDoc((d) =>
        d
          ? {
              ...d,
              rows: d.rows.map((r) => (r.id === rowId ? res.row : r)),
              coverage: res.coverage,
            }
          : d,
      );
      onError("");
    } catch (e) {
      onError((e as Error).message);
    }
  };

  const reset = (rowId: string) =>
    void (async () => {
      try {
        const res = await api.rowReset(rowId);
        setDoc((d) =>
          d
            ? { ...d, rows: d.rows.map((r) => (r.id === rowId ? res.row : r)), coverage: res.coverage }
            : d,
        );
        onToast("Row reset to Planned; Reflection and Status cleared.");
      } catch (e) {
        onError((e as Error).message);
      }
    })();

  const ai = (rowId: string) =>
    void (async () => {
      setAiBusyId(rowId);
      try {
        const res = await api.rowAiReflection(rowId);
        setDoc((d) => (d ? { ...d, rows: d.rows.map((r) => (r.id === rowId ? res.row : r)) } : d));
        onError("");
      } catch (e) {
        onError((e as Error).message);
      } finally {
        setAiBusyId(null);
      }
    })();

  const accept = (rowId: string, text?: string) =>
    void (async () => {
      try {
        const res = await api.rowAiAccept(rowId, text);
        setDoc((d) => (d ? { ...d, rows: d.rows.map((r) => (r.id === rowId ? res.row : r)) } : d));
        onToast("AI reflection accepted - it is now your Reflection.");
      } catch (e) {
        onError((e as Error).message);
      }
    })();

  const reject = (rowId: string) =>
    void (async () => {
      try {
        const res = await api.rowAiReject(rowId);
        setDoc((d) => (d ? { ...d, rows: d.rows.map((r) => (r.id === rowId ? res.row : r)) } : d));
        onToast("AI draft rejected. Reflection left empty.");
      } catch (e) {
        onError((e as Error).message);
      }
    })();

  const carry = (rowId: string, week: number, lesson: number) =>
    void withBusy(async () => await api.rowCarryOver(rowId, week, lesson), "Carry-over row created; original kept for audit.");

  const handlers: Handlers = { save: (id, p) => void save(id, p), reset, ai, accept, reject, carry };

  const bulk = () =>
    void withBusy(async () =>
      doc ? await api.rowBulkStatus(doc.id, bulkWeek, "Taught") : null,
    );

  const setStatus = (status: "Draft" | "Final") =>
    void withBusy(
      async () => doc && (await api.rowStatus(doc.id, status)),
      status === "Final" ? "Record of Work marked Final." : "Unlocked - new Draft.",
    );

  const openHistory = async () => {
    if (!doc) return;
    setHistoryOpen(true);
    setDiff(null);
    setPreview(null);
    setRestoreTarget(null);
    try {
      const res = await api.rowVersions(doc.id);
      setVersions(res.versions);
    } catch (e) {
      onError((e as Error).message);
    }
  };

  const openPreview = async (v: PlanVersion) => {
    if (!doc) return;
    setDiff(null);
    try {
      setPreview(await api.rowVersion(doc.id, v.id));
    } catch (e) {
      onError((e as Error).message);
    }
  };

  const openDiff = async (v: PlanVersion) => {
    if (!doc) return;
    setPreview(null);
    try {
      setDiff(await api.rowVersionDiff(doc.id, v.id));
    } catch (e) {
      onError((e as Error).message);
    }
  };

  const restore = async (v: PlanVersion) => {
    if (!doc) return;
    setRestoreTarget(null);
    try {
      const next = await api.rowRestoreVersion(doc.id, v.id);
      setDoc(next);
      setHistoryOpen(false);
      onToast(`Restored ${v.label} - saved as a NEW version. Old versions were kept.`);
    } catch (e) {
      onError((e as Error).message);
    }
  };

  const saveVersion = async () => {
    if (!doc) return;
    if (!comment.trim()) {
      setCommentError("A comment is required, e.g. 'Filled Week 2 after teaching'.");
      return;
    }
    try {
      const res = await api.rowCreateVersion(doc.id, comment.trim());
      setDoc(res.recordOfWork);
      setCommentOpen(false);
      setComment("");
      setCommentError(null);
      onToast(`Saved ${res.label}`);
    } catch (e) {
      onError((e as Error).message);
    }
  };

  if (!doc) {
    return <div className="card p-6 text-sm text-muted" data-testid="row-editor-loading">Loading Record of Work…</div>;
  }

  const cov = doc.coverage;
  const isFinal = doc.status === "Final";
  const h = doc.header || {};

  return (
    <div className="space-y-4" data-testid="row-editor">
      {/* Header ------------------------------------------------------------ */}
      <div className="card">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <button className="text-[11px] font-semibold text-brand-700 underline" onClick={onBack} data-testid="row-back">
              ← All Records of Work
            </button>
            <h2 className="mt-1 text-lg font-extrabold text-ink">Record of Work</h2>
            <p className="mt-0.5 text-xs text-muted">
              {h.school || "School not set"} · {h.grade} · {h.learningArea} · {h.term} {h.year} ·{" "}
              {h.teacher || "Teacher not set"} {h.tscNo ? `(TSC ${h.tscNo})` : ""}
            </p>
            <p className="mt-0.5 text-[11px] text-muted">{doc.schemeTitle}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={isFinal ? "green" : "amber"}>{doc.finalVersionLabel || doc.status}</Badge>
            {doc.rowExists ? <Badge tone="green" data-testid="row-created-badge">✓ ROW Created</Badge> : null}
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-3">
          {doc.rowExists ? (
            <button
              className="btn-ghost px-2.5 py-1.5 text-xs"
              disabled={busy || isFinal}
              onClick={() => void generate(true)}
              data-testid="row-add-missing-editor"
            >
              Add Missing Rows Only
            </button>
          ) : null}
          <button className="btn-ghost px-2.5 py-1.5 text-xs" onClick={() => setGapsOpen(true)} data-testid="row-view-gaps">
            View Gaps ({cov.gaps.length})
          </button>
          <button className="btn-ghost px-2.5 py-1.5 text-xs" onClick={() => void openHistory()} data-testid="row-history">
            Version history ({doc.versions.length})
          </button>
          <button
            className="btn-primary px-2.5 py-1.5 text-xs"
            onClick={() => {
              setCommentError(null);
              setCommentOpen(true);
            }}
            data-testid="row-save-version"
          >
            Save Version
          </button>
          {isFinal ? (
            <button className="btn-ghost px-2.5 py-1.5 text-xs" disabled={busy} onClick={() => void setStatus("Draft")} data-testid="row-unlock">
              Unlock to Edit
            </button>
          ) : (
            <button className="btn-ghost px-2.5 py-1.5 text-xs" disabled={busy} onClick={() => void setStatus("Final")} data-testid="row-final">
              Mark Final
            </button>
          )}
          <a className="btn-ghost px-2.5 py-1.5 text-xs" href={api.rowPdfUrl(doc.id)} target="_blank" rel="noreferrer" data-testid="row-export-pdf">
            Export ROW PDF
          </a>
          {onExportTermPack ? (
            <button className="btn-primary px-2.5 py-1.5 text-xs" onClick={() => onExportTermPack(doc.planId || planId)} data-testid="row-export-term-pack">
              📦 Export Term Pack
            </button>
          ) : null}
        </div>
      </div>

      {/* Coverage stats (always visible) ------------------------------------ */}
      <div className="card" data-testid="row-coverage">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs">
          <Stat label="Planned" value={cov.planned} testId="row-stat-planned" />
          <Stat label="Taught" value={cov.taught} testId="row-stat-taught" tone="green" />
          <Stat label="Partially" value={cov.partially} testId="row-stat-partially" tone="amber" />
          <Stat label="Not Taught" value={cov.notTaught} testId="row-stat-nottaught" tone="red" />
          <Stat label="Carry Over" value={cov.carryOver} testId="row-stat-carryover" tone="amber" />
          <span className="ml-auto text-sm font-extrabold text-ink" data-testid="row-coverage-pct">
            Coverage: {cov.coverageLabel}
          </span>
        </div>
        {cov.warning ? (
          <p className="mt-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-900" data-testid="row-coverage-warning">
            ⚠ {cov.warning}{" "}
            <button className="underline" onClick={() => setGapsOpen(true)}>
              See Gaps
            </button>
          </p>
        ) : null}
        {cov.unrecorded > 0 ? (
          <p className="mt-2 text-[11px] text-muted">
            {cov.unrecorded} row(s) still have a blank Status — the teacher must select one.
          </p>
        ) : null}
      </div>

      {/* Bulk --------------------------------------------------------------- */}
      <div className="card flex flex-wrap items-end gap-3" data-testid="row-bulk">
        <label className="text-xs">
          <span className="field-label block">Week</span>
          <select
            className="input mt-1 w-32"
            value={bulkWeek}
            onChange={(e) => setBulkWeek(Number(e.target.value))}
            data-testid="row-bulk-week"
          >
            {weeks.map((w) => (
              <option key={w} value={w}>Week {w}</option>
            ))}
          </select>
        </label>
        <button className="btn-ghost px-2.5 py-1.5 text-xs" disabled={busy || isFinal || !weeks.length} onClick={bulk} data-testid="row-bulk-taught">
          Mark All Week {bulkWeek} as Taught
        </button>
        {onAssess ? (
          <button className="btn-ghost px-2.5 py-1.5 text-xs" disabled={busy || !weeks.length}
                  onClick={() => {
                    const row = (doc?.rows || []).find((r) => r.week === bulkWeek && r.schemeRowId);
                    if (!row) return;
                    onAssess({
                      schemeRowId: row.schemeRowId, week: row.week, lesson: row.lesson,
                      grade: String(doc?.header?.grade || ""),
                      learningArea: String(doc?.header?.learningArea || ""),
                    });
                  }} data-testid="row-assess-learners">
            📊 Assess Learners
          </button>
        ) : null}
        <span className="text-[11px] text-muted">
          Sets Status only. Work Done and Reflection stay for you to fill; carry-over rows are kept.
        </span>
      </div>

      {/* Table -------------------------------------------------------------- */}
      {!doc.rowExists ? (
        <div className="card space-y-3 text-center" data-testid="row-empty">
          <p className="text-sm text-muted">No Record of Work rows for this scheme yet.</p>
          <button className="btn-primary px-3 py-1.5 text-xs" disabled={busy} onClick={() => void generate(false)} data-testid="row-generate-editor">
            {busy ? "Generating…" : "Generate ROW for Term"}
          </button>
        </div>
      ) : (
        <div className="card p-0" data-testid="row-table-card">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
            <label className="flex items-center gap-2 text-[11px] text-muted">
              Filter week (screen only)
              <select
                className="input w-28 py-1 text-xs"
                value={weekFilter}
                onChange={(e) => {
                  setWeekFilter(e.target.value);
                  setPage(0);
                }}
                data-testid="row-week-filter"
              >
                <option value="all">All weeks</option>
                {weeks.map((w) => (
                  <option key={w} value={w}>Week {w}</option>
                ))}
              </select>
            </label>
            <span className="text-[11px] text-muted">
              Showing {visible.length} of {filtered.length} rows · PDF exports the full term
            </span>
          </div>
          <p className="border-b border-line px-3 py-1.5 text-[10px] text-muted">
            Work Done starts as grey italic <em>Planned: …</em> — edit it to what actually happened.
            AI is opt-in, only suggests Reflection, and never writes Work Done or sets Status.
          </p>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[1180px] text-left text-[11px]" data-testid="row-table">
              <thead>
                <tr className="border-b border-line bg-slate-50 text-[10px] uppercase tracking-wide text-muted">
                  <th className="px-2 py-2 font-semibold">Date</th>
                  <th className="px-2 py-2 font-semibold">Week</th>
                  <th className="px-2 py-2 font-semibold">Lesson</th>
                  <th className="px-2 py-2 font-semibold">Strand / Sub-Strand</th>
                  <th className="px-2 py-2 font-semibold">Focus</th>
                  <th className="px-2 py-2 font-semibold">Work Done</th>
                  <th className="px-2 py-2 font-semibold">Reflection</th>
                  <th className="px-2 py-2 font-semibold">Status</th>
                  <th className="px-2 py-2 font-semibold">Signature</th>
                  <th className="px-2 py-2 font-semibold">Reset</th>
                </tr>
              </thead>
              <tbody>
                {visible.map((row) => (
                  <RowLine
                    key={row.id}
                    row={row}
                    aiAvailable={doc.ai.available}
                    aiBusy={aiBusyId === row.id}
                    locked={isFinal}
                    highlighted={highlightId === row.id}
                    handlers={handlers}
                  />
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between gap-2 border-t border-line px-3 py-2 text-[11px] text-muted">
            <span>Screen pagination only · Export PDF prints all {doc.rows.length} rows.</span>
            <span className="flex items-center gap-2">
              <button className="btn-mini" disabled={safePage === 0} onClick={() => setPage(safePage - 1)} data-testid="row-prev-page">← Prev</button>
              <span>Page {safePage + 1} / {pageCount}</span>
              <button className="btn-mini" disabled={safePage >= pageCount - 1} onClick={() => setPage(safePage + 1)} data-testid="row-next-page">Next →</button>
            </span>
          </div>
        </div>
      )}

      {/* Gaps drawer --------------------------------------------------------- */}
      {gapsOpen ? (
        <Drawer title={`Gaps — ${cov.gaps.length} lesson(s)`} onClose={() => setGapsOpen(false)} testId="row-gaps-drawer">
          <p className="mb-3 text-xs text-muted">
            Only rows marked <strong>Not Taught</strong> or <strong>Partially Taught</strong> appear here.
            A carry-over creates a new row at the target week/lesson and keeps this original for audit.
          </p>
          {cov.gaps.length === 0 ? (
            <p className="card p-4 text-xs text-muted">No gaps recorded.</p>
          ) : (
            <div className="space-y-2">
              {cov.gaps.map((g) => (
                <GapItem key={g.rowId} gap={g} locked={isFinal} onCarry={handlers.carry} />
              ))}
            </div>
          )}
        </Drawer>
      ) : null}

      {/* Version history drawer ---------------------------------------------- */}
      {historyOpen ? (
        <Drawer title="Version history" onClose={() => setHistoryOpen(false)} testId="row-version-history">
          <p className="mb-3 text-xs text-muted">
            Snapshots of the entire Record of Work. Restoring applies an old snapshot and appends a{" "}
            <strong>new</strong> version — old versions are never deleted.
          </p>
          {versions.length === 0 ? <p className="card p-4 text-xs text-muted">No versions saved yet.</p> : null}
          <div className="space-y-2">
            {versions.map((v) => (
              <div key={v.id} className="card space-y-2 p-3" data-testid={`row-version-${v.versionNumber}`}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs font-bold text-ink">{v.label}</span>
                  <span className="text-[10px] text-muted">{v.createdAt}</span>
                </div>
                <p className="text-[11px] text-muted">{v.comment}</p>
                <div className="flex flex-wrap gap-2">
                  <button className="btn-mini" onClick={() => void openPreview(v)} data-testid={`row-version-preview-${v.versionNumber}`}>Preview</button>
                  <button className="btn-mini" onClick={() => void openDiff(v)} data-testid={`row-version-diff-${v.versionNumber}`}>Compare</button>
                  <button className="btn-mini" disabled={isFinal} onClick={() => setRestoreTarget(v)} data-testid={`row-version-restore-${v.versionNumber}`}>Restore</button>
                </div>
                {restoreTarget?.id === v.id ? (
                  <div className="rounded-lg border border-amber-300 bg-amber-50 p-2 text-[11px] text-amber-900">
                    Restore {v.label}? The current state is replaced and saved as a new version.
                    <div className="mt-2 flex gap-2">
                      <button className="btn-mini-primary" onClick={() => void restore(v)} data-testid="row-restore-confirm">Restore</button>
                      <button className="btn-mini" onClick={() => setRestoreTarget(null)}>Cancel</button>
                    </div>
                  </div>
                ) : null}
              </div>
            ))}
          </div>

          {preview ? (
            <div className="mt-4 rounded-lg border border-line bg-white p-3" data-testid="row-version-preview-panel">
              <p className="text-xs font-bold text-ink">Preview · {preview.label}</p>
              <p className="mt-1 text-[11px] text-muted">
                {(preview.snapshot.rows || []).length} rows · {preview.snapshot.status} ·{" "}
                {(preview.snapshot.rows || []).filter((r) => r.status === "Taught").length} taught
              </p>
              <ul className="mt-2 max-h-48 space-y-1 overflow-y-auto text-[11px]">
                {(preview.snapshot.rows || []).slice(0, 12).map((r) => (
                  <li key={r.id}>Week {r.week} · Lesson {r.lesson} — {r.status || "blank"} — {r.workDone.slice(0, 60)}</li>
                ))}
              </ul>
            </div>
          ) : null}

          {diff ? (
            <div className="mt-4 rounded-lg border border-line bg-white p-3" data-testid="row-version-diff-panel">
              <p className="text-xs font-bold text-ink">{diff.from} → {diff.to}</p>
              <p className="mt-1 text-[11px] text-muted">
                {diff.summary.changed} changed · {diff.summary.added} added · {diff.summary.removed} removed
              </p>
              <ul className="mt-2 max-h-56 space-y-1 overflow-y-auto text-[11px]">
                {diff.cells.length === 0 ? <li>No differences.</li> : null}
                {diff.cells.slice(0, 40).map((c) => (
                  <li key={c.field} className="border-b border-line/60 py-1">
                    <strong>{c.label}</strong>
                    <span className="block text-rose-700">− {c.from || "(empty)"}</span>
                    <span className="block text-emerald-700">+ {c.to || "(empty)"}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </Drawer>
      ) : null}

      {/* Save Version dialog ------------------------------------------------- */}
      {commentOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={() => setCommentOpen(false)}>
          <div className="card w-full max-w-md space-y-3" onClick={(e) => e.stopPropagation()} data-testid="row-save-dialog">
            <h3 className="text-sm font-bold text-ink">Save Version</h3>
            <p className="text-[11px] text-muted">A comment is required. The whole Record of Work is snapshotted.</p>
            <textarea
              className="input min-h-[84px] w-full"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="e.g. Filled Week 2 after teaching"
              data-testid="row-comment"
            />
            {commentError ? <p className="text-[11px] text-rose-700" data-testid="row-comment-error">{commentError}</p> : null}
            <div className="flex justify-end gap-2">
              <button className="btn-ghost text-xs" onClick={() => setCommentOpen(false)}>Cancel</button>
              <button className="btn-primary text-xs" onClick={() => void saveVersion()} data-testid="row-comment-confirm">Save Version</button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Small local primitives                                                     */
/* -------------------------------------------------------------------------- */

function Stat({ label, value, testId, tone }: { label: string; value: number; testId: string; tone?: "green" | "amber" | "red" }) {
  return (
    <span className="flex items-center gap-1.5" data-testid={testId}>
      <span className="text-muted">{label}:</span>
      {tone ? <Badge tone={tone}>{value}</Badge> : <strong className="text-ink">{value}</strong>}
    </span>
  );
}

function Drawer({
  title,
  onClose,
  children,
  testId,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  testId: string;
}) {
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-900/40" onClick={onClose}>
      <aside
        className="h-full w-full max-w-lg overflow-y-auto bg-white p-4 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        data-testid={testId}
      >
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-bold text-ink">{title}</h3>
          <button className="text-xs font-semibold text-brand-700 underline" onClick={onClose}>Close</button>
        </div>
        {children}
      </aside>
    </div>
  );
}

function EditableArea({
  value,
  onSave,
  planned,
  disabled,
  testId,
}: {
  value: string;
  onSave: (text: string) => void;
  planned?: boolean;
  disabled: boolean;
  testId: string;
}) {
  const [text, setText] = useState(value);
  useEffect(() => setText(value), [value]);
  return (
    <textarea
      className={`w-full min-w-[150px] resize-y rounded-md border border-line bg-white px-2 py-1 text-[11px] leading-snug focus:border-brand-400 focus:outline-none ${
        planned ? "italic text-muted" : "text-ink"
      } disabled:opacity-60`}
      rows={3}
      value={text}
      disabled={disabled}
      onChange={(e) => setText(e.target.value)}
      onBlur={() => {
        if (text !== value) onSave(text);
      }}
      data-testid={testId}
    />
  );
}

function AiDraftBox({
  row,
  onAccept,
  onReject,
}: {
  row: RecordOfWorkRow;
  onAccept: (text?: string) => void;
  onReject: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(row.aiDraft || "");
  useEffect(() => {
    setText(row.aiDraft || "");
    setEditing(false);
  }, [row.aiDraft]);
  return (
    <div className="mt-1.5 rounded-lg border border-amber-300 bg-ai p-2" data-testid={`row-ai-draft-${row.id}`}>
      <AIDraftLabel />
      {editing ? (
        <textarea
          className="mt-1 w-full rounded-md border border-amber-300 bg-white px-2 py-1 text-[11px]"
          rows={3}
          value={text}
          onChange={(e) => setText(e.target.value)}
          data-testid={`row-ai-edit-${row.id}`}
        />
      ) : (
        <p className="mt-1 whitespace-pre-wrap text-[11px] leading-relaxed text-amber-950">{row.aiDraft}</p>
      )}
      <div className="mt-1 flex flex-wrap gap-1">
        <button className="rounded-md bg-brand-600 px-2 py-0.5 text-[10px] font-semibold text-white" onClick={() => onAccept(editing ? text : undefined)}>
          Accept
        </button>
        <button className="rounded-md border border-amber-400 px-2 py-0.5 text-[10px] font-semibold text-amber-900" onClick={() => setEditing((v) => !v)}>
          {editing ? "Cancel" : "Edit"}
        </button>
        <button className="rounded-md border border-rose-300 px-2 py-0.5 text-[10px] font-semibold text-rose-700" onClick={onReject}>
          Reject
        </button>
      </div>
    </div>
  );
}

function RowLine({
  row,
  aiAvailable,
  aiBusy,
  locked,
  highlighted,
  handlers,
}: {
  row: RecordOfWorkRow;
  aiAvailable: boolean;
  aiBusy: boolean;
  locked: boolean;
  highlighted: boolean;
  handlers: Handlers;
}) {
  const [targetWeek, setTargetWeek] = useState(String(row.week + 1));
  const [targetLesson, setTargetLesson] = useState("1");
  const [signature, setSignature] = useState(row.signature);
  useEffect(() => setSignature(row.signature), [row.signature]);
  const carryDisabled = locked || !targetWeek || !targetLesson;

  return (
    <tr
      className={`border-b border-line/70 align-top ${highlighted ? "bg-brand-50" : ""} ${row.origin === "carry-over" ? "bg-sky-50/50" : ""}`}
      data-testid={`row-line-${row.id}`}
    >
      <td className="px-2 py-2">
        <input
          className="input w-[112px] px-1 py-1 text-[11px]"
          type="date"
          value={row.date}
          disabled={locked}
          onChange={(e) => handlers.save(row.id, { date: e.target.value })}
          data-testid={`row-date-${row.id}`}
        />
        {row.dateInFuture ? (
          <p className="mt-1 w-[112px] text-[10px] font-semibold text-amber-800" data-testid={`row-future-${row.id}`}>
            Date is in future - is this planned or taught?
          </p>
        ) : null}
      </td>
      <td className="px-2 py-2 font-semibold text-ink">{row.week}</td>
      <td className="px-2 py-2 font-semibold text-ink">{row.lesson}</td>
      <td className="max-w-[170px] px-2 py-2">
        <span className="block font-semibold text-ink">{row.strand}</span>
        <span className="block text-muted">{row.subStrand}</span>
        {row.origin === "carry-over" ? (
          <span
            className="mt-1 block overflow-hidden text-[10px] font-semibold text-sky-800"
            style={{ display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical" }}
            title={row.carryOverNote}
            data-testid={`row-carry-note-${row.id}`}
          >
            {row.carryOverNote}
          </span>
        ) : null}
      </td>
      <td className="max-w-[130px] px-2 py-2 text-muted">
        <span
          className="block overflow-hidden text-ellipsis"
          style={{ display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical" }}
          title={row.focusKeyword}
        >
          {row.focusKeyword}
        </span>
      </td>
      <td className="min-w-[210px] px-2 py-2">
        <EditableArea
          value={row.workDone}
          planned={row.isPlanned}
          disabled={locked}
          onSave={(text) => handlers.save(row.id, { workDone: text })}
          testId={`row-work-${row.id}`}
        />
        {row.teacherEdited ? (
          <span className="mt-1 inline-block" data-testid={`row-edited-${row.id}`}>
            <Badge tone="amber">Teacher Edited</Badge>
          </span>
        ) : null}
        {row.isPlanned ? (
          <p className="mt-1 text-[10px] italic text-muted">Planned text - edit to what actually happened.</p>
        ) : null}
        {row.status === "Not Taught - Carry Over" ? (
          <div className="mt-1.5 rounded-md border border-sky-200 bg-sky-50 p-1.5 text-[10px]">
            <span className="font-semibold text-sky-900">Carry Over to Week</span>
            <div className="mt-1 flex items-center gap-1">
              <input
                className="input w-12 px-1 py-0.5 text-[10px]"
                type="number"
                min={1}
                value={targetWeek}
                onChange={(e) => setTargetWeek(e.target.value)}
                aria-label="Target week"
                data-testid={`row-carry-week-${row.id}`}
              />
              <span>Lesson</span>
              <input
                className="input w-12 px-1 py-0.5 text-[10px]"
                type="number"
                min={1}
                value={targetLesson}
                onChange={(e) => setTargetLesson(e.target.value)}
                aria-label="Target lesson"
                data-testid={`row-carry-lesson-${row.id}`}
              />
              <button
                className="btn-mini"
                disabled={carryDisabled}
                onClick={() => handlers.carry(row.id, Number(targetWeek), Number(targetLesson))}
                data-testid={`row-carry-button-${row.id}`}
              >
                Carry Over
              </button>
            </div>
            {row.carryOverTo ? (
              <p className="mt-1 text-sky-800">
                Already carried to Week {row.carryOverTo.week} Lesson {row.carryOverTo.lesson}.
              </p>
            ) : null}
          </div>
        ) : null}
      </td>
      <td className="min-w-[210px] px-2 py-2">
        <EditableArea
          value={row.reflection}
          disabled={locked}
          onSave={(text) => handlers.save(row.id, { reflection: text })}
          testId={`row-reflection-${row.id}`}
        />
        <button
          className="mt-1.5 rounded-md border border-amber-300 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-900 disabled:opacity-50"
          disabled={!aiAvailable || aiBusy || locked || row.isPlanned}
          title={
            !aiAvailable
              ? "AI is off - configure it in AI & Web Search"
              : row.isPlanned
                ? "Edit Work Done first - AI only uses what you actually wrote"
                : "Opt-in: suggest 2-3 sentences from your Work Done"
          }
          onClick={() => handlers.ai(row.id)}
          data-testid={`row-ai-${row.id}`}
        >
          {aiBusy ? "Suggesting…" : "✨ Suggest Reflection"}
        </button>
        {row.aiDraft ? (
          <AiDraftBox
            row={row}
            onAccept={(text) => handlers.accept(row.id, text)}
            onReject={() => handlers.reject(row.id)}
          />
        ) : null}
      </td>
      <td className="px-2 py-2">
        <select
          className="input w-[166px] max-w-[166px] px-1 py-1 text-[11px]"
          value={row.status}
          disabled={locked}
          onChange={(e) => handlers.save(row.id, { status: e.target.value })}
          data-testid={`row-status-${row.id}`}
        >
          {ROW_STATUSES.map((s: RowEntryStatus) => (
            <option key={s} value={s}>{s || "— Select status —"}</option>
          ))}
        </select>
        {!row.status ? <p className="mt-1 text-[10px] text-rose-700">Status required before Mark Final</p> : null}
      </td>
      <td className="px-2 py-2">
        <input
          className="input w-[100px] px-1 py-1 text-[11px]"
          value={signature}
          disabled={locked}
          placeholder="Name / TSC No"
          onChange={(e) => setSignature(e.target.value)}
          onBlur={() => {
            if (signature !== row.signature) handlers.save(row.id, { signature });
          }}
          data-testid={`row-signature-${row.id}`}
        />
      </td>
      <td className="px-2 py-2">
        <button
          className="btn-mini whitespace-nowrap"
          disabled={locked}
          onClick={() => handlers.reset(row.id)}
          data-testid={`row-reset-${row.id}`}
        >
          Reset to Planned
        </button>
      </td>
    </tr>
  );
}

function GapItem({
  gap,
  locked,
  onCarry,
}: {
  gap: RowGap;
  locked: boolean;
  onCarry: (rowId: string, week: number, lesson: number) => void;
}) {
  const [week, setWeek] = useState(String(gap.week + 1));
  const [lesson, setLesson] = useState("1");
  return (
    <div className="card space-y-1.5 p-3" data-testid={`row-gap-${gap.rowId}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-xs font-bold text-ink">Week {gap.week} · Lesson {gap.lesson}</span>
        <Badge tone="red">{gap.status}</Badge>
      </div>
      <p className="text-[11px] text-muted">{gap.subStrand} · {gap.focusKeyword}</p>
      {gap.reason ? <p className="text-[11px] text-slate-600">Reason: {gap.reason}</p> : null}
      {gap.carryOverTo ? (
        <p className="text-[11px] text-sky-800">
          Carried to Week {gap.carryOverTo.week} Lesson {gap.carryOverTo.lesson}. Original kept.
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-1.5 pt-1">
        <span className="text-[11px] text-muted">Carry Over to Week</span>
        <input
          className="input w-14 px-1 py-0.5 text-[11px]"
          type="number"
          min={1}
          value={week}
          onChange={(e) => setWeek(e.target.value)}
          aria-label="Carry-over week"
          data-testid={`row-gap-week-${gap.rowId}`}
        />
        <span className="text-[11px] text-muted">Lesson</span>
        <input
          className="input w-14 px-1 py-0.5 text-[11px]"
          type="number"
          min={1}
          value={lesson}
          onChange={(e) => setLesson(e.target.value)}
          aria-label="Carry-over lesson"
          data-testid={`row-gap-lesson-${gap.rowId}`}
        />
        <button
          className="btn-mini"
          disabled={locked || !week || !lesson}
          onClick={() => onCarry(gap.rowId, Number(week), Number(lesson))}
          data-testid={`row-gap-carry-${gap.rowId}`}
        >
          Carry Over
        </button>
      </div>
    </div>
  );
}
