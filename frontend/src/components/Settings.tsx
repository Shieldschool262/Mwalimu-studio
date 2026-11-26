import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type {
  AITestResult,
  ProviderInfo,
  SearchTestResult,
  SettingsDraft,
  SettingsPayload,
  WebExample,
} from "../types";
import { Badge } from "./ui";

type Props = {
  onToast: (message: string) => void;
  onError: (message: string | null) => void;
};

function toDraft(p: SettingsPayload): SettingsDraft {
  return {
    ai: {
      provider: p.settings.ai.provider,
      apiKey: "",
      model: p.settings.ai.model,
      baseUrl: p.settings.ai.baseUrl,
      timeoutSeconds: p.settings.ai.timeoutSeconds,
      temperature: p.settings.ai.temperature,
    },
    search: {
      provider: p.settings.search.provider,
      apiKey: "",
      baseUrl: p.settings.search.baseUrl,
      timeoutSeconds: p.settings.search.timeoutSeconds,
      maxResults: p.settings.search.maxResults,
      verifyLinks: p.settings.search.verifyLinks,
      minScore: p.settings.search.minScore,
    },
  };
}

const SAMPLE_QUERY = "Kenya CBC Grade 1 counting classroom activity";

/** Free provider options with no credit card required. */
const VERIFIED_PICKS: {
  kind: "AI" | "Web search";
  name: string;
  free: string;
  why: string;
  url: string;
  linkLabel: string;
}[] = [
  {
    kind: "AI",
    name: "Google Gemini · gemini-3.5-flash-lite",
    free: "Free tier, no card · ~50–250 req/day",
    why: "Fast free-tier Flash-Lite model that returns structured JSON reliably.",
    url: "https://aistudio.google.com/apikey",
    linkLabel: "Get free key",
  },
  {
    kind: "AI",
    name: "OpenRouter · openrouter/free",
    free: "50 req/day (1,000 after $10 credit)",
    why: "One key routes to whichever free model is healthy. No credit card needed.",
    url: "https://openrouter.ai/keys",
    linkLabel: "Get free key",
  },
  {
    kind: "AI",
    name: "Groq · openai/gpt-oss-120b",
    free: "Free developer tier",
    why: "Very fast OpenAI-compatible endpoint; good fallback when Gemini is rate limited.",
    url: "https://console.groq.com/keys",
    linkLabel: "Get free key",
  },
  {
    kind: "AI",
    name: "Ollama (local)",
    free: "Unlimited, fully offline",
    why: "No key and no network. Install Ollama, pull a model, and point Base URL at localhost:11434.",
    url: "https://ollama.com/download",
    linkLabel: "Download",
  },
  {
    kind: "Web search",
    name: "DuckDuckGo HTML",
    free: "No key, no signup",
    why: "No account needed; returns relevant classroom activity links. Default in this app.",
    url: "https://html.duckduckgo.com/",
    linkLabel: "Open",
  },
  {
    kind: "Web search",
    name: "Tavily Search",
    free: "1,000 free credits / month",
    why: "Clean JSON with snippets; the most reliable keyed option for AI apps.",
    url: "https://app.tavily.com/",
    linkLabel: "Get free key",
  },
  {
    kind: "Web search",
    name: "Serper",
    free: "2,500 free Google queries",
    why: "Google results via a simple JSON API; good if DuckDuckGo is blocked on your network.",
    url: "https://serper.dev/",
    linkLabel: "Get free key",
  },
  {
    kind: "Web search",
    name: "Wikipedia API",
    free: "No key, always available",
    why: "Encyclopedic background rather than activity ideas, but never rate limited.",
    url: "https://www.mediawiki.org/wiki/API:Search",
    linkLabel: "Docs",
  },
];

export default function Settings({ onToast, onError }: Props) {
  const [payload, setPayload] = useState<SettingsPayload | null>(null);
  const [draft, setDraft] = useState<SettingsDraft | null>(null);
  const [baseline, setBaseline] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showAIKey, setShowAIKey] = useState(false);
  const [showSearchKey, setShowSearchKey] = useState(false);
  const [aiTest, setAiTest] = useState<AITestResult | null>(null);
  const [searchTest, setSearchTest] = useState<SearchTestResult | null>(null);
  const [testingAI, setTestingAI] = useState(false);
  const [testingSearch, setTestingSearch] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const [modelsBusy, setModelsBusy] = useState(false);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState(SAMPLE_QUERY);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.settings();
      const fresh = toDraft(data);
      setPayload(data);
      setDraft(fresh);
      setBaseline(JSON.stringify(fresh));
      onError(null);
    } catch (e) {
      onError(`Could not load settings: ${(e as Error).message}`);
    } finally {
      setLoading(false);
    }
  }, [onError]);

  useEffect(() => {
    void load();
  }, [load]);

  const dirty = useMemo(
    () => (draft ? JSON.stringify(draft) !== baseline : false),
    [draft, baseline],
  );

  const patchAI = (patch: Partial<SettingsDraft["ai"]>) => {
    setDraft((d) => (d ? { ...d, ai: { ...d.ai, ...patch } } : d));
    setAiTest(null);
  };

  const patchSearch = (patch: Partial<SettingsDraft["search"]>) => {
    setDraft((d) => (d ? { ...d, search: { ...d.search, ...patch } } : d));
    setSearchTest(null);
  };

  const chooseProvider = (kind: "ai" | "search", meta: ProviderInfo) => {
    if (kind === "ai") {
      patchAI({
        provider: meta.id,
        model: meta.defaultModel || "",
        baseUrl: meta.baseUrl || "",
        apiKey: "",
      });
      setModels([]);
      setModelsError(null);
    } else {
      patchSearch({ provider: meta.id, baseUrl: meta.baseUrl || "", apiKey: "" });
    }
  };

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    try {
      const res = await api.saveSettings(draft);
      const fresh = toDraft(res);
      setPayload(res);
      setDraft(fresh);
      setBaseline(JSON.stringify(fresh));
      onError(null);
      onToast("AI & Web Search settings saved ✓");
    } catch (e) {
      onError(`Could not save settings: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  const reset = async () => {
    if (!window.confirm("Reset AI and web search settings to defaults?")) return;
    try {
      const res = await api.resetSettings();
      const fresh = toDraft(res);
      setPayload(res);
      setDraft(fresh);
      setBaseline(JSON.stringify(fresh));
      setAiTest(null);
      setSearchTest(null);
      setModels([]);
      onToast("Settings reset to defaults");
    } catch (e) {
      onError(`Could not reset settings: ${(e as Error).message}`);
    }
  };

  const testAI = async () => {
    if (!draft) return;
    setTestingAI(true);
    setAiTest(null);
    try {
      setAiTest(await api.testAI(draft.ai));
    } catch (e) {
      setAiTest({
        ok: false,
        provider: draft.ai.provider,
        model: draft.ai.model,
        latencyMs: 0,
        message: (e as Error).message,
      });
    } finally {
      setTestingAI(false);
    }
  };

  const testSearch = async () => {
    if (!draft) return;
    setTestingSearch(true);
    setSearchTest(null);
    try {
      setSearchTest(await api.testSearch(draft.search, searchQuery));
    } catch (e) {
      setSearchTest({
        ok: false,
        provider: draft.search.provider,
        query: searchQuery,
        latencyMs: 0,
        results: [],
        message: (e as Error).message,
        errors: [],
      });
    } finally {
      setTestingSearch(false);
    }
  };

  const fetchModels = async () => {
    if (!draft) return;
    setModelsBusy(true);
    setModelsError(null);
    try {
      const res = await api.settingsModels(draft.ai.provider, draft.ai);
      setModels(res.models);
    } catch (e) {
      setModels([]);
      setModelsError((e as Error).message);
    } finally {
      setModelsBusy(false);
    }
  };

  if (loading || !payload || !draft) {
    return (
      <div className="card text-sm text-muted" data-testid="settings-loading">
        Loading settings…
      </div>
    );
  }

  const aiMeta = payload.catalog.ai.find((p) => p.id === draft.ai.provider) || payload.catalog.ai[0];
  const searchMeta =
    payload.catalog.search.find((p) => p.id === draft.search.provider) || payload.catalog.search[0];
  const showBaseUrl =
    draft.ai.provider === "ollama" || draft.ai.provider === "openai-compatible" || Boolean(aiMeta.baseUrl);
  const showSearchBaseUrl = draft.search.provider === "searxng" || Boolean(searchMeta.baseUrl);

  return (
    <div className="space-y-5 pb-3" data-testid="settings-page">
      {/* ------------------------------------------------------------------ */}
      <div className="card">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-extrabold text-ink">AI &amp; Web Search</h2>
            <p className="mt-1 max-w-2xl text-xs leading-relaxed text-muted">
              Choose which provider <strong>Draft with AI</strong> and <strong>Web examples</strong> use.
              Settings are saved on this machine in{" "}
              <code className="rounded bg-slate-100 px-1">backend/settings.json</code> (gitignored) and
              take priority over <code className="rounded bg-slate-100 px-1">.env</code>. Keys are never
              sent back to the browser in full.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge tone={payload.ai.available ? "green" : "red"}>
              <span className="h-1.5 w-1.5 rounded-full bg-current" />
              AI {payload.ai.available ? "ready" : "not configured"}
            </Badge>
            <Badge tone={payload.search.available ? "green" : "amber"}>
              <span className="h-1.5 w-1.5 rounded-full bg-current" />
              Search {payload.search.available ? "ready" : "off"}
            </Badge>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 border-t border-line pt-3 text-[11px] text-muted">
          <span>
            AI: <strong className="text-ink">{payload.ai.provider}</strong> · {payload.ai.model || "—"}
          </span>
          <span>
            Search: <strong className="text-ink">{payload.search.label}</strong>
          </span>
          <span>
            Key source: <strong className="text-ink">{payload.settings.ai.keySource}</strong>
          </span>
        </div>
      </div>

      {/* ------------------------------------------------------------------ */}
      <div className="grid gap-5 xl:grid-cols-2">
        {/* AI -------------------------------------------------------------- */}
        <section className="card space-y-4" data-testid="settings-ai-section">
          <div>
            <h3 className="text-[15px] font-bold text-ink">AI provider</h3>
            <p className="mt-0.5 text-xs text-muted">
              Used by [✨ Draft with AI] and [Suggest split]. AI stays opt-in and never changes
              Outcomes, KIQ or Resources.
            </p>
          </div>

          <ProviderGrid
            items={payload.catalog.ai}
            value={draft.ai.provider}
            onPick={(m) => chooseProvider("ai", m)}
            testPrefix="ai"
          />

          <p className="rounded-lg border border-line bg-slate-50 px-3 py-2 text-[11px] leading-relaxed text-slate-600">
            <strong>{aiMeta.label}:</strong> {aiMeta.note}
            <br />
            <span className="text-slate-500">Free quota: {aiMeta.quota}</span>
          </p>

          {draft.ai.provider !== "off" ? (
            <>
              {aiMeta.keyRequired ? (
                <KeyField
                  label="API key"
                  value={draft.ai.apiKey}
                  masked={payload.settings.ai.maskedKey}
                  source={payload.settings.ai.keySource}
                  keyEnv={payload.settings.ai.keyEnv}
                  show={showAIKey}
                  onToggleShow={() => setShowAIKey((v) => !v)}
                  onChange={(v) => patchAI({ apiKey: v })}
                  onClear={() => patchAI({ apiKey: "__clear__" })}
                  signupUrl={aiMeta.signupUrl}
                />
              ) : (
                <p className="rounded-lg border border-brand-200 bg-brand-50 px-3 py-2 text-[11px] text-brand-800">
                  This provider needs no API key.
                </p>
              )}

              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Model" hint="Small Flash-Lite models are fastest on free tiers.">
                  <div className="flex gap-1.5">
                    <input
                      className="input min-w-0 flex-1 font-mono text-xs"
                      value={draft.ai.model}
                      onChange={(e) => patchAI({ model: e.target.value })}
                      placeholder="model id"
                      data-testid="settings-ai-model"
                      list="settings-model-list"
                    />
                    <button
                      className="btn-mini whitespace-nowrap"
                      onClick={() => void fetchModels()}
                      disabled={modelsBusy}
                      title="List models available to your key"
                      data-testid="settings-fetch-models"
                    >
                      {modelsBusy ? "Loading…" : "Fetch models"}
                    </button>
                  </div>
                  <datalist id="settings-model-list">
                    {models.map((m) => (
                      <option key={m} value={m} />
                    ))}
                  </datalist>
                  {models.length ? (
                    <p className="mt-1 text-[10px] text-emerald-700">
                      {models.length} models available — click the field to pick one.
                    </p>
                  ) : null}
                  {modelsError ? (
                    <p className="mt-1 text-[10px] text-rose-700">{modelsError}</p>
                  ) : null}
                </Field>
                <Field label="Timeout (seconds)" hint="Lower values fail fast instead of hanging.">
                  <input
                    className="input w-full"
                    type="number"
                    min={5}
                    max={180}
                    value={draft.ai.timeoutSeconds}
                    onChange={(e) => patchAI({ timeoutSeconds: Number(e.target.value) })}
                    data-testid="settings-ai-timeout"
                  />
                </Field>
              </div>

              {showBaseUrl ? (
                <Field label="Base URL" hint="OpenAI-compatible /chat/completions endpoint.">
                  <input
                    className="input w-full font-mono text-xs"
                    value={draft.ai.baseUrl}
                    onChange={(e) => patchAI({ baseUrl: e.target.value })}
                    placeholder="https://…/v1"
                    data-testid="settings-ai-baseurl"
                  />
                </Field>
              ) : null}

              <Field label={`Temperature: ${draft.ai.temperature}`} hint="0 = deterministic, 1 = creative.">
                <input
                  className="w-full accent-brand-600"
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={draft.ai.temperature}
                  onChange={(e) => patchAI({ temperature: Number(e.target.value) })}
                  data-testid="settings-ai-temperature"
                />
              </Field>

              <div className="flex flex-wrap items-center gap-2">
                <button
                  className="btn-ghost text-xs"
                  onClick={() => void testAI()}
                  disabled={testingAI}
                  data-testid="settings-test-ai"
                >
                  {testingAI ? "Testing…" : "⚡ Test AI connection"}
                </button>
                {aiMeta.docsUrl ? (
                  <a
                    className="text-[11px] font-semibold text-brand-700 underline"
                    href={aiMeta.docsUrl}
                    target="_blank"
                    rel="noreferrer"
                  >
                    API docs ↗
                  </a>
                ) : null}
              </div>
              {aiTest ? <TestPanel ok={aiTest.ok} message={aiTest.message} ms={aiTest.latencyMs} /> : null}
            </>
          ) : null}
        </section>

        {/* Web search ------------------------------------------------------- */}
        <section className="card space-y-4" data-testid="settings-search-section">
          <div>
            <h3 className="text-[15px] font-bold text-ink">Web search provider</h3>
            <p className="mt-0.5 text-xs text-muted">
              Used by [Web examples] in lesson plans and lesson notes. Search is teacher-initiated;
              nothing is inserted automatically.
            </p>
          </div>

          <ProviderGrid
            items={payload.catalog.search}
            value={draft.search.provider}
            onPick={(m) => chooseProvider("search", m)}
            testPrefix="search"
          />

          <p className="rounded-lg border border-line bg-slate-50 px-3 py-2 text-[11px] leading-relaxed text-slate-600">
            <strong>{searchMeta.label}:</strong> {searchMeta.note}
            <br />
            <span className="text-slate-500">Free quota: {searchMeta.quota}</span>
          </p>

          {draft.search.provider !== "off" ? (
            <>
              {searchMeta.keyRequired ? (
                <KeyField
                  label="API key"
                  value={draft.search.apiKey}
                  masked={payload.settings.search.maskedKey}
                  source={payload.settings.search.keySource}
                  keyEnv={payload.settings.search.keyEnv}
                  show={showSearchKey}
                  onToggleShow={() => setShowSearchKey((v) => !v)}
                  onChange={(v) => patchSearch({ apiKey: v })}
                  onClear={() => patchSearch({ apiKey: "__clear__" })}
                  signupUrl={searchMeta.signupUrl}
                />
              ) : (
                <p className="rounded-lg border border-brand-200 bg-brand-50 px-3 py-2 text-[11px] text-brand-800">
                  This provider needs no API key.
                </p>
              )}

              <div className="grid gap-3 sm:grid-cols-3">
                <Field label="Max results">
                  <input
                    className="input w-full"
                    type="number"
                    min={1}
                    max={10}
                    value={draft.search.maxResults}
                    onChange={(e) => patchSearch({ maxResults: Number(e.target.value) })}
                    data-testid="settings-search-max"
                  />
                </Field>
                <Field label="Timeout (s)">
                  <input
                    className="input w-full"
                    type="number"
                    min={5}
                    max={60}
                    value={draft.search.timeoutSeconds}
                    onChange={(e) => patchSearch({ timeoutSeconds: Number(e.target.value) })}
                    data-testid="settings-search-timeout"
                  />
                </Field>
                <Field label="Min score" hint="0 = keep all results; raise it to filter weaker matches.">
                  <input
                    className="input w-full"
                    type="number"
                    min={-100}
                    max={100}
                    value={draft.search.minScore}
                    onChange={(e) => patchSearch({ minScore: Number(e.target.value) })}
                    data-testid="settings-search-minscore"
                  />
                </Field>
              </div>

              {showSearchBaseUrl ? (
                <Field label="Base URL" hint="Endpoint used by this provider.">
                  <input
                    className="input w-full font-mono text-xs"
                    value={draft.search.baseUrl}
                    onChange={(e) => patchSearch({ baseUrl: e.target.value })}
                    data-testid="settings-search-baseurl"
                  />
                </Field>
              ) : null}

              <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-line bg-white px-3 py-2 text-xs">
                <input
                  className="mt-0.5 accent-brand-600"
                  type="checkbox"
                  checked={draft.search.verifyLinks}
                  onChange={(e) => patchSearch({ verifyLinks: e.target.checked })}
                  data-testid="settings-search-verify"
                />
                <span>
                  <strong className="text-ink">Verify links with a HEAD request</strong>
                  <span className="block text-[11px] text-muted">
                    Off by default. Many education sites reject HEAD requests, so enabling this may
                    discard good results.
                  </span>
                </span>
              </label>

              <Field label="Test query">
                <input
                  className="input w-full"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  data-testid="settings-search-query"
                />
              </Field>

              <div className="flex flex-wrap items-center gap-2">
                <button
                  className="btn-ghost text-xs"
                  onClick={() => void testSearch()}
                  disabled={testingSearch}
                  data-testid="settings-test-search"
                >
                  {testingSearch ? "Searching…" : "🔎 Test web search"}
                </button>
                {searchMeta.docsUrl ? (
                  <a
                    className="text-[11px] font-semibold text-brand-700 underline"
                    href={searchMeta.docsUrl}
                    target="_blank"
                    rel="noreferrer"
                  >
                    API docs ↗
                  </a>
                ) : null}
              </div>

              {searchTest ? (
                <>
                  <TestPanel
                    ok={searchTest.ok}
                    message={searchTest.message}
                    ms={searchTest.latencyMs}
                  />
                  {searchTest.errors.length ? (
                    <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[11px] text-rose-800">
                      {searchTest.errors.join(" | ")}
                    </p>
                  ) : null}
                  {searchTest.results.length ? (
                    <ul className="space-y-1.5" data-testid="settings-search-results">
                      {searchTest.results.map((r: WebExample, i: number) => (
                        <li key={`${r.url}-${i}`} className="rounded-lg border border-line bg-white px-3 py-2">
                          <a
                            className="text-xs font-semibold text-brand-700 hover:underline"
                            href={r.url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {r.title}
                          </a>
                          <p className="mt-0.5 text-[10px] text-muted">{r.source}</p>
                          {r.snippet ? (
                            <p className="mt-1 text-[11px] leading-snug text-slate-600">{r.snippet}</p>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </>
              ) : null}
            </>
          ) : null}
        </section>
      </div>

      {/* ------------------------------------------------------------------ */}
      <section className="card" data-testid="settings-free-picks">
        <h3 className="text-[15px] font-bold text-ink">Free providers</h3>
        <p className="mt-1 text-xs text-muted">
          All of these offer a free tier with no credit card. Brave Search no longer offers a free
          API plan, and Gemini Google Search grounding is quota-limited on free keys — neither is
          recommended.
        </p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[720px] text-left text-xs">
            <thead>
              <tr className="border-b border-line text-[10px] uppercase tracking-wide text-muted">
                <th className="py-2 pr-3 font-semibold">Type</th>
                <th className="py-2 pr-3 font-semibold">Provider</th>
                <th className="py-2 pr-3 font-semibold">Free allowance</th>
                <th className="py-2 pr-3 font-semibold">Why use it</th>
                <th className="py-2 font-semibold">Link</th>
              </tr>
            </thead>
            <tbody>
              {VERIFIED_PICKS.map((p) => (
                <tr key={p.name} className="border-b border-line/70 align-top last:border-0">
                  <td className="py-2 pr-3">
                    <Badge tone={p.kind === "AI" ? "green" : "blue"}>{p.kind}</Badge>
                  </td>
                  <td className="py-2 pr-3 font-semibold text-ink">{p.name}</td>
                  <td className="py-2 pr-3 text-muted">{p.free}</td>
                  <td className="py-2 pr-3 text-slate-600">{p.why}</td>
                  <td className="py-2">
                    <a
                      className="font-semibold text-brand-700 underline"
                      href={p.url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {p.linkLabel} ↗
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 rounded-lg border border-brand-200 bg-brand-50 px-3 py-2 text-[11px] leading-relaxed text-brand-900">
          <strong>Easiest setup:</strong> keep DuckDuckGo HTML for web search (no signup at all) and
          paste a free Google AI Studio key for AI, then choose{" "}
          <code>gemini-3.5-flash-lite</code>. Both [Test] buttons should go green. If Gemini is
          rate-limited, switch AI to OpenRouter <code>openrouter/free</code> or run Ollama locally.
        </p>
      </section>

      {/* ------------------------------------------------------------------ */}
      <div className="sticky bottom-0 z-20 rounded-card border border-line bg-white/95 px-4 py-3 shadow-card backdrop-blur">
        <div className="flex flex-wrap items-center justify-end gap-2">
          <span className="mr-auto text-[11px] text-muted">
            {dirty ? "● Unsaved changes — tests use your unsaved edits." : "✓ All changes saved"}
          </span>
          <button className="btn-ghost text-xs" onClick={() => void reset()} data-testid="settings-reset">
            Reset to defaults
          </button>
          <button
            className="btn-ghost text-xs"
            onClick={() => {
              const fresh = toDraft(payload);
              setDraft(fresh);
              setBaseline(JSON.stringify(fresh));
              setAiTest(null);
              setSearchTest(null);
            }}
            disabled={!dirty}
            data-testid="settings-discard"
          >
            Discard
          </button>
          <button
            className="btn-primary text-xs"
            onClick={() => void save()}
            disabled={saving || !dirty}
            data-testid="settings-save"
          >
            {saving ? "Saving…" : "Save settings"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Small local primitives                                                      */
/* -------------------------------------------------------------------------- */

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="field-label block">{label}</span>
      <div className="mt-1">{children}</div>
      {hint ? <span className="mt-1 block text-[10px] text-muted">{hint}</span> : null}
    </label>
  );
}

function KeyField({
  label,
  value,
  masked,
  source,
  keyEnv,
  show,
  onToggleShow,
  onChange,
  onClear,
  signupUrl,
}: {
  label: string;
  value: string;
  masked: string;
  source: string;
  keyEnv: string;
  show: boolean;
  onToggleShow: () => void;
  onChange: (v: string) => void;
  onClear: () => void;
  signupUrl: string;
}) {
  const cleared = value === "__clear__";
  return (
    <Field
      label={label}
      hint={
        cleared
          ? "The saved key will be removed on Save; the .env value will be used instead."
          : masked
            ? `Current: ${masked} (${source}). Leave blank to keep it.`
            : `No key yet. You can also set ${keyEnv} in backend/.env.`
      }
    >
      <div className="flex gap-1.5">
        <input
          className="input min-w-0 flex-1 font-mono text-xs"
          type={show ? "text" : "password"}
          value={cleared ? "" : value}
          placeholder={cleared ? "Saved key will be removed" : masked ? `Keep ${masked}` : "Paste key"}
          onChange={(e) => onChange(e.target.value)}
          data-testid="settings-key-input"
        />
        <button className="btn-mini" onClick={onToggleShow} type="button">
          {show ? "Hide" : "Show"}
        </button>
        {masked || cleared ? (
          <button className="btn-mini" onClick={onClear} type="button" title="Remove saved key">
            Clear
          </button>
        ) : null}
      </div>
      {signupUrl ? (
        <a
          className="mt-1.5 inline-block text-[11px] font-semibold text-brand-700 underline"
          href={signupUrl}
          target="_blank"
          rel="noreferrer"
        >
          Get a free key ↗
        </a>
      ) : null}
    </Field>
  );
}

function ProviderGrid({
  items,
  value,
  onPick,
  testPrefix,
}: {
  items: ProviderInfo[];
  value: string;
  onPick: (item: ProviderInfo) => void;
  testPrefix: string;
}) {
  return (
    <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label={`${testPrefix} provider`}>
      {items.map((p) => {
        const active = p.id === value;
        return (
          <button
            key={p.id}
            role="radio"
            aria-checked={active}
            onClick={() => onPick(p)}
            className={`rounded-lg border px-3 py-2 text-left transition-colors ${
              active
                ? "border-brand-500 bg-brand-50 ring-1 ring-brand-500"
                : "border-line bg-white hover:border-brand-300 hover:bg-slate-50"
            }`}
            data-testid={`settings-${testPrefix}-provider-${p.id}`}
          >
            <span className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs font-bold text-ink">{p.label}</span>
              {p.recommended ? <Badge tone="green">Recommended</Badge> : null}
              {!p.keyRequired && p.id !== "off" ? <Badge tone="blue">No key</Badge> : null}
            </span>
            <span className="mt-0.5 block text-[10px] leading-snug text-muted">{p.tagline}</span>
          </button>
        );
      })}
    </div>
  );
}

function TestPanel({ ok, message, ms }: { ok: boolean; message: string; ms: number }) {
  return (
    <div
      className={`rounded-lg border px-3 py-2 text-xs ${
        ok
          ? "border-brand-200 bg-brand-50 text-brand-900"
          : "border-rose-200 bg-rose-50 text-rose-800"
      }`}
      data-testid="settings-test-result"
      data-ok={ok ? "yes" : "no"}
    >
      <span className="font-bold">{ok ? "✓ Working" : "✕ Failed"}</span>
      {ms > 0 ? <span className="ml-2 text-[10px] opacity-70">{ms} ms</span> : null}
      <p className="mt-1 break-words leading-relaxed">{message}</p>
    </div>
  );
}
