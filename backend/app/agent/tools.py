# Agent 工具集：按学生身份查个人数据，并将学生明确提供的数学作答接入现有诊断管线。
# 学生身份（db 会话 + student 对象）在建工具时以闭包注入，模型无法传 user_id，
# 从根本上杜绝越权查询他人数据。工具返回值是给模型看的紧凑文本摘要，不塞原始 JSON。
from typing import List

from langchain_core.tools import tool
from sqlalchemy.orm import Session

from datetime import datetime

from ..models import (
    Assignment,
    Correction,
    Error,
    Question,
    StudentMistakeArchive,
    StudentQuestionCapture,
    Submission,
    SubmissionReview,
    User,
)
from ..services import reviews as review_svc
from ..services.learning_memory import student_memory_to_text
from ..services.diagnosis import diagnose_submission
from ..services.stats import (
    knowledge_point_errors,
    student_briefing,
    student_report,
)
from ..services.related_mistakes import find_related_mistake

_STATUS_LABEL = {
    "pending": "待修复",
    "stubborn": "需要加固（反复出错）",
    "awaiting_verify": "已订正，待验证",
    "fixed": "已修复",
}


def _fmt_date(dt) -> str:
    return dt.strftime("%Y-%m-%d") if dt else ""


def briefing_to_text(briefing: dict) -> str:
    """把 student_briefing 的结构化结果压成一段紧凑文本（工具与上下文注入共用）。"""
    lines = []
    pending = briefing.get("pending_assignments", [])
    if pending:
        desc = "；".join(
            f"《{p['title']}》（还剩 {p['remaining_count']} 题未做）" for p in pending
        )
        lines.append(f"未完成的作业 {len(pending)} 份：{desc}")
    else:
        lines.append("作业都已完成，没有未完成的作业。")
    corr_n = briefing.get("pending_corrections_count", 0)
    if corr_n:
        kps = "、".join(briefing.get("pending_corrections_knowledge_points", []))
        lines.append(f"有 {corr_n} 处错题还没订正，涉及知识点：{kps}。")
    weak = briefing.get("weak_points", [])
    if weak:
        lines.append(f"需要加固的知识点：{'、'.join(weak)}。")
    recent = briefing.get("recent_feedback")
    if recent:
        lines.append(f"最近动态：{recent}")
    return "\n".join(lines)


def report_to_text(report: List[dict]) -> str:
    """把 student_report 压成紧凑文本：按科目给提交/正确率，知识点按错误率列出。"""
    if not report:
        return "还没有任何作答记录，暂时没有学习报告数据。"
    lines = []
    for subj in report:
        lines.append(
            f"科目 {subj['subject']}：累计提交 {subj['submission_count']} 次，"
            f"正确率约 {round(subj['correct_rate'] * 100)}%，"
            f"待修复知识点 {subj['pending_fix_count']} 个，修复进度 {round(subj['fixed_ratio'] * 100)}%。"
        )
        for kp in subj["knowledge_points"]:
            lines.append(
                f"- 知识点「{kp['name']}」：提交 {kp['attempts']} 次、出错 {kp['error_count']} 次"
                f"（错误率 {round(kp['error_rate'] * 100)}%），状态：{_STATUS_LABEL.get(kp['status'], kp['status'])}"
                f"，最近出错 {_fmt_date(kp['last_error_at'])}。"
            )
        if not subj["knowledge_points"]:
            lines.append("- 暂无错题记录。")
    return "\n".join(lines)


def kp_errors_to_text(knowledge_point: str, items: List[dict]) -> str:
    """知识点错题时间线压成紧凑文本（最多 10 条）。"""
    if not items:
        return f"在「{knowledge_point}」下还没有错题记录。"
    lines = [f"「{knowledge_point}」的错题记录（共 {len(items)} 条，最近的在前）："]
    for it in items[:10]:
        seq = f"，第 {it['first_error_seq']} 步出错" if it.get("first_error_seq") is not None else ""
        corr = "已订正" if it.get("corrected") else "未订正"
        lines.append(
            f"- {_fmt_date(it['created_at'])} 《{it['assignment_title']}》{it['question_prompt']}"
            f"{seq}，问题类型：{it['error_type']}，{corr}。"
        )
    return "\n".join(lines)


def student_notebook_to_text(db: Session, student: User, limit: int = 12) -> str:
    """读取该学生当前错题和自主收录，明确区分系统判定与待教师复核。"""
    rows = (
        db.query(
            Error,
            Question.subject,
            Question.stem,
            Assignment.title,
            SubmissionReview.status,
        )
        .join(Submission, Submission.id == Error.submission_id)
        .join(Question, Question.id == Submission.question_id)
        .join(Assignment, Assignment.id == Question.assignment_id)
        .outerjoin(
            SubmissionReview,
            SubmissionReview.submission_id == Submission.id,
        )
        .outerjoin(
            StudentMistakeArchive,
            (StudentMistakeArchive.error_id == Error.id)
            & (StudentMistakeArchive.student_id == student.id),
        )
        .filter(
            Submission.student_id == student.id,
            StudentMistakeArchive.archived_at.is_(None),
        )
        .order_by(Error.created_at.desc(), Error.id.desc())
        .limit(limit)
        .all()
    )
    lines = []
    for error, subject, stem, assignment_title, review_status in rows:
        latest_correction = db.query(Correction).filter(
            Correction.error_id == error.id,
            Correction.student_id == student.id,
        ).order_by(Correction.submitted_at.desc(), Correction.id.desc()).first()
        correction_status = (
            "尚未订正" if latest_correction is None
            else "最近订正正确" if latest_correction.is_correct is True
            else "最近订正仍需修改" if latest_correction.is_correct is False
            else "订正已提交，结果待确认"
        )
        review_label = "待教师审核" if review_status == review_svc.PENDING else "系统批改记录"
        lines.append(
            f"- [{review_label}] {subject} / {error.knowledge_point}，"
            f"作业《{assignment_title}》，题目：{stem}；错因：{error.error_type}；"
            f"{correction_status}；记录日期：{_fmt_date(error.created_at)}。"
        )

    captures = db.query(StudentQuestionCapture).filter(
        StudentQuestionCapture.student_id == student.id,
        StudentQuestionCapture.saved_at.isnot(None),
        StudentQuestionCapture.archived_at.is_(None),
    ).order_by(
        StudentQuestionCapture.created_at.desc(),
        StudentQuestionCapture.id.desc(),
    ).limit(5).all()
    lines.extend(
        f"- [自主收录，未判定为答错] {capture.subject}：{capture.question_text[:180]}。"
        for capture in captures
    )
    if not lines:
        return "错题本目前没有未归档的批改错题或自主收录记录。"
    return "学生当前错题本记录（最近记录优先；待审核条目是暂定判断）：\n" + "\n".join(lines)


def build_tools(db: Session, student: User) -> tuple[list, dict]:
    """按当前学生构造工具列表（身份闭包注入）。"""
    related_result: dict = {"mistake": None}
    text_diagnosis_result: dict = {"summary": None}
    text_capture_result: dict = {"summary": None}

    def save_text_capture(question_text: str, subject: str,
                          knowledge_point: str = "", explanation: str = "") -> str:
        """持久化学生主动收录的文字题目；同轮重复调用保持幂等。"""
        if text_capture_result["summary"] is not None:
            return text_capture_result["summary"]
        stem = (question_text or "").strip()[:12000]
        if not stem:
            return "题目内容为空，没有加入错题本。"
        normalized_subject = (subject or "math").strip()[:32] or "math"
        capture = StudentQuestionCapture(
            student_id=student.id,
            subject=normalized_subject,
            question_text=stem,
            image_path="",
            explanation=(explanation or "").strip()[:2000] or None,
            saved_at=datetime.now(),
        )
        db.add(capture)
        db.commit()
        text_capture_result["summary"] = (
            "这道题已按你的要求加入错题本，可以在错题本的自主收录题目中查看。"
        )

        kp = (knowledge_point or "").strip()[:64]
        if kp:
            related_result["mistake"] = find_related_mistake(
                db, student.id, normalized_subject, kp
            )
        return text_capture_result["summary"]

    @tool
    def get_my_briefing() -> str:
        """查询学生当前的待办情况：未完成的作业、还没订正的错题数、需要加固的知识点。当学生问"我还有什么没做""作业做完了吗"之类的问题时调用。"""
        # 待审分数照常展示；待办和错题统计直接读取本人当前记录。
        return briefing_to_text(student_briefing(db, student, visible_only=True))

    @tool
    def get_my_report() -> str:
        """查询学生的学习报告摘要：各科目提交次数、正确率，以及每个知识点的错误率和状态（待修复/需要加固/已订正待验证/已修复）。当学生问"我学得怎么样""哪个知识点最弱"时调用。"""
        report = student_report(db, student, visible_only=False)
        text = report_to_text(report)
        pending_count = db.query(SubmissionReview.submission_id).join(
            Submission, Submission.id == SubmissionReview.submission_id,
        ).filter(
            Submission.student_id == student.id,
            SubmissionReview.status == review_svc.PENDING,
        ).count()
        if pending_count:
            text = (
                f"有 {pending_count} 条作答记录仍待教师审核，相关错因是暂定诊断；"
                "下面统计包含这些记录，教师改判后会同步更新。\n" + text
            )
        if not report:
            text += "\n" + student_notebook_to_text(db, student)
        return text

    @tool
    def get_my_mistake_notebook() -> str:
        """直接读取学生本人错题本与订正状态，包括待教师审核条目和自主收录题。
        学生询问具体错题、错因、订正进度或最薄弱知识点时调用；待审核诊断必须说明是暂定判断。"""
        return student_notebook_to_text(db, student)

    @tool
    def get_my_learning_memory() -> str:
        """读取从本人错题、订正和变式验证沉淀的学科知识点状态。
        学生问长期薄弱点、哪些知识点已经掌握或学习变化时调用；教师审核中的暂定错因不会作为已确认记忆。"""
        return student_memory_to_text(db, student.id)

    @tool
    def get_knowledge_point_errors(knowledge_point: str) -> str:
        """查询学生在某个知识点下的错题时间线。参数 knowledge_point 是知识点名称，例如「一元一次方程」。当学生问"我在某个知识点错过哪些题"时调用。"""
        items = knowledge_point_errors(db, student, knowledge_point, visible_only=False)
        return kp_errors_to_text(knowledge_point, items)

    @tool
    def find_my_related_mistake(subject: str, knowledge_point: str) -> str:
        """查找学生过去在这个学科和知识点做错的最近一道题，供回看历史作业。
        学生只发来题目、没有自己的作答步骤并需要解题或讲解时，识别学科（math 或 english）和知识点后调用一次；
        学生已经给出数学作答过程时改用 diagnose_student_text_work，不要与该工具同轮调用；
        普通闲聊或查询学习报告时不要调用。"""
        match = find_related_mistake(
            db, student.id, subject, knowledge_point
        )
        if match is not None:
            related_result["mistake"] = match
        if match is None:
            return f"该学生以前没有在「{subject} / {knowledge_point}」相关作业中留下可回看的错题。"
        return (
            f"找到一条历史错题：作业《{match['assignment_title']}》，题目："
            f"{match['question_stem']}；错因：{match['error_type']}。"
            "回答当前题目时可提醒学生有同类错题可回看。"
        )

    @tool
    def save_student_text_question(question_text: str, subject: str,
                                   knowledge_point: str = "") -> str:
        """将学生明确要求收录的纯文字题目加入其错题本。
        subject 使用 math、english 等学科标识。仅在学生明确要求加入、收藏或保存时调用；
        不得因学生只问答案而收录。"""
        return save_text_capture(question_text, subject, knowledge_point)

    @tool
    def diagnose_student_text_work(question_stem: str, steps: List[str],
                                   knowledge_point: str,
                                   save_to_mistakes: bool = False) -> str:
        """诊断学生在聊天消息中明确写出的数学题目和本人作答步骤。
        学生只要给出具体题干和至少一步本人作答就调用，不要求其额外说“检查”；
        只有题目、没有本人作答时不要调用。save_to_mistakes 仅在学生明确要求收录时设为 true。
        此工具会保存一次提交，重复调用同轮只使用首次结果。"""
        if text_diagnosis_result["summary"] is not None:
            return text_diagnosis_result["summary"]
        stem = (question_stem or "").strip()[:12000]
        student_steps = [str(step).strip()[:2000] for step in (steps or []) if str(step).strip()]
        if not stem or not student_steps or len(student_steps) > 20:
            return "没有足够的题干和作答步骤，未创建提交记录。"

        kp = (knowledge_point or "").strip()[:64] or "自主输入题"
        related_result["mistake"] = find_related_mistake(db, student.id, "math", kp)
        assignment = Assignment(
            title=f"学习助手文本题目 · {datetime.now():%Y-%m-%d %H:%M}",
            description="学生在学习助手中提交的数学作答。",
            created_by=student.id,
        )
        question = Question(
            assignment=assignment,
            subject="math",
            knowledge_point=kp,
            stem=stem,
            order_num=1,
        )

        submission, _, errors = diagnose_submission(db, student, question, student_steps)
        pending = review_svc.create_review_if_needed(db, submission) is not None
        if pending:
            summary = (
                "整份作业得分低于 60 分，错题已同步加入错题本和订正流程，并提交教师复核；"
                "请继续回答学生的问题，可以说明错因目前待老师复核，老师调整后记录会同步更新。"
            )
        elif errors:
            summary = "批改发现作答错误，错题已加入错题本并进入订正流程。"
        else:
            if save_to_mistakes:
                summary = save_text_capture(
                    stem, "math", kp,
                    "学习助手已检查这份作答，未发现错误；按学生要求收录复习。",
                )
                summary = "检查后作答正确；" + summary
            else:
                summary = "检查后作答正确，没有创建错题记录。"
        text_diagnosis_result["summary"] = summary
        text_diagnosis_result["submission_id"] = submission.id
        return summary

    return [get_my_briefing, get_my_report, get_my_mistake_notebook,
            get_my_learning_memory,
            get_knowledge_point_errors,
            find_my_related_mistake, save_student_text_question,
            diagnose_student_text_work], related_result
