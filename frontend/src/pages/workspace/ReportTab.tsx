/**
 * workspace/ReportTab.tsx — 模块七：评估报告与流程判定
 *
 * 【报告在这个系统里的定位】
 * 报告不是"把页面截图导出"，而是一份能交给评审、能归档、能复现的交付物。
 * 所以每次生成都会重新渲染，并在页脚写明：参数库版本、引擎版本、假设快照、
 * 生成时间。参数库以后改了，旧报告里的数字也不会变——这才叫可追溯。
 *
 * 【为什么 PDF 和 Excel 都要有】
 *   PDF 给评审看（排版固定、不会被改）；
 *   Excel 给工程师用（可以自己拿明细做二次分析、算成本、做取舍表）。
 * 只给 PDF 会被抱怨"数据拿不出来"，只给 Excel 会被抱怨"没法签字"。
 *
 * 【版本对比放在这里而不是结果页】
 * 评审的实际动作是"上一版报告 vs 这一版报告"。所以历史评估与报告放在同一屏，
 * 选两次评估即可对比 MTBF / 存活率 / 判定变化（对比计算复用结果页的接口）。
 */

import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Divider,
  Empty,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Timeline,
  Tooltip,
  Typography,
  message,
} from 'antd'
import {
  CheckCircleOutlined,
  FileExcelOutlined,
  FilePdfOutlined,
  HistoryOutlined,
  SwapOutlined,
} from '@ant-design/icons'
import {
  compareAssessments,
  createReport,
  downloadReport,
  getAssessment,
  listAssessments,
  listReports,
} from '../../api'
import { MODE_TEXT, STANDARD_TEXT, VERDICT_META, int, num, pct } from '../../utils/format'

/** 报告章节结构（与后端 report 服务的 10 章对应，供页面说明用） */
const SECTIONS = [
  '封面与结论摘要（判定、MTBF、存活率、预警条数）',
  '项目与评估假设（四参数、目标、标准与模式）',
  '方法说明与标准出处（计数法/应力法、π 因子体系）',
  '整机结果（总 FIT、MTBF、R(t)、判定理由）',
  '短板分析（Pareto Top 10 与累计占比）',
  '磨损件寿命（排行榜、限制机理、双轨结论）',
  '降额检查（四级判定统计与违规清单）',
  '敏感性分析（温度曲线、弹性系数、影响排序）',
  '改进建议（按"收益/成本"排序的可执行项）',
  '附录（逐零件明细、计算追溯、免责声明与版本信息）',
]

export default function ReportTab({
  project,
  assessmentId,
  onReported,
}: {
  project: any
  assessmentId: number | null
  onReported: () => void
}) {
  const [reports, setReports] = useState<any[]>([])
  const [assessments, setAssessments] = useState<any[]>([])
  const [snapshot, setSnapshot] = useState<any>(null)
  const [making, setMaking] = useState<string | null>(null)
  const [cmpIds, setCmpIds] = useState<[number?, number?]>([])
  const [cmp, setCmp] = useState<any>(null)
  const [cmpLoading, setCmpLoading] = useState(false)

  const load = useCallback(async () => {
    try {
      const [rs, as] = await Promise.all([listReports(project.id), listAssessments(project.id)])
      setReports(rs)
      setAssessments(as)
    } catch (e: any) {
      message.error(e.message)
    }
  }, [project.id])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    if (!assessmentId) {
      setSnapshot(null)
      return
    }
    getAssessment(assessmentId)
      .then(setSnapshot)
      .catch(() => setSnapshot(null))
  }, [assessmentId])

  const make = async (kind: 'pdf' | 'xlsx') => {
    if (!assessmentId) {
      message.warning('请先选择一次评估记录')
      return
    }
    setMaking(kind)
    try {
      const r = await createReport(assessmentId, kind)
      message.success(`报告已生成（${(r.file_size / 1024).toFixed(0)} KB），正在下载`)
      await downloadReport(r.id, `可靠性评估报告_${r.id}.${kind}`)
      await load()
      onReported()
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setMaking(null)
    }
  }

  const runCompare = async () => {
    if (!cmpIds[0] || !cmpIds[1]) {
      message.warning('请选择两次评估')
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

  const a = snapshot?.assessment

  return (
    <div>
      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col xs={24} xl={15}>
          <Card
            size="small"
            title="生成报告"
            variant="borderless"
            style={{ border: '1px solid #EEE' }}
          >
            {a ? (
              <>
                <Descriptions size="small" column={2} colon={false} style={{ marginBottom: 12 }}>
                  <Descriptions.Item label="评估记录">
                    #{snapshot.meta?.id}
                    <Tag
                      style={{ marginLeft: 6 }}
                      color={VERDICT_META[a.verdict]?.tag === 'success' ? 'success' : a.verdict === 'FAIL' ? 'error' : 'default'}
                    >
                      {VERDICT_META[a.verdict]?.text || a.verdict}
                    </Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="标准">{STANDARD_TEXT[a.standard]}</Descriptions.Item>
                  <Descriptions.Item label="方法">{MODE_TEXT[a.mode]}</Descriptions.Item>
                  <Descriptions.Item label="MTBF">{int(a.mtbf_hours)} h</Descriptions.Item>
                  <Descriptions.Item label="目标存活率">
                    {pct(a.r_at_target, 2)}
                  </Descriptions.Item>
                  <Descriptions.Item label="参数库">{a.param_version}</Descriptions.Item>
                </Descriptions>
                <Space wrap>
                  <Button
                    type="primary"
                    icon={<FilePdfOutlined />}
                    loading={making === 'pdf'}
                    onClick={() => make('pdf')}
                  >
                    生成 PDF（评审用）
                  </Button>
                  <Button
                    icon={<FileExcelOutlined />}
                    loading={making === 'xlsx'}
                    onClick={() => make('xlsx')}
                  >
                    生成 Excel（数据分析用）
                  </Button>
                  <span className="muted" style={{ fontSize: 12 }}>
                    每次生成都重新渲染，页脚写入参数库/引擎版本，保证可复现
                  </span>
                </Space>
              </>
            ) : (
              <Empty description="还没有评估记录，请先在「③ 假设与评估」跑一次" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </Card>
        </Col>

        <Col xs={24} xl={9}>
          <Card
            size="small"
            title="报告结构（10 章）"
            variant="borderless"
            style={{ border: '1px solid #EEE' }}
            styles={{ body: { paddingTop: 8, maxHeight: 330, overflow: 'auto' } }}
          >
            <Timeline
              items={SECTIONS.map((s, i) => ({
                color: i === 0 ? 'red' : 'blue',
                children: <span style={{ fontSize: 12.5 }}>{s}</span>,
              }))}
            />
          </Card>
        </Col>
      </Row>

      {/* ---- 历史报告 ---- */}
      <Card
        size="small"
        title={
          <Space>
            <HistoryOutlined />
            <span>历史报告</span>
            <Tag>{reports.length}</Tag>
          </Space>
        }
        extra={
          <Button size="small" onClick={load}>
            刷新
          </Button>
        }
        variant="borderless"
        style={{ border: '1px solid #EEE', marginBottom: 12 }}
        styles={{ body: { padding: 0 } }}
      >
        <Table
          size="small"
          rowKey="id"
          dataSource={reports}
          pagination={reports.length > 10 ? { pageSize: 10, size: 'small' } : false}
          locale={{ emptyText: '还没有生成过报告' }}
          columns={[
            { title: '#', dataIndex: 'id', width: 60 },
            {
              title: '类型',
              dataIndex: 'kind',
              width: 90,
              render: (v: string) =>
                v === 'pdf' ? (
                  <Tag color="volcano" icon={<FilePdfOutlined />}>
                    PDF
                  </Tag>
                ) : (
                  <Tag color="green" icon={<FileExcelOutlined />}>
                    Excel
                  </Tag>
                ),
            },
            {
              title: '对应评估',
              dataIndex: 'assessment_id',
              width: 100,
              render: (v: number) => `#${v}`,
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
            {
              title: '大小',
              dataIndex: 'file_size',
              width: 90,
              align: 'right' as const,
              render: (v: number) => `${(v / 1024).toFixed(0)} KB`,
            },
            { title: '生成时间', dataIndex: 'created_at', width: 170 },
            {
              title: '文件',
              dataIndex: 'exists',
              width: 90,
              render: (v: boolean) =>
                v ? <Tag color="green">在库</Tag> : <Tag>已清理</Tag>,
            },
            {
              title: '',
              width: 90,
              render: (_: any, r: any) => (
                <Tooltip title={r.exists ? '下载' : '文件已被清理，请重新生成'}>
                  <Button
                    size="small"
                    type="link"
                    disabled={!r.exists}
                    onClick={() => downloadReport(r.id, `可靠性评估报告_${r.id}.${r.kind}`)}
                  >
                    下载
                  </Button>
                </Tooltip>
              ),
            },
          ]}
        />
      </Card>

      {/* ---- 版本对比 ---- */}
      <Card
        size="small"
        title={
          <Space>
            <SwapOutlined />
            <span>版本对比（改版前后）</span>
          </Space>
        }
        variant="borderless"
        style={{ border: '1px solid #EEE' }}
      >
        <Space wrap style={{ marginBottom: 12 }}>
          <Select
            size="small"
            style={{ width: 250 }}
            placeholder="改版前"
            value={cmpIds[0]}
            onChange={(v) => setCmpIds([v, cmpIds[1]])}
            options={assessments.map((x) => ({
              value: x.id,
              label: `#${x.id} ${x.standard} · ${x.verdict} · ${x.created_at.slice(5, 16)}`,
            }))}
          />
          <SwapOutlined className="muted" />
          <Select
            size="small"
            style={{ width: 250 }}
            placeholder="改版后"
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
        </Space>

        {!cmp ? (
          <Typography.Paragraph type="secondary" style={{ fontSize: 12.5, marginBottom: 0 }}>
            选两次评估记录做横向对比。典型场景：换掉一颗短板电容、把柜内温度降 5°C、或给电源加一路冗余，
            然后各跑一次评估——用这张表证明改进的收益，而不是"感觉好一些"。
          </Typography.Paragraph>
        ) : (
          <>
            <Row gutter={12} style={{ marginBottom: 12 }}>
              <Col xs={12} md={8}>
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
              <Col xs={12} md={8}>
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
              <Col xs={12} md={8}>
                <Card size="small" variant="borderless" style={{ background: '#F7F9FC' }}>
                  <Statistic
                    title="判定变化"
                    value={cmp.delta?.verdict_change || '—'}
                    valueStyle={{ fontSize: 18 }}
                  />
                </Card>
              </Col>
            </Row>

            <Table
              size="small"
              rowKey="side"
              pagination={false}
              dataSource={[
                { side: '改版前', ...cmp.left.assessment, mtbf: cmp.left.mtbf_hours, r: cmp.left.r_at_target, top: cmp.left.top_contributors?.[0] },
                { side: '改版后', ...cmp.right.assessment, mtbf: cmp.right.mtbf_hours, r: cmp.right.r_at_target, top: cmp.right.top_contributors?.[0] },
              ]}
              columns={[
                { title: '', dataIndex: 'side', width: 90 },
                { title: '评估', dataIndex: 'id', width: 70, render: (v: number) => `#${v}` },
                {
                  title: '标准 / 方法',
                  width: 230,
                  render: (_: any, r: any) => `${STANDARD_TEXT[r.standard]} · ${MODE_TEXT[r.mode]}`,
                },
                { title: 'MTBF (h)', dataIndex: 'mtbf', align: 'right' as const, render: (v: number) => int(v) },
                { title: '存活率', dataIndex: 'r', align: 'right' as const, render: (v: number) => pct(v, 2) },
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
                {
                  title: '最大短板',
                  render: (_: any, r: any) =>
                    r.top ? `${r.top.part_number}（${num(r.top.contribution_pct, 1)}%）` : '—',
                },
              ]}
            />
            <Divider style={{ margin: '12px 0 8px' }} />
            <Alert
              type="success"
              showIcon
              icon={<CheckCircleOutlined />}
              message="对比结论怎么写"
              description={
                <span style={{ fontSize: 12.5 }}>
                  「改版后 MTBF 由 {int(cmp.left.mtbf_hours)} h 提升至 {int(cmp.right.mtbf_hours)} h
                  （{num(cmp.delta?.mtbf_change_pct, 1)}%），目标年份存活率由 {pct(cmp.left.r_at_target, 2)} 变为{' '}
                  {pct(cmp.right.r_at_target, 2)}，判定 {cmp.delta?.verdict_change}。」
                  同时应说明改动的具体内容（换料/降温/加冗余）与成本，才构成完整的工程决策记录。
                </span>
              }
            />
          </>
        )}
      </Card>
    </div>
  )
}
