# 数据模型。列类型只用标准类型（Integer/String/Text/Float/Boolean/DateTime），
# JSON 以 TEXT 存序列化字符串 —— 与 docs/schema-design.md 一致，PostgreSQL 可直接迁移。
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
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

    id = Column(Integer, primary_key=True, autoincrement=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id"), nullable=False, index=True)
    subject = Column(String(16), nullable=False, comment="math | english")
    knowledge_point = Column(String(64), nullable=False, comment="知识点")
    stem = Column(Text, nullable=False, comment="题干")
    standard_answer = Column(Text, nullable=True, comment="标准答案（不下发学生端）")
    order_num = Column(Integer, nullable=False, default=0)

    assignment = relationship("Assignment", back_populates="questions")


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False, index=True)
    status = Column(String(16), nullable=False, default="submitted", comment="submitted | graded")
    submitted_at = Column(DateTime, nullable=False, default=datetime.now)

    student = relationship("User", back_populates="submissions")
    question = relationship("Question")
    steps = relationship("Step", back_populates="submission", cascade="all, delete-orphan",
                         order_by="Step.seq")
    errors = relationship("Error", back_populates="submission", cascade="all, delete-orphan")


class Step(Base):
    __tablename__ = "steps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    submission_id = Column(Integer, ForeignKey("submissions.id"), nullable=False, index=True)
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
    error_type = Column(String(16), nullable=False, comment="计算失误 | 概念混淆 | 审题遗漏 | 无法解析")
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

    id = Column(Integer, primary_key=True, autoincrement=True)
    error_id = Column(Integer, ForeignKey("errors.id"), nullable=False, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False, comment="订正内容")
    is_correct = Column(Boolean, nullable=True, comment="true/false/NULL(无法判定)")
    note = Column(Text, nullable=True)
    submitted_at = Column(DateTime, nullable=False, default=datetime.now)


class Essay(Base):
    __tablename__ = "essays"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=True)
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


class Notification(Base):
    """站内提醒（v0.3.0 新增表）：如教师一键纠错后提醒被纠错的学生。"""
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True,
                     comment="接收提醒的用户")
    type = Column(String(32), nullable=False, comment="teacher_correction | ...")
    content = Column(Text, nullable=False, comment="提醒文案")
    related_submission_id = Column(Integer, ForeignKey("submissions.id"), nullable=True,
                                   comment="关联的提交（点提醒跳诊断报告用），可空")
    is_read = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class Verification(Base):
    """二次验证记录（v0.4.0 新增表）：学生订正后做一道同知识点变式题，
    通过验证才算该知识点「已修复」。variant_json 存变式题全量
    （prompt / standard_steps / answer / mode），只把 prompt 下发给学生。"""
    __tablename__ = "verifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    knowledge_point = Column(String(64), nullable=False, index=True)
    source_error_id = Column(Integer, ForeignKey("errors.id"), nullable=True,
                             comment="触发本次验证的错题，可空")
    variant_json = Column(Text, nullable=False,
                          comment='JSON: {prompt, knowledge_point, standard_steps, answer, mode}')
    status = Column(String(16), nullable=False, default="pending",
                    comment="pending | passed | failed")
    attempts = Column(Integer, nullable=False, default=0, comment="提交作答次数")
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    completed_at = Column(DateTime, nullable=True, comment="通过时间")


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
