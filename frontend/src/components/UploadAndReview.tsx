import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { ParseJob, SourceChunk, StrandGroup } from "../types";
import { Badge, ConfidenceBadge, EditableField, ReviewStateBadge } from "./ui";

type Props = {
  job: ParseJob | null;
  setJob: (job: ParseJob | null) => void;
  /** Read-only header (no upload button) when opened from the Library. */
  fromLibrary?: boolean;
  /** Chunk ids to highlight, e.g. from a search hit. */
  highlightChunkIds?: string[];
  onSavedToLibrary?: (job: ParseJob) => void;
  onError?: (msg: string) => void;
};

const LIST_KEYS = [
  ["outcomes", "Outcomes", "specific_learning_outcomes"],
  ["experiences", "Experiences", "suggested_learning_experiences"],
  ["kiqs", "Key inquiry questions", "key_inquiry_questions"],
] as const;

const TEXT_KEYS = [
  ["core_competencies", "Core competencies"],
  ["values", "Values"],
  ["pcis", "PCIs"],
  ["link_to_other_learning_areas", "Link to other learning areas"],
] as const;

function SubStrandCard({
  chunk,
  jobId,
  onJob,
  onError,
  highlighted,
  saving,
  setSaving,
}: {
  chunk: SourceChunk;
  jobId: string;
  onJob: (job: ParseJob) => void;
  onError: (msg: string) => void;
  highlighted: boolean;
  saving: boolean;
  setSaving: (v: boolean) => void;
}) {
  const sf = chunk.structuredFields;
  const of = chunk.originalFields || {};
  const [appendixOpen, setAppendixOpen] = useState(false);
  const hasAppendix = Boolean(chunk.appendixResources || chunk.appendixAssessment);

  const patch = useCallback(
    async (body: Record<string, unknown>) => {
      setSaving(true);
      try {
        onJob(await api.correctChunk(jobId, chunk.id, body));
      } catch (e) {
        onError((e as Error).message);
      } finally {
        setSaving(false);
      }
    },
    [jobId, chunk.id, onJob, onError, setSaving],
  );

  const edited = (key: string) => {
    const orig = (of as Record<string, unknown>)[key];
    if (orig === undefined) return false;
    return JSON.stringify(orig) !== JSON.stringify((sf as Record<string, unknown>)[key]);
  };

  return (
    <div
      id={`chunk-${chunk.id}`}
      className={`card p-3 ${
        highlighted ? "ring-2 ring-yellow-400" : chunk.needsReview ? "border-amber-200" : ""
      }`}
    >
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-slate-500">{chunk.subStrandCode ?? "—"}</span>
            <span className="font-medium text-slate-900">{chunk.subStrand}</span>
            <ReviewStateBadge state={chunk.reviewState} />
            {chunk.missingFields.length > 0 ? (
              <span className="badge bg-rose-100 text-rose-800 ring-1 ring-rose-300">
                Missing: {chunk.missingFields.join(", ")}
              </span>
            ) : null}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span>page {chunk.pageNumber ?? "—"}</span>
            <span aria-hidden>·</span>
            <span>{chunk.lessons ? `${chunk.lessons} lessons` : "lessons not stated"}</span>
            <span aria-hidden>·</span>
            <span className="inline-flex items-center gap-1">
              confidence <ConfidenceBadge value={chunk.confidence} />
            </span>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {chunk.reviewState === "Approved" ? (
            <button className="btn-ghost" disabled={saving} onClick={() => patch({ reviewState: "Parsed" })}>
              Un-approve
            </button>
          ) : (
            <button
              className="btn-primary"
              disabled={saving}
              onClick={() => patch({ reviewState: "Approved" })}
              title="Approve this sub-strand"
              data-testid="card-approve"
            >
              ✓ Approve
            </button>
          )}
        </div>
      </div>

      {chunk.flags.length > 0 ? (
        <ul className="mt-2 space-y-1">
          {chunk.flags.map((f) => (
            <li key={f} className="text-xs text-amber-700">
              ⚠ {f}
            </li>
          ))}
        </ul>
      ) : null}

      <div className="mt-2 grid gap-2 md:grid-cols-3">
        {LIST_KEYS.map(([alias, label, key]) => (
          <EditableField
            key={alias}
            label={label}
            values={sf[key] ?? []}
            missing={chunk.missingFields.includes(label === "Key inquiry questions" ? "KIQs" : label)}
            saving={saving}
            canUndo={edited(key)}
            onSave={(text) => patch({ field: alias, newValue: text })}
            onUndo={() => patch({ undoField: alias })}
          />
        ))}
      </div>

      {TEXT_KEYS.some(([k]) => (sf as Record<string, unknown>)[k]) ? (
        <div className="mt-1 grid gap-2 md:grid-cols-2">
          {TEXT_KEYS.map(([key, label]) => {
            const val = (sf as Record<string, unknown>)[key];
            const text = val ? String(val) : "";
            return (
              <EditableField
                key={key}
                label={label}
                values={text ? [text] : []}
                multiline={false}
                saving={saving}
                canUndo={edited(key)}
                onSave={(t) => patch({ field: key, newValue: t.replace(/\n+/g, " ").trim() })}
                onUndo={() => patch({ undoField: key })}
              />
            );
          })}
        </div>
      ) : null}

      {/* Phase 3.5: Collapsible appendix section */}
      {hasAppendix ? (
        <div className="mt-2 border-t border-slate-100 pt-2">
          <button
            className="flex items-center gap-1 text-[11px] font-medium text-slate-500 hover:text-slate-700"
            onClick={() => setAppendixOpen((v) => !v)}
            aria-expanded={appendixOpen}
            data-testid={`appendix-toggle-${chunk.id}`}
          >
            <span className={`inline-block transition-transform ${appendixOpen ? "rotate-90" : ""}`}>
              ▶
            </span>
            Appendix autofill
            <span className="rounded bg-slate-100 px-1 py-[1px] text-[9px] uppercase tracking-wide text-slate-500">
              {chunk.appendixLevel ?? "—"}
            </span>
          </button>
          {appendixOpen ? (
            <div className="mt-1 space-y-1 text-xs text-slate-600" data-testid={`appendix-body-${chunk.id}`}>
              {chunk.appendixResources ? (
                <div>
                  <span className="font-semibold text-slate-700">Resources: </span>
                  <span>{chunk.appendixResources}</span>
                </div>
              ) : null}
              {chunk.appendixAssessment ? (
                <div>
                  <span className="font-semibold text-slate-700">Assessment: </span>
                  <span>{chunk.appendixAssessment}</span>
                </div>
              ) : null}
              {chunk.appendixSource ? (
                <div className="text-[10px] text-slate-400">
                  Source: {chunk.appendixSource}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function StrandSection({
  group,
  jobId,
  onJob,
  onError,
  showOnlyNeedsReview,
  highlightChunkIds,
  saving,
  setSaving,
  forceOpen,
}: {
  group: StrandGroup;
  jobId: string;
  onJob: (job: ParseJob) => void;
  onError: (msg: string) => void;
  showOnlyNeedsReview: boolean;
  highlightChunkIds: string[];
  saving: boolean;
  setSaving: (v: boolean) => void;
  forceOpen: boolean;
}) {
  const [open, setOpen] = useState(true);
  const isOpen = forceOpen || open;

  const visible = showOnlyNeedsReview
    ? group.chunks.filter((c) => c.needsReview || highlightChunkIds.includes(c.id))
    : group.chunks;
  if (visible.length === 0) return null;

  const pending = group.chunks.filter((c) => c.needsReview).length;

  const approveStrand = async () => {
    setSaving(true);
    try {
      onJob(await api.approveStrand(jobId, group.strandCode, group.strand));
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 px-4 py-3 hover:bg-slate-50">
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex min-w-0 flex-1 items-center gap-3 text-left"
          aria-expanded={isOpen}
          disabled={forceOpen}
        >
          {!forceOpen ? (
            <span className={`inline-block text-slate-400 transition-transform ${isOpen ? "rotate-90" : ""}`}>
              ▶
            </span>
          ) : (
            <span className="text-slate-400" aria-hidden>
              ▾
            </span>
          )}
          <span className="flex min-w-0 flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-slate-500">{group.strandCode ?? "—"}</span>
            <span className="truncate font-semibold text-slate-900">{group.strand}</span>
            <Badge tone={group.strandUnresolved ? "red" : "slate"}>
              {group.chunkCount} {group.chunkCount === 1 ? "Sub-Strand" : "Sub-Strands"}
            </Badge>
            {pending > 0 ? <Badge tone="amber">{pending} to review</Badge> : <Badge tone="green">all reviewed</Badge>}
          </span>
        </button>
        <button
          className="btn-ghost shrink-0 text-xs"
          onClick={approveStrand}
          disabled={saving || pending === 0}
          title="Approve every sub-strand under this strand"
        >
          ✓ Approve Strand
        </button>
      </div>

      {isOpen ? (
        <div className="space-y-3 border-t border-slate-100 bg-slate-50/60 p-3">
          {visible.map((c) => (
            <SubStrandCard
              key={c.id}
              chunk={c}
              jobId={jobId}
              onJob={onJob}
              onError={onError}
              highlighted={highlightChunkIds.includes(c.id)}
              saving={saving}
              setSaving={setSaving}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

export default function UploadAndReview({
  job,
  setJob,
  fromLibrary = false,
  highlightChunkIds = [],
  onSavedToLibrary,
  onError,
}: Props) {
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsOnly, setNeedsOnly] = useState(!highlightChunkIds.length);
  const [saveWithGaps, setSaveWithGaps] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  // Opening a document from search/library must reveal it: an approved document has
  // nothing "needing review", so the default filter would render an empty tree.
  useEffect(() => {
    setNeedsOnly(highlightChunkIds.length === 0);
  }, [job?.id, highlightChunkIds.length]);

  const reportError = (msg: string) => {
    setError(msg);
    onError?.(msg);
  };

  const tree = job?.tree ?? [];
  const s = job?.reviewSummary;
  const autoApproved = s ? s.approved : 0;
  const needsReview = s ? s.needsReview : 0;
  const corrected = s ? s.corrected : 0;
  const canSave = Boolean(job) && ((s?.readyToSave ?? false) || saveWithGaps);

  const autoApproveCount = useMemo(() => {
    if (!job) return 0;
    return job.chunks.filter((c) => c.confidence >= 0.9 && c.missingFields.length === 0 && c.needsReview)
      .length;
  }, [job]);

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      reportError("Please choose a PDF curriculum design.");
      return;
    }
    setBusy(true);
    setError(null);
    setJob(null);
    try {
      setJob(await api.parsePdf(file));
    } catch (e) {
      reportError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const approveAll = async () => {
    if (!job) return;
    setSaving(true);
    setError(null);
    try {
      setJob(await api.approveAll(job.id, 0.9));
    } catch (e) {
      reportError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const saveToLibrary = async () => {
    if (!job) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await api.saveToLibrary(job.id, saveWithGaps);
      setJob(saved);
      onSavedToLibrary?.(saved);
    } catch (e) {
      reportError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Upload */}
      {!fromLibrary ? (
        <section className="card p-4">
          <div className="flex flex-wrap items-center gap-3">
            <input
              ref={fileRef}
              type="file"
              accept="application/pdf"
              className="hidden"
              data-testid="pdf-input"
              onChange={(e) => onFile(e.target.files?.[0])}
            />
            <button className="btn-primary" onClick={() => fileRef.current?.click()} disabled={busy}>
              {busy ? "Parsing…" : "Upload curriculum design (PDF)"}
            </button>
            {job ? (
              <div className="flex flex-wrap items-center gap-2 text-sm text-slate-600">
                <span className="font-medium text-slate-800">{job.fileName}</span>
                <Badge tone="slate">{job.grade}</Badge>
                <Badge tone="slate">{job.subject}</Badge>
              </div>
            ) : (
              <span className="text-sm text-slate-500">
                Grade 1–9 KICD curriculum designs. Nothing leaves your machine.
              </span>
            )}
          </div>
        </section>
      ) : null}

      {error ? (
        <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700 ring-1 ring-rose-200">
          {error}
        </p>
      ) : null}

      {/* Detected archetype + counts */}
      {job ? (
        <section className="card space-y-3 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-slate-700">Detected:</span>
            <span className="badge bg-emerald-700 text-white" data-testid="archetype-badge">
              Archetype {job.archetypeLabel ?? job.archetype ?? "Unknown"}
            </span>
            {job.archetypeConfidence != null ? <ConfidenceBadge value={job.archetypeConfidence} /> : null}
            <Badge tone="slate">{job.chunkCount} sub-strands</Badge>
            {job.parseMeta?.rubricRowsSkipped ? (
              <Badge tone="slate">{job.parseMeta.rubricRowsSkipped} rubric rows skipped</Badge>
            ) : null}
            {job.parseMeta?.strandsRecovered ? (
              <Badge tone="amber">{job.parseMeta.strandsRecovered} strand(s) recovered — verify</Badge>
            ) : null}
            {job.parseMeta?.experiencesRecovered ? (
              <Badge tone="amber">{job.parseMeta.experiencesRecovered} experience list(s) recovered — verify</Badge>
            ) : null}
          </div>

          {/* Counts line required by the spec */}
          <div className="flex flex-wrap items-center gap-2 text-sm" data-testid="counts-line">
            <Badge tone="green">Auto-approved: {autoApproved}</Badge>
            <span className="text-slate-300">|</span>
            <Badge tone={needsReview ? "amber" : "green"}>Needs Review: {needsReview}</Badge>
            <span className="text-slate-300">|</span>
            <Badge tone="blue">Corrected: {corrected}</Badge>
          </div>

          {/* Bulk + filter toolbar */}
          <div className="flex flex-wrap items-center gap-2">
            <button
              className="btn-primary"
              onClick={approveAll}
              disabled={saving || autoApproveCount === 0}
              data-testid="approve-all"
            >
              ✓ Approve All (
              {s ? `${s.approved + autoApproveCount}/${s.total}` : "0/0"} ready)
            </button>

            <div className="ml-auto inline-flex overflow-hidden rounded-md border border-slate-300 text-xs">
              <button
                className={`px-3 py-1.5 ${needsOnly ? "bg-emerald-700 text-white" : "bg-white text-slate-700"}`}
                onClick={() => setNeedsOnly(true)}
                data-testid="filter-needs"
              >
                Show Needs Review Only
              </button>
              <button
                className={`px-3 py-1.5 ${!needsOnly ? "bg-emerald-700 text-white" : "bg-white text-slate-700"}`}
                onClick={() => setNeedsOnly(false)}
                data-testid="filter-all"
              >
                Show All
              </button>
            </div>
          </div>
        </section>
      ) : null}

      {/* Tree */}
      {job && tree.length > 0 ? (
        <section className="space-y-3" data-testid="strand-tree">
          {tree.map((g) => (
            <StrandSection
              key={`${g.strandCode}-${g.strand}`}
              group={g}
              jobId={job.id}
              onJob={setJob}
              onError={reportError}
              showOnlyNeedsReview={needsOnly}
              highlightChunkIds={highlightChunkIds}
              saving={saving}
              setSaving={setSaving}
              forceOpen={highlightChunkIds.length > 0}
            />
          ))}
          {needsOnly && needsReview === 0 ? (
            <p className="card p-6 text-center text-sm text-slate-500">
              Nothing left to review. Switch to “Show All” to see everything.
            </p>
          ) : null}
        </section>
      ) : null}

      {/* Save to library */}
      {job ? (
        <section className="card space-y-3 p-4">
          <div className="flex flex-wrap items-center gap-3">
            <button
              className="btn-primary"
              onClick={saveToLibrary}
              disabled={!canSave || saving}
              data-testid="save-library"
            >
              {job.status === "Approved" ? "Saved to My Library ✓" : "Approve & Save to My Library"}
            </button>
            <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                className="h-4 w-4 accent-emerald-700"
                checked={saveWithGaps}
                onChange={(e) => setSaveWithGaps(e.target.checked)}
                data-testid="save-with-gaps"
              />
              Save with gaps - I will fix later
            </label>
          </div>
          <p className="text-xs text-slate-500">
            {job.status === "Approved"
              ? "This document is in your library."
              : s?.readyToSave
                ? "Everything is reviewed — ready to save."
                : `${needsReview} sub-strand(s) still need review. Approve them, or tick “Save with gaps”.`}
          </p>
        </section>
      ) : null}

      {job && tree.length === 0 ? (
        <section className="card p-6 text-center text-sm text-slate-500">
          No sub-strands found in this PDF. The layout may not be a KICD curriculum design.
        </section>
      ) : null}
    </div>
  );
}
