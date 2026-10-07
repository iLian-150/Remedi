// 教师端 store：错误记录、一键纠错、班级看板统计、学生画像
// 路径与字段严格对齐 docs/api-contract.md v0.1.0
import { defineStore } from 'pinia'
import api from '../api/client'
import type {
  AgentChatResult,
  AgentHistoryItem,
  ChatSession,
  ClassRepairRate,
  GradingError,
  KnowledgePointStat,
  PageResult,
  PhotoTranscribeResult,
  StudentProfile,
  StudentSummary,
  TeacherAssignment,
  TeacherAssignmentInput,
  TeacherErrorItem,
  TopQuestion,
  Workbook
} from '../api/types'

export interface ErrorFilter {
  student_id?: number
  knowledge_point?: string
  error_type?: string
  stubborn_only?: boolean
  limit?: number
  offset?: number
}

export const useTeacherStore = defineStore('teacher', {
  state: () => ({
    /** 作业管理页的发布日期筛选（v0.3.1）：空 = 全部；由右侧栏日历写入、本页消费 */
    assignmentDateFilter: '',
    /** 会话区状态（v0.6.2）：左侧栏会话导航与对话页共用同一份 */
    sessions: [] as ChatSession[],
    activeSessionId: null as number | null,
    sessionsLoading: false,
    sessionsLoaded: false,
    /** 侧栏发起的查看请求：seq 每次递增，对话页 watch 到变化后重渲染对应会话消息；
     *  fresh=true 表示刚新建的空会话（页面切空白新会话态），id=null 表示无会话可看 */
    sessionView: { id: null, fresh: false, seq: 0 } as {
      id: number | null
      fresh: boolean
      seq: number
    }
  }),
  actions: {
    setAssignmentDateFilter(date: string) {
      this.assignmentDateFilter = date
    },
    // 4.1 错误记录列表（批改列表）
    async fetchErrors(filter: ErrorFilter = {}): Promise<PageResult<TeacherErrorItem>> {
      const { data } = await api.get<PageResult<TeacherErrorItem>>('/api/teacher/errors', { params: filter })
      return data
    },
    // 4.2 一键纠错：修正错因类型 + 备注
    async correctError(errorId: number, payload: { error_type: string; teacher_note?: string }): Promise<GradingError> {
      const { data } = await api.post<GradingError>(`/api/teacher/errors/${errorId}/correct`, payload)
      return data
    },
    // 4.3 高频错题 TopN
    async fetchTopQuestions(n = 10): Promise<TopQuestion[]> {
      const { data } = await api.get<{ n: number; items: TopQuestion[] }>('/api/teacher/stats/top-questions', {
        params: { n }
      })
      return data.items
    },
    // 4.4 知识点错误率排行
    async fetchKnowledgePoints(): Promise<KnowledgePointStat[]> {
      const { data } = await api.get<{ items: KnowledgePointStat[] }>('/api/teacher/stats/knowledge-points')
      return data.items
    },
    // 4.11 班级知识修复率（v0.4.0）：全班口径 + 各知识点修复率
    async fetchRepairRate(): Promise<ClassRepairRate> {
      const { data } = await api.get<ClassRepairRate>('/api/teacher/stats/repair-rate')
      return data
    },
    // 4.5 学生列表
    async fetchStudents(): Promise<StudentSummary[]> {
      const { data } = await api.get<PageResult<StudentSummary>>('/api/teacher/students')
      return data.items
    },
    // 4.6 学生画像查询（结构同 3.10）
    async fetchStudentProfile(id: number): Promise<StudentProfile> {
      const { data } = await api.get<StudentProfile>(`/api/teacher/students/${id}/profile`)
      return data
    },
    // 4.8 已发布作业列表（含每题提交人数，v0.2.0）
    async fetchTeacherAssignments(): Promise<TeacherAssignment[]> {
      const { data } = await api.get<PageResult<TeacherAssignment>>('/api/teacher/assignments')
      return data.items
    },
    // 4.7 发布作业（v0.2.0）
    async createAssignment(payload: TeacherAssignmentInput): Promise<TeacherAssignment> {
      const { data } = await api.post<TeacherAssignment>('/api/teacher/assignments', payload)
      return data
    },
    // 4.10 删除已发布作业（v0.3.0）：后端级联删除题目与学生提交数据
    async deleteAssignment(id: number): Promise<void> {
      await api.delete(`/api/teacher/assignments/${id}`)
    },
    // 4.9 拍照识别题目（v0.2.1）：上传题目照片，返回转写 {question_text, steps} 供填入表单
    async recognizePhoto(file: File): Promise<PhotoTranscribeResult> {
      const form = new FormData()
      form.append('file', file)
      const { data } = await api.post<PhotoTranscribeResult>('/api/teacher/photo-recognize', form, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      return data
    },
    // 4.12 与班级数据助理对话（v0.5.0，LangGraph 教师 Agent；v0.6.0 会话制：可指定
    // session_id，响应含建议追问 suggestions 与实际写入的 session_id）
    async agentChat(message: string, sessionId?: number | null): Promise<AgentChatResult> {
      const { data } = await api.post<AgentChatResult>('/api/teacher/agent/chat', {
        message,
        session_id: sessionId ?? undefined
      })
      return data
    },
    // 4.13 教师对话历史（v0.5.0；v0.6.0 起返回当前会话最近 50 条）
    async fetchAgentHistory(): Promise<AgentHistoryItem[]> {
      const { data } = await api.get<AgentHistoryItem[]>('/api/teacher/agent/history')
      return data
    },
    // 4.19 教师对话会话列表（v0.6.0）：按最近更新倒序，含消息数
    async fetchSessions(): Promise<ChatSession[]> {
      const { data } = await api.get<ChatSession[]>('/api/teacher/agent/sessions')
      return data
    },
    // 4.20 新建教师对话会话（v0.6.0）
    async createSession(): Promise<ChatSession> {
      const { data } = await api.post<ChatSession>('/api/teacher/agent/sessions', {})
      return data
    },
    // 4.21 某会话的全部消息（v0.6.0），时间正序
    async fetchSessionMessages(sessionId: number): Promise<AgentHistoryItem[]> {
      const { data } = await api.get<AgentHistoryItem[]>(
        `/api/teacher/agent/sessions/${sessionId}/messages`
      )
      return data
    },
    // 4.22 删除一条教师对话会话（v0.6.0）
    async deleteSession(sessionId: number): Promise<void> {
      await api.delete(`/api/teacher/agent/sessions/${sessionId}`)
    },
    // 4.14 开始新对话（v0.5.0 新增；v0.6.0 语义变更：新建一条会话，旧会话保留可找回）
    async newAgentSession(): Promise<ChatSession> {
      const { data } = await api.post<ChatSession>('/api/teacher/agent/new-session', {})
      return data
    },
    // ---- 会话区状态层（v0.6.2）：左侧栏会话导航与对话页共用 ----
    /** 拉取会话列表进 store；首次自动定位当前会话 = 最近更新的一条 */
    async loadSessions(force = false) {
      if (this.sessionsLoading) return
      if (this.sessionsLoaded && !force) return
      this.sessionsLoading = true
      try {
        this.sessions = await this.fetchSessions()
        this.sessionsLoaded = true
        if (this.activeSessionId == null) {
          this.activeSessionId = this.sessions[0]?.id ?? null
        }
      } catch (e) {
        console.error(e)
      } finally {
        this.sessionsLoading = false
      }
    },
    setActiveSession(id: number | null) {
      this.activeSessionId = id
    },
    /** 侧栏点「新对话」：新建会话、置顶高亮，并通知对话页切到空白新会话态 */
    async startSidebarSession(): Promise<ChatSession> {
      const s = await this.newAgentSession()
      this.sessions = [s, ...this.sessions.filter((x) => x.id !== s.id)]
      this.activeSessionId = s.id
      this.sessionView = { id: s.id, fresh: true, seq: this.sessionView.seq + 1 }
      return s
    },
    /** 侧栏点选某条会话：通知对话页加载该会话的消息 */
    selectSidebarSession(id: number) {
      if (id === this.activeSessionId) return
      this.activeSessionId = id
      this.sessionView = { id, fresh: false, seq: this.sessionView.seq + 1 }
    },
    /** 侧栏删除会话：删的是当前会话时自动切到最新一条（都没有则空白态），并通知对话页 */
    async removeSidebarSession(id: number) {
      await this.deleteSession(id)
      const wasActive = id === this.activeSessionId
      this.sessions = this.sessions.filter((x) => x.id !== id)
      if (wasActive) {
        this.activeSessionId = this.sessions[0]?.id ?? null
        this.sessionView = {
          id: this.activeSessionId,
          fresh: false,
          seq: this.sessionView.seq + 1
        }
      }
    },
    /** 退出登录时清空会话区状态，避免换人后残留 */
    clearSessionState() {
      this.sessions = []
      this.activeSessionId = null
      this.sessionsLoading = false
      this.sessionsLoaded = false
      this.sessionView = { id: null, fresh: false, seq: 0 }
    },
    // 4.15 上传练习册 PDF 到知识库（v0.5.0，≤30MB）
    async uploadWorkbook(file: File): Promise<Workbook> {
      const form = new FormData()
      form.append('file', file)
      const { data } = await api.post<Workbook>('/api/teacher/workbooks', form, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      return data
    },
    // 4.16 我的练习册知识库（v0.5.0）
    async fetchWorkbooks(): Promise<Workbook[]> {
      const { data } = await api.get<PageResult<Workbook>>('/api/teacher/workbooks')
      return data.items
    },
    // 4.17 删除练习册（v0.5.0）：连文件删；已被作业引用的会解除关联
    async deleteWorkbook(id: number): Promise<void> {
      await api.delete(`/api/teacher/workbooks/${id}`)
    },
    // 4.18 一键提醒未交学生（v0.5.0）：给未提交全部题目的学生发站内提醒，返回提醒人数
    async remindAssignment(id: number): Promise<number> {
      const { data } = await api.post<{ reminded_count: number }>(
        `/api/teacher/assignments/${id}/remind`
      )
      return data.reminded_count
    }
  }
})
