/**
 * workspace/SensTab.tsx — 敏感性分析
 *
 * 【为什么这一屏比结果页更重要】
 * 可靠性预计最大的风险不是"算错"，而是"假设错了却没人知道"。
 * 同一份 BOM，环境温度从 25°C 换到 70°C，MTBF 可能差 5 倍；
 * 但报告上往往只写一个数，读者会把它当成客观事实。
 * 敏感性分析就是把"这个结论有多依赖那条假设"摆到台面上。
 *
 * 【弹性系数怎么读】
 *     E = (ΔMTBF / MTBF) ÷ (Δx / x)
 *     E = −2  ⇒  温度升高 10%，MTBF 下降 20%
 * |E| 越大越敏感。温度通常是强负相关；质量等级是阶跃式的（查表因子，不成曲线）。
 *
 * 【为什么要做"四假设影响排序"】
 * 单条曲线只回答"这一个变量有多重要"。而工程决策需要的是"四个变量里先管哪个"。
 * 排序表用固定变化量（+10°C、差一档质量、8h→24h、环境升一档）统一度量，
 * 让人一眼看到该先做散热还是先换料。
 */

import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Row,
  Segmented,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import { ExperimentOutlined, InfoCircleOutlined } from '@ant-design/icons'
import Chart from '../../components/Chart'
import { Term } from '../../components/Term'
import { getAssessment, runSensitivity } from '../../api'
import { int, num, pct } from '../../utils/format'

const VARIABLES = [
  { label: '环境温度', value: 'ambient_temp' },
  { label: '质量等级', value: 'quality_level' },
  { label: '日通电占比', value: 'duty_cycle' },
  { label: '环境类别', value: 'environment' },
]

export default function SensTab({ assessmentId }: { assessmentId: number | null }) {
  const [variable, setVariable] = useState<string>('ambient_temp')
  const [data, setData] = useState<any>(null)
  const [ranking, setRanking] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [running, setRunning] = useState(false)
  const [base, setBase] = useState<any>(null)

  // 评估时已经跑过一次温度扫描，这里直接复用，避免打开页面就重算
  useEffect(() => {
    if (!assessmentId) {
      setData(null)
      return
    }
    setLoading(true)
    getAssessment(assessmentId)
      .then((d) => {
        setBase(d)
        const sens = d?.sensitivity
        if (sens?.temp) setData(sens.temp)
        if (sens?.ranking) setRanking(sens.ranking)
      })
      .catch((e) => message.error(e.message))
      .finally(() => setLoading(false))
  }, [assessmentId])

  const run = async (v: string) => {
    if (!assessmentId) return
    setRunning(true)
    try {
      const r = await runSensitivity(assessmentId, { variable: v })
      setData(r)
      if (r.ranking) setRanking(r.ranking)
      message.success(`已扫描「${r.variable_label}」${r.points?.length || 0} 个点`)
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setRunning(false)
    }
  }

  const isCategorical = variable === 'quality_level' || variable === 'environment'

  const curveOption = useMemo(() => {
    if (!data?.points) return null
    const pts = data.points
    return {
      grid: { left: 74, right: 28, top: 40, bottom: 52 },
      tooltip: {
        trigger: 'axis',
        formatter: (ps: any) => {
          const p = ps[0]
          return `<b>${p.name}</b><br/>MTBF ${int(p.value)} h`
        },
      },
      xAxis: {
        type: 'category',
        name: data.x_unit ? data.variable_label : data.variable_label,
        data: pts.map((p: any) => p.label),
        axisLabel: { fontSize: 11, rotate: isCategorical ? 0 : 0, interval: isCategorical ? 0 : 'auto' },
      },
      yAxis: {
        type: 'value',
        name: 'MTBF (h)',
        scale: true,
        splitLine: { lineStyle: { type: 'dashed' } },
        axisLabel: { formatter: (v: number) => `${(v / 10000).toFixed(0)}万` },
      },
      series: [
        {
          type: 'line',
          smooth: !isCategorical,
          symbolSize: 7,
          data: pts.map((p: any) => p.mtbf_hours),
          areaStyle: { opacity: 0.1 },
          lineStyle: { width: 2.2 },
        },
      ],
    }
  }, [data, isCategorical, variable])

  const rankOption = useMemo(() => {
    if (!ranking.length) return null
    const rows = [...ranking].sort((a, b) => a.delta_pct - b.delta_pct)
    return {
      grid: { left: 96, right: 78, top: 26, bottom: 28 },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        formatter: (ps: any) => {
          const p = ps[0]
          const d = rows[p.dataIndex]
          return `<b>${d.variable}</b><br/>${d.change}<br/>MTBF 变化 ${d.delta_pct}%`;
        },
      },
      xAxis: { type: 'value', name: 'MTBF 变化 %', nameGap: 22, splitLine: { lineStyle: { type: 'dashed' } } },
      yAxis: { type: 'category', data: rows.map((r) => r.variable) },
      series: [
        {
          type: 'bar',
          barMaxWidth: 20,
          data: rows.map((r) => ({
            value: r.delta_pct,
            itemStyle: { color: r.delta_pct >= 50 ? '#C0392B' : r.delta_pct >= 20 ? '#D48806' : '#3A6EA5' },
          })),
          label: { show: true, position: 'right', formatter: '{c}%', fontSize: 11 },
        },
      ],
    }
  }, [ranking])

  if (!assessmentId) return <Empty description="还没有评估记录，请先跑一次评估" />

  if (loading && !data) {
    return (
      <div style={{ padding: 60, textAlign: 'center' }}>
        <Spin />
      </div>
    )
  }

  const assumption = base?.assumptions || {}

  return (
    <div>
      <Card size="small" variant="borderless" style={{ border: '1px solid #EEE', marginBottom: 12 }}>
        <Space wrap>
          <Segmented
            value={variable}
            onChange={(v) => {
              setVariable(v as string)
              if (!data || data.variable !== v) run(v as string)
            }}
            options={VARIABLES}
          />
          <Button icon={<ExperimentOutlined />} loading={running} onClick={() => run(variable)}>
            重新扫描
          </Button>
          <span className="muted" style={{ fontSize: 12 }}>
            基准假设：{assumption.ambient_temp_c ?? '—'}°C · {assumption.environment ?? '—'} ·{' '}
            {assumption.quality_level ?? '—'} · {((assumption.duty_cycle ?? 0) * 24).toFixed(0)} h/日
          </span>
        </Space>
      </Card>

      {data?.conclusion && (
        <Alert
          // 曲线是平的时候用 warning 而不是 info：这是"口径里没有这一项"，很容易被误读成
          // "温度不重要"，需要比普通说明更显眼一点。
          type={(data.total_swing_pct ?? 1) < 0.5 ? 'warning' : 'info'}
          showIcon
          icon={<InfoCircleOutlined />}
          style={{ marginBottom: 12 }}
          message={<span style={{ fontSize: 13 }}>{data.conclusion}</span>}
          description={
            <span style={{ fontSize: 12.5 }}>
              弹性系数 E = {data.elasticity === null ? '—' : num(data.elasticity, 2)}，全区间 MTBF 变化{' '}
              {num(data.total_swing_pct, 1)}%。
              {data.elasticity !== null && data.elasticity < -0.5 && variable === 'ambient_temp'
                ? '温度是主导因素——先做散热，比换料更划算。'
                : ''}
              {(data.total_swing_pct ?? 1) < 0.5
                ? ' 要看温度/应力的真实影响：把评估方法改成零件应力法，或把标准切到 Telcordia SR-332。'
                : ''}
            </span>
          }
        />
      )}

      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col xs={12} md={6}>
          <Card size="small" variant="borderless" style={{ background: '#F7F9FC' }}>
            <Statistic
              title={<Term k="pit">弹性系数 E</Term>}
              value={data?.elasticity === null || data?.elasticity === undefined ? '—' : num(data.elasticity, 2)}
              valueStyle={{ fontSize: 22 }}
            />
            <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
              |E| &gt; 1 表示结论高度敏感
            </div>
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small" variant="borderless" style={{ background: '#F7F9FC' }}>
            <Statistic
              title="全区间变化"
              value={num(data?.total_swing_pct, 1)}
              suffix="%"
              valueStyle={{ fontSize: 22, color: (data?.total_swing_pct ?? 0) > 100 ? '#C0392B' : undefined }}
            />
            <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
              扫描范围内 MTBF 最大/最小差
            </div>
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small" variant="borderless" style={{ background: '#F7F9FC' }}>
            <Statistic
              title="扫描点数"
              value={data?.points?.length ?? 0}
              valueStyle={{ fontSize: 22 }}
            />
            <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
              {data?.variable_label}
            </div>
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small" variant="borderless" style={{ background: '#F7F9FC' }}>
            <Statistic
              title="影响最大假设"
              value={ranking[0]?.variable ?? '—'}
              valueStyle={{ fontSize: 18 }}
            />
            <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
              {ranking[0] ? `变化 ${num(ranking[0].delta_pct, 1)}%` : ''}
            </div>
          </Card>
        </Col>
      </Row>

      <Row gutter={12}>
        <Col xs={24} xl={14}>
          <Card
            size="small"
            title={`${data?.variable_label || ''} → MTBF 曲线`}
            variant="borderless"
            style={{ border: '1px solid #EEE' }}
            styles={{ body: { paddingTop: 6 } }}
            extra={
              isCategorical ? (
                <Tag color="blue">阶跃式（查表因子，非连续曲线）</Tag>
              ) : (
                <Tag color="green">连续扫描</Tag>
              )
            }
          >
            {curveOption ? (
              <Chart option={curveOption as any} height={320} />
            ) : (
              <Empty description="尚无扫描数据，点击「重新扫描」" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
            <div className="muted" style={{ fontSize: 11.5, padding: '0 12px 8px' }}>
              纵轴为 MTBF。曲线越陡，说明结论对该假设越敏感；曲线平缓说明"这条假设填错了影响不大"。
            </div>
          </Card>
        </Col>

        <Col xs={24} xl={10}>
          <Card
            size="small"
            title="四条假设的影响排序"
            variant="borderless"
            style={{ border: '1px solid #EEE', marginBottom: 12 }}
            styles={{ body: { paddingTop: 6 } }}
          >
            {rankOption ? (
              <>
                <Chart option={rankOption as any} height={190} />
                <div className="muted" style={{ fontSize: 11.5, padding: '0 12px 8px' }}>
                  统一施加"合理变化量"：+10°C、质量差一档、8h→24h/日、环境升一档。
                  变化量事先说明，读者才能理解排序的含义。
                </div>
              </>
            ) : (
              <Empty description="暂无排序数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </Card>

          <Card
            size="small"
            title="明细"
            variant="borderless"
            style={{ border: '1px solid #EEE' }}
            styles={{ body: { padding: 0 } }}
          >
            <Table
              size="small"
              rowKey="variable"
              pagination={false}
              dataSource={ranking}
              columns={[
                { title: '假设', dataIndex: 'variable', width: 96 },
                { title: '变化', dataIndex: 'change' },
                {
                  title: 'MTBF',
                  dataIndex: 'mtbf',
                  width: 96,
                  align: 'right' as const,
                  render: (v: number) => int(v),
                },
                {
                  title: '变化幅度',
                  dataIndex: 'delta_pct',
                  width: 100,
                  align: 'right' as const,
                  render: (v: number) => (
                    <b style={{ color: v >= 50 ? '#C0392B' : v >= 20 ? '#D48806' : undefined }}>
                      {num(v, 1)}%
                    </b>
                  ),
                },
              ]}
            />
          </Card>
        </Col>
      </Row>

      <Card
        size="small"
        variant="borderless"
        style={{ border: '1px solid #EEE', marginTop: 12 }}
        title="这份敏感性分析在报告里怎么用"
      >
        <Typography.Paragraph style={{ fontSize: 12.5, marginBottom: 6 }}>
          1. 把结论写成<strong>带条件的句子</strong>：不是"MTBF 40 万小时"，而是"在 40°C / 商用级 / 8h 每日的假设下，
          MTBF 40 万小时；若环境温度升至 55°C，则降至约 18 万小时"。
        </Typography.Paragraph>
        <Typography.Paragraph style={{ fontSize: 12.5, marginBottom: 6 }}>
          2. 用弹性系数说明<strong>设计抓手</strong>：温度弹性 |E| 明显大于其他项时，
          散热改造的收益大于换料升级，评审时应优先争取结构与风道资源。
        </Typography.Paragraph>
        <Typography.Paragraph style={{ fontSize: 12.5, marginBottom: 0 }}>
          3. 用排序表说明<strong>假设的置信要求</strong>：排第一的假设必须实测（如柜内实测温度），
          排最后一条可以用经验值——这决定了验证试验要测什么。
        </Typography.Paragraph>
      </Card>
    </div>
  )
}
