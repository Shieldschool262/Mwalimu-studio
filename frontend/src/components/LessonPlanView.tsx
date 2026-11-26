import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type {
  AssessTarget,
  LessonAssessmentData,
  LessonDiff,
  LessonPicker,
  LessonPlan,
  LessonPlanSection,
  LessonStepData,
  PlanVersion,
  WebExample,
} from "../types";
import { buildSloDomains } from "../lib/slo";
import { AIDraftLabel, Badge, ConfirmDialog, ProvenanceBadge, Tabs } from "./ui";

interface Props {
  lessonId: string;
  onToast: (msg: string) => void;
  onError: (msg: string) => void;
  onViewSource: (documentId: string, chunkId: string) => void;
  onOpenNotes: (noteId: string) => void;
  onOpenLesson: (lessonId: string) => void;
  onMarkTaught?: (schemeId: string, week: number, lesson: number) => void;
  onAssess?: (target: AssessTarget) => void;
  onCrumb?: (parts: string[]) => void;
  onBack: () => void;
}

const STEP_KEYS = ["introduction", "step1", "step2", "step3", "conclusion"];

/** Stage names only - the template must never add "1.", "Step 1", etc. */
function stageHeading(key: string, section: LessonPlanSection, all: LessonPlanSection[], total: number) {
  const timeFor = (k: string) => {
    const s = all.find((x) => x.key === k);
    return String(s?.data?.time ?? "").trim();
  };
  const intro = timeFor("introduction") || "5 min";
  const conclusion = timeFor("conclusion") || "5 min";
  let minutes = timeFor(key);
  if (key === "step1" && !minutes) {
    const left = Number(total) - parseInt(intro, 10) - parseInt(conclusion, 10);
    minutes = left > 0 ? `${left} min` : "25 min";
  }
  if (key === "step2" || key === "step3") return "";
  const label = key === "introduction" ? "Introduction"
    : key === "step1" ? "Development"
    : key === "conclusion" ? "Conclusion"
    : section.title.replace(/^\d+\.\s*/, "");
  return minutes ? `${label} (${minutes})` : label;
}

function focusOnly(focus: string): string {
  const clean = focus.replace(/\s+only\s*$/i, "").trim();
  return `${clean} only`;
}

function tabLabel(lesson: number, total: number, focus: string): string {
  if (lesson === total) return "Review";
  if (lesson === total - 1) return "Consolidation";
  const after = focus.includes(":") ? focus.split(":").slice(1).join(":").trim() : focus;
  const cleaned = after
    .replace(/^sort objects by\s+/i, "")
    .replace(/\bonly\b/gi, "")
    .trim();
  const first = cleaned.split(/[,/]/)[0].split(/\s+/)[0] || `Lesson ${lesson}`;
  return first.charAt(0).toUpperCase() + first.slice(1);
}

export default function LessonPlanView({
  lessonId,
  onToast,
  onError,
  onViewSource,
  onOpenNotes,
  onOpenLesson,
  onMarkTaught,
  onAssess,
  onCrumb,
  onBack,
}: Props) {
  const [plan, setPlan] = useState<LessonPlan | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [aiBusy, setAiBusy] = useState(false);
  const [notesBusy, setNotesBusy] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [aiNotice, setAiNotice] = useState<string | null>(null);
  const [lessonPicker, setLessonPicker] = useState<LessonPicker | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const [commentOpen, setCommentOpen] = useState(false);
  const [comment, setComment] = useState("");
  const [commentError, setCommentError] = useState<string | null>(null);

  const [historyOpen, setHistoryOpen] = useState(false);
  const [versions, setVersions] = useState<PlanVersion[]>([]);
  const [diff, setDiff] = useState<LessonDiff | null>(null);

  const [webOpen, setWebOpen] = useState(false);
  const [webQuery, setWebQuery] = useState("");
  const [webResults, setWebResults] = useState<WebExample[]>([]);
  const [webProvider, setWebProvider] = useState<string>("");
  const [webMessage, setWebMessage] = useState<string>("");
  const [webBusy, setWebBusy] = useState(false);

  const load = () => {
    setLoading(true);
    api
      .lessonPlan(lessonId)
      .then((p) => {
        setPlan(p);
        setWebQuery(`${p.subStrand ?? ""} ${p.header.grade ?? ""} activity`.trim());
        api
          .lessonPicker(p.schemeId, p.sectionId)
          .then(setLessonPicker)
          .catch(() => setLessonPicker(null));
      })
      .catch((e) => onError((e as Error).message))
      .finally(() => setLoading(false));
  };

  useEffect(load, [lessonId]);

  useEffect(() => {
    if (!plan || !onCrumb) return;
    onCrumb([
      `${String(plan.header.grade ?? "")} ${String(
        plan.header.learningArea ?? "",
      )}`.trim(),
      `Week ${plan.week}`,
      `Lesson ${plan.lesson}`,
    ]);
  }, [plan, onCrumb]);

  const fail = (e: unknown) => onError((e as Error).message);

  const saveSection = async (section: LessonPlanSection, patch: Record<string, unknown>) => {
    if (!plan) return;
    setBusy(true);
    try {
      setPlan(await api.editLessonSection(plan.id, section.id, patch));
      setEditId(null);
      onToast("Saved");
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const resetSection = async (section: LessonPlanSection) => {
    if (!plan) return;
    setBusy(true);
    try {
      setPlan(await api.resetLessonSection(plan.id, section.id));
      onToast(`${section.title} reset`);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const resetAll = async () => {
    if (!plan) return;
    setConfirmReset(false);
    setBusy(true);
    try {
      let next: LessonPlan = plan;
      for (const section of plan.sections) {
        next = await api.resetLessonSection(plan.id, section.id);
      }
      setPlan(next);
      onToast("All fields reset to source");
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const saveHeader = async (patch: Record<string, unknown>) => {
    if (!plan) return;
    setBusy(true);
    try {
      setPlan(await api.editLessonHeader(plan.id, patch));
      onToast("Updated");
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const resetHeader = async (field: string) => {
    if (!plan) return;
    setBusy(true);
    try {
      setPlan(await api.resetLessonHeader(plan.id, field));
      onToast("Reset to source");
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const fixSlo = async () => {
    if (!plan) return;
    setBusy(true);
    try {
      setPlan(await api.fixLessonSlo(plan.id));
      onToast("Specific Learning Outcome fixed to 'By the end of the lesson'");
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const runAi = async () => {
    if (!plan) return;
    if (!plan.ai.available) {
      onError("AI enrichment needs GEMINI_API_KEY");
      return;
    }
    setAiBusy(true);
    setAiNotice(null);
    try {
      const next = await api.aiDraft(plan.id);
      setPlan(next);
      const drafts = next.sections.filter((s) => s.aiDraft).length;
      setAiNotice(
        drafts
          ? `${drafts} AI draft${drafts === 1 ? "" : "s"} ready - review each field, then Accept, Edit or Reject. AI never changed Outcomes, KIQ or Resources.`
          : "AI returned no drafts.",
      );
      onToast("AI drafts ready for review");
    } catch (e) {
      fail(e);
    } finally {
      setAiBusy(false);
    }
  };

  const saveVersion = async () => {
    if (!plan) return;
    if (!comment.trim()) {
      setCommentError("A comment is required, e.g. 'Added group work to Step 2'.");
      return;
    }
    setBusy(true);
    try {
      const res = await api.createLessonVersion(plan.id, comment.trim());
      setPlan(res.lessonPlan);
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

  const openHistory = async () => {
    if (!plan) return;
    setHistoryOpen(true);
    setDiff(null);
    try {
      setVersions((await api.lessonVersions(plan.id)).versions);
    } catch (e) {
      fail(e);
    }
  };

  const openDiff = async (versionId: string) => {
    if (!plan) return;
    try {
      setDiff(await api.lessonVersionDiff(plan.id, versionId));
    } catch (e) {
      fail(e);
    }
  };

  const restore = async (version: PlanVersion) => {
    if (!plan) return;
    setBusy(true);
    try {
      const next = await api.restoreLessonVersion(plan.id, version.id);
      setPlan(next);
      onToast(`Restored - saved as ${next.restoredVersion?.label ?? "a new version"}`);
      setHistoryOpen(false);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const setStatus = async (status: "Draft" | "Final") => {
    if (!plan) return;
    setBusy(true);
    try {
      setPlan(await api.lessonStatus(plan.id, status));
      onToast(status === "Final" ? "Lesson plan marked Final" : "Reopened as Draft");
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!plan) return;
    setBusy(true);
    try {
      const res = await api.deleteLessonPlan(plan.id);
      setConfirmDelete(false);
      onToast("Lesson plan deleted");
      if (res.deleted) onBack();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const generateNotes = async () => {
    if (!plan) return;
    setNotesBusy(true);
    try {
      let noteId: string | undefined;
      try {
        const res = await api.createLessonNotes({ lessonPlanId: plan.id });
        noteId = res.created[0]?.id;
        onToast("Lesson notes generated from the Vetted source");
      } catch (e) {
        // One notes document per lesson - reopen the existing one instead of duplicating.
        const list = await api.lessonNotes({ sectionId: plan.sectionId });
        const existing = list.notes.find((n) => n.lesson === plan.lesson);
        if (!existing) throw e;
        noteId = existing.id;
        onToast(`Opening the existing notes for Lesson ${plan.lesson}`);
      }
      if (noteId) onOpenNotes(noteId);
    } catch (e) {
      fail(e);
    } finally {
      setNotesBusy(false);
    }
  };

  const searchWeb = async () => {
    if (!plan) return;
    setWebBusy(true);
    try {
      const res = await api.webExamples(plan.id, webQuery);
      setWebResults(res.results);
      setWebProvider(res.provider || "");
      setWebMessage(res.message || "");
    } catch (e) {
      fail(e);
    } finally {
      setWebBusy(false);
    }
  };

  const openWeb = (query?: string) => {
    if (query) setWebQuery(query);
    setWebOpen(true);
  };

  const insertExample = async (ex: WebExample) => {
    if (!plan) return;
    const target = plan.sections.find((s) => s.key === "extended");
    if (!target) return;
    let host = ex.source;
    if (!host) {
      try {
        host = new URL(ex.url).hostname;
      } catch {
        host = "web";
      }
    }
    const label = `[Web Example - ${host}] ${ex.title}: ${ex.url}`;
    const body = [target.body, label].filter(Boolean).join("\n");
    await saveSection(target, { body, provenance: "web" });
    setWebOpen(false);
    onToast("Web example inserted into Extended Activities");
  };

  const sections = useMemo(() => plan?.sections ?? [], [plan]);
  const outcomes = sections.find((s) => s.key === "outcomes");
  const kiq = sections.find((s) => s.key === "kiq");
  const draftSection = sections.find((s) => Boolean(s.aiDraft));

  if (loading) return <p className="card p-6 text-center text-sm text-muted">Loading lesson plan…</p>;
  if (!plan) return <p className="card p-6 text-center text-sm text-muted">Lesson plan not found.</p>;

  const h = plan.header;
  const source = plan.source;
  const isFinal = plan.status === "Final";
  const isJss = plan.gradeBand === "jss";
  const sloItems = buildSloDomains(outcomes?.body ?? "", plan.focus, source.outcomes ?? []);
  const savedLabel = plan.versions[plan.versions.length - 1]?.label ?? "v1.0";
  const lessonTotal = lessonPicker?.lessonCount ?? plan.lessonCount ?? 5;
  const lessonTabs =
    lessonPicker?.lessons?.length
      ? lessonPicker.lessons
      : Array.from({ length: lessonTotal }, (_, i) => ({
          lesson: i + 1,
          focus: i + 1 === plan.lesson ? plan.focus : `Lesson ${i + 1}`,
          kind: i + 1 === lessonTotal ? "assessment" : i + 1 === lessonTotal - 1 ? "consolidation" : "atomic",
          created: i + 1 === plan.lesson,
          lessonPlanId: i + 1 === plan.lesson ? plan.id : null,
          status: i + 1 === plan.lesson ? plan.status : null,
          date: "",
        }));
  const anchorQuote =
    outcomes?.sourceQuote || source.experiences?.[0] || plan.sourceExperience || plan.focus;
  const pageMatch = String(source.sourceLabel ?? "").match(/p\.\s*(\d+)/i);
  const sourcePage = pageMatch ? pageMatch[1] : "—";

  return (
    <div className="space-y-4" data-testid="lesson-plan-view">
      {/* Row 1: navigation + primary actions */}
      <section className="card flex flex-wrap items-center gap-2 py-2.5">
        <button className="btn-ghost px-2 py-1 text-xs" onClick={onBack} data-testid="lesson-back">
          ← Back to Scheme
        </button>
        <span className="min-w-0 flex-1 truncate text-[11px] text-muted">
          {String(plan.header.grade ?? "")} {String(plan.header.learningArea ?? "")} › Week{" "}
          {plan.week} › Lesson {plan.lesson}
        </span>
        <Badge tone={isFinal ? "green" : "amber"} data-testid="lesson-status">
          {isFinal ? "Final" : "Draft"}
        </Badge>
        <button
          className="btn-primary px-2.5 py-1.5 text-xs"
          onClick={() => {
            setCommentError(null);
            setCommentOpen(true);
          }}
          disabled={busy}
          data-testid="lesson-save-version"
        >
          Save Version
        </button>
        {isFinal ? (
          <button className="btn-ghost px-2.5 py-1.5 text-xs" onClick={() => setStatus("Draft")} disabled={busy}>
            Reopen as Draft
          </button>
        ) : (
          <button className="btn-ghost px-2.5 py-1.5 text-xs" onClick={() => setStatus("Final")} disabled={busy} data-testid="lesson-final">
            Mark Final
          </button>
        )}
        <button
          className="btn-ghost px-2.5 py-1.5 text-xs text-rose-600 hover:text-rose-800"
          onClick={() => setConfirmDelete(true)}
          disabled={busy}
          data-testid="lesson-delete"
        >
          Delete
        </button>
      </section>

      {/* Row 2: template + version tools */}
      <section className="card flex flex-wrap items-center gap-2 py-2 text-[11px]">
        <Tabs
          value={plan.gradeBand === "jss" ? "jss" : "primary"}
          onChange={(value) => {
            if (value === "jss" && plan.gradeBand !== "jss") saveHeader({ templateVersion: "cbe-lesson-jss-v1" });
            if (value === "primary" && plan.gradeBand !== "primary") saveHeader({ templateVersion: "cbe-lesson-primary-v1" });
          }}
          items={[
            { value: "primary", label: "Primary (PP1-G6, 35m)", testId: "lesson-template-primary" },
            { value: "jss", label: "Junior School (G7-G9, 40m)", testId: "lesson-template-jss" },
          ]}
          ariaLabel="Lesson template"
        />
        <span className="mx-1 hidden h-4 w-px bg-line sm:block" />
        <button
          className="btn-ghost px-2 py-1 text-[11px]"
          onClick={() =>
            onToast("Duplicating a lesson plan: create the next lesson from the scheme row to keep one plan per lesson.")
          }
          data-testid="lesson-duplicate"
        >
          Duplicate
        </button>
        <button className="btn-ghost px-2 py-1 text-[11px]" onClick={() => setConfirmReset(true)} disabled={busy} data-testid="lesson-reset-all">
          Reset to Source
        </button>
        <button className="text-[11px] font-semibold text-brand-700 underline" onClick={openHistory} data-testid="lesson-history">
          Version history ({plan.versions.length})
        </button>
        <span className="ml-auto rounded-full border border-brand-200 bg-brand-50 px-2 py-1 font-semibold text-brand-800" data-testid="lesson-saved-label">
          Saved {savedLabel}
        </span>
        <button
          className="btn-ghost px-2 py-1 text-[11px]"
          onClick={runAi}
          disabled={aiBusy || !plan.ai.available}
          title={plan.ai.available ? "Draft the teacher-owned fields with Gemini" : "AI enrichment needs GEMINI_API_KEY"}
          data-testid="lesson-ai"
        >
          {aiBusy ? "Drafting…" : "✨ Draft with AI"}
        </button>
        <button className="btn-ghost px-2 py-1 text-[11px]" onClick={() => openWeb()} data-testid="lesson-web">
          Web Examples
        </button>
        <button
          className="btn-ghost px-2 py-1 text-[11px]"
          onClick={generateNotes}
          disabled={notesBusy || busy}
          title="Create learner-facing Lesson Notes for this lesson from the Vetted source"
          data-testid="lesson-generate-notes"
        >
          {notesBusy ? "Generating…" : "→ Notes for This Lesson"}
        </button>
        {onAssess ? (
          <button
            className="btn-ghost px-2 py-1 text-[11px]"
            onClick={() => onAssess({
              schemeRowId: plan.sectionId, week: plan.week, lesson: plan.lesson,
              grade: String(plan.header.grade || ""), learningArea: String(plan.header.learningArea || ""),
            })}
            title="Record a rubric level for every learner in this lesson"
            data-testid="lesson-assess"
          >
            📊 Assess This Lesson
          </button>
        ) : null}
        {onMarkTaught ? (
          <button
            className="btn-ghost px-2 py-1 text-[11px]"
            onClick={() => onMarkTaught(plan.schemeId, plan.week, plan.lesson)}
            title="Record what was actually taught: sets Status=Taught and opens the Record of Work"
            data-testid="lesson-mark-taught"
          >
            → Mark as Taught
          </button>
        ) : null}
        <a className="btn-ghost px-2 py-1 text-[11px]" href={api.lessonPdfUrl(plan.id)} target="_blank" rel="noreferrer" data-testid="lesson-pdf">
          Export PDF
        </a>
      </section>

      {!plan.ai.available ? (
        <p className="rounded-lg border border-line bg-white px-3 py-2 text-xs text-muted" data-testid="ai-disabled">
          {plan.ai.message}
        </p>
      ) : null}

      {aiNotice ? (
        <p className="rounded-lg border border-amber-300 bg-ai px-3 py-2 text-xs text-amber-950" data-testid="ai-notice">
          {aiNotice}
        </p>
      ) : null}

      {plan.sloWarning ? (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-400 bg-amber-50 px-3 py-2 text-xs text-amber-950" data-testid="slo-warning">
          <span>{plan.sloWarning}</span>
          <button className="rounded-lg bg-amber-600 px-2 py-0.5 text-[11px] font-semibold text-white" onClick={fixSlo} disabled={busy} data-testid="slo-fix">
            Fix Automatically
          </button>
        </div>
      ) : null}

      {/* Official header */}
      <section className="card text-center">
        <p className="text-[10px] font-bold uppercase tracking-[0.22em] text-muted">
          Republic of Kenya • Ministry of Education • KICD
        </p>
        <h1 className="mt-1 text-[18px] font-extrabold tracking-wide text-ink" data-testid="lesson-title">
          Competency Based Curriculum Lesson Plan
        </h1>
        <p className="mt-0.5 text-[11px] font-semibold text-brand-800">
          Official 11-Part Primary Framework · Standard {plan.duration}-Minute Period
        </p>
      </section>

      {/* Lesson tabs */}
      <section className="card p-2" data-testid="lesson-tabs">
        <div className="flex flex-wrap gap-1">
          {lessonTabs.map((tab) => {
            const active = tab.lesson === plan.lesson;
            return (
              <button
                key={tab.lesson}
                className={`min-w-[98px] rounded-lg px-3 py-2 text-left text-[11px] font-semibold transition-colors ${
                  active ? "bg-brand-600 text-white shadow-sm" : "bg-white text-ink hover:bg-brand-50"
                }`}
                onClick={() => {
                  if (tab.lessonPlanId && tab.lessonPlanId !== plan.id) onOpenLesson(tab.lessonPlanId);
                  else if (tab.lesson !== plan.lesson)
                    onToast("Create this lesson plan from the scheme row first.");
                }}
                data-testid={`lesson-tab-${tab.lesson}`}
              >
                <span className={`block font-mono text-[9px] ${active ? "text-brand-100" : "text-muted"}`}>
                  Lesson {tab.lesson}
                </span>
                <span className="block truncate">
                  {tabLabel(tab.lesson, lessonTotal, tab.focus)}
                </span>
              </button>
            );
          })}
        </div>
      </section>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 space-y-4">
          {/* Part 1 - Administrative details: a real bordered table, not a list. */}
          <PartCard part="1" title="Administrative Details">
            <table className="lp-admin-grid w-full border-collapse text-[11pt]" data-testid="lesson-admin-grid">
              <tbody>
                <tr>
                  <th scope="row">School</th>
                  <td>
                    <HeaderLine label="" value={String(h.school ?? "")} blankValue="________" disabled={isFinal}
                      onSave={(v) => saveHeader({ school: v })} onReset={() => resetHeader("school")}
                      testId="lesson-header-school" />
                  </td>
                  <th scope="row">Learning Area</th>
                  <td>
                    <HeaderLine label="" value={String(h.learningArea ?? "")} blankValue="________" disabled={isFinal}
                      onSave={(v) => saveHeader({ learningArea: v })} onReset={() => resetHeader("learningArea")}
                      testId="lesson-header-learningArea" />
                  </td>
                </tr>
                <tr>
                  <th scope="row">Grade</th>
                  <td><span data-testid="lesson-header-grade">{String(h.grade ?? "________")}</span></td>
                  <th scope="row">Term</th>
                  <td>
                    <HeaderLine label="" value={String(h.term ?? "")} blankValue="________" disabled={isFinal}
                      onSave={(v) => saveHeader({ term: v })} onReset={() => resetHeader("term")}
                      testId="lesson-header-term" />
                  </td>
                </tr>
                <tr>
                  <th scope="row">Year</th>
                  <td>
                    <HeaderLine label="" value={String(h.year ?? "")} blankValue="________" disabled={isFinal}
                      onSave={(v) => saveHeader({ year: v })} onReset={() => resetHeader("year")}
                      testId="lesson-header-year" />
                  </td>
                  <th scope="row">Week</th>
                  <td><span data-testid="lesson-header-week">{String(h.week ?? plan.week ?? "________")}</span></td>
                </tr>
                <tr>
                  <th scope="row">Lesson</th>
                  <td><span data-testid="lesson-header-lesson">Lesson {h.lesson ?? plan.lesson} of {plan.lessonCount ?? 5}</span></td>
                  <th scope="row">Date</th>
                  <td>
                    <HeaderLine label="" value={String(h.date ?? "")} blankValue="________" disabled={isFinal}
                      onSave={(v) => saveHeader({ date: v })} onReset={() => resetHeader("date")}
                      testId="lesson-header-date" />
                  </td>
                </tr>
                <tr>
                  <th scope="row">Time</th>
                  <td>
                    <HeaderLine label="" value={String(h.time ?? "")} blankValue="________" disabled={isFinal}
                      onSave={(v) => saveHeader({ time: v })} onReset={() => resetHeader("time")}
                      testId="lesson-header-time" />
                  </td>
                  <th scope="row">Duration</th>
                  <td><span data-testid="lesson-duration">{plan.duration} min</span></td>
                </tr>
                <tr>
                  <th scope="row">Strand</th>
                  <td><span data-testid="lesson-strand-admin">{String(h.strand ?? "________")}</span></td>
                  <th scope="row">Sub-Strand</th>
                  <td><span data-testid="lesson-substrand-admin">{String(h.subStrand ?? "________")}</span></td>
                </tr>
                <tr>
                  <th scope="row" colSpan={4}>Focus</th>
                </tr>
                <tr>
                  <td colSpan={4} className="font-semibold text-ink" data-testid="lesson-admin-focus">
                    {String(h.focus ?? plan.focus ?? "________")}
                  </td>
                </tr>
                <tr>
                  <th scope="row">Teacher</th>
                  <td>
                    <HeaderLine label="" value={String(h.teacherName ?? "")} blankValue="________" disabled={isFinal}
                      onSave={(v) => saveHeader({ teacherName: v })} onReset={() => resetHeader("teacherName")}
                      testId="lesson-header-teacherName" />
                  </td>
                  <th scope="row">TSC No.</th>
                  <td>
                    <HeaderLine label="" value={String(h.tscNo ?? "")} blankValue="________" disabled={isFinal}
                      onSave={(v) => saveHeader({ tscNo: v })} onReset={() => resetHeader("tscNo")}
                      testId="lesson-header-tscNo" />
                  </td>
                </tr>
                <tr>
                  <th scope="row">Class Size</th>
                  <td>{h.classSize ?? "________"}</td>
                  <th scope="row">Roll B / G / T</th>
                  <td>{[h.rollBoys, h.rollGirls, h.rollTotal].map((v) => v || "________").join(" / ")}</td>
                </tr>
              </tbody>
            </table>
            <p className="mt-2 text-[10px] text-muted">
              {isJss
                ? "Subject-specific: experiment, project, investigation, lab/workshop task."
                : "Activity-based: song, play, manipulatives, pair work."}
            </p>
          </PartCard>

          {/* Part 2 - Strand */}
          <PartCard
            part="2"
            title="Strand"
            badge={<ProvenanceBadge kind="source" edited={plan.headerEditedFields.includes("strand")} />}
            onReset={() => resetHeader("strand")}
            resetTestId="reset-strand"
          >
            <p className="text-[15px] font-semibold text-ink" data-testid="lesson-strand">
              {String(h.strand ?? plan.strand ?? "—")}
            </p>
          </PartCard>

          {/* Part 3 - Sub-strand */}
          <PartCard
            part="3"
            title="Sub-Strand"
            badge={<ProvenanceBadge kind="source" edited={plan.headerEditedFields.includes("subStrand")} />}
            onReset={() => resetHeader("subStrand")}
            resetTestId="reset-substrand"
          >
            <p className="text-[15px] font-semibold text-ink" data-testid="lesson-substrand">
              {plan.subStrandCode ? `${plan.subStrandCode} ` : ""}
              {String(h.subStrand ?? plan.subStrand ?? "—")}
            </p>
            <p className="mt-1 rounded-lg bg-brand-50 px-2 py-1 text-[11px] font-semibold text-brand-900">
              Focus: {focusOnly(plan.focus)}
            </p>
          </PartCard>

          {/* Part 4 - SLO, 3-domain list */}
          <PartCard
            part="4"
            title="Specific Learning Outcomes"
            badge={
              <ProvenanceBadge
                kind={outcomes?.provenance === "source" ? "source" : "derived"}
                edited={outcomes?.editedFromSource}
              />
            }
            onReset={outcomes ? () => resetSection(outcomes) : undefined}
            resetTestId="reset-outcomes"
            testId="lesson-part-outcomes"
          >
            <p className="text-[11px] font-semibold text-muted">By the end of the lesson, the learner should be able to:</p>
            <ul className="mt-2 space-y-2" data-testid="lesson-slo-list">
              {sloItems.map((item) => (
                <li key={item.domain} className="min-w-0 rounded-lg border border-line bg-white p-2.5">
                  <span className="badge border border-brand-200 bg-brand-50 text-brand-800">
                    {item.domain}
                  </span>
                  <p className="mt-1 break-words text-[12px] leading-relaxed text-slate-700">
                    {item.text}
                  </p>
                </li>
              ))}
            </ul>
            {outcomes ? (
              <SectionEditor
                section={outcomes}
                editing={editId === outcomes.id}
                busy={busy}
                onStartEdit={() => setEditId(outcomes.id)}
                onCancel={() => setEditId(null)}
                onSave={(patch) => saveSection(outcomes, patch)}
                onAcceptAi={() => saveSection(outcomes, { acceptAi: true })}
                onRejectAi={() => saveSection(outcomes, { rejectAi: true })}
                compact
              />
            ) : null}
          </PartCard>

          {/* Part 5 - KIQ */}
          <PartCard
            part="5"
            title="Key Inquiry Question(s)"
            badge={
              <ProvenanceBadge
                kind={kiq?.provenance === "source" ? "source" : "derived"}
                edited={kiq?.editedFromSource}
              />
            }
            onReset={kiq ? () => resetSection(kiq) : undefined}
            resetTestId="reset-kiq"
            testId="lesson-part-kiq"
          >
            <blockquote className="border-l-4 border-brand-300 bg-brand-50/50 px-3 py-2 text-[12px] italic text-slate-700">
              {kiq?.body?.trim() || "—"}
            </blockquote>
            <p className="mt-1 text-[10px] text-muted">
              Distributed 1/week from source p.{sourcePage}
            </p>
            {kiq ? (
              <SectionEditor
                section={kiq}
                editing={editId === kiq.id}
                busy={busy}
                onStartEdit={() => setEditId(kiq.id)}
                onCancel={() => setEditId(null)}
                onSave={(patch) => saveSection(kiq, patch)}
                onAcceptAi={() => saveSection(kiq, { acceptAi: true })}
                onRejectAi={() => saveSection(kiq, { rejectAi: true })}
                compact
              />
            ) : null}
          </PartCard>

          {/* Parts 6-9 */}
          {(
            [
              { part: "6", key: "competencies" },
              { part: "7", key: "values" },
              { part: "8", key: "pcis" },
              { part: "9", key: "resources" },
            ] as const
          ).map((group) => {
            const section = sections.find((s) => s.key === group.key);
            if (!section) return null;
            return (
              <PartCard
                key={group.key}
                part={group.part}
                title={section.title.replace(/^\d+\.\s*/, "")}
                badge={<ProvenanceBadge kind={section.provenance === "source" ? "source" : "derived"} edited={section.editedFromSource} />}
                onReset={() => resetSection(section)}
                resetTestId={`reset-${group.key}`}
              >
                <SectionEditor
                  section={section}
                  editing={editId === section.id}
                  busy={busy}
                  onStartEdit={() => setEditId(section.id)}
                  onCancel={() => setEditId(null)}
                  onSave={(patch) => saveSection(section, patch)}
                  onAcceptAi={() => saveSection(section, { acceptAi: true })}
                  onRejectAi={() => saveSection(section, { rejectAi: true })}
                />
              </PartCard>
            );
          })}

          {/* Part 10 - Lesson development */}
          <PartCard part="10" title="Lesson Development">
            <div className="space-y-2">
              {STEP_KEYS.map((key) => {
                const section = sections.find((s) => s.key === key);
                if (!section) return null;
                return (
                  <div key={key} className="rounded-lg border border-line p-2">
                    <SectionEditor
                      section={section}
                      displayTitle={stageHeading(key, section, sections, plan.duration)}
                      editing={editId === section.id}
                      busy={busy}
                      onStartEdit={() => setEditId(section.id)}
                      onCancel={() => setEditId(null)}
                      onSave={(patch) => saveSection(section, patch)}
                      onAcceptAi={() => saveSection(section, { acceptAi: true })}
                      onRejectAi={() => saveSection(section, { rejectAi: true })}
                    />
                  </div>
                );
              })}
            </div>
          </PartCard>

          {/* Part 11 - Extended, Assessment, Reflection */}
          <PartCard part="11" title="Extended Activities, Assessment & Reflection">
            <div className="space-y-2">
              {["extended", "assessment", "reflection"].map((key) => {
                const section = sections.find((s) => s.key === key);
                if (!section) return null;
                return (
                  <div key={key} className="rounded-lg border border-line p-2">
                    <SectionEditor
                      section={section}
                      editing={editId === section.id}
                      busy={busy}
                      onStartEdit={() => setEditId(section.id)}
                      onCancel={() => setEditId(null)}
                      onSave={(patch) => saveSection(section, patch)}
                      onAcceptAi={() => saveSection(section, { acceptAi: true })}
                      onRejectAi={() => saveSection(section, { rejectAi: true })}
                    />
                  </div>
                );
              })}
            </div>
          </PartCard>
        </div>

        {/* AI assistant - hard max 320px */}
        <aside className="min-w-0 space-y-3 xl:sticky xl:top-[104px] xl:h-fit xl:w-[320px] xl:max-w-[320px]" data-testid="lesson-assistant-panel">
          <div className="card p-3">
            <div className="flex items-center justify-between gap-2">
              <h3 className="text-[13px] font-bold text-ink">AI Assistant</h3>
              <Badge tone={plan.ai.available ? "green" : "slate"}>
                {plan.ai.available ? "Ready" : "Offline"}
              </Badge>
            </div>
            <p className="mt-1 text-[10px] text-muted">
              AI is opt-in and review-only. Nothing changes until you accept a draft.
            </p>
          </div>

          <div className="card space-y-2 p-3">
            <p className="section-label">Current Anchor Chunk</p>
            <p className="rounded-lg bg-slate-50 p-2 text-[11px] leading-relaxed text-slate-700">
              {anchorQuote}
            </p>
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge tone="green">100% Match</Badge>
              <button
                className="text-[10px] font-semibold text-brand-700 underline"
                onClick={() => plan.documentId && plan.chunkId && onViewSource(plan.documentId, plan.chunkId)}
                data-testid="compare-source"
              >
                [Compare with Source]
              </button>
            </div>
            <p className="text-[10px] text-muted">
              {plan.subStrandCode} {plan.subStrand} · source p.{sourcePage}
            </p>
          </div>

          <div className="card space-y-2 p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="section-label">AI Draft</p>
              {draftSection ? <AIDraftLabel /> : null}
            </div>
            {draftSection ? (
              <div className="rounded-lg border border-amber-300 bg-ai p-2" data-testid="panel-ai-draft">
                <p className="text-[10px] font-semibold text-amber-900">{draftSection.title}</p>
                <p className="mt-1 whitespace-pre-wrap text-[11px] leading-relaxed text-amber-950">
                  {draftSection.aiDraft}
                </p>
                <div className="mt-1 flex gap-1">
                  <button
                    className="rounded-md bg-brand-600 px-2 py-0.5 text-[10px] font-semibold text-white"
                    onClick={() => saveSection(draftSection, { acceptAi: true })}
                    disabled={busy}
                  >
                    Accept
                  </button>
                  <button
                    className="rounded-md border border-amber-400 px-2 py-0.5 text-[10px] font-semibold text-amber-900"
                    onClick={() => setEditId(draftSection.id)}
                    disabled={busy}
                  >
                    Edit
                  </button>
                  <button
                    className="rounded-md border border-rose-300 px-2 py-0.5 text-[10px] font-semibold text-rose-700"
                    onClick={() => saveSection(draftSection, { rejectAi: true })}
                    disabled={busy}
                  >
                    Reject
                  </button>
                </div>
              </div>
            ) : (
              <div className="rounded-lg border border-dashed border-line p-2 text-[11px] text-muted">
                No AI drafts yet. Draft with AI is opt-in.
                <button
                  className="mt-1 block w-full rounded-md border border-brand-300 bg-white px-2 py-1 text-[10px] font-semibold text-brand-800 hover:bg-brand-50 disabled:opacity-50"
                  onClick={runAi}
                  disabled={aiBusy || !plan.ai.available}
                >
                  {aiBusy ? "Drafting…" : "✨ Draft with AI"}
                </button>
              </div>
            )}
          </div>

          <div className="card space-y-1.5 p-3">
            <p className="section-label">Contextual AI Actions</p>
            <button
              className="w-full rounded-lg border border-line bg-white px-2 py-1.5 text-left text-[11px] font-semibold text-ink hover:bg-brand-50"
              onClick={() =>
                openWeb(`low cost rural classroom resources ${plan.subStrand ?? ""} ${plan.focus}`.trim())
              }
            >
              [Suggest Rural Low-Cost Resources]
            </button>
            <button
              className="w-full rounded-lg border border-line bg-white px-2 py-1.5 text-left text-[11px] font-semibold text-ink hover:bg-brand-50"
              onClick={() => openWeb(`${plan.focus} classroom activity Kenya`)}
            >
              [Find Example Activity (Web)]
            </button>
            <button
              className="w-full rounded-lg border border-line bg-white px-2 py-1.5 text-left text-[11px] font-semibold text-ink hover:bg-brand-50"
              onClick={() =>
                onToast("Write the local-language version in a teacher-edited field; translations are never auto-applied.")
              }
            >
              [Translate Rhyme to Swahili / Mother Tongue]
            </button>
          </div>

          <div className="card space-y-1.5 p-3">
            <p className="section-label">Traceability &amp; Moderation</p>
            {[
              ["KICD Sub-strand Lock", "Enforced"],
              ["SLO Verb Check", outcomes?.body ? "Valid Bloom's" : "Needs review"],
              ["Time Allocation", `${plan.duration} min · Accurate`],
              ["Reflection Autocomplete", "Strictly Disabled"],
            ].map(([label, value]) => (
              <div key={label} className="flex items-center justify-between gap-2 text-[11px]">
                <span className="text-muted">{label}</span>
                <span className="font-semibold text-brand-800">✓ {value}</span>
              </div>
            ))}
          </div>

          <details className="card p-3 text-[11px]">
            <summary className="cursor-pointer font-bold text-ink">Full source chunk</summary>
            <div className="mt-2 space-y-2 text-slate-700">
              <div>
                <p className="font-semibold text-ink">{source.sourceLabel ?? "Vetted source"}</p>
                <p className="text-[10px] text-muted">{plan.sourceOutcomesHeading}</p>
                <ul className="mt-0.5 list-disc space-y-0.5 pl-4">
                  {(source.outcomes ?? []).map((x, i) => (
                    <li key={i}>{x}</li>
                  ))}
                </ul>
              </div>
              <SourceList label="Experiences" items={source.experiences ?? []} />
              <SourceList label="Key inquiry questions" items={source.kiqs ?? []} />
              {source.appendixResources ? <SourceText label="Appendix resources" value={source.appendixResources} /> : null}
              <SourceText label="Scheme assessment" value={source.schemeAssessment ?? "—"} />
            </div>
          </details>
        </aside>
      </div>

      {commentOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
          <div className="w-full max-w-md rounded-card bg-white p-5 shadow-xl" data-testid="lesson-save-dialog">
            <h3 className="text-[15px] font-bold text-ink">Save Version</h3>
            <p className="mt-1 text-xs text-muted">A comment is required. Restoring later creates a new version.</p>
            <textarea
              autoFocus
              className="mt-3 h-24 w-full rounded-lg border border-line p-2 text-sm"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="e.g. Added group work to Step 2"
            />
            {commentError ? <p className="mt-1 text-xs text-rose-700">{commentError}</p> : null}
            <div className="mt-3 flex justify-end gap-2">
              <button className="btn-ghost" onClick={() => setCommentOpen(false)}>
                Cancel
              </button>
              <button className="btn-primary" onClick={saveVersion} disabled={busy}>
                Save Version
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {historyOpen ? (
        <div className="fixed inset-0 z-40 flex justify-end bg-slate-900/40" onClick={() => setHistoryOpen(false)}>
          <aside className="h-full w-full max-w-lg overflow-y-auto bg-white p-4 shadow-2xl" onClick={(e) => e.stopPropagation()} data-testid="lesson-version-history">
            <div className="flex items-center justify-between">
              <h3 className="text-[15px] font-bold text-ink">Lesson version history</h3>
              <button className="text-muted hover:text-ink" onClick={() => setHistoryOpen(false)}>
                ✕
              </button>
            </div>
            <ul className="mt-3 space-y-2">
              {versions.map((v) => (
                <li key={v.id} className="rounded-lg border border-line p-2 text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-ink">{v.label}</span>
                    <span className="text-muted">{v.createdAt}</span>
                    <span className="ml-auto flex gap-2">
                      <button className="underline text-brand-700" onClick={() => openDiff(v.id)}>
                        Diff
                      </button>
                      <button className="underline text-amber-700" onClick={() => restore(v)} disabled={busy}>
                        Restore
                      </button>
                    </span>
                  </div>
                  <p className="mt-0.5 text-slate-600">{v.comment}</p>
                </li>
              ))}
            </ul>
            {diff ? (
              <div className="mt-4 rounded-lg border border-line p-2">
                <p className="text-xs font-semibold text-ink">
                  {diff.from} → {diff.to}
                </p>
                <ul className="mt-2 space-y-1">
                  {diff.cells.map((c, i) => (
                    <li key={i} className="rounded bg-slate-50 p-1.5 text-[10px]">
                      <span className="font-semibold text-slate-700">{c.label}</span>
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

      {webOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
          <div className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-card bg-white p-5 shadow-xl" data-testid="web-modal">
            <div className="flex items-start justify-between">
              <div>
                <h3 className="text-[15px] font-bold text-ink">Web examples</h3>
                <p className="text-xs text-muted">Teacher-initiated only. Top 3 results; nothing is inserted until you choose.</p>
              </div>
              <button className="text-muted hover:text-ink" onClick={() => setWebOpen(false)}>
                ✕
              </button>
            </div>
            <div className="mt-3 flex gap-2">
              <input
                className="flex-1 rounded-lg border border-line px-2 py-1 text-sm"
                value={webQuery}
                onChange={(e) => setWebQuery(e.target.value)}
                placeholder="e.g. sorting objects by colour activity"
                data-testid="web-query"
              />
              <button className="btn-primary" onClick={searchWeb} disabled={webBusy} data-testid="web-search">
                {webBusy ? "Searching…" : "Search"}
              </button>
            </div>
            {webProvider ? (
              <p className="mt-2 text-[11px] text-muted" data-testid="web-provider">
                Searched via {webProvider === "gemini-grounding" ? "Google (Gemini)" : webProvider === "tavily" ? "Tavily" : webProvider} • {webResults.length} result{webResults.length === 1 ? "" : "s"}
              </p>
            ) : null}
            {webMessage ? (
              <p className="mt-1 text-[11px] text-amber-700" data-testid="web-message">{webMessage}</p>
            ) : null}
            <ul className="mt-3 space-y-2">
              {webResults.map((r, i) => (
                <li key={i} className="rounded-lg border border-line p-2 text-xs">
                  <p className="font-semibold text-ink">{r.title}</p>
                  <a className="break-all text-[11px] text-brand-700 underline" href={r.url} target="_blank" rel="noreferrer">
                    {r.url}
                  </a>
                  <p className="mt-1 text-slate-600">{r.snippet}</p>
                  <button
                    className="mt-1 rounded-lg border border-brand-300 px-2 py-0.5 text-[10px] font-semibold text-brand-800 hover:bg-brand-50"
                    onClick={() => insertExample(r)}
                    data-testid={`web-insert-${i}`}
                  >
                    Insert into Extended Activities
                  </button>
                </li>
              ))}
              {!webResults.length ? (
                <li className="text-xs text-muted" data-testid="web-empty">
                  No helpful Kenyan CBC activity found. Add your own example or try a different search.
                  <div className="mt-2 flex gap-2">
                    <button
                      className="rounded-lg border border-line px-2 py-0.5 text-[10px] font-semibold"
                      onClick={() => setWebOpen(false)}
                      data-testid="web-add-own"
                    >
                      Add My Own Example
                    </button>
                    <button
                      className="rounded-lg border border-line px-2 py-0.5 text-[10px] font-semibold"
                      onClick={() => {
                        setWebQuery("");
                      }}
                      data-testid="web-try-different"
                    >
                      Try Different Search
                    </button>
                  </div>
                </li>
              ) : null}
            </ul>
          </div>
        </div>
      ) : null}

      {confirmReset ? (
        <ConfirmDialog
          title="Reset every field to source?"
          body="This clears teacher edits and AI-accepted text from all sections. Versions are never deleted."
          confirmLabel="Reset to Source"
          onConfirm={resetAll}
          onCancel={() => setConfirmReset(false)}
        />
      ) : null}

      {confirmDelete ? (
        <ConfirmDialog
          title="Delete this lesson plan?"
          body={`Week ${plan.week} Lesson ${plan.lesson} - permanently removed. This cannot be undone.`}
          confirmLabel="Delete lesson plan"
          onConfirm={remove}
          onCancel={() => setConfirmDelete(false)}
        />
      ) : null}
    </div>
  );
}

function PartCard({
  part,
  title,
  badge,
  onReset,
  resetTestId,
  children,
  testId,
}: {
  part: string;
  title: string;
  badge?: React.ReactNode;
  onReset?: () => void;
  resetTestId?: string;
  children: React.ReactNode;
  testId?: string;
}) {
  return (
    <section className="card min-w-0" data-testid={testId ?? `lesson-part-${part}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-brand-600 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white">
          Part {part}
        </span>
        <h2 className="min-w-0 flex-1 text-[15px] font-bold text-ink">{title}</h2>
        {badge}
        {onReset ? (
          <button
            className="text-[10px] font-semibold text-brand-700 underline"
            onClick={onReset}
            data-testid={resetTestId}
          >
            [Reset to Source]
          </button>
        ) : null}
      </div>
      <div className="mt-2 min-w-0">{children}</div>
    </section>
  );
}

function SectionEditor({
  section,
  displayTitle,
  editing,
  busy,
  onStartEdit,
  onCancel,
  onSave,
  onAcceptAi,
  onRejectAi,
  compact = false,
}: {
  section: LessonPlanSection;
  displayTitle?: string;
  editing: boolean;
  busy: boolean;
  onStartEdit: () => void;
  onCancel: () => void;
  onSave: (patch: Record<string, unknown>) => void;
  onAcceptAi: () => void;
  onRejectAi: () => void;
  compact?: boolean;
}) {
  const isStep = STEP_KEYS.includes(section.key);
  const isAssessment = section.key === "assessment";
  const [draft, setDraft] = useState(section.aiDraft || section.body);
  const [step, setStep] = useState<LessonStepData>({
    time: String(section.data?.time ?? ""),
    teacherActivity: String(section.data?.teacherActivity ?? ""),
    learnerActivity: String(section.data?.learnerActivity ?? ""),
  });
  const [assessment, setAssessment] = useState<LessonAssessmentData>({
    method: String(section.data?.method ?? ""),
    description: String(section.data?.description ?? ""),
    sampleItems: Array.isArray(section.data?.sampleItems)
      ? section.data.sampleItems
      : String(section.data?.sampleItems ?? "").split("\n").filter(Boolean),
    rubricIndicator: String(section.data?.rubricIndicator ?? ""),
  });

  useEffect(() => {
    setDraft(section.aiDraft || section.body);
    setStep({
      time: String(section.data?.time ?? ""),
      teacherActivity: String(section.data?.teacherActivity ?? ""),
      learnerActivity: String(section.data?.learnerActivity ?? ""),
    });
    setAssessment({
      method: String(section.data?.method ?? ""),
      description: String(section.data?.description ?? ""),
      sampleItems: Array.isArray(section.data?.sampleItems)
        ? section.data.sampleItems
        : String(section.data?.sampleItems ?? "").split("\n").filter(Boolean),
      rubricIndicator: String(section.data?.rubricIndicator ?? ""),
    });
  }, [section, editing]);

  const save = () => {
    if (isStep) onSave({ data: step, body: step.learnerActivity });
    else if (isAssessment) onSave({ data: assessment });
    else onSave({ body: draft });
  };

  return (
    <div className={compact ? "mt-2" : ""} data-testid={`section-${section.key}`}>
      <div className="flex flex-wrap items-center gap-1.5">
        {!compact ? <h4 className="min-w-0 flex-1 text-[12px] font-bold text-ink">{displayTitle ?? section.title.replace(/^\d+\.\s*/, "")}</h4> : null}
        <ProvenanceBadge
          kind={
            section.provenance === "source"
              ? "source"
              : section.provenance === "ai"
                ? "ai"
                : section.provenance === "web"
                  ? "web"
                  : section.provenance === "derived" || section.provenance === "source-derived"
                    ? "derived"
                    : "teacher"
          }
          edited={section.editedFromSource}
        />
        {section.aiAssisted ? <span className="badge-ai">AI-assisted</span> : null}
        {!compact ? (
          <button className="ml-auto text-[10px] font-semibold text-brand-700 underline" onClick={onStartEdit} disabled={busy} data-testid={`section-edit-${section.key}`}>
            Edit
          </button>
        ) : null}
        {!compact ? (
          <button className="text-[10px] font-semibold text-brand-700 underline" onClick={onStartEdit} disabled={busy}>
            [Expand]
          </button>
        ) : null}
      </div>
      {section.hint ? <p className="mt-0.5 text-[10px] text-muted">{section.hint}</p> : null}

      {section.aiDraft ? (
        <div className="mt-2 rounded-lg border border-amber-300 bg-ai p-2" data-testid={`ai-draft-${section.key}`}>
          <AIDraftLabel />
          <p className="mt-1 whitespace-pre-wrap text-[11px] leading-relaxed text-amber-950">{section.aiDraft}</p>
          <div className="mt-1 flex gap-1">
            <button className="rounded-md bg-brand-600 px-2 py-0.5 text-[10px] font-semibold text-white" onClick={onAcceptAi} disabled={busy}>
              Accept
            </button>
            <button className="rounded-md border border-amber-400 px-2 py-0.5 text-[10px] font-semibold text-amber-900" onClick={onStartEdit} disabled={busy}>
              Edit
            </button>
            <button className="rounded-md border border-rose-300 px-2 py-0.5 text-[10px] font-semibold text-rose-700" onClick={onRejectAi} disabled={busy}>
              Reject
            </button>
          </div>
        </div>
      ) : null}

      {editing ? (
        <div className="mt-2 space-y-1.5">
          {isStep ? (
            <>
              <label className="flex items-center gap-2 text-[10px] font-semibold text-muted">
                Time
                <input className="w-24 rounded-lg border border-brand-300 px-1.5 py-0.5 text-xs" value={step.time} onChange={(e) => setStep({ ...step, time: e.target.value })} data-testid={`step-time-${section.key}`} />
              </label>
              <textarea
                autoFocus
                className="h-20 w-full rounded-lg border border-brand-300 p-1.5 text-xs"
                value={step.teacherActivity}
                onChange={(e) => setStep({ ...step, teacherActivity: e.target.value })}
                placeholder="Teacher Activity"
                data-testid={`step-teacher-${section.key}`}
              />
              <textarea
                className="h-20 w-full rounded-lg border border-brand-300 p-1.5 text-xs"
                value={step.learnerActivity}
                onChange={(e) => setStep({ ...step, learnerActivity: e.target.value })}
                placeholder="Learner Activity"
                data-testid={`step-learner-${section.key}`}
              />
            </>
          ) : isAssessment ? (
            <>
              <input className="w-full rounded-lg border border-brand-300 p-1.5 text-xs" value={assessment.method} onChange={(e) => setAssessment({ ...assessment, method: e.target.value })} placeholder="Assessment method" data-testid="assessment-method" />
              <textarea className="h-24 w-full rounded-lg border border-brand-300 p-1.5 text-xs" value={assessment.description} onChange={(e) => setAssessment({ ...assessment, description: e.target.value })} placeholder="Planned Assessment / description" data-testid="assessment-description" />
              <textarea
                className="h-16 w-full rounded-lg border border-brand-300 p-1.5 text-xs"
                value={assessment.sampleItems.join("\n")}
                onChange={(e) => setAssessment({ ...assessment, sampleItems: e.target.value.split("\n").filter((x) => x.trim()) })}
                placeholder="Sample items (one per line)"
                data-testid="assessment-samples"
              />
              <input className="w-full rounded-lg border border-brand-300 p-1.5 text-xs" value={assessment.rubricIndicator} onChange={(e) => setAssessment({ ...assessment, rubricIndicator: e.target.value })} placeholder="Rubric indicator" data-testid="assessment-indicator" />
            </>
          ) : (
            <textarea
              autoFocus
              className="h-24 w-full rounded-lg border border-brand-300 p-1.5 text-xs"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") onCancel();
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  save();
                }
              }}
              data-testid={`section-input-${section.key}`}
            />
          )}
          <div className="flex gap-1">
            <button className="rounded-md bg-brand-600 px-2 py-0.5 text-[10px] font-semibold text-white" onClick={save} disabled={busy} data-testid="section-save">
              Save
            </button>
            <button className="rounded-md border px-2 py-0.5 text-[10px]" onClick={onCancel}>
              Cancel
            </button>
            <span className="text-[10px] text-muted">Enter saves · Esc cancels</span>
          </div>
        </div>
      ) : (
        <button
          className={`mt-1 block w-full min-w-0 whitespace-pre-wrap break-words text-left text-[11px] leading-relaxed ${
            section.body ? "text-slate-700" : "italic text-slate-400"
          } hover:bg-amber-50`}
          onClick={onStartEdit}
          data-testid={`section-body-${section.key}`}
        >
          {isStep
            ? [
                step.time ? `Time: ${step.time}` : "",
                step.teacherActivity ? `Teacher: ${step.teacherActivity}` : "",
                step.learnerActivity ? `Learner: ${step.learnerActivity}` : "",
              ]
                .filter(Boolean)
                .join("  ·  ") || section.placeholder || "—"
            : isAssessment
              ? [
                  assessment.method ? `Method: ${assessment.method}` : "",
                  assessment.description,
                  assessment.sampleItems.length ? `Samples: ${assessment.sampleItems.join("; ")}` : "",
                ]
                  .filter(Boolean)
                  .join("\n") || section.placeholder || "—"
              : section.body || section.placeholder || "—"}
        </button>
      )}
    </div>
  );
}

function HeaderLine({
  label,
  value,
  edited,
  onSave,
  onReset,
  testId,
  blankValue,
  disabled,
}: {
  label: string;
  value: string;
  edited?: boolean;
  onSave?: (v: string) => void;
  onReset?: () => void;
  testId?: string;
  blankValue?: string;
  disabled?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);

  useEffect(() => setDraft(value), [value]);

  const commit = () => {
    setEditing(false);
    if (draft !== value) onSave?.(draft);
  };

  return (
    <div className="flex min-w-0 flex-wrap items-center gap-1.5">
      {label ? <span className="field-label shrink-0">{label}</span> : null}
      {editing ? (
        <input
          autoFocus
          className="min-w-0 flex-1 rounded-lg border border-brand-300 px-1 py-0.5 text-xs"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit();
            if (e.key === "Escape") {
              setDraft(value);
              setEditing(false);
            }
          }}
          data-testid={testId ? `${testId}-input` : undefined}
        />
      ) : (
        <button
          className="min-w-0 flex-1 break-words text-left text-xs text-ink hover:bg-amber-50"
          onClick={() => !disabled && setEditing(true)}
          disabled={disabled}
          data-testid={testId}
        >
          {value || (
            <span className="text-slate-400">{blankValue ?? "—"}</span>
          )}
        </button>
      )}
      {edited ? (
        <span className="flex items-center gap-1">
          <span className="text-[9px] font-bold uppercase text-amber-700">Edited</span>
          <button className="text-[10px] text-brand-700 underline" onClick={onReset} title="Reset to source" data-testid={testId ? `${testId}-reset` : undefined}>
            ↩
          </button>
        </span>
      ) : null}
    </div>
  );
}

function SourceList({ label, items }: { label: string; items: string[] }) {
  return (
    <div>
      <p className="font-semibold text-ink">{label}</p>
      {items.length ? (
        <ul className="mt-0.5 list-disc space-y-0.5 pl-4 text-slate-600">
          {items.map((x, i) => (
            <li key={i}>{x}</li>
          ))}
        </ul>
      ) : (
        <p className="text-slate-400">—</p>
      )}
    </div>
  );
}

function SourceText({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="font-semibold text-ink">{label}</p>
      <p className="whitespace-pre-wrap text-slate-600">{value || "—"}</p>
    </div>
  );
}
