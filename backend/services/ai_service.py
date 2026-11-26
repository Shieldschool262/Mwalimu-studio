"""AI drafting + web example search with configurable providers (Phase 6).

AI remains OPT-IN: it only runs when a teacher presses [Draft with AI]. Web
search is teacher-initiated too. Both providers are chosen in the Settings page
and persisted by ``services.settings_service``; ``.env`` keys are a fallback.

Before this refactor the app hardcoded ``gemini-3.8-flash`` (routinely 503 /
timeout on the free tier) and Google Search grounding (free tier returns 429),
and ``draft_lesson`` called an undefined ``_post_gemini`` helper. All three are
fixed here.
"""
from __future__ import annotations

import html as html_lib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from services import settings_service

SYSTEM_PROMPT = (
    "You are a Kenyan CBE assistant. Use ONLY source provided. Do NOT invent new outcomes, "
    "do NOT add content not in source, do NOT change KIQ. If you add a concrete example, label "
    "it [AI Example]. Simple English for Grade 1. Each step 2-3 sentences."
)

GEMINI_API_ROOT = "https://generativelanguage.googleapis.com/v1beta"


class AIUnavailable(RuntimeError):
    pass


class AIError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

_WEB_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122 Safari/537.36"
    ),
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
}


def _http(
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30,
    method: str | None = None,
) -> tuple[int, str]:
    """One HTTP call. Returns (status, text). Raises AIError with the body."""
    req = urllib.request.Request(
        url,
        data=data,
        headers={**_WEB_HEADERS, **(headers or {})},
        method=method or ("POST" if data is not None else "GET"),
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(resp.status), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", "replace")[:400]
        except Exception:
            detail = ""
        code = int(e.code)
        if code == 429:
            raise AIError(
                f"Provider returned HTTP 429 (quota/rate limit exceeded). "
                f"Wait a little, switch to a smaller model or another free provider in Settings. {detail}"
            ) from e
        if code in (401, 403):
            raise AIError(
                f"Provider rejected the API key (HTTP {code}). Check the key in Settings. {detail}"
            ) from e
        if code == 404:
            raise AIError(
                f"HTTP 404 - the model or endpoint does not exist (or is retired). "
                f"Use [Fetch models] in Settings. {detail}"
            ) from e
        raise AIError(f"Provider returned HTTP {code}. {detail}".strip()) from e
    except urllib.error.URLError as e:
        raise AIError(f"Could not reach the provider: {e.reason}") from e
    except TimeoutError as e:
        raise AIError(
            f"Provider timed out after {int(timeout)}s. Try a smaller/faster model in Settings."
        ) from e
    except Exception as e:
        raise AIError(f"Request failed: {e}") from e


def _http_json(
    url: str,
    *,
    body: dict[str, Any],
    headers: dict[str, str],
    timeout: float,
) -> dict[str, Any]:
    _, text = _http(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        timeout=timeout,
        method="POST",
    )
    try:
        payload = json.loads(text)
    except Exception as e:
        raise AIError(f"Provider returned non-JSON text: {text[:180]}") from e
    if not isinstance(payload, dict):
        raise AIError("Provider returned an unexpected JSON shape.")
    return payload


def _extract_json(text: str) -> dict[str, Any]:
    """Parse a JSON object even if the model wrapped it in prose/code fences."""
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I).strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(cleaned[start : end + 1])
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    raise AIError(f"AI returned text that was not valid JSON: {cleaned[:180]}")


# ---------------------------------------------------------------------------
# AI providers
# ---------------------------------------------------------------------------

def api_key() -> str:
    """Backwards-compatible Gemini key accessor used by a few callers."""
    return str(settings_service.get_settings()["ai"].get("apiKey") or "").strip()


def ai_status() -> dict[str, Any]:
    cfg = settings_service.get_settings()["ai"]
    provider = str(cfg.get("provider") or "off")
    key = str(cfg.get("apiKey") or "")
    meta = settings_service.provider_by_id("ai", provider)
    if provider == "off":
        return {
            "available": False,
            "provider": "off",
            "model": "",
            "message": "AI is turned off in Settings.",
        }
    needs_key = bool(meta.get("keyRequired"))
    available = (not needs_key) or bool(key)
    return {
        "available": available,
        "provider": provider,
        "model": str(cfg.get("model") or ""),
        "message": (
            f"AI ready · {meta['label']} · {cfg.get('model') or 'default model'}"
            if available
            else f"Add a {meta['label']} API key in Settings (or set {meta.get('keyEnv')})."
        ),
    }


def _gemini_text(
    prompt: str,
    system_prompt: str,
    *,
    cfg: dict[str, Any],
    json_mode: bool = True,
    tools: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    key = str(cfg.get("apiKey") or "")
    if not key:
        raise AIUnavailable("Add a Google Gemini API key in Settings.")
    model = str(cfg.get("model") or "gemini-3.5-flash-lite").strip()
    gen: dict[str, Any] = {"temperature": float(cfg.get("temperature") or 0.35)}
    if json_mode:
        # Grounding + responseMimeType is not a valid combination.
        gen["responseMimeType"] = "application/json"
    body: dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": gen,
    }
    if tools:
        body["tools"] = tools
    url = f"{GEMINI_API_ROOT}/models/{urllib.parse.quote(model)}:generateContent?key={urllib.parse.quote(key)}"
    payload = _http_json(
        url, body=body, headers={}, timeout=float(cfg.get("timeoutSeconds") or 30)
    )
    candidate = (payload.get("candidates") or [{}])[0] or {}
    text = ""
    try:
        text = str(candidate["content"]["parts"][0]["text"])
    except (KeyError, IndexError, TypeError):
        text = ""
    if not text:
        raise AIError("The model returned an empty response (it may be overloaded). Try a smaller model.")
    return text, candidate


def _openai_compatible_text(
    prompt: str,
    system_prompt: str,
    *,
    cfg: dict[str, Any],
    provider: str,
) -> tuple[str, dict[str, Any]]:
    base = str(cfg.get("baseUrl") or "").strip().rstrip("/")
    if not base:
        meta = settings_service.provider_by_id("ai", provider)
        base = str(meta.get("baseUrl") or "").rstrip("/")
    if not base:
        raise AIUnavailable("Set a Base URL for this provider in Settings.")
    model = str(cfg.get("model") or "").strip()
    if not model:
        raise AIUnavailable("Set a model name in Settings.")
    headers: dict[str, str] = {}
    key = str(cfg.get("apiKey") or "")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": float(cfg.get("temperature") or 0.35),
        "stream": False,
    }
    if provider in ("groq", "cerebras"):
        body["response_format"] = {"type": "json_object"}
    if provider == "openrouter":
        headers["HTTP-Referer"] = "http://localhost:5173"
        headers["X-Title"] = "Mwalimu Studio"
    payload = _http_json(
        f"{base}/chat/completions",
        body=body,
        headers=headers,
        timeout=float(cfg.get("timeoutSeconds") or 30),
    )
    try:
        text = str(payload["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError) as e:
        raise AIError(f"Unexpected response from {provider}: {str(payload)[:180]}") from e
    if not text:
        raise AIError(f"{provider} returned an empty response.")
    return text, payload


def _ai_text(prompt: str, system_prompt: str, *, json_mode: bool = True) -> tuple[str, dict[str, Any]]:
    cfg = settings_service.get_settings()["ai"]
    provider = str(cfg.get("provider") or "off")
    if provider == "off":
        raise AIUnavailable("AI is turned off in Settings.")
    meta = settings_service.provider_by_id("ai", provider)
    if meta.get("keyRequired") and not str(cfg.get("apiKey") or ""):
        raise AIUnavailable(f"Add a {meta['label']} API key in Settings.")
    if provider == "gemini":
        return _gemini_text(prompt, system_prompt, cfg=cfg, json_mode=json_mode)
    return _openai_compatible_text(prompt, system_prompt, cfg=cfg, provider=provider)


def post_ai_json(prompt: str, system_prompt: str = SYSTEM_PROMPT) -> dict[str, Any]:
    """Provider-agnostic JSON completion used by lesson plans and lesson notes."""
    text, _ = _ai_text(prompt, system_prompt, json_mode=True)
    return _extract_json(text)


def post_gemini_json(prompt: str, system_prompt: str = SYSTEM_PROMPT) -> dict[str, Any]:
    """Legacy name kept for notes_enrich and any other callers."""
    return post_ai_json(prompt, system_prompt)


def _gemini_request(
    prompt: str,
    system_prompt: str = SYSTEM_PROMPT,
    response_mime_type: str = "application/json",
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Legacy low-level helper. Returns a Gemini-shaped payload for grounding."""
    cfg = settings_service.get_settings()["ai"]
    text, candidate = _gemini_text(prompt, system_prompt, cfg=cfg, json_mode=False, tools=tools)
    return {"candidates": [{"content": {"parts": [{"text": text}]}, "groundingMetadata": candidate.get("groundingMetadata") or {}}]}


def _post_gemini_raw(
    prompt: str,
    system_prompt: str = SYSTEM_PROMPT,
    response_mime_type: str = "application/json",
    tools: list[dict[str, Any]] | None = None,
) -> str:
    text, _ = _ai_text(prompt, system_prompt, json_mode=(response_mime_type == "application/json"))
    return text


# ---------------------------------------------------------------------------
# Model discovery + connection tests (used by the Settings page)
# ---------------------------------------------------------------------------

def list_ai_models(provider: str | None = None, override: dict[str, Any] | None = None) -> dict[str, Any]:
    """List models available to the configured key. Never returns key material."""
    cfg = dict(settings_service.get_settings()["ai"])
    if override:
        for k in ("provider", "apiKey", "baseUrl", "model", "timeoutSeconds"):
            v = override.get(k)
            if v in (None, ""):
                continue
            if k == "apiKey":
                if str(v) == "__clear__":
                    meta = settings_service.provider_by_id("ai", str(cfg.get("provider") or "gemini"))
                    cfg[k] = settings_service.env_key(str(meta.get("keyEnv") or ""))
                elif "•" not in str(v):
                    cfg[k] = str(v)
                continue
            cfg[k] = v
    pid = str(provider or cfg.get("provider") or "gemini")
    cfg["provider"] = pid
    key = str(cfg.get("apiKey") or "")
    timeout = min(float(cfg.get("timeoutSeconds") or 30), 20)
    models: list[str] = []
    if pid == "gemini":
        if not key:
            raise AIUnavailable("Add a Gemini API key first.")
        _, text = _http(f"{GEMINI_API_ROOT}/models?key={urllib.parse.quote(key)}", timeout=timeout)
        data = json.loads(text)
        for m in data.get("models") or []:
            name = str(m.get("name") or "").replace("models/", "")
            methods = m.get("supportedGenerationMethods") or []
            if name and (not methods or "generateContent" in methods):
                if not any(x in name for x in ("embedding", "image", "tts", "transcribe", "robotics", "lyria", "banana", "computer-use", "deep-research")):
                    models.append(name)
    elif pid in ("groq", "openrouter", "cerebras", "ollama", "openai-compatible"):
        base = str(cfg.get("baseUrl") or settings_service.provider_by_id("ai", pid).get("baseUrl") or "").rstrip("/")
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        _, text = _http(f"{base}/models", headers=headers, timeout=timeout)
        data = json.loads(text)
        rows = data.get("data") or data.get("models") or []
        for m in rows:
            name = str(m.get("id") or m.get("name") or "") if isinstance(m, dict) else str(m)
            if name:
                models.append(name)
    else:
        raise AIUnavailable(f"Model discovery is not available for '{pid}'.")
    models = list(dict.fromkeys(models))
    return {"provider": pid, "models": models, "count": len(models)}


def test_ai(override: dict[str, Any] | None = None) -> dict[str, Any]:
    """Tiny real request. Returns latency + the exact error when it fails."""
    if override:
        current = settings_service.get_settings()["ai"]
        patch = {
            k: v for k, v in override.items()
            if v not in (None, "") and not (k == "apiKey" and "•" in str(v))
        }
        if str(override.get("apiKey") or "") == "__clear__":
            pid = str(patch.get("provider") or current.get("provider") or "gemini")
            meta = settings_service.provider_by_id("ai", pid)
            patch["apiKey"] = settings_service.env_key(str(meta.get("keyEnv") or ""))
        return _test_ai_with({**current, **patch})
    return _test_ai_with(settings_service.get_settings()["ai"])


def _test_ai_with(cfg: dict[str, Any]) -> dict[str, Any]:
    provider = str(cfg.get("provider") or "off")
    started = time.time()
    try:
        if provider == "off":
            raise AIUnavailable("AI is turned off.")
        meta = settings_service.provider_by_id("ai", provider)
        if meta.get("keyRequired") and not str(cfg.get("apiKey") or ""):
            raise AIUnavailable(f"Add a {meta['label']} API key first.")
        if provider == "gemini":
            text, _ = _gemini_text(
                'Return a JSON object: {"ok": true, "greeting": "Habari"}',
                "You must reply with valid JSON only.",
                cfg=cfg,
                json_mode=True,
            )
        else:
            text, _ = _openai_compatible_text(
                'Return a JSON object: {"ok": true, "greeting": "Habari"}',
                "You must reply with valid JSON only.",
                cfg=cfg,
                provider=provider,
            )
        parsed = _extract_json(text)
        return {
            "ok": True,
            "provider": provider,
            "model": str(cfg.get("model") or ""),
            "latencyMs": int((time.time() - started) * 1000),
            "sample": str(parsed.get("greeting") or "OK"),
            "message": f"Working - {meta['label']} replied in {int((time.time() - started) * 1000)} ms.",
        }
    except (AIError, AIUnavailable) as e:
        return {
            "ok": False,
            "provider": provider,
            "model": str(cfg.get("model") or ""),
            "latencyMs": int((time.time() - started) * 1000),
            "message": str(e),
        }


# ---------------------------------------------------------------------------
# Drafting (unchanged prompts, now provider-agnostic and bug-free)
# ---------------------------------------------------------------------------

def draft_lesson(context: dict[str, Any]) -> dict[str, Any]:
    """Draft only the teacher-owned narrative fields from the source context."""
    prompt = (
        "Using ONLY this source context, draft the requested lesson fields.\n"
        "Return JSON with exactly these keys: introduction, step1, step2, step3, "
        "extendedActivity, conclusion, commonMisconception, teacherQuestions.\n"
        "Every value is a string. Do not change outcomes, KIQ or resources.\n"
        "If you mention a Specific Learning Outcome it must start with "
        '"By the end of the lesson, the learner should be able to:" - never '
        '"By the end of the sub-strand". Focus only on this lesson\'s atomic skill.\n\n'
        f"Strand: {context.get('strand')}\n"
        f"Sub-Strand: {context.get('subStrand')}\n"
        f"Outcomes: {context.get('outcomes')}\n"
        f"Experiences (atomic focus): {context.get('experiences')}\n"
        f"KIQ: {context.get('kiq')}\n"
        f"Resources: {context.get('resources')}\n"
        f"Rubric: {context.get('rubric')}\n"
        f"Grade: {context.get('grade')}\n"
        f"Duration: {context.get('duration')} minutes\n"
        f"Lesson: Week {context.get('week')} Lesson {context.get('lesson')} of "
        f"{context.get('lessonCount')}. Focus: {context.get('focus')}"
    )
    data = post_ai_json(prompt)
    keys = [
        "introduction", "step1", "step2", "step3",
        "extendedActivity", "conclusion", "commonMisconception", "teacherQuestions",
    ]
    return {key: (str(data.get(key)).strip() if data.get(key) is not None else "") for key in keys}


def suggest_split(context: dict[str, Any]) -> list[dict[str, Any]]:
    prompt = (
        "Split this compound curriculum experience into ATOMIC skills for single lessons. "
        'Return JSON: {"atoms":[{"text":"...","focus_keyword":"..."}]}. '
        "Keep the source verbs and objects. Do not add skills that are not in the source.\n\n"
        f"Experience: {context.get('experience')}\n"
        f"Sub-Strand: {context.get('subStrand')}\nGrade: {context.get('grade')}"
    )
    data = post_ai_json(prompt)
    atoms = data.get("atoms") or []
    out = []
    for a in atoms:
        if isinstance(a, dict) and str(a.get("text") or "").strip():
            out.append({
                "text": str(a["text"]).strip(),
                "focus_keyword": str(a.get("focus_keyword") or "").strip().lower(),
                "source": context.get("experience") or "",
                "pattern": "ai_suggested",
            })
    return out


# ---------------------------------------------------------------------------
# Web search - teacher-initiated only, never auto-inserted
# ---------------------------------------------------------------------------

_WEB_SEARCH_LOGS: dict[str, dict[str, Any]] = {}
WEB_SEARCH_UNAVAILABLE = "Web search unavailable - try again or add your own example"
WEB_SEARCH_MIN_SCORE = 0


def _web_head_ok(url: str, timeout: float = 5.0) -> bool:
    """HEAD-check a URL. Accept any 2xx/3xx (many sites reject HEAD with 403)."""
    try:
        req = urllib.request.Request(url, method="HEAD", headers=_WEB_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= int(resp.status) < 400
    except urllib.error.HTTPError as e:
        # A 403/405 on HEAD usually means the site blocks HEAD, not that the page is gone.
        return e.code in (403, 405, 406)
    except Exception:
        return False


def _score_web_result(title: str, snippet: str, url: str, query: str) -> float:
    text = f"{(title or '').lower()} {(snippet or '').lower()}"
    q = (query or "").lower()
    score = 0.0
    words = [w for w in re.split(r"[^a-z0-9]+", q) if len(w) > 3]
    if any(w in text for w in words):
        score += 30
    if any(k in text for k in ("kenya", "kicd", "cbc", "teacher", "learning", "curriculum")):
        score += 20
    if any(k in text for k in ("activity", "game", "hands-on", "song", "play", "learn", "practice", "exercise", "drill", "story", "classroom")):
        score += 15
    if "worksheet" in text:
        score -= 40
    return score


def get_web_search_log(note_id: str) -> dict[str, Any] | None:
    return _WEB_SEARCH_LOGS.get(note_id)


def _resolve_url(url: str) -> str:
    """Decode DuckDuckGo's ``uddg`` redirect parameter if present."""
    url = (url or "").strip()
    try:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query or "")
        if "uddg" in qs and qs["uddg"]:
            resolved = urllib.parse.unquote(qs["uddg"][0])
            if resolved.startswith(("http://", "https://")):
                return resolved
        if parsed.netloc.endswith("duckduckgo.com"):
            return ""  # internal redirect with no target
    except Exception:
        pass
    if url.startswith("//"):
        return "https:" + url
    return url


def _strip_tags(value: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", "", value or ""))).strip()


def _normalize(raw: dict[str, Any]) -> dict[str, Any] | None:
    url = _resolve_url(str(raw.get("url") or ""))
    if not url.startswith(("http://", "https://")):
        return None
    return {
        "title": _strip_tags(str(raw.get("title") or ""))[:140] or urllib.parse.urlparse(url).netloc,
        "url": url,
        "snippet": _strip_tags(str(raw.get("snippet") or ""))[:240],
        "source": urllib.parse.urlparse(url).netloc.replace("www.", ""),
    }


# --- individual providers -------------------------------------------------

def _search_duckduckgo(q: str, cfg: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    timeout = float(cfg.get("timeoutSeconds") or 15)
    base = str(cfg.get("baseUrl") or "https://html.duckduckgo.com/html/").rstrip("/")
    url = f"{base}/?q={urllib.parse.quote(q)}"
    _, text = _http(url, timeout=timeout)
    out: list[dict[str, Any]] = []

    # html.duckduckgo.com layout
    blocks = re.findall(
        r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>(.*?)(?=<a[^>]*class="result__a"|</body>)',
        text, re.S | re.I,
    )
    for href, title, tail in blocks:
        snip = re.search(r'class="result__snippet"[^>]*>(.*?)</(?:a|div|td)>', tail, re.S | re.I)
        item = _normalize({
            "url": html_lib.unescape(href),
            "title": title,
            "snippet": snip.group(1) if snip else "",
        })
        if item:
            out.append(item)

    # lite.duckduckgo.com layout (href comes before class='result-link')
    if not out:
        lite = re.findall(
            r'<a[^>]*href="([^"]+)"[^>]*class=[\'"]result-link[\'"][^>]*>(.*?)</a>(.*?)(?=<a[^>]*class=[\'"]result-link|\Z)',
            text, re.S | re.I,
        )
        if not lite:
            lite = re.findall(
                r'<a[^>]*class=[\'"]result-link[\'"][^>]*href="([^"]+)"[^>]*>(.*?)</a>(.*?)(?=<a[^>]*class=[\'"]result-link|\Z)',
                text, re.S | re.I,
            )
        for href, title, tail in lite:
            snip = re.search(r"class=['\"]result-snippet['\"][^>]*>(.*?)</td>", tail, re.S | re.I)
            item = _normalize({
                "url": html_lib.unescape(href),
                "title": title,
                "snippet": snip.group(1) if snip else "",
            })
            if item:
                out.append(item)
    return out[: max(limit * 3, limit)]


def _search_wikipedia(q: str, cfg: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    base = str(cfg.get("baseUrl") or "https://en.wikipedia.org/w/api.php")
    url = (
        f"{base}?action=query&list=search&srsearch={urllib.parse.quote(q)}"
        f"&srlimit={max(limit * 2, limit)}&format=json"
    )
    _, text = _http(url, timeout=float(cfg.get("timeoutSeconds") or 15))
    data = json.loads(text)
    out = []
    for row in (data.get("query") or {}).get("search") or []:
        item = _normalize({
            "url": f"https://en.wikipedia.org/wiki/{urllib.parse.quote(str(row.get('title') or '').replace(' ', '_'))}",
            "title": row.get("title"),
            "snippet": row.get("snippet"),
        })
        if item:
            out.append(item)
    return out


def _search_tavily(q: str, cfg: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    key = str(cfg.get("apiKey") or "")
    if not key:
        raise AIUnavailable("Add a Tavily API key in Settings.")
    payload = _http_json(
        str(cfg.get("baseUrl") or "https://api.tavily.com/search"),
        body={
            "api_key": key,
            "query": q,
            "topic": "general",
            "search_depth": "basic",
            "max_results": max(limit * 2, limit),
            "include_answer": False,
        },
        headers={"Content-Type": "application/json"},
        timeout=float(cfg.get("timeoutSeconds") or 15),
    )
    return [
        item for item in (
            _normalize({"url": r.get("url"), "title": r.get("title"), "snippet": r.get("content")})
            for r in payload.get("results") or []
        ) if item
    ]


def _search_serper(q: str, cfg: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    key = str(cfg.get("apiKey") or "")
    if not key:
        raise AIUnavailable("Add a Serper API key in Settings.")
    payload = _http_json(
        str(cfg.get("baseUrl") or "https://google.serper.dev/search"),
        body={"q": q, "num": max(limit * 2, limit)},
        headers={"X-API-KEY": key},
        timeout=float(cfg.get("timeoutSeconds") or 15),
    )
    return [
        item for item in (
            _normalize({"url": r.get("link"), "title": r.get("title"), "snippet": r.get("snippet")})
            for r in payload.get("organic") or []
        ) if item
    ]


def _search_searxng(q: str, cfg: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    base = str(cfg.get("baseUrl") or "http://127.0.0.1:8080/search").rstrip("/")
    url = f"{base}?q={urllib.parse.quote(q)}&format=json&language=en"
    _, text = _http(url, timeout=float(cfg.get("timeoutSeconds") or 15))
    payload = json.loads(text)
    return [
        item for item in (
            _normalize({"url": r.get("url"), "title": r.get("title"), "snippet": r.get("content")})
            for r in payload.get("results") or []
        ) if item
    ]


def search_with_gemini_grounding(
    query: str,
    grade: str = "",
    focus: str = "",
    limit: int = 3,
    log_key: str = "global",
    ai_config: dict[str, Any] | None = None,
    search_config: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Gemini Google Search grounding. Kept as an optional provider.

    Free-tier keys commonly return 429 here - the Settings page recommends
    DuckDuckGo / Tavily / Serper instead.
    """
    q = (query or (focus or "CBE classroom activity")).strip()
    log: dict[str, Any] = {"provider": "gemini-grounding", "query": q, "candidates": [], "returned": 0}
    cfg = ai_config or settings_service.get_settings()["ai"]
    prompt = (
        f"Find Kenyan CBC classroom activities for Grade {grade}, Focus: {focus or q}. "
        "Use ONLY activities, NOT worksheets. "
        'Return JSON: {"results":[{"title":"...","url":"...","snippet":"..."}]}. '
        'If none found, return {"results":[]}.'
    )
    try:
        text, candidate = _gemini_text(
            prompt, SYSTEM_PROMPT, cfg=cfg, json_mode=False, tools=[{"googleSearch": {}}]
        )
        chunks = (candidate.get("groundingMetadata") or {}).get("groundingChunks") or []
        try:
            data = json.loads(text) if text else {}
        except Exception:
            data = {}
        candidates = (data.get("results") or []) if isinstance(data, dict) else []
        if not isinstance(candidates, list):
            candidates = []
        if not candidates and chunks:
            for ch in chunks:
                web = (ch or {}).get("web") or {}
                if web.get("uri") or web.get("url"):
                    candidates.append({"title": web.get("title") or "", "url": web.get("uri") or web.get("url"), "snippet": ""})
        items = [it for it in (_normalize(dict(c)) for c in candidates if isinstance(c, dict)) if it]
        results = _rank_and_filter(items, q, limit, search_config or settings_service.get_settings()["search"])
        _WEB_SEARCH_LOGS[log_key] = {
            **log, "candidates": items, "status": "ok" if results else "empty",
            "returned": len(results),
            "message": "" if results else "Google Search grounding returned no usable links (check your grounding quota in Settings).",
        }
        return results, []
    except (AIError, AIUnavailable) as e:
        _WEB_SEARCH_LOGS[log_key] = {
            **log, "status": "unavailable", "message": WEB_SEARCH_UNAVAILABLE,
            "error": str(e)[:300],
        }
        return [], []


def _rank_and_filter(
    items: list[dict[str, Any]], q: str, limit: int, cfg: dict[str, Any]
) -> list[dict[str, Any]]:
    min_score = float(cfg.get("minScore") or 0)
    verify = bool(cfg.get("verifyLinks"))
    scored: list[tuple[float, dict[str, Any]]] = []
    seen: set[str] = set()
    for r in items:
        if r["url"] in seen:
            continue
        seen.add(r["url"])
        if verify and not _web_head_ok(r["url"]):
            continue
        s = _score_web_result(r["title"], r["snippet"], r["url"], q)
        if s >= min_score:
            scored.append((s, r))
    scored.sort(key=lambda x: -x[0])
    return [r for _, r in scored[:limit]]


_SEARCH_FUNCS = {
    "duckduckgo": _search_duckduckgo,
    "wikipedia": _search_wikipedia,
    "tavily": _search_tavily,
    "serper": _search_serper,
    "searxng": _search_searxng,
}


def _run_provider(
    provider: str,
    q: str,
    cfg: dict[str, Any],
    limit: int,
    grade: str,
    focus: str,
    ai_cfg: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if provider == "off":
        return []
    if provider == "gemini-grounding":
        results, _ = search_with_gemini_grounding(
            q, grade=grade, focus=focus, limit=limit,
            ai_config=ai_cfg, search_config=cfg,
        )
        return results
    func = _SEARCH_FUNCS.get(provider)
    if func is None:
        raise AIError(f"Unknown web search provider '{provider}'.")
    return func(q, cfg, limit)


def search_examples(
    query: str,
    limit: int = 3,
    grade: str = "",
    focus: str = "",
    log_key: str = "global",
    config_override: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Real web activity examples. Never invents results.

    Returns (results, errors). Failures are recorded in the search log so the
    UI can show *why* nothing came back instead of a silent empty list.

    ``config_override`` lets the Settings page test unsaved edits without
    writing them to disk.
    """
    cfg_all = settings_service.get_settings()
    cfg = dict(cfg_all["search"])
    if config_override:
        for k, v in config_override.items():
            if k not in cfg or v in (None, ""):
                continue
            if k == "apiKey":
                if str(v) == "__clear__":
                    meta = settings_service.provider_by_id("search", str(cfg.get("provider") or "duckduckgo"))
                    cfg["apiKey"] = settings_service.env_key(str(meta.get("keyEnv") or ""))
                elif "•" not in str(v):
                    cfg["apiKey"] = str(v)
                continue
            cfg[k] = v
    ai_cfg = dict(cfg_all["ai"])
    provider = str(cfg.get("provider") or "duckduckgo")
    limit = int(limit or cfg.get("maxResults") or 3)
    q = (query or "").strip()
    if not q:
        q = f"Kenya CBC Grade {grade} {focus} classroom activity".strip()
    if len(q.split()) < 4:
        q = f"{q} Kenya CBC classroom activity"

    log: dict[str, Any] = {
        "provider": provider,
        "query": q,
        "candidates": [],
        "returned": 0,
        "rejected": [],
    }
    if provider == "off":
        _WEB_SEARCH_LOGS[log_key] = {
            **log, "status": "off", "message": "Web search is turned off in Settings. Add your own example instead."
        }
        return [], []

    tried: list[str] = []
    errors: list[str] = []
    items: list[dict[str, Any]] = []
    primary = provider
    chain = ["auto-duckduckgo"] if provider == "auto" else [provider]
    if provider == "auto":
        # auto = use the keyed provider if one is configured, else no-key DuckDuckGo
        if cfg.get("apiKey"):
            chain.insert(0, "tavily")
        chain.append("wikipedia")
    for step in chain:
        p = step.replace("auto-", "")
        if p in tried:
            continue
        tried.append(p)
        try:
            items = _run_provider(p, q, cfg, limit, grade, focus, ai_cfg=ai_cfg)
            if items:
                provider = p
                break
        except (AIError, AIUnavailable) as e:
            errors.append(f"{p}: {e}")
        except Exception as e:
            errors.append(f"{p}: {type(e).__name__}: {e}")

    results = _rank_and_filter(items, q, limit, cfg)
    status = "ok" if results else "empty"
    message = ""
    if not results:
        message = (
            "; ".join(errors)[:300]
            or f"No usable results from {', '.join(tried)}. Try a different query or provider in Settings."
        )
    _WEB_SEARCH_LOGS[log_key] = {
        **log,
        "provider": provider,
        "tried": tried,
        "candidates": items[:20],
        "status": status,
        "returned": len(results),
        "message": message,
        "errors": errors,
    }
    return results, []


def test_search(query: str = "", override: dict[str, Any] | None = None) -> dict[str, Any]:
    """Settings-page smoke test for the web search provider (no disk writes)."""
    q = (query or "Kenya CBC Grade 1 counting classroom activity").strip()
    started = time.time()
    try:
        results, _ = search_examples(
            q, limit=3, log_key="__settings_test__", config_override=override
        )
        log = _WEB_SEARCH_LOGS.get("__settings_test__") or {}
        return {
            "ok": bool(results),
            "provider": log.get("provider") or "",
            "query": q,
            "latencyMs": int((time.time() - started) * 1000),
            "results": results,
            "message": (
                f"{len(results)} result(s) from {log.get('provider')} in {int((time.time() - started) * 1000)} ms."
                if results else log.get("message") or WEB_SEARCH_UNAVAILABLE
            ),
            "errors": log.get("errors") or [],
        }
    except Exception as e:
        return {
            "ok": False,
            "provider": "",
            "query": q,
            "latencyMs": int((time.time() - started) * 1000),
            "results": [],
            "message": f"{type(e).__name__}: {e}",
            "errors": [],
        }
