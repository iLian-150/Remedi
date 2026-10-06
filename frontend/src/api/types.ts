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
}

// ---------- v0.2.1 新增：学习报告（科目 → 知识点 → 错题时间线 → 步骤诊断） ----------
// 契约见 docs/api-contract.md v0.2.1 第 3.13 / 3.14 节

export type KnowledgePointStatus = 'pending' | 'stubborn' | 'fixed'

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
