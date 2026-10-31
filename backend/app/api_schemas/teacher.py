"""Public request and response models for the teacher API domain."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .base import QuestionOut, UserOut
from .diagram import FigureSpec
from .student import DiagnosisOut


class TeacherErrorItem(BaseModel):
    id: int
    # v0.9.0 新增（只加字段）：所属提交 id 与其审核状态（pending 时批改列表打「待审核」标）
    submission_id: int = 0
    review_status: str = "approved"
    # 评分系统新增（只加字段）：所属提交的最终分与本题满分；仅审核通过后有值
    score: Optional[float] = None
    max_score: Optional[float] = None
    student: UserOut
    question: QuestionOut
    step_seq: Optional[int] = None
    step_text: Optional[str] = None
    knowledge_point: str
    error_type: str
    confidence: float
    is_stubborn: bool
    detail: Optional[str] = None
    teacher_corrected: bool
    teacher_note: Optional[str] = None
    created_at: datetime

class ErrorCorrectIn(BaseModel):
    error_type: str = Field(pattern="^(计算失误|概念混淆|审题遗漏|无法解析)$")
    teacher_note: Optional[str] = Field(default=None, max_length=1000)

class TopQuestionItem(BaseModel):
    question_id: int
    stem: str
    subject: str
    knowledge_point: str
    error_count: int
    student_count: int

class KnowledgePointRankItem(BaseModel):
    subject: str
    knowledge_point: str
    submissions: int
    errors: int
    error_rate: float

class StudentBrief(BaseModel):
    id: int
    name: str
    student_no: Optional[str] = None
    submission_count: int
    error_count: int

class TeacherQuestionIn(BaseModel):
    type: str = Field(pattern="^(math|essay)$")
    subject: Optional[str] = Field(
        default=None,
        pattern="^(math|english|english_exercise|physics|chemistry|biology|chinese|history|geography|politics|computer_science|art|music|pe|other)$",
    )
    prompt: str = Field(min_length=1, max_length=2000)          # 题干
    # 发布不等待异步知识点识别；空值表示尚未归类。
    knowledge_point: str = Field(default="", max_length=64)
    standard_steps: Optional[List[str]] = Field(default=None, max_length=30)  # 标准解题步骤（参考）
    reference_answer: Optional[str] = Field(default=None, max_length=2000)    # 参考答案
    # 评分系统新增（只加可选字段）：该题分值占比 %（占作业总分的百分比）；不传 = 按题数均分
    weight_pct: Optional[float] = Field(default=None, ge=0, le=100)
    # v0.13.1 新增（只加可选字段）：所属大题的客户端临时 key（与 groups[].key 对应），普通题为 None
    group_key: Optional[str] = Field(default=None, max_length=32)

class QuestionGroupIn(BaseModel):
    """大题入参（v0.13.1）：key 是发布请求内的临时标识，小题用 group_key 挂靠。"""
    key: str = Field(min_length=1, max_length=32)
    stem: str = Field(min_length=1, max_length=4000)            # 大题共享题干
    diagram: Optional[FigureSpec] = None

class TeacherAssignmentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=128)
    subject: Optional[str] = Field(
        default=None,
        pattern="^(math|english|english_exercise|physics|chemistry|biology|chinese|history|geography|politics|computer_science|art|music|pe|other)$",
    )
    description: Optional[str] = Field(default=None, max_length=2000)
    questions: List[TeacherQuestionIn] = Field(min_length=1, max_length=50)
    # v0.5.0 新增（只加可选字段）：发布模式。mode=offline 时把后三项写进 assignment_ext
    mode: str = Field(default="online", pattern="^(online|offline)$")
    workbook_id: Optional[int] = None                       # 关联练习册知识库中的一本（须为本人上传）
    page_range: Optional[str] = Field(default=None, max_length=64)   # 如「第12-14页 第1-8题」
    deadline: Optional[datetime] = None                     # 截止时间（ISO 8601）
    # 评分系统新增（只加可选字段）：作业总分（满分）；不传 = 100
    total_score: Optional[float] = Field(default=None, gt=0, le=10000)
    # v0.13.1 新增（只加可选字段）：允许学生截止前修改作答（开启后延迟到截止统一批改）
    allow_revision: bool = False
    # v0.13.1 新增（只加可选字段）：大题列表（小题经 group_key 挂靠）
    groups: List[QuestionGroupIn] = Field(default_factory=list, max_length=20)
    # 新建作业必须选择目标班级，防止新作业被所有学生默认看见。
    class_ids: List[int] = Field(default_factory=list, max_length=100)

class TeacherAssignmentQuestionOut(BaseModel):
    id: int
    type: str                     # math | essay（由题目 subject 映射）
    subject: str                  # v0.13.23：题目实际学科代码
    prompt: str                   # 题干
    knowledge_point: str
    standard_answer: Optional[str] = None
    submission_count: int         # 该题累计提交人数（含作文提交）
    # 评分系统新增（只加字段）：该题分值占比 %（生效值：配置值或均分）
    weight_pct: Optional[float] = None

class TeacherAssignmentOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    created_at: datetime
    questions: List[TeacherAssignmentQuestionOut]
    # v0.5.0 新增（只加字段）：发布模式与线下作业信息
    mode: str = "online"
    workbook_title: Optional[str] = None
    page_range: Optional[str] = None
    deadline: Optional[datetime] = None
    # 评分系统新增（只加字段）：作业总分（生效值：配置值或默认 100）
    total_score: float = 100.0
    # v0.13.1 新增（只加字段）：允许修改开关
    allow_revision: bool = False
    class_ids: List[int] = Field(default_factory=list)
    can_delete: bool = False

class ClassroomCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    subject: str = Field(
        pattern="^(chinese|math|english|politics|history|physics|chemistry|geography|biology)$",
    )

class ClassroomStudentCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    student_no: str = Field(min_length=1, max_length=32)

class ClassroomStudentOut(BaseModel):
    id: int
    name: str
    student_no: str

class ClassroomOut(BaseModel):
    id: int
    name: str
    subjects: List[str] = Field(default_factory=list)
    student_count: int = 0

class SubjectKnowledgeCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=20000)
    source_name: Optional[str] = Field(default=None, max_length=200)

class SubjectKnowledgeSearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=4, ge=1, le=8)

class WorkbookOut(BaseModel):
    id: int
    title: str
    file_url: str                 # /api/uploads/workbooks/<文件名>，可直接打开 PDF
    cover_url: Optional[str] = None  # v0.6.0 新增：PDF 首页封面图（/api/uploads/covers/<id>.jpg），无封面为 null
    created_at: datetime

class WorkbookExtractIn(BaseModel):
    page_range: str = Field(
        min_length=1,
        max_length=64,
        description="页码范围原文，如「第 12-14 页 第 1-8 题」",
    )

class ExtractedQuestionOut(BaseModel):
    prompt: str                   # 识别出的题干（草稿，教师检查修改后才发布）
    knowledge_point: str = ""     # 模型给的知识点猜测，可空
    source_page: int              # 来源页（1-based）

class WorkbookExtractOut(BaseModel):
    pages: List[int]              # 实际识别的页号（1-based，已按 PDF 页数夹紧）
    questions: List[ExtractedQuestionOut]
    warnings: List[str] = []      # 逐页提示（如某页没识别到题目）

class RemindOut(BaseModel):
    reminded_count: int           # 本次实际写入提醒的学生数

class KnowledgePointRepairItem(BaseModel):
    subject: str
    knowledge_point: str
    students_errored: int         # 在该学科知识点出过错的学生数
    students_fixed: int           # 其中已修复（订正+通过验证）的学生数
    repair_rate: float            # students_fixed / students_errored

class ClassRepairRateOut(BaseModel):
    class_repair_rate: float                 # 已修复（学生×学科×知识点）/ 出过错组合
    students_with_errors: int                # 有过错题的学生数
    total_knowledge_point_pairs: int         # 出过错的（学生, 学科, 知识点）组合数
    fixed_knowledge_point_pairs: int         # 其中已修复的组合数
    knowledge_points: List[KnowledgePointRepairItem]

class ErrorTypeCountOut(BaseModel):
    name: str
    value: int

class TeachingSuggestionOut(BaseModel):
    kind: str
    title: str
    subject: Optional[str] = None
    knowledge_point: Optional[str] = None
    evidence: str
    action: str
    sample_questions: List[str] = Field(default_factory=list)

class TeacherDashboardOut(BaseModel):
    top_questions: List[TopQuestionItem]
    knowledge_points: List[KnowledgePointRankItem]
    students: List[StudentBrief]
    total_errors: int
    stubborn_errors: int
    graded_submissions: int
    graded_submissions_with_errors: int
    repair_rate: Optional[ClassRepairRateOut] = None
    recent_error_types: List[ErrorTypeCountOut]
    suggestions: Optional[List[TeachingSuggestionOut]] = None

class ReviewPendingItem(BaseModel):
    submission_id: int
    student: UserOut
    assignment_id: Optional[int] = None
    assignment_title: str = ""
    question_id: int
    question_stem: str
    subject: str
    knowledge_point: str
    error_count: int            # 该提交的 AI 诊断错误数（教师端可见）
    correct_steps: int = 0      # 评分口径：正确的学生作答步骤数
    total_steps: int = 0        # 评分口径：学生作答步骤总数
    assignment_correct_steps: int = 0  # 该学生本作业各题最新提交的正确步骤数
    assignment_total_steps: int = 0    # 该学生本作业各题最新提交的步骤总数
    review_reason: str = ""    # 触发教师复核的置信度/正确率原因
    submitted_at: datetime
    image_url: Optional[str] = None  # 学生上传的作答原图（如有）
    image_name: Optional[str] = None  # 原图文件名

class ReviewPendingOut(BaseModel):
    count: int                  # 待审核总数（导航角标用）
    items: List[ReviewPendingItem]
    latest_submission_id: Optional[int] = None  # 队列变更快照，供审核页轻量轮询

class ReviewPendingCountOut(BaseModel):
    count: int                  # 待审核总数（轻量导航角标接口）
    latest_submission_id: Optional[int] = None  # 最新待审提交 ID；空队列为 None

class ReviewScoreOut(BaseModel):
    """审核详情的评分信息（评分系统新增）：老师据此核对 AI 分、决定是否改分。"""
    question_max: float           # 本题满分 = 作业总分 × 分值占比
    ai_score: Optional[float] = None      # AI 初评分（按步骤对错折算）
    final_score: Optional[float] = None   # 已落定的最终分（未审核为 None）
    ok_steps: int                 # 正确步骤数
    total_steps: int              # 作答步骤总数

class ProcessCheckSignalOut(BaseModel):
    """过程可疑识别的一条信号（仅教师端可见）。"""
    code: str                   # broken_chain | leap | unparseable_heavy
    text: str                   # 给老师看的中文原因

class ProcessCheckOut(BaseModel):
    """过程可疑识别结果（仅教师端）：答案对但过程存疑时 suspicious=True。
    学生端任何出参都不含本结构与 suspicious 等字段。"""
    suspicious: bool = False
    signals: List[ProcessCheckSignalOut] = []
    final_answer: Optional[str] = None      # 学生最终答案（格式化文本）
    reference_answer: Optional[str] = None  # sympy 解题干得到的参考解

class ReviewDetailOut(BaseModel):
    submission_id: int
    student: UserOut
    assignment_title: str = ""
    question: QuestionOut
    submitted_at: datetime
    review_status: str          # pending | approved
    diagnosis: DiagnosisOut     # 完整分步诊断（教师端全量，含 review_status）
    # 评分系统新增（只加字段）：本题评分信息（满分/AI 分/步骤对了几步）
    score: Optional[ReviewScoreOut] = None
    # 过程可疑识别（只加字段）：答案对、过程存疑的确定性信号，供教师审核参考
    process_check: Optional[ProcessCheckOut] = None

class ReviewApproveIn(BaseModel):
    """审核通过入参（评分系统新增，整个 body 可选）：带 final_score = 老师改分后通过。"""
    final_score: Optional[float] = Field(default=None, ge=0)

class ReviewApproveOut(BaseModel):
    submission_id: int
    review_status: str          # approved

class ReviewApproveAllOut(BaseModel):
    approved_count: int         # 本次通过的条数

__all__ = [
    'TeacherErrorItem',
    'ErrorCorrectIn',
    'TopQuestionItem',
    'KnowledgePointRankItem',
    'StudentBrief',
    'TeacherQuestionIn',
    'QuestionGroupIn',
    'TeacherAssignmentCreate',
    'TeacherAssignmentQuestionOut',
    'TeacherAssignmentOut',
    'ClassroomCreateIn',
    'ClassroomStudentCreateIn',
    'ClassroomStudentOut',
    'ClassroomOut',
    'SubjectKnowledgeCreateIn',
    'SubjectKnowledgeSearchIn',
    'WorkbookOut',
    'WorkbookExtractIn',
    'ExtractedQuestionOut',
    'WorkbookExtractOut',
    'RemindOut',
    'KnowledgePointRepairItem',
    'ClassRepairRateOut',
    'ErrorTypeCountOut',
    'TeachingSuggestionOut',
    'TeacherDashboardOut',
    'ReviewPendingItem',
    'ReviewPendingOut',
    'ReviewPendingCountOut',
    'ReviewScoreOut',
    'ProcessCheckSignalOut',
    'ProcessCheckOut',
    'ReviewDetailOut',
    'ReviewApproveIn',
    'ReviewApproveOut',
    'ReviewApproveAllOut',
]
