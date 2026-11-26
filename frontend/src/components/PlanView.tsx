import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type {
  LessonNotesList,
  LessonPicker,
  LessonPlanList,
  NotesPicker,
  PlanDiff,
  PlanDocument,
  PlanSection,
  PlanVersion,
  SchemeColumn,
} from "../types";
import NotesPickerModal from "./NotesPickerModal";
import {
  AIDraftLabel,
  Badge,
  ConfirmDialog,
  ExpandableList,
  ExpandableText,
  ProvenanceBadge,
} from "./ui";

interface Props {
  planId: string;
  onToast: (msg: string) => void;
  onError: (msg: string) => void;
  onViewSource: (documentId: string, chunkId: string) => void;
  onOpenLesson: (lessonId: string) => void;
  onOpenNotes: (noteId: string) => void;
  onOpenRow?: (planId: string) => void;
  onExportTermPack?: (planId: string) => void;
  onCrumb?: (parts: string[]) => void;
  onBack: () => void;
}

type ConfirmState = { title: string; body: string; action: () => void } | null;

/** The exact 9 printed columns, in the required order. */
const COLUMNS: SchemeColumn[] = [
  { key: "week", index: 0, label: "Week", source: "plan", width: "6%" },
  { key: "lesson", index: 1, label: "Lesson", source: "plan", width: "6%" },
  { key: "strand", index: 2, label: "Strand / Sub-Strand", source: "source", width: "14%" },
  { key: "outcomes", index: 3, label: "Specific Learning Outcomes", source: "source", width: "16%" },
  { key: "experiences", index: 4, label: "Learning Experiences", source: "source", width: "16%" },
  { key: "kiqs", index: 5, label: "Key Inquiry Questions", source: "source", width: "14%" },
  { key: "resources", index: 6, label: "Learning Resources", source: "source", width: "10%" },
  { key: "assessment", index: 7, label: "Assessment", source: "source", width: "10%" },
  { key: "reflection", index: 8, label: "Reflection (Teacher to fill after teaching)", source: "teacher", width: "8%" },
];

const MIN_WIDTHS: Record<string, number> = {
  week: 58,
  lesson: 64,
  strand: 140,
  subStrand: 140,
  outcomes: 280,
  experiences: 280,
  kiqs: 200,
  resources: 170,
  assessment: 180,
  reflection: 160,
};

const SUBJECT_SHORT: Record<string, string> = {
  Mathematics: "Maths",
  "English Language": "English",
  English: "English",
  Kiswahili: "Kiswahili",
  "Science and Technology": "Science",
  "Social Studies": "Social Studies",
  "Religious Education": "RE",
  CRE: "CRE",
  "Agriculture and Nutrition": "Agriculture",
  Agriculture: "Agriculture",
};

function subjectShort(subject: string): string {
  return SUBJECT_SHORT[subject] ?? subject;
}

function shortHash(input: string): string {
  let h1 = 0xdeadbeef;
  let h2 = 0x41c6ce57;
  for (let i = 0; i < input.length; i += 1) {
    const ch = input.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return `${(h2 >>> 0).toString(16).padStart(8, "0")}${(h1 >>> 0).toString(16).padStart(8, "0")}`;
}

function lessonRange(section: PlanSection): string {
  const count = section.weekLessonCount ?? section.lessonCount ?? 5;
  return `Lesson 1-${count}`;
}

function citationText(section: PlanSection, subject: string): string {
  const page = section.citations[0]?.pageNumber;
  const wk = section.week ?? "?";
  const of = section.weekCount ?? 1;
  return `[${subjectShort(subject)} p.${page ?? "?"} - Wk ${wk}/${of}]`;
}

export default function PlanView({
  planId,
  onToast,
  onError,
  onViewSource,
  onOpenLesson,
  onOpenNotes,
  onOpenRow,
  onExportTermPack,
  onCrumb,
  onBack,
}: Props) {
  const [plan, setPlan] = useState<PlanDocument | null>(null);
  const [lessons, setLessons] = useState<LessonPlanList>({ plans: [], groups: [], count: 0 });
  const [notes, setNotes] = useState<LessonNotesList>({ notes: [], schemes: [], count: 0 });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [validation, setValidation] = useState<string[]>([]);
  const [editKey, setEditKey] = useState<{ sectionId: string; field: string } | null>(null);

  const [commentOpen, setCommentOpen] = useState(false);
  const [comment, setComment] = useState("");
  const [commentError, setCommentError] = useState<string | null>(null);

  const [historyOpen, setHistoryOpen] = useState(false);
  const [versions, setVersions] = useState<PlanVersion[]>([]);
  const [diff, setDiff] = useState<PlanDiff | null>(null);

  const [picker, setPicker] = useState<LessonPicker | null>(null);
  const [notesPicker, setNotesPicker] = useState<NotesPicker | null>(null);
  const [confirm, setConfirm] = useState<ConfirmState>(null);

  const [inspector, setInspector] = useState<PlanSection | null>(null);
  const [filterOpen, setFilterOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const [bulkOpen, setBulkOpen] = useState(false);
  const [paceOpen, setPaceOpen] = useState(false);
  const [aiOptIn, setAiOptIn] = useState(false);
  const [notesListOpen, setNotesListOpen] = useState(false);

  const load = () => {
    setLoading(true);
    Promise.all([api.plan(planId), api.lessonPlans({ planId }), api.lessonNotes({ planId })])
      .then(([p, ls, ns]) => {
        setPlan(p);
        setLessons(ls);
        setNotes(ns);
      })
      .catch((e) => onError((e as Error).message))
      .finally(() => setLoading(false));
  };

  useEffect(load, [planId]);

  useEffect(() => {
    if (!plan || !onCrumb) return;
    onCrumb([`${plan.grade} ${plan.subject}`, plan.term]);
  }, [plan, onCrumb]);

  const refreshLessons = () =>
    api
      .lessonPlans({ planId })
      .then(setLessons)
      .catch((e) => onError((e as Error).message));

  const refreshNotes = () =>
    api
      .lessonNotes({ planId })
      .then(setNotes)
      .catch((e) => onError((e as Error).message));

  const fail = (e: unknown) => {
    const message = (e as Error).message;
    setValidation(message.split(" | ").filter(Boolean));
    onError(message);
  };

  const run = async (fn: () => Promise<PlanDocument | void>, ok?: string) => {
    setBusy(true);
    setValidation([]);
    try {
      const next = await fn();
      if (next) setPlan(next);
      if (ok) onToast(ok);
      return true;
    } catch (e) {
      fail(e);
      return false;
    } finally {
      setBusy(false);
    }
  };

  const saveVersion = async () => {
    if (!comment.trim()) {
      setCommentError("A comment is required, e.g. 'Fixed Week 3 outcomes'.");
      return;
    }
    setBusy(true);
    setValidation([]);
    try {
      const res = await api.createPlanVersion(planId, comment.trim());
      setPlan(res.plan);
      setCommentOpen(false);
      setComment("");
      setCommentError(null);
      onToast(`Saved ${res.label}`);
    } catch (e) {
      setCommentError((e as Error).message);
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const duplicate = async () => {
    setBusy(true);
    try {
      const copy = await api.duplicatePlan(planId);
      onToast(`Duplicated to ${copy.term}`);
      setPlan(copy);
      refreshLessons();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const markFinal = async () => {
    setBusy(true);
    setValidation([]);
    try {
      setPlan(await api.planStatus(planId, "Final"));
      onToast("Marked Final");
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const unlock = async () => {
    setBusy(true);
    setValidation([]);
    try {
      const res = await api.unlockPlan(planId);
      setPlan(res);
      onToast(`Unlocked as ${res.unlockedVersion?.label ?? "a new Draft"}`);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const openHistory = async () => {
    setHistoryOpen(true);
    setDiff(null);
    try {
      setVersions((await api.planVersions(planId)).versions);
    } catch (e) {
      fail(e);
    }
  };

  const openDiff = async (versionId: string) => {
    try {
      setDiff(await api.planVersionDiff(planId, versionId));
    } catch (e) {
      fail(e);
    }
  };

  const restoreVersion = (version: PlanVersion) => {
    setConfirm({
      title: `Restore ${version.label}?`,
      body: "This copies the saved snapshot into the working plan and appends a NEW version. No version is ever deleted.",
      action: async () => {
        setConfirm(null);
        await run(async () => {
          const res = await api.restorePlanVersion(planId, version.id);
          onToast(`Restored - saved as ${res.restoredVersion.label}`);
          return res;
        });
        openHistory();
      },
    });
  };

  const resetRow = (section: PlanSection) => {
    setConfirm({
      title: `Reset Week ${section.week} to source?`,
      body: "Outcomes, Experiences, KIQs, Resources and Assessment go back to the vetted source. This row's Reflection is kept.",
      action: async () => {
        setConfirm(null);
        await run(() => api.resetSource(planId, section.id), "Row reset to source");
      },
    });
  };

  const openPicker = async (section: PlanSection) => {
    try {
      setPicker(await api.lessonPicker(planId, section.id));
      setInspector(null);
    } catch (e) {
      fail(e);
    }
  };

  const openNotesPicker = async (section: PlanSection) => {
    try {
      setNotesPicker(await api.notesPicker(planId, section.id));
    } catch (e) {
      fail(e);
    }
  };

  const extendRow = async (section: PlanSection, count: number) => {
    await run(
      () => api.extendRow(planId, section.id, count),
      `Week ${section.week} now has ${count} lessons`,
    );
  };

  const bulkResources = (code: string, name: string, value: string) => {
    if (!value.trim()) {
      onError("Enter the resources text first.");
      return;
    }
    setConfirm({
      title: `Edit Resources for All Weeks (${code})?`,
      body: `Every weekly row of ${name} will use: "${value}". You can undo the last change.`,
      action: async () => {
        setConfirm(null);
        await run(() => api.bulkResources(planId, code, value), "Resources updated for all weeks");
      },
    });
  };

  const clearReflections = () => {
    setConfirm({
      title: "Clear All Reflections?",
      body: "Every weekly row's Reflection / Remarks will be cleared. You can undo the last cleared row.",
      action: async () => {
        setConfirm(null);
        await run(() => api.clearReflections(planId), "All reflections cleared");
      },
    });
  };

  const saveCell = async (sectionId: string, field: string, value: unknown) => {
    const ok = await run(
      () => api.editSection(planId, sectionId, { [field]: value }),
      "Saved",
    );
    if (ok) setEditKey(null);
  };

  const saveHeader = async (patch: Record<string, unknown>) => {
    await run(() => api.editPlanHeader(planId, patch), "Header updated");
  };

  const [rebalancing, setRebalancing] = useState<string | null>(null);
  const [pace, setPace] = useState<Record<string, number>>({});
  const rebalance = async (code: string) => {
    if (!plan) return;
    setRebalancing(code);
    try {
      const lp = pace[code] ?? plan.allocation.lessonsPerWeek;
      setPlan(await api.rebalance(planId, code, lp));
      onToast(`Re-balanced sub-strand ${code} at ${lp} lessons/week`);
    } catch (e) {
      fail(e);
    } finally {
      setRebalancing(null);
    }
  };

  const groups = useMemo(() => {
    const map = new Map<
      string,
      { code: string; name: string; weeks: number[]; edited: number; sections: PlanSection[] }
    >();
    for (const s of plan?.sections ?? []) {
      const code = s.subStrandCode ?? "";
      const g = map.get(code) ?? {
        code,
        name: s.subStrand,
        weeks: [],
        edited: 0,
        sections: [],
      };
      if (s.week != null) g.weeks.push(s.week);
      if (s.edited) g.edited += 1;
      g.sections.push(s);
      map.set(code, g);
    }
    return [...map.values()];
  }, [plan]);

  const lessonsBySection = useMemo(() => {
    const map = new Map<string, LessonPlanList["plans"]>();
    for (const lp of lessons.plans) {
      const list = map.get(lp.sectionId) ?? [];
      list.push(lp);
      map.set(lp.sectionId, list);
    }
    return map;
  }, [lessons]);

  const notesBySection = useMemo(() => {
    const map = new Map<string, LessonNotesList["notes"]>();
    for (const n of notes.notes) {
      const list = map.get(n.sectionId) ?? [];
      list.push(n);
      map.set(n.sectionId, list);
    }
    return map;
  }, [notes]);

  const totals = useMemo(
    () => (plan ? { edited: plan.sections.filter((s) => s.edited).length } : { edited: 0 }),
    [plan],
  );

  const filteredSections = useMemo(() => {
    const sections = plan?.sections ?? [];
    const q = filter.trim().toLowerCase();
    if (!q) return sections;
    return sections.filter((s) =>
      [
        s.weekLabel,
        s.lessonLabel,
        s.strand ?? "",
        s.subStrand,
        ...s.outcomes,
        ...s.experiences,
        ...s.kiqs,
        s.resources.text,
        s.assessment.text,
        s.reflection.text,
      ]
        .join(" ")
        .toLowerCase()
        .includes(q),
    );
  }, [plan, filter]);

  const [bulkDraft, setBulkDraft] = useState<Record<string, string>>({});

  if (loading) return <p className="card p-6 text-center text-sm text-muted">Loading scheme…</p>;
  if (!plan) return <p className="card p-6 text-center text-sm text-muted">Scheme not found.</p>;

  const h = plan.header;
  const isFinal = plan.status === "Final";
  const vettedCount = plan.sections.filter((s) => s.sourceVetted).length;
  const allVetted = vettedCount === plan.sections.length && plan.sections.length > 0;
  const docHash = shortHash(`${plan.id}:${plan.createdAt}:${plan.templateVersion}`);
  const selectedLessonCount = inspector
    ? inspector.weekLessonCount ?? inspector.lessonCount ?? 5
    : 5;
  const inspectorLessons = inspector ? lessonsBySection.get(inspector.id) ?? [] : [];

  return (
    <div className="space-y-4" data-testid="plan-view">
      <section className="card p-0" data-testid="scheme-head">
        <div className="flex flex-wrap items-start gap-3 border-b border-line px-4 py-3">
          <button className="btn-ghost px-2 py-1 text-xs" onClick={onBack} data-testid="plan-back">
            ← Back
          </button>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-[18px] font-bold leading-tight text-ink" data-testid="scheme-title">
                {plan.title}
              </h1>
              <Badge tone={isFinal ? "green" : "amber"} data-testid="plan-status">
                {isFinal ? plan.finalVersionLabel || "Final" : "Draft"}
              </Badge>
              {plan.dirty ? <Badge tone="amber" data-testid="plan-dirty">Dirty - Unsaved</Badge> : null}
            </div>
            <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted">
              <span className="font-mono text-[10px] text-slate-500">Doc hash {docHash}</span>
              <span>·</span>
              <span>{plan.templateVersion}</span>
              <span>·</span>
              <span>
                {plan.sectionCount} rows · {plan.allocation.totalLessons} lessons ·{" "}
                {plan.allocation.lessonsPerWeek}/week × {plan.allocation.totalWeeks} weeks
              </span>
              {totals.edited ? (
                <>
                  <span>·</span>
                  <span>{totals.edited} teacher-edited</span>
                </>
              ) : null}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              className="text-[11px] font-semibold text-brand-700 underline hover:text-brand-900"
              onClick={openHistory}
              data-testid="plan-history"
            >
              Version history
            </button>
            <button
              className="btn-primary px-2.5 py-1.5 text-xs"
              onClick={() => {
                setCommentError(null);
                setCommentOpen(true);
              }}
              disabled={busy}
              data-testid="plan-save-version"
            >
              Save Version
            </button>
            {isFinal ? (
              <button className="btn-ghost px-2.5 py-1.5 text-xs" onClick={unlock} disabled={busy} data-testid="plan-unlock">
                Unlock to Edit
              </button>
            ) : (
              <button className="btn-ghost px-2.5 py-1.5 text-xs" onClick={markFinal} disabled={busy} data-testid="plan-final">
                Mark Final
              </button>
            )}
            {onOpenRow ? (
              <button
                className="btn-ghost px-2.5 py-1.5 text-xs"
                onClick={() => onOpenRow(plan.id)}
                title="Open the retrospective Record of Work for this scheme"
                data-testid="plan-open-row"
              >
                → Record of Work
              </button>
            ) : null}
            <a className="btn-ghost px-2.5 py-1.5 text-xs" href={api.planPdfUrl(plan.id)} target="_blank" rel="noreferrer" data-testid="plan-pdf">
              Export PDF
            </a>
            {onExportTermPack ? (
              <button className="btn-primary px-2.5 py-1.5 text-xs" onClick={() => onExportTermPack(plan.id)} data-testid="plan-export-term-pack">
                📦 Export Term Pack
              </button>
            ) : null}
          </div>
        </div>

        <div className="grid gap-3 border-b border-line bg-brand-50/40 px-4 py-3 sm:grid-cols-2 xl:grid-cols-4">
          <label className="min-w-0">
            <span className="section-label">Grade / Subject</span>
            <select
              className="mt-1 w-full rounded-lg border border-line bg-white px-2 py-1.5 text-xs font-semibold text-ink"
              value={`${plan.grade} · ${plan.subject}`}
              onChange={() =>
                onToast("Grade and subject are fixed to this vetted scheme. Create a new scheme to change them.")
              }
              data-testid="scheme-grade-subject"
            >
              <option>{`${plan.grade} · ${plan.subject}`}</option>
            </select>
          </label>
          <label className="min-w-0">
            <span className="section-label">Term / Year</span>
            <div className="mt-1 flex gap-1">
              <input
                className="min-w-0 flex-1 rounded-lg border border-line bg-white px-2 py-1.5 text-xs font-semibold"
                value={h.term}
                onChange={(e) => setPlan({ ...plan, header: { ...h, term: e.target.value } })}
                onBlur={(e) => saveHeader({ term: e.target.value })}
                readOnly={isFinal}
                data-testid="hdr-term"
              />
              <input
                className="w-16 rounded-lg border border-line bg-white px-2 py-1.5 text-xs font-semibold"
                value={h.year}
                onChange={(e) => setPlan({ ...plan, header: { ...h, year: e.target.value } })}
                onBlur={(e) => saveHeader({ year: e.target.value })}
                readOnly={isFinal}
                data-testid="hdr-year"
              />
            </div>
          </label>
          <div className="min-w-0">
            <span className="section-label">School</span>
            <input
              className="mt-1 w-full rounded-lg border border-line bg-white px-2 py-1.5 text-xs"
              value={h.institution}
              onChange={(e) => setPlan({ ...plan, header: { ...h, institution: e.target.value } })}
              onBlur={(e) => saveHeader({ institution: e.target.value })}
              readOnly={isFinal}
              data-testid="hdr-institution"
            />
          </div>
          <div className="min-w-0">
            <span className="section-label">Vetting status</span>
            <p
              className={`mt-1 inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold ${
                allVetted
                  ? "border-brand-300 bg-white text-brand-800"
                  : "border-amber-300 bg-amber-50 text-amber-900"
              }`}
              data-testid="scheme-vetting"
            >
              <span className={`h-1.5 w-1.5 rounded-full ${allVetted ? "bg-brand-600" : "bg-amber-500"}`} />
              {allVetted
                ? `All Chunks Vetted (${vettedCount}/${plan.sections.length})`
                : `Vetting pending (${vettedCount}/${plan.sections.length})`}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-1.5 px-4 py-2.5">
          <Chip active>{`[1 Week = 1 Row]`}</Chip>
          <Chip>{`[${plan.allocation.lessonsPerWeek} Lessons/Week]`}</Chip>
          <Chip>{`[Sequential SLO Split Active]`}</Chip>
          <button
            className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold ${
              filterOpen ? "border-brand-600 bg-brand-600 text-white" : "border-line bg-white text-ink hover:bg-brand-50"
            }`}
            onClick={() => setFilterOpen((v) => !v)}
            data-testid="scheme-filter-toggle"
          >
            [Filter]
          </button>
          <ChipButton
            onClick={() =>
              onToast("Rows are already one week each. Increase the term length when creating a new scheme to add weeks.")
            }
            testId="scheme-add-week"
          >
            [+ Add Week]
          </ChipButton>
          <ChipButton onClick={() => setPaceOpen((v) => !v)} testId="scheme-rebalance-pace">
            [Re-balance Pace]
          </ChipButton>
          <ChipButton onClick={() => setBulkOpen((v) => !v)} testId="scheme-bulk-resources">
            [Bulk Edit Resources]
          </ChipButton>
          <span className="ml-auto flex flex-wrap items-center gap-1.5">
            <button
              className="rounded-full border border-line bg-white px-2.5 py-1 text-[11px] font-semibold text-ink hover:bg-brand-50"
              onClick={() => run(() => api.undoPlan(planId), "Undid the last edit")}
              disabled={busy}
              data-testid="plan-undo"
            >
              ↩ Undo Last Edit
            </button>
            <button className="rounded-full border border-line bg-white px-2.5 py-1 text-[11px] font-semibold text-ink hover:bg-brand-50" onClick={duplicate} disabled={busy} data-testid="plan-duplicate">
              Duplicate Term
            </button>
          </span>
        </div>

        {filterOpen ? (
          <div className="border-t border-line bg-white px-4 py-2">
            <input
              autoFocus
              className="input w-full text-xs"
              placeholder="Filter rows by week, strand, sub-strand, SLO, experience, KIQ, resource or assessment…"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              data-testid="scheme-filter"
            />
            <p className="mt-1 text-[10px] text-muted">
              Showing {filteredSections.length} of {plan.sections.length} rows. Filtering is screen-only; Export PDF
              prints the full term.
            </p>
          </div>
        ) : null}
      </section>

      {validation.length ? (
        <div className="rounded-lg border border-rose-300 bg-rose-50 px-3 py-2 text-xs text-rose-800" data-testid="validation-errors">
          {validation.map((msg, i) => (
            <p key={i}>{msg}</p>
          ))}
        </div>
      ) : null}

      {plan.allocation.warning ? (
        <p className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900" data-testid="allocation-warning">
          {plan.allocation.warning}
        </p>
      ) : null}

      <section className="card overflow-hidden p-0" data-testid="scheme-table-card">
        <div className="overflow-x-auto">
          <table className="scheme-table w-full min-w-[1500px] border-collapse text-[12px]" data-testid="scheme-table">
            <colgroup>
              {COLUMNS.map((col) => (
                <col key={col.key} style={{ width: col.width, minWidth: MIN_WIDTHS[col.key] }} />
              ))}
            </colgroup>
            <thead>
              <tr>
                {COLUMNS.map((col) => (
                  <th
                    key={col.key}
                    className="scheme-th"
                    style={{ width: col.width, minWidth: MIN_WIDTHS[col.key] }}
                    data-testid={`th-${col.key}`}
                  >
                    {col.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredSections.map((s) => (
                <SchemeRow
                  key={s.id}
                  section={s}
                  subject={plan.subject}
                  editKey={editKey}
                  readOnly={isFinal}
                  created={lessonsBySection.get(s.id) ?? []}
                  notesCreated={notesBySection.get(s.id) ?? []}
                  onStartEdit={(field) => setEditKey({ sectionId: s.id, field })}
                  onCancel={() => setEditKey(null)}
                  onSave={(field, value) => saveCell(s.id, field, value)}
                  onViewSource={onViewSource}
                  onResetAppendix={(field) => run(() => api.resetAppendix(plan.id, s.id, field), "Restored from Appendix")}
                  onResetSource={() => resetRow(s)}
                  onCreateLessons={() => openPicker(s)}
                  onOpenLesson={onOpenLesson}
                  onOpenNotes={onOpenNotes}
                  onCreateNotes={() => openNotesPicker(s)}
                  onExtend={(n) => extendRow(s, n)}
                  onInspect={() => setInspector(s)}
                />
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-center gap-2 border-t border-line px-4 py-2 text-[10px] text-muted" data-testid="scheme-footer">
          <span>
            Screen pagination only · showing {filteredSections.length} of {plan.sections.length} rows · Export PDF
            prints all {plan.allocation.totalWeeks} weeks.
          </span>
          <span className="ml-auto">
            Sources: {plan.sources.length ? plan.sources.join(" | ") : "—"}
          </span>
        </div>
      </section>

      {bulkOpen || paceOpen ? (
        <section className="card space-y-2" data-testid="bulk-bar">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-[13px] font-bold text-ink">Bulk edits &amp; pace</h3>
            <span className="text-[11px] text-muted">
              Resources apply to every week of one sub-strand. Pace changes keep one row per week.
            </span>
            <button
              className="ml-auto text-[11px] font-semibold text-brand-700 underline"
              onClick={() => {
                setBulkOpen(false);
                setPaceOpen(false);
              }}
            >
              Close
            </button>
          </div>
          <div className="space-y-2">
            {groups.map((g) => (
              <div key={g.code} className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-white p-2 text-[11px]">
                <span className="min-w-[12rem] text-ink">
                  <span className="font-mono text-muted">{g.code} </span>
                  <span className="font-semibold">{g.name}</span>
                  <span className="text-muted">
                    {" "}
                    · {g.weeks.length} week{g.weeks.length === 1 ? "" : "s"}
                    {g.edited ? ` · ${g.edited} edited` : ""}
                  </span>
                </span>
                {bulkOpen ? (
                  <>
                    <input
                      className="min-w-[11rem] flex-1 rounded-lg border border-line px-2 py-1 text-[11px]"
                      placeholder="Resources for every week in this sub-strand"
                      value={bulkDraft[g.code] ?? ""}
                      onChange={(e) => setBulkDraft({ ...bulkDraft, [g.code]: e.target.value })}
                      data-testid={`bulk-resources-input-${g.code}`}
                    />
                    <button
                      className="rounded-lg border border-line bg-white px-2 py-1 font-semibold text-ink hover:bg-brand-50"
                      onClick={() => bulkResources(g.code, g.name, bulkDraft[g.code] ?? "")}
                      data-testid={`bulk-resources-${g.code}`}
                    >
                      Edit Resources for All Weeks
                    </button>
                  </>
                ) : null}
                {paceOpen ? (
                  <>
                    <label className="flex items-center gap-1 rounded-lg border border-line bg-white px-2 py-1">
                      <span className="text-muted">Lessons/wk</span>
                      <input
                        type="number"
                        min={1}
                        max={40}
                        className="w-12 rounded border border-line px-1 text-[11px]"
                        value={pace[g.code] ?? plan.allocation.lessonsPerWeek}
                        onChange={(e) => setPace({ ...pace, [g.code]: Math.max(1, Number(e.target.value) || 1) })}
                        data-testid={`paces-${g.code}`}
                      />
                    </label>
                    <button
                      className="rounded-lg border border-line bg-white px-2 py-1 font-semibold text-ink hover:bg-brand-50 disabled:opacity-50"
                      disabled={rebalancing !== null || isFinal}
                      onClick={() => rebalance(g.code)}
                      data-testid={`rebalance-${g.code}`}
                    >
                      {rebalancing === g.code ? "Re-balancing…" : "[Re-balance Outcomes]"}
                    </button>
                  </>
                ) : null}
              </div>
            ))}
          </div>
          <button
            className="rounded-lg border border-rose-300 bg-white px-2 py-1 text-[11px] font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-50"
            onClick={clearReflections}
            disabled={isFinal}
            data-testid="clear-reflections"
          >
            Clear All Reflections
          </button>
        </section>
      ) : null}

      <details
        className="card p-0"
        open={notesListOpen}
        onToggle={(e) => setNotesListOpen((e.target as HTMLDetailsElement).open)}
        data-testid="notes-list"
      >
        <summary className="flex cursor-pointer flex-wrap items-center gap-2 px-4 py-3 text-[13px] font-bold text-ink">
          Lesson Notes
          <Badge tone="blue">
            {notes.count} document{notes.count === 1 ? "" : "s"}
          </Badge>
          <span className="text-[11px] font-normal text-muted">
            One document per lesson · every paragraph, word, example and question is editable
          </span>
        </summary>
        <div className="space-y-2 border-t border-line px-4 py-3">
          {notes.count === 0 ? (
            <p className="text-xs text-muted">
              No notes yet. Use “Lesson Notes” on a scheme row, or open a Lesson Plan and press “Generate Notes for
              This Lesson”.
            </p>
          ) : (
            notes.schemes.map((scheme) => (
              <div key={scheme.planId} className="rounded-lg border border-line p-2" data-testid="notes-list-scheme">
                <p className="text-[11px] font-semibold text-ink">
                  {scheme.planTitle} · {scheme.grade} · {scheme.subject} · {scheme.term}
                </p>
                <div className="mt-1.5 space-y-1.5">
                  {scheme.weeks.map((week) => (
                    <div key={week.week} data-testid={`notes-list-week-${week.week}`}>
                      <p className="section-label">Week {week.week}</p>
                      <ul className="mt-0.5 space-y-0.5">
                        {week.lessons.map((n) => (
                          <li key={n.id} className="flex flex-wrap items-center gap-2 text-xs">
                            <span className="font-mono text-muted">L{n.lesson}</span>
                            <button
                              className="text-left text-ink hover:underline"
                              onClick={() => onOpenNotes(n.id)}
                              data-testid={`notes-list-note-${n.lesson}`}
                            >
                              {n.title}
                            </button>
                            <Badge tone={n.status === "Final" ? "green" : "amber"}>{n.status}</Badge>
                            {n.aiEnriched ? <Badge tone="blue">AI</Badge> : null}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      </details>

      {inspector ? (
        <div
          className="fixed inset-0 z-40 flex justify-end bg-slate-900/30"
          onClick={() => setInspector(null)}
          data-testid="inspector-backdrop"
        >
          <aside
            className="h-full w-full max-w-[420px] overflow-y-auto bg-white shadow-drawer"
            onClick={(e) => e.stopPropagation()}
            data-testid="inspector-drawer"
          >
            <div className="sticky top-0 z-10 flex items-center gap-2 border-b border-line bg-white px-4 py-3">
              <div className="min-w-0 flex-1">
                <h3 className="text-[15px] font-bold text-ink">Inspector</h3>
                <p className="truncate text-[10px] text-muted">
                  Week {inspector.week ?? "—"} · {lessonRange(inspector)} · {inspector.subStrandCode}{" "}
                  {inspector.subStrand}
                </p>
              </div>
              <button
                className="rounded-lg border border-line px-2 py-1 text-xs font-semibold text-muted hover:bg-slate-50"
                onClick={() => setInspector(null)}
                data-testid="inspector-close"
              >
                ✕
              </button>
            </div>

            <div className="space-y-4 p-4">
              <section>
                <h4 className="section-label">Traceability Inspector</h4>
                <div className="mt-2 rounded-lg border border-line bg-slate-50 p-2.5">
                  <p className="text-[11px] font-semibold text-ink">Source quote</p>
                  <p className="mt-1 whitespace-pre-wrap text-[11px] leading-relaxed text-slate-700">
                    {inspector.outcomes[0] || inspector.experiences[0] || "—"}
                  </p>
                  <div className="mt-2 grid grid-cols-2 gap-2 text-[10px]">
                    <div>
                      <span className="field-label">Page</span>
                      <p className="font-semibold text-ink">p.{inspector.citations[0]?.pageNumber ?? "?"}</p>
                    </div>
                    <div>
                      <span className="field-label">Byte offset</span>
                      <p className="font-semibold text-ink">— (page-anchored)</p>
                    </div>
                    <div className="col-span-2">
                      <span className="field-label">Source chunk</span>
                      <p className="break-all font-mono text-[9px] text-muted">
                        {inspector.citations[0]?.chunkId ?? "—"}
                      </p>
                    </div>
                  </div>
                  {inspector.citations[0]?.documentId ? (
                    <a
                      className="mt-2 inline-flex rounded-lg border border-brand-300 bg-white px-2 py-1 text-[10px] font-semibold text-brand-800 hover:bg-brand-50"
                      href={`${api.pdfUrl(inspector.citations[0].documentId as string)}#page=${inspector.citations[0]?.pageNumber ?? 1}`}
                      target="_blank"
                      rel="noreferrer"
                      data-testid="inspector-view-pdf"
                    >
                      [View PDF Source Page]
                    </a>
                  ) : null}
                </div>
              </section>

              <section>
                <h4 className="section-label">Lesson Plan Generator</h4>
                <p className="mt-1 text-[11px] text-muted">
                  Week {inspector.week ?? "—"} becomes {selectedLessonCount} independent lesson plans.
                </p>
                <ul className="mt-2 space-y-1">
                  {(inspector.decomposition?.assignments ?? []).slice(0, selectedLessonCount).map((a) => (
                    <li key={a.lesson} className="flex items-center gap-2 rounded-lg border border-line px-2 py-1.5 text-[11px]">
                      <span className="font-mono text-muted">L{a.lesson}</span>
                      <span className="min-w-0 flex-1 truncate text-ink">{a.focus}</span>
                      <span className="text-[9px] uppercase tracking-wide text-muted">{a.kind}</span>
                    </li>
                  ))}
                  {!inspector.decomposition?.assignments?.length
                    ? Array.from({ length: selectedLessonCount }, (_, i) => (
                        <li key={i} className="flex items-center gap-2 rounded-lg border border-line px-2 py-1.5 text-[11px]">
                          <span className="font-mono text-muted">L{i + 1}</span>
                          <span className="min-w-0 flex-1 truncate text-ink">
                            {i + 1 === selectedLessonCount ? "Review" : `Lesson ${i + 1} focus`}
                          </span>
                        </li>
                      ))
                    : null}
                </ul>
                <button
                  className="btn-primary mt-2 w-full px-2 py-1.5 text-xs"
                  onClick={() => openPicker(inspector)}
                  disabled={!inspector.sourceVetted}
                  data-testid="inspector-create-lessons"
                >
                  [Create Lesson Plans ({selectedLessonCount})]
                </button>
                {inspectorLessons.length ? (
                  <button
                    className="btn-ghost mt-1 w-full px-2 py-1.5 text-xs"
                    onClick={() => inspectorLessons[0] && onOpenLesson(inspectorLessons[0].id)}
                  >
                    Open Lesson {inspectorLessons[0]?.lesson}
                  </button>
                ) : null}
              </section>

              <section>
                <div className="flex items-center justify-between gap-2">
                  <h4 className="section-label">AI Draft Enrichment</h4>
                  <label className="flex items-center gap-1.5 text-[10px] font-semibold text-muted">
                    <input
                      type="checkbox"
                      checked={aiOptIn}
                      onChange={(e) => setAiOptIn(e.target.checked)}
                      data-testid="inspector-ai-opt-in"
                    />
                    Opt in
                  </label>
                </div>
                {aiOptIn ? (
                  <div className="mt-2 rounded-lg border border-amber-300 bg-ai p-2.5">
                    <AIDraftLabel />
                    <p className="mt-1 text-[11px] leading-relaxed text-amber-950">
                      AI drafting is optional and review-only. Open any generated Lesson Plan to draft the
                      teacher-owned fields with Gemini; nothing is written into this vetted scheme automatically.
                    </p>
                    {inspectorLessons[0] ? (
                      <button
                        className="mt-2 rounded-lg border border-amber-400 bg-white px-2 py-1 text-[10px] font-semibold text-amber-900 hover:bg-amber-50"
                        onClick={() => onOpenLesson(inspectorLessons[0].id)}
                      >
                        Open Lesson {inspectorLessons[0].lesson} to draft
                      </button>
                    ) : (
                      <button
                        className="mt-2 rounded-lg border border-amber-400 bg-white px-2 py-1 text-[10px] font-semibold text-amber-900 hover:bg-amber-50"
                        onClick={() => openPicker(inspector)}
                      >
                        Create lesson plans first
                      </button>
                    )}
                  </div>
                ) : (
                  <p className="mt-1 text-[11px] text-muted">
                    Off by default. Turn it on only when you want Gemini suggestions to review.
                  </p>
                )}
              </section>

              <section className="rounded-lg border border-line p-2.5">
                <h4 className="section-label">Row checks</h4>
                <ul className="mt-1.5 space-y-1 text-[11px] text-slate-700">
                  <li>✓ Lesson range: {lessonRange(inspector)}</li>
                  <li>✓ SLO heading: By the end of the sub-strand</li>
                  <li>✓ Sub-strand: {inspector.subStrandCode} {inspector.subStrand}</li>
                  <li>✓ Citation: {citationText(inspector, plan.subject)}</li>
                  <li>✓ Source: {inspector.sourceVetted ? "Vetted" : "Pending"}</li>
                </ul>
              </section>
            </div>
          </aside>
        </div>
      ) : null}

      {commentOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
          <div className="w-full max-w-md rounded-card bg-white p-5 shadow-xl" data-testid="save-version-dialog">
            <h3 className="text-[15px] font-bold text-ink">Save Version</h3>
            <p className="mt-1 text-xs text-muted">
              A comment is required. The whole plan is snapshotted; old versions are never overwritten.
            </p>
            <textarea
              autoFocus
              className="mt-3 h-24 w-full rounded-lg border border-line p-2 text-sm"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="e.g. Fixed Week 3 outcomes"
              data-testid="save-version-comment"
            />
            {commentError ? (
              <p className="mt-1 text-xs text-rose-700" data-testid="save-version-error">
                {commentError}
              </p>
            ) : null}
            <div className="mt-3 flex justify-end gap-2">
              <button
                className="btn-ghost"
                onClick={() => {
                  setCommentOpen(false);
                  setCommentError(null);
                }}
              >
                Cancel
              </button>
              <button className="btn-primary" onClick={saveVersion} disabled={busy} data-testid="save-version-confirm">
                Save Version
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {historyOpen ? (
        <div className="fixed inset-0 z-40 flex justify-end bg-slate-900/40" onClick={() => setHistoryOpen(false)}>
          <aside
            className="h-full w-full max-w-lg overflow-y-auto bg-white p-4 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
            data-testid="version-history"
          >
            <div className="flex items-center justify-between">
              <h3 className="text-[15px] font-bold text-ink">Version history</h3>
              <button className="text-muted hover:text-ink" onClick={() => setHistoryOpen(false)}>
                ✕
              </button>
            </div>
            <p className="mt-1 text-xs text-muted">
              Append-only: restoring creates a new version. {versions.length} saved.
            </p>
            <ul className="mt-3 space-y-2">
              {versions.map((v) => (
                <li key={v.id} className="rounded-lg border border-line p-2 text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-ink">{v.label}</span>
                    <span className="text-muted">{v.createdAt}</span>
                    <span className="ml-auto flex gap-2">
                      <button className="underline text-brand-700" onClick={() => openDiff(v.id)} data-testid={`version-diff-${v.versionNumber}`}>
                        Diff
                      </button>
                      {!isFinal ? (
                        <button className="underline text-amber-700" onClick={() => restoreVersion(v)} data-testid={`version-restore-${v.versionNumber}`}>
                          Restore
                        </button>
                      ) : null}
                    </span>
                  </div>
                  <p className="mt-0.5 text-slate-600">{v.comment}</p>
                </li>
              ))}
            </ul>
            {diff ? (
              <div className="mt-4 rounded-lg border border-line p-2" data-testid="version-diff">
                <p className="text-xs font-semibold text-ink">
                  {diff.from} → {diff.to}
                </p>
                <p className="text-[11px] text-muted">
                  {diff.summary.changed} changed · {diff.summary.added} added · {diff.summary.removed} removed
                </p>
                <ul className="mt-2 space-y-1">
                  {diff.cells.map((c, i) => (
                    <li key={i} className="rounded bg-slate-50 p-1.5 text-[10px]">
                      <span className="font-semibold text-slate-700">
                        {c.week != null ? `Week ${c.week} · ` : ""}
                        {c.label}
                      </span>
                      <div className="text-rose-700">− {c.from || "(empty)"}</div>
                      <div className="text-brand-700">+ {c.to || "(empty)"}</div>
                    </li>
                  ))}
                  {!diff.cells.length ? <li className="text-[11px] text-muted">No changes.</li> : null}
                </ul>
              </div>
            ) : null}
          </aside>
        </div>
      ) : null}

      {picker ? (
        <LessonPickerModal
          picker={picker}
          onClose={() => setPicker(null)}
          onCreated={async (count) => {
            await refreshLessons();
            const fresh = await api.lessonPicker(planId, picker.sectionId);
            setPicker(fresh);
            onToast(`${count} lesson plan${count === 1 ? "" : "s"} created`);
          }}
          onError={fail}
        />
      ) : null}

      {notesPicker ? (
        <NotesPickerModal
          picker={notesPicker}
          onClose={() => setNotesPicker(null)}
          onCreated={async (count, firstNoteId) => {
            setNotesPicker(null);
            await refreshNotes();
            onToast(`${count} lesson note${count === 1 ? "" : "s"} generated from Vetted source`);
            if (firstNoteId) onOpenNotes(firstNoteId);
          }}
          onOpenNote={(noteId) => {
            setNotesPicker(null);
            onOpenNotes(noteId);
          }}
          onError={fail}
        />
      ) : null}

      {confirm ? (
        <ConfirmDialog
          title={confirm.title}
          body={confirm.body}
          confirmLabel="Continue"
          danger={false}
          onConfirm={confirm.action}
          onCancel={() => setConfirm(null)}
        />
      ) : null}
    </div>
  );
}

function Chip({ children, active = false }: { children: React.ReactNode; active?: boolean }) {
  return (
    <span
      className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold ${
        active ? "border-brand-600 bg-brand-50 text-brand-800" : "border-line bg-white text-ink"
      }`}
    >
      {children}
    </span>
  );
}

function ChipButton({
  children,
  onClick,
  testId,
}: {
  children: React.ReactNode;
  onClick: () => void;
  testId?: string;
}) {
  return (
    <button
      className="rounded-full border border-line bg-white px-2.5 py-1 text-[11px] font-semibold text-ink hover:bg-brand-50"
      onClick={onClick}
      data-testid={testId}
    >
      {children}
    </button>
  );
}

function SchemeRow({
  section,
  subject,
  editKey,
  readOnly,
  created,
  notesCreated,
  onStartEdit,
  onCancel,
  onSave,
  onViewSource,
  onResetAppendix,
  onResetSource,
  onCreateLessons,
  onOpenLesson,
  onOpenNotes,
  onCreateNotes,
  onExtend,
  onInspect,
}: {
  section: PlanSection;
  subject: string;
  editKey: { sectionId: string; field: string } | null;
  readOnly: boolean;
  created: LessonPlanList["plans"];
  notesCreated: LessonNotesList["notes"];
  onStartEdit: (field: string) => void;
  onCancel: () => void;
  onSave: (field: string, value: unknown) => void;
  onViewSource: (documentId: string, chunkId: string) => void;
  onResetAppendix: (field: "resources" | "assessment") => void;
  onResetSource: () => void;
  onCreateLessons: () => void;
  onOpenLesson: (lessonId: string) => void;
  onOpenNotes: (noteId: string) => void;
  onCreateNotes: () => void;
  onExtend: (n: number) => void;
  onInspect: () => void;
}) {
  const sfx = `${section.subStrandCode}-w${section.week ?? section.ord}`;
  const decomp = section.decomposition;
  const warnings = decomp?.warnings ?? [];
  const spill = decomp?.spill ?? [];
  const suggested = spill.length ? (section.weekLessonCount ?? 5) + spill.length : 0;
  const cite = section.citations[0];

  return (
    <>
      <tr className="align-top odd:bg-white even:bg-brand-50/20" data-testid={`plan-row-${sfx}`}>
        {COLUMNS.map((col) => (
          <td
            key={col.key}
            className="border-b border-line px-2 py-2"
            style={{ minWidth: MIN_WIDTHS[col.key] }}
            data-testid={`td-${col.key}-${sfx}`}
          >
            <Cell
              col={col}
              section={section}
              suffix={sfx}
              cite={cite}
              readOnly={readOnly}
              onViewSource={onViewSource}
              onResetAppendix={onResetAppendix}
              editing={editKey?.sectionId === section.id && editKey.field === col.key}
              onStartEdit={() => onStartEdit(col.key)}
              onCancel={onCancel}
              onSave={(v) => onSave(col.key, v)}
            />
          </td>
        ))}
      </tr>
      <tr className="bg-slate-50/80" data-testid={`row-actions-${sfx}`}>
        <td colSpan={COLUMNS.length} className="border-b border-line px-2 py-1.5">
          <div className="flex flex-wrap items-center gap-1.5 text-[10px]">
            {section.sourceVetted ? (
              <span className="badge-approved">✓ Vetted source</span>
            ) : (
              <span className="badge border border-amber-300 bg-amber-50 text-amber-800">Pending source</span>
            )}
            <ProvenanceBadge kind="source" edited={section.edited} />
            {decomp?.preview?.length ? (
              <span className="text-muted" title="Deterministic decomposition of this row's experiences">
                {decomp.preview.join(" · ")}
              </span>
            ) : null}
            {warnings.map((w, i) => (
              <span key={i} className="rounded-full bg-amber-100 px-1.5 py-0.5 font-semibold text-amber-900" data-testid={`decomp-warning-${sfx}`}>
                {w}
              </span>
            ))}
            {suggested ? (
              <button className="rounded-full border border-amber-400 bg-white px-2 py-0.5 font-semibold text-amber-800 hover:bg-amber-50" onClick={() => onExtend(suggested)} data-testid={`extend-${sfx}`}>
                Extend to {suggested} lessons
              </button>
            ) : null}
            <span className="text-muted">{citationText(section, subject)}</span>
            <button className="font-semibold text-brand-700 underline" onClick={onResetSource} data-testid={`reset-source-${sfx}`}>
              [Reset to Source]
            </button>
            <button className="font-semibold text-brand-700 underline" onClick={onInspect} data-testid={`inspect-${sfx}`}>
              [Inspector]
            </button>
            <span className="mx-1 h-3 w-px bg-line" />
            {created.map((lp) => (
              <button
                key={lp.id}
                className="rounded-full bg-brand-50 px-1.5 py-0.5 font-semibold text-brand-800 hover:bg-brand-100"
                onClick={() => onOpenLesson(lp.id)}
                data-testid={`created-lesson-${sfx}-${lp.lesson}`}
              >
                ✓ Lesson {lp.lesson}
                {lp.status === "Final" ? " · Final" : ""}
              </button>
            ))}
            {notesCreated.map((n) => (
              <button
                key={n.id}
                className="rounded-full bg-sky-50 px-1.5 py-0.5 font-semibold text-sky-800 hover:bg-sky-100"
                onClick={() => onOpenNotes(n.id)}
                data-testid={`created-notes-${sfx}-${n.lesson}`}
              >
                📄 Notes {n.lesson}
                {n.status === "Final" ? " · Final" : ""}
                {n.aiEnriched ? " · AI" : ""}
              </button>
            ))}
            <button
              className="rounded-full border border-brand-300 bg-white px-2 py-0.5 font-semibold text-brand-800 hover:bg-brand-50 disabled:opacity-50"
              onClick={onCreateLessons}
              disabled={!section.sourceVetted || readOnly}
              title={section.sourceVetted ? `Create independent lesson plans for Week ${section.week}` : "Cannot create lesson plan - source not Vetted"}
              data-testid={`create-lessons-${sfx}`}
            >
              Create Lesson Plans
            </button>
            <button
              className="rounded-full border border-sky-300 bg-white px-2 py-0.5 font-semibold text-sky-800 hover:bg-sky-50 disabled:opacity-50"
              onClick={onCreateNotes}
              disabled={!section.sourceVetted}
              title={section.sourceVetted ? `Lesson Notes for Week ${section.week} - one document per lesson` : "Cannot generate notes - source not Vetted"}
              data-testid={`create-notes-${sfx}`}
            >
              → Lesson Notes ({section.weekLessonCount ?? 5})
            </button>
          </div>
        </td>
      </tr>
    </>
  );
}

function Cell({
  col,
  section,
  suffix,
  cite,
  readOnly,
  onViewSource,
  onResetAppendix,
  editing,
  onStartEdit,
  onCancel,
  onSave,
}: {
  col: SchemeColumn;
  section: PlanSection;
  suffix: string;
  cite: PlanSection["citations"][number] | undefined;
  readOnly: boolean;
  onViewSource: (documentId: string, chunkId: string) => void;
  onResetAppendix: (field: "resources" | "assessment") => void;
  editing: boolean;
  onStartEdit: () => void;
  onCancel: () => void;
  onSave: (v: unknown) => void;
}) {
  if (col.key === "week")
    return (
      <button
        className="font-mono text-[11px] font-semibold text-ink hover:bg-amber-50 disabled:hover:bg-transparent"
        onClick={onStartEdit}
        disabled={readOnly}
        data-testid={`cell-week-${suffix}`}
      >
        Week {section.week ?? "—"}
      </button>
    );

  if (col.key === "lesson")
    return (
      <button
        className="font-mono text-[11px] font-semibold text-ink hover:bg-amber-50 disabled:hover:bg-transparent"
        onClick={onStartEdit}
        disabled={readOnly}
        data-testid={`cell-lesson-${suffix}`}
      >
        {lessonRange(section)}
      </button>
    );

  if (col.key === "strand" || col.key === "subStrand")
    return (
      <span>
        {col.key === "strand" ? (
          <span className="block text-[11px] font-medium text-slate-700">{section.strand ?? "—"}</span>
        ) : null}
        <span className="font-mono text-[10px] text-muted">{section.subStrandCode} </span>
        <span className="text-[11px] font-semibold text-ink">{section.subStrand}</span>
        {section.partLabel && section.weekCount && section.weekCount > 1 ? (
          <span className="mt-0.5 block text-[9px] font-normal text-muted" data-testid={`part-${suffix}`}>
            {section.partLabel}
          </span>
        ) : null}
        {cite ? (
          <button
            className="mt-0.5 block text-[9px] font-semibold text-brand-700 hover:underline"
            onClick={() => cite.documentId && onViewSource(cite.documentId, cite.chunkId)}
            title="Open this row's source chunk in the Library"
            data-testid={`citation-${suffix}`}
          >
            {section.citations[0] ? `p.${cite.pageNumber ?? "?"}` : "Source"}
          </button>
        ) : null}
      </span>
    );

  if (col.key === "outcomes" || col.key === "experiences" || col.key === "kiqs") {
    const field = col.key as "outcomes" | "experiences" | "kiqs";
    if (editing)
      return (
        <InlineEditor
          initial={section[field].join("\n")}
          onCancel={onCancel}
          onSave={(v) => onSave(v.split("\n").map((s) => s.trim()).filter(Boolean))}
          testId={`cell-${field}-${suffix}`}
        />
      );
    return (
      <button
        className="block w-full text-left hover:bg-amber-50 disabled:hover:bg-transparent"
        onClick={onStartEdit}
        disabled={readOnly}
        title={`${section.partLabel ?? ""} - click to edit only this week's ${field}`}
        data-testid={`cell-${field}-${suffix}`}
      >
        <ExpandableList
          items={section[field]}
          threshold={4}
          testId={`${field}-list-${suffix}`}
          className="text-[11px] leading-relaxed text-slate-700"
        />
      </button>
    );
  }

  if (col.key === "resources" || col.key === "assessment") {
    const field: "resources" | "assessment" = col.key === "resources" ? "resources" : "assessment";
    const cell = section[field];
    const appendixValue = section.appendix?.[field];
    const appendixSource = section.appendix?.source ?? null;
    if (editing)
      return (
        <InlineEditor
          initial={cell.placeholder ? "" : cell.text}
          placeholder={col.fallback}
          onCancel={onCancel}
          onSave={onSave}
          testId={`cell-${col.key}-${suffix}`}
        />
      );
    return (
      <div>
        <button
          className={`block w-full text-left text-[11px] leading-relaxed ${cell.placeholder ? "italic text-slate-400" : "text-slate-700"} hover:bg-amber-50 disabled:hover:bg-transparent`}
          onClick={onStartEdit}
          disabled={readOnly}
          title={
            cell.fromAppendix && appendixSource
              ? `From ${appendixSource}`
              : cell.fromSource
                ? "From the sub-strand table - click to edit"
                : "Not in source - teacher to fill"
          }
          data-testid={`cell-${col.key}-${suffix}`}
          data-placeholder={cell.placeholder ? "yes" : "no"}
          data-from-appendix={cell.fromAppendix ? "yes" : "no"}
        >
          <ExpandableText text={cell.text} threshold={140} />
        </button>
        {cell.fromAppendix ? (
          <span
            className="mt-0.5 inline-block rounded-full bg-slate-100 px-1.5 py-[1px] text-[8px] font-semibold uppercase tracking-wide text-slate-500"
            title={appendixSource ?? "From the appendix"}
            data-testid={`appendix-pill-${suffix}`}
          >
            {col.key === "resources" ? "Appendix p." + appendixPage(appendixSource) : "Appendix"}
          </span>
        ) : null}
        {appendixValue && !cell.fromAppendix ? (
          <button
            className="mt-0.5 block text-[9px] font-semibold text-brand-700 hover:underline"
            onClick={() => onResetAppendix(field)}
            title={`Restore the appendix value: ${appendixValue}`}
            data-testid={`reset-appendix-${col.key}-${suffix}`}
          >
            ↩ Reset to Appendix
          </button>
        ) : null}
      </div>
    );
  }

  if (col.key === "reflection") {
    if (editing)
      return (
        <InlineEditor
          initial={section.reflection.text}
          placeholder={section.reflection.placeholder}
          onCancel={onCancel}
          onSave={onSave}
          testId={`cell-reflection-${suffix}`}
        />
      );
    return (
      <button
        className={`block w-full text-left text-[11px] ${section.reflection.text ? "text-slate-700" : "italic text-slate-400"} hover:bg-amber-50 disabled:hover:bg-transparent`}
        onClick={onStartEdit}
        disabled={readOnly}
        data-testid={`cell-reflection-${suffix}`}
        data-empty={section.reflection.text ? "no" : "yes"}
      >
        {section.reflection.text || section.reflection.placeholder}
      </button>
    );
  }

  return null;
}

/** "Appendix 1, p.29, Sub-Strand WHOLE NUMBERS" -> "29" (for the compact pill). */
function appendixPage(source: string | null | undefined): string {
  if (!source) return "";
  const m = source.match(/p\.\s*(\d+)/i);
  return m ? m[1] : "";
}

function InlineEditor({
  initial,
  placeholder,
  onCancel,
  onSave,
  testId,
}: {
  initial: string;
  placeholder?: string;
  onCancel: () => void;
  onSave: (v: string) => void;
  testId?: string;
}) {
  const [draft, setDraft] = useState(initial);
  return (
    <div>
      <textarea
        autoFocus
        className="h-20 w-full rounded-lg border border-brand-300 px-1.5 py-1 text-[11px]"
        value={draft}
        placeholder={placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") onCancel();
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            onSave(draft);
          }
        }}
        data-testid={testId ? `${testId}-input` : undefined}
      />
      <div className="mt-1 flex gap-1">
        <button className="rounded-md bg-brand-600 px-1.5 py-0.5 text-[10px] font-semibold text-white" onClick={() => onSave(draft)} data-testid="cell-save">
          Save
        </button>
        <button className="rounded-md border px-1.5 py-0.5 text-[10px]" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

function LessonPickerModal({
  picker,
  onClose,
  onCreated,
  onError,
}: {
  picker: LessonPicker;
  onClose: () => void;
  onCreated: (count: number) => void;
  onError: (e: unknown) => void;
}) {
  const missing = picker.lessons.filter((l) => !l.created);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [date, setDate] = useState("");
  const durationOptions = picker.durationOptions?.length ? picker.durationOptions : [35];
  const [duration, setDuration] = useState(picker.defaultDuration || durationOptions[0]);
  const [durationType, setDurationType] = useState<"Single" | "Double">("Single");
  const [time, setTime] = useState("");
  const [classSize, setClassSize] = useState("");
  const [busy, setBusy] = useState(false);

  const toggle = (lesson: number) => {
    const next = new Set(selected);
    if (next.has(lesson)) next.delete(lesson);
    else next.add(lesson);
    setSelected(next);
  };

  const selectAll = () => setSelected(new Set(picker.lessons.map((l) => l.lesson)));
  const chooseMissing = () => setSelected(new Set(missing.map((l) => l.lesson)));

  const create = async () => {
    const chosen = [...selected].sort((a, b) => a - b);
    if (!chosen.length) return;
    setBusy(true);
    try {
      const dates: Record<string, string> = {};
      if (date) dates[String(chosen[0])] = date;
      const res = await api.createLessonPlans({
        schemeRowId: picker.sectionId,
        lessons: chosen,
        dates,
        duration,
        durationType: picker.gradeBand === "jss" ? durationType : undefined,
        templateVersion: picker.templateVersion,
        time,
        classSize: classSize === "" ? null : Number(classSize),
      });
      onCreated(res.count);
    } catch (e) {
      onError(e);
    } finally {
      setBusy(false);
    }
  };

  const blocked = !picker.sourceVetted;
  const chosenMissing = [...selected].filter((n) => missing.some((m) => m.lesson === n)).length;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-card bg-white p-5 shadow-xl" data-testid="lesson-picker">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="text-[15px] font-bold text-ink">Lesson plans · Week {picker.week} · Lesson {picker.lessonRange}</h3>
            <p className="text-xs text-muted">
              {picker.subStrandCode} {picker.subStrand} · one week = independent lesson plans
            </p>
          </div>
          <button className="text-muted hover:text-ink" onClick={onClose}>
            ✕
          </button>
        </div>

        {blocked ? (
          <p className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-800" data-testid="lesson-picker-blocked">
            {picker.vettingMessage || "Cannot create lesson plan - source not Vetted"}
          </p>
        ) : null}

        <div className="mt-3 grid gap-2 text-xs sm:grid-cols-4">
          <label className="flex flex-col gap-1">
            <span className="field-label">Date for Lesson 1</span>
            <input type="date" className="rounded-lg border border-line px-1.5 py-1" value={date} onChange={(e) => setDate(e.target.value)} data-testid="picker-date" />
          </label>
          {picker.gradeBand === "jss" ? (
            <>
              <label className="flex flex-col gap-1">
                <span className="field-label">Lesson Length</span>
                <select
                  className="rounded-lg border border-line px-1.5 py-1"
                  value={durationType}
                  onChange={(e) => {
                    const next = e.target.value as "Single" | "Double";
                    setDurationType(next);
                    setDuration(next === "Double" ? 80 : 40);
                  }}
                  data-testid="picker-duration-type"
                >
                  <option value="Single">Single (40 min)</option>
                  <option value="Double">Double (80 min)</option>
                </select>
              </label>
              <label className="flex flex-col gap-1">
                <span className="field-label">Duration (min)</span>
                <select className="rounded-lg border border-line px-1.5 py-1" value={duration} onChange={(e) => setDuration(Number(e.target.value))} data-testid="picker-duration">
                  {durationOptions.map((n) => (
                    <option key={n} value={n}>
                      {n} min
                    </option>
                  ))}
                </select>
              </label>
            </>
          ) : (
            <label className="flex flex-col gap-1">
              <span className="field-label">Duration (min)</span>
              <input
                type="number"
                min={1}
                max={240}
                className="rounded-lg border border-line px-1.5 py-1"
                value={duration}
                onChange={(e) => setDuration(Math.max(1, Number(e.target.value) || 35))}
                data-testid="picker-duration"
              />
            </label>
          )}
          <label className="flex flex-col gap-1">
            <span className="field-label">Time</span>
            <input className="rounded-lg border border-line px-1.5 py-1" value={time} onChange={(e) => setTime(e.target.value)} placeholder="08:00" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="field-label">Class Size</span>
            <input type="number" min={1} className="rounded-lg border border-line px-1.5 py-1" value={classSize} onChange={(e) => setClassSize(e.target.value)} placeholder="Optional" />
          </label>
        </div>

        <div className="mt-3 flex items-center gap-2 text-xs">
          <button className="btn-ghost px-2 py-1" onClick={selectAll} data-testid="picker-select-all">
            Select All
          </button>
          <button className="btn-ghost px-2 py-1" onClick={chooseMissing} data-testid="picker-select-missing">
            Select Missing Only
          </button>
          <span className="text-muted">
            {picker.createdCount} of {picker.lessonCount} already created
          </span>
        </div>

        <ul className="mt-2 divide-y divide-line rounded-lg border border-line">
          {picker.lessons.map((l) => (
            <li key={l.lesson} className="flex items-center gap-2 px-3 py-1.5 text-xs">
              <input type="checkbox" checked={selected.has(l.lesson)} disabled={l.created || blocked} onChange={() => toggle(l.lesson)} data-testid={`picker-check-${l.lesson}`} />
              <span className="font-mono text-muted">L{l.lesson}</span>
              <span className="flex-1 text-ink">{l.focus}</span>
              {l.created ? (
                <Badge tone="green" data-testid={`picker-created-${l.lesson}`}>
                  ✓ Created
                </Badge>
              ) : (
                <span className="text-[10px] uppercase tracking-wide text-muted">Not created</span>
              )}
            </li>
          ))}
        </ul>

        <div className="mt-4 flex items-center justify-end gap-2">
          <span className="mr-auto text-[11px] text-muted">
            {selected.size} selected · {chosenMissing} missing to create
          </span>
          <button className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn-primary" onClick={create} disabled={busy || blocked || chosenMissing === 0} data-testid="picker-create">
            {picker.createdCount > 0 ? "Create Missing Only" : "Create Selected"}
          </button>
        </div>
      </div>
    </div>
  );
}
