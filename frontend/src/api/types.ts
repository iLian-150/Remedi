// 前后端契约类型声明 —— 严格对齐 ~/workspace/remedi/docs/api-contract.md v0.1.0
// 任何路径/字段/枚举的修改必须先更新契约文档，绝不自创。

// ---------- 通用 ----------
export interface User {
  id: number
  name: string
  student_no: string | null
  role: 'teacher' | 'student'
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
}

export interface AssignmentDetail extends Assignment {
  questions: Question[]
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

// POST /api/student/submissions 与 GET /api/student/submissions/{id} 的响应体
export interface SubmissionResult {
  submission_id: number
  question_id: number
  status: 'submitted' | 'graded'
  first_error_seq: number | null
  steps: StepDiagnosis[]
  errors: GradingError[]
  follow_up_question?: string | null // v0.4.0：启发式追问，无错时为 null
}

export interface SubmissionSummary {
  id: number
  question_id: number
  question_stem: string
  knowledge_point: string
  status: string
  error_count: number
  submitted_at: string
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
  student: { id: number; name: string; student_no: string }
  knowledge_points: KnowledgeStat[]
  stubborn_errors: GradingError[]
  recent_errors: GradingError[]
  suggestion: string
}

// ---------- 教师端 ----------
export interface TeacherErrorItem extends GradingError {
  student: { id: number; name: string; student_no: string }
  question: { id: number; stem: string; subject: string }
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
}

export interface TeacherAssignmentInput {
  title: string
  subject?: 'math' | 'english'
  description?: string
  questions: TeacherQuestionInput[]
  // v0.5.0：发布模式（不传 = 线上）；线下模式带练习册/页码/截止
  mode?: 'online' | 'offline'
  workbook_id?: number
  page_range?: string
  deadline?: string
}

// ---------- v0.5.0 新增：教师 AI 助手 / 练习册知识库 ----------
// 契约见 docs/api-contract.md v0.5.0 第 4.12~4.18 节

export interface Workbook {
  id: number
  title: string
  file_url: string // /api/uploads/workbooks/<文件名>
  created_at: string
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
