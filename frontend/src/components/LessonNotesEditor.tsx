import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type {
  ExampleItem,
  LessonDiff,
  LessonNote,
  LessonNoteSection,
  PlanVersion,
  PracticeItem,
  VocabularyItem,
  WebExample,
} from "../types";
import { Badge, ConfirmDialog } from "./ui";

interface Props {
  noteId: string;
  onToast: (msg: string) => void;
  onError: (msg: string) => void;
  onViewSource: (documentId: string, chunkId: string) => void;
  onBack: () => void;
}

const AI_REVIEW_LABEL = "AI Draft - Not from source - Review";

function itemsOf(section: LessonNoteSection): unknown[] {
  const value = section.data?.items;
  return Array.isArray(value) ? value : [];
}

function stepsOf(section: LessonNoteSection): string[] {
  const value = section.data?.steps;
  return Array.isArray(value) ? value.map((x) => String(x ?? "")) : [];
}

function vocabularyOf(section: LessonNoteSection): VocabularyItem[] {
  return itemsOf(section).map((raw) => {
    const item = (raw ?? {}) as Record<string, unknown>;
    return {
      word: String(item.word ?? ""),
      definition: String(item.definition ?? ""),
      example: String(item.example ?? ""),
      source: String(item.source ?? "From source"),
    };
  });
}

function examplesOf(section: LessonNoteSection): ExampleItem[] {
  return itemsOf(section).map((raw) => {
    if (typeof raw === "string") return { text: raw };
    const item = (raw ?? {}) as Record<string, unknown>;
    return {
      text: String(item.text ?? ""),
      source: item.source ? String(item.source) : undefined,
      url: item.url ? String(item.url) : undefined,
    };
  });
}

function practiceOf(section: LessonNoteSection): PracticeItem[] {
  return itemsOf(section).map((raw) => {
    const item = (raw ?? {}) as Record<string, unknown>;
    return {
      question: String(item.question ?? ""),
      answer: String(item.answer ?? ""),
    };
  });
}

export default function LessonNotesEditor({
  noteId,
  onToast,
  onError,
  onViewSource,
  onBack,
}: Props) {
  const [note, setNote] = useState<LessonNote | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiNotice, setAiNotice] = useState<string | null>(null);

  const [commentOpen, setCommentOpen] = useState(false);
  const [comment, setComment] = useState("");
  const [commentError, setCommentError] = useState<string | null>(null);

  const [historyOpen, setHistoryOpen] = useState(false);
  const [versions, setVersions] = useState<PlanVersion[]>([]);
  const [diff, setDiff] = useState<LessonDiff | null>(null);
  const [restoreTarget, setRestoreTarget] = useState<PlanVersion | null>(null);

  const [webOpen, setWebOpen] = useState(false);
  const [webQuery, setWebQuery] = useState("");
  const [webResults, setWebResults] = useState<WebExample[]>([]);
  const [webProvider, setWebProvider] = useState<string>("");
  const [webMessage, setWebMessage] = useState<string>("");
  const [webBusy, setWebBusy] = useState(false);

  const [sourceOpen, setSourceOpen] = useState(false);
  const [sourceTitle, setSourceTitle] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [sourceText, setSourceText] = useState("");
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const [includeAnswers, setIncludeAnswers] = useState(false);

  const fail = (e: unknown) => onError((e as Error).message);

  const load = () => {
    setLoading(true);
    api
      .lessonNote(noteId)
      .then((n) => {
        setNote(n);
        setWebQuery(`${n.focus} Grade ${n.grade} activity Kenya`);
      })
      .catch((e) => fail(e))
      .finally(() => setLoading(false));
  };

  useEffect(load, [noteId]);

  const sections = useMemo(() => note?.sections ?? [], [note]);
  const aiDraftCount = sections.filter((s) => Boolean(s.aiDraft)).length;
  const isFinal = note?.status === "Final";

  const saveSection = async (section: LessonNoteSection, patch: Record<string, unknown>) => {
    if (!note) return;
    setBusy(true);
    try {
      setNote(await api.editNoteSection(note.id, section.id, patch));
      onToast(`${section.title} saved`);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const resetSection = async (section: LessonNoteSection) => {
    if (!note) return;
    setBusy(true);
    try {
      setNote(await api.resetNoteSection(note.id, section.id));
      onToast(`${section.title} reset to source`);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const runAi = async () => {
    if (!note) return;
    if (!note.ai.available) {
      onError("AI enrichment needs GEMINI_API_KEY");
      return;
    }
    setAiBusy(true);
    setAiNotice(null);
    try {
      const next = await api.aiNoteDraft(note.id);
      setNote(next);
      const drafts = next.sections.filter((s) => s.aiDraft).length;
      setAiNotice(
        drafts
          ? `${drafts} AI draft${drafts === 1 ? "" : "s"} ready. Yellow boxes are AI suggestions - not from source. Accept each section, Accept All, or Reject.`
          : "AI returned no drafts.",
      );
      onToast("AI notes drafts ready for review");
    } catch (e) {
      fail(e);
    } finally {
      setAiBusy(false);
    }
  };

  const acceptAll = async () => {
    if (!note) return;
    setBusy(true);
    try {
      const next = await api.aiNoteAcceptAll(note.id);
      setNote(next);
      onToast(`Accepted ${next.acceptedSections ?? 0} AI sections`);
      setAiNotice(null);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const saveVersion = async () => {
    if (!note) return;
    if (!comment.trim()) {
      setCommentError("A comment is required, e.g. 'Simplified the vocabulary'.");
      return;
    }
    setBusy(true);
    try {
      const res = await api.createNoteVersion(note.id, comment.trim());
      setNote(res.lessonNote);
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
    if (!note) return;
    setHistoryOpen(true);
    setDiff(null);
    try {
      setVersions((await api.noteVersions(note.id)).versions);
    } catch (e) {
      fail(e);
    }
  };

  const openDiff = async (versionId: string) => {
    if (!note) return;
    try {
      setDiff(await api.noteVersionDiff(note.id, versionId));
    } catch (e) {
      fail(e);
    }
  };

  const restore = async (version: PlanVersion) => {
    if (!note) return;
    setBusy(true);
    try {
      const next = await api.restoreNoteVersion(note.id, version.id);
      setNote(next);
      setRestoreTarget(null);
      setHistoryOpen(false);
      onToast(`Restored - saved as ${next.restoredVersion?.label ?? "a new version"}`);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const setStatus = async (status: "Draft" | "Final") => {
    if (!note) return;
    setBusy(true);
    try {
      setNote(await api.noteStatus(note.id, status));
      onToast(status === "Final" ? "Lesson notes marked Final" : "Reopened as Draft");
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!note) return;
    setBusy(true);
    try {
      const res = await api.deleteLessonNote(note.id);
      setConfirmDelete(false);
      onToast("Lesson notes deleted");
      if (res.deleted) onBack();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const searchWeb = async () => {
    if (!note) return;
    setWebBusy(true);
    try {
      const res = await api.noteWebExamples(note.id, webQuery);
      setWebResults(res.results);
      setWebProvider(res.provider || "");
      setWebMessage(res.message || "");
    } catch (e) {
      fail(e);
    } finally {
      setWebBusy(false);
    }
  };

  const insertWebExample = async (ex: WebExample) => {
    if (!note) return;
    setBusy(true);
    try {
      setNote(
        await api.insertNoteWebExample(note.id, {
          title: ex.title,
          url: ex.url,
          snippet: ex.snippet,
        }),
      );
      setWebOpen(false);
      onToast("Web example inserted and labelled with its source URL");
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  const addSource = async () => {
    if (!note) return;
    if (!sourceTitle.trim() && !sourceUrl.trim() && !sourceText.trim()) {
      setSourceError("Add a title, URL or text for your source.");
      return;
    }
    setBusy(true);
    try {
      setNote(
        await api.addNoteSource(note.id, {
          kind: "teacher",
          title: sourceTitle.trim(),
          url: sourceUrl.trim(),
          text: sourceText.trim(),
        }),
      );
      setSourceOpen(false);
      setSourceTitle("");
      setSourceUrl("");
      setSourceText("");
      setSourceError(null);
      onToast("Teacher source added - shown in the footer");
    } catch (e) {
      setSourceError((e as Error).message);
      fail(e);
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return <p className="card p-6 text-center text-sm text-slate-500">Loading lesson notes…</p>;
  }
  if (!note) {
    return <p className="card p-6 text-center text-sm text-slate-500">Lesson notes not found.</p>;
  }

  const source = note.source;
  const webSources = note.sources.filter((s) => s.kind === "web");
  const teacherSources = note.sources.filter((s) => s.kind === "teacher");

  return (
    <div className="space-y-4" data-testid="notes-editor">
      <section className="card flex flex-wrap items-center gap-2 p-3">
        <button className="btn-ghost px-2 py-1 text-xs" onClick={onBack} data-testid="notes-back">
          ← Back
        </button>
        <Badge tone={isFinal ? "green" : "amber"} data-testid="note-status">
          {isFinal ? "Final" : "Draft"}
        </Badge>
        {note.aiEnriched ? (
          <Badge tone="blue" data-testid="note-ai-badge">
            ✨ AI-enriched
          </Badge>
        ) : null}
        <span className="text-xs text-slate-500">
          Week {note.week} · Lesson {note.lesson} of {note.lessonCount} · {note.subStrandCode}{" "}
          {note.subStrand}
        </span>
        <span className="ml-auto flex flex-wrap items-center gap-2">
          <button
            className="btn-primary"
            onClick={() => {
              setCommentError(null);
              setCommentOpen(true);
            }}
            disabled={busy}
            data-testid="note-save-version"
          >
            Save Version
          </button>
          <button
            className="btn-ghost"
            onClick={runAi}
            disabled={aiBusy || busy || !note.ai.available}
            title={
              note.ai.available
                ? "Draft learner-friendly notes with Gemini"
                : "AI enrichment needs GEMINI_API_KEY"
            }
            data-testid="note-ai"
          >
            {aiBusy ? "Drafting…" : "✨ Draft with AI"}
          </button>
          <button
            className="btn-ghost"
            onClick={() => setWebOpen(true)}
            data-testid="note-find-examples"
          >
            🔍 Find Examples
          </button>
          <button
            className="btn-ghost"
            onClick={() => {
              setSourceError(null);
              setSourceOpen(true);
            }}
            data-testid="note-add-source"
          >
            + Add My Source
          </button>
          <button className="btn-ghost" onClick={openHistory} data-testid="note-history">
            History ({note.versions.length})
          </button>
          {isFinal ? (
            <button className="btn-ghost" onClick={() => setStatus("Draft")} disabled={busy}>
              Reopen as Draft
            </button>
          ) : (
            <button
              className="btn-ghost"
              onClick={() => setStatus("Final")}
              disabled={busy}
              data-testid="note-final"
            >
              Mark Final
            </button>
          )}
          <button
            className="btn-ghost"
            onClick={() => setConfirmDelete(true)}
            disabled={busy}
            data-testid="note-delete"
          >
            Delete
          </button>
          <label className="flex items-center gap-1 text-[10px] text-slate-500">
            <input
              type="checkbox"
              checked={includeAnswers}
              onChange={(e) => setIncludeAnswers(e.target.checked)}
              data-testid="note-pdf-answers"
            />
            answers
          </label>
          <a
            className="btn-ghost"
            href={api.notePdfUrl(note.id, includeAnswers)}
            target="_blank"
            rel="noreferrer"
            data-testid="note-pdf"
          >
            Export PDF
          </a>
        </span>
      </section>

      {!note.ai.available ? (
        <p
          className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600"
          data-testid="note-ai-disabled"
        >
          {note.ai.message} - the notes stay fully usable without AI.
        </p>
      ) : null}

      {aiNotice || aiDraftCount > 0 ? (
        <div
          className="flex flex-wrap items-center gap-2 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900"
          data-testid="note-ai-notice"
        >
          <span className="flex-1">
            {aiNotice ??
              `${aiDraftCount} AI draft${aiDraftCount === 1 ? "" : "s"} waiting for review. Yellow boxes are AI suggestions - not from source.`}
          </span>
          <button
            className="rounded bg-emerald-600 px-2 py-0.5 text-[11px] font-semibold text-white disabled:opacity-50"
            onClick={acceptAll}
            disabled={busy || aiDraftCount === 0}
            data-testid="note-ai-accept-all"
          >
            Accept All
          </button>
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[1fr_19rem]">
        <section className="card space-y-3 p-4" data-testid="note-sections">
          {sections.map((section) => (
            <NoteSectionBlock
              key={section.id}
              section={section}
              busy={busy}
              onSave={(patch) => saveSection(section, patch)}
              onReset={() => resetSection(section)}
              onAcceptAi={() => saveSection(section, { acceptAi: true })}
              onRejectAi={() => saveSection(section, { rejectAi: true })}
            />
          ))}

          <div className="rounded border border-slate-200 bg-slate-50 p-2.5" data-testid="note-footer">
            <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Source</p>
            <p className="mt-0.5 break-words text-[11px] text-slate-600">{note.footer}</p>
          </div>
        </section>

        <aside className="card h-fit space-y-3 p-3 text-xs" data-testid="notes-source-panel">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-800">Source</h3>
            <Badge tone="slate">Read-only</Badge>
          </div>
          <p className="text-[11px] text-slate-500">
            {source.sourceLabel ?? `${note.subStrand} p.${source.page ?? "?"}`}
          </p>

          <div>
            <p className="font-semibold text-slate-600">
              {source.outcomesHeading ??
                "Source: By the end of the sub-strand, the learner should be able to:"}
            </p>
            <ul className="mt-0.5 list-disc space-y-0.5 pl-4 text-slate-600">
              {(source.outcomes ?? []).map((x, i) => (
                <li key={i}>{x}</li>
              ))}
              {!source.outcomes?.length ? <li className="text-slate-400">—</li> : null}
            </ul>
          </div>

          <SourceList label="Experiences" items={source.experiences ?? []} />
          <SourceList label="Key inquiry questions" items={source.kiqs ?? []} />

          {source.appendixResources ? (
            <SourceText label="Appendix resources" value={source.appendixResources} />
          ) : null}
          {source.appendixAssessment ? (
            <SourceText label="Appendix assessment" value={source.appendixAssessment} />
          ) : null}

          {source.rubric?.length ? (
            <div>
              <p className="font-semibold text-slate-600">Rubric</p>
              <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap rounded bg-slate-50 p-1.5 text-[10px] text-slate-600">
                {JSON.stringify(source.rubric, null, 2)}
              </pre>
            </div>
          ) : null}

          {note.chunkId && note.documentId ? (
            <button
              className="text-[11px] text-brand-700 underline"
              onClick={() => onViewSource(note.documentId as string, note.chunkId as string)}
              data-testid="note-open-source"
            >
              Open source chunk in Library
            </button>
          ) : null}

          <div className="border-t border-slate-200 pt-2">
            <h3 className="text-sm font-semibold text-slate-800">AI &amp; Web</h3>
            <p className="mt-1 text-[11px] text-slate-500">
              AI is opt-in. Web examples are inserted only when you choose one.
            </p>
            <div className="mt-2 flex flex-wrap gap-1">
              <button
                className="rounded border border-slate-300 bg-white px-2 py-0.5 text-[10px] text-slate-700 hover:bg-amber-50 disabled:opacity-50"
                onClick={runAi}
                disabled={aiBusy || busy || !note.ai.available}
              >
                ✨ Draft with AI
              </button>
              <button
                className="rounded border border-slate-300 bg-white px-2 py-0.5 text-[10px] text-slate-700 hover:bg-amber-50"
                onClick={() => setWebOpen(true)}
              >
                🔍 Find Examples
              </button>
              <button
                className="rounded border border-slate-300 bg-white px-2 py-0.5 text-[10px] text-slate-700 hover:bg-amber-50"
                onClick={() => setSourceOpen(true)}
              >
                + Add My Source
              </button>
            </div>
            {note.aiEnriched ? (
              <p className="mt-2 text-[10px] text-slate-500">
                AI: {note.aiProvider ?? "gemini"} · {(note.aiTimestamp ?? "").slice(0, 19)}
              </p>
            ) : null}
            {webSources.length ? (
              <div className="mt-2">
                <p className="font-semibold text-slate-600">Web examples</p>
                <ul className="mt-0.5 space-y-0.5">
                  {webSources.map((s) => (
                    <li key={s.id} className="break-all text-[10px] text-slate-500">
                      {s.url}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {teacherSources.length ? (
              <div className="mt-2">
                <p className="font-semibold text-slate-600">Teacher sources</p>
                <ul className="mt-0.5 space-y-0.5">
                  {teacherSources.map((s) => (
                    <li key={s.id} className="text-[10px] text-slate-500">
                      {s.title || s.url || (s.text ?? "").slice(0, 60)}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        </aside>
      </div>

      {commentOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
          <div className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl" data-testid="note-save-dialog">
            <h3 className="text-base font-semibold text-slate-900">Save Version</h3>
            <p className="mt-1 text-xs text-slate-500">
              A comment is required. Restoring later creates a new version and never overwrites one.
            </p>
            <textarea
              autoFocus
              className="mt-3 h-24 w-full rounded border border-slate-300 p-2 text-sm"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="e.g. Simplified vocabulary for Grade 1"
              data-testid="note-comment"
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
        <div
          className="fixed inset-0 z-40 flex justify-end bg-slate-900/40"
          onClick={() => setHistoryOpen(false)}
        >
          <aside
            className="h-full w-full max-w-lg overflow-y-auto bg-white p-4 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
            data-testid="note-version-history"
          >
            <div className="flex items-center justify-between">
              <h3 className="text-base font-semibold text-slate-900">Notes version history</h3>
              <button className="text-slate-400 hover:text-slate-700" onClick={() => setHistoryOpen(false)}>
                ✕
              </button>
            </div>
            <ul className="mt-3 space-y-2">
              {versions.map((v) => (
                <li key={v.id} className="rounded border border-slate-200 p-2 text-xs">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-slate-800">{v.label}</span>
                    <span className="text-slate-400">{v.createdAt}</span>
                    <span className="ml-auto flex gap-2">
                      <button className="underline text-brand-700" onClick={() => openDiff(v.id)}>
                        Diff
                      </button>
                      <button
                        className="underline text-amber-700"
                        onClick={() => setRestoreTarget(v)}
                        disabled={busy}
                        data-testid={`note-restore-${v.versionNumber}`}
                      >
                        Restore
                      </button>
                    </span>
                  </div>
                  <p className="mt-0.5 text-slate-600">{v.comment}</p>
                </li>
              ))}
              {!versions.length ? <li className="text-xs text-slate-500">No versions yet.</li> : null}
            </ul>
            {diff ? (
              <div className="mt-4 rounded border border-slate-200 p-2">
                <p className="text-xs font-semibold text-slate-700">
                  {diff.from} → {diff.to}
                </p>
                <ul className="mt-2 space-y-1">
                  {diff.cells.map((c, i) => (
                    <li key={i} className="rounded bg-slate-50 p-1.5 text-[10px]">
                      <span className="font-semibold text-slate-700">{c.label}</span>
                      <div className="text-rose-700">− {c.from || "(empty)"}</div>
                      <div className="text-emerald-700">+ {c.to || "(empty)"}</div>
                    </li>
                  ))}
                  {!diff.cells.length ? <li className="text-[11px] text-slate-500">No changes.</li> : null}
                </ul>
              </div>
            ) : null}
            {restoreTarget ? (
              <div className="mt-4 rounded border border-amber-300 bg-amber-50 p-3 text-xs">
                <p className="font-semibold text-amber-900">Restore {restoreTarget.label}?</p>
                <p className="mt-1 text-amber-800">
                  This copies that snapshot into the working notes and appends a NEW version. No
                  version is ever deleted.
                </p>
                <div className="mt-2 flex gap-2">
                  <button
                    className="rounded bg-amber-600 px-2 py-0.5 text-[11px] font-semibold text-white"
                    onClick={() => restore(restoreTarget)}
                    disabled={busy}
                    data-testid="note-restore-confirm"
                  >
                    Restore
                  </button>
                  <button className="rounded border px-2 py-0.5 text-[11px]" onClick={() => setRestoreTarget(null)}>
                    Cancel
                  </button>
                </div>
              </div>
            ) : null}
          </aside>
        </div>
      ) : null}

      {webOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
          <div
            className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-lg bg-white p-5 shadow-xl"
            data-testid="note-web-modal"
          >
            <div className="flex items-start justify-between">
              <div>
                <h3 className="text-base font-semibold text-slate-900">Find Examples</h3>
                <p className="text-xs text-slate-500">
                  Teacher-initiated only. Top 3 results; nothing is inserted until you choose.
                </p>
              </div>
              <button className="text-slate-400 hover:text-slate-700" onClick={() => setWebOpen(false)}>
                ✕
              </button>
            </div>
            <div className="mt-3 flex gap-2">
              <input
                className="flex-1 rounded border border-slate-300 px-2 py-1 text-sm"
                value={webQuery}
                onChange={(e) => setWebQuery(e.target.value)}
                placeholder="e.g. sorting bottle tops by colour activity"
                data-testid="note-web-query"
              />
              <button
                className="btn-primary"
                onClick={searchWeb}
                disabled={webBusy}
                data-testid="note-web-search"
              >
                {webBusy ? "Searching…" : "Search"}
              </button>
            </div>
            {webProvider ? (
              <p className="mt-2 text-[11px] text-slate-500" data-testid="note-web-provider">
                Searched via {webProvider === "gemini-grounding" ? "Google (Gemini)" : webProvider === "tavily" ? "Tavily" : webProvider} • {webResults.length} result{webResults.length === 1 ? "" : "s"}
              </p>
            ) : null}
            {webMessage ? (
              <p className="mt-1 text-[11px] text-amber-700" data-testid="note-web-message">{webMessage}</p>
            ) : null}
            <ul className="mt-3 space-y-2">
              {webResults.map((r, i) => (
                <li key={i} className="rounded border border-slate-200 p-2 text-xs">
                  <p className="font-semibold text-slate-800">{r.title}</p>
                  <a
                    className="break-all text-[11px] text-brand-700 underline"
                    href={r.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {r.url}
                  </a>
                  <p className="mt-1 text-slate-600">{r.snippet}</p>
                  <button
                    className="mt-1 rounded border border-brand-300 px-2 py-0.5 text-[10px] text-brand-800 hover:bg-brand-50"
                    onClick={() => insertWebExample(r)}
                    data-testid={`note-web-insert-${i}`}
                  >
                    [Insert as Web Example]
                  </button>
                </li>
              ))}
              {!webResults.length ? (
                <li className="text-xs text-slate-500" data-testid="note-web-empty">
                  No helpful Kenyan CBC activity found. Add your own example or try a different search.
                  <div className="mt-2 flex gap-2">
                    <button
                      className="rounded border border-slate-300 px-2 py-0.5 text-[10px] text-slate-700 hover:bg-slate-50"
                      onClick={() => {
                        setWebOpen(false);
                        setSourceOpen(true);
                      }}
                      data-testid="note-web-add-own"
                    >
                      Add My Own Example
                    </button>
                    <button
                      className="rounded border border-slate-300 px-2 py-0.5 text-[10px] text-slate-700 hover:bg-slate-50"
                      onClick={() => setWebQuery("")}
                      data-testid="note-web-try-different"
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

      {sourceOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
          <div className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl" data-testid="note-source-dialog">
            <h3 className="text-base font-semibold text-slate-900">Add My Source</h3>
            <p className="mt-1 text-xs text-slate-500">
              Stored as a Teacher Source and shown in the source footer. Your source never changes the
              Vetted source chunk.
            </p>
            <div className="mt-3 space-y-2 text-xs">
              <label className="block">
                <span className="font-semibold text-slate-600">Title</span>
                <input
                  autoFocus
                  className="mt-0.5 w-full rounded border border-slate-300 px-2 py-1"
                  value={sourceTitle}
                  onChange={(e) => setSourceTitle(e.target.value)}
                  placeholder="e.g. KICD Grade 1 teacher guide"
                  data-testid="note-source-title"
                />
              </label>
              <label className="block">
                <span className="font-semibold text-slate-600">URL (optional)</span>
                <input
                  className="mt-0.5 w-full rounded border border-slate-300 px-2 py-1"
                  value={sourceUrl}
                  onChange={(e) => setSourceUrl(e.target.value)}
                  placeholder="https://…"
                  data-testid="note-source-url"
                />
              </label>
              <label className="block">
                <span className="font-semibold text-slate-600">Text (optional)</span>
                <textarea
                  className="mt-0.5 h-20 w-full rounded border border-slate-300 px-2 py-1"
                  value={sourceText}
                  onChange={(e) => setSourceText(e.target.value)}
                  placeholder="A note, book reference or activity idea"
                  data-testid="note-source-text"
                />
              </label>
            </div>
            {sourceError ? <p className="mt-1 text-xs text-rose-700">{sourceError}</p> : null}
            <div className="mt-3 flex justify-end gap-2">
              <button className="btn-ghost" onClick={() => setSourceOpen(false)}>
                Cancel
              </button>
              <button className="btn-primary" onClick={addSource} disabled={busy} data-testid="note-source-save">
                Add Source
              </button>
            </div>
          </div>
        </div>
      ) : null}
      {confirmDelete ? (
        <ConfirmDialog
          title="Delete this lesson notes document?"
          body="The notes for this lesson and its versions will be permanently removed. This cannot be undone."
          confirmLabel="Delete notes"
          onConfirm={remove}
          onCancel={() => setConfirmDelete(false)}
        />
      ) : null}
    </div>
  );
}

function NoteSectionBlock({
  section,
  busy,
  onSave,
  onReset,
  onAcceptAi,
  onRejectAi,
}: {
  section: LessonNoteSection;
  busy: boolean;
  onSave: (patch: Record<string, unknown>) => void;
  onReset: () => void;
  onAcceptAi: () => void;
  onRejectAi: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(section.body);
  const [vocabulary, setVocabulary] = useState<VocabularyItem[]>([]);
  const [examples, setExamples] = useState<ExampleItem[]>([]);
  const [practice, setPractice] = useState<PracticeItem[]>([]);
  const [steps, setSteps] = useState<string[]>([]);
  const [showAnswers, setShowAnswers] = useState(false);

  useEffect(() => {
    setDraft(section.body);
    setVocabulary(vocabularyOf(section));
    setExamples(examplesOf(section));
    setPractice(practiceOf(section));
    setSteps(stepsOf(section));
    setEditing(false);
  }, [section]);

  const startEdit = () => setEditing(true);

  const save = () => {
    if (section.key === "vocabulary") {
      onSave({ data: { items: vocabulary } });
    } else if (section.key === "examples") {
      onSave({ data: { items: examples } });
    } else if (section.key === "practice") {
      onSave({ data: { items: practice } });
    } else if (section.key === "workedExample") {
      onSave({ data: { steps } });
    } else {
      onSave({ body: draft });
    }
    setEditing(false);
  };

  if (section.key === "title") {
    return (
      <div className="rounded border border-slate-200 p-2.5" data-testid="note-section-title">
        {editing ? (
          <div className="space-y-1.5">
            <textarea
              autoFocus
              className="h-16 w-full rounded border border-brand-300 p-1.5 text-sm"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              data-testid="note-section-input-title"
            />
            <div className="flex gap-1">
              <button className="rounded bg-brand-600 px-2 py-0.5 text-[10px] text-white" onClick={save} disabled={busy}>
                Save
              </button>
              <button className="rounded border px-2 py-0.5 text-[10px]" onClick={() => setEditing(false)}>
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <button className="block w-full text-center hover:bg-amber-50" onClick={startEdit} data-testid="note-section-body-title">
            <span className="block text-lg font-bold tracking-wide text-slate-900">{draft}</span>
            <span className="mt-1 block text-[11px] text-slate-500">
              Week {String(section.data?.week ?? "—")} · Lesson {String(section.data?.lesson ?? "—")} ·
              Focus: {String(section.data?.focus ?? "—")}
            </span>
          </button>
        )}
      </div>
    );
  }

  if (section.key === "footer") {
    return (
      <div className="rounded border border-slate-200 bg-slate-50 p-2.5" data-testid="note-section-footer">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">Source footer</p>
        <p className="mt-0.5 break-words text-[11px] text-slate-600">{section.body}</p>
      </div>
    );
  }

  return (
    <div className="rounded border border-slate-200 p-2.5" data-testid={`note-section-${section.key}`}>
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-xs font-semibold text-slate-800">{section.title}</h4>
        <Badge
          tone={
            section.provenance === "source"
              ? "blue"
              : section.provenance === "ai"
                ? "amber"
                : section.provenance === "web"
                  ? "blue"
                  : "slate"
          }
        >
          {section.provenance === "source"
            ? "From source"
            : section.provenance === "ai"
              ? "AI accepted"
              : section.provenance === "web"
                ? "Web example"
                : section.provenance === "teacher"
                  ? "Teacher"
                  : "Editable"}
        </Badge>
        {section.editedFromSource ? (
          <Badge tone="amber" data-testid={`note-edited-${section.key}`}>
            Edited
          </Badge>
        ) : null}
        {section.aiAssisted ? <Badge tone="amber">AI-assisted</Badge> : null}
        {section.hint ? <span className="text-[10px] text-slate-400">{section.hint}</span> : null}
        <button
          className="ml-auto text-[10px] text-brand-700 underline"
          onClick={onReset}
          disabled={busy}
          data-testid={`note-reset-${section.key}`}
        >
          ↩ Reset to Source
        </button>
      </div>

      {section.aiDraft ? (
        <div
          className="mt-2 rounded border border-amber-400 bg-amber-50 p-2"
          data-testid={`note-ai-draft-${section.key}`}
        >
          <p className="text-[10px] font-semibold uppercase tracking-wide text-amber-800">
            {AI_REVIEW_LABEL}
          </p>
          <p className="mt-1 whitespace-pre-wrap text-xs text-amber-950">{section.aiDraft}</p>
          <div className="mt-1 flex flex-wrap gap-1">
            <button
              className="rounded bg-emerald-600 px-2 py-0.5 text-[10px] text-white"
              onClick={onAcceptAi}
              disabled={busy}
              data-testid={`note-ai-accept-${section.key}`}
            >
              Accept
            </button>
            <button
              className="rounded border border-amber-400 px-2 py-0.5 text-[10px]"
              onClick={startEdit}
              disabled={busy}
            >
              Edit
            </button>
            <button
              className="rounded border border-rose-300 px-2 py-0.5 text-[10px] text-rose-700"
              onClick={onRejectAi}
              disabled={busy}
              data-testid={`note-ai-reject-${section.key}`}
            >
              Reject
            </button>
          </div>
        </div>
      ) : null}

      {editing ? (
        <div className="mt-2 space-y-1.5">
          {section.key === "vocabulary" ? (
            <VocabularyEditor items={vocabulary} setItems={setVocabulary} />
          ) : section.key === "examples" ? (
            <ExamplesEditor items={examples} setItems={setExamples} />
          ) : section.key === "practice" ? (
            <PracticeEditor items={practice} setItems={setPractice} />
          ) : section.key === "workedExample" ? (
            <StepsEditor steps={steps} setSteps={setSteps} />
          ) : (
            <textarea
              autoFocus
              className="h-28 w-full rounded border border-brand-300 p-1.5 text-sm"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              data-testid={`note-section-input-${section.key}`}
            />
          )}
          <div className="flex flex-wrap gap-1">
            <button
              className="rounded bg-brand-600 px-2 py-0.5 text-[10px] text-white"
              onClick={save}
              disabled={busy}
              data-testid={`note-save-${section.key}`}
            >
              Save
            </button>
            <button className="rounded border px-2 py-0.5 text-[10px]" onClick={() => setEditing(false)}>
              Cancel
            </button>
            <span className="text-[10px] text-slate-400">
              Edits are saved here only - the SourceChunk never changes.
            </span>
          </div>
        </div>
      ) : (
        <div
          role="button"
          tabIndex={0}
          className="mt-1 block w-full cursor-pointer text-left hover:bg-amber-50"
          onClick={startEdit}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") startEdit();
          }}
          data-testid={`note-section-body-${section.key}`}
        >
          {section.key === "vocabulary" ? (
            <ul className="space-y-1.5">
              {vocabulary.map((item, i) => (
                <li key={i} className="text-xs text-slate-700">
                  <span className="font-semibold text-slate-900">{item.word}</span>
                  {item.definition ? <span>: {item.definition}</span> : null}
                  {item.example ? (
                    <span className="mt-0.5 block text-[11px] italic text-slate-500">
                      Example: {item.example}
                    </span>
                  ) : null}
                  <span className="mt-0.5 block text-[9px] uppercase tracking-wide text-slate-400">
                    [{item.source || "From source"}]
                  </span>
                </li>
              ))}
              {!vocabulary.length ? <li className="text-xs italic text-slate-400">No vocabulary yet.</li> : null}
            </ul>
          ) : section.key === "examples" ? (
            <ul className="space-y-1">
              {examples.map((item, i) => {
                const placeholder = item.text.startsWith("[");
                return (
                  <li
                    key={i}
                    className={`text-xs ${placeholder ? "italic text-slate-400" : "text-slate-700"}`}
                  >
                    {!placeholder ? "- " : ""}
                    {item.text}
                    {item.source === "Web" && item.url ? (
                      <span className="mt-0.5 block break-all text-[9px] uppercase tracking-wide text-slate-400">
                        [Web Example - {item.url}]
                      </span>
                    ) : null}
                  </li>
                );
              })}
              {!examples.length ? <li className="text-xs italic text-slate-400">No examples yet.</li> : null}
            </ul>
          ) : section.key === "workedExample" ? (
            <ol className="list-decimal space-y-0.5 pl-5 text-xs text-slate-700">
              {steps.map((step, i) => (
                <li key={i}>{step}</li>
              ))}
              {!steps.length ? <li className="italic text-slate-400">No worked example yet.</li> : null}
            </ol>
          ) : section.key === "practice" ? (
            <div>
              <div className="mb-1 flex items-center gap-2">
                <span className="text-[10px] text-slate-400">
                  Answers are hidden by default for learners.
                </span>
                <button
                  className="rounded border border-slate-300 px-1.5 py-0.5 text-[10px] text-slate-600"
                  onClick={(e) => {
                    e.stopPropagation();
                    setShowAnswers(!showAnswers);
                  }}
                  data-testid="note-practice-toggle"
                >
                  {showAnswers ? "Hide Answers" : "Show Answers"}
                </button>
              </div>
              <ol className="list-decimal space-y-1 pl-5 text-xs text-slate-700">
                {practice.map((item, i) => (
                  <li key={i}>
                    {item.question}
                    {showAnswers ? (
                      <span className="mt-0.5 block text-[11px] italic text-emerald-700">
                        Answer: {item.answer || "—"}
                      </span>
                    ) : null}
                  </li>
                ))}
                {!practice.length ? <li className="italic text-slate-400">No questions yet.</li> : null}
              </ol>
            </div>
          ) : section.key === "remember" ? (
            <p className="rounded border border-emerald-200 bg-emerald-50 px-2 py-1.5 text-xs text-emerald-900">
              {draft || <span className="italic text-slate-400">No summary yet.</span>}
            </p>
          ) : section.key === "whatIs" ? (
            <div className="space-y-1.5">
              {draft
                .split("\n\n")
                .filter((p) => p.trim())
                .map((p, i) => (
                  <p key={i} className="text-xs leading-relaxed text-slate-700">
                    {p}
                  </p>
                ))}
              {!draft.trim() ? (
                <p className="text-xs italic text-slate-400">{section.placeholder ?? "—"}</p>
              ) : null}
            </div>
          ) : (
            <p className="whitespace-pre-wrap text-xs text-slate-700">
              {draft || <span className="italic text-slate-400">{section.placeholder ?? "—"}</span>}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function VocabularyEditor({
  items,
  setItems,
}: {
  items: VocabularyItem[];
  setItems: (items: VocabularyItem[]) => void;
}) {
  const patch = (i: number, next: Partial<VocabularyItem>) =>
    setItems(items.map((item, idx) => (idx === i ? { ...item, ...next } : item)));

  return (
    <div className="space-y-2">
      {items.map((item, i) => (
        <div key={i} className="rounded border border-slate-200 p-1.5">
          <div className="grid gap-1 sm:grid-cols-[10rem_1fr]">
            <input
              className="rounded border border-brand-300 px-1.5 py-0.5 text-xs"
              value={item.word}
              onChange={(e) => patch(i, { word: e.target.value })}
              placeholder="Word"
              data-testid={`note-vocab-word-${i}`}
            />
            <input
              className="rounded border border-brand-300 px-1.5 py-0.5 text-xs"
              value={item.definition}
              onChange={(e) => patch(i, { definition: e.target.value })}
              placeholder="Definition"
              data-testid={`note-vocab-def-${i}`}
            />
          </div>
          <div className="mt-1 grid gap-1 sm:grid-cols-[1fr_7rem]">
            <input
              className="rounded border border-brand-300 px-1.5 py-0.5 text-xs"
              value={item.example}
              onChange={(e) => patch(i, { example: e.target.value })}
              placeholder="Example"
              data-testid={`note-vocab-example-${i}`}
            />
            <select
              className="rounded border border-brand-300 px-1 py-0.5 text-[10px]"
              value={item.source}
              onChange={(e) => patch(i, { source: e.target.value })}
              data-testid={`note-vocab-source-${i}`}
            >
              <option value="From source">From source</option>
              <option value="AI">AI</option>
              <option value="Web">Web</option>
            </select>
          </div>
          <button
            className="mt-1 text-[10px] text-rose-600 underline"
            onClick={() => setItems(items.filter((_, idx) => idx !== i))}
          >
            Remove
          </button>
        </div>
      ))}
      <button
        className="rounded border border-slate-300 px-2 py-0.5 text-[10px]"
        onClick={() => setItems([...items, { word: "", definition: "", example: "", source: "From source" }])}
        data-testid="note-vocab-add"
      >
        + Add word
      </button>
    </div>
  );
}

function ExamplesEditor({
  items,
  setItems,
}: {
  items: ExampleItem[];
  setItems: (items: ExampleItem[]) => void;
}) {
  return (
    <div className="space-y-1.5">
      {items.map((item, i) => (
        <div key={i} className="flex gap-1">
          <input
            className="flex-1 rounded border border-brand-300 px-1.5 py-0.5 text-xs"
            value={item.text}
            onChange={(e) =>
              setItems(items.map((x, idx) => (idx === i ? { ...x, text: e.target.value } : x)))
            }
            placeholder="Example, or [Picture: …] placeholder"
            data-testid={`note-example-${i}`}
          />
          <button
            className="text-[10px] text-rose-600 underline"
            onClick={() => setItems(items.filter((_, idx) => idx !== i))}
          >
            Remove
          </button>
        </div>
      ))}
      <button
        className="rounded border border-slate-300 px-2 py-0.5 text-[10px]"
        onClick={() => setItems([...items, { text: "", source: "From source" }])}
        data-testid="note-example-add"
      >
        + Add example
      </button>
    </div>
  );
}

function PracticeEditor({
  items,
  setItems,
}: {
  items: PracticeItem[];
  setItems: (items: PracticeItem[]) => void;
}) {
  const patch = (i: number, next: Partial<PracticeItem>) =>
    setItems(items.map((item, idx) => (idx === i ? { ...item, ...next } : item)));

  return (
    <div className="space-y-2">
      {items.map((item, i) => (
        <div key={i} className="rounded border border-slate-200 p-1.5">
          <input
            className="w-full rounded border border-brand-300 px-1.5 py-0.5 text-xs"
            value={item.question}
            onChange={(e) => patch(i, { question: e.target.value })}
            placeholder={`Question ${i + 1}`}
            data-testid={`note-practice-question-${i}`}
          />
          <input
            className="mt-1 w-full rounded border border-brand-300 px-1.5 py-0.5 text-[11px]"
            value={item.answer}
            onChange={(e) => patch(i, { answer: e.target.value })}
            placeholder="Answer (hidden from learners by default)"
            data-testid={`note-practice-answer-${i}`}
          />
          <button
            className="mt-1 text-[10px] text-rose-600 underline"
            onClick={() => setItems(items.filter((_, idx) => idx !== i))}
          >
            Remove
          </button>
        </div>
      ))}
      <button
        className="rounded border border-slate-300 px-2 py-0.5 text-[10px]"
        onClick={() => setItems([...items, { question: "", answer: "" }])}
        data-testid="note-practice-add"
      >
        + Add question
      </button>
    </div>
  );
}

function StepsEditor({
  steps,
  setSteps,
}: {
  steps: string[];
  setSteps: (steps: string[]) => void;
}) {
  return (
    <div className="space-y-1.5">
      {steps.map((step, i) => (
        <div key={i} className="flex items-center gap-1">
          <span className="w-4 text-right text-[10px] text-slate-500">{i + 1}.</span>
          <input
            className="flex-1 rounded border border-brand-300 px-1.5 py-0.5 text-xs"
            value={step}
            onChange={(e) => setSteps(steps.map((x, idx) => (idx === i ? e.target.value : x)))}
            data-testid={`note-step-${i}`}
          />
          <button
            className="text-[10px] text-rose-600 underline"
            onClick={() => setSteps(steps.filter((_, idx) => idx !== i))}
          >
            Remove
          </button>
        </div>
      ))}
      <button
        className="rounded border border-slate-300 px-2 py-0.5 text-[10px]"
        onClick={() => setSteps([...steps, ""])}
        data-testid="note-step-add"
      >
        + Add step
      </button>
    </div>
  );
}

function SourceList({ label, items }: { label: string; items: string[] }) {
  return (
    <div>
      <p className="font-semibold text-slate-600">{label}</p>
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
      <p className="font-semibold text-slate-600">{label}</p>
      <p className="whitespace-pre-wrap text-slate-600">{value || "—"}</p>
    </div>
  );
}
