# 数学分步诊断服务：sympy 逐个验证步骤等价性 → 规则分类错因 → 顽固判定。
#
# 诊断流程：
#   1. step0 = 题干（仅参考，不校验；尝试从题干提取等式作为初始基准）
#   2. 从 seq=1 起逐个解析步骤：
#        - 解析失败 → 记 error（无法解析，置信度 0.3），流程继续，基准不变
#        - 与基准等价 → ok，基准更新为本步
#        - 不等价 → 记 error（规则分类 + Provider 复核），停止（后续步骤记 skipped）
#   3. 每条 error 落库后做顽固判定（同学生同知识点 N 天内重复出错）
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from sqlalchemy import inspect as sa_inspect
from sympy import Add, Eq, expand, simplify

from ..config import settings
from ..models import Error, Question, Step, Submission, User
from .mathparse import ParsedStep, UnparseableError, extract_equation, parse_step
from .confidence import normalize_confidence
from .providers import get_provider

# 置信度常量
CONF_PATTERN = 0.85      # 命中常见误区模式
CONF_ARITHMETIC = 0.7    # 纯算术小偏差
CONF_FALLBACK = 0.5      # 兜底：审题遗漏
CONF_UNPARSEABLE = 0.3   # 无法解析


# ---------------------------------------------------------------- 等价性判定

def equivalent(a, b) -> bool:
    """判断两个 sympy 对象（表达式或等式）是否数学等价。

    - 等式：把两边移项得 f1、f2；simplify(f1-f2)==0，或 f2/f1 化简为非零常数
      （允许两边同乘/同除非零常数，如 2x=4 → 4x=8）。
    - 表达式：simplify(a-b)==0。
    """
    a_is_eq = isinstance(a, Eq)
    b_is_eq = isinstance(b, Eq)
    if a_is_eq and b_is_eq:
        f1 = simplify(a.lhs - a.rhs)
        f2 = simplify(b.lhs - b.rhs)
        if f1 == 0 and f2 == 0:
            return True
        if f1 == 0 or f2 == 0:
            return False
        if simplify(f1 - f2) == 0:
            return True
        try:
            ratio = simplify(f2 / f1)
            if ratio.is_number and ratio.is_nonzero:
                return True
        except Exception:
            pass
        return False
    if a_is_eq != b_is_eq:
        return False
    try:
        return simplify(a - b) == 0
    except Exception:
        return False


def _terms(expr) -> List:
    expr = expand(expr)
    return list(expr.args) if isinstance(expr, Add) else [expr]


def _term_in(term, terms) -> bool:
    return any(simplify(term - c) == 0 for c in terms)


# ---------------------------------------------------------------- 误区模式库（规则分类）

def detect_square_mistake(prev_text: str, curr: ParsedStep) -> Optional[str]:
    """模式1：(a±b)² 展开漏掉交叉项，如 (x+2)² → x²+4（漏掉 4x）。"""
    m = re.search(r"\(\s*([^()]+?)\s*([+-])\s*([^()]+?)\s*\)\s*\*\*\s*2", prev_text)
    if not m:
        return None
    try:
        from sympy.parsing.sympy_parser import parse_expr
        from .mathparse import TRANSFORMATIONS
        a = parse_expr(m.group(1), transformations=TRANSFORMATIONS)
        b = parse_expr(m.group(3), transformations=TRANSFORMATIONS)
    except Exception:
        return None
    sign = m.group(2)
    correct = expand((a + b) ** 2) if sign == "+" else expand((a - b) ** 2)
    wrong = expand(a ** 2 + b ** 2)  # 漏掉交叉项的典型错误
    sides = [curr.expr.lhs, curr.expr.rhs] if curr.kind == "eq" else [curr.expr]
    for side in sides:
        if equivalent(side, wrong) and not equivalent(side, correct):
            if sign == "+":
                return "平方展开漏掉交叉项：(a+b)²=a²+2ab+b²，本次漏掉了 2ab 项"
            return "平方展开漏掉交叉项：(a-b)²=a²-2ab+b²，本次漏掉了 -2ab 项"
    return None


def _raw_terms(expr) -> List:
    """不展开的项拆分：保留 7+3 中的 3 等原始项，移项检测需要看到"被搬动的项"原样。"""
    return list(expr.args) if isinstance(expr, Add) else [expr]


def detect_sign_move_mistake(prev: ParsedStep, curr: ParsedStep) -> Optional[str]:
    """模式2：移项不变号，如 2x+3=7 → 2x=7+3（+3 移到右边应变 -3）。仅处理等式→等式。
    注意用不展开的项：展开会把 7+3 合并成 10，使被搬动的 +3 无法被识别。"""
    if prev.kind != "eq" or curr.kind != "eq":
        return None
    pl, pr = _raw_terms(prev.expr.lhs), _raw_terms(prev.expr.rhs)
    cl, cr = _raw_terms(curr.expr.lhs), _raw_terms(curr.expr.rhs)
    # 左边消失的项：正确应以变号形式出现在右边；若以同号出现 → 移项未变号
    for t in pl:
        if not _term_in(t, cl):
            if _term_in(t, cr):
                return f"移项未变号：{t} 移到等号另一边时没有变号"
    for t in pr:
        if not _term_in(t, cr):
            if _term_in(t, cl):
                return f"移项未变号：{t} 移到等号另一边时没有变号"
    return None


def detect_distributive_mistake(prev_text: str, curr: ParsedStep) -> Optional[str]:
    """模式3：分配律漏乘，如 2(x-3)=10 → 2x-3=10（-3 漏乘 2）。"""
    matches = re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*\*\s*\(([^()]+)\)", prev_text)
    if not matches:
        return None
    from sympy.parsing.sympy_parser import parse_expr
    from .mathparse import TRANSFORMATIONS
    prev_sides = prev_text.split("=")
    curr_sides = [curr.expr.lhs, curr.expr.rhs] if curr.kind == "eq" else [curr.expr]
    for k_s, inner_s in matches:
        try:
            k = parse_expr(k_s, transformations=TRANSFORMATIONS)
            inner = parse_expr(inner_s, transformations=TRANSFORMATIONS)
        except Exception:
            continue
        inner_terms = _terms(inner)
        for idx, side_text in enumerate(prev_sides):
            if f"{k_s}*({inner_s})" not in side_text and f"{k_s} * ({inner_s})" not in side_text:
                # 宽松匹配：该侧包含 k*(...) 结构即可
                if "*" not in side_text or "(" not in side_text:
                    continue
            try:
                side_parsed = parse_expr(side_text, transformations=TRANSFORMATIONS)
            except Exception:
                continue
            correct_side = expand(side_parsed)
            if idx >= len(curr_sides):
                continue
            curr_side = curr_sides[idx]
            for it in inner_terms:
                wrong_side = expand(correct_side - k * it + it)  # 该项漏乘 k
                if equivalent(curr_side, wrong_side) and not equivalent(curr_side, correct_side):
                    return f"分配律漏乘：用 {k_s} 乘括号时，括号内 {it} 这一项漏乘了系数"
    return None


_NUMBER_RE = re.compile(r"(?<![\d.])([0-9]+(?:\.[0-9]+)?)(?![\d.])")
_DELTAS = (1, -1, 2, -2, 3, -3)


def detect_arithmetic_slip(prev: ParsedStep, curr_text: str) -> Optional[str]:
    """纯算术小偏差：把本步中的数字逐个做 ±1/±2/±3 微调，若某次微调后与上一步
    等价 → 判定为抄错数字/口算小偏差（计算失误）。"""
    numbers = []
    for m in _NUMBER_RE.finditer(curr_text):
        if m.group(1) not in numbers:
            numbers.append(m.group(1))
    for num_s in numbers[:6]:  # 上限，避免组合爆炸
        is_float = "." in num_s
        base_v = float(num_s) if is_float else int(num_s)
        for d in _DELTAS:
            new_v = base_v + d
            new_s = str(new_v) if is_float else str(int(new_v))
            # 只替换第一个出现的该数字，避免 "2" 误伤 "12"
            candidate = re.sub(r"(?<![\d.])" + re.escape(num_s) + r"(?![\d.])", new_s, curr_text, count=1)
            try:
                cand = parse_step(candidate)
            except UnparseableError:
                continue
            if equivalent(prev.expr, cand.expr):
                return f"纯算术偏差：数字 {num_s} 疑似应为 {new_s}（抄错/口算小偏差）"
    return None


def classify_rule(prev: ParsedStep, prev_text: str,
                  curr: ParsedStep, curr_text: str) -> Dict:
    """先规则后模型中的"规则"部分：返回 {error_type, confidence, detail}。"""
    hit = detect_square_mistake(prev_text, curr)
    if hit:
        return {"error_type": "概念混淆", "confidence": CONF_PATTERN, "detail": hit}
    hit = detect_sign_move_mistake(prev, curr)
    if hit:
        return {"error_type": "概念混淆", "confidence": CONF_PATTERN, "detail": hit}
    hit = detect_distributive_mistake(prev_text, curr)
    if hit:
        return {"error_type": "概念混淆", "confidence": CONF_PATTERN, "detail": hit}
    hit = detect_arithmetic_slip(prev, curr_text)
    if hit:
        return {"error_type": "计算失误", "confidence": CONF_ARITHMETIC, "detail": hit}
    return {
        "error_type": "审题遗漏",
        "confidence": CONF_FALLBACK,
        "detail": "未命中常见误区模式：请对照题干检查是否看错条件或问题（已降置信度，建议教师复核）",
    }


# ---------------------------------------------------------------- 顽固判定

def check_stubborn(
    db, student_id: int, knowledge_point: str,
    exclude_submission_id: Optional[int],
) -> bool:
    """同一学生的其他提交在过去 N 天内出现过该知识点错因 → 顽固误区。"""
    window_start = datetime.now() - timedelta(days=settings.STUBBORN_WINDOW_DAYS)
    query = (
        db.query(Error.id)
        .join(Submission, Error.submission_id == Submission.id)
        .filter(
            Submission.student_id == student_id,
            Error.knowledge_point == knowledge_point,
            Error.created_at >= window_start,
        )
    )
    if exclude_submission_id is not None:
        query = query.filter(Submission.id != exclude_submission_id)
    return query.first() is not None


def _commit_diagnosis_and_score(
    db, submission: Submission, steps: List[Step],
) -> None:
    """Commit diagnosis rows without refreshing every step and error separately.

    Keep objects loaded across both commits so score calculation can use the
    in-memory steps. Diagnosis stays committed if writing its score fails.
    """
    expire_on_commit = db.expire_on_commit
    db.expire_on_commit = False
    try:
        db.commit()
        try:
            from .scoring import persist_ai_score
            persist_ai_score(db, submission, steps)
        except Exception:
            db.rollback()
    finally:
        db.expire_on_commit = expire_on_commit


# ---------------------------------------------------------------- 主流程

def diagnose_submission(db, student: User, question: Question,
                        step_texts: List[str],
                        reuse: Optional[Submission] = None) -> Tuple[Submission, List[Step], List[Error]]:
    """执行一次数学诊断，落库 Submission/Step/Error，返回 ORM 对象。

    reuse（v0.13.1）：延迟批改到期时复用原延迟提交行——分析完成后替换占位
    步骤/错误，提交 id 与时间保持不变。分析和模型请求阶段不写数据库。"""
    if reuse is None:
        submission = Submission(
            student_id=student.id,
            question_id=question.id,
            question=question,
            status="submitted",
        )
    else:
        submission = reuse
    submission.question = question

    def new_step(seq: int, text: str, status: str) -> Step:
        if reuse is None:
            return Step(submission=submission, seq=seq, text=text, status=status)
        return Step(submission_id=submission.id, seq=seq, text=text, status=status)

    def new_error(step: Step, **fields) -> Error:
        if reuse is None:
            return Error(submission=submission, step=step, **fields)
        return Error(submission_id=submission.id, step=step, **fields)

    steps: List[Step] = []
    errors: List[Error] = []
    stubborn_history = None

    # seq=0：题干，仅参考
    stem_step = new_step(0, question.stem, "stem")
    steps.append(stem_step)

    base: Optional[ParsedStep] = extract_equation(question.stem)
    stopped = False  # 是否已在首个不等价步骤处停止（无法解析不触发停止）
    provider = get_provider()

    for i, raw in enumerate(step_texts, start=1):
        if stopped:
            steps.append(new_step(i, raw, "skipped"))
            continue
        try:
            parsed = parse_step(raw)
        except UnparseableError as e:
            if stubborn_history is None:
                stubborn_history = check_stubborn(
                    db, student.id, question.knowledge_point, submission.id
                )
            step = new_step(i, raw, "unparseable")
            err = new_error(
                step,
                knowledge_point=question.knowledge_point,
                error_type="无法解析",
                confidence=CONF_UNPARSEABLE,
                detail=f"该步骤无法解析为数学表达式（{e}），请检查格式",
                is_stubborn=stubborn_history,
            )
            steps.append(step)
            errors.append(err)
            continue  # 基准不变，流程继续（不停止）

        if base is None:
            base = parsed
            steps.append(new_step(i, raw, "ok"))
            continue

        if equivalent(base.expr, parsed.expr):
            base = parsed
            steps.append(new_step(i, raw, "ok"))
            continue

        # 首个不等价步骤 → 错因分类（先规则，后用 Provider 复核/改写）
        step = new_step(i, raw, "error")
        rule_result = classify_rule(base, base.text, parsed, parsed.text)
        try:
            final = provider.classify_error(
                question_stem=question.stem,
                knowledge_point=question.knowledge_point,
                prev_step=base.text,
                curr_step=parsed.text,
                rule_result=rule_result,
            ) or rule_result
        except Exception:
            final = rule_result  # Provider 异常时回退到规则结果，保证流程不中断
        if stubborn_history is None:
            stubborn_history = check_stubborn(
                db, student.id, question.knowledge_point, submission.id
            )
        err = new_error(
            step,
            knowledge_point=question.knowledge_point,
            error_type=final.get("error_type", rule_result["error_type"]),
            confidence=normalize_confidence(
                final.get("confidence", rule_result["confidence"]),
                rule_result["confidence"],
            ),
            detail=final.get("detail", rule_result["detail"]),
            is_stubborn=stubborn_history,
        )
        steps.append(step)
        errors.append(err)
        stopped = True  # 首个不等价步骤：停止，后续步骤记 skipped

    if reuse is not None:
        db.query(Step).filter(Step.submission_id == submission.id).delete()
        db.query(Error).filter(Error.submission_id == submission.id).delete()
    db.add(submission)
    db.add_all(steps)
    db.add_all(errors)
    submission.status = "graded"
    _commit_diagnosis_and_score(db, submission, steps)
    return submission, steps, errors


def diagnose_visual_submission(db, student: User, question: Question,
                               visual_steps: List[dict],
                               reuse: Optional[Submission] = None) -> Tuple[Submission, List[Step], List[Error]]:
    """持久化视觉模型直接给出的多学科作答判断，不再二次解析识别文本。"""
    if reuse is not None:
        submission = reuse
        db.query(Error).filter(Error.submission_id == submission.id).delete()
        db.query(Step).filter(Step.submission_id == submission.id).delete()
        submission.status = "submitted"
        db.flush()
    else:
        submission = Submission(
            student_id=student.id,
            question_id=question.id,
            question=question,
            status="submitted",
        )
        db.add(submission)
        db.flush()

    stem_step = Step(submission_id=submission.id, seq=0, text=question.stem, status="stem")
    db.add(stem_step)
    steps: List[Step] = [stem_step]
    errors: List[Error] = []
    stubborn_history = None
    allowed_error_types = {
        "计算失误", "概念混淆", "审题遗漏", "无法解析", "语法错误",
        "拼写错误", "词形错误", "表达不当", "知识错误", "单位错误",
        "步骤遗漏", "答案不完整", "论证不充分", "图表判断错误", "其他错误",
    }

    for seq, item in enumerate(visual_steps, start=1):
        text = str(item.get("text", "")).strip()[:500]
        if not text:
            continue
        result = str(item.get("result", "uncertain")).strip().lower()
        confidence = normalize_confidence(item.get("confidence", 0.5), 0.5)
        if result == "correct":
            step = Step(submission_id=submission.id, seq=seq, text=text, status="ok")
            db.add(step)
            steps.append(step)
            continue

        uncertain = result != "incorrect"
        if uncertain:
            # 无法确认的步骤以低置信记录进入错题本，并同步进入教师复核队列。
            confidence = min(confidence, 0.59)
        error_type = str(item.get("error_type", "")).strip()
        if error_type not in allowed_error_types:
            error_type = "无法解析" if uncertain else "审题遗漏"
        step = Step(
            submission_id=submission.id,
            seq=seq,
            text=text,
            status="unparseable" if uncertain else "error",
        )
        if stubborn_history is None:
            stubborn_history = check_stubborn(
                db, student.id, question.knowledge_point, submission.id
            )
        error = Error(
            submission_id=submission.id,
            step=step,
            knowledge_point=question.knowledge_point,
            error_type=error_type,
            confidence=confidence,
            detail=(str(item.get("detail", "")).strip()[:1000]
                    or ("视觉模型无法确认该步骤是否正确，建议教师复核。"
                        if uncertain else "视觉模型判断该步骤有误。")),
            is_stubborn=stubborn_history,
        )
        db.add_all([step, error])
        steps.append(step)
        errors.append(error)

    submission.status = "graded"
    _commit_diagnosis_and_score(db, submission, steps)
    return submission, steps, errors


# ---------------------------------------------------------------- 订正判定

def verify_correction(db, error: Error, content: str) -> Tuple[Optional[bool], str]:
    """判定订正是否正确：订正内容应与"出错前一步"等价。
    返回 (is_correct, note)，is_correct 为 None 表示无法判定。"""
    submission = error.submission
    question = submission.question if submission is not None else None
    if question is None or question.subject != "math":
        return None, "非数学题，订正需教师人工确认"
    try:
        corrected = parse_step(content)
    except UnparseableError:
        return None, "订正内容无法解析，请检查格式（如 2x=4）"
    step = error.step
    base_text = None
    if step is not None:
        prev = (
            db.query(Step.text)
            .filter(Step.submission_id == error.submission_id,
                    Step.seq < step.seq,
                    Step.status.in_(["ok", "stem"]))
            .order_by(Step.seq.desc())
            .first()
        )
        if prev is not None:
            base_text = prev[0]
    if not base_text:
        return None, "缺少可用的参考步骤，需教师确认"
    try:
        base = parse_step(base_text)
    except UnparseableError:
        base = extract_equation(base_text)
    if base is None:
        return None, "参考步骤无法解析，需教师确认"
    if equivalent(base.expr, corrected.expr):
        return True, "订正步骤与出错前一步等价，订正正确"
    return False, "订正后仍与上一步不等价，请再检查"


# ---------------------------------------------------------------- 出参组装

def present_error(err: Error, db, step: Optional[Step] = None) -> dict:
    if step is None and err.step_id:
        step = db.query(Step).filter(Step.id == err.step_id).first()
    return {
        "id": err.id,
        "submission_id": err.submission_id,
        "step_seq": step.seq if step else None,
        "step_text": step.text if step else None,
        "knowledge_point": err.knowledge_point,
        "error_type": err.error_type,
        "confidence": err.confidence,
        "is_stubborn": err.is_stubborn,
        "detail": err.detail,
        "teacher_corrected": err.teacher_corrected,
        "teacher_note": err.teacher_note,
        "created_at": err.created_at,
    }


def present_diagnosis(
    submission: Submission,
    db,
    steps: Optional[List[Step]] = None,
    errors: Optional[List[Error]] = None,
) -> dict:
    if steps is not None and any(sa_inspect(step).expired for step in steps):
        steps = None
    if errors is not None and any(sa_inspect(error).expired for error in errors):
        errors = None
    diagnosis, _ = present_diagnosis_with_process_check(
        submission, db, steps=steps, errors=errors
    )
    return diagnosis


def present_diagnosis_with_process_check(
    submission: Submission,
    db,
    steps: Optional[List[Step]] = None,
    *,
    errors: Optional[List[Error]] = None,
    strict_process_check: bool = False,
) -> Tuple[dict, dict]:
    if steps is None:
        steps = (
            db.query(Step)
            .filter(Step.submission_id == submission.id)
            .order_by(Step.seq)
            .all()
        )
    steps_by_id = {step.id: step for step in steps}
    if errors is None:
        errors = (
            db.query(Error)
            .filter(Error.submission_id == submission.id)
            .order_by(Error.id)
            .all()
        )
    # first_error_seq：首个 status=error（真正不等价）步骤的 seq；
    # 若只有无法解析，则取首个 unparseable 的 seq；全对则为 None
    seq_by_step_id = {s.id: s.seq for s in steps}
    status_by_step_id = {s.id: s.status for s in steps}
    first_error_seq = None
    for e in errors:
        if status_by_step_id.get(e.step_id) == "error":
            first_error_seq = seq_by_step_id.get(e.step_id)
            break
    if first_error_seq is None:
        for e in errors:
            if status_by_step_id.get(e.step_id) == "unparseable":
                first_error_seq = seq_by_step_id.get(e.step_id)
                break
    # 追问（v0.4.0）：取主错误（与 first_error_seq 同口径：优先真正不等价步的
    # 错误，其次无法解析步）生成一句启发式追问；无错时为 None。
    from .followup import generate_follow_up
    main_error = None
    if errors:
        for e in errors:
            if seq_by_step_id.get(e.step_id) == first_error_seq:
                main_error = e
                break
        if main_error is None:
            main_error = errors[0]
    follow_up_question = (
        generate_follow_up(main_error.error_type, main_error.knowledge_point)
        if main_error else None
    )
    # 过程可疑识别（与教师端 process_check 同源判定）：答案对但过程存疑时，
    # 把追问换成针对断裂步的过程追问——口径是老师在问，只问过程、不带任何
    # 怀疑字眼；判定本身（suspicious/signals）绝不进学生出参。
    try:
        from .process_check import analyze_process
        pc = analyze_process(
            db, submission, [step for step in steps if step.seq >= 1]
        )
    except Exception:
        if strict_process_check:
            raise
        pc = {"suspicious": False, "signals": []}
    if pc.get("suspicious"):
        codes = {s.get("code") for s in pc.get("signals", [])}
        if "broken_chain" in codes and first_error_seq is not None:
            follow_up_question = (
                f"这道题你最后得到了正确答案，不过老师想听听："
                f"第 {first_error_seq} 步你是怎么想的？"
            )
        elif "leap" in codes:
            follow_up_question = (
                "这道题你很快就写出了正确答案，老师想听听："
                "你心里是怎么一步一步想的？把中间的想法说给老师听听。"
            )
        elif "unparseable_heavy" in codes:
            if first_error_seq is not None:
                follow_up_question = (
                    f"这道题你最后得到了正确答案，不过有一步老师没太看清："
                    f"第 {first_error_seq} 步你是怎么想的？"
                )
            else:
                follow_up_question = (
                    "这道题你最后得到了正确答案，不过有几步老师没太看清："
                    "挑一步，把你当时的想法说给老师听听。"
                )
    return {
        "submission_id": submission.id,
        "question_id": submission.question_id,
        "status": submission.status,
        "first_error_seq": first_error_seq,
        "steps": [{"seq": s.seq, "text": s.text, "status": s.status} for s in steps],
        "errors": [present_error(e, db, steps_by_id.get(e.step_id)) for e in errors],
        "follow_up_question": follow_up_question,
    }, pc
