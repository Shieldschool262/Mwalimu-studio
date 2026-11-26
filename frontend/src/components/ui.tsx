import { useEffect, useRef, useState } from "react";

/* -------------------------------------------------------------------------- */
/* Design-system primitives                                                    */
/* -------------------------------------------------------------------------- */

export type Provenance =
  | "source"
  | "verbatim"
  | "ai"
  | "teacher"
  | "web"
  | "derived"
  | "empty";

/** The four badges the studio uses everywhere. */
export function ProvenanceBadge({ kind, edited }: { kind: Provenance; edited?: boolean }) {
  if (edited) {
    return (
      <span className="badge-edited">
        <span aria-hidden>✎</span> Teacher Edited
      </span>
    );
  }
  if (kind === "ai") {
    return (
      <span className="badge-ai">
        <span aria-hidden>✨</span> AI Draft · Not from source
      </span>
    );
  }
  if (kind === "web") {
    return (
      <span className="badge border border-sky-300 bg-sky-50 text-sky-800">
        <span aria-hidden>🔗</span> Web example
      </span>
    );
  }
  if (kind === "source" || kind === "verbatim") {
    return (
      <span className="badge-verbatim">
        <span aria-hidden>✓</span> Verbatim Source
      </span>
    );
  }
  if (kind === "derived") {
    return (
      <span className="badge border border-brand-200 bg-brand-50 text-brand-800">
        Source-derived
      </span>
    );
  }
  return <span className="badge-pending">Editable</span>;
}

export function ApprovedBadge({ label = "Approved" }: { label?: string }) {
  return (
    <span className="badge-approved">
      <span aria-hidden>✓</span> {label}
    </span>
  );
}

export function AIDraftLabel() {
  return (
    <span className="badge-ai">
      <span aria-hidden>✨</span> AI Draft · Not from source · Review
    </span>
  );
}

/**
 * Text that never silently truncates. Long content gets a real [Expand] button.
 * The collapsed state uses line-clamp; the expanded state has no fixed height.
 */
export function ExpandableText({
  text,
  threshold = 180,
  lines = 5,
  className = "",
  testId,
}: {
  text: string;
  threshold?: number;
  lines?: number;
  className?: string;
  testId?: string;
}) {
  const [open, setOpen] = useState(false);
  const long = text.length > threshold || text.split("\n").length > lines;
  if (!long) {
    return (
      <span className={`whitespace-pre-wrap ${className}`} data-testid={testId}>
        {text}
      </span>
    );
  }
  return (
    <span className={className} data-testid={testId}>
      <span
        className={open ? "whitespace-pre-wrap" : "line-clamp-5 whitespace-pre-wrap"}
        style={open ? undefined : { WebkitLineClamp: lines }}
      >
        {text}
      </span>
      <button
        type="button"
        className="ml-1 align-baseline text-[10px] font-semibold text-brand-700 underline"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
      >
        [{open ? "Collapse" : "Expand"}]
      </button>
    </span>
  );
}

export function ExpandableList({
  items,
  threshold = 4,
  className = "",
  testId,
}: {
  items: string[];
  threshold?: number;
  className?: string;
  testId?: string;
}) {
  const [open, setOpen] = useState(false);
  if (!items.length) return <span className="italic text-slate-400">—</span>;
  const long = items.length > threshold || items.join(" ").length > 220;
  const shown = open || !long ? items : items.slice(0, threshold);
  return (
    <span className={className} data-testid={testId}>
      <ul className="list-disc space-y-1 pl-4">
        {shown.map((item, i) => (
          <li key={i} className="whitespace-pre-wrap">
            {item}
          </li>
        ))}
      </ul>
      {long ? (
        <button
          type="button"
          className="mt-0.5 text-[10px] font-semibold text-brand-700 underline"
          onClick={(e) => {
            e.stopPropagation();
            setOpen((v) => !v);
          }}
        >
          [{open ? "Collapse" : "Expand"}]
        </button>
      ) : null}
    </span>
  );
}

export function Tabs<T extends string>({
  value,
  onChange,
  items,
  ariaLabel,
  className = "",
}: {
  value: T;
  onChange: (value: T) => void;
  items: { value: T; label: React.ReactNode; testId?: string }[];
  ariaLabel?: string;
  className?: string;
}) {
  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={`inline-flex flex-wrap items-center gap-1 rounded-xl border border-line bg-white p-1 ${className}`}
    >
      {items.map((item) => {
        const active = item.value === value;
        return (
          <button
            key={item.value}
            role="tab"
            aria-selected={active}
            className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
              active
                ? "bg-brand-600 text-white shadow-sm"
                : "text-muted hover:bg-brand-50 hover:text-brand-800"
            }`}
            onClick={() => onChange(item.value)}
            data-testid={item.testId}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}

export function InfoRow({
  label,
  children,
  strong,
}: {
  label: string;
  children: React.ReactNode;
  strong?: boolean;
}) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-xs">
      <span className="field-label shrink-0">{label}</span>
      <span className={strong ? "font-semibold text-ink" : "text-ink"}>{children}</span>
    </div>
  );
}

export function Badge({
  tone = "slate",
  children,
  className = "",
  ...rest
}: {
  tone?: "slate" | "green" | "amber" | "red" | "blue" | "dark";
  children: React.ReactNode;
  className?: string;
} & React.HTMLAttributes<HTMLSpanElement>) {
  const tones: Record<string, string> = {
    slate: "bg-slate-100 text-slate-700 ring-1 ring-slate-200",
    green: "bg-brand-50 text-brand-800 ring-1 ring-brand-200",
    amber: "bg-amber-50 text-amber-800 ring-1 ring-amber-200",
    red: "bg-rose-50 text-rose-800 ring-1 ring-rose-200",
    blue: "bg-sky-50 text-sky-800 ring-1 ring-sky-200",
    dark: "bg-brand-600 text-white ring-1 ring-brand-700",
  };
  return (
    <span className={`badge ${tones[tone]} ${className}`} {...rest}>
      {children}
    </span>
  );
}

export function ConfidenceBadge({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const tone = value >= 0.9 ? "green" : value >= 0.7 ? "amber" : "red";
  return (
    <Badge tone={tone as "green" | "amber" | "red"}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {pct}%
    </Badge>
  );
}

export function ReviewStateBadge({ state }: { state: string }) {
  if (state === "Approved") return <Badge tone="green">✓ Approved</Badge>;
  if (state === "TeacherCorrected") return <Badge tone="blue">Teacher Corrected</Badge>;
  return <Badge tone="amber">Needs review</Badge>;
}

/**
 * Click-to-edit field. The text itself becomes a textarea in place.
 * Enter (without Shift) or clicking outside saves; Esc cancels.
 */
export function EditableField({
  label,
  values,
  onSave,
  onUndo,
  canUndo,
  saving,
  highlight = false,
  missing = false,
  multiline = true,
}: {
  label: string;
  values: string[];
  onSave: (text: string) => void;
  onUndo?: () => void;
  canUndo?: boolean;
  saving?: boolean;
  highlight?: boolean;
  missing?: boolean;
  multiline?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(values.join("\n"));
  const boxRef = useRef<HTMLDivElement>(null);
  const areaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!editing) setDraft(values.join("\n"));
  }, [values, editing]);

  useEffect(() => {
    if (editing) areaRef.current?.focus();
  }, [editing]);

  // Click outside saves (matches the spec: Enter OR click outside both save).
  useEffect(() => {
    if (!editing) return;
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        commit();
      }
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing, draft]);

  const commit = () => {
    setEditing(false);
    if (draft !== values.join("\n")) onSave(draft);
  };

  const cancel = () => {
    setDraft(values.join("\n"));
    setEditing(false);
  };

  const startEdit = () => {
    if (saving) return;
    setDraft(values.join("\n"));
    setEditing(true);
  };

  return (
    <div
      ref={boxRef}
      className={`rounded-md p-1.5 transition-colors ${
        highlight
          ? "bg-yellow-100 ring-2 ring-yellow-400"
          : missing
            ? "bg-rose-50 ring-1 ring-rose-200"
            : "hover:bg-slate-50"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
          {label}
        </div>
        {canUndo && !editing ? (
          <button
            className="text-[11px] font-medium text-slate-500 hover:text-slate-800"
            onClick={onUndo}
            title="Restore the originally extracted text"
          >
            ↩ Undo
          </button>
        ) : null}
      </div>

      {editing ? (
        <div className="mt-1">
          <textarea
            ref={areaRef}
            className="w-full resize-y rounded border border-emerald-400 bg-white p-1.5 font-mono text-xs outline-none ring-1 ring-emerald-200"
            rows={multiline ? 5 : 2}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                e.preventDefault();
                cancel();
              }
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                commit();
              }
            }}
          />
          <div className="mt-1 flex items-center gap-2">
            <button className="btn-mini-primary" onClick={commit} disabled={saving}>
              Save
            </button>
            <button className="btn-mini" onClick={cancel} disabled={saving}>
              Cancel
            </button>
            <span className="text-[10px] text-slate-400">Enter saves · Esc cancels</span>
          </div>
        </div>
      ) : values.length === 0 ? (
        <button
          onClick={startEdit}
          className="mt-0.5 w-full text-left text-xs italic text-slate-400 hover:text-emerald-700"
        >
          none parsed — click to add
        </button>
      ) : (
        <ul
          className="mt-0.5 cursor-text list-disc space-y-0.5 pl-4 text-xs text-slate-700"
          onClick={startEdit}
          title="Click to edit"
        >
          {values.map((v, i) => (
            <li key={`${i}-${v.slice(0, 20)}`}>{v}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Toast({
  message,
  onDone,
  duration = 3200,
}: {
  message: string;
  onDone: () => void;
  duration?: number;
}) {
  useEffect(() => {
    const t = setTimeout(onDone, duration);
    return () => clearTimeout(t);
  }, [message, duration, onDone]);

  return (
    <div className="fixed bottom-5 left-1/2 z-50 -translate-x-1/2">
      <div className="rounded-lg bg-brand-700 px-4 py-2.5 text-sm font-medium text-white shadow-lg ring-1 ring-brand-900">
        {message}
      </div>
    </div>
  );
}

export function ConfirmDialog({
  title,
  body,
  confirmLabel = "Delete",
  danger = true,
  onConfirm,
  onCancel,
}: {
  title: string;
  body: string;
  confirmLabel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
      <div className="w-full max-w-sm rounded-lg bg-white p-5 shadow-xl">
        <h3 className="text-base font-semibold text-slate-900">{title}</h3>
        <p className="mt-2 text-sm text-slate-600">{body}</p>
        <div className="mt-4 flex justify-end gap-2">
          <button className="btn-ghost" onClick={onCancel}>
            Cancel
          </button>
          <button
            className={danger ? "btn bg-rose-600 text-white hover:bg-rose-700" : "btn-primary"}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
