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
_FORMULA_OPERATOR = r"(?:[+\-*/^=<>≤≥≠≈]|×|÷|·|⋅)"
_FORMULA_VARIABLE_BEFORE_GROUP_RE = re.compile(rf"(?<![a-z0-9_])({_FORMULA_VARIABLE})\s*(?=\()")
_FORMULA_FUNCTION_NAMES = {"f", "g", "h"}
_FORMULA_VARIABLE_PAIR_RE = re.compile(r"(?<![a-z0-9_])([a-z]{2})(?![a-z0-9_])")
_FORMULA_NAMED_PAIRS = {
    "ln", "pi", "mu", "nu", "xi", "cm", "mm", "dm", "km", "nm", "pm",
    "kg", "mg", "ug", "um", "ua", "uv", "uf", "uw", "uh", "ml", "ul",
    "ms", "us", "ns", "hz", "db",
}
_MICRO_UNIT_RE = re.compile(r"μ(?=(?:mol|hz|[mglsavfwh])\b)")
_GREEK_SYMBOL_NAMES = {
    "α": "alpha", "β": "beta", "γ": "gamma", "δ": "delta", "ε": "epsilon",
    "ζ": "zeta", "η": "eta", "θ": "theta", "ι": "iota", "κ": "kappa",
    "λ": "lambda", "μ": "mu", "ν": "nu", "ξ": "xi", "ο": "omicron",
    "π": "pi", "ρ": "rho", "ς": "sigma", "σ": "sigma", "τ": "tau",
    "υ": "upsilon", "φ": "phi", "ϕ": "phi", "χ": "chi", "ψ": "psi",
    "ω": "omega", "ϵ": "epsilon", "ϑ": "theta", "ϖ": "pi", "ϱ": "rho",
}
_GREEK_SYMBOL_CLASS = "".join(_GREEK_SYMBOL_NAMES)
_GREEK_SYMBOL_RE = re.compile("|".join(map(re.escape, _GREEK_SYMBOL_NAMES)))
_FORMULA_RE = re.compile(
    rf"(?<![a-z0-9_(]){_FORMULA_TERM}(?:\s*{_FORMULA_OPERATOR}\s*{_FORMULA_TERM})+(?![a-z0-9_)])",
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
    # NFKC turns the micro sign into Greek mu; preserve common SI prefixes as `u`.
    value = _MICRO_UNIT_RE.sub("u", value)
    # Transliterate Greek variables for portable token matching. Insert explicit
    # products at symbol boundaries, but keep digits attached as subscripts.
    value = re.sub(rf"(?<=[a-z0-9_)])(?=[{_GREEK_SYMBOL_CLASS}])", "*", value)
    value = re.sub(rf"(?<=[{_GREEK_SYMBOL_CLASS}])(?=[a-z(])", "*", value)
    value = re.sub(rf"(?<=[{_GREEK_SYMBOL_CLASS}])(?=[{_GREEK_SYMBOL_CLASS}])", "*", value)
    value = _GREEK_SYMBOL_RE.sub(lambda match: _GREEK_SYMBOL_NAMES[match.group(0)], value)
    # In school algebra, a single-letter variable before a group means
    # multiplication; preserve the conventional single-letter function names.
    value = _FORMULA_VARIABLE_BEFORE_GROUP_RE.sub(
        lambda match: match.group(0)
        if len(match.group(1)) > 1 or match.group(1) in _FORMULA_FUNCTION_NAMES
        else f"{match.group(1)}*",
        value,
    )
    # A numeric coefficient immediately before a variable is implicit multiplication.
    # Normalize it before matching so the regex cannot fall through to a shared suffix
    # such as `3=7` and treat distinct equations as the same evidence.
    value = re.sub(r"(?<=\d)(?=[a-z])", "*", value)
    value = re.sub(rf"(?<=\d)\s+(?={_FORMULA_VARIABLE}\s*{_FORMULA_OPERATOR})", "*", value)
    # In school algebra, two adjacent one-letter variables mean a product.
    # Keep common named constants, functions, and units as single atoms.
    value = _FORMULA_VARIABLE_PAIR_RE.sub(
        lambda match: match.group(1)
        if match.group(1) in _FORMULA_NAMED_PAIRS
        else f"{match.group(1)[0]}*{match.group(1)[1]}",
        value,
    )
    # Parenthesized groups are formula atoms too, with implicit multiplication
    # normalized before them so `2(x+1)` remains distinct from `3(x+1)`.
    value = re.sub(r"(?<=\d)\s*(?=\()", "*", value)
    # A closing group followed by another group is multiplication. Before a
    # variable or number, require a following formula operator to avoid treating
    # ordinary prose such as `(x+1) is useful` as an equation.
    value = re.sub(r"(?<=\))\s*(?=\()", "*", value)
    value = re.sub(rf"(?<=\))\s*(?={_FORMULA_VARIABLE}\s*{_FORMULA_OPERATOR})", "*", value)
    value = re.sub(rf"(?<=\))\s*(?=\d+(?:\.\d+)?\s*{_FORMULA_OPERATOR})", "*", value)
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
