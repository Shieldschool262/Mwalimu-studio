"""Deterministic lesson decomposition (Phase 4).

NO LLM lives here. One compound curriculum experience is split into atomic skills so that
`Learners sort objects by colour, shape, size` becomes three lessons (colour, shape, size)
plus consolidation / assessment - never the same compound sentence repeated in every lesson.

The rules are deliberately conservative: if no known pattern matches, the experience is
returned as ONE atomic item. Nothing is invented and no skill is ever dropped.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

BULLET_CHARS = ("●", "•", "▪", "·", "\uf0b7", "\u25cf")

LEARNER_PREFIX = re.compile(
    r"^(?:the\s+learner\s+(?:is\s+guided\s+to|should\s+be\s+able\s+to)|learners?|pupils?|mwanafunzi)\s*:?\s*",
    re.I,
)
PAIR_PREFIX = re.compile(
    r"^(?:in\s+(?:pairs?|groups?)(?:\s*(?:/|or|and)\s*(?:pairs?|groups?))?"
    r"|in\s+pairs/groups|kwa\s+wawili|kwa\s+vikundi)\s*,?\s*",
    re.I,
)
TRAILING = re.compile(r"[\s,;:.]+$")

CONSOLIDATION_PREFIX = "Consolidation / Practice"
ASSESSMENT_PREFIX = "Assessment / Revision"


def normalise(text: str) -> str:
    s = str(text or "")
    for ch in BULLET_CHARS:
        s = s.replace(ch, " ")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^[-–—]\s+", "", s)
    s = LEARNER_PREFIX.sub("", s)
    s = PAIR_PREFIX.sub("", s)
    s = TRAILING.sub("", s)
    return s.strip()


def _split_list(raw: str) -> list[str]:
    """Split 'colour, shape and size' -> [colour, shape, size]."""
    s = re.sub(r"\s+", " ", raw).strip().rstrip(".,;:")
    if not s:
        return []
    # Never split comparison phrases such as "size from smallest to biggest and from
    # biggest to smallest" - that is one criterion, not two.
    if " from " in s.lower():
        return [s]
    parts = re.split(r"\s*(?:,|\band\b|\bor\b)\s*", s)
    out = []
    for p in parts:
        p = p.strip(" .,;:")
        if p:
            out.append(p)
    return out


def _title(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return text
    return text[0].upper() + text[1:]


def _verb_focus(text: str) -> str:
    words = re.findall(r"[A-Za-z]+", text)
    return words[0].lower() if words else ""


def _clean_pre(pre: str) -> str:
    pre = re.sub(
        r"\s+(?:according\s+to(?:\s+(?:the\s+following\s+)?attributes?)?|"
        r"with\s+similar\s+attributes?|"
        r"on\s+the\s+basis\s+of|"
        r"such\s+as|by)\s*$",
        "",
        pre.strip(),
        flags=re.I,
    )
    return pre.strip(" ,;:.")


def _attribute_atoms(text: str) -> list[dict[str, Any]]:
    """'sort objects by colour, shape, size' -> three atomic skills.

    Also handles the common design phrasing
    'group objects according to attributes such as size, colour, shape and texture'.
    """
    # Prefer the most specific connector. 'according to attributes such as ...' must use
    # 'such as', not the earlier 'according to'.
    matches: list[re.Match[str]] = []
    for pattern in (r"\bsuch\s+as\b", r"\bby\b", r"\baccording\s+to\b"):
        found = list(re.finditer(pattern + r"\s+(.+)$", text, re.I))
        if found:
            matches = [found[-1]]
            break
    if not matches:
        return []
    m = matches[0]
    raw_list = m.group(1).strip()
    # 'count by 1's and 2's up to 20' is not an attribute list.
    if re.match(r"^[0-9]", raw_list) or " up to " in raw_list.lower():
        return []
    items = _split_list(raw_list)
    if len(items) < 2:
        return []
    # An 'and' inside a single noun phrase is not a list of attributes.
    if any(len(i.split()) > 4 for i in items):
        return []
    pre = _clean_pre(text[: m.start()])
    if not pre:
        pre = text[: m.start()].strip()
    # Drop a dangling 'with ... attributes' left over from the source phrasing.
    pre = re.sub(r"\s+with\s+similar\s+attributes?$", "", pre, flags=re.I).strip()
    if not pre:
        return []
    atoms: list[dict[str, Any]] = []
    for item in items:
        focus = item.strip().lower()
        phrase = f"{pre} by {item}".strip()
        atoms.append(
            {
                "text": normalise(phrase),
                "focus_keyword": focus,
                "source": text,
                "pattern": "attribute_list",
            }
        )
    return atoms if len(atoms) >= 2 else []


_VERB = r"[A-Za-z][A-Za-z-]{1,20}"
_VERB_LIST = re.compile(
    rf"^(?P<verbs>{_VERB}(?:\s*,\s*{_VERB})+(?:\s*,?\s*(?:and|or)\s+{_VERB})?)\s+(?P<rest>.+)$"
)
_TWO_VERBS = re.compile(rf"^(?P<v1>{_VERB})\s+(?:and|or)\s+(?P<v2>{_VERB})\s+(?P<rest>.+)$")


def _verb_atoms(text: str) -> list[dict[str, Any]]:
    """'sort, group and match objects' / 'identify, name and write numbers 1-5'."""
    m = _VERB_LIST.match(text)
    verbs: list[str] = []
    rest = ""
    if m:
        verbs = [
            v.strip()
            for v in re.split(r"\s*(?:,|\band\b|\bor\b)\s*", m.group("verbs"))
            if v.strip()
        ]
        rest = m.group("rest").strip()
    else:
        two = _TWO_VERBS.match(text)
        if two:
            verbs = [two.group("v1"), two.group("v2")]
            rest = two.group("rest").strip()
    if len(verbs) < 2:
        return []
    # Guard against splitting ordinary prose: the object must follow immediately and the
    # verbs must be plausible action words (no articles / conjunctions).
    if any(v.lower() in {"the", "a", "an", "in", "on", "of", "to", "with", "by"} for v in verbs):
        return []
    if not rest:
        return []
    atoms = []
    for verb in verbs:
        phrase = f"{verb} {rest}"
        atoms.append(
            {
                "text": normalise(phrase),
                "focus_keyword": verb.lower(),
                "source": text,
                "pattern": "verb_list",
            }
        )
    return atoms


_OF_DIFFERENT = re.compile(
    r"^(?P<pre>.*?)\bof\s+different\s+(?P<list>[A-Za-z ]+(?:,\s*[A-Za-z ]+)*(?:\s+and\s+[A-Za-z ]+)?)$",
    re.I,
)


def _of_different_atoms(text: str) -> list[dict[str, Any]]:
    suffix = ""
    body = text
    m_using = re.search(r"\s+using\b.*$", text, re.I)
    if m_using:
        body = text[: m_using.start()].strip()
        suffix = text[m_using.start() :].strip()
    m = _OF_DIFFERENT.match(body)
    if not m:
        return []
    items = _split_list(m.group("list"))
    if len(items) < 2:
        return []
    pre = m.group("pre").strip()
    atoms = []
    for item in items:
        phrase = f"{pre} of different {item}"
        if suffix:
            phrase = f"{phrase} {suffix}"
        atoms.append(
            {
                "text": normalise(phrase),
                "focus_keyword": item.strip().lower(),
                "source": text,
                "pattern": "of_different",
            }
        )
    return atoms


def decompose_experience(text: str) -> list[dict[str, Any]]:
    """Split ONE curriculum experience into atomic skills.

    Returns a single-item list when no known pattern matches - a compound sentence is never
    force-split.
    """
    cleaned = normalise(text)
    if not cleaned:
        return []
    atoms: list[dict[str, Any]] = []
    for detector in (_attribute_atoms, _verb_atoms, _of_different_atoms):
        atoms = detector(cleaned)
        if atoms:
            break
    if not atoms:
        atoms = [
            {
                "text": cleaned,
                "focus_keyword": _verb_focus(cleaned),
                "source": str(text or ""),
                "pattern": "single",
            }
        ]
    # `focus` is the short label callers show in previews; keyword stays the matcher.
    for atom in atoms:
        atom.setdefault("focus", atom.get("focus_keyword") or "")
    return atoms


def decompose_experiences(texts: Iterable[str]) -> list[dict[str, Any]]:
    """Decompose a whole list, preserving source order and removing exact duplicates."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for text in texts:
        for atom in decompose_experience(text):
            key = atom["text"].lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(atom)
    return out


def _join_focuses(focuses: list[str]) -> str:
    clean = [f for f in focuses if f]
    if not clean:
        return ""
    if len(clean) == 1:
        return clean[0]
    if len(clean) == 2:
        return f"{clean[0]} and {clean[1]}"
    return f"{', '.join(clean[:-1])} and {clean[-1]}"


def _join_atoms(atoms: list[dict[str, Any]]) -> str:
    """'sort objects by colour, shape and size' instead of repeating the whole phrase."""
    texts = [str(a.get("text") or "") for a in atoms if a.get("text")]
    if not texts:
        return ""
    if all(" by " in t for t in texts):
        prefixes = {t.split(" by ", 1)[0] for t in texts}
        if len(prefixes) == 1:
            prefix = prefixes.pop()
            attrs = [t.split(" by ", 1)[1] for t in texts]
            return _title(f"{prefix} by {_join_focuses(attrs)}")
    return _join_focuses([_title(t) for t in texts])


def assign_lessons(
    atoms: list[dict[str, Any]],
    lesson_count: int,
    source_quote: str = "",
) -> dict[str, Any]:
    """Assign atomic skills to N lessons, padding with consolidation / assessment.

    * atomic == lessons -> one skill per lesson.
    * atomic  < lessons -> last lesson is assessment / revision, the lessons between are
      consolidation / practice of the skills already met.
    * atomic  > lessons -> every skill is kept; the overflow is returned as `spill` with a
      warning. Nothing is dropped.
    """
    lesson_count = max(1, int(lesson_count or 1))
    atoms = [a for a in atoms if (a.get("text") or "").strip()]

    if len(atoms) > lesson_count:
        shown = atoms[:lesson_count]
        spill = atoms[lesson_count:]
        assignments = [
            {
                "lesson": i + 1,
                "kind": "atomic",
                "focus": _title(a["text"]),
                "focus_keyword": a.get("focus_keyword") or "",
                "atomic": a,
                "source_quote": a.get("source") or source_quote,
            }
            for i, a in enumerate(shown)
        ]
        warning = (
            f"This sub-strand has {len(atoms)} atomic skills but only {lesson_count} lessons. "
            f"{len(spill)} will spill to next week. Extend lessons or split sub-strand?"
        )
        return {
            "assignments": assignments,
            "atoms": atoms,
            "atomicCount": len(atoms),
            "lessonCount": lesson_count,
            "warning": warning,
            "warnings": [warning],
            "spill": spill,
            "extendTo": len(atoms),
        }

    atomic_focuses = [_title(a["text"]) for a in atoms]
    combined = _join_atoms(atoms)
    assignments: list[dict[str, Any]] = []
    for i in range(lesson_count):
        if i < len(atoms):
            a = atoms[i]
            assignments.append(
                {
                    "lesson": i + 1,
                    "kind": "atomic",
                    "focus": _title(a["text"]),
                    "focus_keyword": a.get("focus_keyword") or "",
                    "atomic": a,
                    "source_quote": a.get("source") or source_quote,
                }
            )
            continue
        if i == lesson_count - 1:
            text = f"{ASSESSMENT_PREFIX}: {combined}".strip()
            assignments.append(
                {
                    "lesson": i + 1,
                    "kind": "assessment",
                    "focus": text,
                    "focus_keyword": "assessment",
                    "atomic": None,
                    "source_quote": source_quote,
                }
            )
        else:
            # Consolidate the skills already introduced, in source order.
            prev_atoms = atoms[:i]
            if len(prev_atoms) > 3:
                prev_atoms = prev_atoms[:2] + [prev_atoms[-1]]
            focuses = _join_atoms(prev_atoms) or combined or _join_focuses(atomic_focuses)
            text = f"{CONSOLIDATION_PREFIX}: {focuses}".strip()
            assignments.append(
                {
                    "lesson": i + 1,
                    "kind": "consolidation",
                    "focus": text,
                    "focus_keyword": "consolidation",
                    "atomic": None,
                    "source_quote": source_quote,
                }
            )
    return {
        "assignments": assignments,
        "atoms": atoms,
        "atomicCount": len(atoms),
        "lessonCount": lesson_count,
        "warning": None,
        "warnings": [],
        "spill": [],
        "extendTo": None,
    }


def decompose_for_row(experiences: list[str], lesson_count: int) -> dict[str, Any]:
    atoms = decompose_experiences(experiences or [])
    quote = " ".join(str(e) for e in (experiences or []) if str(e).strip())
    result = assign_lessons(atoms, lesson_count, source_quote=quote)
    result["preview"] = preview_labels(result)
    return result


def preview_labels(result: dict[str, Any]) -> list[str]:
    """['L1 colour', 'L2 shape', ..., 'L4 consolidation', 'L5 assessment']."""
    out = []
    for a in result.get("assignments") or []:
        if a["kind"] == "atomic":
            label = a.get("focus_keyword") or a["focus"]
        elif a["kind"] == "consolidation":
            label = "consolidation"
        else:
            label = "assessment"
        out.append(f"L{a['lesson']} {label}")
    return out


def focus_outcome(outcomes: list[str], assignment: dict[str, Any] | None) -> str:
    """The FOCUS outcome for one lesson (full outcomes stay in the side panel)."""
    if not outcomes:
        return ""
    keyword = ((assignment or {}).get("focus_keyword") or "").lower()
    chosen = outcomes[0]
    if keyword:
        for o in outcomes:
            if keyword in str(o).lower():
                chosen = o
                break
    raw = str(chosen).strip()
    # The Outcomes section is copied verbatim; the lesson-specific atomic focus is shown in
    # the header (e.g. "Group objects by colour") and must never rewrite the source outcome.
    return raw


def preview_for_ui(experiences: list[str], lesson_count: int) -> dict[str, Any]:
    """Compact payload for the scheme hover preview."""
    result = decompose_for_row(experiences, lesson_count)
    return {
        "atoms": result["atoms"],
        "assignments": result["assignments"],
        "preview": result["preview"],
        "atomicCount": result["atomicCount"],
        "lessonCount": result["lessonCount"],
        "warning": result["warning"],
        "warnings": result["warnings"],
        "spill": [a.get("text") for a in result.get("spill") or []],
        "extendTo": result.get("extendTo"),
    }
