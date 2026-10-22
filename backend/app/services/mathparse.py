# 数学步骤解析：把学生输入的文本步骤解析为 sympy 表达式/等式。
# 学生文本经 SymPy tokenizer 转成 Python AST 后，只解释算术节点和白名单函数；
# 不调用 parse_expr/eval。解析失败抛 UnparseableError，由上层记为"无法解析"。
import ast
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional, Union

from sympy import (
    Abs, Add, E, Eq, Float, Function, I, Integer, Max, Min, Mul, Pow, Rational,
    Symbol, acos, acosh, asin, asinh, atan, atan2, atanh, ceiling, cos, cosh,
    exp, factorial, floor, im, log, nan, oo, pi, re as real_part, sign, sin,
    sinh, tan, tanh, zoo,
)
from sympy.parsing.sympy_parser import (
    implicit_multiplication_application,
    standard_transformations,
    stringify_expr,
)

TRANSFORMATIONS = standard_transformations + (implicit_multiplication_application,)

_SAFE_GLOBALS = {
    "__builtins__": {},
    "Symbol": Symbol,
    "Integer": Integer,
    "Float": Float,
    "Rational": Rational,
    "Function": Function,
    "Add": Add,
    "Mul": Mul,
    "Pow": Pow,
    "factorial": factorial,
    "Abs": Abs,
    "Max": Max,
    "Min": Min,
    "acos": acos,
    "acosh": acosh,
    "asin": asin,
    "asinh": asinh,
    "atan": atan,
    "atan2": atan2,
    "atanh": atanh,
    "ceiling": ceiling,
    "cos": cos,
    "cosh": cosh,
    "exp": exp,
    "floor": floor,
    "im": im,
    "log": log,
    "re": real_part,
    "sign": sign,
    "sin": sin,
    "sinh": sinh,
    "tan": tan,
    "tanh": tanh,
    "E": E,
    "I": I,
    "nan": nan,
    "oo": oo,
    "pi": pi,
    "zoo": zoo,
}
_SAFE_CALLS = {
    key: value for key, value in _SAFE_GLOBALS.items()
    if key not in {"__builtins__", "Function", "E", "I", "nan", "oo", "pi", "zoo"}
}
_SAFE_CONSTANTS = {
    key: _SAFE_GLOBALS[key] for key in ("E", "I", "nan", "oo", "pi", "zoo")
}


def _evaluate_math_ast(node):
    """Interpret only SymPy's arithmetic AST nodes; never execute generated code."""
    if isinstance(node, ast.Expression):
        return _evaluate_math_ast(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return node.value
        if isinstance(node.value, bool):
            raise UnparseableError("布尔值不是数学表达式")
        if isinstance(node.value, int):
            return Integer(node.value)
        if isinstance(node.value, float):
            return Float(node.value)
        raise UnparseableError("表达式包含不支持的常量")
    if isinstance(node, ast.Name):
        if node.id not in _SAFE_CONSTANTS:
            raise UnparseableError("表达式包含不支持的名称")
        return _SAFE_CONSTANTS[node.id]
    if isinstance(node, ast.UnaryOp):
        value = _evaluate_math_ast(node.operand)
        if isinstance(node.op, ast.UAdd):
            return value
        if isinstance(node.op, ast.USub):
            if isinstance(value, Integer):
                return -value
            return Mul(Integer(-1), value, evaluate=False)
        raise UnparseableError("表达式包含不支持的一元运算")
    if isinstance(node, ast.Call):
        if node.keywords:
            if (len(node.keywords) != 1 or node.keywords[0].arg != "evaluate"
                    or not isinstance(node.keywords[0].value, ast.Constant)
                    or node.keywords[0].value.value is not False):
                raise UnparseableError("表达式包含不支持的参数")
            evaluate_false = True
        else:
            evaluate_false = False

        if isinstance(node.func, ast.Name) and node.func.id == "Function":
            if evaluate_false or len(node.args) != 1:
                raise UnparseableError("函数定义格式不受支持")
            name = _evaluate_math_ast(node.args[0])
            if not isinstance(name, str):
                raise UnparseableError("函数名格式不受支持")
            return Function(name)

        if isinstance(node.func, ast.Call):
            if (not isinstance(node.func.func, ast.Name)
                    or node.func.func.id != "Function"
                    or evaluate_false):
                raise UnparseableError("表达式包含不支持的函数调用")
            function = _evaluate_math_ast(node.func)
            return function(*[_evaluate_math_ast(arg) for arg in node.args])

        if not isinstance(node.func, ast.Name):
            raise UnparseableError("表达式包含不支持的函数调用")
        function_name = node.func.id
        function = _SAFE_CALLS.get(function_name)
        if function is None:
            raise UnparseableError("表达式包含不支持的函数")
        if evaluate_false and function_name not in {"Add", "Mul", "Pow"}:
            raise UnparseableError("表达式包含不支持的参数")
        kwargs = {"evaluate": False} if evaluate_false else {}
        return function(*[_evaluate_math_ast(arg) for arg in node.args], **kwargs)
    if isinstance(node, ast.BinOp):
        left = _evaluate_math_ast(node.left)
        right = _evaluate_math_ast(node.right)
        if isinstance(node.op, ast.Add):
            return Add(left, right, evaluate=False)
        if isinstance(node.op, ast.Sub):
            return Add(left, Mul(Integer(-1), right, evaluate=False), evaluate=False)
        if isinstance(node.op, ast.Mult):
            return Mul(left, right, evaluate=False)
        if isinstance(node.op, ast.Div):
            return Mul(left, Pow(right, Integer(-1), evaluate=False), evaluate=False)
        if isinstance(node.op, ast.Pow):
            return Pow(left, right, evaluate=False)
        raise UnparseableError("表达式包含不支持的运算")
    raise UnparseableError("表达式包含不支持的语法")


def _safe_parse_expression(text: str):
    source = stringify_expr(text, {}, _SAFE_GLOBALS, TRANSFORMATIONS)
    expression = _evaluate_math_ast(ast.parse(source, mode="eval"))
    if not hasattr(expression, "free_symbols"):
        raise UnparseableError("表达式无法解析为数学形式")
    return expression

# 全角 → 半角
_FULL2HALF = str.maketrans({
    "＋": "+", "－": "-", "＊": "*", "／": "/",
    "＝": "=", "（": "(", "）": ")",
    "，": ",", "。": ".", "：": ":", "　": " ",
})
# 常见数学符号归一化（v0.13.1 补 −/√/π：做题板符号栏会插入这三个符号——
# − 是 U+2212 减号、√ 归一为 sqrt（符号栏插入的是 √( 形式）、π 归一为 pi，
# 不补的话学生点符号写出的步骤会被判「无法解析」）
_SYMBOL_MAP = {"×": "*", "÷": "/", "·": "*", "²": "**2", "³": "**3", "^": "**", "−": "-", "√": "sqrt", "π": "pi"}
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_CJK_PAREN_RE = re.compile(r"[（(][\u4e00-\u9fff][^()（）]*[)）]")  # 中文括号注释，如 （检验略）
# 步骤里允许出现的字符（归一化之后）
_ALLOWED_RE = re.compile(r"^[0-9a-zA-Z+\-*/().=_\s]+$")


class UnparseableError(Exception):
    """步骤文本无法解析为数学表达式/等式。"""


@dataclass
class ParsedStep:
    kind: str  # "expr" | "eq"
    expr: Union[object, Eq]  # sympy Basic 或 Eq
    text: str  # 归一化后的文本


def _sqrt_to_pow(t: str) -> str:
    """把 sqrt(...) 改写成 (... )**(1/2)：本解析器 evaluate=False 下直接调
    sqrt 函数会触发 SympifyError，幂形式可正常解析、与 sqrt 等价（归一化文本
    两侧同形，检测器不受影响）。括号不配平时原样返回，留给后续解析报错。"""
    while "sqrt(" in t:
        i = t.index("sqrt(")
        depth = 0
        j = i + 4  # 指向 '('
        while j < len(t):
            if t[j] == "(":
                depth += 1
            elif t[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if j >= len(t):
            break
        inner = t[i + 5:j]
        t = t[:i] + f"({inner})**(1/2)" + t[j + 1:]
    return t


def clean_text(raw: str) -> str:
    """归一化步骤文本：全角转半角、符号统一、去掉中文括号注释。"""
    t = raw.strip().translate(_FULL2HALF)
    for k, v in _SYMBOL_MAP.items():
        t = t.replace(k, v)
    t = _sqrt_to_pow(t)
    t = _CJK_PAREN_RE.sub("", t)  # 去掉 "（检验）" 这类中文注释
    # 隐式乘法显式化：2(x+1) → 2*(x+1)，保证归一化文本形态一致（检测器依赖显式 *）
    t = re.sub(r"([0-9a-zA-Z])\(", r"\1*(", t)
    t = re.sub(r"\)([0-9a-zA-Z])", r")*\1", t)
    t = re.sub(r"\)\(", r")*(", t)
    t = re.sub(r"\s+", "", t)
    return t


@lru_cache(maxsize=512)
def _parse_expression_cached(text: str):
    """Reuse immutable SymPy expressions for repeated normalized steps."""
    return _safe_parse_expression(text)


def _parse_expression(text: str):
    # Keep unusually long expressions out of the process-wide cache.
    if len(text) > 256:
        return _safe_parse_expression(text)
    return _parse_expression_cached(text)


def parse_step(raw: str) -> ParsedStep:
    """解析单个步骤。失败抛 UnparseableError。"""
    t = clean_text(raw)
    if not t:
        raise UnparseableError("步骤为空")
    if _CJK_RE.search(t):
        raise UnparseableError("步骤中包含无法解析的中文字符")
    if not _ALLOWED_RE.match(t):
        raise UnparseableError("步骤中包含无法解析的字符")
    if t.count("=") > 1:
        raise UnparseableError("一个步骤中只能包含一个等号")
    try:
        if "=" in t:
            lhs_s, rhs_s = t.split("=")
            if not lhs_s or not rhs_s:
                raise UnparseableError("等式两边不能为空")
            # evaluate=False：保留 7+3 这类原始结构不被立即求值，
            # 移项检测需要看到"被搬动的项"原样；等价性判定里的 simplify 会求值，不受影响
            lhs = _parse_expression(lhs_s)
            rhs = _parse_expression(rhs_s)
            return ParsedStep(kind="eq", expr=Eq(lhs, rhs, evaluate=False), text=t)
        expr = _parse_expression(t)
        return ParsedStep(kind="expr", expr=expr, text=t)
    except UnparseableError:
        raise
    except Exception as e:
        raise UnparseableError(f"解析失败: {e}")


def extract_equation(stem: str) -> Optional[ParsedStep]:
    """从题干文本中提取第一个等式（如"解方程：2x+3=7"→"2x+3=7"），
    找不到则返回 None（调用方把第一个可解析的学生步骤当作基准）。"""
    t = clean_text(stem)
    # 找包含等号的最长数学子串
    candidates = re.findall(r"[0-9a-zA-Z+\-*/()._\s]*=[0-9a-zA-Z+\-*/()._\s]*", t)
    candidates = [c.strip() for c in candidates if "=" in c and c.strip(" =")]
    if not candidates:
        return None
    best = max(candidates, key=len)
    try:
        return parse_step(best)
    except UnparseableError:
        return None
