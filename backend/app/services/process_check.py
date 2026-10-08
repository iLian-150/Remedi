# 过程可疑识别：答案对、过程存疑的二次验证信号。
#
# 背景（开题报告差异化点之三）：只看最终答案会漏掉一类作答——答案是对的，
# 但过程断裂/跳步/大面积写不清，学生可能并没有真正理解。本模块从已落库的
# Step/Error 做确定性判定（不调模型、不新建表、不改诊断主流程）：
#   - 先判最终答案是否与参考解一致（不一致直接 False，本模块只管"对而存疑"）；
#   - 再看三个结构信号：broken_chain / leap / unparseable_heavy，命中任一即
#     suspicious=True，signals 列出全部命中项及给老师看的中文原因。
#
# 可见性口径：判定结果只下发教师端（待审核详情的 process_check 字段）。
# 学生端永不出现 suspicious/process_check 等字段与「可疑/疑似」字样——
# 只在 diagnosis.present_diagnosis 里把追问换成老师口吻的过程追问。
from typing import Dict, List, Optional

from sympy import simplify, solve

from ..models import Question, Step, Submission
from .answer_check import _fmt
from .mathparse import extract_equation, parse_step


def _reference_values(stem: str) -> Optional[List]:
    """参考解：用 sympy 解题干方程，返回根列表（均为常数）。
    题干提不出等式、未知数不是恰好一个、解不出或根带符号 → None（判不了）。"""
    stem_eq = extract_equation(stem or "")
    if stem_eq is None or stem_eq.kind != "eq":
        return None
    symbols = sorted(stem_eq.expr.free_symbols, key=str)
    if len(symbols) != 1:
        return None
    try:
        roots = solve(stem_eq.expr.lhs - stem_eq.expr.rhs, symbols[0])
    except Exception:
        return None
    if not isinstance(roots, list) or not roots:
        return None
    if any(r.free_symbols for r in roots):
        return None
    return roots


def _final_answer_values(last_text: str) -> Optional[List]:
    """学生最终答案：解析最后一个作答步的文本取其解值。
    - 等式步（如 x=2 或 2x=4）：解这个等式，未知数须恰好一个、根为常数；
    - 纯数值表达式步（如直接写 2）：值本身即答案；
    其余（带符号的表达式、解析失败）→ None（取不到最终答案）。"""
    try:
        parsed = parse_step(last_text or "")
    except Exception:
        return None
    if parsed.kind == "eq":
        symbols = sorted(parsed.expr.free_symbols, key=str)
        if len(symbols) != 1:
            return None
        try:
            roots = solve(parsed.expr.lhs - parsed.expr.rhs, symbols[0])
        except Exception:
            return None
        if not isinstance(roots, list) or not roots:
            return None
        if any(r.free_symbols for r in roots):
            return None
        return roots
    if not parsed.expr.free_symbols:
        return [parsed.expr]
    return None


def _same_values(a: List, b: List) -> bool:
    """两个解集是否相等（逐一用 simplify 差值为 0 匹配，不计顺序、须等长）。"""
    if len(a) != len(b):
        return False
    remaining = list(b)
    for v in a:
        hit = None
        for i, w in enumerate(remaining):
            try:
                if simplify(v - w) == 0:
                    hit = i
                    break
            except Exception:
                continue
        if hit is None:
            return False
        remaining.pop(hit)
    return True


def analyze_process(db, submission: Submission) -> Dict:
    """判定一份提交是否「答案对、过程存疑」。

    返回 {suspicious, signals: [{code, text}], final_answer, reference_answer}；
    final_answer / reference_answer 是格式化后的答案文本（判不了时为 None）。
    纯从落库数据计算：答案不对、或结构上没有任何信号预兆时直接 False，
    不做无谓的求解。
    """
    result: Dict = {
        "suspicious": False,
        "signals": [],
        "final_answer": None,
        "reference_answer": None,
    }
    question: Optional[Question] = submission.question
    if question is None:
        question = db.query(Question).filter(
            Question.id == submission.question_id).first()
    if question is None or question.subject != "math":
        return result

    steps = (
        db.query(Step)
        .filter(Step.submission_id == submission.id, Step.seq >= 1)
        .order_by(Step.seq)
        .all()
    )
    if not steps:
        return result
    total = len(steps)
    error_steps = [s for s in steps if s.status == "error"]
    unparseable_steps = [s for s in steps if s.status == "unparseable"]
    has_broken = bool(error_steps)
    is_leap = total <= 1
    is_heavy = (len(unparseable_steps) / total) >= 0.5
    if not (has_broken or is_leap or is_heavy):
        return result  # 结构上无信号预兆，不必求解

    # 参考解与学生最终答案：任一取不到/对不上 → 不是"答案对"，一律 False
    ref_values = _reference_values(question.stem)
    if ref_values is None:
        return result
    final_values = _final_answer_values(steps[-1].text)
    if final_values is None or not _same_values(final_values, ref_values):
        return result

    result["final_answer"] = "、".join(_fmt(v) for v in final_values)
    result["reference_answer"] = "、".join(_fmt(v) for v in ref_values)
    signals: List[Dict] = []
    if has_broken:
        seq = error_steps[0].seq
        signals.append({
            "code": "broken_chain",
            "text": f"第 {seq} 步已判错，但最终答案正确，过程可能不完整",
        })
    if is_leap:
        signals.append({
            "code": "leap",
            "text": "只用了 1 步就直接写出正确答案，中间过程没有展开",
        })
    if is_heavy:
        signals.append({
            "code": "unparseable_heavy",
            "text": f"共 {total} 步中有 {len(unparseable_steps)} 步无法解析，"
                    f"但最终答案正确，过程难以核对",
        })
    result["signals"] = signals
    result["suspicious"] = bool(signals)
    return result
