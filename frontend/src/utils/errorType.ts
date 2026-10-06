// 错因三色语义 —— 全局统一的唯一来源
// 计算失误=琥珀 / 概念混淆=红 / 审题遗漏=紫 / 无法解析=灰
// 徽标、图表、时间线全部从这里取色，禁止在各页面硬编码。

export type ErrorTypeKey = 'amber' | 'red' | 'purple' | 'gray'

const ERROR_TYPE_KEY_MAP: Record<string, ErrorTypeKey> = {
  '计算失误': 'amber',
  '概念混淆': 'red',
  '审题遗漏': 'purple',
  '无法解析': 'gray'
}

/** 错因文本 → 三色 key（未知类型兜底为灰） */
export function errorTypeKey(errorType: string): ErrorTypeKey {
  return ERROR_TYPE_KEY_MAP[errorType] ?? 'gray'
}

/** 徽标用 class：badge-amber / badge-red / badge-purple / badge-gray */
export function errorTypeBadgeClass(errorType: string): string {
  return `badge badge-${errorTypeKey(errorType)}`
}

/** 时间线圆点用 class：timeline-dot amber / red / purple / gray */
export function errorTypeDotClass(errorType: string): string {
  return `timeline-dot ${errorTypeKey(errorType)}`
}

/** ECharts 用色（与徽标严格一致） */
export const ERROR_TYPE_CHART_COLORS: Record<ErrorTypeKey, string> = {
  amber: '#D97706',
  red: '#DC2626',
  purple: '#7C3AED',
  gray: '#9CA3AF'
}

/** 按错因枚举顺序返回三色（图表 legend / pie 用） */
export function errorTypePalette(): string[] {
  return ['计算失误', '概念混淆', '审题遗漏', '无法解析'].map((t) => ERROR_TYPE_CHART_COLORS[errorTypeKey(t)])
}

// ---------- 学生端文案伦理 ----------
// 「顽固误区」「疑似」等术语仅教师端可见；学生端一律用鼓励性文案。
// 后端返回的 suggestion / grammar issue 文案可能含术语，前端展示前统一净化。
const STUDENT_COPY_RULES: Array<[RegExp, string]> = [
  [/顽固误区/g, '需要加固的知识点'],
  [/疑似/g, '可能'],
  [/偶发失误/g, '偶发的小失误']
]

/** 学生端文案净化：去掉贴标签术语，换成鼓励口径 */
export function sanitizeStudentCopy(text: string): string {
  let out = text
  for (const [re, replacement] of STUDENT_COPY_RULES) {
    out = out.replace(re, replacement)
  }
  return out
}
