/**
 * utils/format.ts — 数值与文案格式化
 *
 * 【为什么集中在一处】
 * "MTBF 该显示几位小数""R(t) 用百分数还是小数"这类问题，如果各页面各写一套，
 * 用户会在两张表里看到同一个数一个显示 0.9954、另一个显示 99.54%，非常混乱。
 */

export function num(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  if (Math.abs(v) >= 10000) return v.toLocaleString('zh-CN', { maximumFractionDigits: 0 })
  return v.toFixed(digits)
}

export function int(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return Math.round(v).toLocaleString('zh-CN')
}

export function pct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return '—'
  return `${(v * 100).toFixed(digits)}%`
}

export function mtbfText(hours: number | null | undefined): string {
  if (hours === null || hours === undefined) return '∞'
  if (hours >= 8760) return `${Math.round(hours).toLocaleString('zh-CN')} h`
  return `${Math.round(hours).toLocaleString('zh-CN')} h`
}

export function mtbfYears(hours: number | null | undefined): string {
  if (!hours) return '—'
  const y = hours / 8760
  return y >= 1 ? `≈ ${y.toFixed(1)} 年连续运行` : `≈ ${(y * 12).toFixed(1)} 个月连续运行`
}

export const VERDICT_META: Record<string, { color: string; text: string; tag: 'success' | 'error' | 'default' }> = {
  PASS: { color: '#1B7F3B', text: '通过', tag: 'success' },
  FAIL: { color: '#C0392B', text: '不通过', tag: 'error' },
  NA: { color: '#8c8c8c', text: '未判定', tag: 'default' },
}

export const DERATING_META: Record<string, { color: string; text: string }> = {
  pass: { color: '#1B7F3B', text: '满足' },
  marginal: { color: '#D48806', text: '接近上限' },
  violation: { color: '#C0392B', text: '超限' },
  no_data: { color: '#8c8c8c', text: '缺数据' },
}

export const MODE_TEXT: Record<string, string> = {
  parts_count: '零件计数法',
  parts_stress: '零件应力法',
}

export const STANDARD_TEXT: Record<string, string> = {
  'MIL-217F': 'MIL-HDBK-217F',
  TELCORDIA_SR332: 'Telcordia SR-332',
}

/** 敏感度排序里各假设的中文名（后端已经给了，但表格里需要更短的标签）。 */
export const VARIABLE_TEXT: Record<string, string> = {
  ambient_temp: '环境温度',
  quality_level: '质量等级',
  duty_cycle: '日通电占比',
  environment: '环境类别',
}
