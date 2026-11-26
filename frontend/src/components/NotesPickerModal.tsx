import { useState } from "react";
import { api } from "../api";
import type { NotesPicker } from "../types";

interface Props {
  picker: NotesPicker;
  onClose: () => void;
  onCreated: (count: number, firstNoteId?: string) => void;
  onOpenNote: (noteId: string) => void;
  onError: (e: unknown) => void;
}

/**
 * One scheme row prints "Lesson 1-5". Lesson Notes are one document per LESSON,
 * so this picker creates (or opens) Lesson Notes lesson by lesson.
 */
export default function NotesPickerModal({
  picker,
  onClose,
  onCreated,
  onOpenNote,
  onError,
}: Props) {
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const blocked = !picker.sourceVetted;
  const missing = picker.lessons.filter((l) => !l.created);

  const toggle = (lesson: number) => {
    const next = new Set(selected);
    if (next.has(lesson)) next.delete(lesson);
    else next.add(lesson);
    setSelected(next);
  };

  const create = async () => {
    const chosen = [...selected].sort((a, b) => a - b);
    if (!chosen.length) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.createLessonNotes({
        schemeRowId: picker.sectionId,
        lessons: chosen,
        templateVersion: picker.templateVersion,
      });
      onCreated(res.count, res.created[0]?.id);
    } catch (e) {
      const message = (e as Error).message;
      setError(message);
      onError(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div
        className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-lg bg-white p-5 shadow-xl"
        data-testid="notes-picker"
      >
        <div className="flex items-start justify-between">
          <div>
            <h3 className="text-base font-semibold text-slate-900">
              Lesson Notes · Week {picker.week} · Lesson {picker.lessonRange}
            </h3>
            <p className="text-xs text-slate-500">
              {picker.subStrandCode} {picker.subStrand} · one notes document per lesson ·{" "}
              {picker.gradeBand === "jss" ? "Junior School template" : "Primary template"}
            </p>
          </div>
          <button className="text-slate-400 hover:text-slate-700" onClick={onClose}>
            ✕
          </button>
        </div>

        {blocked ? (
          <p
            className="mt-3 rounded bg-rose-50 px-3 py-2 text-xs text-rose-800"
            data-testid="notes-picker-blocked"
          >
            {picker.vettingMessage || "Cannot generate notes - source not Vetted"}
          </p>
        ) : null}

        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <button
            className="btn-ghost px-2 py-1"
            onClick={() => setSelected(new Set(picker.lessons.map((l) => l.lesson)))}
            data-testid="notes-picker-select-all"
          >
            Select All
          </button>
          <button
            className="btn-ghost px-2 py-1"
            onClick={() => setSelected(new Set(missing.map((l) => l.lesson)))}
            data-testid="notes-picker-select-missing"
          >
            Select Missing Only
          </button>
          <span className="text-slate-500">
            {picker.createdCount} of {picker.lessonCount} notes already created
          </span>
        </div>

        <ul className="mt-2 divide-y divide-slate-100 rounded border border-slate-200">
          {picker.lessons.map((l) => (
            <li key={l.lesson} className="flex flex-wrap items-center gap-2 px-3 py-1.5 text-xs">
              <input
                type="checkbox"
                checked={selected.has(l.lesson)}
                disabled={l.created || blocked}
                onChange={() => toggle(l.lesson)}
                data-testid={`notes-picker-check-${l.lesson}`}
              />
              <span className="font-mono text-slate-500">L{l.lesson}</span>
              <span className="flex-1 text-slate-700">
                <span className="font-medium">{l.title}</span>
                <span className="block text-[10px] text-slate-400">{l.focus}</span>
              </span>
              {l.created && l.noteId ? (
                <button
                  className="rounded bg-emerald-100 px-1.5 py-0.5 font-medium text-emerald-800 hover:bg-emerald-200"
                  onClick={() => onOpenNote(l.noteId as string)}
                  data-testid={`notes-picker-open-${l.lesson}`}
                >
                  Open · {l.status ?? "Draft"}
                </button>
              ) : (
                <span className="text-[10px] uppercase tracking-wide text-slate-400">
                  Not created
                </span>
              )}
            </li>
          ))}
        </ul>

        <p className="mt-2 text-[10px] text-slate-400">
          Notes mirror the Lesson Plan focus exactly: colour, shape, size, consolidation and
          assessment each get their own document.
        </p>

        {error ? (
          <p className="mt-2 rounded bg-rose-50 px-2 py-1 text-xs text-rose-800" data-testid="notes-picker-error">
            {error}
          </p>
        ) : null}

        <div className="mt-4 flex items-center justify-end gap-2">
          <span className="mr-auto text-[11px] text-slate-500">
            {selected.size} selected · {missing.length} missing
          </span>
          <button className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn-primary"
            onClick={create}
            disabled={busy || blocked || selected.size === 0}
            data-testid="notes-picker-create"
          >
            {busy ? "Generating…" : picker.createdCount > 0 ? "Create Missing Notes" : "Generate Notes"}
          </button>
        </div>
      </div>
    </div>
  );
}
