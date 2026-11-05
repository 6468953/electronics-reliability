/**
 * components/EvaluationLimits.tsx — 「本次评估的局限」
 *
 * 【为什么结果页要专门摆这一块】
 * 页面顶部只有 MTBF 和 PASS/FAIL，很容易被读成一个硬结论。但这份数字的边界
 * 由几件具体的事决定：参数库是不是示例值、有多少零件用了默认温升、
 * 非电子件占了多少 FIT、降额里有多少项压根没法判。
 *
 * 这些都能从结果里现算，不用查文档。放在数字旁边，比写在 README 里有用——
 * 没人会为了看一次评估去翻文档，但一定会看到结果页上多出来的那一行。
 *
 * 【和 PDF 报告附录 C 的关系】
 * 两边算的是同一组指标（后端 report.py 的 _limitations / 这里的前端实现），
 * 保证"屏幕上看得到的"和"打印出来的"说法一致。改一边记得同步另一边。
 */

import { Collapse, Tag, Typography } from 'antd'
import { DATA_QUALITY } from '../utils/format'

type Limit = {
  key: string
  brief: string // 折叠状态下显示的一行摘要
  title: string
  value: string
  impact: string
  tone: 'red' | 'orange' | 'blue'
}

const TONE_COLOR: Record<Limit['tone'], string> = {
  red: '#C0392B',
  orange: '#D48806',
  blue: '#1F3864',
}

/** 从一次评估的完整结果里算出局限性条目。数据缺失时静默跳过，不报错。 */
function computeLimits(data: any): Limit[] {
  const a = data?.assessment || {}
  const meta = data?.param_meta || {}
  const parts: any[] = a.parts || []
  const wearItems: any[] = data?.wear?.items || []
  const derItems: any[] = data?.derating?.items || []
  const totalFit = Number(a.lambda_total_fit || 0)
  const out: Limit[] = []

  // 1) 参数库成色：影响的是「所有数字」，所以排第一条
  const dq = DATA_QUALITY[meta.data_quality] || null
  if (dq) {
    out.push({
      key: 'dq',
      brief: `参数${dq.label}`,
      title: '参数基准值',
      value: dq.label,
      impact: meta.data_quality === 'verified' ? '可作为正式报告依据' : '绝对值不可对外引用，只能做横向比较',
      tone: meta.data_quality === 'verified' ? 'blue' : 'red',
    })
  }

  // 2) 标准未覆盖的非电子件：这部分 FIT 不是标准值
  const nonstd = parts.filter((p) => p.is_standard === false)
  if (nonstd.length) {
    const fit = nonstd.reduce((s, p) => s + Number(p.lambda_part || 0), 0)
    const qty = nonstd.reduce((s, p) => s + Number(p.qty || 0), 0)
    const pct = totalFit ? (fit / totalFit) * 100 : 0
    out.push({
      key: 'nonstd',
      brief: `非电子件占 ${pct.toFixed(0)}%`,
      title: '非电子件（标准未覆盖）',
      value: `${nonstd.length} 行 / ${qty} 件 / ${fit.toFixed(1)} FIT（占 ${pct.toFixed(0)}%）`,
      impact: 'λ 为工程假设值，已按保守方向计入，但不能作定稿依据',
      tone: 'orange',
    })
  }

  // 3) 默认温升：只在应力法下出现（计数法没有温度因子）
  const defaultParts = parts.filter((p) => (p.trace || []).some((s: any) => s.is_default))
  if (defaultParts.length) {
    out.push({
      key: 'default',
      brief: `${defaultParts.length} 个零件用默认温升`,
      title: '默认温升 / 应力',
      value: `${defaultParts.length} / ${parts.length} 个零件`,
      impact: '结温按类别默认值估算，与实际发热可能差 10~20°C，会被温度因子放大',
      tone: 'orange',
    })
  }

  // 4) 置信度口径
  if (Math.abs(Number(meta.confidence_factor_90 ?? 1) - 1) < 1e-9) {
    out.push({
      key: 'ci',
      brief: '中值估计，非置信上限',
      title: '置信度口径',
      value: '90% 置信上限未应用',
      impact: '结果是偏乐观的中值，客户要求按 SR-332 报 UCL 时不满足',
      tone: 'red',
    })
  }

  // 5) 冗余共因
  if ((a.redundancy || []).length) {
    out.push({
      key: 'ccf',
      brief: `${a.redundancy.length} 个并联组未计共因`,
      title: '冗余模型',
      value: `${a.redundancy.length} 个并联组，未计共因失效`,
      impact: '并联收益是上限，实际低于计算值（浪涌、过热会同时打坏冗余件）',
      tone: 'orange',
    })
  }

  // 6) 降额缺数据：缺数据不等于合格，必须单独说
  const nod = derItems.filter((d) => d.verdict === 'no_data')
  if (nod.length) {
    out.push({
      key: 'der',
      brief: `${nod.length} 项降额无法判定`,
      title: '降额判定覆盖',
      value: `${nod.length} / ${derItems.length} 项缺数据，无法判定`,
      impact: '「未判定」不等于「合格」，补额定值或工作值后才算通过',
      tone: 'orange',
    })
  }

  // 7) 磨损输入用了兜底默认
  const dw = wearItems.filter((w) => (w.using_defaults || []).length)
  if (dw.length) {
    out.push({
      key: 'wear',
      brief: `${dw.length} 项磨损用默认值`,
      title: '磨损输入',
      value: `${dw.length} / ${wearItems.length} 项使用兜底默认值`,
      impact: '寿命按保守默认值估算（偏悲观），换 datasheet 实际值后重算',
      tone: 'orange',
    })
  }

  return out
}

export default function EvaluationLimits({ data }: { data: any }) {
  const limits = computeLimits(data)
  if (!limits.length) return null

  const brief = limits.slice(0, 3).map((l) => l.brief).join(' · ')

  return (
    <Collapse
      size="small"
      style={{ marginBottom: 12, background: '#FFFBF5', border: '1px solid #F0E0C8' }}
      items={[
        {
          key: 'limits',
          label: (
            <span style={{ fontSize: 12.5 }}>
              <Tag color="orange" style={{ marginRight: 8 }}>
                读数字前先看
              </Tag>
              本次评估的边界：{brief}
            </span>
          ),
          children: (
            <div>
              {limits.map((l) => (
                <div
                  key={l.key}
                  style={{
                    display: 'flex',
                    gap: 10,
                    padding: '6px 0',
                    borderTop: '1px dashed #F0E0C8',
                    alignItems: 'flex-start',
                  }}
                >
                  <div
                    style={{
                      width: 3,
                      alignSelf: 'stretch',
                      background: TONE_COLOR[l.tone],
                      borderRadius: 2,
                      flex: '0 0 3px',
                    }}
                  />
                  <div style={{ flex: '0 0 130px', fontSize: 12.5, fontWeight: 600 }}>{l.title}</div>
                  <div style={{ flex: '0 0 230px', fontSize: 12.5, color: TONE_COLOR[l.tone] }}>{l.value}</div>
                  <div style={{ flex: 1, fontSize: 12, color: '#595959' }}>{l.impact}</div>
                </div>
              ))}
              <Typography.Paragraph style={{ fontSize: 12, color: '#8C8C8C', margin: '8px 0 0' }}>
                这份清单与 PDF 报告的「附录 C」是同一套算法。把参数库换成标准原表后，
                第一条会自动变成「已按标准原表录入」。
              </Typography.Paragraph>
            </div>
          ),
        },
      ]}
    />
  )
}
