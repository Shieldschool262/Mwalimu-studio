export type ReviewState = "Parsed" | "TeacherCorrected" | "Approved";

export type VettingStatus = "Pending" | "Vetted" | "Rejected";

export type DocumentStatus = "Parsed" | "NeedsReview" | "Approved" | "Failed";

export interface StructuredFields {
  specific_learning_outcomes: string[];
  suggested_learning_experiences: string[];
  key_inquiry_questions: string[];
  core_competencies?: string | null;
  values?: string | null;
  pcis?: string | null;
  link_to_other_learning_areas?: string | null;
  link_to_value?: string | null;
  /** Loose access by canonical key (used by the inline editor). */
  [key: string]: string[] | string | null | undefined;
}

export interface SourceChunk {
  id: string;
  documentId: string;
  ord: number;
  pageNumber: number | null;
  theme: string | null;
  themeCode: string | null;
  strand: string | null;
  strandCode: string | null;
  subStrand: string;
  subStrandCode: string | null;
  lessons: number | null;
  structuredFields: StructuredFields;
  originalFields: Partial<StructuredFields>;
  confidence: number;
  flags: string[];
  reviewState: ReviewState;
  /** Phase 3 vetting: Vetted only if the 3 core fields exist AND a teacher signed off. */
  vettingStatus: VettingStatus;
  /** Required fields that parsed empty, e.g. ["KIQs"]. */
  missingFields: string[];
  ready: boolean;
  needsReview: boolean;
  // Phase 3.5: appendix-sourced autofill values (informational, never part of vetting).
  appendixResources: string | null;
  appendixAssessment: string | null;
  appendixSource: string | null;
  appendixLevel: AppendixLevel;
}

export type AppendixLevel = "sub_strand" | "strand" | "subject" | null;

export interface StrandGroup {
  strandCode: string | null;
  strand: string;
  strandUnresolved: boolean;
  theme: string | null;
  themeCode: string | null;
  chunkCount: number;
  chunks: SourceChunk[];
}

export interface ReviewSummary {
  total: number;
  approved: number;
  corrected: number;
  pending: number;
  missing: number;
  needsReview: number;
  autoApprovable: number;
  readyToApprove: boolean;
  readyToSave: boolean;
}

export interface ParseMeta {
  archetypeName?: string;
  archetypeLabel?: string;
  detectionReason?: string;
  mappingSource?: string;
  tablesFound?: number;
  tablesDetected?: number;
  rubricRowsSkipped?: number;
  duplicatesSkipped?: number;
  backMatterStopPage?: number | null;
  /** Phase 3.5: page where appendix mode started (null if no appendix found). */
  appendixStartPage?: number | null;
  /** Phase 3.5: how many appendix rows were matched to sub-strand chunks. */
  appendixMatched?: number;
  warnings?: string[];
  strandsRecovered?: number;
  experiencesRecovered?: number;
  engineGrade?: string;
  savedWithGaps?: boolean;
  reparsed?: boolean;
}

export interface ParseJob {
  id: string;
  fileName: string;
  grade: string;
  subject: string;
  archetype: string | null;
  archetypeConfidence: number | null;
  archetypeReason: string | null;
  parserVersion: string;
  status: DocumentStatus;
  parseMeta: ParseMeta;
  createdAt: string;
  chunkCount: number;
  reviewSummary: ReviewSummary;
  tree: StrandGroup[];
  chunks: SourceChunk[];
  /** Present on library payloads. */
  archetypeLabel?: string;
  strandCount?: number;
  subStrandCount?: number;
  savedWithGaps?: boolean;
  hasOriginalPdf?: boolean;
}

export interface LibraryCard {
  id: string;
  fileName: string;
  grade: string;
  subject: string;
  archetype: string | null;
  archetypeLabel: string;
  archetypeConfidence: number | null;
  parserVersion: string;
  status: DocumentStatus;
  parseMeta: ParseMeta;
  createdAt: string;
  strandCount: number;
  subStrandCount: number;
  themeCount?: number;
  hasOriginalPdf: boolean;
  savedWithGaps: boolean;
  matchCount?: number;
  // ---- Phase 3 vetting ----
  vettedCount?: number;
  vettingTotal?: number;
  allVetted?: boolean;
  inStudioLibrary?: boolean;
  vettingBadge?: string;
  vettingProblems?: VettingProblem[];
}

export interface VettingProblem {
  chunkId: string;
  subStrandCode: string | null;
  subStrand: string;
  pageNumber: number | null;
  needs: string[];
  reviewState: ReviewState;
}

export interface LibraryList {
  myMaterials: LibraryCard[];
  needsReview: LibraryCard[];
  studioLibrary: LibraryCard[];
  /** Flat list behind the grid (carries inStudioLibrary so the filter works). */
  documents: LibraryCard[];
  facets: { grades: string[]; subjects: string[] };
  counts: { myMaterials: number; needsReview: number; studioLibrary: number };
}

export interface SearchHit {
  documentId: string;
  fileName: string;
  subject: string;
  grade: string;
  status: DocumentStatus;
  archetype: string | null;
  archetypeLabel: string;
  pageNumber: number | null;
  subStrandCode: string | null;
  subStrand: string;
  strand: string | null;
  strandCode: string | null;
  chunkId: string;
  reviewState: ReviewState;
  matchedOn: string[];
  snippet: string;
}

export interface SearchResponse {
  query: string;
  results: SearchHit[];
  documents: LibraryCard[];
  total: number;
}

export interface HealthInfo {
  status: string;
  app: string;
  phase: string;
  parserVersion: string;
  engineGrade: string;
  archetypes: { id: string; label: string; name?: string }[];
}

// ---------------------------------------------------------------------------
// Phase 3 - official KICD Scheme of Work (cbe-scheme-v1)
// ---------------------------------------------------------------------------

export type PlanType = "scheme";
export type PlanStatus = "Draft" | "Final" | "Archived";

/** A cell the teacher owns. `placeholder` is true while it still shows the template default. */
export interface CellText {
  text: string;
  fromSource: boolean;
  placeholder: boolean;
  /** Phase 3.5: value came from the curriculum appendix, not the sub-strand table. */
  fromAppendix?: boolean;
}

export interface ReflectionCell {
  text: string;
  placeholder: string;
  fromSource: boolean;
}

export interface PlanCitation {
  id: string;
  chunkId: string;
  documentId: string | null;
  pageNumber: number | null;
  field: string;
  subStrandCode: string | null;
}

export interface PlanSection {
  id: string;
  planId: string;
  ord: number;
  strandCode: string | null;
  strand: string | null;
  subStrandCode: string | null;
  subStrand: string;
  // Week / lesson allocation - ONE WEEK PER ROW, weeks are single integers
  week: number | null;
  weekStart: number | null;
  weekEnd: number | null;
  lessonStart: number | null;
  lessonEnd: number | null;
  lessonCount: number | null;
  weekLabel: string;
  lessonLabel: string;
  /** "Part 2 of 4" - which weekly slice of the sub-strand this row is. */
  partLabel: string | null;
  /** "Outcomes a) - b)" - hover hint for this week's slice of the sub-strand. */
  outcomePartLabel: string | null;
  /** How many weekly rows this sub-strand was split into. */
  weekCount: number | null;
  flags: string[];
  // Verbatim source
  outcomes: string[];
  experiences: string[];
  kiqs: string[];
  // Teacher-owned cells
  resources: CellText;
  assessment: CellText;
  reflection: ReflectionCell;
  edited: boolean;
  original: Record<string, unknown>;
  citations: PlanCitation[];
  /** Phase 4: vetting state of this row's source chunk (blocks lesson-plan creation). */
  sourceVettingStatus?: VettingStatus;
  sourceVetted?: boolean;
  /** Number of lessons in this row (Lesson 1..N). */
  weekLessonCount?: number;
  /** Deterministic decomposition preview (atoms, warning/spill, preview labels). */
  decomposition?: DecompositionPreview;
  /** Phase 3.5 appendix provenance for the pill, tooltip and [Reset to Appendix]. */
  appendix?: {
    resources: string | null;
    assessment: string | null;
    source: string | null;
    level: AppendixLevel;
  };
}

/** One column of the KICD table - defined by the template file, not by code. */
export interface SchemeColumn {
  key: string;
  index: number;
  label: string;
  source: string;
  width?: string;
  align?: string;
  verbatim?: boolean;
  fallback?: string;
  editable?: boolean;
  alwaysEmpty?: boolean;
  placeholder?: string;
}

export interface SchemeHeaderField {
  key: string;
  label: string;
  source: "teacher" | "source" | "profile" | "derived";
  required: boolean;
  placeholder?: string;
  editable?: boolean;
}

export interface SchemeHeader {
  institution: string;
  grade: string;
  learningArea: string;
  term: string;
  year: string;
  teacherName: string;
  tscNo: string;
  generalOutcomes: string;
}

export interface SchemeAllocation {
  lessonsPerWeek: number;
  totalWeeks: number;
  totalLessons: number;
  capacity: number;
  fits: boolean;
  warning: string | null;
  startWeek?: number;
  lessonMode?: string;
}

export interface PlanTreeNode {
  strandCode: string | null;
  strand: string;
  sectionCount: number;
  sections: PlanSection[];
}

/** Lightweight list payload from GET /api/plans. */
export interface PlanSummary {
  id: string;
  type: PlanType;
  title: string;
  grade: string;
  subject: string;
  term: string;
  status: PlanStatus;
  templateVersion: string;
  createdAt: string;
  sectionCount: number;
  totalLessons?: number;
  warning?: string | null;
}

export interface PlanDocument {
  id: string;
  type: PlanType;
  typeLabel: string;
  title: string;
  grade: string;
  subject: string;
  term: string;
  templateVersion: string;
  status: PlanStatus;
  aiExpanded: boolean;
  /** Phase 4: true while there are unsaved edits ("Dirty - Unsaved"). */
  dirty?: boolean;
  finalVersionLabel?: string | null;
  createdAt: string;
  updatedAt: string;
  sourceChunkIds: string[];
  sectionCount: number;
  columns: SchemeColumn[];
  headerFields: SchemeHeaderField[];
  footer: Record<string, string>;
  landscape: boolean;
  header: SchemeHeader;
  allocation: SchemeAllocation;
  sources: string[];
  sections: PlanSection[];
  tree: PlanTreeNode[];
}

/** A source chunk as offered on the Create screen, with vetting state attached. */
export interface CatalogChunk extends SourceChunk {
  vettingStatus: VettingStatus;
  missingCore: string[];
  selectable: boolean;
}

export interface CatalogDocument {
  documentId: string;
  fileName: string;
  grade: string;
  subject: string;
  archetype: string | null;
  status: DocumentStatus;
  vettedCount: number;
  totalCount: number;
  allVetted: boolean;
  chunks: CatalogChunk[];
}

export interface VettingCatalog {
  documents: CatalogDocument[];
}

// ---------------------------------------------------------------------------
// Phase 4 - version history, decomposition and KICD lesson plans
// ---------------------------------------------------------------------------

export interface DecompositionAtom {
  text: string;
  focus: string;
  focus_keyword?: string;
  pattern?: string;
  source_quote?: string;
}

export interface DecompositionAssignment {
  lesson: number;
  kind: "atomic" | "consolidation" | "assessment";
  focus: string;
  focus_keyword?: string;
  atomic?: DecompositionAtom | null;
  source_quote?: string;
}

export interface DecompositionPreview {
  atoms: DecompositionAtom[];
  assignments: DecompositionAssignment[];
  warnings: string[];
  spill?: string[];
  preview?: string[];
  lessonCount?: number;
}

export interface PlanVersion {
  id: string;
  planId?: string;
  versionNumber: number;
  label: string;
  comment: string;
  kind?: string;
  createdAt: string;
}

export interface PlanVersionList {
  versions: PlanVersion[];
  count: number;
}

export interface PlanDiffCell {
  sectionId: string | null;
  week: number | null;
  field: string;
  label: string;
  from: string;
  to: string;
  status: "changed" | "added" | "removed";
}

export interface PlanDiff {
  version: PlanVersion;
  from: string;
  to: string;
  cells: PlanDiffCell[];
  summary: { changed: number; added: number; removed: number };
}

export interface AIStatus {
  available: boolean;
  provider: string;
  model: string;
  message: string;
}

export interface LessonStepData {
  time: string;
  teacherActivity: string;
  learnerActivity: string;
}

export interface LessonAssessmentData {
  method: string;
  description: string;
  sampleItems: string[];
  rubricIndicator: string;
}

export interface LessonPlanSection {
  id: string;
  ord: number;
  key: string;
  title: string;
  body: string;
  data: Record<string, any>;
  sourceBody: string;
  sourceData: Record<string, any>;
  editedFromSource: boolean;
  placeholder: string | null;
  hint: string | null;
  provenance: string;
  sourceQuote: string | null;
  editable: boolean;
  aiDraft: string | null;
  aiAssisted: boolean;
  aiProvider: string | null;
  aiTimestamp: string | null;
}

export interface LessonPlan {
  id: string;
  schemeId: string;
  sectionId: string;
  chunkId: string | null;
  documentId: string | null;
  week: number;
  lesson: number;
  lessonCount: number;
  strand: string | null;
  subStrand: string | null;
  subStrandCode: string | null;
  focus: string;
  focusKeyword: string;
  sourceExperience: string;
  date: string;
  time: string;
  duration: number;
  classSize: number | null;
  status: "Draft" | "Final";
  templateVersion: string;
  templateName: string;
  gradeBand: "primary" | "jss" | string;
  defaultDuration: number;
  durationOptions: number[];
  durationModes: Record<string, number>;
  developmentHint: string;
  development: Record<string, any>;
  typeLabel: string;
  sloHeading: string;
  sourceOutcomesHeading: string;
  sloWarning: string | null;
  sloFixable: boolean;
  headerFields: SchemeHeaderField[];
  adminFields: Record<string, any>[];
  sectionTemplate: Record<string, any>[];
  assessmentTemplate: Record<string, any>;
  header: Record<string, string | number | null>;
  headerSource: Record<string, string | number | null>;
  headerEditedFields: string[];
  source: {
    strand?: string;
    subStrand?: string;
    outcomes?: string[];
    experiences?: string[];
    kiqs?: string[];
    competencies?: string | null;
    values?: string | null;
    pcis?: string | null;
    linkOther?: string | null;
    resources?: string | null;
    appendixResources?: string | null;
    rubric?: Record<string, unknown>[];
    schemeAssessment?: string;
    sourceLabel?: string;
  };
  assessment: {
    planned: string;
    differentiation: string;
    rubric?: Record<string, unknown>[];
  };
  aiEnriched: boolean;
  aiProvider: string | null;
  aiTimestamp: string | null;
  aiExtras: { commonMisconception?: string; teacherQuestions?: string } | Record<string, never>;
  ai: AIStatus;
  createdAt: string;
  updatedAt: string;
  sections: LessonPlanSection[];
  versions: PlanVersion[];
}

export interface LessonPickerItem {
  lesson: number;
  focus: string;
  kind: string;
  created: boolean;
  lessonPlanId: string | null;
  status: string | null;
  date: string;
}

export interface LessonPicker {
  sectionId: string;
  planId: string;
  week: number;
  strand: string | null;
  subStrand: string;
  subStrandCode: string | null;
  lessonCount: number;
  lessonRange: string;
  sourceVetted: boolean;
  vettingMessage: string | null;
  createdCount: number;
  lessons: LessonPickerItem[];
  decomposition: DecompositionPreview;
  templateVersion: string;
  gradeBand: "primary" | "jss" | string;
  defaultDuration: number;
  durationOptions: number[];
  developmentHint: string;
}

export interface LessonPlanList {
  plans: {
    id: string;
    planId: string;
    planTitle: string;
    grade: string;
    subject: string;
    term: string;
    sectionId: string;
    week: number;
    lesson: number;
    lessonCount: number;
    strand: string | null;
    subStrand: string | null;
    subStrandCode: string | null;
    focus: string;
    status: string;
    date: string;
    duration: number;
  }[];
  groups: {
    planId: string;
    planTitle: string;
    grade: string;
    subject: string;
    term: string;
    sectionId: string;
    week: number;
    strand: string | null;
    subStrand: string | null;
    subStrandCode: string | null;
    lessonCount: number;
    lessons: {
      id: string;
      lesson: number;
      status: string;
      date: string;
      focus: string;
      duration: number;
    }[];
  }[];
  count: number;
}

export interface LessonDiff {
  version: PlanVersion;
  from: string;
  to: string;
  cells: { field: string; label: string; from: string; to: string; status: string }[];
  summary: { changed: number; added: number; removed: number };
}

export interface WebExample {
  title: string;
  url: string;
  snippet: string;
  source?: string;
}

export interface WebSearchResponse {
  query: string;
  results: WebExample[];
  provider: string;
  message?: string;
}

// ---------------------------------------------------------------------------
// Phase 6 - Settings: AI providers + web search providers
// ---------------------------------------------------------------------------

export interface AIConfig {
  provider: string;
  apiKey: string; // always empty in GET responses (masked server-side)
  maskedKey: string;
  hasKey: boolean;
  keySource: "saved" | "environment" | "none";
  keyEnv: string;
  keyRequired: boolean;
  model: string;
  baseUrl: string;
  timeoutSeconds: number;
  temperature: number;
}

export interface SearchConfig {
  provider: string;
  apiKey: string;
  maskedKey: string;
  hasKey: boolean;
  keySource: "saved" | "environment" | "none";
  keyEnv: string;
  keyRequired: boolean;
  baseUrl: string;
  timeoutSeconds: number;
  maxResults: number;
  verifyLinks: boolean;
  minScore: number;
}

export interface ProviderInfo {
  id: string;
  label: string;
  tagline: string;
  recommended: boolean;
  free: boolean;
  keyRequired: boolean;
  keyEnv: string;
  signupUrl: string;
  docsUrl: string;
  defaultModel?: string;
  baseUrl: string;
  quota: string;
  note: string;
}

export interface SettingsPayload {
  settings: {
    ai: AIConfig;
    search: SearchConfig;
    settingsPath: string;
    updatedAt: string;
  };
  catalog: { ai: ProviderInfo[]; search: ProviderInfo[] };
  ai: AIStatus;
  search: { provider: string; label: string; available: boolean; message: string };
}

export interface SettingsDraft {
  ai: {
    provider: string;
    apiKey: string;
    model: string;
    baseUrl: string;
    timeoutSeconds: number;
    temperature: number;
  };
  search: {
    provider: string;
    apiKey: string;
    baseUrl: string;
    timeoutSeconds: number;
    maxResults: number;
    verifyLinks: boolean;
    minScore: number;
  };
}

export interface AITestResult {
  ok: boolean;
  provider: string;
  model: string;
  latencyMs: number;
  sample?: string;
  message: string;
}

export interface SearchTestResult {
  ok: boolean;
  provider: string;
  query: string;
  latencyMs: number;
  results: WebExample[];
  message: string;
  errors: string[];
}

export interface ModelsResponse {
  provider: string;
  models: string[];
  count: number;
}

// ---------------------------------------------------------------------------
// Phase 5 - learner-facing Lesson Notes (one document per lesson)
// ---------------------------------------------------------------------------

export interface VocabularyItem {
  word: string;
  definition: string;
  example: string;
  source: "From source" | "AI" | "Web" | string;
}

export interface ExampleItem {
  text: string;
  source?: string;
  url?: string;
}

export interface PracticeItem {
  question: string;
  answer: string;
}

export interface LessonNoteSection {
  id: string;
  ord: number;
  key: string;
  title: string;
  body: string;
  data: Record<string, any>;
  sourceBody: string;
  sourceData: Record<string, any>;
  editedFromSource: boolean;
  placeholder: string | null;
  hint: string | null;
  provenance: string;
  editable: boolean;
  aiDraft: string | null;
  aiData: Record<string, any>;
  aiAssisted: boolean;
  aiProvider: string | null;
  aiTimestamp: string | null;
}

export interface LessonNoteSource {
  id: string;
  kind: "teacher" | "web" | "source" | string;
  title: string | null;
  url: string | null;
  text: string | null;
  createdAt: string;
}

export interface LessonNote {
  id: string;
  lessonPlanId: string | null;
  schemeId: string;
  planId: string;
  schemeRowId: string;
  sectionId: string;
  chunkId: string | null;
  documentId: string | null;
  week: number;
  lesson: number;
  lessonCount: number;
  strand: string | null;
  subStrand: string | null;
  subStrandCode: string | null;
  focus: string;
  focusKeyword: string;
  title: string;
  grade: string;
  subject: string;
  term: string;
  status: "Draft" | "Final";
  templateVersion: string;
  templateName: string;
  gradeBand: "primary" | "jss" | string;
  typeLabel: string;
  sloHeading: string;
  practiceCount: number;
  picturePlaceholders: boolean;
  source: {
    strand?: string;
    subStrand?: string;
    subStrandCode?: string;
    page?: number | null;
    outcomes?: string[];
    outcomesHeading?: string;
    experiences?: string[];
    kiqs?: string[];
    competencies?: string | null;
    values?: string | null;
    pcis?: string | null;
    resources?: string | null;
    appendixResources?: string | null;
    appendixAssessment?: string | null;
    appendixSource?: string | null;
    rubric?: Record<string, unknown>[];
    schemeAssessment?: string;
    sourceLabel?: string;
    subject?: string;
    grade?: string;
    duration?: number;
  };
  sources: LessonNoteSource[];
  footer: string;
  aiEnriched: boolean;
  aiProvider: string | null;
  aiTimestamp: string | null;
  ai: AIStatus;
  createdAt: string;
  updatedAt: string;
  sections: LessonNoteSection[];
  versions: PlanVersion[];
  acceptedSections?: number;
  restoredVersion?: PlanVersion;
}

export interface LessonNoteSummary {
  id: string;
  lessonPlanId: string | null;
  planId: string;
  planTitle: string;
  grade: string;
  subject: string;
  term: string;
  sectionId: string;
  week: number;
  lesson: number;
  lessonCount: number;
  strand: string | null;
  subStrand: string | null;
  subStrandCode: string | null;
  focus: string;
  focusKeyword: string;
  title: string;
  status: string;
  aiEnriched: boolean;
  templateVersion: string;
  createdAt: string;
  updatedAt: string;
}

export interface LessonNotesList {
  notes: LessonNoteSummary[];
  schemes: {
    planId: string;
    planTitle: string;
    grade: string;
    subject: string;
    term: string;
    weeks: {
      week: number;
      lessons: {
        id: string;
        lesson: number;
        lessonCount: number;
        title: string;
        focus: string;
        status: string;
        aiEnriched: boolean;
        subStrand: string | null;
        subStrandCode: string | null;
      }[];
    }[];
  }[];
  count: number;
}

export interface NotesPickerItem {
  lesson: number;
  focus: string;
  title: string;
  kind: string;
  created: boolean;
  noteId: string | null;
  status: string | null;
}

export interface NotesPicker {
  sectionId: string;
  planId: string;
  week: number;
  strand: string | null;
  subStrand: string;
  subStrandCode: string | null;
  lessonCount: number;
  lessonRange: string;
  sourceVetted: boolean;
  vettingMessage: string | null;
  createdCount: number;
  lessons: NotesPickerItem[];
  decomposition: DecompositionPreview;
  templateVersion: string;
  gradeBand: "primary" | "jss" | string;
  practiceCount: number;
}

// ---------------------------------------------------------------------------
// Phase 6 - Record of Work (ROW): what WAS taught, teacher-filled after teaching
// ---------------------------------------------------------------------------

export type RowEntryStatus =
  | ""
  | "Taught"
  | "Not Taught - Carry Over"
  | "Not Taught - Skipped"
  | "Partially Taught";

export const ROW_STATUSES: RowEntryStatus[] = [
  "",
  "Taught",
  "Not Taught - Carry Over",
  "Not Taught - Skipped",
  "Partially Taught",
];

export interface RowHeader {
  school?: string;
  institution?: string;
  grade?: string;
  learningArea?: string;
  term?: string;
  year?: string;
  teacher?: string;
  tscNo?: string;
}

export interface RowCarryOverTarget {
  week: number;
  lesson: number;
}

export interface RecordOfWorkRow {
  id: string;
  docId: string;
  planId: string;
  schemeRowId: string;
  lessonPlanId: string | null;
  origin: "planned" | "carry-over";
  carryOverFromRowId: string | null;
  carryOverNote: string;
  date: string;
  dateInFuture: boolean;
  week: number;
  lesson: number;
  strand: string;
  subStrand: string;
  focusKeyword: string;
  plannedWork: string;
  workDone: string;
  isPlanned: boolean;
  reflection: string;
  status: RowEntryStatus;
  carryOverTo: RowCarryOverTarget | null;
  signature: string;
  source: string;
  teacherEdited: boolean;
  aiDraft: string | null;
  aiEnriched: boolean;
  aiProvider: string | null;
  aiTimestamp: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface RowGap {
  rowId: string;
  week: number;
  lesson: number;
  strand: string;
  subStrand: string;
  focusKeyword: string;
  status: RowEntryStatus;
  reason: string;
  carryOverTo: RowCarryOverTarget | null;
  origin: string;
}

export interface RowCoverage {
  planned: number;
  taught: number;
  partially: number;
  notTaught: number;
  carryOver: number;
  unrecorded: number;
  coveragePct: number;
  coverageLabel: string;
  carryOverRows: number;
  gaps: RowGap[];
  warning: string | null;
}

export interface RecordOfWorkDoc {
  id: string;
  planId: string;
  title: string;
  schemeTitle: string;
  status: "Draft" | "Final";
  finalVersionLabel: string | null;
  header: RowHeader;
  rowExists: boolean;
  rows: RecordOfWorkRow[];
  coverage: RowCoverage;
  versions: PlanVersion[];
  ai: AIStatus;
  createdAt: string;
  updatedAt: string;
  focusRowId?: string | null;
  // Optional echoes returned by mutating endpoints.
  created?: number;
  updated?: number;
  message?: string;
  rowId?: string;
  restoredVersion?: string;
  newRow?: RecordOfWorkRow;
  originalRow?: RecordOfWorkRow;
}

export interface RowScheme {
  planId: string;
  title: string;
  grade: string;
  subject: string;
  term: string;
  schemeStatus: string;
  sectionCount: number;
  rowExists: boolean;
  rowCount: number;
  taught: number;
  rowStatus: string;
}

export interface RowSchemeList {
  schemes: RowScheme[];
  count: number;
}

export interface RowEditResult {
  row: RecordOfWorkRow;
  coverage: RowCoverage;
}

export interface RowDiffCell {
  field: string;
  label: string;
  from: string;
  to: string;
  status: "added" | "removed" | "changed";
}

export interface RowDiff {
  version: PlanVersion;
  from: string;
  to: string;
  cells: RowDiffCell[];
  summary: { changed: number; added: number; removed: number };
}

export interface RowVersionPreview extends PlanVersion {
  snapshot: Partial<RecordOfWorkDoc>;
}

export interface RowVersionSaved {
  id: string;
  versionNumber: number;
  label: string;
  comment: string;
  kind: string;
  createdAt: string;
  recordOfWork: RecordOfWorkDoc;
}

/* -------------------------------------------------------------------------- */
/* Phase 7: Term Pack export bundle                                           */
/* -------------------------------------------------------------------------- */

export type ExportFormat = "pdf" | "zip";
export type ExportSelectionMode = "all" | "weeks" | "selected";

export interface ExportSelection {
  include: boolean;
  mode: ExportSelectionMode;
  weeks: number[];
  lessonIds: string[];
}

export interface ExportIncludes {
  cover: boolean;
  coverage: boolean;
  scheme: boolean;
  plans: ExportSelection;
  notes: ExportSelection;
  row: boolean;
  citations: boolean;
  includeDrafts: boolean;
  includeAnswers: boolean;
  includeVersionHistory: boolean;
  progress?: boolean;
  progressConfirm?: string;
}

export interface ExportSection {
  name: string;
  pages: number;
  orientation: "portrait" | "landscape";
}

export interface ExportManifest {
  planId?: string;
  grade?: string;
  subject?: string;
  term?: string;
  teacher?: string;
  generatedAt?: string;
  totalPages?: number;
  sections: ExportSection[];
  coverage?: { planned: number; taught: number; coveragePct: number };
  files?: ExportSection[];
}

export interface ExportJob {
  id: string;
  planId: string;
  teacherId: string;
  includes: ExportIncludes;
  format: ExportFormat;
  status: "queued" | "building" | "done" | "failed";
  progress: number;
  progressText: string;
  fileUrl: string;
  fileName: string;
  filePath?: string;
  fileSize: number;
  pageCount: number;
  manifest: ExportManifest;
  error: string;
  createdAt: string;
  updatedAt: string;
}

export interface ExportStartResult {
  jobId: string;
  status: string;
  progress: number;
}

export interface ExportPlanOption {
  id: string;
  title: string;
  grade: string;
  subject: string;
  term: string;
}

/* -------------------------------------------------------------------------- */
/* Phase 8: Coverage Dashboard                                                */
/* -------------------------------------------------------------------------- */

export type DashboardSubjectStatus =
  | "Complete" | "On Track" | "Behind" | "Not Started";

export interface DashboardWeekStat {
  week: number;
  planned: number;
  taught: number;
  partially: number;
  carryOver: number;
  cumulativePct: number;
}

export interface DashboardSubject {
  planId: string;
  subject: string;
  grade: string;
  term: string;
  year: string;
  teacher: string;
  rowExists: boolean;
  planned: number;
  taught: number;
  partially: number;
  notTaught: number;
  carryOver: number;
  coveragePct: number | null;
  status: DashboardSubjectStatus;
  lastTaughtWeek: number | null;
  byWeek: { week: number; planned: number; taught: number }[];
}

export interface DashboardGap {
  rowId: string;
  planId: string;
  subject: string;
  grade: string;
  term: string;
  week: number;
  lesson: number;
  focus: string;
  strand: string;
  status: RowEntryStatus;
  reason: string;
  carryOverTo: RowCarryOverTarget | null;
  origin: string;
}

export interface DashboardSummary {
  planned: number;
  taught: number;
  partially: number;
  notTaught: number;
  carryOver: number;
  coveragePct: number;
  onTrack: number;
  behind: number;
  complete: number;
  gapsThisWeek: number;
  withoutRow: number;
}

export interface DashboardFilters {
  term?: string;
  year?: string;
  grade?: string;
  subject?: string;
  week?: number;
  teacher?: string;
}

export interface DashboardData {
  summary: DashboardSummary;
  bySubject: DashboardSubject[];
  byWeek: DashboardWeekStat[];
  gaps: DashboardGap[];
  partiallyTaught: DashboardGap[];
  nextWeek: {
    week: number;
    planned: number;
    carryOver: number;
    total: number;
    overloaded: boolean;
  };
  filters: Record<string, string[]>;
  appliedFilters: Required<DashboardFilters>;
  currentWeek: number;
  reflections: {
    planId: string; term: string; year: string;
    reflection: string; updatedAt: string;
  }[];
  lastUpdated: string;
}

export interface DashboardReflection {
  planId: string;
  term: string;
  year: string;
  reflection: string;
  updatedAt: string;
}

// ---- Phase 9: individual teacher account -----------------------------------
export interface AuthUser {
  id: string;
  email: string;
  name: string;
  role: "Teacher";
  tscNo: string;
  county: string;
  schoolName: string;
  grades: string[];
  subjects: string[];
  preferences: {
    defaultTerm?: string;
    defaultYear?: string;
    notesFontSize?: number;
    answersInNotesPdf?: boolean;
  };
  needsProfileConfirm: boolean;
  createdAt: string;
}

export interface AuthResult {
  ok?: boolean;
  message?: string;
  resetToken?: string;
  resetUrl?: string;
  expiresAt?: string;
}

// ---- Phase 10: My Learners, Assessment, Progress and IEP -------------------
export type LearnerStatus = "Active" | "Transferred" | "Left";
export type AssessmentLevel = "Not Assessed" | "Below" | "Approaching" | "Meets" | "Exceeds";
export type IepStatus = "Active" | "Met Goal" | "Review Needed" | "Closed";

export interface Learner {
  id: string;
  ownerId?: string;
  grade: string;
  learningArea: string;
  className: string;
  firstName: string;
  lastName: string;
  name: string;
  admissionNo: string;
  gender: string;
  status: LearnerStatus;
  createdAt: string;
  updatedAt: string;
}

export interface LearnerGroup {
  grade: string;
  learningArea: string;
  className: string;
  count: number;
  learners: Learner[];
}

export interface LearnersList {
  learners: Learner[];
  count: number;
  groups: LearnerGroup[];
}

export interface LearnerSummary {
  active: number;
  needsSupport: number;
  iepsActive: number;
  iepReviewsDue: number;
}

export interface AssessmentRecord {
  id: string;
  learnerId: string;
  schemeRowId: string;
  chunkId: string;
  strand: string;
  subStrand: string;
  focusKeyword: string;
  week: number;
  lesson: number;
  level: AssessmentLevel;
  evidence: string;
  date: string;
  source: string;
  createdAt: string;
  updatedAt: string;
}

export interface RubricEntry {
  indicator: string;
  page: number;
  levels: Record<string, string>;
}

export interface AssessmentContext {
  schemeRowId: string;
  week: number;
  lesson: number;
  grade: string;
  learningArea: string;
  term: string;
  strand: string;
  subStrand: string;
  focus: string;
  chunkId: string;
  vettingStatus: string;
  canAssess: boolean;
  reason: string;
  rubric: RubricEntry[];
  pageNumber?: number | null;
}

export interface AssessmentAuditEntry {
  learnerId: string;
  oldLevel: string;
  newLevel: string;
  changedBy: string;
  changedAt: string;
  reason: string;
}

export interface FocusProgress {
  focus: string;
  level: AssessmentLevel;
  date: string;
  trend: "↑" | "→" | "↓" | "—";
  evidence: string;
  source: string;
  week: number;
  lesson: number;
  history: { level: string; date: string; evidence: string; source: string }[];
}

export interface LearnerProgress {
  learnerId: string;
  name: string;
  grade: string;
  learningArea: string;
  className: string;
  byFocus: FocusProgress[];
  overall: AssessmentLevel;
  needsSupport: boolean;
}

export interface ProgressData {
  learners: LearnerProgress[];
  count: number;
  classSummary: Record<AssessmentLevel, number>;
  needsSupport: LearnerProgress[];
  needsSupportCount: number;
}

export interface IepReview {
  date: string;
  note: string;
  newLevel: string;
}

export interface Iep {
  id: string;
  learnerId: string;
  learner?: Learner;
  need: string;
  goal: string;
  support: string;
  materials: string;
  reviewDate: string;
  reviewWeek: number;
  status: IepStatus;
  reviewNeeded: boolean;
  aiEnriched: boolean;
  reviews: IepReview[];
  createdAt: string;
  updatedAt: string;
}

export interface AssessTarget {
  schemeRowId: string;
  week?: number;
  lesson?: number;
  grade?: string;
  learningArea?: string;
  className?: string;
}

export interface AssessOption {
  schemeRowId: string;
  subStrand: string;
  code: string;
  grade: string;
  learningArea: string;
  term: string;
  canAssess: boolean;
  reason: string;
}
export interface AssessOptions {
  options: AssessOption[];
  count: number;
}
