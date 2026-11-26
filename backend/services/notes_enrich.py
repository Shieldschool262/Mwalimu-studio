"""Optional AI enrichment for learner-facing Lesson Notes (Phase 5).

AI is OFF by default. It runs only when the teacher presses [Draft Notes with AI] and a
GEMINI_API_KEY exists. The prompt is deliberately strict: source-only, Grade-appropriate,
Kenyan examples, never new outcomes and never content beyond this lesson's focus.

The response shape is::

    {
      "vocabulary": [{"word": "...", "definition": "...", "example": "..."}],
      "whatIs": "paragraphs",
      "examples": ["..."],
      "workedExample": {"steps": ["..."]},
      "practice": [{"question": "...", "answer": "..."}],
      "remember": "..."
    }
"""
from __future__ import annotations

import re
from typing import Any

from services import ai_service


def system_prompt(grade: str | None) -> str:
    g = str(grade or "the learner").strip() or "the learner"
    return (
        f"You are a Kenyan CBE lesson notes writer for {g}. Use ONLY the source provided. "
        f"Write in simple, short sentences for {g} learners. Use Kenyan examples "
        "(bottle tops, stones, fruits, shillings, matatu, shamba). Do NOT teach beyond the "
        "focus. Do NOT add new outcomes. If you add an example, label it [AI Example]. "
        "For primary grades, suggest a short description for each [Picture: ...] placeholder "
        "instead of inventing an image. Do NOT invent facts."
    )


def user_prompt(context: dict[str, Any]) -> str:
    return (
        "Write learner-facing Lesson Notes for THIS lesson only.\n"
        "Return JSON with exactly these keys: vocabulary, whatIs, examples, workedExample, "
        "practice, remember.\n"
        "vocabulary is a list of {word, definition, example}. whatIs is one string with "
        "short paragraphs. examples is a list of strings. workedExample is "
        "{\"steps\": [strings]}. practice is a list of {question, answer}. remember is one "
        "short sentence. Do not use the phrase 'sub-strand'. Do not change the outcome.\n\n"
        f"Focus: {context.get('focus')}\n"
        f"Sub-Strand: {context.get('subStrand')}\n"
        f"Outcomes: {context.get('outcomes')}\n"
        f"Experiences: {context.get('experiences')}\n"
        f"KIQ: {context.get('kiq')}\n"
        f"Resources: {context.get('resources')}\n"
        f"Rubric: {context.get('rubric')}\n"
        f"Grade: {context.get('grade')}\n"
        f"Duration: {context.get('duration')} min."
    )


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _example(text: Any) -> str:
    s = _clean(text)
    if s and not s.startswith("["):
        return f"[AI Example] {s}"
    return s


def draft_notes(context: dict[str, Any]) -> dict[str, Any]:
    """Return normalized AI notes content. Raises AIUnavailable / AIError."""
    grade = context.get("grade")
    data = ai_service.post_gemini_json(
        user_prompt(context), system_prompt(grade)
    )

    vocabulary: list[dict[str, str]] = []
    for item in data.get("vocabulary") or []:
        if isinstance(item, str):
            word = _clean(item)
            if word:
                vocabulary.append(
                    {"word": word, "definition": "", "example": "", "source": "AI"}
                )
            continue
        if not isinstance(item, dict):
            continue
        word = _clean(item.get("word"))
        if not word:
            continue
        vocabulary.append(
            {
                "word": word,
                "definition": _clean(item.get("definition")),
                "example": _clean(item.get("example")),
                "source": "AI",
            }
        )

    what_is = data.get("whatIs")
    if isinstance(what_is, list):
        what_is = "\n\n".join(_clean(x) for x in what_is if _clean(x))
    what_is = str(what_is or "").strip()

    examples_raw = data.get("examples") or []
    if isinstance(examples_raw, str):
        examples_raw = [examples_raw]
    examples = [
        _example(x.get("text") if isinstance(x, dict) else x)
        for x in examples_raw
    ]
    examples = [x for x in examples if x]

    worked = data.get("workedExample") or {}
    if isinstance(worked, list):
        steps_raw = worked
    elif isinstance(worked, dict):
        steps_raw = worked.get("steps") or []
    else:
        steps_raw = []
    steps = [_clean(x.get("text") if isinstance(x, dict) else x) for x in steps_raw]
    steps = [x for x in steps if x]

    practice_raw = data.get("practice") or []
    if isinstance(practice_raw, str):
        practice_raw = [practice_raw]
    practice: list[dict[str, str]] = []
    for item in practice_raw:
        if isinstance(item, str):
            q = _clean(item)
            if q:
                practice.append({"question": q, "answer": ""})
            continue
        if not isinstance(item, dict):
            continue
        question = _clean(item.get("question"))
        if not question:
            continue
        practice.append(
            {"question": question, "answer": _clean(item.get("answer"))}
        )

    remember = _clean(data.get("remember"))

    return {
        "vocabulary": vocabulary,
        "whatIs": what_is,
        "examples": examples,
        "workedExample": {"steps": steps},
        "practice": practice,
        "remember": remember,
    }
