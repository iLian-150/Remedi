"""Small retrieval helpers that preserve formula evidence and candidate breadth."""
import re
import unicodedata


_FORMULA_GROUP_CHARS = r"a-z0-9_.+\-*/^=<>≤≥≠≈×÷·⋅\s"


def _formula_group_pattern(depth: int) -> str:
    """Build a bounded, balanced-parenthesis atom pattern for Python's regex engine."""
    content = rf"[{_FORMULA_GROUP_CHARS}]"
    if depth > 0:
        content = rf"(?:{content}|{_formula_group_pattern(depth - 1)})"
    return rf"\((?:{content})+\)"


_FORMULA_GROUP = _formula_group_pattern(6)
_FORMULA_VARIABLE = r"[a-z][a-z0-9_]*"
_FORMULA_ATOM = rf"(?:{_FORMULA_VARIABLE}{_FORMULA_GROUP}|{_FORMULA_VARIABLE}|\d+(?:\.\d+)?|{_FORMULA_GROUP})"
_FORMULA_TERM = rf"[+-]?\s*{_FORMULA_ATOM}"
_FORMULA_RE = re.compile(
    rf"(?<![a-z0-9_(]){_FORMULA_TERM}(?:\s*(?:[+\-*/^=<>≤≥≠≈]|×|÷|·|⋅)\s*{_FORMULA_TERM})+(?![a-z0-9_)])",
    re.IGNORECASE,
)
_SUPERSCRIPT_RE = re.compile(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+")
_SUPERSCRIPT_MAP = str.maketrans({
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
    "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
    "⁺": "+", "⁻": "-",
})
_FORMULA_REPLACEMENTS = (
    (r"\\(?:times|cdot)", "*"),
    (r"\\div", "/"),
    ("×", "*"),
    ("÷", "/"),
    ("·", "*"),
    ("⋅", "*"),
    ("−", "-"),
    ("–", "-"),
    ("≤", "<="),
    ("≥", ">="),
    ("≠", "!="),
    ("≈", "~="),
)


def formula_tokens(text: str) -> list[str]:
    """Return exact, whitespace/operator-normalized equation tokens.

    Common superscripts and Unicode fraction bars are normalized before matching.
    A formula token contains its operators, so a one-letter variable can be
    useful evidence without making arbitrary single letters searchable. Pure
    arithmetic expressions are omitted unless they state an equation or
    comparison; this keeps a shared number such as ``2`` from becoming a hit.
    """
    value = _SUPERSCRIPT_RE.sub(
        lambda match: "^" + match.group(0).translate(_SUPERSCRIPT_MAP),
        text or "",
    )
    value = unicodedata.normalize("NFKC", value).lower().replace("⁄", "/")
    for source, replacement in _FORMULA_REPLACEMENTS:
        value = re.sub(source, replacement, value) if source.startswith("\\") else value.replace(source, replacement)
    # A numeric coefficient immediately before a variable is implicit multiplication.
    # Normalize it before matching so the regex cannot fall through to a shared suffix
    # such as `3=7` and treat distinct equations as the same evidence.
    value = re.sub(r"(?<=\d)(?=[a-z])", "*", value)
    # Parenthesized groups are formula atoms too, with implicit multiplication
    # normalized before them so `2(x+1)` remains distinct from `3(x+1)`.
    value = re.sub(r"(?<=\d)\s*(?=\()", "*", value)
    found = []
    for match in _FORMULA_RE.finditer(value):
        formula = re.sub(r"\s+", "", match.group(0))
        has_variable = bool(re.search(r"[a-z]", formula))
        has_relation = any(operator in formula for operator in ("=", "<", ">", "!", "~"))
        if len(formula) <= 160 and (has_variable or has_relation):
            found.append(f"formula:{formula}")
    return list(dict.fromkeys(found))


def spread_by_document(ranked_indices: list[int], candidates: list[dict], limit: int) -> list[int]:
    """Take a ranking prefix in rounds across documents, retaining source order.

    Retrieval scores are still computed from each source's original rank by the
    caller. This helper only decides which candidates survive an early cap.
    """
    if limit <= 0:
        return []
    groups: dict[int, list[int]] = {}
    seen = set()
    for index in ranked_indices:
        if index in seen or not 0 <= index < len(candidates):
            continue
        seen.add(index)
        document_id = candidates[index].get("document_id")
        groups.setdefault(document_id, []).append(index)

    selected = []
    while groups and len(selected) < limit:
        exhausted = []
        for document_id, indices in groups.items():
            selected.append(indices.pop(0))
            if not indices:
                exhausted.append(document_id)
            if len(selected) >= limit:
                break
        for document_id in exhausted:
            groups.pop(document_id, None)
    return selected
