# Agent 工具集：按学生身份查个人数据，并将各学科文字作答接入统一诊断管线。
# 学生身份（db 会话 + student 对象）在建工具时以闭包注入，模型无法传 user_id，
# 从根本上杜绝越权查询他人数据。工具返回值是给模型看的紧凑文本摘要，不塞原始 JSON。
from typing import List, Literal

from langchain_core.tools import tool
from sqlalchemy.orm import Session

from datetime import datetime

from ..models import (
    Assignment,
    AssignmentClass,
    ClassroomMember,
    ClassroomTeacherSubject,
    Correction,
    Error,
    Question,
    Step,
    StudentMistakeArchive,
    StudentQuestionCapture,
    Submission,
    SubmissionReview,
    User,
)
from ..services import reviews as review_svc
from ..services.learning_memory import student_memory_to_text
from ..services.diagnosis import diagnose_visual_submission
from ..services.providers import get_provider
from ..services.scoring import compute_ai_score
from ..services.stats import (
    knowledge_point_errors,
    student_briefing,
    student_report,
)
from ..services.related_mistakes import find_related_mistake
from .subjects import SUBJECT_AGENTS, build_subject_context, normalize_subject

_STATUS_LABEL = {
    "pending": "待修复",
    "stubborn": "需要加固（反复出错）",
    "awaiting_verify": "已订正，待验证",
    "fixed": "已修复",
}


def _fmt_date(dt) -> str:
    return dt.strftime("%Y-%m-%d") if dt else ""


def _compact_text(value: str | None, limit: int) -> str:
    return " ".join((value or "").split())[:limit]


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
        line = (
            f"- {_fmt_date(it['created_at'])} 《{it['assignment_title']}》"
            f"题目：{_compact_text(it.get('question_prompt'), 320)}{seq}，"
        )
        if it.get("student_step_text"):
            line += f"学生作答：{_compact_text(it['student_step_text'], 320)}；"
        line += f"问题类型：{it['error_type']}；"
        if it.get("detail"):
            line += f"诊断：{_compact_text(it['detail'], 360)}；"
        lines.append(f"{line}{corr}。")
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
            Step.seq,
            Step.text,
        )
        .join(Submission, Submission.id == Error.submission_id)
        .join(Question, Question.id == Submission.question_id)
        .join(Assignment, Assignment.id == Question.assignment_id)
        .outerjoin(Step, Step.id == Error.step_id)
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
    for error, subject, stem, assignment_title, review_status, step_seq, step_text in rows:
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
        line = (
            f"- [{review_label}] {subject} / {error.knowledge_point}，"
            f"作业《{assignment_title}》，题目：{_compact_text(stem, 320)}；"
        )
        if step_text:
            step_label = step_seq if step_seq is not None else "?"
            line += f"学生第 {step_label} 步作答：{_compact_text(step_text, 320)}；"
        line += f"错因：{error.error_type}；"
        if error.detail:
            line += f"诊断：{_compact_text(error.detail, 360)}；"
        line += f"{correction_status}；记录日期：{_fmt_date(error.created_at)}。"
        lines.append(line)

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


def build_tools(db: Session, student: User, *, routed_subject: str | None = None,
                subject_context: str = "") -> tuple[list, dict]:
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
        normalized_subject = normalize_subject(subject)
        if not normalized_subject:
            return "还不能确定这道题的学科，请告诉我学科后再加入错题本。"
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
        """读取学生本人错题本与订正状态，包括题目、学生出错步骤、诊断说明、待审核条目和自主收录题。
        学生询问具体错题、错因、订正进度或薄弱知识点时调用；待审核诊断必须说明是暂定判断。"""
        return student_notebook_to_text(db, student)

    @tool
    def get_my_learning_memory() -> str:
        """读取从本人错题、订正和变式验证沉淀的学科知识点状态。
        学生问长期薄弱点、哪些知识点已经掌握或学习变化时调用；教师审核中的暂定错因不会作为已确认记忆。"""
        return student_memory_to_text(db, student.id)

    @tool
    def get_knowledge_point_errors(knowledge_point: str) -> str:
        """查询学生在某个知识点下的错题时间线，包括题目、本人作答步骤和诊断说明。
        参数 knowledge_point 是知识点名称，例如「一元一次方程」。当学生问某知识点的具体错题时调用。"""
        items = knowledge_point_errors(
            db, student, knowledge_point,
            visible_only=False, include_archived=False,
        )
        return kp_errors_to_text(knowledge_point, items)

    @tool
    def find_my_related_mistake(subject: str, knowledge_point: str) -> str:
        """查找学生过去在这个学科和知识点做错的最近一道题，供回看历史作业。
        学生只发来题目、没有自己的作答并需要解题或讲解时，识别学科和知识点后调用一次；
        学生已经给出本人作答时改用 diagnose_student_text_work，不要与该工具同轮调用；
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
        subject 使用九个学科代码或对应中文学科名称。仅在学生明确要求加入、收藏或保存时调用；
        不得因学生只问答案而收录。"""
        return save_text_capture(question_text, subject, knowledge_point)

    @tool
    def diagnose_student_text_work(
        subject: Literal[
            "chinese", "math", "english", "politics", "history", "physics",
            "chemistry", "geography", "biology",
        ],
        question_stem: str,
        steps: List[str],
        knowledge_point: str = "",
        save_to_mistakes: bool = False,
    ) -> str:
        """调用对应学科 Agent 批改学生在聊天中写出的作答。
        数学步骤、语文/英语作文与默写、其他学科文字作答都适用；只要明确是学生本人作答就调用，
        不要求其额外说“检查”。不要把纯题目、题目自带答案、引用的解法或老师批注当成学生作答；
        只有题目、没有本人作答时不要调用。save_to_mistakes 仅在学生明确要求收录时设为 true。
        此工具会调用专属学科批改 Agent、保存评分和错题，并按低于 60 分的规则进入教师审核；
        重复调用同轮只使用首次结果。"""
        if text_diagnosis_result["summary"] is not None:
            return text_diagnosis_result["summary"]
        stem = (question_stem or "").strip()[:12000]
        student_steps = [str(step).strip()[:2000] for step in (steps or []) if str(step).strip()]
        normalized_subject = normalize_subject(subject)
        if not normalized_subject:
            return "暂时无法确定作答学科，请先确认学科后再批改。"
        if not stem or not student_steps or len(student_steps) > 20:
            return "没有足够的题干和作答步骤，未创建提交记录。"

        grading_context = subject_context
        if normalize_subject(routed_subject) != normalized_subject or not grading_context:
            grading_context = build_subject_context(
                db, normalized_subject, f"{stem}\n" + "\n".join(student_steps),
            )
        grade = get_provider().diagnose_homework_text(
            subject=normalized_subject,
            question_text=stem,
            student_work=student_steps,
            knowledge_context=grading_context,
        )
        graded_steps = grade.get("steps") or []
        if not grade.get("student_work_detected") or not graded_steps:
            if save_to_mistakes:
                return save_text_capture(
                    stem, normalized_subject, knowledge_point,
                    "已收到你的收录请求，但暂未识别到本人作答；这条记录未判定为答错。",
                )
            return "暂时没有识别到明确的本人作答，所以没有生成批改记录；请补充题目或作答内容。"

        subject_name = SUBJECT_AGENTS[normalized_subject][0]
        kp = (
            (knowledge_point or "").strip()
            or str(grade.get("knowledge_point") or "").strip()
        )[:64] or "自主输入题"
        related_result["mistake"] = find_related_mistake(
            db, student.id, normalized_subject, kp,
        )
        assignment = Assignment(
            title=f"学习助手文字批改 · {subject_name} · {datetime.now():%Y-%m-%d %H:%M}",
            description=f"学生在学习助手中提交的{subject_name}文字作答。",
            # 不归属为教师发布的正式作业；通过学科班级映射提供给对应任课老师审核。
            created_by=None,
        )
        db.add(assignment)
        db.flush()
        teacher_class_ids = [row[0] for row in db.query(
            ClassroomMember.classroom_id,
        ).join(
            ClassroomTeacherSubject,
            ClassroomTeacherSubject.classroom_id == ClassroomMember.classroom_id,
        ).filter(
            ClassroomMember.student_id == student.id,
            ClassroomTeacherSubject.subject == normalized_subject,
        ).distinct().all()]
        db.add_all(
            AssignmentClass(assignment_id=assignment.id, classroom_id=classroom_id)
            for classroom_id in teacher_class_ids
        )
        question = Question(
            assignment=assignment,
            subject=normalized_subject,
            knowledge_point=kp,
            stem=stem,
            order_num=1,
        )

        submission, _, errors = diagnose_visual_submission(
            db, student, question, graded_steps,
        )
        score = compute_ai_score(db, submission)["ai_score"]
        pending = review_svc.create_review_if_needed(db, submission) is not None
        correct_count = sum(1 for item in graded_steps if item.get("result") == "correct")
        total_count = sum(
            1 for item in graded_steps
            if item.get("result") in {"correct", "incorrect", "uncertain"}
        )
        lines = [
            f"{subject_name} Agent 已完成批改：本次 AI 评分 {score:.1f}/100 "
            f"（{correct_count}/{total_count} 项正确）。"
        ]
        if pending:
            if teacher_class_ids:
                lines.append(
                    "本次得分低于 60 分，错题已同步进入错题本和订正流程，并进入对应学科任课教师审核；"
                    "错因目前是暂定诊断，教师改判后会同步更新。"
                )
            else:
                lines.append(
                    "本次得分低于 60 分，错题已进入错题本和订正流程，并标记为待教师审核；"
                    "但该学生目前没有关联的本学科任课班级，教师端暂时无法收到审核项。"
                )
        elif errors:
            lines.append("发现的错误已加入错题本并进入订正流程。")
        else:
            if save_to_mistakes:
                lines.append(save_text_capture(
                    stem, normalized_subject, kp,
                    "学习助手已检查这份作答，未发现错误；按学生要求收录复习。",
                ))
            else:
                lines.append("没有发现错误，因此没有新增错题记录。")
        for item in graded_steps:
            if item.get("result") != "correct":
                lines.append(
                    f"- 学生作答「{str(item.get('text') or '')[:180]}」："
                    f"{str(item.get('detail') or '建议结合题目重新核对。')[:500]}"
                )
        feedback = str(grade.get("feedback") or "").strip()
        if feedback:
            lines.append("学科 Agent 的订正讲解：" + feedback)
        summary = "\n".join(lines)
        text_diagnosis_result["summary"] = summary
        text_diagnosis_result["submission_id"] = submission.id
        return summary

    return [get_my_briefing, get_my_report, get_my_mistake_notebook,
            get_my_learning_memory,
            get_knowledge_point_errors,
            find_my_related_mistake, save_student_text_question,
            diagnose_student_text_work], related_result
