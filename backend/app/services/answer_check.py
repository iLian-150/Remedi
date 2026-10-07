# 参考答案 AI 验算（v0.9.3）：教师发布作业填写参考答案时，先帮他验一遍
# 这个参考答案本身对不对。定位是"只警告、永不拦截"——疑似有误只提示，
# 发布与否始终由教师决定。
#
# 验算分两层：
#   1. sympy 机械验算（快、准、免费）：从题干提取等式，把老师答案代入验证
#      LHS=RHS；一元一/二次多项式方程再独立 solve 一遍比对，抓漏解。
#      题干是纯表达式（计算/化简题）时与题干表达式做等价/求值比对。
#   2. LLM 快速判断：机械法判不了的题型才问一次模型；模型不可用/超时/
#      结论不合格式 → 一律收敛为 unknown，绝不因 unknown 判 suspect。
# 任何异常都收敛为 unknown 返回，本模块不抛异常。
import logging
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Dict, List, Optional, Tuple

from sympy import Poly, simplify, solve

from .diagnosis import equivalent
from .mathparse import clean_text, extract_equation, parse_step
from .providers import get_provider

logger = logging.getLogger(__name__)

_UNKNOWN_DETAIL = "这类题暂时无法自动验算，请老师留意核对"
_LLM_TIMEOUT_SECONDS = 12

# 答案文本里的中文连接/引导词（在 clean_text 之前处理：它不认中文）
_ANSWER_SPLIT_RE = re.compile(r"[,，;；、]")
_ANSWER_LEAD_RE = re.compile(r"(解得|答案是|答案为|答案|所以|即|得)\s*[:：]?")


# ---------------------------------------------------------------- 工具

def _fmt(v) -> str:
    """把 sympy 数值格式化成老师能直接读的文本（整数/分数/小数）。"""
    try:
        v = simplify(v)
    except Exception:
        return str(v)
    if getattr(v, "is_Integer", False):
        return str(int(v))
    if getattr(v, "is_Rational", False):
        return f"{v.p}/{v.q}"
    if getattr(v, "is_number", False) and not v.free_symbols:
        try:
            f = float(v)
            if f == int(f) and abs(f) < 1e15:
                return str(int(f))
            return f"{f:.6f}".rstrip("0").rstrip(".")
        except Exception:
            pass
    return str(v).replace("**", "^")


def _clean_answer_text(raw: str) -> str:
    """答案文本预处理：去掉中文引导词、把「或/、/；」统一成分隔符，再走
    mathparse 的 clean_text 做全角/符号归一化。"""
    t = raw.strip()
    t = t.replace("或", ",")
    t = _ANSWER_LEAD_RE.sub("", t)
    t = t.rstrip("。").strip()
    return clean_text(t)


# ---------------------------------------------------------------- 答案解析

_VAR_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _base_var_name(name: str) -> str:
    """x1 / x_2 这类多解下标写法归一到基变量名 x。"""
    return re.sub(r"_?\d+$", "", name)


def _parse_answer_values(reference_answer: str) -> Optional[List[List[Tuple[Optional[str], object]]]]:
    """把老师答案解析成「候选赋值」列表：外层是候选（一元方程每个解一个），
    内层是 (基变量名, 常数值) 对（裸值时变量名为 None）。

    解析不了（答案是等式、含未知量、写法太自由）返回 None，交给上层转 LLM。
    """
    t = _clean_answer_text(reference_answer)
    if not t:
        return None
    parts = [p for p in _ANSWER_SPLIT_RE.split(t) if p]
    if not parts:
        return None
    by_base: Dict[Optional[str], List[object]] = {}
    for part in parts:
        if part.count("=") > 1:
            return None
        if "=" in part:
            lhs_s, rhs_s = part.split("=")
            if not _VAR_NAME_RE.match(lhs_s):
                return None  # 等号左边不是变量名 → 是等式型答案，不在此处理
            base: Optional[str] = _base_var_name(lhs_s)
            value_text = rhs_s
        else:
            base = None
            value_text = part
        try:
            parsed = parse_step(value_text)
        except Exception:
            return None
        if parsed.kind != "expr" or parsed.expr.free_symbols:
            return None  # 值里还带符号 → 不是常数答案，机械法判不了
        by_base.setdefault(base, []).append(parsed.expr)
    bases = [b for b in by_base if b is not None]
    if len(bases) <= 1:
        base = bases[0] if bases else None
        values = list(by_base.get(None, [])) + list(by_base.get(base, []) if base else [])
        if not values:
            return None
        return [[(base, v)] for v in values]
    # 多个不同变量（方程组类）：每个变量必须恰好给一个值，合成一个候选赋值
    candidate: List[Tuple[Optional[str], object]] = []
    for b in bases:
        vals = by_base[b]
        if len(vals) != 1:
            return None
        candidate.append((b, vals[0]))
    if by_base.get(None):
        return None  # 变量值与裸值混写，判不了
    return [candidate]


def _map_to_symbols(pairs: List[Tuple[Optional[str], object]],
                    symbols: List) -> Optional[Dict]:
    """把候选赋值里的基变量名映射到题干里的 sympy 符号。
    题干只有一个未知数时，任何变量名/裸值都映射到它；多个未知数时按同名匹配。"""
    if len(symbols) == 1:
        sym = symbols[0]
        if len(pairs) > 1:
            return None  # 单未知数题出现多个不同变量名，不合常理
        return {sym: pairs[0][1]}
    by_name = {str(s): s for s in symbols}
    subs = {}
    for base, value in pairs:
        if base is None or base not in by_name:
            return None
        subs[by_name[base]] = value
    return subs


# ---------------------------------------------------------------- sympy 验算

def _check_equation_answer(eq, candidates) -> Optional[Dict]:
    """把候选解代入题干等式验证。返回结论 dict；判不了返回 None。"""
    lhs, rhs = eq.lhs, eq.rhs
    symbols = sorted(eq.free_symbols, key=str)
    if not symbols:
        return None
    checked: List[Tuple[Dict, str]] = []  # (subs, 该候选的文字描述)
    for pairs in candidates:
        subs = _map_to_symbols(pairs, symbols)
        if subs is None:
            return None
        desc = "、".join(f"{s}={_fmt(v)}" for s, v in subs.items())
        lv = simplify(lhs.subs(subs))
        rv = simplify(rhs.subs(subs))
        if not lv.free_symbols and not rv.free_symbols:
            if simplify(lv - rv) != 0:
                var_desc = "、".join(f"{s}={_fmt(v)}" for s, v in subs.items())
                return {
                    "status": "suspect",
                    "detail": f"把 {var_desc} 代入原方程：左边={_fmt(lv)}，右边={_fmt(rv)}，"
                              f"等式不成立，参考答案可能有误",
                    "method": "sympy",
                }
            checked.append((subs, desc))
        elif simplify(lv - rv) == 0:
            checked.append((subs, desc))  # 代入后恒等成立
        else:
            return None  # 代入后仍带符号且不恒等，机械法判不了
    if not checked:
        return None
    descs = "；".join(d for _, d in checked)
    detail = f"已代入验算：{descs} 代入原方程成立"
    # 完备性：单未知数的一/二次多项式方程独立求解一遍，抓漏解
    if len(symbols) == 1:
        sym = symbols[0]
        expr = lhs - rhs
        try:
            if expr.is_polynomial(sym) and Poly(expr, sym).degree() <= 2:
                roots = solve(expr, sym)
                if isinstance(roots, list) and roots:
                    teacher_vals = [list(s.values())[0] for s, _ in checked]
                    missing = [
                        r for r in roots
                        if not any(simplify(r - tv) == 0 for tv in teacher_vals)
                    ]
                    if missing:
                        miss_desc = "、".join(f"{sym}={_fmt(r)}" for r in missing)
                        return {
                            "status": "suspect",
                            "detail": f"{descs} 代入成立，但独立求解还得到 {miss_desc}，"
                                      f"参考答案可能漏了答案",
                            "method": "sympy",
                        }
                    detail += "，与独立求解的结果一致"
        except Exception:
            pass  # 求解失败只跳过完备性，代入结论照常成立
    return {"status": "ok", "detail": detail, "method": "sympy"}


def _check_expression_answer(stem: str, reference_answer: str) -> Optional[Dict]:
    """题干是纯表达式（计算/化简题）时：与题干表达式做求值/等价比对。"""
    t = clean_text(stem)
    if ":" in t:  # 去掉「计算：」「化简：」这类中文引导前缀（clean_text 后只剩冒号）
        t = t.rsplit(":", 1)[-1]
    try:
        stem_parsed = parse_step(t)
    except Exception:
        return None
    if stem_parsed.kind != "expr":
        return None
    target = stem_parsed.expr
    # 老师答案：数值或表达式
    values = _parse_answer_values(reference_answer)
    if values and len(values) == 1 and len(values[0]) == 1:
        val = values[0][0][1]
        if not target.free_symbols:
            diff = simplify(target - val)
            if not diff.free_symbols:
                if diff == 0:
                    return {"status": "ok",
                            "detail": f"已验算：题干算式的值为 {_fmt(target)}，与参考答案一致",
                            "method": "sympy"}
                return {"status": "suspect",
                        "detail": f"题干算式的值应为 {_fmt(target)}，参考答案写的是 {_fmt(val)}，可能有误",
                        "method": "sympy"}
            return None
        if equivalent(target, val):
            return {"status": "ok", "detail": "已验算：参考答案与题干表达式等价",
                    "method": "sympy"}
        return {"status": "suspect",
                "detail": "参考答案与题干表达式化简后不相等，可能有误",
                "method": "sympy"}
    try:
        ans_parsed = parse_step(_clean_answer_text(reference_answer))
    except Exception:
        return None
    if ans_parsed.kind == "expr":
        if equivalent(target, ans_parsed.expr):
            return {"status": "ok", "detail": "已验算：参考答案与题干表达式等价",
                    "method": "sympy"}
        return {"status": "suspect",
                "detail": "参考答案与题干表达式化简后不相等，可能有误",
                "method": "sympy"}
    return None


def _sympy_check(stem: str, reference_answer: str) -> Optional[Dict]:
    stem_eq = extract_equation(stem)
    if stem_eq is not None and stem_eq.kind == "eq":
        # 优先值解析：x=2 / 2 / x1=2, x2=3 这类"解"的写法走代入验证。
        # 不能先判等式等价——"x=2"与原方程在等价语义下成立纯属形式巧合，
        # 且错误答案（如 x=3）会因此被误判为判不了。
        candidates = _parse_answer_values(reference_answer)
        if candidates:
            return _check_equation_answer(stem_eq.expr, candidates)
        # 值解析失败且答案本身是个等式（恒等变形类）→ 与题干做等价比对
        try:
            ans_parsed = parse_step(_clean_answer_text(reference_answer))
        except Exception:
            ans_parsed = None
        if ans_parsed is not None and ans_parsed.kind == "eq":
            if equivalent(stem_eq.expr, ans_parsed.expr):
                return {"status": "ok", "detail": "已验算：参考答案与题干等式等价",
                        "method": "sympy"}
        return None  # 其余交给 LLM 判读
    return _check_expression_answer(stem, reference_answer)


# ---------------------------------------------------------------- LLM 验算

def _llm_check(stem: str, reference_answer: str,
               knowledge_point: Optional[str]) -> Optional[Dict]:
    """机械法判不了时问一次模型。模型没有真实推理通道（如 Mock）/超时/
    返回不合格式 → None（上层收敛为 unknown），绝不据此判 suspect。"""
    provider = get_provider()
    chat = getattr(provider, "_chat", None)
    if chat is None:
        return None  # Mock 等无 LLM 通道的 provider：视为不可用
    system = "你是数学教师助手，只判断老师拟用的参考答案是否正确。只返回 JSON，不要解释。"
    user = (
        f"题干：{stem}\n"
        f"知识点：{knowledge_point or '未注明'}\n"
        f"老师填写的参考答案：{reference_answer}\n"
        '请判断这份参考答案是否正确。返回 JSON：{"correct": true 或 false, '
        '"reason": "一句中文理由，不超过 40 字"}。'
    )
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(chat, system, user)
        out = future.result(timeout=_LLM_TIMEOUT_SECONDS)
    except FutureTimeout:
        logger.warning("参考答案 LLM 验算超时，降级 unknown")
        return None
    except Exception as e:
        logger.warning("参考答案 LLM 验算失败，降级 unknown: %s", e)
        return None
    finally:
        executor.shutdown(wait=False)
    try:
        from .providers import DeepSeekProvider
        data = DeepSeekProvider._extract_json(out)
        correct = data.get("correct")
        reason = str(data.get("reason", "")).strip()
        if correct is True:
            return {"status": "ok", "detail": f"AI 复核：{reason or '参考答案正确'}",
                    "method": "llm"}
        if correct is False:
            return {"status": "suspect",
                    "detail": f"AI 复核提示：{reason or '参考答案可能有误'}（仅供参考，请老师再核对一遍）",
                    "method": "llm"}
    except Exception as e:
        logger.warning("参考答案 LLM 返回解析失败，降级 unknown: %s", e)
    return None


# ---------------------------------------------------------------- 主入口

def check_reference_answer(stem: str, reference_answer: str,
                           knowledge_point: Optional[str] = None) -> Dict:
    """验算老师的参考答案。返回 {status, detail, method}，永不抛异常：
    status ∈ ok / suspect / unknown；method ∈ sympy / llm / none。"""
    try:
        stem = (stem or "").strip()
        reference_answer = (reference_answer or "").strip()
        if not stem or not reference_answer:
            return {"status": "unknown", "detail": _UNKNOWN_DETAIL, "method": "none"}
        result = _sympy_check(stem, reference_answer)
        if result is not None:
            return result
        result = _llm_check(stem, reference_answer, knowledge_point)
        if result is not None:
            return result
        return {"status": "unknown", "detail": _UNKNOWN_DETAIL, "method": "none"}
    except Exception as e:
        logger.warning("参考答案验算异常，收敛为 unknown: %s", e)
        return {"status": "unknown", "detail": _UNKNOWN_DETAIL, "method": "none"}
