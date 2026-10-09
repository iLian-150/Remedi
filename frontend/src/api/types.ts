// 前后端契约类型声明 —— 严格对齐 ~/workspace/remedi/docs/api-contract.md v0.1.0
// 任何路径/字段/枚举的修改必须先更新契约文档，绝不自创。

// ---------- 通用 ----------
export interface User {
  id: number
  name: string
  student_no: string | null
  role: 'teacher' | 'student'
  created_at?: string | null // v0.9.0：加入时间（档案黑板用）
}

export interface LoginResponse {
  token: string
  token_type: string
  user: User
}

export interface PageResult<T> {
  total: number
  items: T[]
}

export type ErrorType = '计算失误' | '概念混淆' | '审题遗漏' | '无法解析'

// ---------- 作业 / 题目 ----------
export interface Assignment {
  id: number
  title: string
  description: string
  question_count: number
  created_at: string
  // v0.5.0：发布模式与线下作业信息（线上作业 mode='online'、其余为 null）
  mode: 'online' | 'offline'
  workbook_title: string | null
  page_range: string | null
  deadline: string | null
}

export interface Question {
  id: number
  subject: 'math' | 'english'
  knowledge_point: string
  stem: string
  order_num: number
  group_id?: number | null // v0.13.1：所属大题 id，普通题为 null
}

export interface AssignmentDetail extends Assignment {
  questions: Question[]
  // v0.13.1：允许修改开关 + 大题列表（共享题干）
  allow_revision?: boolean
  groups?: { id: number; stem: string; order_num: number }[]
}

// ---------- 数学提交与诊断 ----------
export type StepStatus = 'stem' | 'ok' | 'error' | 'unparseable' | 'skipped'

export interface StepDiagnosis {
  seq: number
  text: string
  status: StepStatus
}

export interface GradingError {
  id: number
  submission_id: number
  step_seq: number
  step_text: string
  knowledge_point: string
  error_type: ErrorType | string
  confidence: number // 0~1
  is_stubborn: boolean // 顽固误区
  detail: string
  teacher_corrected: boolean
  teacher_note: string | null
  created_at: string
}

export interface StudentMistake {
  id: number
  submission_id: number
  question_id: number
  assignment_id: number
  assignment_title: string
  assignment_created_at: string
  question_subject: string
  question_order: number
  question_stem: string
  knowledge_point: string
  error_type: ErrorType | string
  is_stubborn: boolean
  detail: string | null
  step_seq: number | null
  step_text: string | null
  created_at: string
  submitted_at?: string | null // v0.9.0：错题所属提交的提交时间（订正页日历打点用）
  category_key: string
  category_label: string
  category_studied: boolean
  archived_at: string | null
  similar_occurrences: Array<{
    id: number
    submission_id: number
    assignment_id: number
    assignment_title: string
    assignment_created_at: string
    question_stem: string
  }>
  latest_correction: {
    id: number
    content: string
    is_correct: boolean | null
    note: string | null
    submitted_at: string
  } | null
  verification_status: VerificationStatus | null
  source_kind?: 'diagnosed' | 'student_saved'
  capture_id?: number | null
  image_url?: string | null
}

// POST /api/student/submissions 与 GET /api/student/submissions/{id} 的响应体
export interface SubmissionResult {
  submission_id: number
  question_id: number
  // v0.9.0：新增 'pending_review'——已提交、等老师审核，steps/errors 为空
  // v0.13.1：新增 'deferred'——已提交、等截止后统一批改，steps/errors 为空
  status: 'submitted' | 'graded' | 'pending_review' | 'deferred'
  first_error_seq: number | null
  steps: StepDiagnosis[]
  errors: GradingError[]
  follow_up_question?: string | null // v0.4.0：启发式追问，无错时为 null
  review_status?: 'pending' | 'approved' | 'deferred' // v0.9.0：教师审核状态；v0.13.1 加 deferred
  // 评分系统：本题得分（最终分）与满分；待审核时为 null，分数跟诊断一起放行
  // assignment_* 是这份作业目前的累计得分与总分（成绩单展示用，可能缺失）
  score?: {
    score: number
    max_score: number
    assignment_score?: number | null
    assignment_total?: number | null
  } | null
}

export interface SubmissionSummary {
  id: number
  question_id: number
  question_stem: string
  knowledge_point: string
  status: string
  error_count: number
  submitted_at: string
  review_status?: 'pending' | 'approved' // v0.9.0：教师审核状态（pending 时 error_count=0）
  score?: number | null // 评分系统：本题最终分（仅已通过时有值）
  max_score?: number | null // 评分系统：本题满分
}

// ---------- 英语作文 ----------
export interface EssayScores {
  content: number
  structure: number
  grammar: number
  vocabulary: number
  expression: number
  total: number
}

export interface GrammarIssue {
  sentence_no: number
  sentence: string
  issue: string
  suggestion: string
}

// POST /api/student/essays 响应；GET /api/student/essays/{essay_id} 另含 text 与 question_id
export interface EssayResult {
  essay_id: number
  scores: EssayScores
  grammar_issues: GrammarIssue[]
  overall: string
  submitted_at: string
  text?: string
  question_id?: number | null
}

export interface EssaySummary {
  essay_id: number
  question_id: number | null
  total: number
  submitted_at: string
}

// ---------- 订正 ----------
export interface CorrectionResult {
  id: number
  error_id: number
  content: string
  is_correct: boolean | null // true 正确 / false 仍不正确 / null 无法判定
  note: string
  submitted_at: string
  can_verify?: boolean // v0.4.0：订正成功时为 true，提示可去做二次验证
  knowledge_point?: string | null // v0.4.0：该错题所属知识点
}

// ---------- 学习画像（学生自查 / 教师查学生同结构） ----------
export interface KnowledgeStat {
  knowledge_point: string
  attempts: number
  errors: number
  error_rate: number
  mastery: number
}

export interface StudentProfile {
  student: { id: number; name: string; student_no: string; role?: string; created_at?: string | null }
  knowledge_points: KnowledgeStat[]
  stubborn_errors: GradingError[]
  recent_errors: GradingError[]
  suggestion: string
}

// ---------- 教师端 ----------
export interface TeacherErrorItem extends GradingError {
  student: { id: number; name: string; student_no: string }
  question: { id: number; stem: string; subject: string }
  review_status?: 'pending' | 'approved' // v0.9.0：所属提交的审核状态
  score?: number | null // 评分系统：所属提交最终分（仅已通过时有值）
  max_score?: number | null // 评分系统：本题满分
}

// ---------- v0.9.0 新增：教师审核流 ----------
// 契约见 docs/api-contract.md v0.9.0 第 4.23~4.26 节

export interface ReviewPendingItem {
  submission_id: number
  student: { id: number; name: string; student_no: string | null }
  assignment_id: number | null
  assignment_title: string
  question_id: number
  question_stem: string
  subject: string
  knowledge_point: string
  error_count: number
  submitted_at: string
}

// 评分系统：审核详情里的评分信息（满分/AI 分/最终分/步骤对了几步）
export interface ReviewScore {
  question_max: number
  ai_score: number | null
  final_score: number | null
  ok_steps: number
  total_steps: number
}

// 过程可疑识别（仅教师端）：答案对但过程存疑的确定性信号
export interface ProcessCheckSignal {
  code: string // broken_chain | leap | unparseable_heavy
  text: string
}

export interface ProcessCheck {
  suspicious: boolean
  signals: ProcessCheckSignal[]
  final_answer: string | null
  reference_answer: string | null
}

export interface ReviewDetail {
  submission_id: number
  student: { id: number; name: string; student_no: string | null }
  assignment_title: string
  question: Question
  submitted_at: string
  review_status: 'pending' | 'approved'
  diagnosis: SubmissionResult
  score?: ReviewScore | null // 评分系统：本题评分信息
  process_check?: ProcessCheck | null // 过程可疑识别：供教师审核参考
}

export interface TopQuestion {
  question_id: number
  stem: string
  subject: string
  knowledge_point: string
  error_count: number
  student_count: number
}

export interface KnowledgePointStat {
  knowledge_point: string
  submissions: number
  errors: number
  error_rate: number
}

export interface StudentSummary {
  id: number
  name: string
  student_no: string
  submission_count: number
  error_count: number
}

// ---------- v0.2.0 新增：简报 / 拍照转写 / 教师作业 ----------
// 契约见 docs/api-contract.md v0.2.0 第 3.11 / 3.12 / 4.7 / 4.8 节

export interface PendingAssignment {
  id: number
  title: string
  question_count: number
  remaining_count: number
  created_at: string
  // v0.5.0：简报待办卡上的线下作业信息
  mode: 'online' | 'offline'
  workbook_title: string | null
  page_range: string | null
  deadline: string | null
}

export interface WeakPointDetail {
  knowledge_point: string
  error_count: number
  last_error_at: string | null
}

export interface StudentBriefing {
  pending_assignments: PendingAssignment[]
  pending_corrections_count: number
  pending_corrections_knowledge_points: string[]
  weak_points: string[]
  weak_point_details: WeakPointDetail[] // v0.2.1 新增：需加固知识点明细（与 weak_points 同序）
  recent_feedback: string | null
}

export interface PhotoTranscribeResult {
  image_id: string
  image_url: string
  question_text: string
  steps: string[]
  student_work_detected?: boolean | null
  needs_image_review?: boolean | null
  confidence?: number | null
}

export interface PhotoReviewResult {
  mode: 'answer' | 'diagnosis' | 'transcribe'
  question_text: string
  steps: string[]
  capture_id: number | null
  diagnosis: SubmissionResult | null
}

// ---------- 主页 Agent 对话（v0.3.0） ----------

export interface AgentHistoryItem {
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

// ---------- 站内提醒（v0.3.0） ----------

export interface NotificationItem {
  id: number
  type: string
  content: string
  related_submission_id: number | null
  is_read: boolean
  created_at: string
}

export interface NotificationList {
  unread_count: number
  items: NotificationItem[]
}

export interface TeacherAssignmentQuestion {
  id: number
  type: 'math' | 'essay'
  prompt: string
  knowledge_point: string
  standard_answer: string | null
  submission_count: number
}

export interface TeacherAssignment {
  id: number
  title: string
  description: string | null
  created_at: string
  questions: TeacherAssignmentQuestion[]
  // v0.5.0：发布模式与线下作业信息
  mode: 'online' | 'offline'
  workbook_title: string | null
  page_range: string | null
  deadline: string | null
}

export interface TeacherQuestionInput {
  type: 'math' | 'essay'
  prompt: string
  knowledge_point: string
  standard_steps?: string[]
  reference_answer?: string
  weight_pct?: number // 评分系统：该题分值占比 %（不传 = 按题数均分）
  group_key?: string // v0.13.1：所属大题的临时 key（与 groups[].key 对应）
}

export interface TeacherAssignmentInput {
  title: string
  subject?: 'math' | 'english'
  description?: string
  questions: TeacherQuestionInput[]
  // v0.13.1：允许学生截止前修改作答（开启后延迟到截止统一批改）
  allow_revision?: boolean
  // v0.13.1：大题列表（共享题干），小题用 group_key 挂靠
  groups?: { key: string; stem: string }[]
  // v0.5.0：发布模式（不传 = 线上）；线下模式带练习册/页码/截止
  mode?: 'online' | 'offline'
  workbook_id?: number
  page_range?: string
  deadline?: string
  total_score?: number // 评分系统：作业总分（不传 = 100）
}

// ---------- v0.5.0 新增：教师 AI 助手 / 练习册知识库 ----------
// 契约见 docs/api-contract.md v0.5.0 第 4.12~4.18 节

export interface Workbook {
  id: number
  title: string
  file_url: string // /api/uploads/workbooks/<文件名>
  cover_url: string | null // v0.6.0 新增：PDF 首页封面图，无封面时为 null（前端用纯色书脊兜底）
  created_at: string
}

// ---------- v0.6.0 新增：对话会话（双端共用结构） ----------
// 契约见 docs/api-contract.md v0.6.0 第 3.23~3.26 / 4.19~4.22 节

export interface ChatSession {
  id: number
  title: string
  created_at: string
  updated_at: string
  message_count: number
}

// POST /api/{role}/agent/chat 响应：回复 + 建议追问 + 实际写入的会话
export interface AgentChatResult {
  reply: string
  suggestions: string[]
  session_id: number | null
}

// ---------- v0.2.1 新增：学习报告（科目 → 知识点 → 错题时间线 → 步骤诊断） ----------
// 契约见 docs/api-contract.md v0.2.1 第 3.13 / 3.14 节

// v0.4.0 四态：pending 待修复 | stubborn 反复出错 | awaiting_verify 已订正待验证 | fixed 已修复（通过二次验证）
export type KnowledgePointStatus = 'pending' | 'stubborn' | 'awaiting_verify' | 'fixed'

export interface ReportKnowledgePoint {
  name: string
  attempts: number
  error_count: number
  error_rate: number
  status: KnowledgePointStatus
  last_error_at: string | null
}

export interface SubjectReport {
  subject: string // 'math' | 'english'
  submission_count: number
  correct_rate: number
  pending_fix_count: number
  fixed_ratio: number
  knowledge_points: ReportKnowledgePoint[]
}

export interface KnowledgePointErrorItem {
  created_at: string
  assignment_title: string
  question_prompt: string
  first_error_seq: number | null
  error_type: ErrorType | string
  corrected: boolean
  submission_id: number
}

// ---------- 评分系统新增：报告成绩分析（GET /api/student/report/scores） ----------

export interface AssignmentScoreItem {
  assignment_id: number
  assignment_title: string
  subject: string
  date: string
  score: number // 得分（各题最新一次已通过提交的最终分之和）
  max_score: number // 满分（计入题目的满分之和）
  rate: number // 得分率 0~1
}

export interface ReportScores {
  items: AssignmentScoreItem[] // 按日期正序
  subjects: { subject: string; avg_rate: number; assignment_count: number }[]
  overall_avg_rate: number | null
}

// ---------- v0.4.0 新增：二次验证 / 班级知识修复率 ----------
// 契约见 docs/api-contract.md v0.4.0 第 3.19~3.21 / 4.11 节

export type VerificationStatus = 'pending' | 'passed' | 'failed'

export interface Verification {
  id: number
  knowledge_point: string
  prompt: string // 只下发题干，答案与标准步骤不下发
  status: VerificationStatus
  attempts: number
  source_error_id: number | null
  created_at: string
  completed_at: string | null
}

export interface VerificationStepResult {
  seq: number
  text: string
  status: StepStatus // ok | error | unparseable | skipped
}

export interface VerificationSubmitResult {
  id: number
  knowledge_point: string
  status: VerificationStatus
  attempts: number
  passed: boolean
  first_error_seq: number | null
  error_type: string | null
  detail: string | null
  steps: VerificationStepResult[]
}

export interface KnowledgePointRepair {
  knowledge_point: string
  students_errored: number
  students_fixed: number
  repair_rate: number
}

export interface ClassRepairRate {
  class_repair_rate: number
  students_with_errors: number
  total_knowledge_point_pairs: number
  fixed_knowledge_point_pairs: number
  knowledge_points: KnowledgePointRepair[]
}

// 教学建议（GET /api/teacher/suggestions）：规则模板生成，按严重度排序
export interface TeachingSuggestion {
  kind: 'reteach' | 'stubborn_group' | 'high_error' | 'low_score'
  title: string
  knowledge_point: string | null
  evidence: string
  action: string
  sample_questions: string[]
}

// ---------- 界面文案映射 ----------
export const STEP_STATUS_TEXT: Record<StepStatus, string> = {
  stem: '题干',
  ok: '正确',
  error: '出错',
  unparseable: '无法解析',
  skipped: '跳过'
}

export const SUBMISSION_STATUS_TEXT: Record<string, string> = {
  submitted: '已提交',
  graded: '已批改'
}

export const ERROR_TYPES: ErrorType[] = ['计算失误', '概念混淆', '审题遗漏', '无法解析']
