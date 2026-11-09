import type { QuestionSubject } from '../api/types'

export const SUBJECT_LABELS: Record<QuestionSubject, string> = {
  math: '数学',
  english: '英语',
  english_exercise: '英语练习',
  physics: '物理',
  chemistry: '化学',
  biology: '生物',
  chinese: '语文',
  history: '历史',
  geography: '地理',
  politics: '道德与法治',
  computer_science: '信息科技',
  art: '艺术',
  music: '音乐',
  pe: '体育',
  other: '其他',
}

export const SUBJECT_OPTIONS = (Object.keys(SUBJECT_LABELS) as QuestionSubject[])
  .map((value) => ({ value, label: SUBJECT_LABELS[value] }))

export function getSubjectLabel(subject: string | null | undefined, fallback = '其他'): string {
  if (!subject) return fallback
  return SUBJECT_LABELS[subject as QuestionSubject] ?? fallback
}
