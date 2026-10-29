"""Public request and response models for the student API domain."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .base import UserOut


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
    """学生可见的 AI 当前分；低分作业待教师审核时仍返回，最终分可能调整。"""
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
    # 教师审核状态与错题流程并行：pending 时步骤、错误与 AI 当前分仍对学生可见。
    review_status: str = "approved"
    # 本题 AI 当前得分；待审核时可见，教师调整后可能更新。
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
    # 教师审核状态 pending | approved（无审核行=历史数据=approved）；错误数与审核并行显示
    review_status: str = "approved"
    # 本题 AI 当前分与满分；待审核时可见，教师可能调整最终分
    score: Optional[float] = None
    max_score: Optional[float] = None

class SubmissionQuestionStatusOut(BaseModel):
    question_id: int
    status: str
    review_status: str = "approved"
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
    review_status: Optional[str] = None
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

class StudentMistakeCountOut(BaseModel):
    count: int

class StudentMistakeReviewCategoryOut(BaseModel):
    key: str
    subject: str
    category_label: str
    knowledge_point: str
    assignment_title: str
    mistake_id: int
    item_count: int
    priority: int
    created_at: datetime
    studied: bool

class StudentMistakeReviewSummaryOut(BaseModel):
    total_count: int
    has_records: bool
    categories: List[StudentMistakeReviewCategoryOut]

class StudentMistakeTimelineItemOut(BaseModel):
    id: int
    submission_id: int
    question_subject: str
    created_at: datetime
    question_stem: str
    knowledge_point: str
    error_type: str
    corrected: bool

class StudentMistakeTimelinePageOut(BaseModel):
    items: List[StudentMistakeTimelineItemOut]
    has_more: bool
    total_count: Optional[int] = None

class StudentCorrectionWallItemOut(BaseModel):
    id: int
    submission_id: int
    question_subject: str
    assignment_title: str
    question_stem: str
    review_status: str
    corrected: bool
    is_stubborn: bool
    knowledge_point: str
    error_type: str
    detail: Optional[str] = None
    step_seq: Optional[int] = None
    step_text: Optional[str] = None
    created_at: datetime
    submitted_at: Optional[datetime] = None
    image_url: Optional[str] = None

class StudentCorrectionWallCursorOut(BaseModel):
    created_at: datetime
    id: int

class StudentCorrectionWallPageOut(BaseModel):
    items: List[StudentCorrectionWallItemOut]
    total_count: Optional[int] = None
    pending_count: Optional[int] = None
    has_more: bool
    next_cursor: Optional[StudentCorrectionWallCursorOut] = None

class RelatedMistakeOut(BaseModel):
    id: int
    submission_id: int
    review_status: Optional[str] = None
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
    status: str = "submitted"
    scores: Optional[EssayScores] = None
    grammar_issues: List[GrammarIssue] = Field(default_factory=list)
    overall: Optional[str] = None
    submitted_at: datetime

class EssayBrief(BaseModel):
    essay_id: int
    question_id: Optional[int] = None
    status: str = "submitted"
    total: Optional[int] = None
    submitted_at: datetime

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

class PhotoTranscribeOut(BaseModel):
    image_id: Optional[str] = None  # save_image=false 时不写盘
    image_url: Optional[str] = None
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
    image_id: Optional[str] = None  # save_image=false 时不写盘
    image_url: Optional[str] = None
    stem: str
    sub_questions: List[PhotoGroupSubOut]

class PhotoReviewOut(BaseModel):
    mode: str  # answer | diagnosis | transcribe
    question_text: str = ""
    steps: List[str] = Field(default_factory=list)
    capture_id: Optional[int] = None
    diagnosis: Optional[DiagnosisOut] = None
    session_id: Optional[int] = None  # 学习助手拍照记录所属会话
    image_url: Optional[str] = None   # 服务器保存的原图地址
    related_mistake: Optional[RelatedMistakeOut] = None

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

class StudentLearningMemoryOut(BaseModel):
    subject: str
    knowledge_point: str
    error_count: int
    corrected_count: int
    correction_success_rate: float
    verification_pass_rate: float
    state: str
    summary: str
    updated_at: datetime

class AssignmentScoreItem(BaseModel):
    """一份作业的成绩聚合：每题取最新一次已通过且有分的提交求和。"""
    assignment_id: int
    assignment_title: str
    subject: str                  # 单学科代码；跨学科作业为 mixed
    subjects: List[str] = Field(default_factory=list)
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

__all__ = [
    'SubmissionCreate',
    'StepOut',
    'ErrorOut',
    'DiagnosisScoreOut',
    'DiagnosisOut',
    'PhotoDiagnosisOut',
    'SubmissionBrief',
    'SubmissionQuestionStatusOut',
    'MistakeCorrectionBrief',
    'SimilarMistakeBrief',
    'StudentMistakeOut',
    'StudentMistakeCountOut',
    'StudentMistakeReviewCategoryOut',
    'StudentMistakeReviewSummaryOut',
    'StudentMistakeTimelineItemOut',
    'StudentMistakeTimelinePageOut',
    'StudentCorrectionWallItemOut',
    'StudentCorrectionWallCursorOut',
    'StudentCorrectionWallPageOut',
    'RelatedMistakeOut',
    'MistakeCategoryStudyIn',
    'MistakeAssignmentArchiveIn',
    'MistakeArchiveIn',
    'EssayCreate',
    'GrammarIssue',
    'EssayScores',
    'EssayOut',
    'EssayBrief',
    'CorrectionCreate',
    'CorrectionOut',
    'KnowledgePointStat',
    'StubbornErrorBrief',
    'ProfileOut',
    'PhotoTranscribeOut',
    'PhotoGroupSubOut',
    'PhotoGroupTranscribeOut',
    'PhotoReviewOut',
    'PhotoCaptureSaveIn',
    'StudentQuestionCaptureCreate',
    'PendingAssignmentItem',
    'WeakPointDetail',
    'BriefingOut',
    'ReportKnowledgePointOut',
    'SubjectReportOut',
    'KnowledgePointErrorItem',
    'StudentLearningMemoryOut',
    'AssignmentScoreItem',
    'SubjectScoreItem',
    'ReportScoresOut',
]
