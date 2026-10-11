# Pydantic 请求/响应模型。与 api-contract.md 的 JSON 示例一一对应。
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------- 通用 ----------

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    student_no: Optional[str] = None
    role: str
    created_at: Optional[datetime] = None   # v0.9.0 新增（只加字段）：学生档案黑板展示「加入时间」


class Pagination(BaseModel):
    total: int
    items: list


# ---------- 认证 ----------

class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    role: str = Field(pattern="^(teacher|student)$")


class LoginOut(BaseModel):
    token: str
    token_type: str = "bearer"
    user: UserOut


# ---------- 学生：作业 ----------

class QuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    subject: str
    knowledge_point: str
    stem: str
    order_num: int
    # v0.13.1 新增（只加字段）：所属大题 id（QuestionGroup），普通题为 None
    group_id: Optional[int] = None


class QuestionGroupOut(BaseModel):
    """大题（v0.13.1）：共享题干，成员小题见 QuestionOut.group_id。"""
    id: int
    stem: str
    order_num: int


class AssignmentBrief(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    question_count: int
    created_at: datetime
    # v0.5.0 新增（只加字段）：发布模式与线下作业信息，无 ext 行时 mode=online、其余为 null
    mode: str = "online"
    workbook_title: Optional[str] = None
    page_range: Optional[str] = None
    deadline: Optional[datetime] = None


class AssignmentDetail(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    questions: List[QuestionOut]
    # v0.5.0 新增（只加字段）：同 AssignmentBrief
    mode: str = "online"
    workbook_title: Optional[str] = None
    page_range: Optional[str] = None
    deadline: Optional[datetime] = None
    # v0.13.1 新增（只加字段）：允许修改开关 + 大题列表
    allow_revision: bool = False
    groups: List[QuestionGroupOut] = []


# ---------- 学生：数学诊断 ----------

class SubmissionCreate(BaseModel):
    question_id: int
    steps: List[str] = Field(min_length=1, max_length=20)

    # 每个步骤非空、限长
    from pydantic import field_validator

    @field_validator("steps")
    @classmethod
    def _check_steps(cls, v: List[str]) -> List[str]:
        cleaned = []
        for s in v:
            if not isinstance(s, str) or not s.strip():
                raise ValueError("每个作答步骤不能为空")
            if len(s) > 500:
                raise ValueError("单个步骤不能超过 500 字符")
            cleaned.append(s.strip())
        return cleaned


class StepOut(BaseModel):
    seq: int
    text: str
    status: str


class ErrorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    submission_id: int
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


class DiagnosisScoreOut(BaseModel):
    """学生可见分（评分系统新增，只加字段）：只在审核通过后下发。"""
    score: float        # 本题得分（最终分）
    max_score: float    # 本题满分 = 作业总分 × 分值占比
    # 该作业目前累计得分（每题最新一次已通过提交的最终分之和）与作业总分；算不出为 None
    assignment_score: Optional[float] = None
    assignment_total: Optional[float] = None


class DiagnosisOut(BaseModel):
    submission_id: int
    question_id: int
    status: str
    first_error_seq: Optional[int] = None
    steps: List[StepOut]
    errors: List[ErrorOut]
    follow_up_question: Optional[str] = None   # v0.4.0：按主错因+知识点生成的启发式追问，无错时为 None
    # v0.9.0 新增（只加字段）：教师审核状态。pending 时 status="pending_review"、
    # steps/errors 为空（诊断结论对学生不可见）；approved = 老师已审核（或历史数据默认通过）
    review_status: str = "approved"
    # 评分系统新增（只加字段）：本题得分；待审核或无分时为 None（分数跟审核一起放行）
    score: Optional[DiagnosisScoreOut] = None


class PhotoDiagnosisOut(DiagnosisOut):
    """原图批改结果；诊断主体复用分步提交结果，并附视觉识别依据。"""
    recognized_question_text: str = ""
    recognized_steps: List[str] = Field(default_factory=list)
    recognition_confidence: float = 0.0


class SubmissionBrief(BaseModel):
    id: int
    question_id: int
    question_stem: str
    knowledge_point: str
    status: str
    error_count: int
    submitted_at: datetime
    # v0.9.0 新增（只加字段）：教师审核状态 pending | approved（无审核行=历史数据=approved）；
    # pending 时 error_count 固定为 0，不向学生泄露诊断结论
    review_status: str = "approved"
    # 评分系统新增（只加字段）：本题最终分与满分；仅审核通过后下发，待审核为 None
    score: Optional[float] = None
    max_score: Optional[float] = None


class MistakeCorrectionBrief(BaseModel):
    id: int
    content: str
    is_correct: Optional[bool] = None
    note: Optional[str] = None
    submitted_at: datetime


class SimilarMistakeBrief(BaseModel):
    id: int
    submission_id: int
    assignment_id: int
    assignment_title: str
    assignment_created_at: datetime
    question_stem: str


class StudentMistakeOut(BaseModel):
    """错题本记录，附带作业分类、复习状态与历史同类错误。"""
    id: int
    submission_id: int
    question_id: int
    assignment_id: int
    assignment_title: str
    assignment_created_at: datetime
    question_subject: str
    question_order: int
    question_stem: str
    correct_answer: Optional[str] = None
    solution_steps: List[str] = Field(default_factory=list)
    knowledge_point: str
    error_type: str
    is_stubborn: bool
    detail: Optional[str] = None
    step_seq: Optional[int] = None
    step_text: Optional[str] = None
    created_at: datetime
    # v0.9.0 新增（只加字段）：错题所属提交的提交时间（订正页日历按此打点）；
    # 自主收录条目无提交，取收录时间兜底
    submitted_at: Optional[datetime] = None
    category_key: str
    category_label: str
    category_studied: bool
    archived_at: Optional[datetime] = None
    similar_occurrences: List[SimilarMistakeBrief] = Field(default_factory=list)
    latest_correction: Optional[MistakeCorrectionBrief] = None
    verification_status: Optional[str] = None
    source_kind: str = "diagnosed"
    capture_id: Optional[int] = None
    image_url: Optional[str] = None


class RelatedMistakeOut(BaseModel):
    id: int
    submission_id: int
    question_id: int
    assignment_id: int
    assignment_title: str
    assignment_created_at: datetime
    question_subject: str
    question_stem: str
    solution_steps: List[str] = Field(default_factory=list)
    knowledge_point: str
    error_type: str
    detail: Optional[str] = None
    step_seq: Optional[int] = None
    step_text: Optional[str] = None
    created_at: datetime
    latest_correction: Optional[MistakeCorrectionBrief] = None


class MistakeCategoryStudyIn(BaseModel):
    assignment_id: int
    category_key: str = Field(min_length=1, max_length=256)
    studied: bool


class MistakeAssignmentArchiveIn(BaseModel):
    archived: bool
    occurrence_ids: List[int] = Field(default_factory=list)


class MistakeArchiveIn(BaseModel):
    archived: bool


# ---------- 学生：作文 ----------

class EssayCreate(BaseModel):
    question_id: Optional[int] = None
    text: str = Field(min_length=10, max_length=2000)


class GrammarIssue(BaseModel):
    sentence_no: int
    sentence: str
    issue: str
    suggestion: str


class EssayScores(BaseModel):
    content: int
    structure: int
    grammar: int
    vocabulary: int
    expression: int
    total: int


class EssayOut(BaseModel):
    essay_id: int
    question_id: Optional[int] = None
    text: Optional[str] = None
    scores: EssayScores
    grammar_issues: List[GrammarIssue]
    overall: Optional[str] = None
    submitted_at: datetime


class EssayBrief(BaseModel):
    essay_id: int
    question_id: Optional[int] = None
    total: int
    submitted_at: datetime


# ---------- 学生：订正 ----------

class CorrectionCreate(BaseModel):
    error_id: int
    content: str = Field(min_length=1, max_length=500)


class CorrectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    error_id: int
    content: str
    is_correct: Optional[bool] = None
    note: Optional[str] = None
    submitted_at: datetime
    # v0.4.0 新增（只加字段）：订正成功时为 True，提示前端引导去做二次验证
    can_verify: bool = False
    knowledge_point: Optional[str] = None   # 该错题所属知识点（供前端直达验证）


# ---------- 画像 ----------

class KnowledgePointStat(BaseModel):
    knowledge_point: str
    attempts: int
    errors: int
    error_rate: float
    mastery: float


class StubbornErrorBrief(BaseModel):
    id: int
    knowledge_point: str
    error_type: str
    step_text: Optional[str] = None
    created_at: datetime


class ProfileOut(BaseModel):
    student: UserOut
    knowledge_points: List[KnowledgePointStat]
    stubborn_errors: List[StubbornErrorBrief]
    recent_errors: List[ErrorOut]
    suggestion: str


# ---------- 拍照转写 / 首页简报（v0.2.0 新增） ----------

class PhotoTranscribeOut(BaseModel):
    image_id: str                 # 服务器保存的文件名
    image_url: str                # 图片相对访问路径（/uploads/<文件名>）
    question_text: str
    steps: List[str]
    student_work_detected: Optional[bool] = None
    needs_image_review: Optional[bool] = None
    confidence: Optional[float] = None


class PhotoGroupSubOut(BaseModel):
    question_text: str
    steps: List[str] = []


class PhotoGroupTranscribeOut(BaseModel):
    """拍照识别大题（v0.13.11）：共同题干 + 全部小题一次返回。"""
    image_id: str                 # 服务器保存的文件名
    image_url: str                # 图片相对访问路径（/uploads/<文件名>）
    stem: str
    sub_questions: List[PhotoGroupSubOut]


class PhotoReviewOut(BaseModel):
    mode: str  # answer | diagnosis | transcribe
    question_text: str = ""
    steps: List[str] = Field(default_factory=list)
    capture_id: Optional[int] = None
    diagnosis: Optional[DiagnosisOut] = None
    session_id: Optional[int] = None  # 学习助手拍照记录所属会话


class PhotoCaptureSaveIn(BaseModel):
    explanation: str = Field(default="", max_length=12000)


class StudentQuestionCaptureCreate(BaseModel):
    question_text: str = Field(min_length=1, max_length=12000)
    subject: str = Field(default="math", max_length=32)
    explanation: str = Field(default="", max_length=12000)


class PendingAssignmentItem(BaseModel):
    id: int
    title: str
    question_count: int           # 作业总题目数
    remaining_count: int          # 该生尚未提交的题目数
    created_at: datetime
    # v0.5.0 新增（只加字段）：线下作业在简报卡上要展示模式/练习册/页码/截止
    mode: str = "online"
    workbook_title: Optional[str] = None
    page_range: Optional[str] = None
    deadline: Optional[datetime] = None


class WeakPointDetail(BaseModel):
    knowledge_point: str
    error_count: int              # 该知识点累计出错次数
    last_error_at: Optional[datetime] = None   # 最近一次出错时间


class BriefingOut(BaseModel):
    pending_assignments: List[PendingAssignmentItem]
    pending_corrections_count: int                     # 已诊断出错但未订正正确的条数
    pending_corrections_knowledge_points: List[str]    # 上述订正涉及的知识点（去重）
    weak_points: List[str]                             # 顽固/需要加固的知识点（去重）
    weak_point_details: List[WeakPointDetail] = []      # v0.2.1 新增：需加固知识点明细（与 weak_points 同序）
    recent_feedback: Optional[str] = None              # 最近一次批改的一句话摘要，可空


# ---------- 学习报告（v0.2.1 新增） ----------

class ReportKnowledgePointOut(BaseModel):
    name: str
    attempts: int                 # 该知识点题目的提交次数
    error_count: int              # 该知识点累计错题数
    error_rate: float             # error_count / attempts（上限 1.0，口径同学生画像）
    # v0.4.0 四态：pending（待修复）| stubborn（反复出错）| awaiting_verify（已订正待验证）| fixed（已修复，通过二次验证）
    status: str
    last_error_at: Optional[datetime] = None


class SubjectReportOut(BaseModel):
    subject: str                  # math | english
    submission_count: int         # 该科目提交总数
    correct_rate: float           # 1 - 错误率（口径同学生画像 mastery）
    pending_fix_count: int        # 未修复知识点数（status != fixed 的知识点数）
    fixed_ratio: float            # 知识修复率 = 已修复（通过二次验证）知识点 / 出过错的知识点（无错题知识点时为 1.0）
    knowledge_points: List[ReportKnowledgePointOut]


class KnowledgePointErrorItem(BaseModel):
    created_at: datetime
    assignment_title: str
    question_prompt: str
    first_error_seq: Optional[int] = None   # 出错步骤序号（该条错题所在步骤）
    error_type: str
    corrected: bool               # 是否已有订正正确的记录
    submission_id: int


# ---------- 教师 ----------

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


# ---------- 教师：发布作业（v0.2.0 新增） ----------

class TeacherQuestionIn(BaseModel):
    type: str = Field(pattern="^(math|essay)$")
    prompt: str = Field(min_length=1, max_length=2000)          # 题干
    knowledge_point: str = Field(min_length=1, max_length=64)
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


class TeacherAssignmentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=128)
    subject: Optional[str] = Field(default=None, pattern="^(math|english)$")
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


class TeacherAssignmentQuestionOut(BaseModel):
    id: int
    type: str                     # math | essay（由题目 subject 映射）
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


# ---------- 教师：练习册知识库 + 提醒未交（v0.5.0 新增） ----------

class WorkbookOut(BaseModel):
    id: int
    title: str
    file_url: str                 # /api/uploads/workbooks/<文件名>，可直接打开 PDF
    cover_url: Optional[str] = None  # v0.6.0 新增：PDF 首页封面图（/api/uploads/covers/<id>.jpg），无封面为 null
    created_at: datetime


class WorkbookExtractIn(BaseModel):
    page_range: str               # 老师填的页码范围原文，如「第 12-14 页 第 1-8 题」


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


# ---------- 主页 Agent 对话（v0.3.0 新增） ----------

class AgentChatIn(BaseModel):
    # 长度上限在接口层手动校验并返回 400（契约约定），故此处只做非空约束
    message: str = Field(min_length=1)
    session_id: Optional[int] = None  # v0.6.0 新增：指定写入的会话；不传 = 当前会话（没有则自动新建）
    persist_user_message: bool = True  # 流式接口允许复用已保存的拍照消息，避免重复记一条


class AgentHistoryItem(BaseModel):
    role: str                     # user | assistant
    content: str
    created_at: datetime
    related_mistake: Optional[RelatedMistakeOut] = None
    image_url: Optional[str] = None
    image_name: Optional[str] = None


class ChatSessionOut(BaseModel):
    """对话会话（v0.6.0 新增）：历史对话列表用。"""
    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int


# ---------- 站内提醒（v0.3.0 新增） ----------

class NotificationItem(BaseModel):
    id: int
    type: str
    content: str
    related_submission_id: Optional[int] = None
    is_read: bool
    created_at: datetime


class NotificationListOut(BaseModel):
    unread_count: int
    items: List[NotificationItem]


class NotificationReadIn(BaseModel):
    ids: Optional[List[int]] = None   # 不传或为空 = 全部标已读


class NotificationReadOut(BaseModel):
    updated: int                  # 本次标已读的条数
    unread_count: int             # 标后的未读数


# ---------- 二次验证（v0.4.0 新增） ----------

class VerificationCreate(BaseModel):
    knowledge_point: str = Field(min_length=1, max_length=64)
    source_error_id: Optional[int] = None   # 触发验证的错题，可空（后端默认取该知识点最近错题）


class VerificationOut(BaseModel):
    id: int
    knowledge_point: str
    prompt: str                   # 只下发题干，答案与标准步骤不下发
    status: str                   # pending | passed | failed
    attempts: int
    source_error_id: Optional[int] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class VerificationSubmitIn(BaseModel):
    steps: List[str] = Field(min_length=1, max_length=20)

    from pydantic import field_validator

    @field_validator("steps")
    @classmethod
    def _check_steps(cls, v: List[str]) -> List[str]:
        cleaned = []
        for s in v:
            if not isinstance(s, str) or not s.strip():
                raise ValueError("每个作答步骤不能为空")
            if len(s) > 500:
                raise ValueError("单个步骤不能超过 500 字符")
            cleaned.append(s.strip())
        return cleaned


class VerificationStepOut(BaseModel):
    seq: int
    text: str
    status: str                   # ok | error | unparseable | skipped


class VerificationSubmitOut(BaseModel):
    id: int
    knowledge_point: str
    status: str                   # passed | failed
    attempts: int
    passed: bool
    first_error_seq: Optional[int] = None   # 首个出错步序号（通过时为 None）
    error_type: Optional[str] = None        # 首个出错步的错因（最终步未完成时为 None）
    detail: Optional[str] = None            # 解析/判定说明
    steps: List[VerificationStepOut]


# ---------- 教师：班级知识修复率（v0.4.0 新增） ----------

class KnowledgePointRepairItem(BaseModel):
    knowledge_point: str
    students_errored: int         # 在该知识点出过错的学生数
    students_fixed: int           # 其中已修复（订正+通过验证）的学生数
    repair_rate: float            # students_fixed / students_errored


class ClassRepairRateOut(BaseModel):
    class_repair_rate: float                 # 全班知识修复率 = 已修复（学生×知识点）/ 出过错（学生×知识点）
    students_with_errors: int                # 有过错题的学生数
    total_knowledge_point_pairs: int         # 出过错的（学生, 知识点）组合数
    fixed_knowledge_point_pairs: int         # 其中已修复的组合数
    knowledge_points: List[KnowledgePointRepairItem]


# ---------- 教师：提交审核流（v0.9.0 新增） ----------

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
    submitted_at: datetime


class ReviewPendingOut(BaseModel):
    count: int                  # 待审核总数（导航角标用）
    items: List[ReviewPendingItem]


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


# ---------- 学生：报告成绩分析（评分系统新增） ----------

class AssignmentScoreItem(BaseModel):
    """一份作业的成绩聚合：每题取最新一次已通过且有分的提交求和。"""
    assignment_id: int
    assignment_title: str
    subject: str
    date: datetime              # 计入提交里最晚的一次提交时间
    score: float                # 得分（各题最终分之和）
    max_score: float            # 满分（计入题目的满分之和）
    rate: float                 # 得分率 0~1


class SubjectScoreItem(BaseModel):
    subject: str
    avg_rate: float             # 该学科各份作业得分率的平均
    assignment_count: int       # 计入的作业份数


class ReportScoresOut(BaseModel):
    items: List[AssignmentScoreItem]        # 按日期正序（画走势折线用）
    subjects: List[SubjectScoreItem]
    overall_avg_rate: Optional[float] = None  # 全部作业得分率平均；无数据为 None


# ---------- 健康检查 ----------

class HealthOut(BaseModel):
    status: str = "ok"
    version: str
    provider: str
    time: datetime
