// 订正追踪（MVP 本地记录）
// 契约未提供"订正记录查询"接口：学生提交订正且判定正确（is_correct=true）后，
// 仅本次浏览器可知。localStorage 记录 userId → 已修复 errorId 集合，
// 供「我的档案」时间线展示修复状态「已修复 / 加固中」。
// 最小假设：换设备/清缓存后状态回退为「加固中」。

function storageKey(userId: number | string): string {
  return `remedi_fixed_errors_${userId}`
}

/** 标记某条 error 已订正正确 */
export function markErrorFixed(userId: number | string, errorId: number): void {
  try {
    const ids = getFixedErrorIds(userId)
    ids.add(errorId)
    localStorage.setItem(storageKey(userId), JSON.stringify([...ids]))
  } catch {
    /* 存储不可用时静默忽略 */
  }
}

/** 取出该用户已修复的 errorId 集合 */
export function getFixedErrorIds(userId: number | string): Set<number> {
  try {
    const raw = localStorage.getItem(storageKey(userId))
    const arr = raw ? (JSON.parse(raw) as unknown) : []
    return new Set(Array.isArray(arr) ? arr.filter((n) => typeof n === 'number') : [])
  } catch {
    return new Set()
  }
}
