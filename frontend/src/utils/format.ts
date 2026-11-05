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

/**
 * 参数库的数据成色。
 *
 * 【为什么界面必须显示这个】
 * 「算法算对了」和「喂进去的数字是真的」是两件事。如果两者在界面上长得一模一样，
 * 用户会默认结果是照标准算的。把这个标记摆在参数库页和结果页，是为了让
 * 「现在这版数字只能做相对比较，不能对外报」这件事一眼可见，不靠人记。
 */
export const DATA_QUALITY: Record<string, { label: string; color: string; hint: string }> = {
  verified: {
    label: '已按标准原表录入',
    color: 'green',
    hint: '参数取自标准正本，可用于正式报告',
  },
  partial: {
    label: '部分类目已录入',
    color: 'orange',
    hint: '部分类目仍是示例值，结论按最弱的一环打折',
  },
  demo: {
    label: '示例量级',
    color: 'red',
    hint: '未按标准原表录入，绝对值不可对外引用，只可用于横向比较',
  },
}
