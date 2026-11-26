"""Server-side configuration for AI providers and web search (Phase 6).

Settings live in ``backend/settings.json`` (gitignored) and are editable from the
Settings page in the UI. Environment variables in ``backend/.env`` remain a
fallback, so existing installations keep working without any migration.

Security note: API keys are stored in plain text in a local file. Nothing is
sent anywhere except to the provider the teacher explicitly picks, and the
GET endpoint always masks keys.
"""
from __future__ import annotations

import copy
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = BACKEND_ROOT / "settings.json"

_LOCK = threading.Lock()
_ENV_LOADED = False

# ---------------------------------------------------------------------------
# Provider catalogues. Shared with the UI so recommendations stay in one place.
# ---------------------------------------------------------------------------

AI_PROVIDERS: list[dict[str, Any]] = [
    {
        "id": "gemini",
        "label": "Google Gemini",
        "tagline": "Best free tier for this app · no credit card",
        "recommended": True,
        "free": True,
        "keyRequired": True,
        "keyEnv": "GEMINI_API_KEY",
        "signupUrl": "https://aistudio.google.com/apikey",
        "docsUrl": "https://ai.google.dev/gemini-api/docs",
        "defaultModel": "gemini-3.5-flash-lite",
        "baseUrl": "https://generativelanguage.googleapis.com/v1beta",
        "quota": "Free tier, roughly 50-250 requests/day depending on model",
        "note": (
            "Use a small Flash-Lite model. gemini-3.8-flash is frequently overloaded "
            "(HTTP 503 / long timeouts) on the free tier; 3.5-flash-lite answers in ~2s."
        ),
    },
    {
        "id": "openrouter",
        "label": "OpenRouter (free models)",
        "tagline": "One key, dozens of free models",
        "recommended": True,
        "free": True,
        "keyRequired": True,
        "keyEnv": "OPENROUTER_API_KEY",
        "signupUrl": "https://openrouter.ai/keys",
        "docsUrl": "https://openrouter.ai/docs/api-reference/overview",
        "defaultModel": "openrouter/free",
        "baseUrl": "https://openrouter.ai/api/v1",
        "quota": "50 requests/day free (1,000/day after a one-time $10 credit)",
        "note": "openrouter/free auto-picks a working free model. No credit card needed.",
    },
    {
        "id": "groq",
        "label": "Groq",
        "tagline": "Fastest inference, generous free developer tier",
        "recommended": True,
        "free": True,
        "keyRequired": True,
        "keyEnv": "GROQ_API_KEY",
        "signupUrl": "https://console.groq.com/keys",
        "docsUrl": "https://console.groq.com/docs/openai",
        "defaultModel": "openai/gpt-oss-120b",
        "baseUrl": "https://api.groq.com/openai/v1",
        "quota": "Free developer tier, per-minute token/request limits",
        "note": "OpenAI-compatible. Use [Fetch models] to see what your account can call.",
    },
    {
        "id": "cerebras",
        "label": "Cerebras",
        "tagline": "Very fast free inference",
        "recommended": False,
        "free": True,
        "keyRequired": True,
        "keyEnv": "CEREBRAS_API_KEY",
        "signupUrl": "https://cloud.cerebras.ai/",
        "docsUrl": "https://inference-docs.cerebras.ai/api-reference/chat-completions",
        "defaultModel": "llama-3.3-70b",
        "baseUrl": "https://api.cerebras.ai/v1",
        "quota": "Free tier with daily token limits",
        "note": "OpenAI-compatible. Use [Fetch models] if the default model is retired.",
    },
    {
        "id": "ollama",
        "label": "Ollama (local)",
        "tagline": "100% offline · no key, no quota, no data leaves the machine",
        "recommended": False,
        "free": True,
        "keyRequired": False,
        "keyEnv": "",
        "signupUrl": "https://ollama.com/download",
        "docsUrl": "https://github.com/ollama/ollama/blob/main/docs/api.md",
        "defaultModel": "llama3.2",
        "baseUrl": "http://127.0.0.1:11434/v1",
        "quota": "Unlimited (runs on your own machine)",
        "note": "Install Ollama, run `ollama pull llama3.2`, then start `ollama serve`.",
    },
    {
        "id": "openai-compatible",
        "label": "Custom OpenAI-compatible",
        "tagline": "LM Studio, vLLM, llama.cpp or any gateway",
        "recommended": False,
        "free": True,
        "keyRequired": False,
        "keyEnv": "AI_API_KEY",
        "signupUrl": "",
        "docsUrl": "",
        "defaultModel": "local-model",
        "baseUrl": "http://127.0.0.1:1234/v1",
        "quota": "Depends on your endpoint",
        "note": "Point Base URL at any /v1/chat/completions compatible server.",
    },
    {
        "id": "off",
        "label": "Off (no AI)",
        "tagline": "Disable AI drafting entirely",
        "recommended": False,
        "free": True,
        "keyRequired": False,
        "keyEnv": "",
        "signupUrl": "",
        "docsUrl": "",
        "defaultModel": "",
        "baseUrl": "",
        "quota": "n/a",
        "note": "Everything else in the studio keeps working.",
    },
]

SEARCH_PROVIDERS: list[dict[str, Any]] = [
    {
        "id": "duckduckgo",
        "label": "DuckDuckGo HTML",
        "tagline": "No key, no signup · works right now",
        "recommended": True,
        "free": True,
        "keyRequired": False,
        "keyEnv": "",
        "signupUrl": "",
        "docsUrl": "https://html.duckduckgo.com/",
        "baseUrl": "https://html.duckduckgo.com/html/",
        "quota": "No published API quota (polite use)",
        "note": "Real web results. Verified returning Kenyan CBC classroom links in ~2s.",
    },
    {
        "id": "tavily",
        "label": "Tavily Search",
        "tagline": "Clean JSON results built for AI apps",
        "recommended": True,
        "free": True,
        "keyRequired": True,
        "keyEnv": "TAVILY_API_KEY",
        "signupUrl": "https://app.tavily.com/",
        "docsUrl": "https://docs.tavily.com/documentation/api-reference/endpoint/search",
        "baseUrl": "https://api.tavily.com/search",
        "quota": "1,000 free credits/month, no credit card",
        "note": "Best quality when you want a real API with snippets.",
    },
    {
        "id": "serper",
        "label": "Serper (Google results)",
        "tagline": "2,500 free Google searches / month",
        "recommended": True,
        "free": True,
        "keyRequired": True,
        "keyEnv": "SERPER_API_KEY",
        "signupUrl": "https://serper.dev/",
        "docsUrl": "https://serper.dev/playground",
        "baseUrl": "https://google.serper.dev/search",
        "quota": "2,500 free queries, no credit card",
        "note": "Google results via a simple JSON API.",
    },
    {
        "id": "wikipedia",
        "label": "Wikipedia",
        "tagline": "No key · always available",
        "recommended": False,
        "free": True,
        "keyRequired": False,
        "keyEnv": "",
        "signupUrl": "",
        "docsUrl": "https://www.mediawiki.org/wiki/API:Search",
        "baseUrl": "https://en.wikipedia.org/w/api.php",
        "quota": "No quota for polite use",
        "note": "Encyclopedic background rather than classroom activity ideas.",
    },
    {
        "id": "searxng",
        "label": "SearXNG",
        "tagline": "Self-hosted / public meta-search",
        "recommended": False,
        "free": True,
        "keyRequired": False,
        "keyEnv": "",
        "signupUrl": "https://docs.searxng.org/",
        "docsUrl": "https://docs.searxng.org/dev/search_api.html",
        "baseUrl": "http://127.0.0.1:8080/search",
        "quota": "Depends on the instance",
        "note": "Set Base URL to an instance that has JSON format enabled.",
    },
    {
        "id": "gemini-grounding",
        "label": "Gemini Google Search grounding",
        "tagline": "Needs a Gemini key with grounding quota",
        "recommended": False,
        "free": False,
        "keyRequired": True,
        "keyEnv": "GEMINI_API_KEY",
        "signupUrl": "https://aistudio.google.com/apikey",
        "docsUrl": "https://ai.google.dev/gemini-api/docs/google-search",
        "baseUrl": "",
        "quota": "Grounding quota is separate; free tier often returns HTTP 429",
        "note": (
            "This is what the app used before. Free-tier keys commonly hit "
            "`429 quota exceeded`, which is why search returned nothing."
        ),
    },
    {
        "id": "auto",
        "label": "Auto (with no-key fallback)",
        "tagline": "Try the chosen API, fall back to DuckDuckGo",
        "recommended": False,
        "free": True,
        "keyRequired": False,
        "keyEnv": "",
        "signupUrl": "",
        "docsUrl": "",
        "baseUrl": "",
        "quota": "n/a",
        "note": "Resilient: you still get results if the paid/free API is rate limited.",
    },
    {
        "id": "off",
        "label": "Off (no web search)",
        "tagline": "Disable web examples entirely",
        "recommended": False,
        "free": True,
        "keyRequired": False,
        "keyEnv": "",
        "signupUrl": "",
        "docsUrl": "",
        "baseUrl": "",
        "quota": "n/a",
        "note": "Teachers can still add their own examples manually.",
    },
]

AI_PROVIDER_IDS = {p["id"] for p in AI_PROVIDERS}
SEARCH_PROVIDER_IDS = {p["id"] for p in SEARCH_PROVIDERS}


def _defaults() -> dict[str, Any]:
    return {
        "ai": {
            "provider": "gemini",
            "apiKey": "",
            "model": "gemini-3.5-flash-lite",
            "baseUrl": "",
            "timeoutSeconds": 30,
            "temperature": 0.35,
        },
        "search": {
            "provider": "duckduckgo",
            "apiKey": "",
            "baseUrl": "",
            "timeoutSeconds": 15,
            "maxResults": 3,
            "verifyLinks": False,
            "minScore": 0,
        },
        "updatedAt": "",
    }


# ---------------------------------------------------------------------------
# .env fallback
# ---------------------------------------------------------------------------

def _load_env() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True
    env_path = BACKEND_ROOT / ".env"
    if not env_path.exists():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        return


def env_key(name: str) -> str:
    if not name:
        return ""
    _load_env()
    return (os.environ.get(name) or "").strip()


def provider_by_id(kind: str, provider_id: str) -> dict[str, Any]:
    catalog = AI_PROVIDERS if kind == "ai" else SEARCH_PROVIDERS
    for p in catalog:
        if p["id"] == provider_id:
            return p
    return catalog[0]


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------

def _read_file() -> dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def get_settings() -> dict[str, Any]:
    """Full config for internal use, including resolved keys."""
    with _LOCK:
        stored = _read_file()
    cfg = _defaults()
    for section in ("ai", "search"):
        incoming = stored.get(section)
        if isinstance(incoming, dict):
            for k, v in incoming.items():
                if k in cfg[section]:
                    cfg[section][k] = v
    cfg["updatedAt"] = str(stored.get("updatedAt") or "")

    # Environment fallback so existing .env installs keep working untouched.
    for section, catalog in (("ai", AI_PROVIDERS), ("search", SEARCH_PROVIDERS)):
        if not str(cfg[section].get("apiKey") or "").strip():
            pid = str(cfg[section].get("provider") or "")
            meta = next((p for p in catalog if p["id"] == pid), None)
            cfg[section]["apiKey"] = env_key(str((meta or {}).get("keyEnv") or ""))
        if not str(cfg[section].get("baseUrl") or "").strip():
            pid = str(cfg[section].get("provider") or "")
            meta = next((p for p in catalog if p["id"] == pid), None)
            cfg[section]["baseUrl"] = str((meta or {}).get("baseUrl") or "")

    for section in ("ai", "search"):
        cfg[section]["timeoutSeconds"] = _clamp_number(
            cfg[section].get("timeoutSeconds"), 5, 180, 30 if section == "ai" else 15
        )
    cfg["ai"]["temperature"] = _clamp_number(cfg["ai"].get("temperature"), 0, 2, 0.35, as_float=True)
    cfg["search"]["maxResults"] = _clamp_number(cfg["search"].get("maxResults"), 1, 10, 3)
    cfg["search"]["minScore"] = _clamp_number(cfg["search"].get("minScore"), -100, 100, 0)
    cfg["search"]["verifyLinks"] = bool(cfg["search"].get("verifyLinks"))
    return cfg


def _clamp_number(value: Any, lo: float, hi: float, fallback: float, as_float: bool = False) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        n = float(fallback)
    n = max(lo, min(hi, n))
    return n if as_float else int(n)


def key_source(section: str) -> str:
    """Where the active key came from: settings file / environment / none."""
    stored = _read_file().get(section) or {}
    file_key = str(stored.get("apiKey") or "").strip()
    if file_key:
        return "saved"
    cfg = get_settings()
    meta = provider_by_id(section, str(cfg[section].get("provider") or ""))
    if env_key(str(meta.get("keyEnv") or "")):
        return "environment"
    return "none"


def mask(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) <= 10:
        return f"{value[:2]}••••"
    return f"{value[:5]}••••••••{value[-4:]}"


def public_settings() -> dict[str, Any]:
    """Config for the browser. Keys are always masked."""
    cfg = get_settings()
    out = copy.deepcopy(cfg)
    for section, catalog in (("ai", AI_PROVIDERS), ("search", SEARCH_PROVIDERS)):
        key = str(out[section].get("apiKey") or "")
        out[section]["apiKey"] = ""          # never ship the secret to the browser
        out[section]["maskedKey"] = mask(key)
        out[section]["hasKey"] = bool(key)
        out[section]["keySource"] = key_source(section)
        meta = provider_by_id(section, str(out[section].get("provider") or ""))
        out[section]["keyEnv"] = meta.get("keyEnv") or ""
        out[section]["keyRequired"] = bool(meta.get("keyRequired"))
    out["settingsPath"] = str(SETTINGS_PATH)
    return out


def save_settings(payload: dict[str, Any]) -> dict[str, Any]:
    """Merge a partial update into settings.json.

    A masked/empty apiKey means "keep what is there"; the literal string
    ``__clear__`` removes a saved key and falls back to the environment.
    """
    if not isinstance(payload, dict):
        raise ValueError("Settings payload must be an object.")
    current_file = _read_file()
    merged = copy.deepcopy(_defaults())
    for section in ("ai", "search"):
        if isinstance(current_file.get(section), dict):
            merged[section].update(
                {k: v for k, v in current_file[section].items() if k in merged[section]}
            )

    for section, valid_ids in (("ai", AI_PROVIDER_IDS), ("search", SEARCH_PROVIDER_IDS)):
        incoming = payload.get(section)
        if not isinstance(incoming, dict):
            continue
        allowed = set(merged[section].keys())
        for k, v in incoming.items():
            if k not in allowed:
                continue
            if k == "apiKey":
                s = str(v or "").strip()
                if s == "__clear__":
                    merged[section]["apiKey"] = ""
                elif s and "•" not in s:
                    merged[section]["apiKey"] = s
                # masked or blank -> keep existing
                continue
            if k in ("provider",):
                if v not in valid_ids:
                    raise ValueError(f"Unknown {section} provider: {v}")
            if k in ("verifyLinks",):
                merged[section][k] = bool(v)
                continue
            if k in ("timeoutSeconds", "maxResults", "minScore", "temperature"):
                try:
                    merged[section][k] = float(v)
                except (TypeError, ValueError):
                    continue
                continue
            merged[section][k] = str(v or "").strip()

    merged["updatedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _LOCK:
        SETTINGS_PATH.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return public_settings()


def reset_settings() -> dict[str, Any]:
    with _LOCK:
        if SETTINGS_PATH.exists():
            SETTINGS_PATH.unlink()
    return public_settings()


def catalog() -> dict[str, Any]:
    return {"ai": AI_PROVIDERS, "search": SEARCH_PROVIDERS}
