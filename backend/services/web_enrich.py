"""Web enrichment helpers (Phase 4/5).

Canonical implementation lives in ``services.ai_service``; this module re-exports
it so callers importing ``services.web_enrich`` keep working.
"""
from services.ai_service import (  # noqa: F401
    WEB_SEARCH_MIN_SCORE,
    WEB_SEARCH_UNAVAILABLE,
    _WEB_SEARCH_LOGS,
    _score_web_result,
    _web_head_ok,
    get_web_search_log,
    search_examples,
    search_with_gemini_grounding,
)
PY = None
