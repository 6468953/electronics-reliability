/**
 * workspace/DeratingTab.tsx — 模块六：降额分析
 *
 * 【降额是什么，为什么它比 MTBF 更"能改"】
 * 降额 = 故意让器件工作在额定值以下（如 25V 电容只用 12V）。它是最便宜、最有效的
 * 可靠性手段，因为不用换料、不用改拓扑，只要改设计选型或散热。
 * 本系统按类别规则逐项判定：工作应力 / 额定值 是否超过规范上限。
 *
 * 【四级判定为什么必须区分「缺数据」】
 *   pass      满足          ratio ≤ 上限 − 余量
 *   marginal  接近上限      上限 − 余量 < ratio ≤ 上限
 *   violation 超限          ratio > 上限
 *   no_data   缺数据        额定值或工作应力读不到
 * 很多工具会把「缺数据」当「满足」——这是最危险的偷懒：报告上写"全部通过"，
 * 实际上一半的件根本没检查。本系统把它单列一档，并在报告里明确计数。
 *
 * 【为什么不能在这一页直接改数值】
 * 降额判定的输入是 BOM 行的额定值与应力值。评估结果是快照，改了 BOM 也不会自动更新。
 * 所以这里的正确流程是：回 BOM 页补录 → 重新评估 → 回来看。页面会提示这一点，
 * 而不是给一个"看起来能改、改完不生效"的假编辑框。
 */

import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Input,
  Row,
  Segmented,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Tooltip,
  message,
} from 'antd'
import { InfoCircleOutlined, ReloadOutlined, ToolOutlined } from '@ant-design/icons'
import Chart from '../../components/Chart'
import { Term } from '../../components/Term'
import { getDerating } from '../../api'
import { DERATING_META, num, pct } from '../../utils/format'

const STRESS_TEXT: Record<string, string> = {
  voltage: '电压',
  current: '电流',
  power: '功率',
  temperature: '温度',
}

/** 把判定状态映射成 antd Tag 颜色 */
const TAG_COLOR: Record<string, string> = {
  pass: 'green',
  marginal: 'gold',
  violation: 'red',
  no_data: 'default',
}

export default function DeratingTab({
  assessmentId,
  onNeedReassess,
}: {
  assessmentId: number | null
  onNeedReassess: () => void
}) {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [filter, setFilter] = useState<string>('problem')
  const [stress, setStress] = useState<string>('all')
  const [kw, setKw] = useState('')

  useEffect(() => {
    if (!assessmentId) {
      setData(null)
      return
    }
    setLoading(true)
    getDerating(assessmentId)
      .then(setData)
      .catch((e) => message.error(e.message))
      .finally(() => setLoading(false))
  }, [assessmentId])

  const s = data?.summary
  const items: any[] = data?.items || []

  const rows = useMemo(() => {
    let r = items
    if (filter === 'problem') r = r.filter((x) => x.verdict === 'violation' || x.verdict === 'marginal')
    else if (filter !== 'all') r = r.filter((x) => x.verdict === filter)
    if (stress !== 'all') r = r.filter((x) => x.stress_type === stress)
    if (kw) {
      const q = kw.toLowerCase()
      r = r.filter((x) => (x.part_number + x.category_name + x.note).toLowerCase().includes(q))
    }
    return r
  }, [items, filter, stress, kw])

  const pieOption = useMemo(() => {
    if (!s) return null
    return {
      tooltip: { trigger: 'item', formatter: '{b}: {c} 项（{d}%）' },
      legend: { bottom: 0, itemHeight: 8, itemWidth: 12, textStyle: { fontSize: 11 } },
      series: [
        {
          type: 'pie',
          radius: ['46%', '70%'],
          center: ['50%', '44%'],
          avoidLabelOverlap: true,
          label: { show: false },
          data: [
            { name: '超限', value: s.violation, itemStyle: { color: '#C0392B' } },
            { name: '接近上限', value: s.marginal, itemStyle: { color: '#D48806' } },
            { name: '缺数据', value: s.no_data, itemStyle: { color: '#BFBFBF' } },
            { name: '满足', value: s.pass, itemStyle: { color: '#1B7F3B' } },
          ],
        },
      ],
    }
  }, [s])

  if (!assessmentId) return <Empty description="还没有评估记录，请先跑一次评估" />

  if (loading && !data) {
    return (
      <div style={{ padding: 60, textAlign: 'center' }}>
        <Spin />
      </div>
    )
  }

  if (!s || !items.length) {
    return (
      <Empty
        description={
          <span>
            本次 BOM 中没有可检查的降额项
            <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
              降额规则按类目匹配（电容看电压、电阻看功率、MOSFET 看 Vds…）。
              如果 BOM 里的器件都没识别出额定值，这里会是空的——先去 BOM 页看"解析预览"。
            </div>
          </span>
        }
      />
    )
  }

  return (
    <div>
      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col xs={12} md={6}>
          <Card size="small" variant="borderless" style={{ background: s.violation ? '#FDF3F2' : '#F7F9FC' }}>
            <Statistic
              title={<Term k="derating">超限项</Term>}
              value={s.violation}
              suffix={`/ ${s.total}`}
              valueStyle={{ fontSize: 22, color: s.violation ? '#C0392B' : '#1B7F3B' }}
            />
            <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
              占 {pct((s.violation_pct ?? 0) / 100, 1)}
            </div>
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small" variant="borderless" style={{ background: '#F7F9FC' }}>
            <Statistic
              title="接近上限"
              value={s.marginal}
              suffix="项"
              valueStyle={{ fontSize: 22, color: s.marginal ? '#D48806' : undefined }}
            />
            <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
              已进入规范余量区间
            </div>
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small" variant="borderless" style={{ background: s.no_data ? '#FAFAFA' : '#F7F9FC' }}>
            <Statistic
              title="缺数据"
              value={s.no_data}
              suffix="项"
              valueStyle={{ fontSize: 22, color: s.no_data ? '#8c8c8c' : undefined }}
            />
            <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
              不代表合格，只是没法判
            </div>
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small" variant="borderless" style={{ background: '#F7F9FC' }}>
            <Statistic
              title="满足"
              value={s.pass}
              suffix="项"
              valueStyle={{ fontSize: 22, color: '#1B7F3B' }}
            />
            <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
              共检查 {s.total} 项应力约束
            </div>
          </Card>
        </Col>
      </Row>

      <Alert
        type={s.violation ? 'error' : s.no_data ? 'warning' : 'success'}
        showIcon
        style={{ marginBottom: 12 }}
        message={s.conclusion}
        description={
          <span style={{ fontSize: 12.5 }}>
            判定口径：工作应力 ÷ 额定值 与规范上限比较。规范上限之上再留"余量带"，
            落在余量带内算「接近上限」（设计上还有调整空间，但已不宽裕）。
          </span>
        }
        action={
          s.no_data > 0 ? (
            <Button
              size="small"
              icon={<ToolOutlined />}
              onClick={() => {
                message.info('请在「① BOM 导入」中补录额定值/应力，然后重新评估')
                onNeedReassess()
              }}
            >
              补录后重算
            </Button>
          ) : undefined
        }
      />

      <Row gutter={12}>
        <Col xs={24} xl={7}>
          <Card
            size="small"
            title="判定分布"
            variant="borderless"
            style={{ border: '1px solid #EEE' }}
            styles={{ body: { paddingTop: 4 } }}
          >
            <Chart option={pieOption as any} height={250} />
            <div style={{ padding: '0 12px 12px' }}>
              <div style={{ fontSize: 11.5, lineHeight: 1.9 }} className="muted">
                规范来源：{data.source_ref || '各类别降额规范整理'}
              </div>
            </div>
          </Card>
        </Col>

        <Col xs={24} xl={17}>
          <Card
            size="small"
            variant="borderless"
            style={{ border: '1px solid #EEE' }}
            title={
              <Space>
                <span>违规清单</span>
                <Tag>{rows.length} / {items.length}</Tag>
              </Space>
            }
            styles={{ body: { padding: 0 } }}
          >
            {/* 筛选条放在表格上方而不是 Card 的 extra 里：
                extra 区域不换行，5+5 个分段项加搜索框在 1500px 屏上会被裁掉。 */}
            <div
              style={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: 8,
                alignItems: 'center',
                padding: '8px 12px',
                borderBottom: '1px solid #F0F0F0',
              }}
            >
              <Segmented
                size="small"
                value={filter}
                onChange={(v) => setFilter(v as string)}
                options={[
                  { label: '待处理', value: 'problem' },
                  { label: '超限', value: 'violation' },
                  { label: '接近', value: 'marginal' },
                  { label: '缺数据', value: 'no_data' },
                  { label: '全部', value: 'all' },
                ]}
              />
              <Segmented
                size="small"
                value={stress}
                onChange={(v) => setStress(v as string)}
                options={[
                  { label: '全部应力', value: 'all' },
                  { label: '电压', value: 'voltage' },
                  { label: '电流', value: 'current' },
                  { label: '功率', value: 'power' },
                  { label: '温度', value: 'temperature' },
                ]}
              />
              <Input.Search
                size="small"
                allowClear
                placeholder="料号/类目"
                style={{ width: 160 }}
                onChange={(e) => setKw(e.target.value)}
              />
            </div>

            <Table
              size="small"
              rowKey={(r: any) => `${r.part_id}-${r.stress_type}`}
              dataSource={rows}
              pagination={rows.length > 20 ? { pageSize: 20, size: 'small' } : false}
              locale={{ emptyText: '没有符合当前筛选条件的检查项' }}
              columns={[
                {
                  title: '零件',
                  dataIndex: 'part_number',
                  width: 160,
                  render: (v: string, r: any) => (
                    <div>
                      <div style={{ fontWeight: 500 }}>{v}</div>
                      <div className="muted" style={{ fontSize: 11.5 }}>
                        {r.category_name} · {r.category_code}
                      </div>
                    </div>
                  ),
                },
                {
                  title: '约束',
                  dataIndex: 'stress_type',
                  width: 78,
                  render: (v: string) => STRESS_TEXT[v] || v,
                },
                {
                  title: '额定值',
                  dataIndex: 'rated_value',
                  width: 92,
                  align: 'right' as const,
                  render: (v: number | null) => (v === null ? <span className="muted">—</span> : num(v, 3)),
                },
                {
                  title: '工作值',
                  dataIndex: 'applied_value',
                  width: 92,
                  align: 'right' as const,
                  render: (v: number | null) => (v === null ? <span className="muted">—</span> : num(v, 3)),
                },
                {
                  title: (
                    <span>
                      比值 / 上限 <Term k="derating" />
                    </span>
                  ),
                  width: 176,
                  render: (_: any, r: any) => {
                    if (r.ratio === null || r.ratio === undefined) {
                      return <span className="muted">无法计算（缺数据）</span>
                    }
                    const color = DERATING_META[r.verdict]?.color || '#8c8c8c'
                    const widthPct = Math.min(100, r.ratio * 100)
                    return (
                      <Tooltip title={`规范上限 ${pct(r.max_ratio, 0)}，余量带起点 ${pct(r.warn_ratio, 0)}`}>
                        <div>
                          {/* 百分比放在条子上方而不是压在条子里：
                              压在深色条上用 mix-blend-mode 反色，浅色主题下反而看不清。 */}
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, lineHeight: '14px' }}>
                            <b style={{ color }}>{pct(r.ratio, 1)}</b>
                            <span className="muted">上限 {pct(r.max_ratio, 0)}</span>
                          </div>
                          <div style={{ position: 'relative', height: 7, background: '#F0F0F0', borderRadius: 4, marginTop: 3 }}>
                            <div
                              style={{
                                width: `${widthPct}%`,
                                height: '100%',
                                background: color,
                                borderRadius: 4,
                                transition: 'width .3s',
                              }}
                            />
                            <div
                              style={{
                                position: 'absolute',
                                left: `${Math.min(99, r.max_ratio * 100)}%`,
                                top: -1,
                                bottom: -1,
                                width: 1.5,
                                background: '#333',
                              }}
                            />
                          </div>
                        </div>
                      </Tooltip>
                    )
                  },
                },
                {
                  title: '判定',
                  dataIndex: 'verdict',
                  width: 92,
                  render: (v: string) => (
                    <Tag color={TAG_COLOR[v]}>{DERATING_META[v]?.text || v}</Tag>
                  ),
                },
                {
                  title: '说明',
                  dataIndex: 'note',
                  // 说明是"规范上限 + 当前值 + 数据来源"拼出来的长句，铺开会把行撑高 5 倍。
                  // 截到 2 行，悬停看全文。
                  render: (v: string) => (
                    <Tooltip title={v} placement="left">
                      <div
                        style={{
                          fontSize: 11.5,
                          color: '#8c8c8c',
                          display: '-webkit-box',
                          WebkitLineClamp: 2,
                          WebkitBoxOrient: 'vertical',
                          overflow: 'hidden',
                        }}
                      >
                        {v}
                      </div>
                    </Tooltip>
                  ),
                },
              ]}
            />
          </Card>
        </Col>
      </Row>

      <Alert
        type="info"
        showIcon
        icon={<InfoCircleOutlined />}
        style={{ marginTop: 12, fontSize: 12.5 }}
        message="关于「缺数据」的处理原则"
        description={
          <>
            {data.disclaimer || '降额规则为工程通行值的整理，具体项目应遵循本单位/客户的降额规范。'}
            <br />
            缺数据的项<strong>不是合格</strong>。报告里会单独列出这类项的清单，评审时应逐条补齐或说明豁免理由。
            {s.no_data > 0 && (
              <Button
                type="link"
                size="small"
                icon={<ReloadOutlined />}
                onClick={onNeedReassess}
                style={{ paddingLeft: 4 }}
              >
                去重新评估
              </Button>
            )}
          </>
        }
      />
    </div>
  )
}
