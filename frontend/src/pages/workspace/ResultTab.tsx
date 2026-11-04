/**
 * workspace/ResultTab.tsx — 模块四的展示层：预计结果
 *
 * 【这一屏要回答三个问题】
 *   1) 结果是多少？（MTBF / 总 FIT / 目标年份存活率 / 判定）
 *   2) 为什么是这个数？（Pareto 短板 + 逐零件追溯）
 *   3) 这个数可信吗？（预警清单 + 双标准对比 + 方案对比）
 *
 * 【为什么 Pareto 是可靠性报告的第一张图】
 * 一张 200 行的 BOM 里，通常是 5~10 个料号贡献了 80% 的失效率。
 * 不找出这几行，改版就是"凭感觉换料"。Pareto 把"先动哪里"变成可执行的动作。
 *
 * 【为什么要单独做"计算追溯"抽屉】
 * 任何一次评审都会有人问："这个 0.0234 是怎么来的？"
 * 如果答不上来，整套结果就失去可信度。抽屉里逐步列出公式、代入值、结果与标准出处，
 * 缺省值会标黄——这一条比结果本身更重要，因为它决定了报告能不能被签字。
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Divider,
  Drawer,
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
import { ApartmentOutlined, FileSearchOutlined, SwapOutlined, WarningOutlined } from '@ant-design/icons'
import Chart from '../../components/Chart'
import { Term } from '../../components/Term'
import {
  compareAssessments,
  compareStandards,
  getAssessment,
  getTrace,
} from '../../api'
import { DERATING_META, MODE_TEXT, STANDARD_TEXT, VERDICT_META, int, mtbfYears, num, pct } from '../../utils/format'

export default function ResultTab({
  project,
  assessmentId,
  assessments,
  onChangeAssessment,
}: {
  project: any
  assessmentId: number | null
  assessments: any[]
  onChangeAssessment: (id: number) => void
}) {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [trace, setTrace] = useState<any>(null)
  const [traceLoading, setTraceLoading] = useState(false)
  const [stdCmp, setStdCmp] = useState<any>(null)
  const [stdLoading, setStdLoading] = useState(false)
  const [cmpIds, setCmpIds] = useState<[number?, number?]>([])
  const [cmp, setCmp] = useState<any>(null)
  const [cmpLoading, setCmpLoading] = useState(false)

  const load = useCallback(async () => {
    if (!assessmentId) {
      setData(null)
      return
    }
    setLoading(true)
    try {
      const d = await getAssessment(assessmentId)
      setData(d)
      setStdCmp(null)
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }, [assessmentId])

  useEffect(() => {
    load()
  }, [load])

  const a = data?.assessment
  const assumption = data?.assumptions || {}
  const targetYears = assumption.target_years ?? project?.target_years ?? 5
  const targetSurvival = assumption.target_survival ?? project?.target_survival ?? 0.95

  const openTrace = async (row: any) => {
    if (!assessmentId) return
    setTraceLoading(true)
    setTrace({ part_number: row.part_number, category_name: row.category_name, qty: row.qty, trace: [] })
    try {
      const t = await getTrace(assessmentId, row.part_id)
      setTrace(t)
    } catch (e: any) {
      message.error(e.message)
      setTrace(null)
    } finally {
      setTraceLoading(false)
    }
  }

  const runStdCompare = async () => {
    if (!assessmentId) return
    setStdLoading(true)
    try {
      setStdCmp(await compareStandards(assessmentId))
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setStdLoading(false)
    }
  }

  const runCompare = async () => {
    if (!cmpIds[0] || !cmpIds[1]) {
      message.warning('请选择两次评估记录')
      return
    }
    setCmpLoading(true)
    try {
      setCmp(await compareAssessments(cmpIds[0], cmpIds[1]))
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setCmpLoading(false)
    }
  }

  const paretoOption = useMemo(() => {
    const rows = (a?.top_contributors || []).slice(0, 12)
    return {
      grid: { left: 56, right: 56, top: 34, bottom: 104 },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      legend: { top: 0, itemHeight: 8, itemWidth: 12, textStyle: { fontSize: 11 } },
      xAxis: {
        type: 'category',
        // 料号很长（SIM-CAP-CER-100N50-01），直接当刻度会把横轴挤成一团。
        // 去掉 SIM- 前缀并截断到 16 字符，完整值放 tooltip。
        data: rows.map((r: any) => String(r.part_number || r.category_code).replace(/^SIM-/, '')),
        axisLabel: {
          rotate: 45,
          fontSize: 10,
          interval: 0,
          formatter: (v: string) => (v.length > 12 ? `${v.slice(0, 11)}…` : v),
        },
      },
      yAxis: [
        { type: 'value', name: '失效率 FIT', splitLine: { lineStyle: { type: 'dashed' } } },
        { type: 'value', name: '累计 %', max: 100, axisLabel: { formatter: '{value}%' }, splitLine: { show: false } },
      ],
      series: [
        {
          name: '失效率',
          type: 'bar',
          barMaxWidth: 26,
          data: rows.map((r: any) => r.lambda_part),
          itemStyle: { borderRadius: [3, 3, 0, 0] },
        },
        {
          name: '累计占比',
          type: 'line',
          yAxisIndex: 1,
          smooth: true,
          symbolSize: 5,
          data: rows.map((r: any) => r.cumulative_pct),
          lineStyle: { width: 1.6 },
        },
      ],
    }
  }, [a])

  const survivalOption = useMemo(() => {
    const pts = data?.survival_curve || []
    return {
      grid: { left: 58, right: 24, top: 34, bottom: 40 },
      tooltip: {
        trigger: 'axis',
        valueFormatter: (v: any) => `${(Number(v) * 100).toFixed(2)}%`,
      },
      xAxis: {
        type: 'category',
        data: pts.map((p: any) => String(p.year)),
        name: '使用年限（年）',
        axisLabel: { fontSize: 10, interval: 0 },
      },
      yAxis: {
        type: 'value',
        name: '存活率 R(t)',
        min: 0,
        max: 1,
        axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
        splitLine: { lineStyle: { type: 'dashed' } },
      },
      series: [
        {
          type: 'line',
          smooth: true,
          symbolSize: 6,
          data: pts.map((p: any) => p.r),
          areaStyle: { opacity: 0.12 },
          markLine: {
            symbol: 'none',
            label: { formatter: `目标 ${(targetSurvival * 100).toFixed(0)}%`, fontSize: 11 },
            lineStyle: { type: 'dashed', color: '#C0392B' },
            data: [{ yAxis: targetSurvival }],
          },
        },
      ],
    }
  }, [data, targetSurvival])

  const stdOption = useMemo(() => {
    if (!stdCmp) return null
    const mil = stdCmp.standards?.['MIL-217F']
    const tel = stdCmp.standards?.['TELCORDIA_SR332']
    return {
      grid: { left: 70, right: 30, top: 24, bottom: 40 },
      tooltip: { trigger: 'axis', valueFormatter: (v: any) => `${int(Number(v))} h` },
      xAxis: { type: 'category', data: ['MIL-HDBK-217F', 'Telcordia SR-332'] },
      yAxis: { type: 'value', name: 'MTBF (h)', splitLine: { lineStyle: { type: 'dashed' } } },
      series: [
        {
          type: 'bar',
          barMaxWidth: 64,
          data: [
            { value: mil?.mtbf_hours, itemStyle: { color: '#3A6EA5' } },
            { value: tel?.mtbf_hours, itemStyle: { color: '#61DDAA' } },
          ],
          label: {
            show: true,
            position: 'top',
            formatter: (p: any) => `${int(p.value)} h`,
            fontSize: 11,
          },
        },
      ],
    }
  }, [stdCmp])

  if (!assessmentId) {
    return <Empty description="还没有评估记录，请先到「③ 假设与评估」跑一次" />
  }

  if (loading && !data) {
    return (
      <div style={{ padding: 60, textAlign: 'center' }}>
        <Spin />
      </div>
    )
  }

  if (!a) return <Empty description="评估记录不可用" />

  const meta = data?.meta || {}
  const verdictMeta = VERDICT_META[a.verdict] || VERDICT_META.NA

  return (
    <div>
      {/* ---- 顶部指标 ---- */}
      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col xs={12} md={6}>
          <Card size="small" variant="borderless" style={{ background: '#F7F9FC' }}>
            <Statistic
              title={<Term k="fit">总失效率</Term>}
              value={num(a.lambda_total_fit, 3)}
              suffix="FIT"
              valueStyle={{ fontSize: 22 }}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small" variant="borderless" style={{ background: '#F7F9FC' }}>
            <Statistic
              title={<Term k="mtbf">MTBF</Term>}
              value={a.mtbf_hours === null ? '∞' : int(a.mtbf_hours)}
              suffix="h"
              valueStyle={{ fontSize: 22 }}
            />
            <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
              {mtbfYears(a.mtbf_hours)}
            </div>
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small" variant="borderless" style={{ background: '#F7F9FC' }}>
            <Statistic
              title={`${targetYears} 年存活率`}
              value={pct(a.r_at_target, 2)}
              valueStyle={{
                fontSize: 22,
                color: a.r_at_target >= targetSurvival ? '#1B7F3B' : '#C0392B',
              }}
            />
            <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
              目标 ≥ {pct(targetSurvival, 1)} · 通电 {int(a.operating_hours)} h
            </div>
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small" variant="borderless" style={{ background: verdictMeta.tag === 'success' ? '#F2FAF4' : '#FDF3F2' }}>
            <Statistic
              title="综合判定"
              value={verdictMeta.text}
              valueStyle={{ fontSize: 22, color: verdictMeta.color }}
            />
            <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
              #{meta.id} · {MODE_TEXT[a.mode]} · {STANDARD_TEXT[a.standard]}
            </div>
          </Card>
        </Col>
      </Row>

      {/* ---- 判定理由 ---- */}
      <Card size="small" variant="borderless" style={{ border: '1px solid #EEE', marginBottom: 12 }}>
        <Space direction="vertical" size={4} style={{ width: '100%' }}>
          {(a.verdict_reasons || []).map((r: string, i: number) => (
            <div key={i} style={{ fontSize: 13 }}>
              <Tag color={r.includes('不达标') || r.includes('未达') ? 'error' : 'success'} style={{ marginRight: 8 }}>
                {r.includes('不达标') || r.includes('未达') ? '✗' : '✓'}
              </Tag>
              {r}
            </div>
          ))}
          <div className="muted" style={{ fontSize: 11.5, marginTop: 4 }}>
            参数库 {a.param_version} · 引擎 {a.engine_version} · 快照时间 {meta.created_at}
            {meta.note ? ` · 备注：${meta.note}` : ''}
          </div>
        </Space>
      </Card>

      {(a.warnings || []).length > 0 && (
        <Alert
          type="warning"
          showIcon
          icon={<WarningOutlined />}
          style={{ marginBottom: 12 }}
          message={`${a.warnings.length} 条预警（先看这里，再相信上面的数字）`}
          description={
            <ol style={{ paddingLeft: 18, margin: '4px 0 0', fontSize: 12.5, lineHeight: 1.8 }}>
              {a.warnings.map((w: string, i: number) => (
                <li key={i}>{w}</li>
              ))}
            </ol>
          }
        />
      )}

      {/* ---- 两张主图 ---- */}
      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col xs={24} xl={14}>
          <Card
            size="small"
            title={
              <Space>
                <span>短板 Pareto</span>
                <span className="muted" style={{ fontSize: 11, fontWeight: 400 }}>
                  先动这几行，收益最大
                </span>
              </Space>
            }
            variant="borderless"
            style={{ border: '1px solid #EEE' }}
            styles={{ body: { paddingTop: 6 } }}
          >
            {/* 高度给到 340：横轴是 45° 旋转的长料号，300px 会把标签底部切掉 */}
            <Chart option={paretoOption as any} height={340} />
          </Card>
        </Col>
        <Col xs={24} xl={10}>
          <Card
            size="small"
            title={<Term k="rt">存活率曲线 R(t)</Term>}
            variant="borderless"
            style={{ border: '1px solid #EEE' }}
            styles={{ body: { paddingTop: 6 } }}
          >
            <Chart option={survivalOption as any} height={340} />
            <div className="muted" style={{ fontSize: 11.5, padding: '0 8px 4px' }}>
              R(t) = e<sup>−t/MTBF</sup>，t 已按日通电 {((assumption.duty_cycle ?? 0.333) * 24).toFixed(0)} h 折算。
              注意这是<strong>随机失效</strong>视角的曲线，不含磨损件（见「⑤ 磨损寿命」）。
            </div>
          </Card>
        </Col>
      </Row>

      {/* ---- 短板表 ---- */}
      <Card
        size="small"
        title={`失效率贡献 Top ${(a.top_contributors || []).length}`}
        variant="borderless"
        style={{ border: '1px solid #EEE', marginBottom: 12 }}
        extra={<span className="muted" style={{ fontSize: 11.5 }}>点击行可查看逐步计算追溯</span>}
        styles={{ body: { padding: 0 } }}
      >
        <Table
          size="small"
          rowKey="part_id"
          dataSource={a.top_contributors || []}
          pagination={false}
          onRow={(row) => ({ onClick: () => openTrace(row), style: { cursor: 'pointer' } })}
          columns={[
            { title: '#', width: 44, render: (_: any, __: any, i: number) => i + 1 },
            { title: '料号', dataIndex: 'part_number', width: 150 },
            { title: '类目', dataIndex: 'category_name', width: 130 },
            { title: '用量', dataIndex: 'qty', width: 64, align: 'right' as const },
            {
              title: '失效率 (FIT)',
              dataIndex: 'lambda_part',
              width: 110,
              align: 'right' as const,
              render: (v: number) => num(v, 4),
            },
            {
              title: '占比',
              dataIndex: 'contribution_pct',
              width: 96,
              align: 'right' as const,
              render: (v: number) => (
                <b style={{ color: v >= 10 ? '#C0392B' : undefined }}>{num(v, 2)}%</b>
              ),
            },
            {
              title: '累计',
              dataIndex: 'cumulative_pct',
              width: 96,
              align: 'right' as const,
              render: (v: number) => `${num(v, 1)}%`,
            },
            {
              title: '冗余组',
              dataIndex: 'in_redundancy_group',
              width: 90,
              render: (v: boolean) =>
                v ? <Tag color="purple">并联折算</Tag> : <span className="muted">—</span>,
            },
            {
              title: '',
              width: 46,
              render: () => <FileSearchOutlined className="muted" />,
            },
          ]}
        />
      </Card>

      {/* ---- 冗余组 ---- */}
      {(a.redundancy || []).length > 0 && (
        <Card
          size="small"
          title={
            <Space>
              <ApartmentOutlined />
              <span>可靠性框图：冗余组</span>
            </Space>
          }
          variant="borderless"
          style={{ border: '1px solid #EEE', marginBottom: 12 }}
          styles={{ body: { padding: 0 } }}
        >
          <Table
            size="small"
            rowKey="group"
            dataSource={a.redundancy || []}
            pagination={false}
            columns={[
              { title: '组名', dataIndex: 'group' },
              { title: '成员数', width: 90, render: (_: any, r: any) => r.member_ids.length },
              {
                title: '串联合计 λ',
                dataIndex: 'member_lambda_sum',
                width: 130,
                align: 'right' as const,
                render: (v: number) => num(v, 4),
              },
              {
                title: '并联等效 λ',
                dataIndex: 'lambda_equiv',
                width: 130,
                align: 'right' as const,
                render: (v: number) => <b>{num(v, 4)}</b>,
              },
              {
                title: '收益',
                width: 90,
                align: 'right' as const,
                render: (_: any, r: any) =>
                  r.member_lambda_sum && r.lambda_equiv
                    ? `${num(r.member_lambda_sum / r.lambda_equiv, 2)}×`
                    : '—',
              },
              {
                title: '组存活率',
                dataIndex: 'r_group',
                width: 110,
                align: 'right' as const,
                render: (v: number) => pct(v, 3),
              },
            ]}
          />
          <div className="muted" style={{ fontSize: 11.5, padding: '8px 12px' }}>
            收益为「共因失效可忽略」下的上限。若冗余件共用电源/散热或同批次同供应商，实际收益会明显低于此值。
          </div>
        </Card>
      )}

      {/* ---- 双标准对比 ---- */}
      <Card
        size="small"
        title={<Term k="parts_count">双标准对比</Term>}
        extra={
          <Button size="small" icon={<SwapOutlined />} loading={stdLoading} onClick={runStdCompare}>
            {stdCmp ? '重新计算' : '计算另一套标准'}
          </Button>
        }
        variant="borderless"
        style={{ border: '1px solid #EEE', marginBottom: 12 }}
      >
        {!stdCmp ? (
          <div className="muted" style={{ fontSize: 12.5 }}>
            基于<strong>同一次评估的假设</strong>，再用另一套标准重算一遍。除标准外其他条件完全一致，
            所以差异只来自标准本身——这比分别跑两次评估再对比更可信。
          </div>
        ) : (
          <Row gutter={16}>
            <Col xs={24} xl={11}>
              <Chart option={stdOption as any} height={240} />
            </Col>
            <Col xs={24} xl={13}>
              <Table
                size="small"
                rowKey="std"
                pagination={false}
                dataSource={['MIL-217F', 'TELCORDIA_SR332'].map((s) => ({
                  std: s,
                  ...(stdCmp.standards?.[s] || {}),
                }))}
                columns={[
                  { title: '标准', dataIndex: 'std', render: (v: string) => STANDARD_TEXT[v] || v },
                  {
                    title: '总 FIT',
                    dataIndex: 'lambda_total_fit',
                    align: 'right' as const,
                    render: (v: number) => num(v, 3),
                  },
                  {
                    title: 'MTBF (h)',
                    dataIndex: 'mtbf_hours',
                    align: 'right' as const,
                    render: (v: number) => int(v),
                  },
                  {
                    title: '存活率',
                    dataIndex: 'r_at_target',
                    align: 'right' as const,
                    render: (v: number) => pct(v, 2),
                  },
                  {
                    title: '判定',
                    dataIndex: 'verdict',
                    width: 90,
                    render: (v: string) => (
                      <Tag color={VERDICT_META[v]?.tag === 'success' ? 'success' : v === 'FAIL' ? 'error' : 'default'}>
                        {VERDICT_META[v]?.text || v}
                      </Tag>
                    ),
                  },
                ]}
              />
              {stdCmp.note && (
                <Alert type="info" showIcon style={{ marginTop: 10, fontSize: 12.5 }} message={stdCmp.note} />
              )}
            </Col>
          </Row>
        )}
      </Card>

      {/* ---- 方案对比 ---- */}
      <Card
        size="small"
        title="方案 / 版本对比"
        variant="borderless"
        style={{ border: '1px solid #EEE' }}
      >
        <Space wrap style={{ marginBottom: 12 }}>
          <Select
            size="small"
            style={{ width: 230 }}
            placeholder="基准方案"
            value={cmpIds[0]}
            onChange={(v) => setCmpIds([v, cmpIds[1]])}
            options={assessments.map((x) => ({
              value: x.id,
              label: `#${x.id} ${x.standard} · ${x.verdict} · ${x.created_at.slice(5, 16)}`,
            }))}
          />
          <span className="muted">→</span>
          <Select
            size="small"
            style={{ width: 230 }}
            placeholder="对比方案"
            value={cmpIds[1]}
            onChange={(v) => setCmpIds([cmpIds[0], v])}
            options={assessments.map((x) => ({
              value: x.id,
              label: `#${x.id} ${x.standard} · ${x.verdict} · ${x.created_at.slice(5, 16)}`,
            }))}
          />
          <Button size="small" type="primary" loading={cmpLoading} onClick={runCompare}>
            对比
          </Button>
          {assessments.length > 1 && (
            <Button
              size="small"
              onClick={() => {
                setCmpIds([assessments[1].id, assessments[0].id])
                message.info('已填入最近两次评估，点「对比」查看')
              }}
            >
              填入最近两次
            </Button>
          )}
          <Select
            size="small"
            style={{ width: 220, marginLeft: 'auto' }}
            value={assessmentId}
            onChange={onChangeAssessment}
            options={assessments.map((x) => ({
              value: x.id,
              label: `当前展示：#${x.id}`,
            }))}
          />
        </Space>

        {!cmp ? (
          <div className="muted" style={{ fontSize: 12.5 }}>
            选两次评估，对比 MTBF、存活率与判定变化。典型用法：改版前后（换料/降温/加冗余）各跑一次，
            用这个卡片证明改进有效，而不是"感觉好一些"。
          </div>
        ) : (
          <>
            <Row gutter={12} style={{ marginBottom: 10 }}>
              <Col xs={24} md={8}>
                <Card size="small" variant="borderless" style={{ background: '#F7F9FC' }}>
                  <Statistic
                    title="MTBF 变化"
                    value={cmp.delta?.mtbf_change_pct ?? 0}
                    precision={2}
                    suffix="%"
                    prefix={(cmp.delta?.mtbf_change_pct ?? 0) >= 0 ? '+' : ''}
                    valueStyle={{
                      fontSize: 20,
                      color: (cmp.delta?.mtbf_change_pct ?? 0) >= 0 ? '#1B7F3B' : '#C0392B',
                    }}
                  />
                </Card>
              </Col>
              <Col xs={24} md={8}>
                <Card size="small" variant="borderless" style={{ background: '#F7F9FC' }}>
                  <Statistic
                    title="存活率变化"
                    value={cmp.delta?.r_change_pp ?? 0}
                    precision={2}
                    suffix="pp"
                    prefix={(cmp.delta?.r_change_pp ?? 0) >= 0 ? '+' : ''}
                    valueStyle={{
                      fontSize: 20,
                      color: (cmp.delta?.r_change_pp ?? 0) >= 0 ? '#1B7F3B' : '#C0392B',
                    }}
                  />
                </Card>
              </Col>
              <Col xs={24} md={8}>
                <Card size="small" variant="borderless" style={{ background: '#F7F9FC' }}>
                  <Statistic
                    title="判定"
                    value={cmp.delta?.verdict_change || '—'}
                    valueStyle={{ fontSize: 20 }}
                  />
                </Card>
              </Col>
            </Row>

            <Row gutter={12}>
              {(['left', 'right'] as const).map((side, idx) => {
                const s = cmp[side]
                return (
                  <Col xs={24} md={12} key={side}>
                    <Card
                      size="small"
                      title={`#${s.assessment.id} · ${idx === 0 ? '基准' : '对比'}`}
                      variant="borderless"
                      style={{ border: '1px solid #EEE' }}
                      styles={{ body: { padding: 12 } }}
                    >
                      <Descriptions size="small" column={2} colon={false}>
                        <Descriptions.Item label="标准">{STANDARD_TEXT[s.assessment.standard]}</Descriptions.Item>
                        <Descriptions.Item label="方法">{MODE_TEXT[s.assessment.mode]}</Descriptions.Item>
                        <Descriptions.Item label="MTBF">{int(s.mtbf_hours)} h</Descriptions.Item>
                        <Descriptions.Item label="存活率">{pct(s.r_at_target, 2)}</Descriptions.Item>
                      </Descriptions>
                      <Divider style={{ margin: '8px 0' }} />
                      <div style={{ fontSize: 12 }}>
                        <b>主要短板</b>
                        {(s.top_contributors || []).slice(0, 3).map((c: any) => (
                          <div key={c.part_id} className="muted" style={{ lineHeight: 1.8 }}>
                            · {c.part_number}（{num(c.contribution_pct, 1)}%）
                          </div>
                        ))}
                      </div>
                    </Card>
                  </Col>
                )
              })}
            </Row>
          </>
        )}
      </Card>

      {/* ---- 追溯抽屉 ---- */}
      <Drawer
        open={!!trace}
        onClose={() => setTrace(null)}
        width={720}
        title={
          trace ? (
            <Space>
              <span>计算追溯：{trace.part_number}</span>
              <Tag>{trace.category_name}</Tag>
              <Tag>用量 {trace.qty}</Tag>
            </Space>
          ) : (
            '计算追溯'
          )
        }
      >
        {traceLoading ? (
          <div style={{ padding: 40, textAlign: 'center' }}>
            <Spin />
          </div>
        ) : trace ? (
          <>
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12, fontSize: 12.5 }}
              message="每一步都写清公式、代入值与标准出处"
              description="标有「默认」的步骤表示该输入没有真实数据，用了类别默认值——这类步骤会拉低结果可信度，建议补录后重算。"
            />
            <Table
              size="small"
              rowKey="step"
              pagination={false}
              dataSource={trace.trace || []}
              columns={[
                { title: '步', dataIndex: 'step', width: 44 },
                {
                  title: '在算什么',
                  dataIndex: 'name',
                  width: 130,
                  render: (v: string, r: any) => (
                    <span>
                      {v}
                      {r.is_default && (
                        <Tooltip title="该步骤使用了默认值/兜底值">
                          <Tag color="gold" style={{ marginLeft: 4 }}>
                            默认
                          </Tag>
                        </Tooltip>
                      )}
                    </span>
                  ),
                },
                {
                  title: '公式与代入',
                  render: (_: any, r: any) => (
                    <div>
                      <code style={{ fontSize: 11.5, color: '#3A6EA5' }}>{r.formula}</code>
                      {r.inputs && Object.keys(r.inputs).length > 0 && (
                        <div className="muted" style={{ fontSize: 11.5, marginTop: 2 }}>
                          {Object.entries(r.inputs)
                            .map(([k, v]) => `${k} = ${v}`)
                            .join('，')}
                        </div>
                      )}
                      {r.note && (
                        <div style={{ fontSize: 11.5, color: '#D48806', marginTop: 2 }}>{r.note}</div>
                      )}
                    </div>
                  ),
                },
                {
                  title: '结果',
                  dataIndex: 'value',
                  width: 96,
                  align: 'right' as const,
                  render: (v: number, r: any) => (
                    <b>
                      {num(v, 4)}
                      {r.unit && r.unit !== '-' ? ` ${r.unit}` : ''}
                    </b>
                  ),
                },
                {
                  title: '依据',
                  dataIndex: 'source',
                  width: 160,
                  render: (v: string) =>
                    // 标准出处往往很长（"…Notice 2（1995）— Part Count 见 Sec.5-3 Sec.10 各类别图…"），
                    // 直接铺开会把每行撑到 5 行高。截到 3 行 + 悬停看全文。
                    v ? (
                      <Tooltip title={v} placement="left">
                        <div
                          style={{
                            fontSize: 11,
                            color: '#8c8c8c',
                            display: '-webkit-box',
                            WebkitLineClamp: 3,
                            WebkitBoxOrient: 'vertical',
                            overflow: 'hidden',
                          }}
                        >
                          {v}
                        </div>
                      </Tooltip>
                    ) : (
                      <span className="muted">—</span>
                    ),
                },
              ]}
            />
            <Divider style={{ margin: '14px 0 10px' }} />
            <Descriptions size="small" column={2} bordered>
              <Descriptions.Item label="基础失效率 λb">{num(trace.lambda_b, 6)} FIT</Descriptions.Item>
              <Descriptions.Item label="该零件合计 λ">{num(trace.lambda_part, 6)} FIT</Descriptions.Item>
              {Object.entries(trace.factors || {}).map(([k, v]) => (
                <Descriptions.Item key={k} label={k}>
                  {num(v as number, 4)}
                </Descriptions.Item>
              ))}
            </Descriptions>
          </>
        ) : null}
      </Drawer>
    </div>
  )
}
