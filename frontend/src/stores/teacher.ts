// 教师端 store：错误记录、一键纠错、班级看板统计、学生画像
// 路径与字段严格对齐 docs/api-contract.md v0.1.0
import { defineStore } from 'pinia'
import api from '../api/client'
import { useAuthStore } from './auth'
import type {
  AgentChatResult,
  AgentHistoryItem,
  ChatSession,
  ClassRepairRate,
  GradingError,
  KnowledgePointStat,
  PageResult,
  PhotoGroupTranscribeResult,
  PhotoTranscribeResult,
  ReviewDetail,
  ReviewPendingItem,
  StudentProfile,
  StudentSummary,
  TeacherDashboardSummary,
  TeacherAssignment,
  TeachingSuggestion,
  TeacherAssignmentInput,
  TeacherErrorItem,
  TeacherErrorSummary,
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

const inFlightAssignmentRequests = new Map<string, Promise<TeacherAssignment[]>>()

function coalesceAssignmentRequest(
  userId: number | undefined,
  load: () => Promise<TeacherAssignment[]>
): Promise<TeacherAssignment[]> {
  const key = userId == null ? 'anonymous' : String(userId)
  const existing = inFlightAssignmentRequests.get(key)
  if (existing) return existing

  const request = Promise.resolve().then(load).finally(() => {
    if (inFlightAssignmentRequests.get(key) === request) {
      inFlightAssignmentRequests.delete(key)
    }
  })
  inFlightAssignmentRequests.set(key, request)
  return request
}

export const useTeacherStore = defineStore('teacher', {
  state: () => ({
    /** 作业管理页的发布日期筛选（v0.3.1）：空 = 全部；由右侧栏日历写入、本页消费 */
    assignmentDateFilter: '',
    /** 待审核队列（v0.9.0）：AI 批改完等老师审核的提交；count 供导航角标，
     *  App.vue 在教师端路由变化时刷新一次 */
    pendingReviews: [] as ReviewPendingItem[],
    pendingReviewCount: 0,
    /** 会话区状态（v0.6.2）：左侧栏会话导航与对话页共用同一份 */
    sessions: [] as ChatSession[],
    activeSessionId: null as number | null,
    sessionsLoading: false,
    sessionsLoaded: false,
    sessionsError: '',
    sessionsLoadPromise: null as Promise<void> | null,
    sessionsRefreshPromise: null as Promise<void> | null,
    sessionsGeneration: 0,
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
    async fetchRecentErrorSummaries(limit = 100): Promise<TeacherErrorSummary[]> {
      const { data } = await api.get<{ items: TeacherErrorSummary[] }>('/api/teacher/errors/summary', {
        params: { limit }
      })
      return data.items
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
    async fetchDashboardSummary(
      n = 10,
      includeSuggestions = false
    ): Promise<TeacherDashboardSummary> {
      const { data } = await api.get<TeacherDashboardSummary>('/api/teacher/dashboard', {
        params: { n, ...(includeSuggestions ? { include_suggestions: true } : {}) }
      })
      return data
    },
    // 教学建议：规则模板生成的建议卡（重讲/预警/分组辅导/巩固练习）
    async fetchSuggestions(): Promise<TeachingSuggestion[]> {
      const { data } = await api.get<TeachingSuggestion[]>('/api/teacher/suggestions')
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
    fetchTeacherAssignments(): Promise<TeacherAssignment[]> {
      const userId = useAuthStore().user?.id
      return coalesceAssignmentRequest(userId, async () => {
        const { data } = await api.get<PageResult<TeacherAssignment>>('/api/teacher/assignments')
        return data.items
      })
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
    // 拍照识别大题（v0.13.11）：一张图拆出共同题干 + 全部小题
    async recognizeGroupPhoto(file: File): Promise<PhotoGroupTranscribeResult> {
      const form = new FormData()
      form.append('file', file)
      const { data } = await api.post<PhotoGroupTranscribeResult>('/api/teacher/photo-recognize-group', form, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      return data
    },
    // 4.12 与班级数据助理对话（v0.5.0，LangGraph 教师 Agent；v0.6.0 会话制：可指定
    // session_id，响应含建议追问 suggestions 与实际写入的 session_id）
    async agentChatStream(
      message: string,
      sessionId: number | null | undefined,
      onCharacter: (character: string) => void
    ): Promise<AgentChatResult> {
      const auth = useAuthStore()
      const response = await fetch(api.getUri({ url: '/api/teacher/agent/chat/stream' }), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(auth.token ? { Authorization: `Bearer ${auth.token}` } : {})
        },
        body: JSON.stringify({ message, session_id: sessionId ?? undefined })
      })

      if (!response.ok) {
        const payload = await response.json().catch(() => null) as { detail?: unknown } | null
        if (response.status === 401) {
          auth.logout()
          if (window.location.pathname !== '/') window.location.href = '/'
        }
        const detail = typeof payload?.detail === 'string' ? payload.detail : ''
        throw new Error(detail || `教师助手请求失败（HTTP ${response.status}）`)
      }

      const reader = response.body?.getReader()
      if (!reader) throw new Error('浏览器无法读取教师助手的流式回复。')
      const decoder = new TextDecoder()
      let buffer = ''
      let result: AgentChatResult | null = null
      const characterQueue: string[] = []
      let queueOffset = 0
      let typingTask: Promise<void> | null = null
      const startTypewriter = () => {
        if (typingTask || queueOffset >= characterQueue.length) return
        typingTask = (async () => {
          while (queueOffset < characterQueue.length) {
            onCharacter(characterQueue[queueOffset++])
            await new Promise<void>((resolve) => window.setTimeout(resolve, 18))
          }
        })().finally(() => {
          typingTask = null
          characterQueue.splice(0, queueOffset)
          queueOffset = 0
          if (characterQueue.length) startTypewriter()
        })
      }
      const waitForTypewriter = async () => {
        while (typingTask) await typingTask
        if (characterQueue.length) {
          startTypewriter()
          await waitForTypewriter()
        }
      }
      const consumeEvent = (block: string) => {
        let eventName = ''
        const dataLines: string[] = []
        for (const line of block.split('\n')) {
          if (!line || line.startsWith(':')) continue
          const separator = line.indexOf(':')
          const field = separator < 0 ? line : line.slice(0, separator)
          let value = separator < 0 ? '' : line.slice(separator + 1)
          if (value.startsWith(' ')) value = value.slice(1)
          if (field === 'event') eventName = value
          else if (field === 'data') dataLines.push(value)
        }
        if (!dataLines.length) return
        const payload = JSON.parse(dataLines.join('\n')) as Record<string, unknown>
        if (eventName === 'token') {
          const text = typeof payload.text === 'string' ? payload.text : ''
          if (text) {
            characterQueue.push(...Array.from(text))
            startTypewriter()
          }
        } else if (eventName === 'done') {
          result = payload as unknown as AgentChatResult
        } else if (eventName === 'error') {
          throw new Error(typeof payload.detail === 'string' ? payload.detail : '回复生成中断，请稍后重试。')
        }
      }

      try {
        while (true) {
          const { value, done } = await reader.read()
          buffer += decoder.decode(value, { stream: !done })
          let boundary = buffer.indexOf('\n\n')
          while (boundary >= 0) {
            consumeEvent(buffer.slice(0, boundary))
            buffer = buffer.slice(boundary + 2)
            boundary = buffer.indexOf('\n\n')
          }
          if (done) break
        }
        if (buffer.trim()) consumeEvent(buffer)
      } catch (error) {
        await waitForTypewriter()
        throw error
      }
      await waitForTypewriter()
      if (!result) throw new Error('教师助手的流式回复没有正常结束，请重试。')
      return result
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
      if (force) {
        if (this.sessionsRefreshPromise) {
          await this.sessionsRefreshPromise
          return
        }
        const generation = this.sessionsGeneration
        const refreshTask = (async () => {
          if (this.sessionsLoadPromise) {
            try {
              await this.sessionsLoadPromise
            } catch {
              // 即使初次请求失败，强制刷新仍继续重试。
            }
          }
          if (generation !== this.sessionsGeneration) return
          await this.fetchSessionsIntoStore()
        })()
        this.sessionsRefreshPromise = refreshTask
        try {
          await refreshTask
        } finally {
          if (this.sessionsRefreshPromise === refreshTask) {
            this.sessionsRefreshPromise = null
          }
        }
        return
      }
      if (this.sessionsLoadPromise) {
        try {
          await this.sessionsLoadPromise
        } catch {
          // 请求失败状态已由 fetchSessionsIntoStore 记录。
        }
        return
      }
      if (this.sessionsLoaded) return

      await this.fetchSessionsIntoStore()
    },
    async fetchSessionsIntoStore() {
      this.sessionsLoading = true
      this.sessionsError = ''
      const generation = this.sessionsGeneration
      const task = (async () => {
        const sessions = await this.fetchSessions()
        if (generation !== this.sessionsGeneration) return
        this.sessions = sessions
        this.sessionsLoaded = true
        const activeExists = this.sessions.some((session) => session.id === this.activeSessionId)
        if (this.activeSessionId == null || !activeExists) {
          this.activeSessionId = this.sessions[0]?.id ?? null
        }
      })()
      this.sessionsLoadPromise = task
      try {
        await task
      } catch (e) {
        if (generation === this.sessionsGeneration) {
          this.sessionsError = '历史对话加载失败，请重试。'
        }
        console.error(e)
      } finally {
        if (this.sessionsLoadPromise === task) {
          this.sessionsLoadPromise = null
          this.sessionsLoading = false
        }
      }
    },
    setActiveSession(id: number | null) {
      this.activeSessionId = id
    },
    /** 侧栏点「新对话」：新建会话、置顶高亮，并通知对话页切到空白新会话态。
     * v0.9.0 防重复：当前激活会话还是空会话（message_count=0）时不再新建，
     * 直接切回它，避免连点攒出一串空会话（会话列表接口已返回 message_count）。 */
    async startSidebarSession(): Promise<ChatSession> {
      const active = this.sessions.find((x) => x.id === this.activeSessionId)
      if (active && active.message_count === 0) {
        this.sessionView = { id: active.id, fresh: true, seq: this.sessionView.seq + 1 }
        return active
      }
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
      this.sessionsGeneration += 1
      this.sessions = []
      this.activeSessionId = null
      this.sessionsLoading = false
      this.sessionsLoaded = false
      this.sessionsError = ''
      this.sessionsLoadPromise = null
      this.sessionsRefreshPromise = null
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
    },
    // 4.23 待审核队列（v0.9.0）：拉全量待审列表并回写角标计数
    async fetchPendingReviews(): Promise<ReviewPendingItem[]> {
      const { data } = await api.get<{ count: number; items: ReviewPendingItem[] }>(
        '/api/teacher/reviews/pending'
      )
      this.pendingReviews = data.items
      this.pendingReviewCount = data.count
      return data.items
    },
    async fetchPendingReviewCount(): Promise<number> {
      const { data } = await api.get<{ count: number }>(
        '/api/teacher/reviews/pending/count'
      )
      this.pendingReviewCount = data.count
      return data.count
    },
    /** 只刷新待审计数（导航角标用，App.vue 路由变化时调用） */
    async refreshPendingReviewCount() {
      try {
        await this.fetchPendingReviewCount()
      } catch (e) {
        console.error(e)
      }
    },
    // 4.24 审核详情（v0.9.0）：完整分步诊断 + 审核状态
    async fetchReviewDetail(submissionId: number): Promise<ReviewDetail> {
      const { data } = await api.get<ReviewDetail>(`/api/teacher/reviews/${submissionId}`)
      return data
    },
    // 4.25 审核通过（v0.9.0）：通过后学生收到提醒并能看到诊断；本地队列同步移除
    // 评分系统：可带 finalScore（老师改分），不带则后端用 AI 初评分落定最终分
    async approveReview(submissionId: number, finalScore?: number): Promise<void> {
      await api.post(
        `/api/teacher/reviews/${submissionId}/approve`,
        finalScore === undefined ? undefined : { final_score: finalScore }
      )
      this.pendingReviews = this.pendingReviews.filter((i) => i.submission_id !== submissionId)
      this.pendingReviewCount = this.pendingReviews.length
    },
    // 4.26 全部通过（v0.9.0）：批量放行当前队列，返回通过条数
    async approveAllReviews(): Promise<number> {
      const { data } = await api.post<{ approved_count: number }>('/api/teacher/reviews/approve-all')
      this.pendingReviews = []
      this.pendingReviewCount = 0
      return data.approved_count
    }
  }
})
