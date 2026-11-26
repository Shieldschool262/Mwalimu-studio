import { useCallback, useEffect, useMemo, useState } from "react";
import CreateDocument from "./components/CreateDocument";
import Dashboard from "./components/Dashboard";
import ExportModal from "./components/ExportModal";
import LessonNotesEditor from "./components/LessonNotesEditor";
import LessonNotesList from "./components/LessonNotesList";
import LessonPlanView from "./components/LessonPlanView";
import LessonPlansList from "./components/LessonPlansList";
import Library from "./components/Library";
import PlanView from "./components/PlanView";
import RecordOfWork from "./components/RecordOfWork";
import SchemeList from "./components/SchemeList";
import Settings from "./components/Settings";
import UploadAndReview from "./components/UploadAndReview";
import { Toast } from "./components/ui";
import Auth from "./components/Auth";
import MySpace from "./components/MySpace";
import MyLearners from "./components/MyLearners";
import type { LearnersView } from "./components/MyLearners";
import { api } from "./api";
import type { AssessTarget, AuthUser, HealthInfo, ParseJob, PlanDocument } from "./types";

type Tab = "review" | "library" | "plan" | "dashboard" | "learners";
/** The nine fixed workflow sections, in the order they must always appear. */
type Section =
  | "review" | "library" | "scheme" | "lesson-plans" | "lesson-notes"
  | "row" | "dashboard" | "learners" | "my-space";

const AUTH_HASHES = ["#/login", "#/signup", "#/forgot-password", "#/reset-password"];

/** Minimal hash router: #/review, #/library, #/plan, #/dashboard, #/my-space. */
function readTab(): Tab {
  const h = window.location.hash;
  if (h.startsWith("#/dashboard")) return "dashboard";
  if (h.startsWith("#/library")) return "library";
  if (h.startsWith("#/plan")) return "plan";
  if (h.startsWith("#/my-learners")) return "learners";
  return "review";
}

function readLearnersView(): LearnersView {
  const h = window.location.hash;
  if (h.startsWith("#/my-learners/progress")) return "progress";
  if (h.startsWith("#/my-learners/iep")) return "iep";
  return "list";
}

export default function App() {
  // Phase 9: no guest mode. The whole workspace is gated by this user.
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [mySpaceOpen, setMySpaceOpen] = useState(() => window.location.hash.startsWith("#/my-space"));
  /** Phase 10: My Learners sub-view + optional assessment launched from Lesson Plan / ROW. */
  const [learnersView, setLearnersView] = useState<LearnersView>(readLearnersView);
  const [assessTarget, setAssessTarget] = useState<AssessTarget | null>(null);
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>(readTab);
  const [job, setJob] = useState<ParseJob | null>(null);
  const [highlight, setHighlight] = useState<string[]>([]);
  const [fromLibrary, setFromLibrary] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [libraryKey, setLibraryKey] = useState(0);
  const [plan, setPlan] = useState<PlanDocument | null>(null);
  /** True while the create-scheme wizard (inside the Scheme tab) is open. */
  const [planCreating, setPlanCreating] = useState(false);
  /** True while the "My Lesson Plans" list is showing. */
  const [lessonListOpen, setLessonListOpen] = useState(false);
  /** True while the "My Lesson Notes" list is showing. */
  const [notesListOpen, setNotesListOpen] = useState(false);
  /** Phase 4: open KICD lesson plan (from a scheme row). */
  const [lessonId, setLessonId] = useState<string | null>(null);
  /** Phase 5: open learner-facing Lesson Notes. */
  const [notesId, setNotesId] = useState<string | null>(null);
  /** Document to open in the Library after a citation jump. */
  const [pendingDocId, setPendingDocId] = useState<string | null>(null);
  /** Breadcrumb tail supplied by whichever screen is open. */
  const [crumb, setCrumb] = useState<string[]>([]);
  const [activeLeftNav, setActiveLeftNav] = useState("curriculum-matrix");
  /** Phase 6: AI + web search settings page. */
  const [settingsOpen, setSettingsOpen] = useState(false);
  /** Phase 6: Record of Work (scheme picker + per-scheme editor). */
  const [rowOpen, setRowOpen] = useState(false);
  const [rowPlanId, setRowPlanId] = useState<string | null>(null);
  const [rowFocus, setRowFocus] = useState<{ week: number; lesson: number } | null>(null);
  /** Phase 7: Term Pack export modal (planId from views, documentId from Library cards). */
  const [exportOpen, setExportOpen] = useState(false);
  const [exportPlanId, setExportPlanId] = useState<string | null>(null);
  const [exportDocumentId, setExportDocumentId] = useState<string | null>(null);

  /** Navigation-only state: compact breakpoint + workflow prerequisites. */
  const [isCompact, setIsCompact] = useState(() => window.innerWidth < 1100);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [flow, setFlow] = useState({ schemes: 0, plans: 0, notes: 0, row: 0 });
  const [mySpaceSection, setMySpaceSection] = useState("my-profile");

  useEffect(() => {
    const onResize = () => setIsCompact(window.innerWidth < 1100);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    let alive = true;
    if (AUTH_HASHES.some((h) => window.location.hash.startsWith(h))) {
      setAuthReady(true);
      return () => { alive = false; };
    }
    api.me()
      .then((u) => {
        if (!alive) return;
        setUser(u);
        setAuthReady(true);
      })
      .catch(() => {
        if (!alive) return;
        setUser(null);
        setAuthReady(true);
        const next = window.location.hash.replace(/^#/, "") || "/review";
        window.location.hash = `#/login?next=${encodeURIComponent(next)}`;
      });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!authReady || user) return;
    const onProtectedHash = () => {
      const h = window.location.hash;
      if (!h || AUTH_HASHES.some((a) => h.startsWith(a))) return;
      if (["#/dashboard", "#/library", "#/plan", "#/review", "#/my-space", "#/row",
           "#/notes", "#/export", "#/my-learners"].some((p) => h.startsWith(p))) {
        const next = h.replace(/^#/, "");
        window.location.hash = `#/login?next=${encodeURIComponent(next)}`;
      }
    };
    onProtectedHash();
    window.addEventListener("hashchange", onProtectedHash);
    return () => window.removeEventListener("hashchange", onProtectedHash);
  }, [authReady, user]);

  const logout = useCallback(async () => {
    try { await api.logout(); } catch { /* clear locally either way */ }
    // Drop any cached workspace state before the next teacher signs in.
    Object.keys(localStorage).filter((k) => k.startsWith("mwalimu")).forEach((k) => localStorage.removeItem(k));
    setUser(null);
    setMySpaceOpen(false);
    window.location.hash = "#/login";
    window.location.reload();
  }, []);

  const signedIn = useCallback((u: AuthUser) => {
    setUser(u);
    setMySpaceOpen(false);
    setError(null);
  }, []);

  useEffect(() => {
    let alive = true;
    api
      .health()
      .then((h) => alive && setHealth(h))
      .catch((e: Error) => alive && setHealthError(e.message));
    return () => {
      alive = false;
    };
  }, []);

  // Workflow Next buttons are disabled from real prerequisites, never hidden.
  const refreshFlow = useCallback(() => {
    if (!user) return;
    api.navigationStatus().then(setFlow).catch(() => undefined);
  }, [user]);

  /** Keep workflow footer prerequisites current when a screen creates content. */
  const workflowToast = useCallback((msg: string) => {
    setToast(msg);
    if (/created|generated|saved|marked|restored|duplicated/i.test(msg)) void refreshFlow();
  }, [refreshFlow]);

  useEffect(() => {
    if (!user) return;
    void refreshFlow();
    window.addEventListener("mwalimu:workflow-change", refreshFlow);
    return () => window.removeEventListener("mwalimu:workflow-change", refreshFlow);
  }, [user, refreshFlow, libraryKey, plan, rowPlanId]);

  // Keep the tab in sync with browser back/forward, and normalise the bare
  // My Learners URL to its explicit Class Lists route.
  useEffect(() => {
    const onHash = () => {
      if (window.location.hash === "#/my-learners") {
        window.history.replaceState(null, "", "#/my-learners/class-lists");
        setTab("learners");
        setLearnersView("list");
        setMySpaceOpen(false);
        return;
      }
      setTab(readTab());
      setLearnersView(readLearnersView());
      setMySpaceOpen(window.location.hash.startsWith("#/my-space"));
    };
    onHash();
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const go = useCallback((next: Tab) => {
    window.location.hash =
      next === "library" ? "#/library"
        : next === "plan" ? "#/plan"
          : next === "dashboard" ? "#/dashboard"
            : next === "learners" ? "#/my-learners/class-lists" : "#/review";
    setTab(next);
  }, []);

  /** Phase 10: open a learner sub-view, and optionally an assessment grid. */
  const navigateLearners = useCallback((next: LearnersView) => {
    setLearnersView(next);
    window.location.hash = next === "list" ? "#/my-learners/class-lists"
      : next === "progress" ? "#/my-learners/progress" : "#/my-learners/iep";
    setTab("learners");
  }, []);

  const openAssessment = useCallback((target: AssessTarget) => {
    setAssessTarget(target);
    setTab("learners");
    setLearnersView("list");
    window.location.hash = "#/my-learners/class-lists";
  }, []);

  /** Open a source chunk in the Library (used by plan citation pills). */
  const openSourceChunk = useCallback(
    (documentId: string, chunkId: string) => {
      setHighlight([chunkId]);
      setPendingDocId(documentId);
      setFromLibrary(true);
      go("library");
      // Library needs to fetch then scroll; it reads the hash highlight.
      setTimeout(() => {
        document.getElementById(`chunk-${chunkId}`)?.scrollIntoView({
          behavior: "smooth",
          block: "center",
        });
      }, 400);
    },
    [go],
  );

  const openDoc = useCallback(
    (doc: ParseJob, highlightChunkIds: string[]) => {
      setJob(doc);
      setHighlight(highlightChunkIds);
      setFromLibrary(true);
      setCrumb([]);
      go("review");
      // Scroll to the matched chunk after render.
      if (highlightChunkIds.length) {
        setTimeout(() => {
          document.getElementById(`chunk-${highlightChunkIds[0]}`)?.scrollIntoView({
            behavior: "smooth",
            block: "center",
          });
        }, 250);
      }
    },
    [go],
  );

  const onSavedToLibrary = useCallback(
    (saved: ParseJob) => {
      setToast("Saved to My Library ✓");
      setFromLibrary(true);
      setJob(saved);
      setLibraryKey((k) => k + 1);
      setTimeout(() => go("library"), 350);
    },
    [go],
  );

  const openScheme = () => {
    setSettingsOpen(false);
    closeRowView();
    setJob(null);
    setHighlight([]);
    setFromLibrary(false);
    setLessonId(null);
    setNotesId(null);
    setPlanCreating(false);
    setLessonListOpen(false);
    setNotesListOpen(false);
    setCrumb([]);
    setActiveLeftNav("curriculum-matrix");
    go("plan");
  };

  const openLessonPlans = () => {
    setSettingsOpen(false);
    closeRowView();
    setJob(null);
    setHighlight([]);
    setFromLibrary(false);
    setPlan(null);
    setPlanCreating(false);
    setLessonId(null);
    setNotesId(null);
    setLessonListOpen(true);
    setNotesListOpen(false);
    setCrumb([]);
    setActiveLeftNav("lesson-plans");
    go("plan");
  };

  const openLessonNotes = () => {
    setSettingsOpen(false);
    closeRowView();
    setJob(null);
    setHighlight([]);
    setFromLibrary(false);
    setPlan(null);
    setPlanCreating(false);
    setLessonId(null);
    setNotesId(null);
    setLessonListOpen(false);
    setNotesListOpen(true);
    setCrumb([]);
    setActiveLeftNav("lesson-notes");
    go("plan");
  };

  const closeRowView = () => {
    setRowOpen(false);
    setRowPlanId(null);
    setRowFocus(null);
  };

  /** Phase 7: one export modal, reached from Scheme / Library / ROW. */
  const openExport = (planId?: string | null, documentId?: string | null) => {
    setExportPlanId(planId || null);
    setExportDocumentId(documentId || null);
    setExportOpen(true);
  };

  const openRecordOfWork = () => {
    setSettingsOpen(false);
    setJob(null);
    setHighlight([]);
    setFromLibrary(false);
    setPlan(null);
    setPlanCreating(false);
    setLessonId(null);
    setNotesId(null);
    setLessonListOpen(false);
    setNotesListOpen(false);
    setRowOpen(true);
    setRowPlanId(null);
    setRowFocus(null);
    setCrumb([]);
    setActiveLeftNav("record-of-work");
    go("plan");
  };

  /** Single entry point for every global nav item and every workflow Back/Next. */
  const openSection = (key: Section) => {
    void refreshFlow();
    setSettingsOpen(false);
    setMobileMenuOpen(false);
    setAssessTarget(null);
    switch (key) {
      case "review":
        setJob(null); setHighlight([]); setFromLibrary(false); setCrumb([]);
        setActiveLeftNav("curriculum-matrix"); go("review"); break;
      case "library":
        closeRowView(); setPlan(null); setLessonId(null); setNotesId(null);
        setLessonListOpen(false); setNotesListOpen(false); setCrumb([]);
        go("library"); break;
      case "scheme": openScheme(); break;
      case "lesson-plans": openLessonPlans(); break;
      case "lesson-notes": openLessonNotes(); break;
      case "row": openRecordOfWork(); break;
      case "dashboard":
        closeRowView(); setPlan(null); setLessonId(null); setNotesId(null);
        setMySpaceOpen(false); go("dashboard"); break;
      case "learners":
        setMySpaceOpen(false); navigateLearners("list"); break;
      case "my-space":
        setMySpaceOpen(true); setCrumb([]); window.location.hash = "#/my-space"; break;
    }
  };

  const openRowDoc = (planId: string, focus?: { week: number; lesson: number } | null) => {
    setSettingsOpen(false);
    setJob(null);
    setHighlight([]);
    setFromLibrary(false);
    setPlan(null);
    setPlanCreating(false);
    setLessonId(null);
    setNotesId(null);
    setLessonListOpen(false);
    setNotesListOpen(false);
    setRowOpen(true);
    setRowPlanId(planId);
    setRowFocus(focus ?? null);
    setCrumb([]);
    setActiveLeftNav("record-of-work");
    go("plan");
  };

  /** Phase 8: dashboard [View Scheme] reuses the existing Scheme view. */
  const viewSchemeFor = async (planId: string) => {
    try {
      const p = await api.plan(planId);
      openScheme();
      setPlan(p);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  /** [→ Mark as Taught] in a Lesson Plan: sets Status then opens the ROW editor. */
  const markTaught = async (schemeId: string, week: number, lesson: number) => {
    try {
      const doc = await api.rowMarkTaught(schemeId, week, lesson);
      openRowDoc(doc.planId, { week, lesson });
      setError(null);
      setToast(doc.message || `Week ${week} Lesson ${lesson} marked as Taught.`);
    } catch (e) {
      setError((e as Error).message);
    }
  };



  const crumbParts = useMemo(() => {
    if (settingsOpen) return ["Parser & Review", "AI & Web Search"];
    if (mySpaceOpen) return ["My Space"];
    if (tab === "learners") return [
      "My Learners",
      learnersView === "list" ? "Class Lists" : learnersView === "progress" ? "Progress" : "IEP",
    ];
    if (tab === "dashboard") return ["My Coverage Dashboard"];
    if (tab === "review") return ["Parser & Review"];
    if (tab === "library") return ["Studio Library"];
    if (rowOpen && rowPlanId) return ["Record of Work", "Term Editor"];
    if (rowOpen) return ["Record of Work"];
    if (notesListOpen) return ["Lesson Notes"];
    if (notesId) return ["Lesson Notes", ...crumb];
    if (lessonListOpen) return ["Lesson Plans"];
    if (lessonId) return ["Lesson Plans", ...crumb];
    return ["Scheme of Work", ...crumb];
  }, [tab, notesId, lessonId, notesListOpen, lessonListOpen, settingsOpen, rowOpen, rowPlanId,
      crumb, learnersView, mySpaceOpen]);

  /* Single source of truth for navigation. Top nav is fixed; side nav is strictly
     contextual and disappears for sections with no sub-pages. */
  const section: Section = settingsOpen ? "review"
    : mySpaceOpen ? "my-space"
      : tab === "plan"
        ? (rowOpen ? "row"
          : (notesId || notesListOpen) ? "lesson-notes"
            : (lessonId || lessonListOpen) ? "lesson-plans" : "scheme")
        : tab as Section;

  const topItems: { key: Section; label: string; testId: string }[] = [
    { key: "review", label: "Parser & Review", testId: "nav-review" },
    { key: "library", label: "Studio Library", testId: "nav-library" },
    { key: "scheme", label: "Scheme of Work", testId: "nav-plan" },
    { key: "lesson-plans", label: "Lesson Plans", testId: "nav-lesson-plans" },
    { key: "lesson-notes", label: "Lesson Notes", testId: "nav-lesson-notes" },
    { key: "row", label: "Record of Work", testId: "nav-record-of-work" },
    { key: "dashboard", label: "My Coverage Dashboard", testId: "nav-dashboard" },
    { key: "learners", label: "My Learners", testId: "nav-learners" },
    { key: "my-space", label: `My Space • ${user?.name ?? "My Space"}`, testId: "top-my-space" },
  ];

  /** Exact wording required by the workflow footer, independent of top-nav labels. */
  const footerBackLabel: Record<Section, string | null> = {
    review: null,
    library: "Parser",
    scheme: "Library",
    "lesson-plans": "Scheme",
    "lesson-notes": "Lesson Plans",
    row: "Lesson Notes",
    dashboard: "Record of Work",
    learners: "Dashboard",
    "my-space": "My Learners",
  };
  const footerNextLabel: Record<Section, string | null> = {
    review: "Studio Library",
    library: "Scheme of Work",
    scheme: "Lesson Plans",
    "lesson-plans": "Lesson Notes",
    "lesson-notes": "Record of Work",
    row: "My Coverage Dashboard",
    dashboard: "My Learners",
    learners: "My Space",
    "my-space": null,
  };

  type SideItem = { key: string; label: string; action: () => void };
  const sideItems: SideItem[] | null =
    section === "review" ? [
      { key: "curriculum-matrix", label: "Curriculum Matrix", action: () => { setActiveLeftNav("curriculum-matrix"); openSection("review"); } },
      { key: "strands", label: "Strands & Sub-strands", action: () => { setActiveLeftNav("strands"); openSection("review"); } },
      { key: "rubrics", label: "Competency Rubrics", action: () => { setActiveLeftNav("rubrics"); openSection("review"); } },
      { key: "media", label: "Evidence & Media", action: () => { setSettingsOpen(false); setMobileMenuOpen(false); setActiveLeftNav("media"); go("review"); } },
      { key: "kicd", label: "KICD Alignment", action: () => { setActiveLeftNav("kicd"); openSection("review"); } },
      { key: "vetting", label: "Vetting Guidelines", action: () => { setActiveLeftNav("vetting"); openSection("review"); } },
      { key: "settings", label: "AI & Web Search", action: () => { setActiveLeftNav("settings"); setSettingsOpen(true); setMobileMenuOpen(false); go("review"); } },
    ]
      : section === "learners" ? [
        { key: "class-lists", label: "Class Lists", action: () => navigateLearners("list") },
        { key: "progress", label: "Progress", action: () => navigateLearners("progress") },
        { key: "iep", label: "IEP", action: () => navigateLearners("iep") },
      ]
        : section === "my-space" ? [
          { key: "my-profile", label: "My Profile", action: () => { setMySpaceSection("my-profile"); document.getElementById("my-profile")?.scrollIntoView({ behavior: "smooth" }); } },
          { key: "my-preferences", label: "My Preferences", action: () => { setMySpaceSection("my-preferences"); document.getElementById("my-preferences")?.scrollIntoView({ behavior: "smooth" }); } },
          { key: "my-data", label: "My Data", action: () => { setMySpaceSection("my-data"); document.getElementById("my-data")?.scrollIntoView({ behavior: "smooth" }); } },
          { key: "danger-zone", label: "Danger Zone", action: () => { setMySpaceSection("danger-zone"); document.getElementById("danger-zone")?.scrollIntoView({ behavior: "smooth" }); } },
        ]
          : null;
  const sideActiveKey = section === "learners"
    ? (learnersView === "list" ? "class-lists" : learnersView)
    : section === "review" ? (settingsOpen ? "settings" : activeLeftNav)
      : section === "my-space" ? mySpaceSection
        : "";

  const workflow: Section[] = [
    "review", "library", "scheme", "lesson-plans", "lesson-notes",
    "row", "dashboard", "learners", "my-space",
  ];
  const stepIndex = Math.max(0, workflow.indexOf(section));
  const prevSection = stepIndex > 0 ? workflow[stepIndex - 1] : null;
  const nextSection = stepIndex < workflow.length - 1 ? workflow[stepIndex + 1] : null;
  const nextEnabled = nextSection === null ? false
    : nextSection === "scheme" ? flow.schemes > 0
      : nextSection === "lesson-plans" ? flow.plans > 0
        : nextSection === "lesson-notes" ? flow.notes > 0
          : nextSection === "dashboard" ? flow.row > 0
            : true;
  const nextDisabledReason = nextSection === "scheme" ? "Generate a Scheme first"
    : nextSection === "lesson-plans" ? "Generate Lesson Plans first"
      : nextSection === "lesson-notes" ? "Generate Lesson Notes first"
        : nextSection === "dashboard" ? "Generate Record of Work first" : "";

  if (!authReady) {
    return <div className="flex min-h-screen items-center justify-center text-sm text-muted">Loading My Space…</div>;
  }
  if (!user) {
    return (
      <>
        <Auth onSignedIn={signedIn} onError={setError} />
        {error ? <Toast message={error} onDone={() => setError(null)} /> : null}
      </>
    );
  }

  return (
    <div className="min-h-full bg-[#F5F8F6]">
      <header className="sticky top-0 z-30 border-b border-line bg-white/95 backdrop-blur">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2.5 lg:px-6">
          <button className="flex items-center gap-2.5 text-left" onClick={() => openSection("review")}
                  data-testid="brand-home">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-600 text-lg font-black text-white shadow-sm">M</span>
            <span>
              <span className="block text-[15px] font-extrabold leading-tight text-ink">Mwalimu Studio</span>
              <span className="block text-[10px] font-medium uppercase tracking-[0.12em] text-muted">CBC teacher workspace</span>
            </span>
          </button>

          {isCompact ? (
            <button className="btn-ghost ml-auto px-3 py-1.5 text-xs" onClick={() => setMobileMenuOpen((v) => !v)}
                    data-testid="nav-menu-toggle">☰ Menu</button>
          ) : null}

          <nav
            aria-label="Main"
            data-testid="top-nav"
            className={isCompact
              ? (mobileMenuOpen ? "absolute left-0 right-0 top-full z-40 flex w-full flex-col gap-1 border-b border-line bg-white p-2 shadow-lg" : "hidden")
              : "flex flex-wrap items-center gap-1"}
          >
            {topItems.map((item) => (
              <button key={item.key} onClick={() => openSection(item.key)}
                      aria-current={section === item.key ? "page" : undefined}
                      className={`rounded-lg px-3 py-2 text-[13px] transition-colors ${
                        section === item.key
                          ? "bg-[#E8F5E9] font-bold text-brand-900 underline decoration-2 underline-offset-4 decoration-emerald-600"
                          : "font-medium text-muted hover:bg-slate-50 hover:text-ink"
                      }`} data-testid={item.testId}>
                {item.label}
              </button>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-2" data-testid="top-right">
            {section === "review" && health ? (
              <span className="hidden items-center gap-1.5 rounded-full border border-brand-200 bg-brand-50 px-2.5 py-1 text-[10px] font-semibold text-brand-800 sm:inline-flex"
                    data-testid="top-api-badge">
                <span className="h-1.5 w-1.5 rounded-full bg-brand-600" />
                API ok · {health.parserVersion}
              </span>
            ) : null}
            {section === "review" ? (
              <button className="btn-ghost px-2.5 py-1.5 text-xs" onClick={() => {
                setCrumb([]); go("review");
                setToast("Open a document in Parser & Review, then use Approve All.");
              }} data-testid="top-approve-all">✓ Approve All</button>
            ) : null}
            <button className="btn-ghost px-2.5 py-1.5 text-xs" onClick={logout}
                    data-testid="top-logout">Logout</button>
          </div>
        </div>

        <div className="flex items-center gap-1.5 border-t border-brand-100 bg-brand-50 px-4 py-1.5 text-[11px] text-brand-900 lg:px-6"
             data-testid="breadcrumb">
          <button className="font-semibold underline" onClick={() => openSection("library")} data-testid="breadcrumb-studio">Studio</button>
          {crumbParts.map((part, i) => (
            <span key={`${part}-${i}`} className="flex items-center gap-1.5">
              <span className="text-brand-400">›</span>
              <span className={i === crumbParts.length - 1 ? "font-semibold" : "text-brand-800/80"}>{part}</span>
            </span>
          ))}
        </div>
      </header>

      <div className={isCompact ? "block" : "flex items-start"}>
        {sideItems ? (isCompact ? (
          <div className="w-full border-b border-line bg-slate-50 px-3 py-2">
            <div className="flex gap-2 overflow-x-auto" data-testid="context-nav" aria-label="Section">
              {sideItems.map((item) => {
                const active = sideActiveKey === item.key;
                return <button key={item.key} onClick={item.action}
                  className={`shrink-0 rounded-full border px-3 py-1.5 text-xs ${active
                    ? "border-emerald-600 bg-white font-bold text-brand-900"
                    : "border-line bg-white/70 text-muted"}`}
                  data-testid={`side-nav-${item.key}`}>{item.label}</button>;
              })}
            </div>
          </div>
        ) : (
          <aside className="sticky top-[92px] h-[calc(100vh-92px)] w-[220px] shrink-0 border-r border-line bg-slate-50"
                 data-testid="context-nav" aria-label="Section">
            <nav className="space-y-1 p-2">
              {sideItems.map((item) => {
                const active = sideActiveKey === item.key;
                return <button key={item.key} onClick={item.action}
                  className={`block w-full rounded-r-md border-l-[3px] px-3 py-2 text-left text-xs ${
                    active ? "border-emerald-600 bg-white font-bold text-brand-900"
                      : "border-transparent text-muted hover:bg-white hover:text-ink"}`}
                  aria-current={active ? "page" : undefined}
                  data-testid={`side-nav-${item.key}`}>{item.label}</button>;
              })}
            </nav>
          </aside>
        )) : null}
        <main className="min-w-0 flex-1 px-3 py-4 sm:px-4 lg:px-6">
          {user.needsProfileConfirm && !mySpaceOpen ? (
            <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900"
              data-testid="migration-banner">
              <span className="flex-1">
                Welcome to My Space! Please confirm your Name and Email to secure your space.
              </span>
              <button className="btn-mini !bg-amber-600 !text-white" onClick={() => {
                window.location.hash = "#/my-space";
                setMySpaceOpen(true);
              }} data-testid="migration-confirm">Confirm</button>
            </div>
          ) : null}

          {mySpaceOpen ? (
            <MySpace
              user={user}
              confirmRequired={user.needsProfileConfirm}
              onUpdated={(u) => setUser(u)}
              onLogout={logout}
              onToast={setToast}
              onError={setError}
            />
          ) : healthError ? (
            <p className="mb-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
              Cannot reach the Mwalimu Studio API ({healthError}). Start it with{" "}
              <code className="rounded bg-rose-100 px-1">uvicorn main:app --reload</code> in{" "}
              <code className="rounded bg-rose-100 px-1">backend/</code>.
            </p>
          ) : null}

          {error ? (
            <div className="mb-4 flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
              <span className="flex-1">{error}</span>
              <button className="text-rose-500 hover:text-rose-800" onClick={() => setError(null)}>
                ✕
              </button>
            </div>
          ) : null}

          {settingsOpen ? (
            <Settings onToast={setToast} onError={setError} />
          ) : tab === "learners" ? (
            <MyLearners
              view={learnersView}
              assessTarget={assessTarget}
              onNavigate={navigateLearners}
              onAssessed={() => setAssessTarget(null)}
              onToast={setToast}
              onError={setError}
            />
          ) : tab === "dashboard" ? (
            <Dashboard
              teacherName={user.name}
              onViewLearners={() => navigateLearners("list")}
              onViewScheme={(planId) => void viewSchemeFor(planId)}
              onViewRow={(planId) => openRowDoc(planId)}
              onExport={(planId) => openExport(planId)}
              onToast={setToast}
              onError={setError}
            />
          ) : tab === "review" ? (
            <>
              {fromLibrary && job ? (
                <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-900">
                  <span>
                    Viewing <strong>{job.fileName}</strong> from your library.
                  </span>
                  <a
                    className="underline"
                    href={api.pdfUrl(job.id)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open original PDF
                  </a>
                  <button className="ml-auto underline" onClick={() => go("library")}>
                    Back to library
                  </button>
                </div>
              ) : null}
              <UploadAndReview
                job={job}
                setJob={setJob}
                fromLibrary={fromLibrary}
                highlightChunkIds={highlight}
                onSavedToLibrary={onSavedToLibrary}
                onError={setError}
              />
            </>
          ) : tab === "library" ? (
            <Library
              onOpen={openDoc}
              onExportTermPack={(documentId) => openExport(null, documentId)}
              onToast={setToast}
              onError={setError}
              refreshKey={libraryKey}
              openDocumentId={pendingDocId}
              onOpenedDocument={() => setPendingDocId(null)}
            />
          ) : tab === "plan" && rowOpen ? (
            <RecordOfWork
              planId={rowPlanId}
              focus={rowFocus}
              onToast={workflowToast}
              onError={setError}
              onOpenRow={openRowDoc}
              onExportTermPack={(pid) => openExport(pid)}
              onAssess={(target) => openAssessment(target)}
              onBack={() => {
                setRowPlanId(null);
                setRowFocus(null);
              }}
            />
          ) : tab === "plan" && notesId ? (
            <LessonNotesEditor
              noteId={notesId}
              onToast={setToast}
              onError={setError}
              onViewSource={openSourceChunk}
              onBack={() => {
                setNotesId(null);
                setCrumb([]);
              }}
            />
          ) : lessonId ? (
            <LessonPlanView
              lessonId={lessonId}
              onToast={setToast}
              onError={setError}
              onViewSource={openSourceChunk}
              onOpenNotes={setNotesId}
              onOpenLesson={setLessonId}
              onMarkTaught={(schemeId, week, lesson) => void markTaught(schemeId, week, lesson)}
              onAssess={(target) => openAssessment(target)}
              onCrumb={setCrumb}
              onBack={() => {
                setLessonId(null);
                setCrumb([]);
              }}
            />
          ) : tab === "plan" && notesListOpen ? (
            <LessonNotesList
              onOpen={(noteId) => {
                setNotesListOpen(false);
                setNotesId(noteId);
                setCrumb([]);
              }}
              onToast={setToast}
              onError={setError}
              refreshKey={libraryKey}
            />
          ) : tab === "plan" && lessonListOpen ? (
            <LessonPlansList
              onOpen={(lessonId) => {
                setLessonListOpen(false);
                setLessonId(lessonId);
                setCrumb([]);
              }}
              onToast={setToast}
              onError={setError}
              refreshKey={libraryKey}
            />
          ) : plan ? (
            <PlanView
              planId={plan.id}
              onToast={workflowToast}
              onError={setError}
              onViewSource={openSourceChunk}
              onOpenLesson={setLessonId}
              onOpenNotes={setNotesId}
              onOpenRow={openRowDoc}
              onExportTermPack={(pid) => openExport(pid)}
              onCrumb={setCrumb}
              onBack={() => {
                setLessonId(null);
                setNotesId(null);
                setCrumb([]);
                setPlan(null);
              }}
            />
          ) : planCreating ? (
            <CreateDocument
              onCreated={(p) => {
                setPlan(p);
                setPlanCreating(false);
                setLessonId(null);
                setNotesId(null);
                setCrumb([]);
                setLibraryKey((k) => k + 1);
              }}
              onCancel={() => setPlanCreating(false)}
              onToast={setToast}
              onError={setError}
            />
          ) : (
            <SchemeList
              onOpen={(p) => {
                setPlan(p);
                setPlanCreating(false);
                setLessonId(null);
                setNotesId(null);
                setCrumb([]);
              }}
              onCreate={() => setPlanCreating(true)}
              onToast={setToast}
              onError={setError}
              refreshKey={libraryKey}
            />
          )}

          <nav className="mt-8 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-line bg-white px-4 py-3"
               aria-label="Workflow" data-testid="workflow-footer">
            {prevSection ? (
              <button className="btn-ghost px-3 py-1.5 text-xs" onClick={() => openSection(prevSection)}
                      data-testid="workflow-back">← {footerBackLabel[section]}</button>
            ) : <span />}
            {nextSection ? (
              <button className="btn-primary px-3 py-1.5 text-xs" disabled={!nextEnabled}
                      title={nextEnabled ? undefined : nextDisabledReason}
                      onClick={() => openSection(nextSection)} data-testid="workflow-next">
                Next → {footerNextLabel[section]}
              </button>
            ) : <span className="text-[11px] text-muted">End of workflow</span>}
          </nav>

          <footer className="mt-10 border-t border-line pt-4 text-[11px] text-muted">
            Parser engine: <code>services/parser_engine.py</code> (copied verbatim,{" "}
            {health?.parserVersion ?? "studio-parser-v1"}). Every sub-strand stays flagged until a
            teacher approves it, and search results always keep their document and page.
          </footer>
        </main>
      </div>

      {toast ? <Toast message={toast} onDone={() => setToast(null)} /> : null}
      {exportOpen ? (
        <ExportModal
          planId={exportPlanId}
          documentId={exportDocumentId}
          onClose={() => setExportOpen(false)}
          onToast={setToast}
          onError={setError}
        />
      ) : null}
    </div>
  );
}

