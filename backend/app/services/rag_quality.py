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
_LATEX_GREEK_SYMBOLS = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "varepsilon": "ϵ", "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "ϑ",
    "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ",
    "omicron": "ο", "pi": "π", "varpi": "ϖ", "rho": "ρ", "varrho": "ϱ",
    "sigma": "σ", "varsigma": "ς", "tau": "τ", "upsilon": "υ", "phi": "φ",
    "varphi": "ϕ", "chi": "χ", "psi": "ψ", "omega": "ω",
}
_GREEK_SYMBOL_CLASS = "".join(_GREEK_SYMBOL_NAMES)
_GREEK_SYMBOL_RE = re.compile("|".join(map(re.escape, _GREEK_SYMBOL_NAMES)))
_LATEX_GREEK_RE = re.compile(
    r"\\(" + "|".join(sorted(map(re.escape, _LATEX_GREEK_SYMBOLS), key=len, reverse=True)) + r")\b"
)
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


def _read_latex_group(text: str, position: int, opening: str, closing: str) -> tuple[str, int] | None:
    while position < len(text) and text[position].isspace():
        position += 1
    if position >= len(text) or text[position] != opening:
        return None
    depth = 0
    index = position
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == opening:
            depth += 1
        elif text[index] == closing:
            depth -= 1
            if depth == 0:
                return text[position + 1:index], index + 1
        index += 1
    return None


def _has_top_level_operator(expression: str, operators: str) -> bool:
    depth = 0
    previous = ""
    for character in expression:
        if character == "(":
            depth += 1
        elif character == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and character in operators:
            if character in "+-" and (not previous or previous in "+-*/^=<>≤≥≠≈"):
                previous = character
                continue
            return True
        if not character.isspace():
            previous = character
    return False


def _format_latex_fraction(numerator: str, denominator: str) -> str:
    numerator = numerator.strip()
    denominator = denominator.strip()
    if _has_top_level_operator(numerator, "+-"):
        numerator = f"({numerator})"
    if _has_top_level_operator(denominator, "+-*/"):
        denominator = f"({denominator})"
    return f"{numerator}/{denominator}"


def _normalize_latex_commands(value: str, depth: int = 0) -> str:
    """Lower common LaTeX fractions, roots, and braced exponents to formula syntax."""
    if depth >= 16:
        return value
    result = []
    index = 0
    while index < len(value):
        command_match = re.match(r"\\([a-z]+)", value[index:]) if value[index] == "\\" else None
        if command_match:
            command = command_match.group(1)
            command_end = index + len(command_match.group(0))
            if command in {"frac", "dfrac", "tfrac"}:
                numerator_group = _read_latex_group(value, command_end, "{", "}")
                denominator_group = (
                    _read_latex_group(value, numerator_group[1], "{", "}")
                    if numerator_group else None
                )
                if numerator_group and denominator_group:
                    numerator = _normalize_latex_commands(numerator_group[0], depth + 1)
                    denominator = _normalize_latex_commands(denominator_group[0], depth + 1)
                    result.append(_format_latex_fraction(numerator, denominator))
                    index = denominator_group[1]
                    continue
            elif command == "sqrt":
                radicand_group = _read_latex_group(value, command_end, "{", "}")
                if radicand_group:
                    radicand = _normalize_latex_commands(radicand_group[0], depth + 1).strip()
                    result.append(f"sqrt({radicand})")
                    index = radicand_group[1]
                    continue
            result.append(command_match.group(0))
            index = command_end
            continue

        if value[index] == "√":
            start = index + 1
            while start < len(value) and value[start].isspace():
                start += 1
            group = _read_latex_group(value, start, "(", ")")
            if group:
                radicand = _normalize_latex_commands(group[0], depth + 1).strip()
                result.append(f"sqrt({radicand})")
                index = group[1]
                continue
            variable = re.match(r"[a-z][a-z0-9_]*|\d+(?:\.\d+)?", value[start:])
            if variable:
                result.append(f"sqrt({variable.group(0)})")
                index = start + len(variable.group(0))
                continue
            result.append(value[index])
            index += 1
            continue

        if value[index] == "^":
            exponent_group = _read_latex_group(value, index + 1, "{", "}")
            if exponent_group:
                exponent = _normalize_latex_commands(exponent_group[0], depth + 1).strip()
                if re.fullmatch(r"(?:[a-z][a-z0-9_]*|\d+(?:\.\d+)?|[α-ω])", exponent):
                    result.append("^" + exponent)
                else:
                    result.append("^(" + exponent + ")")
                index = exponent_group[1]
                continue

        result.append(value[index])
        index += 1
    return "".join(result)


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
    value = _LATEX_GREEK_RE.sub(lambda match: _LATEX_GREEK_SYMBOLS[match.group(1)], value)
    for source, replacement in _FORMULA_REPLACEMENTS:
        value = re.sub(source, replacement, value) if source.startswith("\\") else value.replace(source, replacement)
    value = _normalize_latex_commands(value)
    # NFKC turns the micro sign into Greek mu; preserve common SI prefixes as `u`.
    value = _MICRO_UNIT_RE.sub("u", value)
    # Transliterate Greek variables for portable token matching. Insert explicit
    # products at symbol boundaries, but keep digits attached as subscripts.
    value = re.sub(rf"(?<=[a-z0-9_)])(?=[{_GREEK_SYMBOL_CLASS}])", "*", value)
    value = re.sub(rf"(?<=[a-z0-9_)])\s+(?=[{_GREEK_SYMBOL_CLASS}])", "*", value)
    value = re.sub(rf"(?<=[{_GREEK_SYMBOL_CLASS}])(?=[a-z(])", "*", value)
    value = re.sub(rf"(?<=[{_GREEK_SYMBOL_CLASS}])\s+(?=[a-z(])", "*", value)
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
