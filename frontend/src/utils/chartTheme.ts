export interface ChartColors {
  primary: string
  amber: string
  green: string
  gray: string
  textStrong: string
  textMuted: string
  border: string
  surface: string
  radiusDetail: number
}

const FALLBACK_COLORS: ChartColors = {
  primary: '#1D4ED8',
  amber: '#D97706',
  green: '#059669',
  gray: '#9CA3AF',
  textStrong: '#4B5563',
  textMuted: '#6B7280',
  border: '#E5E7EB',
  surface: '#FFFFFF',
  radiusDetail: 6,
}

export function readChartColors(): ChartColors {
  if (typeof window === 'undefined' || typeof document === 'undefined') return FALLBACK_COLORS

  const styles = window.getComputedStyle(document.documentElement)
  const read = (token: string, fallback: string) => styles.getPropertyValue(token).trim() || fallback
  const radiusDetail = Number.parseFloat(read('--radius-detail', `${FALLBACK_COLORS.radiusDetail}px`))

  return {
    primary: read('--primary', FALLBACK_COLORS.primary),
    amber: read('--amber', FALLBACK_COLORS.amber),
    green: read('--green', FALLBACK_COLORS.green),
    gray: read('--text-3', FALLBACK_COLORS.gray),
    textStrong: read('--text-strong', FALLBACK_COLORS.textStrong),
    textMuted: read('--text-2', FALLBACK_COLORS.textMuted),
    border: read('--border', FALLBACK_COLORS.border),
    surface: read('--card', FALLBACK_COLORS.surface),
    radiusDetail: Number.isFinite(radiusDetail) ? radiusDetail : FALLBACK_COLORS.radiusDetail,
  }
}
