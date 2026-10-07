# 变式题生成与二次验证判定（v0.4.0 新增）。
#
# 定位：闭环的最后一环——学生订正成功只是「改对了这一步」，再独立做对一道
# 同知识点变式题，才算这个知识点真正修复（见 stats 的四态口径）。
#
# 生成策略：
#   1. 模板参数化生成（系数随机）：标准步骤在构造时即保证逐步等价，
#      再用 verify_chain 以与学生作答完全相同的逐步等价口径 sympy 复核一遍；
#   2. 无模板的知识点走 Provider 兜底生成同类题：能通过 verify_chain 的标
#      strict（严格模式），不能的标 practice（练习模式：仍可逐步诊断，
#      通过标准为全程无错且最后一步与参考答案等价——答案不可解析时只看全程无错）。
#
# 判定 judge_steps 与 diagnosis.diagnose_submission 同口径：逐步与上一步等价，
# 首个不等价步用 classify_rule 给错因与解析；无法解析不中断、基准不推进。
import random
from typing import Dict, List, Optional

from .diagnosis import classify_rule, equivalent
from .mathparse import UnparseableError, extract_equation, parse_step
from .providers import get_provider


def _sgn(n: int) -> str:
    """带符号数字：3 → '+3'，-3 → '-3'。"""
    return f"+{n}" if n >= 0 else str(n)


# ---------------------------------------------------------------- 模板

def _tpl_linear(rng: random.Random, kp: str) -> Dict:
    """一元一次方程：ax+b=c（a∈[2,9]，b 为非零整数，解为整数）。"""
    a = rng.randint(2, 9)
    b = 0
    while b == 0:
        b = rng.randint(-9, 9)
    x0 = rng.randint(-8, 10)
    c = a * x0 + b
    eq0 = f"{a}x{_sgn(b)}={c}"
    moved_rhs = f"{c}-{b}" if b > 0 else f"{c}+{-b}"
    steps = [eq0, f"{a}x={moved_rhs}", f"{a}x={c - b}", f"x={x0}"]
    return {
        "prompt": f"解方程：{eq0}",
        "knowledge_point": kp,
        "standard_steps": steps,
        "answer": f"x={x0}",
    }


def _tpl_square(rng: random.Random, kp: str) -> Dict:
    """完全平方公式：计算 (x±a)² 或 (ax±b)² 的展开式。"""
    if rng.random() < 0.5:
        a = rng.randint(2, 9)
        s = rng.choice([1, -1])
        inner = f"x{_sgn(s * a)}"
        expansion = f"x²{_sgn(2 * s * a)}x+{a * a}"
    else:
        a = rng.choice([2, 3])
        b = rng.randint(1, 5)
        s = rng.choice([1, -1])
        inner = f"{a}x{_sgn(s * b)}"
        expansion = f"{a * a}x²{_sgn(2 * a * s * b)}x+{b * b}"
    return {
        "prompt": f"计算：({inner})²",
        "knowledge_point": kp,
        "standard_steps": [f"({inner})²", expansion],
        "answer": expansion,
    }


def _tpl_brackets_solve(rng: random.Random, kp: str) -> Dict:
    """去括号解方程：a(x±b)=c（种子题 2(x-3)=10 的同型题）。"""
    a = rng.randint(2, 6)
    b = rng.randint(1, 9)
    s = rng.choice([1, -1])
    x0 = rng.randint(-5, 10)
    t = a * s * b  # 展开后的常数项
    c = a * (x0 + s * b)
    eq0 = f"{a}(x{_sgn(s * b)})={c}"
    moved_rhs = f"{c}-{t}" if t > 0 else f"{c}+{-t}"
    steps = [
        eq0,
        f"{a}x{_sgn(t)}={c}",
        f"{a}x={moved_rhs}",
        f"{a}x={c - t}",
        f"x={x0}",
    ]
    return {
        "prompt": f"解方程：{eq0}",
        "knowledge_point": kp,
        "standard_steps": steps,
        "answer": f"x={x0}",
    }


def _tpl_brackets_merge(rng: random.Random, kp: str) -> Dict:
    """去括号 + 合并同类项：a(x+b)+cx=d。"""
    a = rng.randint(2, 4)
    b = rng.randint(1, 6)
    c2 = rng.randint(2, 5)
    x0 = rng.randint(1, 8)
    d = a * (x0 + b) + c2 * x0
    coef = a + c2
    eq0 = f"{a}(x+{b})+{c2}x={d}"
    steps = [
        eq0,
        f"{a}x+{a * b}+{c2}x={d}",
        f"{coef}x+{a * b}={d}",
        f"{coef}x={d}-{a * b}",
        f"{coef}x={d - a * b}",
        f"x={x0}",
    ]
    return {
        "prompt": f"解方程：{eq0}",
        "knowledge_point": kp,
        "standard_steps": steps,
        "answer": f"x={x0}",
    }


def _builder_for(knowledge_point: str):
    if "一元一次方程" in knowledge_point:
        return _tpl_linear
    if "完全平方" in knowledge_point:
        return _tpl_square
    if "去括号" in knowledge_point or "合并同类项" in knowledge_point:
        return lambda rng, kp: rng.choice([_tpl_brackets_solve, _tpl_brackets_merge])(rng, kp)
    return None


# ---------------------------------------------------------------- 验算

def verify_chain(prompt: str, standard_steps: List[str], answer: str) -> bool:
    """以与学生作答相同的逐步等价口径验算一条标准步骤链：
    每一步可解析、与前一步等价，且最后一步与答案等价。"""
    try:
        base = extract_equation(prompt)
        if base is None:
            if not standard_steps:
                return False
            base = parse_step(standard_steps[0])
        last = None
        for text in standard_steps:
            parsed = parse_step(text)
            if not equivalent(base.expr, parsed.expr):
                return False
            base = parsed
            last = parsed
        if answer:
            target = parse_step(answer)
            if last is None or not equivalent(last.expr, target.expr):
                return False
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- 生成入口

def generate_variant(knowledge_point: str, seed: Optional[int] = None) -> Dict:
    """为知识点生成一道变式题：{prompt, knowledge_point, standard_steps, answer, mode}。
    mode: strict = 标准步骤/答案已经 sympy 验算；practice = 练习模式（兜底题未验算通过）。"""
    rng = random.Random(seed)
    builder = _builder_for(knowledge_point)
    if builder is not None:
        for _ in range(8):
            variant = builder(rng, knowledge_point)
            if verify_chain(variant["prompt"], variant["standard_steps"], variant["answer"]):
                variant["mode"] = "strict"
                return variant
        # 模板构造即正确，8 次复核全失败属异常情况，落到 Provider 兜底
    return _provider_fallback(knowledge_point, rng)


def _provider_fallback(knowledge_point: str, rng: random.Random) -> Dict:
    """无模板知识点：调 Provider 生成同类题；验算通过 → strict，否则 practice。
    Provider 完全不可用时退回一元一次方程模板题（practice），保证流程可跑。"""
    candidate = None
    try:
        candidate = get_provider().generate_variant_question(knowledge_point=knowledge_point)
    except Exception:
        candidate = None
    if candidate and candidate.get("prompt") and candidate.get("standard_steps"):
        variant = {
            "prompt": str(candidate["prompt"]),
            "knowledge_point": knowledge_point,
            "standard_steps": [str(s) for s in candidate["standard_steps"]],
            "answer": str(candidate.get("answer") or ""),
        }
        ok = verify_chain(variant["prompt"], variant["standard_steps"], variant["answer"])
        variant["mode"] = "strict" if ok else "practice"
        return variant
    variant = _tpl_linear(rng, knowledge_point)
    variant["mode"] = "practice"
    return variant


# ---------------------------------------------------------------- 判定

def judge_steps(variant: Dict, step_texts: List[str]) -> Dict:
    """判定一次验证作答。与 diagnose_submission 同口径：
    逐步等价推进；首个不等价步给出 classify_rule 的错因/解析并停止；
    无法解析记问题但不停止。全程无问题且最后一步与参考答案等价 → passed。"""
    prompt = variant.get("prompt", "")
    standard_steps = variant.get("standard_steps") or []
    answer = variant.get("answer") or ""

    if not step_texts:
        return {
            "passed": False, "steps": [], "first_error_seq": None,
            "error_type": None,
            "detail": "还没有写解题步骤，先把过程一步一步写出来。",
        }

    base = extract_equation(prompt)
    if base is None and standard_steps:
        try:
            base = parse_step(standard_steps[0])
        except UnparseableError:
            base = None

    results: List[Dict] = []
    first_inequiv = None     # 首个不等价步 {seq, error_type, detail}
    first_unparseable = None  # 首个无法解析步
    stopped = False
    last_parsed = None

    for i, raw in enumerate(step_texts, start=1):
        if stopped:
            results.append({"seq": i, "text": raw, "status": "skipped"})
            continue
        try:
            parsed = parse_step(raw)
        except UnparseableError as e:
            results.append({"seq": i, "text": raw, "status": "unparseable"})
            if first_unparseable is None:
                first_unparseable = {
                    "seq": i, "error_type": "无法解析",
                    "detail": f"这一步的写法暂时读不懂（{e}），检查一下符号、括号和等号是否写完整。",
                }
            continue  # 基准不推进，流程继续（与诊断口径一致）
        if base is None:
            base = parsed
            last_parsed = parsed
            results.append({"seq": i, "text": raw, "status": "ok"})
            continue
        if equivalent(base.expr, parsed.expr):
            base = parsed
            last_parsed = parsed
            results.append({"seq": i, "text": raw, "status": "ok"})
            continue
        rule = classify_rule(base, base.text, parsed, parsed.text)
        results.append({"seq": i, "text": raw, "status": "error"})
        if first_inequiv is None:
            detail = rule["detail"]
            if detail and detail.startswith("未命中常见误区模式"):
                # 规则兜底文案含教师端口径（置信度/复核），学生端换友好说法
                detail = "这一步和上一步对不上：对照题干再检查一下，是不是看错了条件，或者变形时出了小问题。"
            first_inequiv = {
                "seq": i, "error_type": rule["error_type"], "detail": detail,
            }
        stopped = True

    # 主问题口径与 present_diagnosis 一致：优先真正不等价步，其次无法解析步
    problem = first_inequiv or first_unparseable
    passed = problem is None

    if passed:
        # 最后一步须得到最终结果（与答案/标准步骤末步等价）；practice 模式
        # 且答案不可解析时，只以全程无错为准。
        target = None
        candidates = [answer] + ([standard_steps[-1]] if standard_steps else [])
        for cand in candidates:
            if cand:
                try:
                    target = parse_step(cand)
                    break
                except UnparseableError:
                    continue
        if target is not None and last_parsed is not None \
                and not equivalent(last_parsed.expr, target.expr):
            passed = False
            problem = {
                "seq": len(step_texts), "error_type": None,
                "detail": "每一步变形都对，但最后还没有得到最终结果，请继续化简到最后一步。",
            }

    return {
        "passed": passed,
        "steps": results,
        "first_error_seq": problem["seq"] if problem else None,
        "error_type": problem["error_type"] if problem else None,
        "detail": problem["detail"] if problem else "全部步骤正确，这道同类题做对了！",
    }
