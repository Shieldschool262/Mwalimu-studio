import type {
  HealthInfo,
  LessonDiff,
  LessonNote,
  LessonNotesList,
  LessonPicker,
  LessonPlan,
  LessonPlanList,
  LibraryList,
  NotesPicker,
  ParseJob,
  PlanDiff,
  PlanDocument,
  PlanSummary,
  PlanVersion,
  PlanVersionList,
  ExportJob,
  ExportPlanOption,
  ExportStartResult,
  RecordOfWorkDoc,
  RowCoverage,
  DashboardData,
  DashboardFilters,
  DashboardReflection,
  RowDiff,
  RowEditResult,
  RowSchemeList,
  RowVersionPreview,
  RowVersionSaved,
  SearchResponse,
  SettingsDraft,
  SettingsPayload,
  AITestResult,
  SearchTestResult,
  ModelsResponse,
  VettingCatalog,
  WebSearchResponse,
  AuthUser,
  AuthResult,
  LearnersList, Learner, LearnerSummary, AssessmentContext, AssessmentAuditEntry,
  ProgressData, Iep, AssessTarget, AssessOptions,
} from "./types";

const BASE = "";

async function parseResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep status text */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

const jsonPost = (url: string, body: unknown) =>
  fetch(BASE + url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const api = {
  health: () => fetch(`${BASE}/health`).then((r) => parseResponse<HealthInfo>(r)),

  // ---- Phase 1: parse + review -------------------------------------------
  parsePdf: async (file: File): Promise<ParseJob> => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${BASE}/api/parse`, { method: "POST", body: form }).then((r) =>
      parseResponse<ParseJob>(r),
    );
  },

  getJob: (jobId: string) =>
    fetch(`${BASE}/api/parse/${jobId}`).then((r) => parseResponse<ParseJob>(r)),

  correctChunk: (jobId: string, chunkId: string, patch: Record<string, unknown>) =>
    jsonPost(`/api/parse/${jobId}/chunks/${chunkId}/correct`, patch).then((r) =>
      parseResponse<ParseJob>(r),
    ),

  approveAll: (jobId: string, minConfidence = 0.9) =>
    jsonPost(`/api/parse/${jobId}/approve-all`, { min_confidence: minConfidence }).then((r) =>
      parseResponse<ParseJob>(r),
    ),

  approveStrand: (jobId: string, strandCode: string | null, strand: string) =>
    jsonPost(`/api/parse/${jobId}/approve-strand`, { strandCode, strand }).then((r) =>
      parseResponse<ParseJob>(r),
    ),

  // ---- Phase 2: library ---------------------------------------------------
  library: (status?: string) => {
    const qs = status ? `?status=${encodeURIComponent(status)}` : "";
    return fetch(`${BASE}/api/library${qs}`).then((r) => parseResponse<LibraryList>(r));
  },

  libraryDoc: (docId: string) =>
    fetch(`${BASE}/api/library/${docId}`).then((r) => parseResponse<ParseJob>(r)),

  search: (q: string, filters: { grade?: string; subject?: string; status?: string } = {}) => {
    const params = new URLSearchParams({ q });
    if (filters.grade) params.set("grade", filters.grade);
    if (filters.subject) params.set("subject", filters.subject);
    if (filters.status) params.set("status", filters.status);
    return fetch(`${BASE}/api/library/search?${params}`).then((r) =>
      parseResponse<SearchResponse>(r),
    );
  },

  saveToLibrary: (jobId: string, saveWithGaps: boolean) =>
    jsonPost("/api/library/save", { jobId, saveWithGaps }).then((r) => parseResponse<ParseJob>(r)),

  reparse: (docId: string) =>
    jsonPost(`/api/library/${docId}/reparse`, {}).then((r) => parseResponse<ParseJob>(r)),

  deleteDoc: (docId: string) =>
    fetch(`${BASE}/api/library/${docId}`, { method: "DELETE" }).then((r) =>
      parseResponse<{ deleted: boolean }>(r),
    ),

  exportUrl: (docId: string) => `${BASE}/api/library/${docId}/export`,
  pdfUrl: (docId: string) => `${BASE}/api/library/${docId}/file`,

  // ---- Phase 3: planning --------------------------------------------------
  planSources: (grade?: string, subject?: string) => {
    const params = new URLSearchParams();
    if (grade) params.set("grade", grade);
    if (subject) params.set("subject", subject);
    const qs = params.toString();
    return fetch(`${BASE}/api/plans/sources${qs ? `?${qs}` : ""}`).then((r) =>
      parseResponse<VettingCatalog>(r),
    );
  },

  createPlan: (body: {
    type: string;
    institution: string;
    grade: string;
    subject: string;
    term: string;
    year: string;
    lessonsPerWeek: number;
    totalWeeks: number;
    sourceChunkIds: string[];
    templateVersion?: string;
    title?: string;
    teacherName?: string;
    tscNo?: string;
  }) => jsonPost("/api/plans", body).then((r) => parseResponse<PlanDocument>(r)),

  editPlanHeader: (planId: string, patch: Record<string, unknown>) =>
    jsonPost(`/api/plans/${planId}/header`, patch).then((r) => parseResponse<PlanDocument>(r)),

  planPdfUrl: (planId: string) => `${BASE}/api/plans/${planId}/export.pdf`,

  plans: () =>
    fetch(`${BASE}/api/plans`).then((r) =>
      parseResponse<{ plans: PlanSummary[]; count: number }>(r),
    ),

  plan: (planId: string) =>
    fetch(`${BASE}/api/plans/${planId}`).then((r) => parseResponse<PlanDocument>(r)),

  deletePlan: (planId: string) =>
    fetch(`${BASE}/api/plans/${planId}`, { method: "DELETE" }).then((r) =>
      parseResponse<{ deleted: boolean }>(r),
    ),

  duplicatePlan: (planId: string, term?: string) =>
    jsonPost(`/api/plans/${planId}/duplicate`, { term }).then((r) =>
      parseResponse<PlanDocument>(r),
    ),

  planStatus: (planId: string, status: string) =>
    jsonPost(`/api/plans/${planId}/status`, { status }).then((r) =>
      parseResponse<PlanDocument>(r),
    ),

  editSection: (planId: string, sectionId: string, patch: Record<string, unknown>) =>
    jsonPost(`/api/plans/${planId}/sections/${sectionId}/edit`, patch).then((r) =>
      parseResponse<PlanDocument>(r),
    ),

  /** [Reset to Appendix] - restore one row's Resources/Assessment from the appendix. */
  resetAppendix: (planId: string, sectionId: string, field: "resources" | "assessment") =>
    jsonPost(`/api/plans/${planId}/sections/${sectionId}/reset-appendix`, { field }).then((r) =>
      parseResponse<PlanDocument>(r),
    ),

  /** [Re-balance Outcomes] - re-split one sub-strand's weekly rows. */
  rebalance: (planId: string, subStrandCode: string, lessonsPerWeek?: number) =>
    jsonPost(`/api/plans/${planId}/rebalance`, { subStrandCode, lessonsPerWeek }).then((r) =>
      parseResponse<PlanDocument>(r),
    ),

  // ---- Phase 4: scheme version history, undo, bulk edits --------------------
  createPlanVersion: (planId: string, comment: string) =>
    jsonPost(`/api/plans/${planId}/versions`, { comment }).then((r) =>
      parseResponse<PlanVersion & { plan: PlanDocument }>(r),
    ),

  planVersions: (planId: string) =>
    fetch(`${BASE}/api/plans/${planId}/versions`).then((r) =>
      parseResponse<PlanVersionList>(r),
    ),

  restorePlanVersion: (planId: string, versionId: string) =>
    jsonPost(`/api/plans/${planId}/versions/${versionId}/restore`, {}).then((r) =>
      parseResponse<PlanDocument & { restoredVersion: PlanVersion }>(r),
    ),

  planVersionDiff: (planId: string, versionId: string) =>
    fetch(`${BASE}/api/plans/${planId}/versions/${versionId}/diff`).then((r) =>
      parseResponse<PlanDiff>(r),
    ),

  undoPlan: (planId: string) =>
    jsonPost(`/api/plans/${planId}/undo`, {}).then((r) => parseResponse<PlanDocument>(r)),

  unlockPlan: (planId: string) =>
    jsonPost(`/api/plans/${planId}/unlock`, {}).then((r) =>
      parseResponse<PlanDocument & { unlockedVersion: PlanVersion }>(r),
    ),

  resetSource: (planId: string, sectionId: string) =>
    jsonPost(`/api/plans/${planId}/sections/${sectionId}/reset-source`, {}).then((r) =>
      parseResponse<PlanDocument>(r),
    ),

  extendRow: (planId: string, sectionId: string, lessonCount: number) =>
    jsonPost(`/api/plans/${planId}/sections/${sectionId}/extend`, { lessonCount }).then((r) =>
      parseResponse<PlanDocument>(r),
    ),

  bulkResources: (planId: string, subStrandCode: string, resources: string) =>
    jsonPost(`/api/plans/${planId}/bulk-resources`, { subStrandCode, resources }).then((r) =>
      parseResponse<PlanDocument>(r),
    ),

  clearReflections: (planId: string) =>
    jsonPost(`/api/plans/${planId}/clear-reflections`, {}).then((r) =>
      parseResponse<PlanDocument>(r),
    ),

  // ---- Phase 4: KICD lesson plans -----------------------------------------
  lessonPicker: (planId: string, sectionId: string) =>
    fetch(`${BASE}/api/plans/${planId}/sections/${sectionId}/lessons`).then((r) =>
      parseResponse<LessonPicker>(r),
    ),

  createLessonPlans: (body: {
    schemeRowId: string;
    lessons: number[];
    dates?: Record<string, string>;
    duration?: number;
    durationType?: "Single" | "Double";
    templateVersion?: string;
    time?: string;
    classSize?: number | null;
  }) =>
    jsonPost("/api/lesson-plans", body).then((r) =>
      parseResponse<{ created: LessonPlan[]; count: number; errors: string[] }>(r),
    ),

  lessonPlans: (params: { planId?: string; sectionId?: string } = {}) => {
    const qs = new URLSearchParams();
    if (params.planId) qs.set("planId", params.planId);
    if (params.sectionId) qs.set("sectionId", params.sectionId);
    return fetch(`${BASE}/api/lesson-plans${qs.toString() ? `?${qs}` : ""}`).then((r) =>
      parseResponse<LessonPlanList>(r),
    );
  },

  lessonPlan: (lessonId: string) =>
    fetch(`${BASE}/api/lesson-plans/${lessonId}`).then((r) => parseResponse<LessonPlan>(r)),

  editLessonSection: (lessonId: string, sectionId: string, patch: Record<string, unknown>) =>
    jsonPost(`/api/lesson-plans/${lessonId}/sections/${sectionId}/edit`, patch).then((r) =>
      parseResponse<LessonPlan>(r),
    ),

  editLessonHeader: (lessonId: string, patch: Record<string, unknown>) =>
    jsonPost(`/api/lesson-plans/${lessonId}/header`, patch).then((r) =>
      parseResponse<LessonPlan>(r),
    ),

  resetLessonHeader: (lessonId: string, field: string) =>
    jsonPost(`/api/lesson-plans/${lessonId}/header/reset`, { field }).then((r) =>
      parseResponse<LessonPlan>(r),
    ),

  resetLessonSection: (lessonId: string, sectionId: string) =>
    jsonPost(`/api/lesson-plans/${lessonId}/sections/${sectionId}/reset`, {}).then((r) =>
      parseResponse<LessonPlan>(r),
    ),

  fixLessonSlo: (lessonId: string) =>
    jsonPost(`/api/lesson-plans/${lessonId}/slo/fix`, {}).then((r) =>
      parseResponse<LessonPlan & { fixed?: boolean }>(r),
    ),

  lessonStatus: (lessonId: string, status: string) =>
    jsonPost(`/api/lesson-plans/${lessonId}/status`, { status }).then((r) =>
      parseResponse<LessonPlan>(r),
    ),

  deleteLessonPlan: (lessonId: string) =>
    fetch(`${BASE}/api/lesson-plans/${lessonId}`, { method: "DELETE" }).then((r) =>
      parseResponse<{ deleted: boolean }>(r),
    ),

  lessonVersions: (lessonId: string) =>
    fetch(`${BASE}/api/lesson-plans/${lessonId}/versions`).then((r) =>
      parseResponse<PlanVersionList>(r),
    ),

  createLessonVersion: (lessonId: string, comment: string) =>
    jsonPost(`/api/lesson-plans/${lessonId}/versions`, { comment }).then((r) =>
      parseResponse<PlanVersion & { lessonPlan: LessonPlan }>(r),
    ),

  restoreLessonVersion: (lessonId: string, versionId: string) =>
    jsonPost(`/api/lesson-plans/${lessonId}/versions/${versionId}/restore`, {}).then((r) =>
      parseResponse<LessonPlan & { restoredVersion: PlanVersion }>(r),
    ),

  lessonVersionDiff: (lessonId: string, versionId: string) =>
    fetch(`${BASE}/api/lesson-plans/${lessonId}/versions/${versionId}/diff`).then((r) =>
      parseResponse<LessonDiff>(r),
    ),

  aiDraft: (lessonId: string) =>
    jsonPost(`/api/lesson-plans/${lessonId}/ai/draft`, {}).then((r) =>
      parseResponse<LessonPlan>(r),
    ),

  aiSplit: (lessonId: string) =>
    jsonPost(`/api/lesson-plans/${lessonId}/ai/split`, {}).then((r) =>
      parseResponse<{ experience: string; atoms: Record<string, string>[]; message: string }>(r),
    ),

  webExamples: (lessonId: string, q: string) =>
    fetch(
      `${BASE}/api/lesson-plans/${lessonId}/web-examples?q=${encodeURIComponent(q)}`,
    ).then((r) => parseResponse<WebSearchResponse>(r)),

  lessonPdfUrl: (lessonId: string) => `${BASE}/api/lesson-plans/${lessonId}/export.pdf`,

  // ---- Phase 5: learner-facing Lesson Notes --------------------------------
  notesPicker: (planId: string, sectionId: string) =>
    fetch(`${BASE}/api/plans/${planId}/sections/${sectionId}/notes-picker`).then((r) =>
      parseResponse<NotesPicker>(r),
    ),

  createLessonNotes: (body: {
    schemeRowId?: string;
    lessonPlanId?: string;
    lessons?: number[];
    templateVersion?: string;
  }) =>
    jsonPost("/api/lesson-notes", body).then((r) =>
      parseResponse<{ created: LessonNote[]; count: number; errors: string[] }>(r),
    ),

  lessonNotes: (params: { planId?: string; sectionId?: string } = {}) => {
    const qs = new URLSearchParams();
    if (params.planId) qs.set("planId", params.planId);
    if (params.sectionId) qs.set("sectionId", params.sectionId);
    return fetch(`${BASE}/api/lesson-notes${qs.toString() ? `?${qs}` : ""}`).then((r) =>
      parseResponse<LessonNotesList>(r),
    );
  },

  lessonNote: (noteId: string) =>
    fetch(`${BASE}/api/lesson-notes/${noteId}`).then((r) => parseResponse<LessonNote>(r)),

  editNoteHeader: (noteId: string, patch: Record<string, unknown>) =>
    jsonPost(`/api/lesson-notes/${noteId}/header`, patch).then((r) =>
      parseResponse<LessonNote>(r),
    ),

  editNoteSection: (noteId: string, sectionId: string, patch: Record<string, unknown>) =>
    jsonPost(`/api/lesson-notes/${noteId}/sections/${sectionId}/edit`, patch).then((r) =>
      parseResponse<LessonNote>(r),
    ),

  resetNoteSection: (noteId: string, sectionId: string) =>
    jsonPost(`/api/lesson-notes/${noteId}/sections/${sectionId}/reset`, {}).then((r) =>
      parseResponse<LessonNote>(r),
    ),

  noteStatus: (noteId: string, status: string) =>
    jsonPost(`/api/lesson-notes/${noteId}/status`, { status }).then((r) =>
      parseResponse<LessonNote>(r),
    ),

  deleteLessonNote: (noteId: string) =>
    fetch(`${BASE}/api/lesson-notes/${noteId}`, { method: "DELETE" }).then((r) =>
      parseResponse<{ deleted: boolean }>(r),
    ),

  noteVersions: (noteId: string) =>
    fetch(`${BASE}/api/lesson-notes/${noteId}/versions`).then((r) =>
      parseResponse<PlanVersionList>(r),
    ),

  createNoteVersion: (noteId: string, comment: string) =>
    jsonPost(`/api/lesson-notes/${noteId}/versions`, { comment }).then((r) =>
      parseResponse<PlanVersion & { lessonNote: LessonNote }>(r),
    ),

  noteVersion: (noteId: string, versionId: string) =>
    fetch(`${BASE}/api/lesson-notes/${noteId}/versions/${versionId}`).then((r) =>
      parseResponse<PlanVersion & { snapshot: LessonNote }>(r),
    ),

  noteVersionDiff: (noteId: string, versionId: string) =>
    fetch(`${BASE}/api/lesson-notes/${noteId}/versions/${versionId}/diff`).then((r) =>
      parseResponse<LessonDiff>(r),
    ),

  restoreNoteVersion: (noteId: string, versionId: string) =>
    jsonPost(`/api/lesson-notes/${noteId}/versions/${versionId}/restore`, {}).then((r) =>
      parseResponse<LessonNote & { restoredVersion: PlanVersion }>(r),
    ),

  aiNoteDraft: (noteId: string) =>
    jsonPost(`/api/lesson-notes/${noteId}/ai/draft`, {}).then((r) =>
      parseResponse<LessonNote>(r),
    ),

  aiNoteAcceptAll: (noteId: string) =>
    jsonPost(`/api/lesson-notes/${noteId}/ai/accept-all`, {}).then((r) =>
      parseResponse<LessonNote>(r),
    ),

  noteWebExamples: (noteId: string, q: string) =>
    fetch(
      `${BASE}/api/lesson-notes/${noteId}/search-examples?q=${encodeURIComponent(q)}`,
    ).then((r) => parseResponse<WebSearchResponse>(r)),

  insertNoteWebExample: (
    noteId: string,
    body: { title: string; url: string; snippet?: string },
  ) =>
    jsonPost(`/api/lesson-notes/${noteId}/web-examples`, body).then((r) =>
      parseResponse<LessonNote>(r),
    ),

  addNoteSource: (
    noteId: string,
    body: { kind?: string; title?: string; url?: string; text?: string },
  ) =>
    jsonPost(`/api/lesson-notes/${noteId}/sources`, body).then((r) =>
      parseResponse<LessonNote>(r),
    ),

  notePdfUrl: (noteId: string, answers = false) =>
    `${BASE}/api/lesson-notes/${noteId}/export.pdf${answers ? "?answers=1" : ""}`,

  // ---- Phase 6: Settings (AI providers + web search providers) ------------
  settings: () =>
    fetch(`${BASE}/api/settings`).then((r) => parseResponse<SettingsPayload>(r)),

  saveSettings: (draft: SettingsDraft) =>
    fetch(`${BASE}/api/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(draft),
    }).then((r) => parseResponse<SettingsPayload>(r)),

  resetSettings: () =>
    fetch(`${BASE}/api/settings/reset`, { method: "POST" }).then((r) =>
      parseResponse<SettingsPayload>(r),
    ),

  testAI: (ai: SettingsDraft["ai"]) =>
    fetch(`${BASE}/api/settings/test/ai`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ai }),
    }).then((r) => parseResponse<AITestResult>(r)),

  testSearch: (search: SettingsDraft["search"], query: string) =>
    fetch(`${BASE}/api/settings/test/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ search, query }),
    }).then((r) => parseResponse<SearchTestResult>(r)),

  settingsModels: (provider: string, ai: SettingsDraft["ai"]) =>
    fetch(`${BASE}/api/settings/models`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider, ai }),
    }).then((r) => parseResponse<ModelsResponse>(r)),

  // ---- Phase 6: Record of Work (retrospective, teacher-filled) ------------
  rowSchemes: () =>
    fetch(`${BASE}/api/row/schemes`).then((r) => parseResponse<RowSchemeList>(r)),

  rowDoc: (planId: string) =>
    fetch(`${BASE}/api/row?planId=${encodeURIComponent(planId)}`).then((r) =>
      parseResponse<RecordOfWorkDoc>(r),
    ),

  rowCoverage: (planId: string) =>
    fetch(`${BASE}/api/row/coverage?planId=${encodeURIComponent(planId)}`).then((r) =>
      parseResponse<RowCoverage>(r),
    ),

  rowGenerate: (planId: string, addMissingOnly = false) =>
    jsonPost(`/api/row`, { planId, addMissingOnly }).then((r) =>
      parseResponse<RecordOfWorkDoc>(r),
    ),

  rowMarkTaught: (planId: string, week: number, lesson: number) =>
    jsonPost(`/api/row/mark-taught`, { planId, week, lesson }).then((r) =>
      parseResponse<RecordOfWorkDoc>(r),
    ),

  rowEdit: (
    rowId: string,
    patch: {
      date?: string;
      workDone?: string;
      reflection?: string;
      status?: string;
      signature?: string;
      carryOverTo?: { week: number; lesson: number } | null;
    },
  ) =>
    jsonPost(`/api/row/${rowId}/edit`, patch).then((r) =>
      parseResponse<RowEditResult>(r),
    ),

  rowReset: (rowId: string) =>
    jsonPost(`/api/row/${rowId}/reset`, {}).then((r) =>
      parseResponse<RowEditResult>(r),
    ),

  rowCarryOver: (rowId: string, week: number, lesson: number) =>
    jsonPost(`/api/row/${rowId}/carry-over`, { week, lesson }).then((r) =>
      parseResponse<RecordOfWorkDoc>(r),
    ),

  rowBulkStatus: (docId: string, week: number, status: string) =>
    jsonPost(`/api/row/${docId}/bulk-status`, { week, status }).then((r) =>
      parseResponse<RecordOfWorkDoc>(r),
    ),

  rowStatus: (docId: string, status: "Draft" | "Final") =>
    jsonPost(`/api/row/${docId}/status`, { status }).then((r) =>
      parseResponse<RecordOfWorkDoc>(r),
    ),

  rowAiReflection: (rowId: string) =>
    jsonPost(`/api/row/${rowId}/ai/reflection`, {}).then((r) =>
      parseResponse<{ row: RecordOfWorkDoc["rows"][number]; draft: string; message: string }>(r),
    ),

  rowAiAccept: (rowId: string, text?: string) =>
    jsonPost(`/api/row/${rowId}/ai/accept`, { text: text || "" }).then((r) =>
      parseResponse<RowEditResult>(r),
    ),

  rowAiReject: (rowId: string) =>
    jsonPost(`/api/row/${rowId}/ai/reject`, {}).then((r) =>
      parseResponse<RowEditResult>(r),
    ),

  rowVersions: (docId: string) =>
    fetch(`${BASE}/api/row/${docId}/versions`).then((r) =>
      parseResponse<PlanVersionList>(r),
    ),

  rowVersion: (docId: string, versionId: string) =>
    fetch(`${BASE}/api/row/${docId}/versions/${versionId}`).then((r) =>
      parseResponse<RowVersionPreview>(r),
    ),

  rowVersionDiff: (docId: string, versionId: string) =>
    fetch(`${BASE}/api/row/${docId}/versions/${versionId}/diff`).then((r) =>
      parseResponse<RowDiff>(r),
    ),

  rowCreateVersion: (docId: string, comment: string) =>
    jsonPost(`/api/row/${docId}/versions`, { comment }).then((r) =>
      parseResponse<RowVersionSaved>(r),
    ),

  rowRestoreVersion: (docId: string, versionId: string) =>
    jsonPost(`/api/row/${docId}/versions/${versionId}/restore`, {}).then((r) =>
      parseResponse<RecordOfWorkDoc>(r),
    ),

  rowPdfUrl: (docId: string) => `${BASE}/api/row/${docId}/export.pdf`,

  // ---- Phase 7: Term Pack export bundle ----
  exportStart: (planId: string, includes: unknown, format: "pdf" | "zip") =>
    jsonPost(`/api/export`, { planId, includes, format }).then((r) =>
      parseResponse<ExportStartResult>(r),
    ),

  exportJob: (jobId: string) =>
    fetch(`${BASE}/api/export/${encodeURIComponent(jobId)}`).then((r) =>
      parseResponse<ExportJob>(r),
    ),

  exportHistory: (planId?: string) =>
    fetch(`${BASE}/api/export/history${planId ? `?planId=${encodeURIComponent(planId)}` : ""}`)
      .then((r) => parseResponse<{ jobs: ExportJob[] }>(r)),

  exportDelete: (jobId: string) =>
    fetch(`${BASE}/api/export/${encodeURIComponent(jobId)}`, { method: "DELETE" }).then((r) =>
      parseResponse<{ ok: boolean }>(r),
    ),

  exportPlansForDocument: (documentId: string) =>
    fetch(`${BASE}/api/export/plans-for-document?documentId=${encodeURIComponent(documentId)}`)
      .then((r) => parseResponse<{ plans: ExportPlanOption[] }>(r)),

  exportFileUrl: (jobId: string) => `${BASE}/api/export/${jobId}/file`,

  // ---- Phase 8: Coverage Dashboard ----------------------------------------
  dashboard: (filters: DashboardFilters = {}) => {
    const qs = new URLSearchParams();
    if (filters.term) qs.set("term", filters.term);
    if (filters.year) qs.set("year", filters.year);
    if (filters.grade) qs.set("grade", filters.grade);
    if (filters.subject) qs.set("subject", filters.subject);
    if (filters.week) qs.set("week", String(filters.week));
    if (filters.teacher) qs.set("teacher", filters.teacher);
    return fetch(`${BASE}/api/dashboard${qs.toString() ? `?${qs}` : ""}`).then((r) =>
      parseResponse<DashboardData>(r),
    );
  },
  dashboardExportUrl: (filters: DashboardFilters = {}) => {
    const qs = new URLSearchParams();
    if (filters.term) qs.set("term", filters.term);
    if (filters.year) qs.set("year", filters.year);
    if (filters.grade) qs.set("grade", filters.grade);
    if (filters.subject) qs.set("subject", filters.subject);
    if (filters.week) qs.set("week", String(filters.week));
    return `${BASE}/api/dashboard/export${qs.toString() ? `?${qs}` : ""}`;
  },
  dashboardReflection: (planId: string, term = "", year = "") => {
    const qs = new URLSearchParams({ planId, term, year });
    return fetch(`${BASE}/api/dashboard/reflection?${qs}`).then((r) =>
      parseResponse<DashboardReflection>(r),
    );
  },
  dashboardSaveReflection: (body: {
    planId: string; term: string; year: string; reflection: string;
  }) => jsonPost(`${BASE}/api/dashboard/reflection`, body).then((r) =>
    parseResponse<DashboardReflection>(r),
  ),
  rowMarkTaughtById: (
    rowId: string,
    body: { date: string; workDone: string; week?: number; lesson?: number },
  ) => jsonPost(`${BASE}/api/row/${rowId}/mark-taught`, body).then((r) =>
    parseResponse<Record<string, unknown>>(r),
  ),
  rowSkip: (
    rowId: string,
    body: { reason: string; week?: number; lesson?: number },
  ) => jsonPost(`${BASE}/api/row/${rowId}/skip`, body).then((r) =>
    parseResponse<Record<string, unknown>>(r),
  ),
  // ---- Phase 9: individual teacher auth -----------------------------------
  me: () => fetch(`${BASE}/api/auth/me`).then((r) => parseResponse<AuthUser>(r)),
  signup: (body: Record<string, unknown>) =>
    jsonPost(`${BASE}/api/auth/signup`, body).then((r) => parseResponse<AuthUser>(r)),
  login: (body: Record<string, unknown>) =>
    jsonPost(`${BASE}/api/auth/login`, body).then((r) => parseResponse<AuthUser>(r)),
  logout: () => jsonPost(`${BASE}/api/auth/logout`, {}).then((r) => parseResponse<{ ok: boolean }>(r)),
  forgot: (email: string) =>
    jsonPost(`${BASE}/api/auth/forgot`, { email }).then((r) => parseResponse<AuthResult>(r)),
  reset: (token: string, password: string) =>
    jsonPost(`${BASE}/api/auth/reset`, { token, password }).then((r) => parseResponse<{ ok: boolean }>(r)),
  updateMe: (body: Record<string, unknown>) =>
    fetch(`${BASE}/api/auth/me`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) => parseResponse<AuthUser>(r)),
  changePassword: (currentPassword: string, newPassword: string) =>
    jsonPost(`${BASE}/api/auth/change-password`, { currentPassword, newPassword }).then((r) =>
      parseResponse<{ ok: boolean }>(r),
    ),
  deleteMe: (confirmation: string) =>
    fetch(`${BASE}/api/auth/me`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmation }),
    }).then((r) => parseResponse<{ ok: boolean }>(r)),
  exportAllUrl: () => `${BASE}/api/my-space/export-all`,

  // ---- Phase 10: My Learners, assessment, progress and IEP -----------------
  learners: (params: Record<string, string> = {}) => {
    const q = new URLSearchParams(params).toString();
    return fetch(`${BASE}/api/learners${q ? `?${q}` : ""}`).then((r) => parseResponse<LearnersList>(r));
  },
  learnerSummary: () => fetch(`${BASE}/api/learners/summary`).then((r) => parseResponse<LearnerSummary>(r)),
  createLearner: (body: Record<string, unknown>) =>
    jsonPost(`${BASE}/api/learners`, body).then((r) => parseResponse<Learner>(r)),
  updateLearner: (id: string, body: Record<string, unknown>) =>
    fetch(`${BASE}/api/learners/${encodeURIComponent(id)}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }).then((r) => parseResponse<Learner>(r)),
  archiveLearner: (id: string, status: string) =>
    jsonPost(`${BASE}/api/learners/${encodeURIComponent(id)}/archive`, { status })
      .then((r) => parseResponse<Learner>(r)),
  deleteLearner: (id: string, confirmation: string) =>
    fetch(`${BASE}/api/learners/${encodeURIComponent(id)}`, {
      method: "DELETE", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmation }),
    }).then((r) => parseResponse<{ ok: boolean; deleted: string }>(r)),
  csvTemplateUrl: () => `${BASE}/api/learners/csv-template`,
  importLearners: (csv: string, grade: string, learningArea: string,
                   previewOnly: boolean, resolutions: Record<string, string> = {}) =>
    jsonPost(`${BASE}/api/learners/import-csv`, {
      csv, grade, learningArea, previewOnly, resolutions,
    }).then((r) => parseResponse<{
      rows: Record<string, string>[]; total: number;
      duplicates: { rowIndex: number; admissionNo: string; existingName: string; source: string }[];
      created?: number; skipped?: number; replaced?: number; message?: string;
    }>(r)),
  assessOptions: (grade: string, learningArea: string) => {
    const q = new URLSearchParams({ grade, learningArea }).toString();
    return fetch(`${BASE}/api/assess-options?${q}`).then((r) => parseResponse<AssessOptions>(r));
  },
  assessmentContext: (t: AssessTarget) => {
    const q = new URLSearchParams({ schemeRowId: t.schemeRowId });
    if (t.week) q.set("week", String(t.week));
    if (t.lesson) q.set("lesson", String(t.lesson));
    return fetch(`${BASE}/api/assessments/context?${q}`).then((r) => parseResponse<AssessmentContext>(r));
  },
  saveAssessment: (schemeRowId: string, week: number, lesson: number,
                   records: Record<string, unknown>[]) =>
    jsonPost(`${BASE}/api/assessments`, { schemeRowId, week, lesson, records })
      .then((r) => parseResponse<{ saved: number; skipped: number; message: string }>(r)),
  assessmentAudit: (learnerId: string) => {
    const q = new URLSearchParams({ learnerId });
    return fetch(`${BASE}/api/assessments/audit?${q}`).then((r) => parseResponse<{ history: AssessmentAuditEntry[] }>(r));
  },
  progress: (params: Record<string, string> = {}) => {
    const q = new URLSearchParams(params).toString();
    return fetch(`${BASE}/api/progress${q ? `?${q}` : ""}`).then((r) => parseResponse<ProgressData>(r));
  },
  progressExportUrl: (params: Record<string, string> = {}) => {
    const q = new URLSearchParams(params).toString();
    return `${BASE}/api/progress/export${q ? `?${q}` : ""}`;
  },
  ieps: (params: Record<string, string> = {}) => {
    const q = new URLSearchParams(params).toString();
    return fetch(`${BASE}/api/iep${q ? `?${q}` : ""}`).then((r) => parseResponse<{ ieps: Iep[]; count: number }>(r));
  },
  createIep: (body: Record<string, unknown>) =>
    jsonPost(`${BASE}/api/iep`, body).then((r) => parseResponse<Iep>(r)),
  updateIep: (id: string, body: Record<string, unknown>) =>
    fetch(`${BASE}/api/iep/${encodeURIComponent(id)}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }).then((r) => parseResponse<Iep>(r)),
  addIepReview: (id: string, body: Record<string, unknown>) =>
    jsonPost(`${BASE}/api/iep/${encodeURIComponent(id)}/reviews`, body).then((r) => parseResponse<Iep>(r)),
  closeIep: (id: string) =>
    jsonPost(`${BASE}/api/iep/${encodeURIComponent(id)}/close`, {}).then((r) => parseResponse<Iep>(r)),
  suggestSupport: (need: string, iepId?: string) =>
    jsonPost(`${BASE}/api/iep/suggest-support`, { need, iepId })
      .then((r) => parseResponse<{ ideas: string[]; aiEnriched: boolean }>(r)),

  navigationStatus: () =>
    fetch(`${BASE}/api/navigation/status`).then((r) => parseResponse<{
      schemes: number; plans: number; notes: number; row: number;
    }>(r)),

};
