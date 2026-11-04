/**
 * workspace/ClassifyTab.tsx — 模块二/三：自动分类结果与人工确认
 *
 * 【这一屏解决什么问题】
 * 自动分类一定会有分不准的行。系统不能"猜错了就静默算进去"，也不能"全都让人确认"。
 * 所以采用三级分流：
 *     ≥ 70 分  → 自动归类（不打扰人）
 *     30~70 分 → 进待确认队列（人只需要点一下）
 *     < 30 分  → 未识别（人需要主动选类目）
 * 这一屏就是"30~70 分与 <30 分"这部分人的工作台。
 *
 * 【为什么候选要露出来，不只显示一个结论】
 * 分类的可信度来自"理由可看"。如果只显示「已归为 铝电解电容」，
 * 用户没法判断是碰巧命中了 0.1uF 这种通用词，还是真的识别出了 ALU 标记。
 * 所以每个候选都展开三个分数：关键词命中（强信号）、IDF 覆盖率（描述像不像这一类）、
 * 字符相似（写法接近度）。用户看一眼就知道该不该信。
 *
 * 【批量确认的意义】
 * 真实 BOM 里同一料号常有几十行（不同位号）。逐行点是折磨，
 * 所以支持勾选多行 → 一次指定一个类目 → 全部确认，并且只学习一次关键词。
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Empty,
  Input,
  Modal,
  Progress,
  Radio,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import {
  CheckCircleOutlined,
  ReloadOutlined,
  RobotOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import Chart from '../../components/Chart'
import { Term } from '../../components/Term'
import {
  classifyFeedback,
  classifyQueue,
  classifyStats,
  confirmBatch,
  confirmItem,
  listCategories,
  runClassify,
} from '../../api'
import { pct } from '../../utils/format'

const STATUS_TAG: Record<string, { color: string; text: string }> = {
  auto: { color: 'blue', text: '自动归类' },
  pending_review: { color: 'gold', text: '待确认' },
  unrecognized: { color: 'red', text: '未识别' },
  confirmed: { color: 'green', text: '已确认' },
  unclassified: { color: 'default', text: '未分类' },
}

/** 把类目树拍平成 Select 需要的分组结构：{label: 大类名, options: [{value, label}]} */
function toGroupedOptions(tree: any[]) {
  return tree.map((m) => ({
    label: `${m.name}（${m.code}）`,
    options: (m.children || []).map((c: any) => ({
      value: c.code,
      label: `${c.name} · ${c.code}`,
    })),
  }))
}

export default function ClassifyTab({ version, onChanged }: { version: any; onChanged: () => void }) {
  const vid = version?.id
  const [stats, setStats] = useState<any>(null)
  const [queue, setQueue] = useState<any>({ total: 0, items: [] })
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined)
  const [kw, setKw] = useState('')
  const [loading, setLoading] = useState(false)
  const [running, setRunning] = useState(false)
  const [tree, setTree] = useState<any[]>([])
  const [feedback, setFeedback] = useState<any>(null)
  const [picked, setPicked] = useState<Record<number, string>>({})
  const [selected, setSelected] = useState<number[]>([])
  const [batchOpen, setBatchOpen] = useState(false)
  const [batchCode, setBatchCode] = useState<string | undefined>()
  const [batchLearn, setBatchLearn] = useState(true)

  const [confirmRow, setConfirmRow] = useState<any>(null)
  const [applySimilar, setApplySimilar] = useState(false)
  const [learn, setLearn] = useState(true)
  const [busy, setBusy] = useState(false)

  const grouped = useMemo(() => toGroupedOptions(tree), [tree])
  const codeName = useMemo(() => {
    const m: Record<string, string> = {}
    tree.forEach((major) =>
      (major.children || []).forEach((c: any) => {
        m[c.code] = c.name
      }),
    )
    return m
  }, [tree])

  const loadStats = useCallback(async () => {
    if (!vid) return
    try {
      setStats(await classifyStats(vid))
    } catch (e: any) {
      message.error(e.message)
    }
  }, [vid])

  const loadQueue = useCallback(async () => {
    if (!vid) return
    setLoading(true)
    try {
      const r = await classifyQueue(vid, { status: statusFilter, page, page_size: 20 })
      setQueue(r)
      // 默认选中引擎最看好的候选，让人"确认"而不是"从零开始选"
      const init: Record<number, string> = {}
      r.items.forEach((it: any) => {
        if (it.candidates?.length) init[it.id] = it.candidates[0].category_code
      })
      setPicked(init)
      setSelected([])
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }, [vid, statusFilter, page])

  useEffect(() => {
    listCategories()
      .then((d) => setTree(d.tree || []))
      .catch(() => setTree([]))
    classifyFeedback()
      .then(setFeedback)
      .catch(() => setFeedback(null))
  }, [])

  useEffect(() => {
    loadStats()
    loadQueue()
  }, [loadStats, loadQueue])

  const rerun = async (onlyUnclassified: boolean) => {
    if (!vid) return
    setRunning(true)
    try {
      const r = await runClassify(vid, onlyUnclassified)
      message.success(
        `分类完成：自动 ${r.auto} 行（${r.auto_pct}%），待确认 ${r.pending_review} 行，未识别 ${r.unrecognized} 行` +
          (r.skipped ? `，跳过已人工确认 ${r.skipped} 行` : ''),
      )
      setPage(1)
      await Promise.all([loadStats(), loadQueue()])
      onChanged()
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setRunning(false)
    }
  }

  const doConfirm = async () => {
    if (!confirmRow || !picked[confirmRow.id]) {
      message.warning('请先选择类目')
      return
    }
    setBusy(true)
    try {
      const r = await confirmItem(confirmRow.id, {
        category_code: picked[confirmRow.id],
        apply_to_similar: applySimilar,
        learn,
      })
      message.success(
        `已归为「${r.category_name}」` +
          (r.applied_to_similar ? `，并同步了 ${r.applied_to_similar} 行相似描述` : '') +
          (r.learned_keywords?.length ? `；学到关键词：${r.learned_keywords.join('、')}` : ''),
      )
      setConfirmRow(null)
      setApplySimilar(false)
      await Promise.all([loadStats(), loadQueue()])
      onChanged()
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setBusy(false)
    }
  }

  const doBatch = async () => {
    if (!selected.length || !batchCode) {
      message.warning('请勾选行并指定类目')
      return
    }
    setBusy(true)
    try {
      const r = await confirmBatch(vid, { item_ids: selected, category_code: batchCode, learn: batchLearn })
      message.success(
        `批量确认 ${r.confirmed} 行 → ${codeName[batchCode] || batchCode}` +
          (r.learned_keywords?.length ? `；学到：${r.learned_keywords.join('、')}` : ''),
      )
      setBatchOpen(false)
      setBatchCode(undefined)
      await Promise.all([loadStats(), loadQueue()])
      onChanged()
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setBusy(false)
    }
  }

  const rows = (queue.items || []).filter((it: any) =>
    kw ? (it.description + it.part_number).toLowerCase().includes(kw.toLowerCase()) : true,
  )

  const st = stats?.status || {}

  const barOption = useMemo(() => {
    const data = (stats?.by_major || []).slice(0, 12).reverse()
    return {
      grid: { left: 100, right: 40, top: 10, bottom: 24 },
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      xAxis: { type: 'value', name: '行数', splitLine: { lineStyle: { type: 'dashed' } } },
      yAxis: { type: 'category', data: data.map((d: any) => d.name) },
      series: [
        {
          type: 'bar',
          data: data.map((d: any) => d.count),
          barMaxWidth: 18,
          itemStyle: { borderRadius: [0, 4, 4, 0] },
          label: { show: true, position: 'right', fontSize: 11 },
        },
      ],
    }
  }, [stats])

  return (
    <div>
      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col xs={12} md={6}>
          <Card size="small" variant="borderless" style={{ background: '#F7F9FC' }}>
            <Statistic title="BOM 行数" value={stats?.total ?? 0} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small" variant="borderless" style={{ background: '#F7F9FC' }}>
            <Statistic
              title="自动归类率"
              value={stats?.auto_pct ?? 0}
              suffix="%"
              valueStyle={{ color: (stats?.auto_pct ?? 0) >= 80 ? '#1B7F3B' : '#D48806' }}
            />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small" variant="borderless" style={{ background: '#F7F9FC' }}>
            <Statistic title="已完成分类" value={stats?.classified_pct ?? 0} suffix="%" />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card size="small" variant="borderless" style={{ background: '#F7F9FC' }}>
            <Statistic
              title="待处理"
              value={stats?.pending_total ?? 0}
              suffix="行"
              valueStyle={{ color: (stats?.pending_total ?? 0) > 0 ? '#C0392B' : '#1B7F3B' }}
            />
          </Card>
        </Col>
      </Row>

      <Card
        size="small"
        variant="borderless"
        style={{ marginBottom: 12, background: '#FCFCFD' }}
        styles={{ body: { padding: 12 } }}
      >
        <Space wrap>
          <Button type="primary" icon={<ThunderboltOutlined />} loading={running} onClick={() => rerun(false)}>
            重新分类全部行
          </Button>
          <Tooltip title="跳过已人工确认的行，只处理自动归类与待确认">
            <Button icon={<RobotOutlined />} loading={running} onClick={() => rerun(true)}>
              只处理未确认
            </Button>
          </Tooltip>
          <Button icon={<ReloadOutlined />} onClick={() => { loadStats(); loadQueue() }}>
            刷新
          </Button>
          {feedback && (
            <span className="muted" style={{ fontSize: 12 }}>
              引擎学习：累计人工确认 {feedback.total} 次，与引擎建议一致率 {pct((feedback.accept_rate ?? 0) / 100, 1)}
            </span>
          )}
        </Space>
      </Card>

      {!!st.pending_review && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message={`${st.pending_review} 行处于「待确认」：模型有把握但不完全确定，评估前必须先确认`}
          description="未确认的行不会进入可靠性计算（避免把猜错的分类静默算进结果）。这是有意的设计，不是 bug。"
        />
      )}

      {/* 上半区：分布图 + 口径说明；下半区：整行宽度的队列表。
          早期版本把队列挤在右侧 15/24 的栅格里，料号会被折成竖排（SIM-CASE-006 变成三行），
          表格几乎没法读。 */}
      <Row gutter={12} style={{ marginBottom: 12 }}>
        <Col xs={24} xl={9}>
          <Card
            size="small"
            title="各类目行数分布"
            variant="borderless"
            style={{ border: '1px solid #EEE', height: '100%' }}
            styles={{ body: { paddingTop: 8 } }}
          >
            {(stats?.by_major || []).length ? (
              <Chart option={barOption as any} height={Math.max(200, Math.min(420, (stats?.by_major?.length || 0) * 26))} />
            ) : (
              <Empty description="尚未分类" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </Card>
        </Col>

        <Col xs={24} xl={15}>
          <Card
            size="small"
            title="为什么这几行必须人工确认"
            variant="borderless"
            style={{ border: '1px solid #EEE', height: '100%' }}
          >
            <div style={{ fontSize: 12.5, lineHeight: 1.9 }}>
              <div>
                <Tag color="blue">≥ 70 分</Tag> 自动归类，不打扰人 —— 关键词命中明确（如描述里带 ALU / MLCC / SOT-23）。
              </div>
              <div style={{ marginTop: 4 }}>
                <Tag color="gold">30~70 分</Tag> 进队列，人点一下即可 —— 通常是「只写了规格、没写材质」的描述，
                例如 <code>电容 0.1uF 50V 0603</code>：陶瓷、薄膜、钽都可能这么写。
              </div>
              <div style={{ marginTop: 4 }}>
                <Tag color="red">&lt; 30 分</Tag> 未识别 —— 库里没有的类型（五金件、螺丝、结构件），
                需要人主动选类目，选完可以沉淀成关键词。
              </div>
              <div className="muted" style={{ marginTop: 8 }}>
                未确认的行<strong>不会进入计算</strong>。这是有意的：宁可报错让你确认，
                也不要把猜错的分类静默算进 MTBF。
              </div>
            </div>
          </Card>
        </Col>
      </Row>

      <Card
        size="small"
        variant="borderless"
        style={{ border: '1px solid #EEE' }}
        title={
          <Space>
            <span>待确认队列</span>
            <Tag>{queue.total ?? 0}</Tag>
          </Space>
        }
            extra={
              <Space>
                <Input.Search
                  size="small"
                  placeholder="搜描述/料号"
                  allowClear
                  style={{ width: 170 }}
                  onChange={(e) => setKw(e.target.value)}
                />
                <Select
                  size="small"
                  style={{ width: 120 }}
                  allowClear
                  placeholder="全部状态"
                  value={statusFilter}
                  onChange={(v) => {
                    setStatusFilter(v)
                    setPage(1)
                  }}
                  options={[
                    { value: 'pending_review', label: '待确认' },
                    { value: 'unrecognized', label: '未识别' },
                  ]}
                />
                <Button
                  size="small"
                  type="primary"
                  icon={<CheckCircleOutlined />}
                  disabled={!selected.length}
                  onClick={() => setBatchOpen(true)}
                >
                  批量确认{selected.length ? `（${selected.length}）` : ''}
                </Button>
              </Space>
            }
            styles={{ body: { padding: 0 } }}
          >
            <Table
              size="small"
              rowKey="id"
              loading={loading}
              dataSource={rows}
              pagination={{
                current: page,
                pageSize: 20,
                total: queue.total,
                showSizeChanger: false,
                onChange: setPage,
                showTotal: (t) => `共 ${t} 行待处理`,
              }}
              rowSelection={{
                selectedRowKeys: selected,
                onChange: (keys) => setSelected(keys as number[]),
              }}
              expandable={{
                expandedRowRender: (row: any) => (
                  <div style={{ padding: '4px 8px' }}>
                    <div style={{ fontSize: 12, marginBottom: 6 }}>
                      <b>引擎理由：</b>
                      <span className="muted">{row.match_reason || '（无）'}</span>
                    </div>
                    <Table
                      size="small"
                      rowKey="category_code"
                      pagination={false}
                      dataSource={row.candidates || []}
                      locale={{ emptyText: '没有任何候选，需要手工选择类目' }}
                      columns={[
                        { title: '候选类目', dataIndex: 'category_name', width: 160 },
                        { title: '编码', dataIndex: 'category_code', width: 110 },
                        {
                          title: '综合分',
                          dataIndex: 'score',
                          width: 90,
                          render: (v: number) => <b>{(v * 100).toFixed(1)}</b>,
                        },
                        {
                          title: '关键词',
                          dataIndex: 'keyword_score',
                          width: 80,
                          render: (v: number) => (v * 100).toFixed(0),
                        },
                        {
                          title: 'IDF 覆盖',
                          dataIndex: 'idf_score',
                          width: 90,
                          render: (v: number) => (v * 100).toFixed(0),
                        },
                        {
                          title: '写法接近',
                          dataIndex: 'char_score',
                          width: 90,
                          render: (v: number) => (v * 100).toFixed(0),
                        },
                        {
                          title: '命中的关键词',
                          dataIndex: 'hits',
                          render: (hits: string[]) =>
                            hits?.length ? (
                              <Space size={4} wrap>
                                {hits.slice(0, 6).map((h) => (
                                  <Tag key={h} color="blue" style={{ margin: 0 }}>
                                    {h}
                                  </Tag>
                                ))}
                              </Space>
                            ) : (
                              <span className="muted">—</span>
                            ),
                        },
                        {
                          title: '负向词',
                          dataIndex: 'negatives',
                          width: 120,
                          render: (n: string[]) =>
                            n?.length ? (
                              <Space size={4} wrap>
                                {n.map((x) => (
                                  <Tag key={x} color="red" style={{ margin: 0 }}>
                                    {x}
                                  </Tag>
                                ))}
                              </Space>
                            ) : (
                              <span className="muted">—</span>
                            ),
                        },
                      ]}
                    />
                  </div>
                ),
              }}
              columns={[
                { title: '行', dataIndex: 'line_no', width: 52 },
                {
                  title: '料号 / 描述',
                  dataIndex: 'description',
                  render: (_: any, row: any) => (
                    <div style={{ maxWidth: 360 }}>
                      <div
                        style={{
                          fontWeight: 500,
                          whiteSpace: 'nowrap',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                        }}
                      >
                        {row.part_number || '—'}
                      </div>
                      <Tooltip title={row.description} placement="topLeft">
                        <div
                          className="muted"
                          style={{
                            fontSize: 12,
                            lineHeight: 1.5,
                            display: '-webkit-box',
                            WebkitLineClamp: 2,
                            WebkitBoxOrient: 'vertical',
                            overflow: 'hidden',
                          }}
                        >
                          {row.description}
                        </div>
                      </Tooltip>
                    </div>
                  ),
                },
                { title: '用量', dataIndex: 'qty', width: 64, align: 'right' as const },
                {
                  title: '状态',
                  dataIndex: 'match_status',
                  width: 86,
                  render: (v: string) => {
                    const m = STATUS_TAG[v] || { color: 'default', text: v }
                    return <Tag color={m.color}>{m.text}</Tag>
                  },
                },
                {
                  title: '置信度',
                  dataIndex: 'match_score',
                  width: 100,
                  render: (v: number | null) =>
                    v === null || v === undefined ? (
                      <span className="muted">—</span>
                    ) : (
                      <Progress
                        percent={Math.round(v * 100)}
                        size="small"
                        strokeColor={v >= 0.7 ? '#1B7F3B' : v >= 0.3 ? '#D48806' : '#C0392B'}
                        format={(p) => `${p}`}
                      />
                    ),
                },
                {
                  title: '选定类目',
                  width: 230,
                  render: (_: any, row: any) => (
                    <Select
                      size="small"
                      style={{ width: '100%' }}
                      placeholder="选择类目"
                      showSearch
                      optionFilterProp="label"
                      value={picked[row.id]}
                      onChange={(v) => setPicked((p) => ({ ...p, [row.id]: v }))}
                      options={[
                        ...(row.candidates || []).map((c: any) => ({
                          value: c.category_code,
                          label: `★ ${c.category_name}（${Math.round(c.score * 100)}）`,
                        })),
                        ...grouped.map((g) => ({
                          label: g.label,
                          options: g.options.filter(
                            (o: any) => !(row.candidates || []).some((c: any) => c.category_code === o.value),
                          ),
                        })),
                      ]}
                    />
                  ),
                },
                {
                  title: '',
                  width: 70,
                  render: (_: any, row: any) => (
                    <Button size="small" type="link" onClick={() => setConfirmRow(row)}>
                      确认
                    </Button>
                  ),
                },
              ]}
            />
      </Card>

      {/* ---- 单行确认 ---- */}
      <Modal
        open={!!confirmRow}
        title="确认分类"
        onCancel={() => setConfirmRow(null)}
        onOk={doConfirm}
        okText="确认归类"
        confirmLoading={busy}
        destroyOnHidden
      >
        {confirmRow && (
          <div>
            <div style={{ marginBottom: 10, fontSize: 13 }}>
              <div className="muted" style={{ fontSize: 12 }}>
                第 {confirmRow.line_no} 行 · {confirmRow.part_number}
              </div>
              <div style={{ marginTop: 2 }}>{confirmRow.description}</div>
            </div>

            <div style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 12, marginBottom: 6 }}>选定类目</div>
              <Select
                style={{ width: '100%' }}
                showSearch
                optionFilterProp="label"
                value={picked[confirmRow.id]}
                onChange={(v) => setPicked((p) => ({ ...p, [confirmRow.id]: v }))}
                options={[
                  ...(confirmRow.candidates || []).map((c: any) => ({
                    value: c.category_code,
                    label: `★ ${c.category_name}（引擎建议，${Math.round(c.score * 100)} 分）`,
                  })),
                  ...grouped,
                ]}
              />
            </div>

            <div style={{ marginBottom: 8 }}>
              <Checkbox checked={applySimilar} onChange={(e) => setApplySimilar(e.target.checked)}>
                同时应用到描述高度相似的其它行
                <span className="muted" style={{ fontSize: 12 }}>
                  （相似度 ≥ 85%，只影响未人工确认的行）
                </span>
              </Checkbox>
            </div>
            <div>
              <Checkbox checked={learn} onChange={(e) => setLearn(e.target.checked)}>
                把这次改判沉淀为知识库关键词
                <span className="muted" style={{ fontSize: 12 }}>
                  （只在与引擎建议不同时生效，权重从 2.0 起，最多 4.0）
                </span>
              </Checkbox>
            </div>

            {confirmRow.candidates?.[0] &&
              picked[confirmRow.id] &&
              confirmRow.candidates[0].category_code !== picked[confirmRow.id] && (
                <Alert
                  type="info"
                  showIcon
                  style={{ marginTop: 12 }}
                  message="这是一次改判"
                  description={`引擎建议「${confirmRow.candidates[0].category_name}」，你选了「${
                    codeName[picked[confirmRow.id]] || picked[confirmRow.id]
                  }」。勾选"沉淀关键词"后，下次遇到相似描述会直接命中你的选择。`}
                />
              )}
          </div>
        )}
      </Modal>

      {/* ---- 批量确认 ---- */}
      <Modal
        open={batchOpen}
        title={`批量确认 ${selected.length} 行`}
        onCancel={() => setBatchOpen(false)}
        onOk={doBatch}
        okText="全部归入该类目"
        confirmLoading={busy}
        destroyOnHidden
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12.5 }}>
          批量确认会把勾选的所有行设为同一类目。只建议用于"同一料号的多行"或"明确同一族"的情况；
          混合内容应逐行确认，否则会污染知识库（学习只发生一次）。
        </Typography.Paragraph>
        <Select
          style={{ width: '100%', marginBottom: 12 }}
          placeholder="选择目标类目"
          showSearch
          optionFilterProp="label"
          value={batchCode}
          onChange={setBatchCode}
          options={grouped}
        />
        <Checkbox checked={batchLearn} onChange={(e) => setBatchLearn(e.target.checked)}>
          把改判沉淀为知识库关键词
        </Checkbox>
      </Modal>
    </div>
  )
}
