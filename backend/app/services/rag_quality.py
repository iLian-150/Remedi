"""Small retrieval helpers that preserve formula evidence and candidate breadth."""
import re
import unicodedata


_FORMULA_ATOM = r"(?:[a-z][a-z0-9_]*|\d+(?:\.\d+)?)"
_FORMULA_RE = re.compile(
    rf"(?<![a-z0-9_]){_FORMULA_ATOM}(?:\s*(?:[+\-*/^=<>≤≥≠≈]|×|÷|·|⋅)\s*{_FORMULA_ATOM})+(?![a-z0-9_])",
    re.IGNORECASE,
)
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

    A formula token contains its operators, so a one-letter variable can be
    useful evidence without making arbitrary single letters searchable. Pure
    arithmetic expressions are omitted unless they state an equation or
    comparison; this keeps a shared number such as ``2`` from becoming a hit.
    """
    value = unicodedata.normalize("NFKC", text or "").lower()
    for source, replacement in _FORMULA_REPLACEMENTS:
        value = re.sub(source, replacement, value) if source.startswith("\\") else value.replace(source, replacement)
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
