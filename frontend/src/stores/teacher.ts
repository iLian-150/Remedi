// 教师端 store：错误记录、一键纠错、班级看板统计、学生画像
// 路径与字段严格对齐 docs/api-contract.md v0.1.0
import { defineStore } from 'pinia'
import api from '../api/client'
import type {
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
  TopQuestion
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
    assignmentDateFilter: ''
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
    }
  }
})
