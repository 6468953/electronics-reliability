/**
 * pages/Params.tsx — 参数库与来源（可核验性的落地）
 *
 * 【为什么要把参数库单独做成一页】
 * 任何可靠性报告的评审都会问同一句话：「这个基础失效率是哪来的？」
 * 如果答"系统里就是这么写的"，报告就废了。所以这一页把每个可调参数
 * 连同它的标准出处、版本号、免责声明一起摊开：
 *     环境倍率 π_E 怎么排的、质量因子 π_Q 取几、每个类别的 λb 是多少、
 *     温度项用的是幂律还是 Arrhenius、电应力项的指数是几。
 *
 * 【为什么参数改动要"版本化"而不是"随手改"】
 * 参数一变，同一份 BOM 算出的 MTBF 就变。历史评估里存了 param_version，
 * 才能保证"三个月后翻出这份报告，数字还是那个数字"。
 * 所以真实项目里升级参数库应当是"发一个新版本文件"，而不是原地改数值。
 */

import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
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
  Typography,
  message,
} from 'antd'
import { DatabaseOutlined, InfoCircleOutlined, SearchOutlined } from '@ant-design/icons'
import { getParamSet, listParamVersions } from '../api'
import { DATA_QUALITY, STANDARD_TEXT, num } from '../utils/format'

/** 把某类别的 stress_spec 压成一行可读的说明 */
function describeSpec(spec: any): string {
  if (!spec || !Object.keys(spec).length) return '—'
  const parts: string[] = []
  if (spec.pi_T) {
    const f = spec.pi_T.formula
    if (f === 'arrhenius') {
      parts.push(`π_T: Arrhenius(Ea=${spec.pi_T.ea_ev ?? '?'} eV)`)
    } else if (f === 'power_law') {
      parts.push(`π_T: 幂律(n=${spec.pi_T.exponent}, 参考 ${spec.pi_T.ref_temp_c}°C)`)
    } else {
      parts.push(`π_T: ${f}`)
    }
  }
  if (spec.pi_V) parts.push(`π_V: (V/额定)^${spec.pi_V.exponent}+1`)
  if (spec.pi_S) parts.push(`π_S: (P/额定)^${spec.pi_S.exponent}+1`)
  if (spec.default_delta_t_c) parts.push(`ΔT 默认 ${spec.default_delta_t_c}°C`)
  return parts.join('；')
}

export default function Params() {
  const [versions, setVersions] = useState<any[]>([])
  const [standard, setStandard] = useState<string>('MIL-217F')
  const [detail, setDetail] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [kw, setKw] = useState('')
  const [group, setGroup] = useState<string>('all')

  useEffect(() => {
    listParamVersions()
      .then((v) => setVersions(v))
      .catch((e) => message.error(e.message))
  }, [])

  useEffect(() => {
    setLoading(true)
    getParamSet(standard)
      .then(setDetail)
      .catch((e) => {
        message.error(e.message)
        setDetail(null)
      })
      .finally(() => setLoading(false))
  }, [standard])

  const groups = useMemo(() => {
    const s = new Set<string>()
    ;(detail?.categories || []).forEach((c: any) => s.add(c.group))
    return Array.from(s)
  }, [detail])

  const cats = useMemo(() => {
    let r = detail?.categories || []
    if (group !== 'all') r = r.filter((c: any) => c.group === group)
    if (kw.trim()) {
      const q = kw.trim().toLowerCase()
      r = r.filter((c: any) => (c.code + c.name + c.family).toLowerCase().includes(q))
    }
    return [...r].sort((a: any, b: any) => b.lambda_g - a.lambda_g)
  }, [detail, group, kw])

  return (
    <div>
      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 12, fontSize: 12.5 }}
        message="这些是示例值，不是认证依据"
        description="参数库按公开标准的典型值整理，用于演示与教学。真实项目的 λb 应取自标准原文表格、厂家失效率报告或本单位历史数据；不同版本标准之间数值也不通用。"
      />

      <Row gutter={12} style={{ marginBottom: 12 }}>
        {versions.map((v) => (
          <Col xs={12} md={8} xl={4} key={v.standard}>
            <Card size="small" variant="borderless" style={{ background: '#F7F9FC', height: '100%' }}>
              <div style={{ fontSize: 11.5, color: '#8c8c8c' }}>{v.standard}</div>
              <div style={{ fontSize: 13.5, fontWeight: 600, marginTop: 2 }}>
                {v.display_name || v.filename}
              </div>
              <div style={{ marginTop: 4 }}>
                <Tag color="blue">{v.version_tag || '—'}</Tag>
                {v.category_count ? <Tag>{v.category_count} 类</Tag> : null}
              </div>
            </Card>
          </Col>
        ))}
      </Row>

      <Card
        size="small"
        variant="borderless"
        style={{ border: '1px solid #EEE', marginBottom: 12 }}
        title={
          <Space>
            <DatabaseOutlined />
            <span>参数详情</span>
          </Space>
        }
        extra={
          <Segmented
            size="small"
            value={standard}
            onChange={(v) => setStandard(v as string)}
            options={[
              { label: 'MIL-HDBK-217F', value: 'MIL-217F' },
              { label: 'Telcordia SR-332', value: 'TELCORDIA_SR332' },
            ]}
          />
        }
      >
        {loading && !detail ? (
          <div style={{ padding: 50, textAlign: 'center' }}>
            <Spin />
          </div>
        ) : !detail ? (
          <Empty description="参数库不可用" />
        ) : (
          <>
            <Typography.Paragraph style={{ fontSize: 12.5, marginBottom: 6 }}>
              <b>{detail.display_name}</b>（{detail.version_tag}）· 共 {detail.category_count} 个类目
              {(() => {
                const dq = DATA_QUALITY[detail.data_quality] || {
                  label: detail.data_quality || '未知',
                  color: 'default',
                  hint: '',
                }
                return (
                  <Tooltip title={dq.hint}>
                    <Tag color={dq.color} style={{ marginLeft: 8 }}>
                      数据成色：{dq.label}
                    </Tag>
                  </Tooltip>
                )
              })()}
            </Typography.Paragraph>
            {detail.data_quality_note && (
              <Typography.Paragraph style={{ fontSize: 12, color: '#8C8C8C', marginBottom: 6 }}>
                {detail.data_quality_note}
              </Typography.Paragraph>
            )}
            <Typography.Paragraph style={{ fontSize: 12.5, marginBottom: 6 }}>
              <b>标准出处：</b>
              {detail.source_ref}
            </Typography.Paragraph>
            <Alert
              type="info"
              showIcon
              icon={<InfoCircleOutlined />}
              style={{ fontSize: 12.5, marginBottom: 12 }}
              message={detail.disclaimer}
              description={
                detail.notes && Object.keys(detail.notes).length ? (
                  <ul style={{ paddingLeft: 18, margin: '4px 0 0', lineHeight: 1.8 }}>
                    {Object.entries(detail.notes).map(([k, v]) => (
                      <li key={k}>
                        <b>{k}：</b>
                        {String(v)}
                      </li>
                    ))}
                  </ul>
                ) : undefined
              }
            />

            <Row gutter={12}>
              <Col xs={24} xl={12}>
                <Card
                  size="small"
                  title="环境倍率 π_E（影响最大的一项）"
                  variant="borderless"
                  style={{ border: '1px solid #EEE', marginBottom: 12 }}
                  styles={{ body: { padding: 0 } }}
                >
                  <Table
                    size="small"
                    rowKey="code"
                    pagination={false}
                    dataSource={detail.environments || []}
                    columns={[
                      { title: '代号', dataIndex: 'code', width: 80 },
                      { title: '环境', dataIndex: 'label' },
                      {
                        title: '倍率',
                        dataIndex: 'mult',
                        width: 90,
                        align: 'right' as const,
                        render: (v: number) => <b>×{num(v, 1)}</b>,
                      },
                    ]}
                  />
                </Card>
              </Col>
              <Col xs={24} xl={12}>
                <Card
                  size="small"
                  title="质量因子 π_Q"
                  variant="borderless"
                  style={{ border: '1px solid #EEE', marginBottom: 12 }}
                  styles={{ body: { padding: 0 } }}
                >
                  <Table
                    size="small"
                    rowKey="code"
                    pagination={false}
                    dataSource={detail.quality_levels || []}
                    columns={[
                      { title: '代号', dataIndex: 'code', width: 110 },
                      { title: '等级', dataIndex: 'label' },
                      {
                        title: 'π_Q',
                        dataIndex: 'pi_q',
                        width: 90,
                        align: 'right' as const,
                        render: (v: number) => <b>{num(v, 2)}</b>,
                      },
                    ]}
                  />
                </Card>
              </Col>
            </Row>

            <Card
              size="small"
              title={`类别基础失效率 λb（${cats.length} 项）`}
              variant="borderless"
              style={{ border: '1px solid #EEE' }}
              extra={
                <Space wrap>
                  <Tag
                    color={group === 'all' ? 'blue' : undefined}
                    style={{ cursor: 'pointer' }}
                    onClick={() => setGroup('all')}
                  >
                    全部组
                  </Tag>
                  {groups.map((g) => (
                    <Tag
                      key={g}
                      color={group === g ? 'blue' : undefined}
                      style={{ cursor: 'pointer' }}
                      onClick={() => setGroup(g)}
                    >
                      {g}
                    </Tag>
                  ))}
                  <Input
                    size="small"
                    allowClear
                    prefix={<SearchOutlined />}
                    placeholder="搜编码/名称/family"
                    style={{ width: 170 }}
                    onChange={(e) => setKw(e.target.value)}
                  />
                </Space>
              }
              styles={{ body: { padding: 0 } }}
            >
              <Table
                size="small"
                rowKey="code"
                dataSource={cats}
                pagination={cats.length > 20 ? { pageSize: 20, size: 'small' } : false}
                columns={[
                  { title: '编码', dataIndex: 'code', width: 120 },
                  { title: '名称', dataIndex: 'name', width: 160 },
                  { title: '分组', dataIndex: 'group', width: 100 },
                  {
                    title: 'family（因子链模板）',
                    dataIndex: 'family',
                    width: 170,
                    render: (v: string) => <code style={{ fontSize: 11.5 }}>{v}</code>,
                  },
                  {
                    title: (
                      <Tooltip title="零件计数法/应力法使用的基准失效率，单位 FIT">
                        <span>
                          λb (FIT) <InfoCircleOutlined style={{ fontSize: 10 }} />
                        </span>
                      </Tooltip>
                    ),
                    dataIndex: 'lambda_g',
                    width: 100,
                    align: 'right' as const,
                    defaultSortOrder: 'descend' as const,
                    sorter: (a: any, b: any) => a.lambda_g - b.lambda_g,
                    render: (v: number) => <b>{num(v, 3)}</b>,
                  },
                  {
                    title: '应力法因子链',
                    dataIndex: 'stress_spec',
                    render: (v: any) => (
                      <span className="muted" style={{ fontSize: 11.5 }}>
                        {describeSpec(v)}
                      </span>
                    ),
                  },
                ]}
              />
            </Card>

            <Card
              size="small"
              variant="borderless"
              style={{ border: '1px solid #EEE', marginTop: 12 }}
              title="公式与口径（这份参数库到底在算什么）"
            >
              <Row gutter={16}>
                <Col xs={24} md={12}>
                  <Typography.Paragraph style={{ fontSize: 12.5, marginBottom: 6 }}>
                    <b>零件计数法：</b> λ = Σ (λb × π_Q × π_E × 数量)
                    <br />
                    <span className="muted">
                      不含温度项。所以 {STANDARD_TEXT[standard]} 的计数法结果对"环境温度"不敏感——这不是 bug，
                      是标准本身的取舍（用环境类别代替温度细节）。
                    </span>
                  </Typography.Paragraph>
                  <Typography.Paragraph style={{ fontSize: 12.5, marginBottom: 0 }}>
                    <b>零件应力法：</b> λ = Σ (λb × π_T × π_V/π_S × π_Q × π_E × 数量)
                  </Typography.Paragraph>
                </Col>
                <Col xs={24} md={12}>
                  <Typography.Paragraph style={{ fontSize: 12.5, marginBottom: 6 }}>
                    <b>温度项两种写法：</b>
                  </Typography.Paragraph>
                  <div style={{ fontSize: 12, lineHeight: 2 }}>
                    <div>
                      <code>π_T = ((T+273)/(T_ref+273))^n</code>
                      <span className="muted"> — 幂律，MIL 常用，n 按器件族取 3~5</span>
                    </div>
                    <div>
                      <code>π_T = exp((Ea/k)(1/T_ref − 1/T_op))</code>
                      <span className="muted"> — Arrhenius，k = 8.617×10⁻⁵ eV/K</span>
                    </div>
                    <div className="muted" style={{ marginTop: 4 }}>
                      两者都是"温度升 → λ 升"，但斜率不同。报告里必须写明用的是哪一种。
                    </div>
                  </div>
                </Col>
              </Row>
            </Card>
          </>
        )}
      </Card>
    </div>
  )
}
