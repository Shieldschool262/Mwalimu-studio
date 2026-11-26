import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { Badge, Tabs } from "./ui";
import type {
  DashboardData, DashboardFilters, DashboardGap, DashboardSubject,
  DashboardSubjectStatus,
} from "../types";

type Props = {
  teacherName?: string;
  onViewScheme: (planId: string) => void;
  onViewRow: (planId: string) => void;
  onExport: (planId: string) => void;
  onViewLearners?: () => void;
  onToast: (msg: string) => void;
  onError: (msg: string) => void;
};

type ViewTab = "this-term" | "all-terms" | "by-subject" | "gaps-only";
type SortKey = "subject" | "planned" | "taught" | "partially" | "notTaught" | "coveragePct";
type ActionKind = "carry" | "taught" | "skip" | "bulk-carry" | "bulk-taught" | null;

function readUrlFilters(): DashboardFilters {
  const hash = window.location.hash;
  const qi = hash.indexOf("?");
  if (qi < 0) return {};
  const p = new URLSearchParams(hash.slice(qi + 1));
  const week = Number(p.get("week") || 0);
  return {
    term: p.get("term") || "", year: p.get("year") || "",
    grade: p.get("grade") || "", subject: p.get("subject") || "",
    week: Number.isFinite(week) ? week : 0,
  };
}

/** An empty gap list is NOT proof of 100% coverage. Say what is actually known. */
function emptyGapsMessage(data: DashboardData | null, weekFilter: number): { text: string; complete: boolean } {
  const s = data?.summary;
  const scope = weekFilter ? ` for Week ${weekFilter}` : " in this view";
  if (!s) return { text: "No gap data available yet.", complete: false };
  if (s.coveragePct === null) {
    return {
      text: `No gap statuses${scope}. Coverage cannot be calculated yet — generate a Record of Work first.`,
      complete: false,
    };
  }
  if (s.planned === 0) {
    return { text: `No planned lessons${scope} — there is nothing to mark as taught.`, complete: false };
  }
  if (s.coveragePct === 100 && s.partially === 0 && s.taught >= s.planned) {
    return { text: `✓ No gaps${scope} — all ${s.planned} planned lessons taught. Coverage 100%.`, complete: true };
  }
  if (s.partially > 0) {
    return {
      text: `No gap statuses${scope}. ${s.partially} partially taught lesson(s) counted at half; coverage ${s.coveragePct}%.`,
      complete: false,
    };
  }
  return {
    text: `No gap statuses${scope}. ${s.taught} of ${s.planned} planned lessons marked Taught; coverage ${s.coveragePct}%.`,
    complete: false,
  };
}

function writeUrlFilters(f: DashboardFilters) {
  const p = new URLSearchParams();
  if (f.term) p.set("term", f.term);
  if (f.year) p.set("year", f.year);
  if (f.grade) p.set("grade", f.grade);
  if (f.subject) p.set("subject", f.subject);
  if (f.week) p.set("week", String(f.week));
  window.location.hash = `#/dashboard${p.toString() ? `?${p}` : ""}`;
}

const STATUS_TONE: Record<DashboardSubjectStatus, "green" | "amber" | "red" | "slate" | "dark"> = {
  Complete: "dark", "On Track": "green", Behind: "amber", "Not Started": "slate",
};

function coverBarColor(pct: number | null): string {
  if (pct === null) return "bg-slate-300";
  if (pct === 100) return "bg-emerald-800";
  if (pct >= 90) return "bg-emerald-600";
  if (pct >= 70) return "bg-amber-500";
  return "bg-rose-600";
}

function Stat({ label, value, testId, tone = "text-ink" }: {
  label: string; value: string | number; testId: string; tone?: string;
}) {
  return (
    <div className="card p-3" data-testid={testId}>
      <p className="text-[10px] font-bold uppercase tracking-wider text-muted">{label}</p>
      <p className={`mt-1 text-2xl font-extrabold ${tone}`}>{value}</p>
    </div>
  );
}

function Modal({ children, onClose, testId = "dash-modal" }: {
  children: React.ReactNode; onClose: () => void; testId?: string;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
         onClick={onClose} data-testid={testId}>
      <div className="w-full max-w-md rounded-xl bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        {children}
      </div>
    </div>
  );
}

export default function Dashboard({
  teacherName, onViewScheme, onViewRow, onExport, onViewLearners, onToast, onError,
}: Props) {
  const [view, setView] = useState<ViewTab>("this-term");
  const [filters, setFilters] = useState<DashboardFilters>(readUrlFilters);
  const [data, setData] = useState<DashboardData | null>(null);
  // Phase 10: read-only learner counts. Assessment never feeds coverage maths.
  const [learnerSummary, setLearnerSummary] = useState<{
    active: number; needsSupport: number; iepsActive: number; iepReviewsDue: number;
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "coveragePct", dir: 1 });
  const [expanded, setExpanded] = useState<string | null>(null);
  const [weekFilter, setWeekFilter] = useState(0);
  const [gapFilter, setGapFilter] = useState<"all" | "skipped" | "partial">("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [action, setAction] = useState<ActionKind>(null);
  const [activeGap, setActiveGap] = useState<DashboardGap | null>(null);
  const [form, setForm] = useState({ date: "", workDone: "", reason: "", week: 0, lesson: 1 });
  const [reflectionDraft, setReflectionDraft] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await api.dashboard(filters);
      setData(d);
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters, onError]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { writeUrlFilters(filters); }, [filters]);
  useEffect(() => {
    api.learnerSummary().then(setLearnerSummary).catch(() => setLearnerSummary(null));
  }, [data]);
  const effectiveFilters = useMemo<DashboardFilters>(() => {
    if (view === "all-terms") return { ...filters, term: "" };
    return filters;
  }, [filters, view]);

  const changeFilter = (key: keyof DashboardFilters, value: string) => {
    setFilters((f) => ({ ...f, [key]: value }));
    setSelected(new Set());
  };

  const subjects = useMemo(() => {
    const list = [...(data?.bySubject || [])];
    list.sort((a, b) => {
      let av: string | number = "";
      let bv: string | number = "";
      if (sort.key === "subject") { av = `${a.subject} ${a.grade}`; bv = `${b.subject} ${b.grade}`; }
      else if (sort.key === "coveragePct") {
        av = a.coveragePct === null ? -1 : a.coveragePct;
        bv = b.coveragePct === null ? -1 : b.coveragePct;
      } else { av = (a[sort.key] as number) || 0; bv = (b[sort.key] as number) || 0; }
      if (av < bv) return -1 * sort.dir;
      if (av > bv) return 1 * sort.dir;
      return 0;
    });
    return list;
  }, [data, sort]);

  const gaps = useMemo(() => {
    let list = data?.gaps || [];
    if (weekFilter) list = list.filter((g) => g.week === weekFilter);
    if (gapFilter === "skipped") list = list.filter((g) => g.status === "Not Taught - Skipped");
    return list;
  }, [data, weekFilter, gapFilter]);

  const emptyGap = useMemo(() => emptyGapsMessage(data, weekFilter), [data, weekFilter]);

  const openAction = (kind: ActionKind, gap?: DashboardGap) => {
    setAction(kind);
    setActiveGap(gap || null);
    const nextWeek = (data?.nextWeek?.week || 1);
    setForm({
      date: new Date().toISOString().slice(0, 10), workDone: "", reason: "",
      week: nextWeek, lesson: 1,
    });
  };

  const submitAction = async () => {
    if (!action) return;
    try {
      const ids = action.startsWith("bulk")
        ? [...selected]
        : activeGap ? [activeGap.rowId] : [];
      if (!ids.length) { onError("Select at least one gap."); return; }
      if (action === "carry" || action === "bulk-carry") {
        if (form.week < 1 || form.lesson < 1) { onError("Pick a future week and lesson."); return; }
        for (const id of ids) {
          await api.rowCarryOver(id, form.week, form.lesson);
        }
        onToast(`${ids.length} lesson(s) carried over to Week ${form.week} Lesson ${form.lesson}.`);
      } else if (action === "taught" || action === "bulk-taught") {
        if (!form.workDone.trim()) { onError("Work Done required."); return; }
        if (!form.date.trim()) { onError("Date required."); return; }
        for (const id of ids) {
          await api.rowMarkTaughtById(id, {
            date: form.date, workDone: form.workDone, week: activeGap?.week, lesson: activeGap?.lesson,
          });
        }
        onToast(`${ids.length} lesson(s) marked as Taught.`);
      } else if (action === "skip") {
        if (!form.reason.trim()) { onError("Reason required."); return; }
        await api.rowSkip(activeGap!.rowId, {
          reason: form.reason, week: activeGap!.week, lesson: activeGap!.lesson,
        });
        onToast("Lesson skipped - still counted as Not Taught.");
      }
      setAction(null);
      setSelected(new Set());
      await load();
    } catch (e) {
      onError((e as Error).message);
    }
  };

  const generateRow = async (planId: string) => {
    try {
      await api.rowGenerate(planId, false);
      onToast("Record of Work generated.");
      await load();
    } catch (e) { onError((e as Error).message); }
  };

  const saveReflection = async (planId: string, term: string, year: string) => {
    try {
      await api.dashboardSaveReflection({
        planId, term, year, reflection: reflectionDraft[planId] || "",
      });
      onToast("Term reflection saved.");
      await load();
    } catch (e) { onError((e as Error).message); }
  };

  const s = data?.summary;
  const lowSubjects = (data?.bySubject || []).filter(
    (x) => x.rowExists && x.coveragePct !== null && x.coveragePct < 80,
  );
  const selectedCount = selected.size;

  return (
    <div className="space-y-5" data-testid="dash-root">
      <section className="card p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-extrabold text-ink" data-testid="dash-title">
              My Coverage Dashboard{teacherName ? ` - ${teacherName}` : ""}
            </h1>
            <p className="mt-0.5 text-xs text-muted">
              One teacher, all subjects and terms. Coverage comes from the Record of Work — never from the Scheme plan.
            </p>
          </div>
          <a className="btn-primary px-3 py-1.5 text-xs" href={api.dashboardExportUrl(effectiveFilters)}
             target="_blank" rel="noreferrer" data-testid="dash-export-pdf">
            Export Dashboard PDF
          </a>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-3 rounded-lg border border-brand-200 bg-brand-50 px-3 py-2 text-xs text-brand-900"
             data-testid="dash-learners-card">
          <strong>My Learners:</strong>
          <span>{learnerSummary?.active ?? 0} Active</span>
          <span>· {learnerSummary?.needsSupport ?? 0} Needs Support</span>
          <span>· {learnerSummary?.iepsActive ?? 0} IEPs Active</span>
          {learnerSummary?.iepReviewsDue ? (
            <span className="rounded bg-amber-100 px-2 py-0.5 font-bold text-amber-900"
                  data-testid="dash-iep-review-badge">
              IEP Review Due: {learnerSummary.iepReviewsDue}
            </span>
          ) : null}
          <button className="ml-auto underline" onClick={onViewLearners} data-testid="dash-view-learners">
            View My Learners →
          </button>
        </div>

        <div className="mt-3">
          <Tabs
            value={view}
            onChange={(v) => setView(v as ViewTab)}
            items={[
              { value: "this-term", label: "This Term", testId: "dash-tab-this-term" },
              { value: "all-terms", label: "All Terms", testId: "dash-tab-all-terms" },
              { value: "by-subject", label: "By Subject", testId: "dash-tab-by-subject" },
              { value: "gaps-only", label: "Gaps Only", testId: "dash-tab-gaps-only" },
            ]}
          />
        </div>

        <div className="mt-3 flex flex-wrap items-end gap-2 border-t border-line pt-3">
          <FilterSelect label="Term" testId="dash-filter-term" value={filters.term || ""}
            options={data?.filters?.terms || []} allLabel="All terms"
            onChange={(v) => changeFilter("term", v)} />
          <FilterSelect label="Year" testId="dash-filter-year" value={filters.year || ""}
            options={data?.filters?.years || []} allLabel="All years"
            onChange={(v) => changeFilter("year", v)} />
          <FilterSelect label="Grade" testId="dash-filter-grade" value={filters.grade || ""}
            options={data?.filters?.grades || []} allLabel="All grades"
            onChange={(v) => changeFilter("grade", v)} />
          <FilterSelect label="Subject" testId="dash-filter-subject" value={filters.subject || ""}
            options={data?.filters?.subjects || []} allLabel="All subjects"
            onChange={(v) => changeFilter("subject", v)} />
          <FilterSelect label="Week" testId="dash-filter-week" value={String(filters.week || 0)}
            options={data?.filters?.weeks || []} allLabel="All weeks"
            onChange={(v) => changeFilter("week", v)} />
          <div>
            <p className="field-label">Teacher</p>
            <span className="inline-flex h-[34px] items-center rounded-lg border border-line bg-slate-50 px-3 text-xs font-semibold text-ink">
              Me
            </span>
          </div>
          {(filters.term || filters.year || filters.grade || filters.subject || filters.week) ? (
            <button className="btn-ghost h-[34px] px-2.5 text-xs"
              onClick={() => { setFilters({}); setWeekFilter(0); }}>Clear filters</button>
          ) : null}
        </div>
      </section>

      {loading && !data ? (
        <div className="card p-8 text-center text-sm text-muted">Building coverage summary…</div>
      ) : (
        <>
          <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-7">
            <Stat label="Planned" value={s?.planned ?? 0} testId="dash-stat-planned" />
            <Stat label="Taught" value={s?.taught ?? 0} testId="dash-stat-taught" tone="text-emerald-700" />
            <Stat label="Partially" value={s?.partially ?? 0} testId="dash-stat-partially" tone="text-amber-600" />
            <Stat label="Not Taught" value={s?.notTaught ?? 0} testId="dash-stat-not-taught" tone="text-rose-700" />
            <Stat label="Carry Over" value={s?.carryOver ?? 0} testId="dash-stat-carry-over" />
            <Stat label="Coverage" value={s?.coveragePct === null || s === undefined ? "—" : `${s.coveragePct}%`}
              testId="dash-stat-coverage"
              tone="text-brand-700" />
            <Stat label="Gaps this week" value={s?.gapsThisWeek ?? 0} testId="dash-stat-gaps" tone="text-clay-700" />
          </section>
          <p className="-mt-2 text-[11px] text-muted">
            On Track: {s?.onTrack ?? 0} · Behind: {s?.behind ?? 0} · Complete: {s?.complete ?? 0}
            {(s?.withoutRow ?? 0) > 0 ? ` · ${s?.withoutRow} subject(s) without ROW (coverage unknown, not 0%)` : ""}
          </p>

          {view !== "gaps-only" ? (
            <section className="card overflow-hidden p-0" data-testid="dash-subject-section">
              <div className="flex items-center justify-between border-b border-line px-4 py-3">
                <h2 className="text-sm font-bold text-ink">Coverage by Subject</h2>
                <span className="text-[11px] text-muted">Worst first · click a row for weekly detail</span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[1000px] text-left text-xs" data-testid="dash-subject-table">
                  <thead className="bg-slate-50 text-[10px] uppercase tracking-wide text-muted">
                    <tr>
                      {([
                        ["subject", "Learning Area"], ["planned", "Planned"], ["taught", "Taught"],
                        ["partially", "Partially"], ["notTaught", "Not Taught"], ["coveragePct", "Coverage %"],
                      ] as [SortKey, string][]).map(([key, label]) => (
                        <th key={key} className="px-3 py-2">
                          <button className="hover:text-brand-700" data-testid={`dash-sort-${key}`}
                            onClick={() => setSort((v) => ({
                              key, dir: v.key === key && v.dir === 1 ? -1 : 1,
                            }))}>
                            {label}{sort.key === key ? (sort.dir === 1 ? " ▲" : " ▼") : ""}
                          </button>
                        </th>
                      ))}
                      <th className="px-3 py-2">Status</th>
                      <th className="px-3 py-2">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {subjects.map((sub) => (
                      <SubjectRow key={sub.planId} sub={sub}
                        expanded={expanded === sub.planId}
                        onExpand={() => setExpanded((x) => x === sub.planId ? null : sub.planId)}
                        onViewScheme={() => onViewScheme(sub.planId)}
                        onViewRow={() => onViewRow(sub.planId)}
                        onExport={() => onExport(sub.planId)}
                        onGenerateRow={() => void generateRow(sub.planId)} />
                    ))}
                    {!subjects.length ? (
                      <tr><td colSpan={8} className="px-3 py-8 text-center text-muted">
                        No schemes match these filters.
                      </td></tr>
                    ) : null}
                  </tbody>
                </table>
              </div>
            </section>
          ) : null}

          {view === "this-term" || view === "all-terms" ? (
            <section className="card p-4" data-testid="dash-week-section">
              <h2 className="text-sm font-bold text-ink">Coverage by Week</h2>
              <p className="mt-0.5 text-[11px] text-muted">
                Grey Planned · green Taught · amber Partially · line = cumulative coverage. Click a week to filter gaps.
              </p>
              <WeekChart weeks={data?.byWeek || []} activeWeek={weekFilter}
                onPick={(w) => { setWeekFilter((v) => v === w ? 0 : w); setGapFilter("all"); }} />
            </section>
          ) : null}

          {view !== "by-subject" ? (
            <section className="card p-4" data-testid="dash-gaps-section">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-sm font-bold text-ink">
                  Gaps to Fix — {gaps.length} lessons not taught
                </h2>
                <div className="flex flex-wrap items-center gap-2">
                  <select className="input text-xs" value={gapFilter}
                    onChange={(e) => setGapFilter(e.target.value as typeof gapFilter)}
                    data-testid="dash-gap-filter">
                    <option value="all">Not Taught ({data?.gaps.length ?? 0})</option>
                    <option value="skipped">Skipped</option>
                  </select>
                  {weekFilter ? (
                    <button className="btn-ghost px-2 py-1 text-xs"
                      onClick={() => setWeekFilter(0)}>Week {weekFilter} ×</button>
                  ) : null}
                  <button className="btn-ghost px-2 py-1 text-xs" disabled={!selectedCount}
                    onClick={() => openAction("bulk-carry")}
                    data-testid="dash-bulk-carry">
                    Carry Over Selected ({selectedCount})
                  </button>
                  <button className="btn-ghost px-2 py-1 text-xs" disabled={!selectedCount}
                    onClick={() => openAction("bulk-taught")}
                    data-testid="dash-bulk-taught">
                    Mark Selected as Taught
                  </button>
                </div>
              </div>
              {gaps.length === 0 ? (
                <div
                  className={`mt-3 rounded-lg border p-5 text-center ${
                    emptyGap.complete
                      ? "border-emerald-200 bg-emerald-50"
                      : "border-amber-200 bg-amber-50"
                  }`}
                  data-testid="dash-empty-gaps"
                >
                  <p className={`text-sm font-bold ${
                    emptyGap.complete
                      ? "text-emerald-800" : "text-amber-900"
                  }`}>
                    {emptyGap.text}
                  </p>
                  {weekFilter ? (
                    <button className="mt-2 text-xs underline" onClick={() => setWeekFilter(0)}>
                      Show all weeks
                    </button>
                  ) : null}
                </div>
              ) : (
                <div className="mt-3 overflow-x-auto">
                  <table className="w-full min-w-[1050px] text-left text-xs" data-testid="dash-gaps-table">
                    <thead className="bg-slate-50 text-[10px] uppercase tracking-wide text-muted">
                      <tr>
                        <th className="px-2 py-2"><input type="checkbox" aria-label="Select all gaps"
                          checked={selectedCount === gaps.length && gaps.length > 0}
                          onChange={(e) => setSelected(e.target.checked ? new Set(gaps.map((g) => g.rowId)) : new Set())}
                          data-testid="dash-select-all" /></th>
                        <th className="px-2 py-2">Week / Lesson</th><th className="px-2 py-2">Subject</th>
                        <th className="px-2 py-2">Grade</th><th className="px-2 py-2">Strand / Focus</th>
                        <th className="px-2 py-2">Reason</th><th className="px-2 py-2">Carry Over To</th>
                        <th className="px-2 py-2">Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {gaps.map((g) => (
                        <tr key={g.rowId} className="border-t border-line" data-testid={`dash-gap-${g.rowId}`}>
                          <td className="px-2 py-2">
                            <input type="checkbox" checked={selected.has(g.rowId)}
                              onChange={(e) => setSelected((prev) => {
                                const next = new Set(prev);
                                if (e.target.checked) next.add(g.rowId); else next.delete(g.rowId);
                                return next;
                              })} data-testid={`dash-gap-check-${g.rowId}`} />
                          </td>
                          <td className="whitespace-nowrap px-2 py-2 font-semibold">
                            W{g.week} L{g.lesson}
                            <span className="ml-1 text-[9px] font-normal text-rose-600">
                              {g.status === "Not Taught - Skipped" ? "Skipped"
                                : g.status === "Not Taught - Carry Over" ? "Carry Over" : ""}
                            </span>
                          </td>
                          <td className="px-2 py-2">{g.subject}</td>
                          <td className="px-2 py-2">{g.grade}</td>
                          <td className="px-2 py-2">{[g.strand, g.focus].filter(Boolean).join(" / ")}</td>
                          <td className="max-w-[220px] truncate px-2 py-2 text-muted" title={g.reason}>
                            {g.reason || g.status}
                          </td>
                          <td className="whitespace-nowrap px-2 py-2">
                            {g.carryOverTo ? `W${g.carryOverTo.week} L${g.carryOverTo.lesson}` : "—"}
                          </td>
                          <td className="whitespace-nowrap px-2 py-2">
                            <button className="btn-mini-primary mr-1" onClick={() => openAction("carry", g)}
                              data-testid={`dash-gap-carry-${g.rowId}`}>Carry Over</button>
                            <button className="btn-mini mr-1" onClick={() => openAction("taught", g)}
                              data-testid={`dash-gap-taught-${g.rowId}`}>Mark as Taught</button>
                            <button className="btn-mini" onClick={() => openAction("skip", g)}
                              data-testid={`dash-gap-skip-${g.rowId}`}>Skip</button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {data?.partiallyTaught?.length ? (
                <p className="mt-3 text-[11px] text-amber-700">
                  {data.partiallyTaught.length} Partially Taught lesson(s) tracked separately — never counted as gaps.
                </p>
              ) : null}
            </section>
          ) : null}

          <section className="card p-4" data-testid="dash-next-week">
            <h2 className="text-sm font-bold text-ink">
              Next Week — Week {data?.nextWeek?.week ?? "—"}
            </h2>
            <p className="mt-1 text-xs text-muted">
              Planned: {data?.nextWeek?.planned ?? 0} + Carry-over: {data?.nextWeek?.carryOver ?? 0}
              {" "}= <strong>{data?.nextWeek?.total ?? 0} lessons to teach</strong>
            </p>
            {data?.nextWeek?.overloaded ? (
              <div className="mt-2 flex flex-wrap items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900"
                   data-testid="dash-next-banner">
                Week {data.nextWeek.week} has {data.nextWeek.total} lessons
                ({data.nextWeek.planned} planned + {data.nextWeek.carryOver} carry-over).
                That's {data.nextWeek.carryOver} extra. Consider moving some to Week {data.nextWeek.week + 1}.
              </div>
            ) : null}
            {(data?.gaps || []).filter((g) => g.carryOverTo).length ? (
              <div className="mt-3 space-y-1">
                {(data?.gaps || []).filter((g) => g.carryOverTo).map((g) => (
                  <div key={g.rowId} className="flex flex-wrap items-center gap-2 rounded-lg border border-line px-3 py-2 text-xs">
                    <Badge tone="amber">Carry-Over</Badge>
                    <span>{g.subject} {g.grade} · W{g.week} L{g.lesson} · {g.focus}</span>
                    <span className="text-muted">→ W{g.carryOverTo?.week} L{g.carryOverTo?.lesson}</span>
                    <select className="input ml-auto text-[11px]" defaultValue={String((g.carryOverTo?.week || 0) + 1)}
                      aria-label={`Move to week for gap ${g.rowId}`}
                      data-testid={`dash-move-${g.rowId}`}
                      onChange={(e) => {
                        void api.rowCarryOver(g.rowId, Number(e.target.value), 1)
                          .then(() => { onToast(`Moved to Week ${e.target.value}.`); return load(); })
                          .catch((err: Error) => onError(err.message));
                      }}>
                      <option value="">Move to week…</option>
                      {(data?.filters?.weeks || []).filter(
                        (w) => Number(w) > (g.carryOverTo?.week || g.week),
                      ).map((w) => <option key={w} value={w}>Week {w}</option>)}
                    </select>
                  </div>
                ))}
              </div>
            ) : null}
          </section>

          {lowSubjects.length ? (
            <section className="card p-4" data-testid="dash-reflections">
              <h2 className="text-sm font-bold text-ink">Teacher Reflection</h2>
              <p className="mt-0.5 text-[11px] text-muted">
                Coverage below 80% — only the teacher writes this. AI never fills term reflections.
              </p>
              <div className="mt-3 space-y-3">
                {lowSubjects.map((sub) => {
                  const saved = (data?.reflections || []).find(
                    (r) => r.planId === sub.planId && r.term === sub.term && r.year === sub.year,
                  );
                  const draft = reflectionDraft[sub.planId] ?? saved?.reflection ?? "";
                  return (
                    <div key={sub.planId} className="rounded-lg border border-amber-200 bg-amber-50 p-3">
                      <p className="text-xs font-semibold text-amber-900">
                        {sub.subject} {sub.grade} coverage is {sub.coveragePct}%. What happened?
                      </p>
                      <textarea className="input mt-2 min-h-[70px] w-full" value={draft}
                        placeholder="Write your own term reflection…"
                        data-testid={`dash-reflection-${sub.planId}`}
                        onChange={(e) => setReflectionDraft((d) => ({ ...d, [sub.planId]: e.target.value }))} />
                      <div className="mt-2 flex items-center gap-2">
                        <button className="btn-primary px-2.5 py-1 text-xs"
                          data-testid={`dash-reflection-save-${sub.planId}`}
                          onClick={() => void saveReflection(sub.planId, sub.term, sub.year)}>
                          {saved?.reflection ? "Update Reflection" : "Save Reflection"}
                        </button>
                        {saved?.updatedAt ? (
                          <span className="text-[10px] text-amber-800">
                            Saved {saved.updatedAt}
                          </span>
                        ) : null}
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          ) : null}
        </>
      )}

      <footer className="border-t border-line pt-3 text-[11px] text-muted">
        Last updated: {data?.lastUpdated || "—"} — from Record of Work · Coverage = (Taught + Partially × 0.5) / Planned
      </footer>

      {action ? (
        <Modal onClose={() => setAction(null)} testId="dash-action-modal">
          <h3 className="text-sm font-bold text-ink">
            {action === "carry" || action === "bulk-carry" ? "Carry Over to a future week"
              : action === "taught" || action === "bulk-taught" ? "Mark as Taught"
              : "Skip this lesson"}
          </h3>
          <p className="mt-1 text-xs text-muted">
            {action.startsWith("bulk")
              ? `This will update ${selectedCount} selected lesson(s).`
              : `Week ${activeGap?.week ?? "—"} Lesson ${activeGap?.lesson ?? "—"} · ${activeGap?.subject ?? ""}`}
          </p>
          {action === "carry" || action === "bulk-carry" ? (
            <div className="mt-3 flex gap-2">
              <label className="flex-1 text-xs">Week
                <select className="input mt-1 w-full" value={form.week}
                  data-testid="dash-modal-week"
                  onChange={(e) => setForm((v) => ({ ...v, week: Number(e.target.value) }))}>
                  {(data?.filters?.weeks || []).filter(
                    (w) => Number(w) > (activeGap?.week || data?.currentWeek || 0),
                  ).map((w) => <option key={w} value={Number(w)}>Week {w}</option>)}
                </select>
              </label>
              <label className="w-24 text-xs">Lesson
                <input type="number" min={1} className="input mt-1 w-full" value={form.lesson}
                  data-testid="dash-modal-lesson"
                  onChange={(e) => setForm((v) => ({ ...v, lesson: Number(e.target.value) }))} />
              </label>
            </div>
          ) : null}
          {action === "taught" || action === "bulk-taught" ? (
            <div className="mt-3 space-y-2">
              <label className="block text-xs">Date *
                <input type="date" className="input mt-1 w-full" value={form.date}
                  data-testid="dash-modal-date"
                  onChange={(e) => setForm((v) => ({ ...v, date: e.target.value }))} />
              </label>
              <label className="block text-xs">Work Done * (required)
                <textarea className="input mt-1 min-h-[80px] w-full" value={form.workDone}
                  data-testid="dash-modal-work" placeholder="What was actually covered…"
                  onChange={(e) => setForm((v) => ({ ...v, workDone: e.target.value }))} />
              </label>
            </div>
          ) : null}
          {action === "skip" ? (
            <label className="mt-3 block text-xs">Reason * (required)
              <textarea className="input mt-1 min-h-[80px] w-full" value={form.reason}
                data-testid="dash-modal-reason" placeholder="e.g. Sports Day"
                onChange={(e) => setForm((v) => ({ ...v, reason: e.target.value }))} />
            </label>
          ) : null}
          <div className="mt-4 flex justify-end gap-2">
            <button className="btn-ghost px-3 py-1.5 text-xs" data-testid="dash-modal-cancel"
              onClick={() => setAction(null)}>Cancel</button>
            <button className="btn-primary px-3 py-1.5 text-xs" data-testid="dash-modal-submit"
              onClick={() => void submitAction()}>
              {action === "skip" ? "Skip lesson" : action.startsWith("bulk") ? "Confirm" : "Save"}
            </button>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}

function FilterSelect({ label, value, options, allLabel, testId, onChange }: {
  label: string; value: string; options: string[]; allLabel: string;
  testId: string; onChange: (v: string) => void;
}) {
  return (
    <label className="block">
      <span className="field-label">{label}</span>
      <select className="input h-[34px] min-w-[110px] text-xs" value={value}
        data-testid={testId} onChange={(e) => onChange(e.target.value)}>
        <option value="">{allLabel}</option>
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </label>
  );
}

function SubjectRow({ sub, expanded, onExpand, onViewScheme, onViewRow, onExport, onGenerateRow }: {
  sub: DashboardSubject; expanded: boolean; onExpand: () => void;
  onViewScheme: () => void; onViewRow: () => void; onExport: () => void; onGenerateRow: () => void;
}) {
  const pct = sub.coveragePct;
  return (
    <>
      <tr className={`cursor-pointer border-t border-line ${expanded ? "bg-brand-50/40" : ""}`}
          onClick={onExpand} data-testid={`dash-subject-row-${sub.planId}`}>
        <td className="px-3 py-2 font-semibold">
          {sub.subject} {sub.grade}
          {!sub.rowExists ? <span className="ml-1 text-[10px] font-normal text-rose-700">(ROW not created)</span> : null}
        </td>
        <td className="px-3 py-2">{sub.planned}</td>
        <td className="px-3 py-2 text-emerald-700">{sub.taught}</td>
        <td className="px-3 py-2 text-amber-700">{sub.partially}</td>
        <td className="px-3 py-2 text-rose-700">{sub.notTaught}</td>
        <td className="px-3 py-2">
          <div className="flex items-center gap-2">
            <div className="h-2 w-20 overflow-hidden rounded-full bg-slate-100">
              <div className={`h-full ${coverBarColor(pct)}`} style={{ width: `${pct ?? 0}%` }} />
            </div>
            <span className="font-bold">{pct === null ? "—" : `${pct}%`}</span>
          </div>
        </td>
        <td className="px-3 py-2">
          <Badge tone={STATUS_TONE[sub.status]}>{sub.status}</Badge>
        </td>
        <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
          <div className="flex flex-wrap gap-1">
            <button className="btn-mini" onClick={onViewScheme}
              data-testid={`dash-view-scheme-${sub.planId}`}>View Scheme</button>
            <button className="btn-mini" onClick={onViewRow}
              data-testid={`dash-view-row-${sub.planId}`}>View ROW</button>
            <button className="btn-mini" onClick={onExport}
              data-testid={`dash-export-${sub.planId}`}>📦 Export</button>
            {!sub.rowExists ? (
              <button className="btn-mini-primary" onClick={onGenerateRow}
                data-testid={`dash-generate-row-${sub.planId}`}>Generate ROW</button>
            ) : null}
          </div>
        </td>
      </tr>
      {expanded ? (
        <tr data-testid={`dash-week-detail-${sub.planId}`}>
          <td colSpan={8} className="bg-slate-50 px-6 py-3">
            <p className="mb-2 text-[11px] font-bold uppercase tracking-wide text-muted">Per-week breakdown</p>
            <div className="flex flex-wrap gap-2">
              {sub.byWeek.length ? sub.byWeek.map((w) => (
                <span key={w.week} className="rounded-lg border border-line bg-white px-2.5 py-1 text-[11px]">
                  Week {w.week}: <strong>{w.taught}/{w.planned}</strong>
                </span>
              )) : <span className="text-xs text-muted">No Record of Work rows yet.</span>}
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}

function WeekChart({ weeks, activeWeek, onPick }: {
  weeks: { week: number; planned: number; taught: number; partially: number; cumulativePct: number; carryOver: number }[];
  activeWeek: number; onPick: (week: number) => void;
}) {
  const max = Math.max(1, ...weeks.map((w) => w.planned));
  return (
    <div className="mt-4" data-testid="dash-week-chart">
      <div className="mt-5 flex h-[190px] items-end gap-1.5 border-b border-line pb-1">
        {weeks.map((w) => (
          <button key={w.week} className="group relative flex h-full flex-1 flex-col justify-end"
            onClick={() => onPick(w.week)} data-testid={`dash-week-bar-${w.week}`}
            title={`Week ${w.week}: ${w.taught}/${w.planned} taught, ${w.cumulativePct}% cumulative`}>
            {w.carryOver ? (
              <span className="absolute -top-4 left-1/2 -translate-x-1/2 whitespace-nowrap text-[9px] font-bold text-amber-700">
                +{w.carryOver} carry-over
              </span>
            ) : null}
            <span className="absolute top-0 left-1/2 -translate-x-1/2 text-[9px] font-bold text-brand-700 opacity-0 group-hover:opacity-100">
              {w.cumulativePct}%
            </span>
            <div className="flex h-full items-end justify-center gap-0.5">
              <div className="w-1/4 bg-slate-300" style={{ height: `${(w.planned / max) * 100}%` }} />
              <div className="w-1/4 bg-emerald-600" style={{ height: `${(w.taught / max) * 100}%` }} />
              <div className="w-1/4 bg-amber-400" style={{ height: `${(w.partially / max) * 100}%` }} />
            </div>
          </button>
        ))}
        {!weeks.length ? <p className="m-auto text-xs text-muted">No Record of Work data yet.</p> : null}
      </div>
      <div className="mt-1 flex gap-1.5">
        {weeks.map((w) => (
          <button key={w.week} onClick={() => onPick(w.week)}
            className={`flex-1 text-center text-[10px] ${activeWeek === w.week ? "font-bold text-brand-700" : "text-muted"}`}>
            W{w.week}
          </button>
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-3 text-[10px] text-muted">
        <span><i className="mr-1 inline-block h-2 w-2 bg-slate-300" />Planned</span>
        <span><i className="mr-1 inline-block h-2 w-2 bg-emerald-600" />Taught</span>
        <span><i className="mr-1 inline-block h-2 w-2 bg-amber-400" />Partially</span>
        <span className="font-semibold text-brand-700">Cumulative: {weeks.length ? `${weeks[weeks.length - 1].cumulativePct}%` : "—"}</span>
        {activeWeek ? <span className="font-semibold text-brand-700">Filtered to Week {activeWeek}</span> : null}
      </div>
    </div>
  );
}
