import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { PlanDocument, PlanSummary } from "../types";
import { Badge, ConfirmDialog } from "./ui";

interface Props {
  /** Open a scheme in the editor. */
  onOpen: (plan: PlanDocument) => void;
  /** Show the create-scheme wizard. */
  onCreate: () => void;
  onToast: (msg: string) => void;
  onError: (msg: string) => void;
  /** Bumped by the parent after a scheme is created so the list refreshes. */
  refreshKey?: number;
}

const STATUS_TONE: Record<string, "green" | "amber" | "slate"> = {
  Draft: "amber",
  Final: "green",
  Archived: "slate",
};

function SchemeRow({
  plan,
  busy,
  onOpen,
  onMarkFinal,
  onUnlock,
  onDuplicate,
  onDelete,
}: {
  plan: PlanSummary;
  busy: boolean;
  onOpen: () => void;
  onMarkFinal: () => void;
  onUnlock: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
}) {
  const date = plan.createdAt ? new Date(plan.createdAt.replace(" ", "T") + "Z") : null;
  return (
    <div className="card flex flex-col gap-3 p-4" data-testid={`scheme-row-${plan.id}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-slate-900">{plan.title}</span>
            <Badge tone="slate">{plan.grade}</Badge>
            <Badge tone="slate">{plan.subject}</Badge>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {plan.term || "—"}
            {date ? ` · created ${date.toLocaleDateString()}` : ""}
          </p>
        </div>
        <Badge tone={STATUS_TONE[plan.status] ?? "slate"} data-testid={`scheme-status-${plan.id}`}>
          {plan.status}
        </Badge>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
        <span>
          <span className="font-semibold text-slate-800">{plan.sectionCount}</span> week rows
        </span>
        <span aria-hidden>·</span>
        <span>
          <span className="font-semibold text-slate-800">{plan.totalLessons ?? "—"}</span> lessons
        </span>
        {plan.warning ? <Badge tone="amber">did not fit the term</Badge> : null}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button
          className="btn-primary px-3 py-1.5 text-xs"
          onClick={onOpen}
          disabled={busy}
          data-testid={`scheme-open-${plan.id}`}
        >
          Open
        </button>
        {plan.status === "Draft" ? (
          <button
            className="btn-ghost px-2.5 py-1.5 text-xs"
            onClick={onMarkFinal}
            disabled={busy}
            data-testid={`scheme-final-${plan.id}`}
          >
            Mark Final
          </button>
        ) : null}
        {plan.status === "Final" ? (
          <button
            className="btn-ghost px-2.5 py-1.5 text-xs"
            onClick={onUnlock}
            disabled={busy}
            data-testid={`scheme-unlock-${plan.id}`}
          >
            Unlock to Edit
          </button>
        ) : null}
        <button
          className="btn-ghost px-2.5 py-1.5 text-xs"
          onClick={onDuplicate}
          disabled={busy}
          data-testid={`scheme-duplicate-${plan.id}`}
        >
          Duplicate
        </button>
        <button
          className="btn-ghost px-2.5 py-1.5 text-xs text-rose-600 hover:text-rose-800"
          onClick={onDelete}
          disabled={busy}
          data-testid={`scheme-delete-${plan.id}`}
        >
          Delete
        </button>
      </div>
    </div>
  );
}

export default function SchemeList({ onOpen, onCreate, onToast, onError, refreshKey }: Props) {
  const [plans, setPlans] = useState<PlanSummary[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmId, setConfirmId] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await api.plans();
      setPlans(res.plans);
    } catch (e) {
      onError((e as Error).message);
      setPlans([]);
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
      await api.planStatus(id, "Final");
      onToast("Marked Final ✓");
      await load();
    });

  const unlock = (id: string) =>
    withBusy(async () => {
      await api.unlockPlan(id);
      onToast("Unlocked as a new Draft ✓");
      await load();
    });

  const duplicate = (id: string) =>
    withBusy(async () => {
      const copy = await api.duplicatePlan(id);
      onToast("Scheme duplicated ✓");
      onOpen(copy);
    });

  const remove = (id: string) =>
    withBusy(async () => {
      await api.deletePlan(id);
      setConfirmId(null);
      onToast("Scheme deleted");
      await load();
    });

  const target = plans?.find((p) => p.id === confirmId) ?? null;

  return (
    <div className="mx-auto w-full max-w-4xl" data-testid="scheme-list">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-slate-900">My Schemes</h2>
          <p className="text-sm text-muted">
            Every generated scheme is kept here as a Draft until you mark it Final or delete it.
          </p>
        </div>
        <button className="btn-primary px-3.5 py-2 text-sm" onClick={onCreate} data-testid="scheme-create">
          + New Scheme of Work
        </button>
      </div>

      {plans === null ? (
        <div className="card p-6 text-sm text-muted">Loading schemes…</div>
      ) : plans.length === 0 ? (
        <div className="card p-6 text-sm text-muted" data-testid="scheme-list-empty">
          No schemes yet. Generate your first Scheme of Work to see it here.
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {plans.map((p) => (
            <SchemeRow
              key={p.id}
              plan={p}
              busy={busy}
              onOpen={() => withBusy(async () => onOpen(await api.plan(p.id)))}
              onMarkFinal={() => markFinal(p.id)}
              onUnlock={() => unlock(p.id)}
              onDuplicate={() => duplicate(p.id)}
              onDelete={() => setConfirmId(p.id)}
            />
          ))}
        </div>
      )}

      {target ? (
        <ConfirmDialog
          title="Delete this scheme?"
          body={`"${target.title}" and all of its week rows, versions and lesson plans will be permanently removed. This cannot be undone.`}
          confirmLabel="Delete scheme"
          onConfirm={() => remove(target.id)}
          onCancel={() => setConfirmId(null)}
        />
      ) : null}
    </div>
  );
}
