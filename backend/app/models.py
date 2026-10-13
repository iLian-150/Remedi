# 数据模型。列类型只用标准类型（Integer/String/Text/Float/Boolean/DateTime），
# JSON 以 TEXT 存序列化字符串 —— 与 docs/schema-design.md 一致，PostgreSQL 可直接迁移。
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), nullable=False, comment="姓名（登录用户名）")
    student_no = Column(String(32), unique=True, nullable=True, comment="学号，全局唯一；教师可为空")
    role = Column(String(16), nullable=False, comment="teacher | student")
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    submissions = relationship("Submission", back_populates="student")
    essays = relationship("Essay", back_populates="student")


class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    questions = relationship("Question", back_populates="assignment")


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        Index(
            "ix_questions_assignment_order_id",
            "assignment_id",
            "order_num",
            "id",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id"), nullable=False)
    subject = Column(String(16), nullable=False, comment="学科代码，如 math、english、physics")
    knowledge_point = Column(String(64), nullable=False, comment="知识点")
    stem = Column(Text, nullable=False, comment="题干")
    standard_answer = Column(Text, nullable=True, comment="标准答案（不下发学生端）")
    order_num = Column(Integer, nullable=False, default=0)

    assignment = relationship("Assignment", back_populates="questions")


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="submitted", comment="submitted | graded")
    submitted_at = Column(DateTime, nullable=False, default=datetime.now)

    student = relationship("User", back_populates="submissions")
    question = relationship("Question")
    steps = relationship("Step", back_populates="submission", cascade="all, delete-orphan",
                         order_by="Step.seq")
    errors = relationship("Error", back_populates="submission", cascade="all, delete-orphan")


Index(
    "ix_submissions_student_question_latest",
    Submission.student_id,
    Submission.question_id,
    Submission.submitted_at.desc(),
    Submission.id.desc(),
)
Index(
    "ix_submissions_student_submitted_latest",
    Submission.student_id,
    Submission.submitted_at.desc(),
    Submission.id.desc(),
)


class Step(Base):
    __tablename__ = "steps"
    __table_args__ = (
        Index(
            "ix_steps_submission_seq_id",
            "submission_id",
            "seq",
            "id",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    submission_id = Column(Integer, ForeignKey("submissions.id"), nullable=False)
    seq = Column(Integer, nullable=False, comment="0=题干，1..n=学生作答步骤")
    text = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, default="pending",
                    comment="stem | ok | error | unparseable | skipped")

    submission = relationship("Submission", back_populates="steps")


class Error(Base):
    __tablename__ = "errors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    submission_id = Column(Integer, ForeignKey("submissions.id"), nullable=False, index=True)
    step_id = Column(Integer, ForeignKey("steps.id"), nullable=True)
    knowledge_point = Column(String(64), nullable=False, index=True, comment="冗余自题目，便于聚合")
    error_type = Column(String(16), nullable=False, comment="按学科归类的错因，长度不超过 16")
    confidence = Column(Float, nullable=False, comment="置信度 0~1")
    is_stubborn = Column(Boolean, nullable=False, default=False, comment="顽固误区")
    teacher_corrected = Column(Boolean, nullable=False, default=False)
    teacher_note = Column(Text, nullable=True)
    detail = Column(Text, nullable=True, comment="人类可读的诊断说明")
    created_at = Column(DateTime, nullable=False, default=datetime.now, index=True)

    submission = relationship("Submission", back_populates="errors")
    step = relationship("Step")


class Correction(Base):
    __tablename__ = "corrections"
    __table_args__ = (
        Index(
            "ix_corrections_student_error_submitted",
            "student_id", "error_id", "submitted_at", "id",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    error_id = Column(Integer, ForeignKey("errors.id"), nullable=False, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False, comment="订正内容")
    is_correct = Column(Boolean, nullable=True, comment="true/false/NULL(无法判定)")
    note = Column(Text, nullable=True)
    submitted_at = Column(DateTime, nullable=False, default=datetime.now)


class Essay(Base):
    __tablename__ = "essays"
    __table_args__ = (
        Index(
            "ix_essays_student_submitted_id",
            "student_id",
            "submitted_at",
            "id",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=True, index=True)
    text = Column(Text, nullable=False, comment="作文原文")
    scores_json = Column(Text, nullable=False, comment='JSON: {content,structure,grammar,vocabulary,expression,total}')
    grammar_issues_json = Column(Text, nullable=False, comment="JSON 数组: [{sentence_no,sentence,issue,suggestion}]")
    overall_comment = Column(Text, nullable=True)
    submitted_at = Column(DateTime, nullable=False, default=datetime.now)

    student = relationship("User", back_populates="essays")


class ChatMessage(Base):
    """学生与主页 Agent 的对话记录（v0.3.0 新增表）。"""
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String(16), nullable=False, comment="user | assistant")
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class ChatSession(Base):
    """Agent 对话会话（v0.6.0 新增表）：一次「新对话」= 一条会话，
    旧会话保留在历史列表里可找回、可单独删除。标题默认「新对话」，
    第一条用户消息到达时自动改为该消息前 20 字。"""
    __tablename__ = "chat_sessions"
    __table_args__ = (
        Index(
            "ix_chat_sessions_user_updated_id",
            "user_id",
            "updated_at",
            "id",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(128), nullable=False, default="新对话")
    message_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now)


class ChatSessionMessage(Base):
    """会话内消息（v0.6.0 新增表）：与旧 chat_messages 分开存，
    上下文组装时只取当前会话的消息，会话之间互不串扰。"""
    __tablename__ = "chat_session_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id"), nullable=False)
    role = Column(String(16), nullable=False, comment="user | assistant")
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    __table_args__ = (
        Index(
            "ix_chat_session_messages_session_created_id",
            "session_id",
            "created_at",
            "id",
        ),
    )


class ChatSessionMessageImage(Base):
    """聊天用户消息关联的服务器图片；文件本体保存在 UPLOAD_DIR。"""
    __tablename__ = "chat_session_message_images"

    message_id = Column(Integer, ForeignKey("chat_session_messages.id"), primary_key=True)
    file_path = Column(String(512), nullable=False)
    file_name = Column(String(255), nullable=False)


class ChatSessionMessageMistakeLink(Base):
    """持久化助手回复关联的历史错题入口，便于重开会话后继续查看。"""
    __tablename__ = "chat_session_message_mistake_links"

    message_id = Column(Integer, ForeignKey("chat_session_messages.id"), primary_key=True)
    error_id = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class Notification(Base):
    """站内提醒（v0.3.0 新增表）：如教师一键纠错后提醒被纠错的学生。"""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False,
                     comment="接收提醒的用户")
    type = Column(String(32), nullable=False, comment="teacher_correction | ...")
    content = Column(Text, nullable=False, comment="提醒文案")
    related_submission_id = Column(
        Integer,
        ForeignKey("submissions.id"),
        nullable=True,
        index=True,
        comment="关联的提交（点提醒跳诊断报告用），可空",
    )
    is_read = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now)


Index(
    "ix_notifications_user_created_id",
    Notification.user_id,
    Notification.created_at.desc(),
    Notification.id.desc(),
)
Index(
    "ix_notifications_user_is_read",
    Notification.user_id,
    Notification.is_read,
)


class Verification(Base):
    """二次验证记录（v0.4.0 新增表）：学生订正后做一道同知识点变式题，
    通过验证才算该知识点「已修复」。variant_json 存变式题全量
    （prompt / standard_steps / answer / mode），只把 prompt 下发给学生。"""
    __tablename__ = "verifications"
    __table_args__ = (
        Index(
            "ix_verifications_student_created_id",
            "student_id", "created_at", "id",
        ),
        Index(
            "ix_verifications_student_knowledge_status_latest",
            "student_id", "knowledge_point", "status", "created_at", "id",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    knowledge_point = Column(String(64), nullable=False)
    source_error_id = Column(Integer, ForeignKey("errors.id"), nullable=True,
                             comment="触发本次验证的错题，可空")
    variant_json = Column(Text, nullable=False,
                          comment='JSON: {prompt, knowledge_point, standard_steps, answer, mode}')
    status = Column(String(16), nullable=False, default="pending",
                    comment="pending | passed | failed")
    attempts = Column(Integer, nullable=False, default=0, comment="提交作答次数")
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    completed_at = Column(DateTime, nullable=True, comment="通过时间")


Index(
    "ix_verifications_source_error_student_created_latest",
    Verification.source_error_id,
    Verification.student_id,
    Verification.created_at.desc(),
    Verification.id.desc(),
)


class StudentMistakeCategoryReview(Base):
    """学生错题本中，某份作业的某类错因是否已学习。"""
    __tablename__ = "student_mistake_category_reviews"

    student_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id"), primary_key=True)
    category_key = Column(String(256), primary_key=True)
    studied_at = Column(DateTime, nullable=False, default=datetime.now)


class StudentMistakeArchive(Base):
    """逐条保存错题本移出状态，不删除原始诊断记录。"""
    __tablename__ = "student_mistake_archives"
    __table_args__ = (
        Index("ix_student_mistake_archives_error_id", "error_id"),
    )

    student_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    error_id = Column(Integer, ForeignKey("errors.id"), primary_key=True)
    archived_at = Column(DateTime, nullable=False, default=datetime.now)


class StudentMistakeEvent(Base):
    """错题本批量移出/恢复审计记录，与参考系统的 event log 对齐。"""
    __tablename__ = "student_mistake_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    assignment_id = Column(Integer, ForeignKey("assignments.id"), nullable=False, index=True)
    event_type = Column(String(48), nullable=False)
    payload_json = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class StudentQuestionCapture(Base):
    """Student-owned photo question that is answered first and only later saved on request."""
    __tablename__ = "student_question_captures"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=True, index=True)
    subject = Column(String(32), nullable=False, default="math")
    question_text = Column(Text, nullable=False)
    image_path = Column(String(256), nullable=False)
    explanation = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    saved_at = Column(DateTime, nullable=True)
    archived_at = Column(DateTime, nullable=True)


Index(
    "ix_student_question_captures_student_created_id",
    StudentQuestionCapture.student_id,
    StudentQuestionCapture.created_at.desc(),
    StudentQuestionCapture.id.desc(),
)


class SubmissionReview(Base):
    """提交审核状态（v0.9.0 新增表）。
    待审核期间，学生仍可查看诊断、错题并开始订正；审核状态控制成绩放行和通过提醒。
    实时批改入口会创建 pending 行；服务启动时也会将尚未审核、仍为最新作答且正确率
    低于阈值的历史提交补入队列。没有审核行的其他历史/种子提交仍视为 approved。"""
    __tablename__ = "submission_reviews"
    __table_args__ = (
        Index("ix_submission_reviews_status_submission_id", "status", "submission_id"),
    )

    submission_id = Column(Integer, ForeignKey("submissions.id"), primary_key=True)
    status = Column(String(16), nullable=False, default="pending",
                    comment="pending | approved")
    reviewed_by = Column(Integer, ForeignKey("users.id"), nullable=True,
                         comment="审核教师，pending 时为空")
    reviewed_at = Column(DateTime, nullable=True, comment="审核时间")
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class Workbook(Base):
    """练习册知识库（v0.5.0 新增表）：教师上传的整本练习册 PDF，
    发布线下作业时可直接选用。file_path 为相对 UPLOAD_DIR 的路径
    （如 workbooks/xxx.pdf），经 /api/uploads/ 访问。"""
    __tablename__ = "workbooks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    teacher_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(128), nullable=False, comment="练习册名（默认取 PDF 文件名）")
    file_path = Column(String(256), nullable=False, comment="相对 UPLOAD_DIR 的文件路径")
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class AssignmentExt(Base):
    """作业扩展信息（v0.5.0 新增表）：一份作业一行，记录发布模式等附加字段。
    无 ext 行 = 线上作业（mode=online）；mode=offline 时关联练习册与页码范围。"""
    __tablename__ = "assignment_ext"

    assignment_id = Column(Integer, ForeignKey("assignments.id"), primary_key=True)
    mode = Column(String(16), nullable=False, default="online",
                  comment="online | offline（线下练习册作业）")
    workbook_id = Column(Integer, ForeignKey("workbooks.id"), nullable=True,
                         comment="线下作业关联的练习册，可空")
    page_range = Column(String(64), nullable=True, comment="页码/题号范围，如 第12-14页 第1-8题")
    deadline = Column(DateTime, nullable=True, comment="线下作业截止时间，可空")


# ---------------------------------------------------------------- 评分系统
# 全部走新表，不给任何现有表加列。无配置行时的口径：作业总分 = 100，
# 每题权重 = 100 / 题数（均分，动态计算，不回填）。

class AssignmentScoring(Base):
    """作业分值设置（评分系统新增表）：一份作业一行，老师发布时设定总分。
    无此行 = 总分按 100 计。"""
    __tablename__ = "assignment_scoring"

    assignment_id = Column(Integer, ForeignKey("assignments.id"), primary_key=True)
    total_score = Column(Float, nullable=False, default=100.0, comment="作业满分（总分）")


class QuestionWeight(Base):
    """题目分值占比（评分系统新增表）：一道题一行，weight_pct 是该题占整份
    作业总分的百分比；题目满分 = 总分 × weight_pct / 100。无此行 = 按题数均分。"""
    __tablename__ = "question_weights"

    question_id = Column(Integer, ForeignKey("questions.id"), primary_key=True)
    weight_pct = Column(Float, nullable=False, comment="分值占比 %（同作业各题合计应为 100）")


class SubmissionScore(Base):
    """提交得分（评分系统新增表）：一份提交一行。ai_score 是批改时按步骤
    对错折算的 AI 初评分；final_score 是教师审核通过时的最终分（老师可改分，
    不改则 = ai_score），审核通过前对学生的可见分一律以审核口径为准。"""
    __tablename__ = "submission_scores"

    submission_id = Column(Integer, ForeignKey("submissions.id"), primary_key=True)
    ai_score = Column(Float, nullable=False, comment="AI 初评分（按步骤得分率折算）")
    final_score = Column(Float, nullable=True, comment="最终分（审核通过时落定，老师可改）")
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True,
                        comment="最后定分/改分的教师")
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now)


class SubmissionImage(Base):
    """学生上传作答图片与对应提交的关联；图片文件保存在 UPLOAD_DIR。"""
    __tablename__ = "submission_images"

    submission_id = Column(Integer, ForeignKey("submissions.id"), primary_key=True)
    file_path = Column(String(512), nullable=False)
    file_name = Column(String(255), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now)


# ---------------------------------------------------------------- v0.13.1：提交规则 + 大题/小题

class AssignmentSetting(Base):
    """作业提交设置（v0.13.1 新增表）：一份作业一行，无行 = 全部默认。

    allow_revision=True 表示教师在发布时勾选了「允许学生修改已提交的作答」：
    截止前学生可反复修改（每次修改生成一份新的延迟提交），AI 不立即批改，
    截止时间到后按每题最后一次提交统一批改；未勾选时每道题只能提交一次。"""
    __tablename__ = "assignment_settings"

    assignment_id = Column(Integer, ForeignKey("assignments.id"), primary_key=True)
    allow_revision = Column(Boolean, nullable=False, default=False,
                            comment="是否允许截止前修改作答（开启后延迟到截止统一批改）")


class QuestionGroup(Base):
    """大题（v0.13.1 新增表）：共享题干 + 若干小题（小题仍是普通 Question 行，
    逐题作答/批改/计分不变；分组关系见 QuestionGroupMember）。"""
    __tablename__ = "question_groups"
    __table_args__ = (
        Index(
            "ix_question_groups_assignment_order_id",
            "assignment_id",
            "order_num",
            "id",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id"), nullable=False)
    stem = Column(Text, nullable=False, comment="大题共享题干（材料/背景）")
    order_num = Column(Integer, nullable=False, default=0, comment="在作业题目序列中的位置（按首个小题排序）")


class QuestionGroupMember(Base):
    """大题成员（v0.13.1 新增表）：一道小题属于一个大题。"""
    __tablename__ = "question_group_members"

    question_id = Column(Integer, ForeignKey("questions.id"), primary_key=True)
    group_id = Column(Integer, ForeignKey("question_groups.id"), nullable=False, index=True)
