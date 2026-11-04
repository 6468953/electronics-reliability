/**
 * workspace/WearTab.tsx — 模块五：磨损件寿命估算
 *
 * 【这一屏要纠正一个最常见的误解】
 * 「MTBF 40 万小时」不等于「能用 45 年」。
 * MTBF 描述的是<随机失效>的平均间隔（指数分布，风险率恒定）；
 * 而电解电容干涸、风扇轴承磨损、继电器触点烧蚀、LED 光衰，是<耗损失效>——
 * 它们的风险随时间上升，到点必坏，且与"平均间隔"无关。
 *
 * 所以这一屏把两个视角并排摆出来（双轨），再给一句"谁先到"的结论：
 *     整机预计寿命 = min(随机失效视角, 最短磨损件)
 * 这也是可靠性工程里浴盆曲线后两段的标准处理方式。
 *
 * 【措辞纪律（重要）】
 * 页面里刻意不写「本品寿命 X 年」，只写「在假设条件下，某机理预计 X 年后导致失效」。
 * 因为磨损模型的输入（额定寿命、使用频次、环境温度）本身就是假设，
 * 说成"能用 X 年"是过度承诺，会被现场数据打脸。
 */

import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Card,
  Col,
  Empty,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import { ClockCircleOutlined, FireOutlined, InfoCircleOutlined } from '@ant-design/icons'
import Chart from '../../components/Chart'
import { Term } from '../../components/Term'
import { getWear } from '../../api'
import { int, num } from '../../utils/format'

export default function WearTab({ assessmentId }: { assessmentId: number | null }) {
  const [wear, setWear] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [group, setGroup] = useState<string>('all')

  useEffect(() => {
    if (!assessmentId) {
      setWear(null)
      return
    }
    setLoading(true)
    getWear(assessmentId)
      .then(setWear)
      .catch((e) => message.error(e.message))
      .finally(() => setLoading(false))
  }, [assessmentId])

  const items: any[] = wear?.items || []

  const mechanisms = useMemo(() => {
    const m: Record<string, string> = {}
    items.forEach((it) => {
      m[it.mechanism_label] = it.mechanism_label
    })
    return Object.keys(m)
  }, [items])

  const rows = useMemo(
    () => (group === 'all' ? items : items.filter((it) => it.mechanism_label === group)),
    [items, group],
  )

  const timelineOption = useMemo(() => {
    if (!wear) return null
    const data = [
      {
        name: '随机失效视角',
        value: wear.t_random_years ?? 0,
        color: wear.mechanism_kind === 'random' ? '#C0392B' : '#3A6EA5',
        desc: '按 R(t) 达到目标存活率反推',
      },
      {
        name: '磨损最短件',
        value: wear.t_wear_years ?? 0,
        color: wear.mechanism_kind === 'wear' ? '#C0392B' : '#61DDAA',
        desc: wear.limiting_mechanism,
      },
      {
        name: '目标年限',
        value: wear.target_years ?? 0,
        color: '#8c8c8c',
        desc: '项目设定的设计寿命要求',
      },
    ]
    return {
      grid: { left: 96, right: 90, top: 16, bottom: 32 },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: (ps: any) => {
          const p = ps[0]
          const d = data[p.dataIndex]
          return `<b>${d.name}</b><br/>${num(d.value, 2)} 年<br/><span style="opacity:.7">${d.desc}</span>`
        },
      },
      xAxis: { type: 'value', name: '年', splitLine: { lineStyle: { type: 'dashed' } } },
      yAxis: { type: 'category', data: data.map((d) => d.name) },
      series: [
        {
          type: 'bar',
          barMaxWidth: 26,
          data: data.map((d) => ({ value: d.value, itemStyle: { color: d.color, borderRadius: [0, 4, 4, 0] } })),
          label: {
            show: true,
            position: 'right',
            formatter: (p: any) => `${num(p.value, 2)} 年`,
            fontSize: 11,
          },
          markLine: {
            symbol: 'none',
            silent: true,
            lineStyle: { type: 'dashed', color: '#C0392B' },
            data: [{ xAxis: wear.t_system_years ?? 0 }],
            label: { formatter: '整机结论', fontSize: 10, position: 'insideEndTop' },
          },
        },
      ],
    }
  }, [wear])

  if (!assessmentId) return <Empty description="还没有评估记录，请先跑一次评估" />

  if (loading && !wear) {
    return (
      <div style={{ padding: 60, textAlign: 'center' }}>
        <Spin />
      </div>
    )
  }

  if (!wear || !items.length) {
    return (
      <Empty
        description={
          <span>
            本次 BOM 中没有识别出<strong>有磨损机理</strong>的零件
            <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
              磨损模型覆盖：铝电解电容、风扇、继电器、开关、连接器、LED、电源模块、薄膜电容。
              若 BOM 里有这些件却没识别出来，通常是分类未确认或描述里缺额定参数。
            </div>
          </span>
        }
      />
    )
  }

  const isWearLimited = wear.mechanism_kind === 'wear'

  return (
    <div>
      {/* ---- 结论 ---- */}
      <Alert
        type={isWearLimited ? 'warning' : 'success'}
        showIcon
        icon={isWearLimited ? <FireOutlined /> : <ClockCircleOutlined />}
        style={{ marginBottom: 12 }}
        message={
          <span style={{ fontSize: 13.5 }}>
            整机预计可用寿命约 <b>{num(wear.t_system_years, 1)} 年</b>，由「{wear.limiting_mechanism}」决定
          </span>
        }
        description={<span style={{ fontSize: 12.5 }}>{wear.conclusion}</span>}
      />

      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col xs={12} md={6}>
          <Card size="small" variant="borderless" style={{ background: '#F7F9FC' }}>
            <Statistic
              title={<Term k="mtbf">随机失效视角</Term>}
              value={wear.t_random_years === null ? '∞' : num(wear.t_random_years, 1)}
              suffix="年"
              valueStyle={{ fontSize: 22, color: wear.mechanism_kind === 'random' ? '#C0392B' : undefined }}
            />
            <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
              R(t) 达到目标存活率的年限
            </div>
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small" variant="borderless" style={{ background: '#F7F9FC' }}>
            <Statistic
              title={<Term k="l10">磨损视角（最短）</Term>}
              value={wear.t_wear_years === null ? '∞' : num(wear.t_wear_years, 1)}
              suffix="年"
              valueStyle={{ fontSize: 22, color: wear.mechanism_kind === 'wear' ? '#C0392B' : undefined }}
            />
            <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
              共 {wear.wear_count} 个磨损件
            </div>
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small" variant="borderless" style={{ background: '#FDF3F2' }}>
            <Statistic
              title="整机结论（取小）"
              value={num(wear.t_system_years, 1)}
              suffix="年"
              valueStyle={{ fontSize: 22, color: '#C0392B' }}
            />
            <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
              min(随机, 磨损)
            </div>
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small" variant="borderless" style={{ background: '#F7F9FC' }}>
            <Statistic
              title="目标年限"
              value={wear.target_years}
              suffix="年"
              valueStyle={{ fontSize: 22 }}
            />
            <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
              {wear.t_system_years !== null && wear.t_system_years >= wear.target_years
                ? '结论 ≥ 目标，余量充足'
                : '结论 < 目标，需改进'}
            </div>
          </Card>
        </Col>
      </Row>

      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col xs={24} xl={10}>
          <Card
            size="small"
            title="双轨时间轴：谁先到？"
            variant="borderless"
            style={{ border: '1px solid #EEE' }}
            styles={{ body: { paddingTop: 6 } }}
          >
            <Chart option={timelineOption as any} height={190} />
            <div className="muted" style={{ fontSize: 11.5, padding: '0 10px 8px' }}>
              两条轨道是<strong>竞争关系</strong>，不是叠加关系：产品因为最先发生的那个机理而失效。
              红色条即限制项。
            </div>
          </Card>
        </Col>
        <Col xs={24} xl={14}>
          <Card
            size="small"
            title="为什么不能用 MTBF 当寿命"
            variant="borderless"
            style={{ border: '1px solid #EEE' }}
          >
            <Typography.Paragraph style={{ fontSize: 12.5, marginBottom: 8 }}>
              <b>MTBF</b> 假设失效率是常数（指数分布）。它回答「多久坏一次」，前提是"没有耗损"。
              这个假设对电阻、陶瓷电容基本成立，对电解电容、风扇、继电器完全不成立。
            </Typography.Paragraph>
            <Typography.Paragraph style={{ fontSize: 12.5, marginBottom: 8 }}>
              <b>磨损寿命</b> 用的是机理模型：电解电容按 10°C 法则（温度每降 10°C 寿命翻倍）、
              风扇按 L10 轴承寿命、继电器按动作次数、LED 按 L70 光衰、连接器按插拔次数。
              这些是"到点必坏"，不是"平均会坏"。
            </Typography.Paragraph>
            <Typography.Paragraph style={{ fontSize: 12.5, marginBottom: 0 }} type="secondary">
              所以报告里的正确写法是：随机失效视角 X 年存活率 R%，最短磨损机理为某件的某机理，预计 Y 年后失效。
              两者取小才是"这台设备实际能撑多久"的估计。
            </Typography.Paragraph>
          </Card>
        </Col>
      </Row>

      {/* ---- 排行榜 ---- */}
      <Card
        size="small"
        title={
          <Space>
            <span>磨损件寿命排行榜</span>
            <Tag>{items.length} 项</Tag>
          </Space>
        }
        extra={
          // 用 Select 而不是 Segmented：机理有 8 类，Segmented 在 1500px 屏上也会溢出被裁掉。
          <Select
            size="small"
            style={{ width: 200 }}
            value={group}
            onChange={setGroup}
            options={[{ value: 'all', label: `全部机理（${items.length}）` }, ...mechanisms.map((m) => ({ value: m, label: m }))]}
          />
        }
        variant="borderless"
        style={{ border: '1px solid #EEE' }}
        styles={{ body: { padding: 0 } }}
      >
        <Table
          size="small"
          rowKey="part_id"
          dataSource={rows}
          pagination={rows.length > 15 ? { pageSize: 15, size: 'small' } : false}
          expandable={{
            expandedRowRender: (r: any) => (
              <div style={{ fontSize: 12, lineHeight: 1.9 }}>
                <div>
                  <b>模型：</b>
                  <code style={{ color: '#3A6EA5' }}>{r.formula}</code>
                </div>
                <div>
                  <b>代入值：</b>
                  {Object.entries(r.inputs || {})
                    .map(([k, v]) => `${k} = ${v}`)
                    .join('，')}
                </div>
                {r.using_defaults?.length > 0 && (
                  <div style={{ color: '#D48806' }}>
                    <b>使用了默认值：</b>
                    {r.using_defaults.join('、')}
                    <span className="muted">（建议在 BOM 明细里补录，或直接在描述中写清）</span>
                  </div>
                )}
                {r.note && (
                  <div className="muted">
                    <b>说明：</b>
                    {r.note}
                  </div>
                )}
              </div>
            ),
          }}
          columns={[
            {
              title: '',
              width: 42,
              render: (_: any, r: any, i: number) =>
                r.is_limiting ? (
                  <Tooltip title="全机最短寿命（限制项）">
                    <FireOutlined style={{ color: '#C0392B' }} />
                  </Tooltip>
                ) : (
                  <span className="muted">{i + 1}</span>
                ),
            },
            {
              title: '零件',
              dataIndex: 'part_number',
              width: 170,
              render: (v: string, r: any) => (
                <div>
                  <div style={{ fontWeight: 500 }}>{v}</div>
                  <div className="muted" style={{ fontSize: 11.5 }}>
                    {r.description}
                  </div>
                </div>
              ),
            },
            { title: '机理', dataIndex: 'mechanism_label', width: 130 },
            {
              title: '寿命 (h)',
              dataIndex: 'life_hours',
              width: 110,
              align: 'right' as const,
              render: (v: number) => int(v),
            },
            {
              title: '折算年限',
              dataIndex: 'life_years',
              width: 130,
              align: 'right' as const,
              sorter: (a: any, b: any) => (a.life_years || 0) - (b.life_years || 0),
              defaultSortOrder: 'ascend' as const,
              render: (v: number, r: any) => (
                <b style={{ color: r.is_limiting ? '#C0392B' : undefined }}>{num(v, 2)} 年</b>
              ),
            },
            {
              title: '数据来源',
              width: 130,
              render: (_: any, r: any) =>
                r.using_defaults?.length ? (
                  <Tag color="gold">{r.using_defaults.length} 项默认值</Tag>
                ) : (
                  <Tag color="green">全部实测/解析</Tag>
                ),
            },
          ]}
        />
      </Card>

      <Alert
        type="info"
        showIcon
        icon={<InfoCircleOutlined />}
        style={{ marginTop: 12, fontSize: 12.5 }}
        message="磨损模型的适用边界"
        description={wear.disclaimer || '磨损模型输入（额定寿命、使用频次、工作温度）均为假设值，结果用于方案比较与风险排序，不作为寿命承诺。'}
      />
    </div>
  )
}
