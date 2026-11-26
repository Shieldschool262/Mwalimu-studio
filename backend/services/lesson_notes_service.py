"""Learner-facing Lesson Notes (Phase 5).

ONE NOTE = ONE LESSON. Notes are content for learners, not teacher plans:

* generated from a Vetted source chunk (Lesson Plan or scheme row),
* focused on exactly the same atomic skill as the Lesson Plan (lesson_derive.py),
* fully editable without ever mutating the SourceChunk,
* optionally enriched by Gemini and teacher-initiated web search,
* versioned append-only, with a learner-friendly portrait A4 PDF.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from auth_service import current_owner_id
from db import connect, new_id
from services import ai_service, notes_enrich
from services.library_service import VETTED
from services.lesson_derive import assign_lessons, decompose_experiences, preview_labels
from services.lesson_plan_service import decomposition_for_section, lesson_slo
from services.lesson_templates import load_notes_template, effective_notes_template
from services.rubric_service import ensure_chunk_rubric

STATUSES = ("Draft", "Final")
SLO_HEADING = "By the end of the lesson, you will be able to:"
VETTING_MESSAGE = "Cannot generate notes - source not Vetted"
AI_MESSAGE = "AI enrichment needs an API key - open Settings to configure a free provider."

NOTE_KEYS = (
    "title",
    "slo",
    "vocabulary",
    "whatIs",
    "examples",
    "workedExample",
    "practice",
    "remember",
    "footer",
)

AI_SECTION_KEYS = ("vocabulary", "whatIs", "examples", "workedExample", "practice", "remember")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _json(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value) if value else default
    except Exception:
        return default


def _clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _title(text: str) -> str:
    text = _clean(text)
    if not text:
        return text
    return text[0].upper() + text[1:]


def _items(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    if isinstance(value, str) and value.strip():
        parsed = _json(value, None)
        if isinstance(parsed, list):
            return [str(x) for x in parsed if str(x).strip()]
        return [ln.strip() for ln in value.splitlines() if ln.strip()]
    return []


def _page_from_text(text: Any) -> int | None:
    m = re.search(r"\bp\.\s*(\d+)", str(text or ""), re.I)
    return int(m.group(1)) if m else None


def _section_lesson_count(section: Any) -> int:
    start = section["lesson_start"] or 1
    end = section["lesson_end"] or start
    return max(1, int(end) - int(start) + 1)


# ---------------------------------------------------------------------------
# Focus, title and SLO - identical atomic focus to the Lesson Plan
# ---------------------------------------------------------------------------

_VERB_GERUND = {
    "sort": "Sorting",
    "group": "Grouping",
    "match": "Matching",
    "order": "Ordering",
    "count": "Counting",
    "identify": "Identifying",
    "name": "Naming",
    "read": "Reading",
    "write": "Writing",
    "classify": "Classifying",
    "compare": "Comparing",
    "measure": "Measuring",
    "describe": "Describing",
    "recognize": "Recognizing",
    "recognise": "Recognising",
    "add": "Adding",
    "subtract": "Subtracting",
    "multiply": "Multiplying",
    "divide": "Dividing",
    "draw": "Drawing",
    "colour": "Colouring",
    "color": "Coloring",
    "make": "Making",
    "use": "Using",
}


def _title_words(text: str) -> str:
    small = {"and", "or", "of", "to", "by", "in", "on", "the", "a", "an"}
    words = _clean(text).split()
    out = []
    for i, word in enumerate(words):
        low = word.lower()
        if i > 0 and low in small:
            out.append(low)
        elif re.match(r"^\d", word):
            out.append(word)
        else:
            out.append(word[0].upper() + word[1:] if word else word)
    return " ".join(out)


def focus_label(assignment: dict[str, Any]) -> str:
    """'Sort objects by colour' -> 'Sorting by Colour' (learner-facing)."""
    kind = str(assignment.get("kind") or "atomic")
    if kind == "consolidation":
        return "Consolidation and Practice"
    if kind == "assessment":
        return "Assessment and Revision"
    focus = _clean(assignment.get("focus") or "")
    if ":" in focus and focus.lower().startswith(("consolidation", "assessment")):
        return "Assessment and Revision" if focus.lower().startswith("assessment") else "Consolidation and Practice"
    atomic = assignment.get("atomic") or {}
    text = _clean(atomic.get("text") or focus)
    m = re.match(r"([A-Za-z][A-Za-z-]*)\b(.*)$", text)
    if m:
        verb = m.group(1).lower()
        rest = m.group(2).strip()
        gerund = _VERB_GERUND.get(verb)
        if gerund:
            if " by " in rest.lower():
                attr = rest.split(" by ", 1)[1]
                return f"{gerund} by {_title_words(attr)}"
            if rest:
                return _title_words(f"{gerund} {rest}")
            return gerund
    keyword = _clean(assignment.get("focus_keyword") or "")
    if keyword:
        return _title_words(keyword)
    return _title(focus)


def notes_title(sub_strand: str | None, assignment: dict[str, Any]) -> str:
    label = focus_label(assignment)
    sub = _clean(sub_strand)
    return f"{sub} - {label}" if sub else label


def _slo_body(assignment: dict[str, Any], lesson_plan_row: Any = None, conn: Any = None) -> str:
    rest = ""
    if lesson_plan_row is not None and conn is not None:
        section = conn.execute(
            "SELECT body FROM lesson_plan_sections WHERE lesson_plan_id = ? AND key = 'outcomes'",
            (lesson_plan_row["id"],),
        ).fetchone()
        if section and section["body"]:
            raw = str(section["body"])
            rest = raw.split("able to:", 1)[-1].strip()
    if not rest:
        raw = lesson_slo(assignment)
        rest = raw.split("able to:", 1)[-1].strip()
    rest = re.sub(r"^a\)\s*", "", rest).strip()
    if not rest or rest == "—":
        rest = _clean(assignment.get("focus") or "")
    rest = re.sub(r"\bsub-?strand\b", "lesson", rest, flags=re.I)
    return f"{SLO_HEADING} {rest}".strip()


# ---------------------------------------------------------------------------
# Deterministic baseline content (no LLM)
# ---------------------------------------------------------------------------

_VOCAB = {
    "colour": (
        "Colour is how something looks, such as red, blue, yellow or green.",
        "The bottle top is red.",
    ),
    "color": (
        "Color is how something looks, such as red, blue, yellow or green.",
        "The bottle top is red.",
    ),
    "shape": (
        "Shape is the outline of something, such as a circle, square or triangle.",
        "The stone is round.",
    ),
    "size": (
        "Size tells us how big or small something is.",
        "The big stone is heavier than the small stone.",
    ),
    "texture": (
        "Texture is how something feels when you touch it, such as rough or smooth.",
        "The tree bark feels rough.",
    ),
    "weight": (
        "Weight tells us how heavy or light something is.",
        "The full water bottle is heavy.",
    ),
    "number": (
        "A number tells us how many things there are.",
        "There are five stones in the group.",
    ),
    "sort": (
        "To sort means to put things into groups that are alike.",
        "We sort the fruits by colour.",
    ),
    "group": (
        "A group is a set of things that belong together.",
        "The red bottle tops are in one group.",
    ),
    "pattern": (
        "A pattern is a repeated arrangement of shapes, colours or numbers.",
        "The beads make a red, blue, red, blue pattern.",
    ),
    "counting": (
        "Counting means saying numbers in order to find how many things there are.",
        "We count the stones one by one.",
    ),
}


def _keyword_vocab(keyword: str) -> tuple[str, str]:
    key = _clean(keyword).lower()
    if key in _VOCAB:
        return _VOCAB[key]
    if not key:
        return ("", "")
    return (
        f"{_title(key)} is an important word in this lesson.",
        f"We use the word {key} when we talk about our work.",
    )


_PLACEHOLDER_TEXT = re.compile(r"^[\s\-—––]+$|^—?\s*See Week \d+$", re.I)


def _source_texts(source: dict[str, Any] | None, key: str) -> list[str]:
    """Cleaned string list from the lesson's source payload (placeholders dropped)."""
    if not source:
        return []
    return [
        _clean(x)
        for x in (source.get(key) or [])
        if _clean(x) and not _PLACEHOLDER_TEXT.match(str(x).strip())
    ]


def _is_sorting_source(source: dict[str, Any] | None) -> bool:
    """True only when the lesson's own source text is about sorting objects."""
    text = " ".join(
        _source_texts(source, "experiences") + _source_texts(source, "outcomes")
    ).lower()
    return "sort" in text


def _effective_keyword(keyword: str, source: dict[str, Any] | None) -> str:
    """Resolve the content keyword for a lesson.

    Consolidation / assessment lessons (and blank keywords) inherit the 'sort'
    keyword ONLY when the lesson's own source experiences are about sorting.
    Anything else is treated as unknown and gets source-derived content, never
    unrelated subject material.
    """
    key = _clean(keyword).lower()
    if key in ("consolidation", "assessment", "") and _is_sorting_source(source):
        return "sort"
    return key


def _vocabulary_source(keyword: str, source: dict[str, Any] | None) -> list[dict[str, str]]:
    """Vocabulary for a keyword with no known definition: derived from the
    lesson's own source (experiences / KIQs), never from unrelated content."""
    key = _clean(keyword).lower()
    experiences = _source_texts(source, "experiences")
    kiqs = _source_texts(source, "kiqs")
    example = experiences[0] if experiences else (kiqs[0] if kiqs else "")
    items: list[dict[str, str]] = [
        {
            "word": key or "lesson",
            "definition": f"{_title(key) if key else 'This lesson'} is the focus of this lesson.",
            "example": example or "See the learning experiences for this lesson.",
            "source": "From source",
        }
    ]
    if len(experiences) > 1:
        items.append(
            {
                "word": "activity",
                "definition": "An activity is something you do to learn.",
                "example": experiences[1],
                "source": "From source",
            }
        )
    return items


def _vocabulary(
    keyword: str, template: dict[str, Any], source: dict[str, Any] | None = None
) -> list[dict[str, str]]:
    key = _effective_keyword(keyword, source)
    if key not in _VOCAB:
        return _vocabulary_source(key, source)
    definition, example = _keyword_vocab(key)
    items: list[dict[str, str]] = [
        {
            "word": key,
            "definition": definition,
            "example": example,
            "source": "From source",
        },
        {
            "word": "sort",
            "definition": _VOCAB["sort"][0],
            "example": _VOCAB["sort"][1],
            "source": "From source",
        },
        {
            "word": "group",
            "definition": _VOCAB["group"][0],
            "example": _VOCAB["group"][1],
            "source": "From source",
        },
    ]
    if template.get("gradeBand") == "jss":
        items.append(
            {
                "word": "attribute",
                "definition": "An attribute is a feature we can observe, such as colour, shape or size.",
                "example": "Colour and shape are attributes of an object.",
                "source": "From source",
            }
        )
    seen: set[str] = set()
    out = []
    for item in items:
        if item["word"] in seen:
            continue
        seen.add(item["word"])
        out.append(item)
    return out


_WHAT_IS = {
    "colour": [
        "Sorting by colour means putting things into groups by their colour.",
        "Look at each object. Put the red things together. Put the blue things together. Put the yellow things together.",
        "When you sort, every object goes into the group that matches its colour.",
    ],
    "color": [
        "Sorting by color means putting things into groups by their color.",
        "Look at each object. Put the red things together. Put the blue things together. Put the yellow things together.",
        "When you sort, every object goes into the group that matches its color.",
    ],
    "shape": [
        "Sorting by shape means putting things into groups by their shape.",
        "Look at each object. Put the round things together. Put the square things together. Put the triangle things together.",
        "When you sort, every object goes into the group that matches its shape.",
    ],
    "size": [
        "Sorting by size means putting things into groups by how big or small they are.",
        "Put the big things together. Put the small things together.",
        "When you sort by size, you compare the objects carefully.",
    ],
    "texture": [
        "Sorting by texture means putting things into groups by how they feel.",
        "Put the rough things together. Put the smooth things together.",
        "We can feel texture with our hands.",
    ],
    "weight": [
        "Sorting by weight means putting things into groups by how heavy or light they are.",
        "Put the heavy things together. Put the light things together.",
        "We can compare weight by holding the objects.",
    ],
}


def _what_is_source(
    label: str, source: dict[str, Any] | None, template: dict[str, Any] | None = None
) -> str:
    """'What is it?' paragraphs for a lesson with no known keyword: built from
    the lesson's own sub-strand, experiences and key inquiry questions."""
    sub = _clean((source or {}).get("subStrand") or (source or {}).get("strand") or "")
    experiences = _source_texts(source, "experiences")
    kiqs = _source_texts(source, "kiqs")
    paras: list[str] = []
    if sub:
        paras.append(f"This lesson is part of {sub}. The focus is {label}.")
    else:
        paras.append(f"This lesson focuses on {label}.")
    if experiences:
        lines = "\n".join(f"- {e}" for e in experiences[:3])
        paras.append(f"In this lesson you will:\n{lines}")
    if kiqs:
        paras.append(f"Think about this question: {kiqs[0]}")
    if not paras[1:]:
        paras.append("Your teacher will guide you through the lesson activities.")
    if template and template.get("gradeBand") == "jss":
        # JSS explanations are longer; the key idea stays inside the source text.
        if len(experiences) > 1:
            paras.append(f"Key idea: {experiences[1]}")
        elif kiqs:
            paras.append(f"Key idea: keep this question in mind - {kiqs[0]}")
        else:
            paras.append("Key idea: talk about what you did in your group and record what you found out.")
    return "\n\n".join(paras)


def _what_is(
    keyword: str,
    label: str,
    template: dict[str, Any],
    source: dict[str, Any] | None = None,
) -> str:
    key = _effective_keyword(keyword, source)
    paras = _WHAT_IS.get(key)
    if not paras:
        return _what_is_source(label, source, template)
    if template.get("gradeBand") == "jss":
        paras = list(paras) + [
            f"Key idea: when we {label.lower()}, we use one clear attribute at a time so that the groups do not mix.",
        ]
    return "\n\n".join(paras)


_EXAMPLES = {
    "colour": [
        "Red bottle tops in one group and blue bottle tops in another.",
        "Yellow bananas and green bananas on two plates.",
        "Red, blue and yellow pencils sorted in a tin.",
    ],
    "color": [
        "Red bottle tops in one group and blue bottle tops in another.",
        "Yellow bananas and green bananas on two plates.",
        "Red, blue and yellow pencils sorted in a tin.",
    ],
    "shape": [
        "Round stones and square tiles in two groups.",
        "Circular lids and rectangular cards sorted on a table.",
        "A ball, a box and a book sorted by shape.",
    ],
    "size": [
        "Big stones and small stones in two piles.",
        "Long sticks and short sticks separated in the shamba.",
        "Large mangoes and small mangoes on two plates.",
    ],
    "texture": [
        "Rough tree bark and smooth bottle tops in two groups.",
        "Soft cotton and hard stones sorted by touch.",
        "Rough sandpaper and smooth paper in the classroom.",
    ],
    "weight": [
        "Heavy stones and light leaves in two groups.",
        "A full water bottle and an empty cup compared by weight.",
        "Full and empty tins sorted on a scale.",
    ],
}

_PICTURE = {
    "colour": "[Picture: Red and blue bottle tops sorted into two groups.]",
    "color": "[Picture: Red and blue bottle tops sorted into two groups.]",
    "shape": "[Picture: Round stones and square tiles sorted into two groups.]",
    "size": "[Picture: Big stones and small stones sorted into two piles.]",
    "texture": "[Picture: Rough bark and smooth bottle tops sorted into two groups.]",
    "weight": "[Picture: A heavy stone and a light leaf on a simple balance.]",
}

_DIAGRAM = {
    "colour": "[Diagram: A table with colour groups labelled red, blue and yellow.]",
    "color": "[Diagram: A table with colour groups labelled red, blue and yellow.]",
    "shape": "[Diagram: A table with shape groups labelled circle, square and triangle.]",
    "size": "[Diagram: A number line showing small, medium and large objects.]",
}


def _examples(
    keyword: str, template: dict[str, Any], source: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    key = _effective_keyword(keyword, source)
    known = _EXAMPLES.get(key)
    if known:
        texts = list(known)
    else:
        # No known examples for this keyword: use the lesson's own experiences.
        texts = _source_texts(source, "experiences")[:3]
        if not texts:
            texts = ["Discuss the lesson focus with your teacher and classmates."]
    items: list[dict[str, Any]] = [
        {"text": text, "source": "From source"} for text in texts
    ]
    if template.get("picturePlaceholders"):
        caption = f"[Picture: {items[0]['text']}]" if items else "[Picture: The lesson activity.]"
        items.append({"text": _PICTURE.get(key, caption), "source": "Picture"})
    elif template.get("gradeBand") == "jss":
        caption = f"[Diagram: {items[0]['text']}]" if items else "[Diagram: The lesson activity.]"
        items.append({"text": _DIAGRAM.get(key, caption), "source": "Diagram"})
    return items


_WORKED = {
    "colour": [
        "Put all the objects on the table.",
        "Choose two colours, for example red and blue.",
        "Look at each object and say its colour.",
        "Put the red objects in one group and the blue objects in another group.",
        "Count how many objects are in each group and say what you sorted by.",
    ],
    "color": [
        "Put all the objects on the table.",
        "Choose two colors, for example red and blue.",
        "Look at each object and say its color.",
        "Put the red objects in one group and the blue objects in another group.",
        "Count how many objects are in each group and say what you sorted by.",
    ],
    "shape": [
        "Put all the objects on the table.",
        "Choose two shapes, for example circles and squares.",
        "Look at the outline of each object.",
        "Put the round objects in one group and the square objects in another group.",
        "Say what you sorted by and check that every object is in the right group.",
    ],
    "size": [
        "Put all the objects on the table.",
        "Compare two objects and decide which one is bigger.",
        "Put the big objects in one group and the small objects in another group.",
        "Check each object again and move it if it is in the wrong group.",
        "Say what you sorted by.",
    ],
}

_PRACTICE = {
    "colour": [
        ("What colour is a ripe banana?", "Yellow."),
        ("You put red bottle tops in one group and blue bottle tops in another. What did you sort by?", "Colour."),
        ("A blue stone and a red stone are in the same group. Is that sorting by colour?", "No."),
        ("Name two colours you can see in your classroom.", "Any two colours, for example red and blue."),
        ("A learner sorts 12 bottle tops into red, blue and yellow groups. What attribute did the learner use?", "Colour."),
        ("Why should we use one attribute at a time when sorting?", "So the groups are clear and do not mix."),
    ],
    "color": [
        ("What color is a ripe banana?", "Yellow."),
        ("You put red bottle tops in one group and blue bottle tops in another. What did you sort by?", "Color."),
        ("A blue stone and a red stone are in the same group. Is that sorting by color?", "No."),
        ("Name two colors you can see in your classroom.", "Any two colors, for example red and blue."),
        ("A learner sorts 12 bottle tops into red, blue and yellow groups. What attribute did the learner use?", "Color."),
        ("Why should we use one attribute at a time when sorting?", "So the groups are clear and do not mix."),
    ],
    "shape": [
        ("What shape is a ball?", "A sphere (round)."),
        ("You put round stones in one group and square tiles in another. What did you sort by?", "Shape."),
        ("A round lid and a square card are in the same group. Is that sorting by shape?", "No."),
        ("Name two shapes you can see in your classroom.", "Any two shapes, for example circle and square."),
        ("A learner sorts 10 objects into circles, squares and triangles. What attribute did the learner use?", "Shape."),
        ("Why do we look at the outline of an object when sorting by shape?", "The outline shows the shape clearly."),
    ],
    "size": [
        ("Which is bigger: a big stone or a small stone?", "The big stone."),
        ("You put big mangoes in one group and small mangoes in another. What did you sort by?", "Size."),
        ("A long stick and a short stick are in the same group. Is that sorting by size?", "No."),
        ("Name two things in your classroom that are different sizes.", "Any two things, for example a desk and a pencil."),
        ("A learner sorts 9 stones into big, medium and small groups. What attribute did the learner use?", "Size."),
        ("Why do we compare two objects before putting them into a size group?", "To decide which one is bigger or smaller."),
    ],
}

_REMEMBER = {
    "colour": "We sort by colour when we put things with the same colour together.",
    "color": "We sort by color when we put things with the same color together.",
    "shape": "We sort by shape when we put things with the same shape together.",
    "size": "We sort by size when we put big things together and small things together.",
    "texture": "We sort by texture when we put things that feel the same together.",
    "weight": "We sort by weight when we put heavy things together and light things together.",
    "sort": "We sort objects when we put things that are alike into the same group.",
    "group": "A group is a set of things that belong together.",
}


def _worked(keyword: str, source: dict[str, Any] | None = None) -> list[str]:
    key = _effective_keyword(keyword, source)
    steps = _WORKED.get(key)
    if steps:
        return list(steps)
    # No known worked example: turn the lesson's own experiences into steps.
    steps = _source_texts(source, "experiences")[:5]
    if steps:
        return [f"Step: {s}" for s in steps]
    return [
        "Follow the learning experiences for this lesson with your teacher.",
        "Record what you did and what you found out.",
    ]


def _practice_source(
    keyword: str, source: dict[str, Any] | None, count: int
) -> list[tuple[str, str]]:
    """Practice questions for a lesson with no known keyword: the lesson's own
    key inquiry questions first, then meta-questions about the lesson focus."""
    key = _clean(keyword).lower()
    pairs: list[tuple[str, str]] = []
    for q in _source_texts(source, "kiqs"):
        pairs.append((q, "Discuss your answer with your teacher and classmates."))
        if len(pairs) >= count:
            return pairs[:count]
    experiences = _source_texts(source, "experiences")
    if experiences:
        pairs.append(
            (
                f"What did you do in this lesson about {key or 'the lesson focus'}?",
                experiences[0],
            )
        )
    pairs.extend(
        [
            (
                f"What is one thing you learned about {key or 'the lesson focus'} today?",
                "Use your own words from the lesson activities.",
            ),
            ("Which part of the lesson activity was hardest for you? Why?", "Explain in your own words."),
            ("What did you enjoy most in this lesson? Why?", "Say what you did and why you liked it."),
            ("Which question would you like to explore further?", "Choose one thing from the lesson activities."),
        ]
    )
    while len(pairs) < count:
        pairs.append(
            (
                f"Tell your partner one new thing you learned about {key or 'the lesson focus'}.",
                "Use your own words from the lesson activities.",
            )
        )
    return pairs[:count]


def _practice(
    keyword: str, template: dict[str, Any], source: dict[str, Any] | None = None
) -> list[dict[str, str]]:
    key = _effective_keyword(keyword, source)
    pairs = _PRACTICE.get(key)
    if pairs:
        count = int(template.get("practiceCount") or 4)
        chosen = list(pairs[:count])
        while len(chosen) < count:
            chosen.append(
                (
                    f"Explain in one sentence how you would sort objects by {key or 'one attribute'}.",
                    f"Put objects with the same {key or 'attribute'} in one group.",
                )
            )
        return [{"question": q, "answer": a} for q, a in chosen[:count]]
    # Unknown keyword: source-derived questions, never unrelated content.
    count = int(template.get("practiceCount") or 4)
    pairs = _practice_source(key, source, count)
    return [{"question": q, "answer": a} for q, a in pairs]


def _remember(keyword: str, source: dict[str, Any] | None = None) -> str:
    key = _effective_keyword(keyword, source)
    if key in _REMEMBER:
        return _REMEMBER[key]
    # Unknown keyword: remember line drawn from the lesson's own source.
    sub = _clean((source or {}).get("subStrand") or (source or {}).get("strand") or "")
    label = _title(key) if key else "this lesson"
    if sub:
        return f"Remember: {label} is part of {sub}. Keep practising it in your lesson activities."
    return f"Remember: this lesson focused on {label}. Keep practising it in your lesson activities."


# ---------------------------------------------------------------------------
# Source loading and vetting
# ---------------------------------------------------------------------------


def _chunk_for_section(conn: Any, plan_id: str, section_id: str) -> Any:
    cit = conn.execute(
        """SELECT * FROM plan_citations
           WHERE plan_id = ? AND section_id = ? AND field = 'specific_learning_outcomes'
           ORDER BY rowid LIMIT 1""",
        (plan_id, section_id),
    ).fetchone()
    if cit is None:
        cit = conn.execute(
            "SELECT * FROM plan_citations WHERE plan_id = ? AND section_id = ? ORDER BY rowid LIMIT 1",
            (plan_id, section_id),
        ).fetchone()
    return cit


def _chunk_vetting(chunk_id: str | None) -> str:
    if not chunk_id:
        return "Pending"
    with connect() as conn:
        row = conn.execute(
            "SELECT vetting_status FROM source_chunks WHERE id = ?", (chunk_id,)
        ).fetchone()
    if row is None:
        return "Pending"
    return row["vetting_status"] if "vetting_status" in row.keys() else "Pending"


def _source_payload(
    plan: Any,
    section: Any,
    cit: Any,
    rubric: list[dict[str, Any]],
    lesson_plan: Any = None,
) -> dict[str, Any]:
    page = cit["page_number"] if cit else None
    if lesson_plan is not None:
        base = _json(lesson_plan["source_json"], {})
    else:
        base = {}
    experiences = _items(section["experiences"])
    if not experiences:
        original = _json(section["original"], {})
        experiences = [str(x) for x in original.get("sourceExperiences") or []]
    original = _json(section["original"], {})
    source = {
        **base,
        "strand": section["strand"],
        "strandCode": section["strand_code"],
        "subStrand": section["sub_strand"],
        "subStrandCode": section["sub_strand_code"],
        "page": page,
        "documentId": cit["document_id"] if cit else None,
        "chunkId": cit["chunk_id"] if cit else None,
        "outcomes": _items(section["outcomes"]) or base.get("outcomes") or [],
        "outcomesHeading": "Source: By the end of the sub-strand, the learner should be able to:",
        "experiences": experiences,
        "kiqs": _items(section["kiqs"]) or base.get("kiqs") or [],
        "competencies": section["competencies"] or base.get("competencies"),
        "values": section["values_text"] or base.get("values"),
        "pcis": section["pcis"] or base.get("pcis"),
        "resources": section["resources"] or original.get("resources") or base.get("resources"),
        "appendixResources": original.get("appendixResources") or base.get("appendixResources"),
        "appendixAssessment": original.get("appendixAssessment") or base.get("appendixAssessment"),
        "appendixSource": original.get("appendixSource") or base.get("appendixSource"),
        "rubric": rubric or base.get("rubric") or [],
        "schemeAssessment": section["assessment"] or original.get("assessment") or "",
        "subject": plan["subject"],
        "grade": plan["grade"],
        "duration": lesson_plan["duration"] if lesson_plan is not None else 35,
        "sourceLabel": (
            f"{section['sub_strand'] or section['strand'] or 'Source'} p.{page}"
            if page
            else (section["sub_strand"] or "Source")
        ),
    }
    return source


# ---------------------------------------------------------------------------
# Build sections
# ---------------------------------------------------------------------------


def _section_values(
    key: str,
    template: dict[str, Any],
    title: str,
    slo: str,
    assignment: dict[str, Any],
    source: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    keyword = _clean(assignment.get("focus_keyword") or "")
    label = focus_label(assignment)
    if key == "title":
        return title, {
            "week": None,
            "lesson": None,
            "focus": assignment.get("focus") or label,
        }
    if key == "slo":
        return slo, {}
    if key == "vocabulary":
        return "", {"items": _vocabulary(keyword, template, source)}
    if key == "whatIs":
        return _what_is(keyword, label, template, source), {"paragraphs": []}
    if key == "examples":
        return "", {"items": _examples(keyword, template, source)}
    if key == "workedExample":
        return "", {"steps": _worked(keyword, source)}
    if key == "practice":
        return "", {"items": _practice(keyword, template, source)}
    if key == "remember":
        return _remember(keyword, source), {}
    return "", {}


def _insert_sections(
    conn: Any,
    note_id: str,
    template: dict[str, Any],
    title: str,
    slo: str,
    assignment: dict[str, Any],
    week: int,
    lesson: int,
    source: dict[str, Any] | None = None,
) -> None:
    for ord_, spec in enumerate(template.get("sections") or []):
        key = str(spec.get("key") or "")
        body, data = _section_values(key, template, title, slo, assignment, source)
        if key == "title":
            data["week"] = week
            data["lesson"] = lesson
            data["subject"] = ""
        conn.execute(
            """INSERT INTO lesson_note_sections
               (id, note_id, ord, key, title, body, data_json, source_body,
                source_data_json, placeholder, hint, provenance, editable, ai_draft,
                ai_data_json, ai_assisted)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                new_id(),
                note_id,
                ord_,
                key,
                str(spec.get("title") or key),
                body,
                json.dumps(data, ensure_ascii=False),
                body,
                json.dumps(data, ensure_ascii=False),
                spec.get("placeholder"),
                spec.get("hint"),
                "source" if key in ("slo", "vocabulary", "examples", "practice") else "source-derived",
                1 if spec.get("editable", True) else 0,
                None,
                "{}",
                0,
            ),
        )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def _new_note(
    conn: Any,
    plan: Any,
    section: Any,
    cit: Any,
    lesson: int,
    assignment: dict[str, Any],
    lesson_plan: Any,
    template_version: str,
    template: dict[str, Any],
    rubric: list[dict[str, Any]],
    source: dict[str, Any],
) -> str:
    note_id = new_id()
    title = notes_title(section["sub_strand"], assignment)
    slo = _slo_body(assignment, lesson_plan, conn)
    count = _section_lesson_count(section)
    conn.execute(
        """INSERT INTO lesson_notes
           (id, lesson_plan_id, plan_id, section_id, chunk_id, document_id, week, lesson,
            lesson_count, strand, sub_strand, sub_strand_code, focus, focus_keyword, title,
            grade, subject, term, status, template_version, source_json, ai_enriched,
            created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            note_id,
            lesson_plan["id"] if lesson_plan is not None else None,
            plan["id"],
            section["id"],
            cit["chunk_id"] if cit else None,
            cit["document_id"] if cit else None,
            section["week_start"] or 1,
            lesson,
            count,
            section["strand"],
            section["sub_strand"],
            section["sub_strand_code"],
            assignment.get("focus") or f"Lesson {lesson}",
            assignment.get("focus_keyword") or "",
            title,
            plan["grade"],
            plan["subject"],
            plan["term"],
            "Draft",
            template_version,
            json.dumps(source, ensure_ascii=False),
            0,
            _now(),
            _now(),
        ),
    )
    _insert_sections(
        conn,
        note_id,
        template,
        title,
        slo,
        assignment,
        section["week_start"] or 1,
        lesson,
        source,
    )
    # Keep the title section's metadata in sync with the real lesson.
    conn.execute(
        """UPDATE lesson_note_sections SET data_json = ?, source_data_json = ?
           WHERE note_id = ? AND key = 'title'""",
        (
            json.dumps(
                {
                    "week": section["week_start"] or 1,
                    "lesson": lesson,
                    "focus": assignment.get("focus") or "",
                    "subject": plan["subject"],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "week": section["week_start"] or 1,
                    "lesson": lesson,
                    "focus": assignment.get("focus") or "",
                    "subject": plan["subject"],
                },
                ensure_ascii=False,
            ),
            note_id,
        ),
    )
    return note_id


def create_lesson_notes(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    lesson_plan_id = str(payload.get("lessonPlanId") or "").strip()
    section_id = str(payload.get("schemeRowId") or payload.get("sectionId") or "").strip()
    requested: list[int] = []

    with connect() as conn:
        lesson_plan = None
        if lesson_plan_id:
            lesson_plan = conn.execute(
                "SELECT * FROM lesson_plans WHERE id = ?", (lesson_plan_id,)
            ).fetchone()
            if lesson_plan is None:
                return [], ["Lesson plan not found."]
            section_id = lesson_plan["section_id"]
            requested = [int(lesson_plan["lesson"])]
        else:
            raw_lessons = payload.get("lessons") or []
            if not isinstance(raw_lessons, list) or not raw_lessons:
                return [], ["Select at least one lesson."]
            try:
                requested = sorted({int(x) for x in raw_lessons})
            except (TypeError, ValueError):
                return [], ["Lessons must be whole numbers."]

        section = conn.execute(
            "SELECT * FROM plan_sections WHERE id = ?", (section_id,)
        ).fetchone()
        if section is None:
            return [], ["Scheme row not found."]
        plan = conn.execute(
            "SELECT * FROM plan_documents WHERE id = ?", (section["plan_id"],)
        ).fetchone()
        if plan is None:
            return [], ["Scheme not found."]
        cit = _chunk_for_section(conn, plan["id"], section_id)
        chunk_id = cit["chunk_id"] if cit else None
        if _chunk_vetting(chunk_id) != VETTED:
            return [], [VETTING_MESSAGE]

        count = _section_lesson_count(section)
        if any(l < 1 or l > count for l in requested):
            return [], [f"Lesson must be a single number from 1 to {count}."]

        template_version = effective_notes_template(
            payload.get("templateVersion"), plan["grade"]
        )
        template = load_notes_template(template_version, plan["grade"])
        decomposition = decomposition_for_section(section)
        assignments = decomposition["assignments"]

        existing_lessons = {
            int(r["lesson"])
            for r in conn.execute(
                "SELECT lesson FROM lesson_notes WHERE section_id = ?", (section_id,)
            ).fetchall()
        }

        original = _json(section["original"], {})
        rubric = original.get("rubric") or []
        if not rubric and chunk_id:
            rubric = ensure_chunk_rubric(chunk_id)
        source = _source_payload(plan, section, cit, rubric, lesson_plan)

        created: list[str] = []
        errors: list[str] = []
        for lesson in requested:
            if lesson in existing_lessons:
                errors.append(
                    f"Lesson notes for Lesson {lesson} already exist - nothing duplicated."
                )
                continue
            plan_row = lesson_plan
            if plan_row is None:
                plan_row = conn.execute(
                    "SELECT * FROM lesson_plans WHERE section_id = ? AND lesson = ?",
                    (section_id, lesson),
                ).fetchone()
            assignment = (
                assignments[lesson - 1]
                if 0 <= lesson - 1 < len(assignments)
                else {
                    "lesson": lesson,
                    "kind": "atomic",
                    "focus": f"Lesson {lesson}",
                    "focus_keyword": "",
                    "atomic": None,
                    "source_quote": "",
                }
            )
            if plan_row is not None:
                # The Lesson Plan is the authority for focus + SLO once it exists.
                assignment = {
                    **assignment,
                    "lesson": lesson,
                    "focus": plan_row["focus"] or assignment.get("focus"),
                    "focus_keyword": plan_row["focus_keyword"] or assignment.get("focus_keyword"),
                }
                if plan_row["source_experience"]:
                    assignment["source_quote"] = plan_row["source_experience"]
            note_id = _new_note(
                conn,
                plan,
                section,
                cit,
                lesson,
                assignment,
                plan_row,
                template_version,
                template,
                rubric,
                source,
            )
            created.append(note_id)

        if not created:
            if not errors:
                errors.append("These lesson notes already exist - nothing duplicated.")

    out: list[dict[str, Any]] = []
    for note_id in created:
        payload_note = get_lesson_note(note_id)
        if payload_note:
            create_note_version(
                note_id,
                f"Initial version - Week {payload_note['week']} Lesson {payload_note['lesson']}",
                kind="initial",
            )
            out.append(get_lesson_note(note_id) or payload_note)
    return out, errors


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def _section_dict(row: Any, note_source: dict[str, Any]) -> dict[str, Any]:
    data = _json(row["data_json"], {})
    source_body = row["source_body"]
    source_data = _json(row["source_data_json"], {})
    body = row["body"] or ""
    if source_body is None:
        source_body = body
    edited = body != (source_body or "") or data != (source_data or {})
    return {
        "id": row["id"],
        "ord": row["ord"],
        "key": row["key"],
        "title": row["title"],
        "body": body,
        "data": data,
        "sourceBody": source_body or "",
        "sourceData": source_data or {},
        "editedFromSource": edited,
        "placeholder": row["placeholder"],
        "hint": row["hint"],
        "provenance": row["provenance"],
        "editable": bool(row["editable"]),
        "aiDraft": row["ai_draft"],
        "aiData": _json(row["ai_data_json"], {}),
        "aiAssisted": bool(row["ai_assisted"]),
        "aiProvider": row["ai_provider"],
        "aiTimestamp": row["ai_timestamp"],
    }


def _footer_text(note: dict[str, Any], sources: list[dict[str, Any]]) -> str:
    source = note.get("source") or {}
    subject = _clean(note.get("subject") or "Subject")
    page = source.get("page")
    bits = [f"{subject} Design p.{page}" if page else f"{subject} Design"]
    appendix_page = _page_from_text(source.get("appendixSource"))
    if appendix_page:
        bits.append(f"Appendix p.{appendix_page}")
    rubric_page = None
    for row in source.get("rubric") or []:
        if isinstance(row, dict):
            rubric_page = row.get("page") or row.get("pageNumber")
            if rubric_page:
                break
        if isinstance(row, dict) and row.get("source"):
            rubric_page = _page_from_text(row.get("source"))
            if rubric_page:
                break
    if not rubric_page:
        rubric_page = _page_from_text((note.get("assessment") or {}).get("planned"))
    line = "Source: " + ", ".join(bits)
    if rubric_page:
        line += f", Rubric p.{rubric_page}"
    if note.get("aiEnriched"):
        date = str(note.get("aiTimestamp") or note.get("createdAt") or "")[:10]
        line += f" | AI-enriched on {date} with Gemini"
    web_urls = [s.get("url") for s in sources if s.get("kind") == "web" and s.get("url")]
    if web_urls:
        line += " | Web examples: " + ", ".join(dict.fromkeys(web_urls))
    teacher = [
        s.get("title") or s.get("url") or (s.get("text") or "")[:60]
        for s in sources
        if s.get("kind") == "teacher"
    ]
    teacher = [t for t in teacher if t]
    if teacher:
        line += " | Teacher source: " + ", ".join(dict.fromkeys(teacher))
    return line


def get_lesson_note(note_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM lesson_notes WHERE id = ?", (note_id,)).fetchone()
        if row is None:
            return None
        section_rows = conn.execute(
            "SELECT * FROM lesson_note_sections WHERE note_id = ? ORDER BY ord", (note_id,)
        ).fetchall()
        version_rows = conn.execute(
            "SELECT * FROM lesson_note_versions WHERE note_id = ? ORDER BY version_number DESC",
            (note_id,),
        ).fetchall()
        source_rows = conn.execute(
            "SELECT * FROM lesson_note_sources WHERE note_id = ? ORDER BY created_at, rowid",
            (note_id,),
        ).fetchall()

    source = _json(row["source_json"], {})
    template_version = effective_notes_template(
        row["template_version"] if "template_version" in row.keys() else None,
        row["grade"],
    )
    template = load_notes_template(template_version, row["grade"])
    sources = [
        {
            "id": s["id"],
            "kind": s["kind"],
            "title": s["title"],
            "url": s["url"],
            "text": s["text"],
            "createdAt": s["created_at"],
        }
        for s in source_rows
    ]
    note = {
        "id": row["id"],
        "lessonPlanId": row["lesson_plan_id"],
        "schemeId": row["plan_id"],
        "planId": row["plan_id"],
        "schemeRowId": row["section_id"],
        "sectionId": row["section_id"],
        "chunkId": row["chunk_id"],
        "documentId": row["document_id"],
        "week": row["week"],
        "lesson": row["lesson"],
        "lessonCount": row["lesson_count"],
        "strand": row["strand"],
        "subStrand": row["sub_strand"],
        "subStrandCode": row["sub_strand_code"],
        "focus": row["focus"],
        "focusKeyword": row["focus_keyword"],
        "title": row["title"],
        "grade": row["grade"],
        "subject": row["subject"],
        "term": row["term"],
        "status": row["status"],
        "templateVersion": template_version,
        "templateName": template.get("name"),
        "gradeBand": template.get("gradeBand"),
        "typeLabel": template.get("title", "LESSON NOTES"),
        "sloHeading": template.get("sloHeading") or SLO_HEADING,
        "practiceCount": template.get("practiceCount"),
        "picturePlaceholders": bool(template.get("picturePlaceholders")),
        "source": source,
        "sources": sources,
        "aiEnriched": bool(row["ai_enriched"]),
        "aiProvider": row["ai_provider"],
        "aiTimestamp": row["ai_timestamp"],
        "ai": ai_service.ai_status(),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "versions": [
            {
                "id": v["id"],
                "versionNumber": v["version_number"],
                "label": v["label"] or f"v{v['version_number']}",
                "comment": v["comment"],
                "kind": v["kind"],
                "createdAt": v["created_at"],
            }
            for v in version_rows
        ],
    }
    sections = [_section_dict(s, source) for s in section_rows]
    footer = _footer_text(note, sources)
    for section in sections:
        if section["key"] == "footer":
            section["body"] = footer
            section["sourceBody"] = footer
            section["editedFromSource"] = False
        if section["key"] == "whatIs":
            label = focus_label(
                {
                    "focus": note["focus"],
                    "focus_keyword": note["focusKeyword"],
                    "kind": "atomic",
                }
            )
            section["title"] = f"What is {label}?"
    note["footer"] = footer
    note["sections"] = sections
    return note


def list_lesson_notes(
    plan_id: str | None = None, section_id: str | None = None
) -> dict[str, Any]:
    where = []
    params: list[Any] = []
    if plan_id:
        where.append("n.plan_id = ?")
        params.append(plan_id)
    if section_id:
        where.append("n.section_id = ?")
        params.append(section_id)
    where.append("pd.owner_id = ?")
    params.append(current_owner_id())
    clause = f"WHERE {' AND '.join(where)}"
    with connect() as conn:
        rows = conn.execute(
            f"""SELECT n.*, pd.title AS plan_title, pd.grade AS plan_grade,
                       pd.subject AS plan_subject, pd.term AS plan_term
                FROM lesson_notes n
                JOIN plan_documents pd ON pd.id = n.plan_id
                {clause}
                ORDER BY n.plan_id, n.week, n.lesson""",
            tuple(params),
        ).fetchall()
    notes = [
        {
            "id": r["id"],
            "lessonPlanId": r["lesson_plan_id"],
            "planId": r["plan_id"],
            "planTitle": r["plan_title"],
            "grade": r["plan_grade"],
            "subject": r["plan_subject"],
            "term": r["plan_term"],
            "sectionId": r["section_id"],
            "week": r["week"],
            "lesson": r["lesson"],
            "lessonCount": r["lesson_count"],
            "strand": r["strand"],
            "subStrand": r["sub_strand"],
            "subStrandCode": r["sub_strand_code"],
            "focus": r["focus"],
            "focusKeyword": r["focus_keyword"],
            "title": r["title"],
            "status": r["status"],
            "aiEnriched": bool(r["ai_enriched"]),
            "templateVersion": r["template_version"],
            "createdAt": r["created_at"],
            "updatedAt": r["updated_at"],
        }
        for r in rows
    ]
    schemes: dict[str, dict[str, Any]] = {}
    for n in notes:
        scheme = schemes.setdefault(
            n["planId"],
            {
                "planId": n["planId"],
                "planTitle": n["planTitle"],
                "grade": n["grade"],
                "subject": n["subject"],
                "term": n["term"],
                "weeks": {},
            },
        )
        week = scheme["weeks"].setdefault(
            n["week"], {"week": n["week"], "lessons": []}
        )
        week["lessons"].append(
            {
                "id": n["id"],
                "lesson": n["lesson"],
                "lessonCount": n["lessonCount"],
                "title": n["title"],
                "focus": n["focus"],
                "status": n["status"],
                "aiEnriched": n["aiEnriched"],
                "subStrand": n["subStrand"],
                "subStrandCode": n["subStrandCode"],
            }
        )
    for scheme in schemes.values():
        scheme["weeks"] = [
            scheme["weeks"][k] for k in sorted(scheme["weeks"].keys())
        ]
    return {
        "notes": notes,
        "schemes": list(schemes.values()),
        "count": len(notes),
    }


def notes_picker(section_id: str) -> tuple[dict[str, Any] | None, list[str]]:
    with connect() as conn:
        section = conn.execute(
            "SELECT * FROM plan_sections WHERE id = ?", (section_id,)
        ).fetchone()
        if section is None:
            return None, ["Scheme row not found."]
        plan = conn.execute(
            "SELECT * FROM plan_documents WHERE id = ?", (section["plan_id"],)
        ).fetchone()
        cit = _chunk_for_section(conn, section["plan_id"], section_id)
        existing_rows = conn.execute(
            "SELECT id, lesson, status, title FROM lesson_notes WHERE section_id = ? ORDER BY lesson",
            (section_id,),
        ).fetchall()
    count = _section_lesson_count(section)
    decomposition = decomposition_for_section(section)
    assignments = decomposition.get("assignments") or []
    by_lesson = {int(r["lesson"]): r for r in existing_rows}
    lessons = []
    for n in range(1, count + 1):
        assignment = assignments[n - 1] if 0 <= n - 1 < len(assignments) else {}
        existing = by_lesson.get(n)
        lessons.append(
            {
                "lesson": n,
                "focus": assignment.get("focus") or f"Lesson {n}",
                "title": existing["title"] if existing else notes_title(section["sub_strand"], assignment),
                "kind": assignment.get("kind") or "atomic",
                "created": existing is not None,
                "noteId": existing["id"] if existing else None,
                "status": existing["status"] if existing else None,
            }
        )
    vetted = _chunk_vetting(cit["chunk_id"] if cit else None) == VETTED
    template_version = effective_notes_template(None, plan["grade"] if plan else "")
    template = load_notes_template(template_version, plan["grade"] if plan else "")
    return {
        "sectionId": section_id,
        "planId": section["plan_id"],
        "week": section["week_start"],
        "strand": section["strand"],
        "subStrand": section["sub_strand"],
        "subStrandCode": section["sub_strand_code"],
        "lessonCount": count,
        "lessonRange": f"1-{count}",
        "sourceVetted": vetted,
        "vettingMessage": None if vetted else VETTING_MESSAGE,
        "createdCount": sum(1 for item in lessons if item["created"]),
        "lessons": lessons,
        "decomposition": decomposition,
        "templateVersion": template_version,
        "gradeBand": template.get("gradeBand"),
        "practiceCount": template.get("practiceCount"),
    }, []


# ---------------------------------------------------------------------------
# Edits and resets
# ---------------------------------------------------------------------------


def _next_note_version(conn: Any, note_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(version_number), 0) n FROM lesson_note_versions WHERE note_id = ?",
        (note_id,),
    ).fetchone()
    return int(row["n"] or 0) + 1


def _merge_items(existing: list[Any], incoming: list[Any]) -> list[Any]:
    out = list(existing)
    seen = {json.dumps(x, sort_keys=True, ensure_ascii=False) for x in out}
    for item in incoming:
        key = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _accept_section(conn: Any, note_id: str, section: Any) -> None:
    key = section["key"]
    data = _json(section["data_json"], {})
    ai_data = _json(section["ai_data_json"], {})
    body = section["body"] or ""
    if key in ("vocabulary", "examples", "practice"):
        incoming = ai_data.get("items") or []
        data = {**data, "items": _merge_items(data.get("items") or [], incoming)}
    elif key == "workedExample":
        data = {**data, "steps": ai_data.get("steps") or []}
    elif key in ("whatIs", "remember"):
        body = section["ai_draft"] or body
    elif key == "slo":
        body = section["ai_draft"] or body
    conn.execute(
        """UPDATE lesson_note_sections
           SET body = ?, data_json = ?, provenance = 'ai', ai_assisted = 1,
               ai_provider = ?, ai_timestamp = ?, ai_draft = NULL, ai_data_json = '{}'
           WHERE id = ?""",
        (
            body,
            json.dumps(data, ensure_ascii=False),
            ai_service.ai_status().get("provider") or "gemini",
            _now(),
            section["id"],
        ),
    )


def edit_note_section(
    note_id: str, section_id: str, patch: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[str]]:
    with connect() as conn:
        note = conn.execute("SELECT * FROM lesson_notes WHERE id = ?", (note_id,)).fetchone()
        if note is None:
            return None, ["Lesson notes not found."]
        section = conn.execute(
            "SELECT * FROM lesson_note_sections WHERE id = ? AND note_id = ?",
            (section_id, note_id),
        ).fetchone()
        if section is None:
            return None, ["Section not found."]

        if patch.get("acceptAi"):
            if not section["ai_draft"] and _json(section["ai_data_json"], {}) == {}:
                return None, ["There is no AI draft to accept."]
            _accept_section(conn, note_id, section)
        elif patch.get("rejectAi"):
            conn.execute(
                """UPDATE lesson_note_sections
                   SET body = '', data_json = '{}', provenance = 'empty', ai_draft = NULL,
                       ai_data_json = '{}', ai_assisted = 0
                   WHERE id = ?""",
                (section["id"],),
            )
        else:
            body = section["body"] or ""
            data = _json(section["data_json"], {})
            provenance = section["provenance"] or "teacher"
            changed = False
            if "body" in patch:
                body = str(patch.get("body") or "")
                provenance = "web" if patch.get("provenance") == "web" else (
                    "teacher" if body.strip() else "empty"
                )
                changed = True
            if isinstance(patch.get("data"), dict):
                data = {**data, **patch["data"]}
                provenance = "teacher"
                changed = True
            if changed:
                conn.execute(
                    """UPDATE lesson_note_sections
                       SET body = ?, data_json = ?, provenance = ?, ai_draft = NULL,
                           ai_data_json = '{}'
                       WHERE id = ?""",
                    (body, json.dumps(data, ensure_ascii=False), provenance, section["id"]),
                )
                if section["key"] == "title" and body.strip():
                    conn.execute(
                        "UPDATE lesson_notes SET title = ?, updated_at = ? WHERE id = ?",
                        (body.strip(), _now(), note_id),
                    )
        conn.execute("UPDATE lesson_notes SET updated_at = ? WHERE id = ?", (_now(), note_id))
    return get_lesson_note(note_id), []


def reset_note_section(
    note_id: str, section_id: str
) -> tuple[dict[str, Any] | None, list[str]]:
    with connect() as conn:
        note = conn.execute("SELECT * FROM lesson_notes WHERE id = ?", (note_id,)).fetchone()
        if note is None:
            return None, ["Lesson notes not found."]
        section = conn.execute(
            "SELECT * FROM lesson_note_sections WHERE id = ? AND note_id = ?",
            (section_id, note_id),
        ).fetchone()
        if section is None:
            return None, ["Section not found."]
        body = section["source_body"] or ""
        data = _json(section["source_data_json"], {})
        conn.execute(
            """UPDATE lesson_note_sections
               SET body = ?, data_json = ?, provenance = 'source', ai_draft = NULL,
                   ai_data_json = '{}', ai_assisted = 0
               WHERE id = ?""",
            (body, json.dumps(data, ensure_ascii=False), section["id"]),
        )
        if section["key"] == "title" and body.strip():
            conn.execute(
                "UPDATE lesson_notes SET title = ?, updated_at = ? WHERE id = ?",
                (body.strip(), _now(), note_id),
            )
        conn.execute("UPDATE lesson_notes SET updated_at = ? WHERE id = ?", (_now(), note_id))
    return get_lesson_note(note_id), []


def edit_note_header(
    note_id: str, patch: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[str]]:
    with connect() as conn:
        note = conn.execute("SELECT * FROM lesson_notes WHERE id = ?", (note_id,)).fetchone()
        if note is None:
            return None, ["Lesson notes not found."]
        title = str(patch.get("title") or note["title"]).strip() or note["title"]
        focus = str(patch.get("focus") or note["focus"] or "")
        conn.execute(
            "UPDATE lesson_notes SET title = ?, focus = ?, updated_at = ? WHERE id = ?",
            (title, focus, _now(), note_id),
        )
        section = conn.execute(
            "SELECT * FROM lesson_note_sections WHERE note_id = ? AND key = 'title'",
            (note_id,),
        ).fetchone()
        if section is not None:
            data = _json(section["data_json"], {})
            data["focus"] = focus
            data["subject"] = note["subject"]
            conn.execute(
                "UPDATE lesson_note_sections SET body = ?, data_json = ? WHERE id = ?",
                (title, json.dumps(data, ensure_ascii=False), section["id"]),
            )
    return get_lesson_note(note_id), []


def set_note_status(
    note_id: str, status: str
) -> tuple[dict[str, Any] | None, list[str]]:
    if status not in STATUSES:
        return None, [f"Unknown status '{status}'."]
    with connect() as conn:
        note = conn.execute("SELECT id FROM lesson_notes WHERE id = ?", (note_id,)).fetchone()
        if note is None:
            return None, ["Lesson notes not found."]
        conn.execute(
            "UPDATE lesson_notes SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now(), note_id),
        )
    if status == "Final":
        create_note_version(note_id, "Marked Final", kind="final", label="Final")
    return get_lesson_note(note_id), []


# ---------------------------------------------------------------------------
# AI enrichment - teacher-initiated only
# ---------------------------------------------------------------------------


def ai_draft_note(note_id: str) -> tuple[dict[str, Any] | None, list[str]]:
    note = get_lesson_note(note_id)
    if note is None:
        return None, ["Lesson notes not found."]
    if not ai_service.ai_status()["available"]:
        return None, [AI_MESSAGE]
    source = note.get("source") or {}
    context = {
        "focus": note.get("focus"),
        "subStrand": note.get("subStrand"),
        "outcomes": source.get("outcomes"),
        "experiences": [note.get("focus")] + (source.get("experiences") or []),
        "kiq": (source.get("kiqs") or [""])[0],
        "resources": source.get("resources"),
        "rubric": source.get("rubric"),
        "grade": note.get("grade"),
        "duration": source.get("duration") or 35,
    }
    try:
        draft = notes_enrich.draft_notes(context)
    except ai_service.AIUnavailable as e:
        return None, [str(e)]
    except ai_service.AIError as e:
        return None, [str(e)]

    mappings = {
        "vocabulary": {
            "text": "\n".join(
                f"{v['word']}: {v['definition']} ({v['example']})"
                for v in draft["vocabulary"]
            ),
            "data": {"items": draft["vocabulary"]},
        },
        "whatIs": {
            "text": draft["whatIs"],
            "data": {"paragraphs": [p for p in draft["whatIs"].split("\n\n") if p.strip()]},
        },
        "examples": {
            "text": "\n".join(draft["examples"]),
            "data": {
                "items": [
                    {"text": text, "source": "AI"} for text in draft["examples"]
                ]
            },
        },
        "workedExample": {
            "text": "\n".join(
                f"{i + 1}. {step}" for i, step in enumerate(draft["workedExample"]["steps"])
            ),
            "data": {"steps": draft["workedExample"]["steps"]},
        },
        "practice": {
            "text": "\n".join(
                f"Q: {p['question']}\nA: {p['answer']}" for p in draft["practice"]
            ),
            "data": {"items": draft["practice"]},
        },
        "remember": {"text": draft["remember"], "data": {}},
    }
    with connect() as conn:
        sections = conn.execute(
            "SELECT * FROM lesson_note_sections WHERE note_id = ?", (note_id,)
        ).fetchall()
        by_key = {s["key"]: s for s in sections}
        for key, payload in mappings.items():
            section = by_key.get(key)
            if section is None:
                continue
            if not payload["text"] and not payload["data"]:
                continue
            conn.execute(
                """UPDATE lesson_note_sections SET ai_draft = ?, ai_data_json = ?,
                   ai_provider = ?, ai_timestamp = ? WHERE id = ?""",
                (
                    payload["text"],
                    json.dumps(payload["data"], ensure_ascii=False),
                    ai_service.ai_status().get("provider") or "ai",
                    _now(),
                    section["id"],
                ),
            )
        conn.execute(
            """UPDATE lesson_notes SET ai_enriched = 1, ai_provider = ?,
               ai_timestamp = ?, updated_at = ? WHERE id = ?""",
            (ai_service.ai_status().get("provider") or "ai", _now(), _now(), note_id),
        )
    return get_lesson_note(note_id), []


def ai_accept_all(note_id: str) -> tuple[dict[str, Any] | None, list[str]]:
    with connect() as conn:
        note = conn.execute("SELECT id FROM lesson_notes WHERE id = ?", (note_id,)).fetchone()
        if note is None:
            return None, ["Lesson notes not found."]
        sections = conn.execute(
            "SELECT * FROM lesson_note_sections WHERE note_id = ?", (note_id,)
        ).fetchall()
        accepted = 0
        for section in sections:
            if section["ai_draft"] or _json(section["ai_data_json"], {}) != {}:
                _accept_section(conn, note_id, section)
                accepted += 1
        conn.execute("UPDATE lesson_notes SET updated_at = ? WHERE id = ?", (_now(), note_id))
    payload = get_lesson_note(note_id)
    if payload is not None:
        payload["acceptedSections"] = accepted
    return payload, []


def search_note_examples(
    note_id: str, query: str
) -> tuple[list[dict[str, Any]], list[str]]:
    note = get_lesson_note(note_id)
    if note is None:
        return [], ["Lesson notes not found."]
    q = query or f"{note.get('focus')} Grade {note.get('grade')} activity Kenya"
    return ai_service.search_examples(
        q,
        grade=str(note.get("grade") or ""),
        focus=str(note.get("focus") or ""),
        log_key=note_id,
    )


def web_search_log(lesson_id: str) -> dict[str, Any] | None:
    """Last teacher-initiated web search log for the notes of one lesson plan or note."""
    with connect() as conn:
        row = conn.execute("SELECT id FROM lesson_notes WHERE id = ?", (lesson_id,)).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT id FROM lesson_notes WHERE lesson_plan_id = ? ORDER BY created_at DESC LIMIT 1",
                (lesson_id,),
            ).fetchone()
        if row is None:
            return None
        return ai_service.get_web_search_log(row["id"])


def add_note_source(
    note_id: str, payload: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[str]]:
    note = get_lesson_note(note_id)
    if note is None:
        return None, ["Lesson notes not found."]
    kind = str(payload.get("kind") or "teacher").strip().lower()
    if kind not in ("teacher", "web", "book", "other"):
        kind = "teacher"
    title = str(payload.get("title") or "").strip()
    url = str(payload.get("url") or "").strip()
    text = str(payload.get("text") or "").strip()
    if not (title or url or text):
        return None, ["Add a title, URL or text for your source."]
    with connect() as conn:
        conn.execute(
            """INSERT INTO lesson_note_sources (id, note_id, kind, title, url, text, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (new_id(), note_id, kind if kind != "book" else "teacher", title, url, text, _now()),
        )
        conn.execute("UPDATE lesson_notes SET updated_at = ? WHERE id = ?", (_now(), note_id))
    return get_lesson_note(note_id), []


def insert_web_example(
    note_id: str, payload: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[str]]:
    note = get_lesson_note(note_id)
    if note is None:
        return None, ["Lesson notes not found."]
    url = str(payload.get("url") or "").strip()
    title = str(payload.get("title") or "").strip()
    snippet = str(payload.get("snippet") or "").strip()
    if not url:
        return None, ["A web example needs a URL."]
    text = f"[Web Example - {url}]"
    if title:
        text += f" {title}"
    if snippet:
        text += f": {snippet}"
    with connect() as conn:
        examples = conn.execute(
            "SELECT * FROM lesson_note_sections WHERE note_id = ? AND key = 'examples'",
            (note_id,),
        ).fetchone()
        if examples is not None:
            data = _json(examples["data_json"], {})
            items = list(data.get("items") or [])
            if not any(str(x.get("url") or "") == url for x in items if isinstance(x, dict)):
                items.append({"text": text, "source": "Web", "url": url})
            data["items"] = items
            conn.execute(
                """UPDATE lesson_note_sections SET data_json = ?, provenance = 'web',
                   ai_draft = NULL, ai_data_json = '{}' WHERE id = ?""",
                (json.dumps(data, ensure_ascii=False), examples["id"]),
            )
        conn.execute(
            """INSERT INTO lesson_note_sources (id, note_id, kind, title, url, text, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (new_id(), note_id, "web", title, url, snippet, _now()),
        )
        conn.execute("UPDATE lesson_notes SET updated_at = ? WHERE id = ?", (_now(), note_id))
    return get_lesson_note(note_id), []


# ---------------------------------------------------------------------------
# Versions - append-only, restore creates a NEW version
# ---------------------------------------------------------------------------


def create_note_version(
    note_id: str,
    comment: str,
    kind: str = "version",
    label: str | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    comment = (comment or "").strip()
    if not comment:
        return None, ["A comment is required, e.g. 'Simplified the vocabulary'."]
    note = get_lesson_note(note_id)
    if note is None:
        return None, ["Lesson notes not found."]
    with connect() as conn:
        n = _next_note_version(conn, note_id)
        version_id = new_id()
        conn.execute(
            """INSERT INTO lesson_note_versions
               (id, note_id, version_number, label, comment, kind, snapshot_json, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                version_id,
                note_id,
                n,
                label or f"v{n}",
                comment,
                kind,
                json.dumps(note, ensure_ascii=False),
                _now(),
            ),
        )
        row = conn.execute(
            "SELECT * FROM lesson_note_versions WHERE id = ?", (version_id,)
        ).fetchone()
    return {
        "id": row["id"],
        "versionNumber": row["version_number"],
        "label": row["label"],
        "comment": row["comment"],
        "kind": row["kind"],
        "createdAt": row["created_at"],
    }, []


def list_note_versions(note_id: str) -> dict[str, Any]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM lesson_note_versions WHERE note_id = ? ORDER BY version_number DESC",
            (note_id,),
        ).fetchall()
    return {
        "versions": [
            {
                "id": r["id"],
                "versionNumber": r["version_number"],
                "label": r["label"] or f"v{r['version_number']}",
                "comment": r["comment"],
                "kind": r["kind"],
                "createdAt": r["created_at"],
            }
            for r in rows
        ],
        "count": len(rows),
    }


def get_note_version(note_id: str, version_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM lesson_note_versions WHERE id = ? AND note_id = ?",
            (version_id, note_id),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "versionNumber": row["version_number"],
        "label": row["label"] or f"v{row['version_number']}",
        "comment": row["comment"],
        "kind": row["kind"],
        "createdAt": row["created_at"],
        "snapshot": _json(row["snapshot_json"], {}),
    }


def _insert_sections_from_snapshot(
    conn: Any, note_id: str, sections: list[dict[str, Any]]
) -> None:
    for s in sections:
        conn.execute(
            """INSERT INTO lesson_note_sections
               (id, note_id, ord, key, title, body, data_json, source_body,
                source_data_json, placeholder, hint, provenance, editable, ai_draft,
                ai_data_json, ai_assisted, ai_provider, ai_timestamp)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                s.get("id") or new_id(),
                note_id,
                int(s.get("ord") or 0),
                s.get("key"),
                s.get("title"),
                s.get("body") or "",
                json.dumps(s.get("data") or {}, ensure_ascii=False),
                s.get("sourceBody") or "",
                json.dumps(s.get("sourceData") or {}, ensure_ascii=False),
                s.get("placeholder"),
                s.get("hint"),
                s.get("provenance") or "source",
                1 if s.get("editable", True) else 0,
                s.get("aiDraft"),
                json.dumps(s.get("aiData") or {}, ensure_ascii=False),
                1 if s.get("aiAssisted") else 0,
                s.get("aiProvider"),
                s.get("aiTimestamp"),
            ),
        )


def _apply_note_snapshot(conn: Any, note_id: str, snap: dict[str, Any]) -> None:
    conn.execute(
        """UPDATE lesson_notes SET
             title = ?, focus = ?, status = ?, template_version = ?, source_json = ?,
             ai_enriched = ?, ai_provider = ?, ai_timestamp = ?, updated_at = ?
           WHERE id = ?""",
        (
            snap.get("title"),
            snap.get("focus"),
            snap.get("status") or "Draft",
            snap.get("templateVersion"),
            json.dumps(snap.get("source") or {}, ensure_ascii=False),
            1 if snap.get("aiEnriched") else 0,
            snap.get("aiProvider"),
            snap.get("aiTimestamp"),
            _now(),
            note_id,
        ),
    )
    conn.execute("DELETE FROM lesson_note_sections WHERE note_id = ?", (note_id,))
    _insert_sections_from_snapshot(conn, note_id, snap.get("sections") or [])
    conn.execute("DELETE FROM lesson_note_sources WHERE note_id = ?", (note_id,))
    for source in snap.get("sources") or []:
        conn.execute(
            """INSERT INTO lesson_note_sources (id, note_id, kind, title, url, text, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                new_id(),
                note_id,
                source.get("kind") or "teacher",
                source.get("title"),
                source.get("url"),
                source.get("text"),
                source.get("createdAt") or _now(),
            ),
        )


def restore_note_version(
    note_id: str, version_id: str
) -> tuple[dict[str, Any] | None, list[str]]:
    version = get_note_version(note_id, version_id)
    if version is None:
        return None, ["Version not found."]
    with connect() as conn:
        note = conn.execute("SELECT id FROM lesson_notes WHERE id = ?", (note_id,)).fetchone()
        if note is None:
            return None, ["Lesson notes not found."]
        _apply_note_snapshot(conn, note_id, version["snapshot"])
    new_version, errors = create_note_version(
        note_id, f"Restored from v{version['versionNumber']}", kind="restore"
    )
    if errors:
        return None, errors
    note = get_lesson_note(note_id)
    return {**(note or {}), "restoredVersion": new_version}, []


def diff_note_version(note_id: str, version_id: str) -> dict[str, Any] | None:
    version = get_note_version(note_id, version_id)
    current = get_lesson_note(note_id)
    if version is None or current is None:
        return None
    old_sections = {s.get("key"): s for s in (version["snapshot"].get("sections") or [])}
    new_sections = {s.get("key"): s for s in (current.get("sections") or [])}
    diffs = []
    for key, old in old_sections.items():
        new = new_sections.get(key)
        frm = old.get("body") or ""
        to = (new or {}).get("body") or ""
        if frm == to:
            if (old.get("data") or {}) != ((new or {}).get("data") or {}):
                diffs.append(
                    {
                        "field": key,
                        "label": old.get("title") or key,
                        "from": json.dumps(old.get("data") or {}, ensure_ascii=False),
                        "to": json.dumps((new or {}).get("data") or {}, ensure_ascii=False),
                        "status": "changed",
                    }
                )
            continue
        status = "removed" if frm and not to else "added" if not frm and to else "changed"
        diffs.append(
            {
                "field": key,
                "label": old.get("title") or key,
                "from": frm,
                "to": to,
                "status": status,
            }
        )
    return {
        "version": {k: v for k, v in version.items() if k != "snapshot"},
        "from": version["label"],
        "to": "Current",
        "cells": diffs,
        "summary": {
            "changed": sum(1 for d in diffs if d["status"] == "changed"),
            "added": sum(1 for d in diffs if d["status"] == "added"),
            "removed": sum(1 for d in diffs if d["status"] == "removed"),
        },
    }


def delete_lesson_note(note_id: str) -> bool:
    """Delete one learner-facing lesson notes document (sections / versions / sources cascade)."""
    with connect() as conn:
        row = conn.execute("SELECT id FROM lesson_notes WHERE id = ?", (note_id,)).fetchone()
        if row is None:
            return False
        conn.execute("DELETE FROM lesson_notes WHERE id = ?", (note_id,))
    return True
