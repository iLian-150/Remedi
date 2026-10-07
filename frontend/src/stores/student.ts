// 学生端 store：作业、提交诊断、作文、订正、学习画像
// 路径与字段严格对齐 docs/api-contract.md v0.1.0
import { defineStore } from 'pinia'
import api from '../api/client'
import type {
  AgentChatResult,
  AgentHistoryItem,
  Assignment,
  AssignmentDetail,
  ChatSession,
  CorrectionResult,
  EssayResult,
  EssaySummary,
  KnowledgePointErrorItem,
  NotificationList,
  PageResult,
  PhotoTranscribeResult,
  StudentBriefing,
  StudentProfile,
  SubjectReport,
  SubmissionResult,
  SubmissionSummary,
  Verification,
  VerificationSubmitResult
} from '../api/types'

export const useStudentStore = defineStore('student', {
  state: () => ({
    /** 作业列表页的发布日期筛选（v0.3.1）：空 = 全部；由右侧栏日历写入、本页消费 */
    assignmentDateFilter: ''
  }),
  actions: {
    setAssignmentDateFilter(date: string) {
      this.assignmentDateFilter = date
    },
    // 3.1 作业列表
    async fetchAssignments(): Promise<Assignment[]> {
      const { data } = await api.get<PageResult<Assignment>>('/api/student/assignments')
      return data.items
    },
    // 3.2 作业详情（含题目，不含标准答案）
    async fetchAssignmentDetail(id: number): Promise<AssignmentDetail> {
      const { data } = await api.get<AssignmentDetail>(`/api/student/assignments/${id}`)
      return data
    },
    // 3.3 提交数学作业并诊断（诊断同步返回）
    async submitMath(payload: { question_id: number; steps: string[] }): Promise<SubmissionResult> {
      const { data } = await api.post<SubmissionResult>('/api/student/submissions', payload)
      return data
    },
    // 3.4 我的提交记录（可按 question_id 过滤）
    async fetchMySubmissions(questionId?: number, limit = 100): Promise<SubmissionSummary[]> {
      const { data } = await api.get<PageResult<SubmissionSummary>>('/api/student/submissions', {
        params: { ...(questionId ? { question_id: questionId } : {}), limit }
      })
      return data.items
    },
    // 3.5 提交详情（分步诊断）
    async fetchSubmissionDetail(id: number): Promise<SubmissionResult> {
      const { data } = await api.get<SubmissionResult>(`/api/student/submissions/${id}`)
      return data
    },
    // 3.6 提交英语作文并评分
    async submitEssay(payload: { question_id?: number; text: string }): Promise<EssayResult> {
      const { data } = await api.post<EssayResult>('/api/student/essays', payload)
      return data
    },
    // 3.7 我的作文列表
    async fetchMyEssays(): Promise<EssaySummary[]> {
      const { data } = await api.get<PageResult<EssaySummary>>('/api/student/essays')
      return data.items
    },
    // 3.8 作文详情
    async fetchEssayDetail(id: number): Promise<EssayResult> {
      const { data } = await api.get<EssayResult>(`/api/student/essays/${id}`)
      return data
    },
    // 3.9 提交订正（针对某条 error）
    async submitCorrection(payload: { error_id: number; content: string }): Promise<CorrectionResult> {
      const { data } = await api.post<CorrectionResult>('/api/student/corrections', payload)
      return data
    },
    // 3.10 我的学习画像
    async fetchProfile(): Promise<StudentProfile> {
      const { data } = await api.get<StudentProfile>('/api/student/profile')
      return data
    },
    // 3.12 首页待办简报（v0.2.0）
    async fetchBriefing(): Promise<StudentBriefing> {
      const { data } = await api.get<StudentBriefing>('/api/student/briefing')
      return data
    },
    // 3.11 拍照转写（v0.2.0）：multipart 上传，返回转写文本，确认后仍走 submitMath
    async transcribePhoto(file: File): Promise<PhotoTranscribeResult> {
      const form = new FormData()
      form.append('file', file)
      const { data } = await api.post<PhotoTranscribeResult>('/api/student/photo-transcribe', form, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      return data
    },
    // 3.13 学习报告（v0.2.1）：按科目聚合 + 知识点状态
    async fetchReport(): Promise<SubjectReport[]> {
      const { data } = await api.get<SubjectReport[]>('/api/student/report')
      return data
    },
    // 3.14 知识点错题时间线（v0.2.1）
    async fetchKnowledgePointErrors(name: string): Promise<KnowledgePointErrorItem[]> {
      const { data } = await api.get<KnowledgePointErrorItem[]>(
        `/api/student/report/knowledge-points/${encodeURIComponent(name)}/errors`
      )
      return data
    },
    // 3.15 与学习助手对话（v0.3.0，LangGraph Agent；v0.6.0 会话制：可指定 session_id，
    // 响应含建议追问 suggestions 与实际写入的 session_id）
    async agentChat(message: string, sessionId?: number | null): Promise<AgentChatResult> {
      const { data } = await api.post<AgentChatResult>('/api/student/agent/chat', {
        message,
        session_id: sessionId ?? undefined
      })
      return data
    },
    // 3.16 我的对话历史（v0.3.0；v0.6.0 起返回当前会话最近 50 条，时间正序）
    async fetchAgentHistory(): Promise<AgentHistoryItem[]> {
      const { data } = await api.get<AgentHistoryItem[]>('/api/student/agent/history')
      return data
    },
    // 3.23 我的对话会话列表（v0.6.0）：按最近更新倒序，含消息数
    async fetchSessions(): Promise<ChatSession[]> {
      const { data } = await api.get<ChatSession[]>('/api/student/agent/sessions')
      return data
    },
    // 3.24 新建对话会话（v0.6.0）
    async createSession(): Promise<ChatSession> {
      const { data } = await api.post<ChatSession>('/api/student/agent/sessions', {})
      return data
    },
    // 3.25 某会话的全部消息（v0.6.0），时间正序
    async fetchSessionMessages(sessionId: number): Promise<AgentHistoryItem[]> {
      const { data } = await api.get<AgentHistoryItem[]>(
        `/api/student/agent/sessions/${sessionId}/messages`
      )
      return data
    },
    // 3.26 删除一条对话会话（v0.6.0）：连同其消息一并删除
    async deleteSession(sessionId: number): Promise<void> {
      await api.delete(`/api/student/agent/sessions/${sessionId}`)
    },
    // 3.22 开始新对话（v0.5.0 新增；v0.6.0 语义变更：新建一条会话，旧会话保留可找回）
    async newAgentSession(): Promise<ChatSession> {
      const { data } = await api.post<ChatSession>('/api/student/agent/new-session', {})
      return data
    },
    // 3.17 我的提醒列表（v0.3.0）：最近 30 条倒序 + 未读数
    async fetchNotifications(): Promise<NotificationList> {
      const { data } = await api.get<NotificationList>('/api/student/notifications')
      return data
    },
    // 3.18 提醒标已读（v0.3.0）：ids 不传 = 全部标已读
    async markNotificationsRead(ids?: number[]): Promise<{ updated: number; unread_count: number }> {
      const { data } = await api.post<{ updated: number; unread_count: number }>(
        '/api/student/notifications/read',
        ids && ids.length ? { ids } : {}
      )
      return data
    },
    // 3.19 创建二次验证（v0.4.0）：为某知识点生成一道变式题，已有未完成的直接复用
    async createVerification(payload: {
      knowledge_point: string
      source_error_id?: number
    }): Promise<Verification> {
      const { data } = await api.post<Verification>('/api/student/verifications', payload)
      return data
    },
    // 3.20 我的验证列表（v0.4.0）
    async fetchVerifications(): Promise<Verification[]> {
      const { data } = await api.get<Verification[]>('/api/student/verifications')
      return data
    },
    // 3.21 提交验证作答（v0.4.0）：逐步等价判定，全对才算通过
    async submitVerification(id: number, steps: string[]): Promise<VerificationSubmitResult> {
      const { data } = await api.post<VerificationSubmitResult>(
        `/api/student/verifications/${id}/submit`,
        { steps }
      )
      return data
    }
  }
})
