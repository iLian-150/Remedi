// 学生端 store：作业、提交诊断、作文、订正、学习画像
// 路径与字段严格对齐 docs/api-contract.md v0.1.0
import { defineStore } from 'pinia'
import api from '../api/client'
import { useAuthStore } from './auth'
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
  PhotoReviewResult,
  PhotoTranscribeResult,
  RelatedMistake,
  StudentBriefing,
  StudentProfile,
  StudentMistake,
  SubjectReport,
  ReportScores,
  SubmissionResult,
  SubmissionSummary,
  Verification,
  VerificationSubmitResult
} from '../api/types'

function activeSessionStorageKey(): string | null {
  const userId = useAuthStore().user?.id
  return userId == null ? null : `remedi_student_active_session_${userId}`
}

function persistActiveSessionId(id: number | null) {
  const key = activeSessionStorageKey()
  if (!key) return
  if (id == null) localStorage.removeItem(key)
  else localStorage.setItem(key, String(id))
}

export const useStudentStore = defineStore('student', {
  state: () => ({
    /** 作业列表页的发布日期筛选（v0.3.1）：空 = 全部；由右侧栏日历写入、本页消费 */
    assignmentDateFilter: '',
    /** 订正页的错题日期筛选（v0.9.1）：空 = 全部；由右侧栏「订正日历」写入、订正页消费
     * （v0.9.0 曾在订正页页内放日历，v0.9.1 迁入右栏，与作业日历同构） */
    correctionsDateFilter: '',
    /** 提醒未读数（v0.8.2）：单一事实来源——App.vue 路由变化时刷新、RightRail 读写后回写，
     *  右栏收起态的提醒 FAB 角标直接读这里，不再靠 RightRail 的 emit 传递 */
    unreadCount: 0,
    /** 错题本里尚未学会的错误类别数；由错题复习侧栏按实际记录刷新。 */
    mistakeReviewCount: 0,
    /** 会话区状态（v0.6.2）：左侧栏会话导航与对话页共用同一份 */
    sessions: [] as ChatSession[],
    activeSessionId: null as number | null,
    sessionsLoading: false,
    sessionsLoaded: false,
    sessionsLoadPromise: null as Promise<void> | null,
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
    setCorrectionsDateFilter(date: string) {
      this.correctionsDateFilter = date
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
    // 错题本：全部诊断错误，附作业、分类、订正与历史同类错误
    async fetchMyMistakes(archived = false): Promise<StudentMistake[]> {
      const { data } = await api.get<StudentMistake[]>('/api/student/mistakes', { params: { archived } })
      return data
    },
    async fetchRelatedMistake(questionId: number): Promise<RelatedMistake | null> {
      const { data } = await api.get<RelatedMistake | null>(
        `/api/student/questions/${questionId}/related-mistake`
      )
      return data
    },
    /** 可订正错题（v0.9.1 抽到 store 供订正页与右栏订正日历共用）：
     * 合并未归档+已归档并按 id 去重，只留诊断产生的错题——自主收录题
     * （id<0 / source_kind=student_saved）没有 errors 记录，进不了订正判定。
     * 低置信错题会立即进入错题本，并带有 review_status=pending 标记。 */
    async fetchCorrectableMistakes(): Promise<StudentMistake[]> {
      const [current, archived] = await Promise.all([
        this.fetchMyMistakes(false),
        this.fetchMyMistakes(true)
      ])
      const merged = [...new Map([...current, ...archived].map((item) => [item.id, item])).values()]
      return merged.filter((item) => item.id > 0 && item.source_kind !== 'student_saved')
    },
    async setMistakeCategoryStudied(payload: {
      assignment_id: number
      category_key: string
      studied: boolean
    }): Promise<void> {
      await api.patch('/api/student/mistakes/categories', payload)
    },
    async setMistakeArchived(errorId: number, archived: boolean): Promise<void> {
      await api.patch(`/api/student/mistakes/${errorId}/archive`, { archived })
    },
    async setMistakeAssignmentArchived(assignmentId: number, archived: boolean, occurrenceIds: number[] = []): Promise<number[]> {
      const { data } = await api.patch<{ archived_ids: number[] }>(
        `/api/student/mistakes/assignments/${assignmentId}/archive`,
        { archived, occurrence_ids: occurrenceIds }
      )
      return data.archived_ids
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
    async reviewPhoto(
      file: File,
      questionId?: number | null,
      questionContext = '',
      sessionId?: number | null,
      saveToChat = false,
      chatPrompt = ''
    ): Promise<PhotoReviewResult> {
      const form = new FormData()
      form.append('file', file)
      if (questionId) form.append('question_id', String(questionId))
      if (questionContext) form.append('question_context', questionContext)
      if (saveToChat) {
        form.append('save_to_chat', 'true')
        if (sessionId) form.append('chat_session_id', String(sessionId))
        if (chatPrompt) form.append('chat_prompt', chatPrompt)
      }
      const { data } = await api.post<PhotoReviewResult>('/api/student/photo-review', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
        // 视觉模型等待上限 120 秒，与后端统一配置保持一致。
        timeout: 120000
      })
      return data
    },
    async savePhotoCapture(captureId: number, explanation: string): Promise<void> {
      await api.post(`/api/student/photo-captures/${captureId}/save`, { explanation })
    },
    async saveTextQuestion(questionText: string, subject = 'math', explanation = ''): Promise<void> {
      await api.post('/api/student/question-captures', {
        question_text: questionText,
        subject,
        explanation
      })
    },
    // 3.13 学习报告（v0.2.1）：按科目聚合 + 知识点状态
    async fetchReport(): Promise<SubjectReport[]> {
      const { data } = await api.get<SubjectReport[]>('/api/student/report')
      return data
    },
    // 评分系统：报告成绩分析（历次作业得分序列 + 学科/总体平均得分率）
    async fetchReportScores(): Promise<ReportScores> {
      const { data } = await api.get<ReportScores>('/api/student/report/scores')
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
    async agentChatStream(
      message: string,
      sessionId: number | null | undefined,
      onText: (text: string) => void,
      persistUserMessage = true,
      safeToolsOnly = false
    ): Promise<AgentChatResult> {
      const auth = useAuthStore()
      const response = await fetch(api.getUri({ url: '/api/student/agent/chat/stream' }), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(auth.token ? { Authorization: `Bearer ${auth.token}` } : {})
        },
        body: JSON.stringify({
          message,
          session_id: sessionId ?? undefined,
          persist_user_message: persistUserMessage,
          safe_tools_only: safeToolsOnly
        })
      })

      if (!response.ok) {
        const payload = await response.json().catch(() => null) as { detail?: unknown } | null
        if (response.status === 401) {
          auth.logout()
          if (window.location.pathname !== '/') window.location.href = '/'
        }
        const detail = typeof payload?.detail === 'string' ? payload.detail : ''
        throw new Error(detail || `学习助手请求失败（HTTP ${response.status}）`)
      }

      const reader = response.body?.getReader()
      if (!reader) throw new Error('浏览器无法读取学习助手的流式回复。')
      const decoder = new TextDecoder()
      let buffer = ''
      let result: AgentChatResult | null = null

      const consumeEvent = async (block: string) => {
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
            // 后端按 token 推送；前端再按字符呈现，避免整段突然出现。
            for (const character of Array.from(text)) {
              onText(character)
              await new Promise<void>((resolve) => window.setTimeout(resolve, 12))
            }
          }
        } else if (eventName === 'done') {
          result = payload as unknown as AgentChatResult
        } else if (eventName === 'error') {
          throw new Error(typeof payload.detail === 'string' ? payload.detail : '回复生成中断，请稍后重试。')
        }
      }

      while (true) {
        const { value, done } = await reader.read()
        buffer += decoder.decode(value, { stream: !done })
        let boundary = buffer.indexOf('\n\n')
        while (boundary >= 0) {
          await consumeEvent(buffer.slice(0, boundary))
          buffer = buffer.slice(boundary + 2)
          boundary = buffer.indexOf('\n\n')
        }
        if (done) break
      }
      if (buffer.trim()) await consumeEvent(buffer)
      if (!result) throw new Error('学习助手的流式回复没有正常结束，请重试。')
      return result
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
    // ---- 会话区状态层（v0.6.2）：左侧栏会话导航与对话页共用 ----
    /** 拉取会话列表进 store；首次自动定位当前会话 = 最近更新的一条 */
    async loadSessions(force = false) {
      if (this.sessionsLoadPromise) {
        try {
          await this.sessionsLoadPromise
        } catch {
          // 让强制刷新继续重试；普通并发调用复用这次结果即可。
        }
        if (!force) return
      }
      if (this.sessionsLoaded && !force) return
      this.sessionsLoading = true
      const task = (async () => {
        this.sessions = await this.fetchSessions()
        this.sessionsLoaded = true
        const activeExists = this.sessions.some((session) => session.id === this.activeSessionId)
        if (this.activeSessionId == null || !activeExists) {
          const key = activeSessionStorageKey()
          const savedId = key ? Number(localStorage.getItem(key)) : NaN
          this.activeSessionId = this.sessions.some((session) => session.id === savedId)
            ? savedId
            : this.sessions[0]?.id ?? null
          persistActiveSessionId(this.activeSessionId)
        }
      })()
      this.sessionsLoadPromise = task
      try {
        await task
      } catch (e) {
        console.error(e)
      } finally {
        if (this.sessionsLoadPromise === task) {
          this.sessionsLoadPromise = null
          this.sessionsLoading = false
        }
      }
    },
    /** 首次发送消息时提前准备会话，让左侧历史列表在 AI 长耗时处理期间也能显示当前对话。 */
    async ensureActiveChatSession(): Promise<number> {
      if (!this.sessionsLoaded) await this.loadSessions()
      const active = this.sessions.find((session) => session.id === this.activeSessionId)
        ?? this.sessions[0]
      if (active) {
        this.activeSessionId = active.id
        persistActiveSessionId(active.id)
        return active.id
      }
      const session = await this.createSession()
      this.sessions = [session, ...this.sessions.filter((item) => item.id !== session.id)]
      this.activeSessionId = session.id
      this.sessionsLoaded = true
      persistActiveSessionId(session.id)
      return session.id
    },
    setActiveSession(id: number | null) {
      this.activeSessionId = id
      persistActiveSessionId(id)
    },
    /** 侧栏点「新对话」：新建会话、置顶高亮，并通知对话页切到空白新会话态。
     * v0.9.0 防重复：当前激活会话还是空会话（message_count=0）时不再新建，
     * 直接切回它，避免连点攒出一串空会话（会话列表接口已返回 message_count）。 */
    async startSidebarSession(): Promise<ChatSession> {
      const active = this.sessions.find((x) => x.id === this.activeSessionId)
      if (active && active.message_count === 0) {
        this.sessionView = { id: active.id, fresh: true, seq: this.sessionView.seq + 1 }
        persistActiveSessionId(active.id)
        return active
      }
      const s = await this.newAgentSession()
      this.sessions = [s, ...this.sessions.filter((x) => x.id !== s.id)]
      this.activeSessionId = s.id
      persistActiveSessionId(s.id)
      this.sessionView = { id: s.id, fresh: true, seq: this.sessionView.seq + 1 }
      return s
    },
    /** 侧栏点选某条会话：通知对话页加载该会话的消息 */
    selectSidebarSession(id: number) {
      if (id === this.activeSessionId) return
      this.activeSessionId = id
      persistActiveSessionId(id)
      this.sessionView = { id, fresh: false, seq: this.sessionView.seq + 1 }
    },
    /** 侧栏删除会话：删的是当前会话时自动切到最新一条（都没有则空白态），并通知对话页 */
    async removeSidebarSession(id: number) {
      await this.deleteSession(id)
      const wasActive = id === this.activeSessionId
      this.sessions = this.sessions.filter((x) => x.id !== id)
      if (wasActive) {
        this.activeSessionId = this.sessions[0]?.id ?? null
        persistActiveSessionId(this.activeSessionId)
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
      persistActiveSessionId(null)
      this.sessionsLoading = false
      this.sessionsLoaded = false
      this.sessionView = { id: null, fresh: false, seq: 0 }
    },
    /** 退出登录时重置提醒未读数（v0.8.2），避免换人登录后角标残留 */
    resetUnread() {
      this.unreadCount = 0
    },
    /** 刷新未读数（v0.8.2）：只取计数不取列表，进任意学生页面时由 App.vue 调用 */
    async refreshUnread() {
      try {
        const res = await this.fetchNotifications()
        this.unreadCount = res.unread_count
      } catch (e) {
        console.error(e)
      }
    },
    // 3.17 我的提醒列表（v0.3.0）：最近 30 条倒序 + 未读数（v0.8.2 起同步回写 unreadCount）
    async fetchNotifications(): Promise<NotificationList> {
      const { data } = await api.get<NotificationList>('/api/student/notifications')
      this.unreadCount = data.unread_count
      return data
    },
    // 3.18 提醒标已读（v0.3.0）：ids 不传 = 全部标已读（v0.8.2 起同步回写 unreadCount）
    async markNotificationsRead(ids?: number[]): Promise<{ updated: number; unread_count: number }> {
      const { data } = await api.post<{ updated: number; unread_count: number }>(
        '/api/student/notifications/read',
        ids && ids.length ? { ids } : {}
      )
      this.unreadCount = data.unread_count
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
