import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { LibraryCard, LibraryList, ParseJob, SearchHit, SearchResponse } from "../types";
import { Badge, ConfirmDialog } from "./ui";

type Props = {
  onOpen: (job: ParseJob, highlightChunkIds: string[]) => void;
  /** Phase 7: open the Term Pack modal for an approved design card. */
  onExportTermPack?: (documentId: string) => void;
  onToast: (msg: string) => void;
  onError: (msg: string) => void;
  /** Bumped by the parent after a save so the library refreshes. */
  refreshKey?: number;
  /** Deep link from a plan citation: open this document and scroll to the chunk. */
  openDocumentId?: string | null;
  onOpenedDocument?: () => void;
};

const STATUS_TONE: Record<string, "green" | "amber" | "slate"> = {
  Approved: "green",
  NeedsReview: "amber",
  Parsed: "amber",
};

function ArchetypeBadge({ card }: { card: LibraryCard }) {
  const letter = (card.archetype || "?").charAt(0);
  return (
    <span className="badge bg-emerald-800 text-white" title={card.archetypeLabel}>
      {letter}
    </span>
  );
}

function MaterialCard({
  card,
  onView,
  onReparse,
  onDelete,
  onExport,
  onExportTermPack,
  busy,
}: {
  card: LibraryCard;
  onView: () => void;
  onReparse: () => void;
  onDelete: () => void;
  onExport: () => void;
  onExportTermPack?: () => void;
  busy: boolean;
}) {
  const date = card.createdAt ? new Date(card.createdAt.replace(" ", "T") + "Z") : null;
  return (
    <div className="card flex flex-col gap-3 p-4" data-testid={`doc-card-${card.id}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-slate-900">{card.subject}</span>
            <Badge tone="slate">{card.grade}</Badge>
            <ArchetypeBadge card={card} />
          </div>
          <p className="mt-1 truncate text-xs text-slate-500" title={card.fileName}>
            {card.fileName}
          </p>
        </div>
        <Badge tone={STATUS_TONE[card.status] ?? "slate"} data-testid="status-badge">
          {card.status === "NeedsReview" ? "Needs review" : card.status}
        </Badge>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
        <span>
          <span className="font-semibold text-slate-800">{card.strandCount}</span> strands
        </span>
        <span aria-hidden>·</span>
        {card.themeCount ? (
          <>
            <span>
              <span className="font-semibold text-slate-800">{card.themeCount}</span> theme(s)
            </span>
            <span aria-hidden>·</span>
          </>
        ) : null}
        <span>
          <span className="font-semibold text-slate-800">{card.subStrandCount}</span> sub-strands
        </span>
        {date ? (
          <>
            <span aria-hidden>·</span>
            <span>{date.toLocaleDateString()}</span>
          </>
        ) : null}
        {card.savedWithGaps ? <Badge tone="amber">saved with gaps</Badge> : null}
      </div>

      {/* Phase 3: vetting. A document only reaches the Studio Library when this is 9/9. */}
      <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2" data-testid="vetting-row">
        <div className="flex flex-wrap items-center gap-2">
          {card.allVetted ? (
            <Badge tone="green" data-testid="vetting-badge">
              Vetting: {card.vettedCount}/{card.vettingTotal} Vetted ✓
            </Badge>
          ) : (
            <Badge tone="amber" data-testid="vetting-badge">
              Vetting: {card.vettedCount}/{card.vettingTotal} Vetted
            </Badge>
          )}
          {!card.allVetted && card.vettingProblems?.length ? (
            <span className="text-xs text-slate-600" data-testid="vetting-detail">
              Missing core:{" "}
              {card.vettingProblems
                .map((p) => `${p.needs.join(" + ")} (${p.subStrandCode ?? p.subStrand})`)
                .join(", ")}
            </span>
          ) : null}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button className="btn-primary" onClick={onView} data-testid="view-btn">
          View
        </button>
        <button className="btn-ghost" onClick={onReparse} disabled={busy} data-testid="reparse-btn">
          {busy ? "Re-parsing…" : "Re-parse"}
        </button>
        <a className="btn-ghost" href={api.pdfUrl(card.id)} target="_blank" rel="noreferrer">
          PDF
        </a>
        <button className="btn-ghost" onClick={onExport} data-testid="export-btn">
          Export JSON
        </button>
        {onExportTermPack && card.allVetted ? (
          <button className="btn-primary px-2 py-1 text-xs" onClick={onExportTermPack} data-testid="card-export-term-pack">
            📦 Export
          </button>
        ) : null}
        <button
          className="btn ml-auto border border-rose-200 bg-white text-rose-700 hover:bg-rose-50"
          onClick={onDelete}
          data-testid="delete-btn"
        >
          Delete
        </button>
      </div>
    </div>
  );
}

export default function Library({
  onOpen,
  onExportTermPack,
  onToast,
  onError,
  refreshKey = 0,
  openDocumentId = null,
  onOpenedDocument,
}: Props) {
  const [data, setData] = useState<LibraryList | null>(null);
  const [query, setQuery] = useState("");
  const [grade, setGrade] = useState("");
  const [subject, setSubject] = useState("");
  const [status, setStatus] = useState("");
  const [vettedOnly, setVettedOnly] = useState(false);
  const [search, setSearch] = useState<SearchResponse | null>(null);
  const [searching, setSearching] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<LibraryCard | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      setData(await api.library());
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  // A plan citation asks for a specific document + chunk: open it directly.
  useEffect(() => {
    if (!openDocumentId) return;
    let alive = true;
    api
      .libraryDoc(openDocumentId)
      .then((job) => {
        if (!alive) return;
        onOpen(job, []);
        onOpenedDocument?.();
      })
      .catch((e) => onError((e as Error).message));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openDocumentId]);

  // Debounced search
  useEffect(() => {
    const term = query.trim();
    if (!term) {
      setSearch(null);
      return;
    }
    let alive = true;
    setSearching(true);
    const t = setTimeout(async () => {
      try {
        const res = await api.search(term, { grade, subject, status });
        if (alive) setSearch(res);
      } catch (e) {
        if (alive) onError((e as Error).message);
      } finally {
        if (alive) setSearching(false);
      }
    }, 220);
    return () => {
      alive = false;
      clearTimeout(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, grade, subject, status]);

  const openDoc = async (id: string, highlight: string[] = []) => {
    try {
      onOpen(await api.libraryDoc(id), highlight);
    } catch (e) {
      onError((e as Error).message);
    }
  };

  const reparse = async (card: LibraryCard) => {
    setBusyId(card.id);
    try {
      const job = await api.reparse(card.id);
      onToast(`Re-parsed ${card.subject} (${card.grade}) — ${job.chunkCount} sub-strands`);
      await load();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusyId(null);
    }
  };

  const doDelete = async () => {
    if (!confirm) return;
    const card = confirm;
    setConfirm(null);
    try {
      await api.deleteDoc(card.id);
      onToast("Deleted from My Library");
      await load();
      if (search) setSearch(await api.search(query, { grade, subject, status }));
    } catch (e) {
      onError((e as Error).message);
    }
  };

  const exportJson = async (card: LibraryCard) => {
    try {
      const res = await fetch(api.exportUrl(card.id));
      if (!res.ok) throw new Error(`Export failed (${res.status})`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${card.subject}-${card.grade}.json`.replace(/\s+/g, "-");
      a.click();
      URL.revokeObjectURL(url);
      onToast("Exported JSON");
    } catch (e) {
      onError((e as Error).message);
    }
  };

  const groups = useMemo(() => {
    if (!data) return { mine: [], review: [], studio: [] };
    const all = data.documents ?? [];
    const pick = (list: LibraryCard[]) =>
      vettedOnly ? list.filter((d) => d.allVetted) : list;

    let mine = data.myMaterials;
    let review = data.needsReview;
    if (status === "Approved") review = [];
    else if (status === "NeedsReview") mine = [];

    // [Show Vetted Only] narrows every section to fully-vetted documents.
    const studio = (data.studioLibrary ?? []).filter((d) => all.length === 0 || d.allVetted);
    return { mine: pick(mine), review: pick(review), studio };
  }, [data, status, vettedOnly]);

  const hitDocuments = useMemo(() => {
    if (!search) return [];
    return search.documents;
  }, [search]);

  return (
    <div className="space-y-5">
      <div className="flex justify-end">
        <a href="#/dashboard" className="btn-ghost px-2.5 py-1.5 text-xs"
           data-testid="library-dashboard-link">
          📊 Coverage Dashboard
        </a>
      </div>
      {/* Search */}
      <section className="card p-4">
        <input
          className="input w-full text-base"
          placeholder="Search outcomes, strands, sub-strands... e.g. Whole Numbers"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          data-testid="library-search"
        />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <select className="input" value={grade} onChange={(e) => setGrade(e.target.value)} data-testid="filter-grade">
            <option value="">All grades</option>
            {(data?.facets.grades.length
              ? data.facets.grades
              : ["Grade 1", "Grade 2", "Grade 3", "Grade 4", "Grade 5", "Grade 6", "Grade 7", "Grade 8", "Grade 9"]
            ).map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </select>
          <select
            className="input"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            data-testid="filter-subject"
          >
            <option value="">All subjects</option>
            {(data?.facets.subjects ?? []).map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          <select className="input" value={status} onChange={(e) => setStatus(e.target.value)} data-testid="filter-status">
            <option value="">All statuses</option>
            <option value="Approved">Approved</option>
            <option value="NeedsReview">Needs review</option>
          </select>
          <label
            className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-1.5 text-xs ${
              vettedOnly
                ? "border-emerald-300 bg-emerald-50 text-emerald-800"
                : "border-slate-200 bg-white text-slate-600"
            }`}
            data-testid="filter-vetted"
          >
            <input
              type="checkbox"
              checked={vettedOnly}
              onChange={(e) => setVettedOnly(e.target.checked)}
              className="h-3.5 w-3.5 accent-emerald-600"
            />
            Show Vetted Only
          </label>
          {query ? (
            <button className="btn-ghost" onClick={() => setQuery("")}>
              Clear
            </button>
          ) : null}
          <span className="ml-auto text-xs text-slate-500">
            {searching
              ? "Searching…"
              : search
                ? `${search.total} chunk match${search.total === 1 ? "" : "es"} in ${search.documents.length} document(s)`
                : `${data?.counts.myMaterials ?? 0} in My Materials · ${data?.counts.needsReview ?? 0} needs review · ${data?.counts.studioLibrary ?? 0} vetted`}
          </span>
        </div>
      </section>

      {/* Search results */}
      {search ? (
        <section className="card overflow-hidden">
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5">
            <h2 className="text-sm font-semibold text-slate-800">Search results</h2>
            <span className="text-xs text-slate-500">“{search.query}”</span>
          </div>
          {search.results.length === 0 ? (
            <p className="p-6 text-center text-sm text-slate-500">
              No matches. Try a strand, sub-strand, outcome or question.
            </p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {search.results.map((h: SearchHit) => (
                <li key={`${h.documentId}-${h.chunkId}`} className="p-3 hover:bg-slate-50">
                  <button
                    className="w-full text-left"
                    onClick={() => openDoc(h.documentId, [h.chunkId])}
                    data-testid="search-hit"
                  >
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <Badge tone="slate">{h.subject}</Badge>
                      <Badge tone="slate">{h.grade}</Badge>
                      <span className="font-mono text-slate-500">{h.subStrandCode}</span>
                      <span className="font-medium text-slate-900">{h.subStrand}</span>
                      {h.pageNumber ? (
                        <span className="text-slate-500" data-testid="hit-page">
                          page {h.pageNumber}
                        </span>
                      ) : null}
                    </div>
                    <p className="mt-1 line-clamp-2 text-xs text-slate-600">{h.snippet}</p>
                    {h.matchedOn.length > 1 ? (
                      <p className="mt-0.5 text-[11px] text-slate-400">+{h.matchedOn.length - 1} more match(es)</p>
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {hitDocuments.length > 0 ? (
            <div className="border-t border-slate-100 px-4 py-2 text-[11px] text-slate-500">
              In: {hitDocuments.map((d) => `${d.subject} ${d.grade}`).join(" · ")}
            </div>
          ) : null}
        </section>
      ) : null}

      {/* My Materials */}
      {!search ? (
        <>
          <section data-testid="my-materials">
            <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-800">
              My Materials
              <Badge tone="slate">{groups.mine.length}</Badge>
            </h2>
            {loading ? (
              <p className="card p-6 text-center text-sm text-slate-500">Loading…</p>
            ) : groups.mine.length === 0 ? (
              <p className="card p-6 text-center text-sm text-slate-500">
                No approved materials yet. Upload a curriculum design, review it, then choose
                “Approve & Save to My Library”.
              </p>
            ) : (
              <div className="grid gap-3 md:grid-cols-2">
                {groups.mine.map((card) => (
                  <MaterialCard
                    key={card.id}
                    card={card}
                    busy={busyId === card.id}
                    onView={() => openDoc(card.id)}
                    onReparse={() => reparse(card)}
                    onDelete={() => setConfirm(card)}
                    onExport={() => exportJson(card)}
                    onExportTermPack={onExportTermPack ? () => onExportTermPack(card.id) : undefined}
                  />
                ))}
              </div>
            )}
          </section>

          {/* Needs review (in-progress) */}
          {groups.review.length > 0 ? (
            <section data-testid="needs-review">
              <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-800">
                Still to review
                <Badge tone="amber">{groups.review.length}</Badge>
              </h2>
              <div className="grid gap-3 md:grid-cols-2">
                {groups.review.map((card) => (
                  <MaterialCard
                    key={card.id}
                    card={card}
                    busy={busyId === card.id}
                    onView={() => openDoc(card.id)}
                    onReparse={() => reparse(card)}
                    onDelete={() => setConfirm(card)}
                    onExport={() => exportJson(card)}
                    onExportTermPack={onExportTermPack ? () => onExportTermPack(card.id) : undefined}
                  />
                ))}
              </div>
            </section>
          ) : null}

          {/* Studio Library: ONLY fully-vetted documents */}
          <section data-testid="studio-library">
            <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-800">
              Studio Library
              <Badge tone="green">{groups.studio.length}</Badge>
              <span className="text-xs font-normal text-slate-500">
                every sub-strand vetted — safe to plan from
              </span>
            </h2>
            {groups.studio.length === 0 ? (
              <div className="card border-dashed p-6 text-center" data-testid="studio-empty">
                <p className="text-sm font-medium text-slate-700">
                  No fully-vetted material yet
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  A document moves here once every sub-strand has outcomes, experiences and
                  Key Inquiry Questions. “Save with gaps” documents stay in My Materials.
                </p>
              </div>
            ) : (
              <div className="grid gap-3 md:grid-cols-2">
                {groups.studio.map((card) => (
                  <MaterialCard
                    key={card.id}
                    card={card}
                    busy={busyId === card.id}
                    onView={() => openDoc(card.id)}
                    onReparse={() => reparse(card)}
                    onDelete={() => setConfirm(card)}
                    onExport={() => exportJson(card)}
                    onExportTermPack={onExportTermPack ? () => onExportTermPack(card.id) : undefined}
                  />
                ))}
              </div>
            )}
          </section>
        </>
      ) : null}

      {confirm ? (
        <ConfirmDialog
          title={`Delete ${confirm.subject} (${confirm.grade})?`}
          body="This removes the document, its sub-strands and the stored PDF. Other documents are untouched. This cannot be undone."
          confirmLabel="Delete document"
          onConfirm={doDelete}
          onCancel={() => setConfirm(null)}
        />
      ) : null}
    </div>
  );
}
