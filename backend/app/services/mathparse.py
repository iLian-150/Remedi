# 数学步骤解析：把学生输入的文本步骤解析为 sympy 表达式/等式。
# 安全：只用 sympy.parsing 的 parse_expr（基于 AST 白名单解析），不用 sympify/eval，
# 不执行任意代码。解析失败抛 UnparseableError，由上层记为"无法解析"而不中断流程。
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional, Union

from sympy import Eq
from sympy.parsing.sympy_parser import (
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

TRANSFORMATIONS = standard_transformations + (implicit_multiplication_application,)

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
    return parse_expr(text, transformations=TRANSFORMATIONS, evaluate=False)


def _parse_expression(text: str):
    # Keep unusually long expressions out of the process-wide cache.
    if len(text) > 256:
        return parse_expr(text, transformations=TRANSFORMATIONS, evaluate=False)
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
