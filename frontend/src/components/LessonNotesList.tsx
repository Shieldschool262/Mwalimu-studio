import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { LessonNotesList } from "../types";
import { Badge, ConfirmDialog } from "./ui";

interface Props {
  onOpen: (noteId: string) => void;
  onToast: (msg: string) => void;
  onError: (msg: string) => void;
  /** Bumped by the parent after notes are created so the list refreshes. */
  refreshKey?: number;
}

const STATUS_TONE: Record<string, "green" | "amber" | "slate"> = {
  Draft: "amber",
  Final: "green",
};

export default function LessonNotesList({ onOpen, onToast, onError, refreshKey }: Props) {
  const [data, setData] = useState<LessonNotesList | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmId, setConfirmId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await api.lessonNotes();
      setData(res);
    } catch (e) {
      onError((e as Error).message);
      setData(null);
    }
  }, [onError]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  const withBusy = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const markFinal = (id: string) =>
    withBusy(async () => {
      await api.noteStatus(id, "Final");
      onToast("Lesson notes marked Final ✓");
      await load();
    });

  const remove = (id: string) =>
    withBusy(async () => {
      await api.deleteLessonNote(id);
      setConfirmId(null);
      onToast("Lesson notes deleted");
      await load();
    });

  const target = data?.notes.find((n) => n.id === confirmId) ?? null;

  return (
    <div className="mx-auto w-full max-w-4xl" data-testid="lesson-notes-list">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-slate-900">My Lesson Notes</h2>
          <p className="text-sm text-muted">
            Every learner-facing lesson notes document is kept here as a Draft until you mark it Final or
            delete it.
          </p>
        </div>
      </div>

      {data === null ? (
        <div className="card p-6 text-sm text-muted" data-testid="lesson-notes-loading">
          Loading lesson notes…
        </div>
      ) : data.notes.length === 0 ? (
        <div className="card p-6 text-sm text-muted" data-testid="lesson-notes-empty">
          No lesson notes yet. Create one from a lesson plan with [→ Notes for This Lesson].
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {data.notes.map((n) => (
            <div className="card flex flex-col gap-3 p-4" data-testid={`lesson-note-row-${n.id}`} key={n.id}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-slate-900">{n.title}</span>
                    <Badge tone="slate">{n.grade}</Badge>
                    <Badge tone="slate">{n.subject}</Badge>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    Week {n.week} · Lesson {n.lesson} of {n.lessonCount} · {n.subStrandCode} {n.subStrand}
                  </p>
                  <p className="mt-1 text-xs text-slate-600">Focus: {n.focus}</p>
                </div>
                <Badge tone={STATUS_TONE[n.status] ?? "slate"} data-testid={`lesson-note-status-${n.id}`}>
                  {n.status}
                </Badge>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <button
                  className="btn-primary px-3 py-1.5 text-xs"
                  onClick={() => withBusy(async () => onOpen(n.id))}
                  disabled={busy}
                  data-testid={`note-open-${n.id}`}
                >
                  Open
                </button>
                {n.status === "Draft" ? (
                  <button
                    className="btn-ghost px-2.5 py-1.5 text-xs"
                    onClick={() => markFinal(n.id)}
                    disabled={busy}
                    data-testid={`note-final-${n.id}`}
                  >
                    Mark Final
                  </button>
                ) : null}
                <button
                  className="btn-ghost px-2.5 py-1.5 text-xs text-rose-600 hover:text-rose-800"
                  onClick={() => setConfirmId(n.id)}
                  disabled={busy}
                  data-testid={`note-delete-${n.id}`}
                >
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {target ? (
        <ConfirmDialog
          title="Delete this lesson notes document?"
          body={`${target.title} - Week ${target.week} Lesson ${target.lesson} will be permanently removed. This cannot be undone.`}
          confirmLabel="Delete notes"
          onConfirm={() => remove(target.id)}
          onCancel={() => setConfirmId(null)}
        />
      ) : null}
    </div>
  );
}
