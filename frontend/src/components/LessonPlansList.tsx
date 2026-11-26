import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { LessonPlanList } from "../types";
import { Badge, ConfirmDialog } from "./ui";

interface Props {
  onOpen: (lessonId: string) => void;
  onToast: (msg: string) => void;
  onError: (msg: string) => void;
  /** Bumped by the parent after a lesson plan is created so the list refreshes. */
  refreshKey?: number;
}

const STATUS_TONE: Record<string, "green" | "amber" | "slate"> = {
  Draft: "amber",
  Final: "green",
};

export default function LessonPlansList({ onOpen, onToast, onError, refreshKey }: Props) {
  const [data, setData] = useState<LessonPlanList | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmId, setConfirmId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await api.lessonPlans();
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
      await api.lessonStatus(id, "Final");
      onToast("Lesson plan marked Final ✓");
      await load();
    });

  const remove = (id: string) =>
    withBusy(async () => {
      await api.deleteLessonPlan(id);
      setConfirmId(null);
      onToast("Lesson plan deleted");
      await load();
    });

  const target = data?.plans.find((p) => p.id === confirmId) ?? null;

  return (
    <div className="mx-auto w-full max-w-4xl" data-testid="lesson-plans-list">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-slate-900">My Lesson Plans</h2>
          <p className="text-sm text-muted">
            Every generated lesson plan is kept here as a Draft until you mark it Final or delete it.
          </p>
        </div>
      </div>

      {data === null ? (
        <div className="card p-6 text-sm text-muted" data-testid="lesson-plans-loading">
          Loading lesson plans…
        </div>
      ) : data.plans.length === 0 ? (
        <div className="card p-6 text-sm text-muted" data-testid="lesson-plans-empty">
          No lesson plans yet. Open a Scheme of Work, then create lesson plans from a week row.
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {data.plans.map((p) => (
            <div className="card flex flex-col gap-3 p-4" data-testid={`lesson-plan-row-${p.id}`} key={p.id}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-slate-900">{p.planTitle}</span>
                    <Badge tone="slate">{p.grade}</Badge>
                    <Badge tone="slate">{p.subject}</Badge>
                  </div>
                  <p className="mt-1 text-xs text-slate-500">
                    {p.planTitle} · Week {p.week} · Lesson {p.lesson} of {p.lessonCount} ·{" "}
                    {p.subStrandCode ? `${p.subStrandCode} ` : ""}
                    {p.subStrand ?? ""}
                  </p>
                  <p className="mt-1 text-xs text-slate-600">Focus: {p.focus}</p>
                </div>
                <Badge tone={STATUS_TONE[p.status] ?? "slate"} data-testid={`lesson-plan-status-${p.id}`}>
                  {p.status}
                </Badge>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <button
                  className="btn-primary px-3 py-1.5 text-xs"
                  onClick={() => withBusy(async () => onOpen(p.id))}
                  disabled={busy}
                  data-testid={`lesson-open-${p.id}`}
                >
                  Open
                </button>
                {p.status === "Draft" ? (
                  <button
                    className="btn-ghost px-2.5 py-1.5 text-xs"
                    onClick={() => markFinal(p.id)}
                    disabled={busy}
                    data-testid={`lesson-final-${p.id}`}
                  >
                    Mark Final
                  </button>
                ) : null}
                <button
                  className="btn-ghost px-2.5 py-1.5 text-xs text-rose-600 hover:text-rose-800"
                  onClick={() => setConfirmId(p.id)}
                  disabled={busy}
                  data-testid={`lesson-delete-${p.id}`}
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
          title="Delete this lesson plan?"
          body={`${target.planTitle} - Week ${target.week} Lesson ${target.lesson} will be permanently removed. This cannot be undone.`}
          confirmLabel="Delete lesson plan"
          onConfirm={() => remove(target.id)}
          onCancel={() => setConfirmId(null)}
        />
      ) : null}
    </div>
  );
}
