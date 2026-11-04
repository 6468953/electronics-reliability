/**
 * workspace/BomTab.tsx — 模块一：BOM 导入与明细
 *
 * 【这一屏的核心矛盾】
 * 用户想快点看到结果，但 BOM 里必然有脏数据。所以这里同时提供三条路：
 *   ① 下载模板 → 上传自己的表（最真实）
 *   ② 一键生成模拟 BOM（最快，用来先跑通流程）
 *   ③ 直接在表格里改（补录应力/额定值，后面降额与磨损要用）
 *
 * 【"解析预览"为什么要露出来】
 * 系统会从描述里猜额定电压/寿命/次数。如果用户看不到猜了什么，
 * 后面降额判"超限"、磨损算"3.7 年"都会被当成黑箱。所以每行都能看到
 * "系统读到了哪些值、是解析来的还是手工填的"。
 */

import { useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Drawer,
  Descriptions,
  Divider,
  Form,
  Input,
  InputNumber,
  InputNumber as Num,
  Modal,
  Radio,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
  Upload,
  message,
} from 'antd'
import { CloudUploadOutlined, DownloadOutlined, EditOutlined, ThunderboltOutlined } from '@ant-design/icons'
import {
  bomTemplate,
  getItem,
  listItems,
  simulateBom,
  updateItem,
  uploadBom,
} from '../../api'
import { num } from '../../utils/format'

const STATUS_TAG: Record<string, { color: string; text: string }> = {
  confirmed: { color: 'green', text: '已确认' },
  auto: { color: 'blue', text: '自动归类' },
  pending_review: { color: 'gold', text: '待确认' },
  unrecognized: { color: 'red', text: '未识别' },
  unclassified: { color: 'default', text: '未分类' },
}

export default function BomTab({
  project,
  version,
  onChanged,
}: {
  project: any
  version: any
  onChanged: () => void
}) {
  const [items, setItems] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState<string | undefined>()
  const [kw, setKw] = useState('')
  const [loading, setLoading] = useState(false)
  const [simOpen, setSimOpen] = useState(false)
  const [simForm] = Form.useForm()
  const [editId, setEditId] = useState<number | null>(null)
  const [detail, setDetail] = useState<any>(null)

  const vid = version?.id

  const load = async (p = page) => {
    if (!vid) return
    setLoading(true)
    try {
      const res = await listItems(vid, { page: p, page_size: 20, status, kw })
      setItems(res.items)
      setTotal(res.total)
      setPage(p)
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load(1)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vid, status])

  const issues = version?.issues || []
  const errors = issues.filter((i: any) => i.level === 'error')
  const warns = issues.filter((i: any) => i.level === 'warn')

  const doSimulate = async () => {
    const v = await simForm.validateFields()
    try {
      message.loading({ content: '正在生成模拟 BOM 并自动分类…', key: 'sim', duration: 0 })
      const res = await simulateBom(project.id, {
        scale: v.scale,
        seed: v.seed,
        label: v.label,
        include_cases: true,
        include_dirty: true,
      })
      message.success({
        content: `已生成 ${res.row_count} 行，自动归类 ${res.classification.auto} 行，待确认 ${res.classification.pending_review + res.classification.unrecognized} 行`,
        key: 'sim',
      })
      setSimOpen(false)
      onChanged()
    } catch (e: any) {
      message.error({ content: e.message, key: 'sim' })
    }
  }

  const openDetail = async (id: number) => {
    try {
      setDetail(await getItem(id))
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const columns = [
    { title: '行', dataIndex: 'line_no', width: 54, fixed: 'left' as const },
    {
      title: '料号 / 规格描述',
      dataIndex: 'description',
      render: (_: any, r: any) => (
        <div>
          <div style={{ fontWeight: 500 }}>{r.part_number}</div>
          <div className="muted" style={{ fontSize: 12 }}>
            {r.description}
          </div>
        </div>
      ),
    },
    { title: '用量', dataIndex: 'qty', width: 66, align: 'right' as const },
    {
      title: '分类',
      dataIndex: 'category_code',
      width: 150,
      render: (c: string, r: any) =>
        c ? (
          <Tooltip title={r.match_reason}>
            <Tag color={STATUS_TAG[r.match_status]?.color}>{r.category_name}</Tag>
          </Tooltip>
        ) : (
          <Tag color={STATUS_TAG[r.match_status]?.color}>{STATUS_TAG[r.match_status]?.text || '未分类'}</Tag>
        ),
    },
    {
      title: '位号',
      dataIndex: 'ref_des',
      width: 130,
      render: (v: string) => <span className="muted">{v || '—'}</span>,
    },
    {
      title: '工作应力 / 额定值',
      width: 210,
      render: (_: any, r: any) => {
        const s = r.stress || {}
        const rt = r.rated || {}
        const fmt = (o: any) =>
          Object.entries(o).length
            ? Object.entries(o)
                .slice(0, 3)
                .map(([k, v]) => `${k}=${v}`)
                .join(' ')
            : '—'
        return (
          <div style={{ fontSize: 12 }}>
            <div>应力：{fmt(s)}</div>
            <div className="muted">额定：{fmt(rt)}</div>
          </div>
        )
      },
    },
    {
      title: '操作',
      width: 110,
      fixed: 'right' as const,
      render: (_: any, r: any) => (
        <Space size={4}>
          <Button size="small" type="link" icon={<EditOutlined />} onClick={() => setEditId(r.id)}>
            编辑
          </Button>
          <Button size="small" type="link" onClick={() => openDetail(r.id)}>
            解析
          </Button>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Row gutter={[12, 12]} style={{ marginBottom: 12 }}>
        <Col xs={24} md={12}>
          <Card size="small" title="导入 BOM" variant="outlined">
            <Space direction="vertical" style={{ width: '100%' }} size={10}>
              <Space wrap>
                <Button icon={<DownloadOutlined />} onClick={() => bomTemplate().catch((e) => message.error(e.message))}>
                  下载模板
                </Button>
                <Upload
                  accept=".xlsx,.csv"
                  showUploadList={false}
                  beforeUpload={async (file) => {
                    try {
                      message.loading({ content: '正在解析并自动分类…', key: 'up', duration: 0 })
                      const res = await uploadBom(project.id, file as File)
                      message.success({
                        content: `导入 ${res.row_count} 行；自动归类 ${res.classification.auto} 行，待确认 ${res.classification.pending_review + res.classification.unrecognized} 行`,
                        key: 'up',
                      })
                      onChanged()
                    } catch (e: any) {
                      message.error({ content: e.message, key: 'up' })
                    }
                    return false
                  }}
                >
                  <Button type="primary" icon={<CloudUploadOutlined />}>
                    上传 BOM（Excel/CSV）
                  </Button>
                </Upload>
                <Button icon={<ThunderboltOutlined />} onClick={() => setSimOpen(true)}>
                  一键生成模拟 BOM
                </Button>
              </Space>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                模板列为：料号、规格描述、用量、位号、备注。描述写得越标准（类型 + 参数 + 封装），自动分类与额定值解析越准。
              </Typography.Text>
            </Space>
          </Card>
        </Col>

        <Col xs={24} md={12}>
          <Card size="small" title="当前 BOM 版本" variant="outlined">
            {version ? (
              <Row gutter={12}>
                <Col span={8}>
                  <Statistic title="版本" value={`v${version.version_no}`} valueStyle={{ fontSize: 18 }} />
                </Col>
                <Col span={8}>
                  <Statistic title="行数" value={version.row_count} valueStyle={{ fontSize: 18 }} />
                </Col>
                <Col span={8}>
                  <Statistic title="元件总数" value={version.qty_total} valueStyle={{ fontSize: 18 }} />
                </Col>
                <Col span={24} style={{ marginTop: 8 }}>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {version.label} · 来源 {version.source === 'simulated' ? '模拟生成' : '上传'} ·{' '}
                    {version.filename || '—'}
                  </Typography.Text>
                </Col>
              </Row>
            ) : (
              <Typography.Text type="secondary">还没有 BOM，请先上传或生成。</Typography.Text>
            )}
          </Card>
        </Col>
      </Row>

      {errors.length > 0 && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 10 }}
          message={`${errors.length} 个错误（阻断）`}
          description={
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {errors.slice(0, 5).map((i: any, k: number) => (
                <li key={k}>{i.message}</li>
              ))}
            </ul>
          }
        />
      )}
      {warns.length > 0 && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 10 }}
          message={`${warns.length} 条提示（不阻断，但建议处理）`}
          description={
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {warns.slice(0, 5).map((i: any, k: number) => (
                <li key={k}>{i.message}</li>
              ))}
            </ul>
          }
        />
      )}

      <Space style={{ marginBottom: 10 }} wrap>
        <Radio.Group
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          options={[
            { label: '全部', value: undefined },
            { label: '自动归类', value: 'auto' },
            { label: '待确认', value: 'pending_review' },
            { label: '未识别', value: 'unrecognized' },
            { label: '已确认', value: 'confirmed' },
          ]}
          optionType="button"
          size="small"
        />
        <Input.Search
          placeholder="搜料号或描述"
          allowClear
          size="small"
          style={{ width: 220 }}
          onSearch={(v) => {
            setKw(v)
            load(1)
          }}
        />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          共 {total} 行
        </Typography.Text>
      </Space>

      <Table
        size="small"
        rowKey="id"
        loading={loading}
        columns={columns as any}
        dataSource={items}
        scroll={{ x: 1080 }}
        pagination={{
          current: page,
          pageSize: 20,
          total,
          showSizeChanger: false,
          onChange: (p) => load(p),
        }}
      />

      <Modal
        title="生成模拟 BOM"
        open={simOpen}
        onOk={doSimulate}
        onCancel={() => setSimOpen(false)}
        okText="生成并自动分类"
        destroyOnHidden
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="模拟数据是刻意设计的"
          description="料号都是真实型号（GRM188R71H104KA93D、RC0603FR-0710KL）、图号（DWG-BRK-1042）或国标号（GB/T818-M3×8-304），不再自拟虚拟料号。包含：同容值同耐压的陶瓷/薄膜/铝电解三兄弟、缺介质的模糊描述、结构件与螺丝、线缆与线束、降额超限的电容、动作次数爆炸的继电器。用来看清三级分流与预警是否真的在工作。"
        />
        <Form form={simForm} layout="vertical" initialValues={{ scale: 200, seed: 42, label: '模拟 BOM' }}>
          <Form.Item
            name="scale"
            label="规模（目标行数）"
            extra="行数 = 不同料号的种类数。料号不做伪造，所以实际行数受内置物料库限制（当前 73 种）；超出部分会并入同料号行的用量，不会凭空造料号。"
          >
            <Radio.Group optionType="button">
              <Radio.Button value={50}>50</Radio.Button>
              <Radio.Button value={200}>200</Radio.Button>
              <Radio.Button value={500}>500</Radio.Button>
              <Radio.Button value={1000}>1000</Radio.Button>
            </Radio.Group>
          </Form.Item>
          <Form.Item name="label" label="版本标签">
            <Input />
          </Form.Item>
          <Form.Item name="seed" label="随机种子" tooltip="同一种子生成完全相同的 BOM，便于复现与对比">
            <Num style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>

      <EditItemModal
        itemId={editId}
        onClose={(changed) => {
          setEditId(null)
          if (changed) {
            load()
            onChanged()
          }
        }}
      />

      <Drawer
        title={detail ? `${detail.part_number}` : '解析详情'}
        width={520}
        open={!!detail}
        onClose={() => setDetail(null)}
      >
        {detail && (
          <>
            <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
              {detail.description}
            </Typography.Paragraph>
            <Divider style={{ margin: '10px 0' }}>系统从描述里解析到的额定值</Divider>
            {Object.keys(detail.parsed_rated || {}).length === 0 ? (
              <Alert type="warning" showIcon message="没解析出任何额定值" description="该零件的降额检查会显示「缺数据」，磨损寿命会走保守默认值。可在「编辑」里手工补录。" />
            ) : (
              <Descriptions column={2} size="small" bordered>
                {Object.entries(detail.parsed_rated).map(([k, v]) => (
                  <Descriptions.Item key={k} label={k}>
                    {String(v)}
                    <Tag style={{ marginLeft: 6 }} color={detail.parsed_sources?.[k] === 'manual' ? 'blue' : 'default'}>
                      {detail.parsed_sources?.[k] === 'manual' ? '手工' : '解析'}
                    </Tag>
                  </Descriptions.Item>
                ))}
              </Descriptions>
            )}
            <Divider style={{ margin: '14px 0' }}>分类判定理由</Divider>
            <Typography.Paragraph style={{ fontSize: 12.5 }}>{detail.match_reason || '—'}</Typography.Paragraph>
            {(detail.candidates || []).length > 0 && (
              <Table
                size="small"
                pagination={false}
                rowKey="category_code"
                dataSource={detail.candidates}
                columns={[
                  { title: '候选类目', dataIndex: 'category_name' },
                  { title: '得分', dataIndex: 'score', render: (v: number) => num(v, 3) },
                  { title: '命中词', dataIndex: 'hits', render: (v: string[]) => (v || []).join('、') || '—' },
                ]}
              />
            )}
          </>
        )}
      </Drawer>
    </div>
  )
}

/** 编辑弹窗：改用量、补录应力与额定值、设置冗余组。 */
function EditItemModal({ itemId, onClose }: { itemId: number | null; onClose: (changed: boolean) => void }) {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!itemId) return
    getItem(itemId)
      .then((d) => {
        form.setFieldsValue({
          qty: d.qty,
          ref_des: d.ref_des,
          voltage_applied: d.stress?.voltage,
          power_applied: d.stress?.power,
          current_applied: d.stress?.current,
          temp_rise_c: d.stress?.temp_rise_c,
          daily_ops: d.stress?.daily_ops,
          voltage_rated: d.rated?.voltage,
          power_rated: d.rated?.power,
          current_rated: d.rated?.current,
          temp_max_c: d.rated?.temp_max_c,
          life_h: d.rated?.life_h,
          cycles: d.rated?.cycles,
          redundancy_group: d.redundancy_group,
        })
      })
      .catch(() => {})
  }, [itemId, form])

  const save = async () => {
    if (!itemId) return
    const v = await form.validateFields()
    setLoading(true)
    try {
      const stress: Record<string, number> = {}
      const rated: Record<string, number> = {}
      if (v.voltage_applied != null) stress.voltage = v.voltage_applied
      if (v.power_applied != null) stress.power = v.power_applied
      if (v.current_applied != null) stress.current = v.current_applied
      if (v.temp_rise_c != null) stress.temp_rise_c = v.temp_rise_c
      if (v.daily_ops != null) stress.daily_ops = v.daily_ops
      if (v.voltage_rated != null) rated.voltage = v.voltage_rated
      if (v.power_rated != null) rated.power = v.power_rated
      if (v.current_rated != null) rated.current = v.current_rated
      if (v.temp_max_c != null) rated.temp_max_c = v.temp_max_c
      if (v.life_h != null) rated.life_h = v.life_h
      if (v.cycles != null) rated.cycles = v.cycles

      await updateItem(itemId, {
        qty: v.qty,
        ref_des: v.ref_des,
        stress,
        rated,
        redundancy_group: v.redundancy_group || null,
      })
      message.success('已保存。重新评估后生效。')
      onClose(true)
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <Modal title="编辑零件" open={!!itemId} onOk={save} onCancel={() => onClose(false)} confirmLoading={loading} destroyOnHidden width={640}>
      <Form form={form} layout="vertical" size="small">
        <Row gutter={12}>
          <Col span={12}>
            <Form.Item name="qty" label="用量">
              <InputNumber min={1} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item name="ref_des" label="位号">
              <Input />
            </Form.Item>
          </Col>
        </Row>

        <Divider style={{ margin: '4px 0 10px' }}>工作应力（应力法 / 磨损计算用）</Divider>
        <Row gutter={12}>
          <Col span={8}>
            <Form.Item name="voltage_applied" label="工作电压 V">
              <InputNumber style={{ width: '100%' }} step={0.1} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="power_applied" label="工作功率 W">
              <InputNumber style={{ width: '100%' }} step={0.01} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="current_applied" label="工作电流 A">
              <InputNumber style={{ width: '100%' }} step={0.01} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="temp_rise_c" label="自升温 °C" tooltip="器件自身发热导致的温升，T_op = 环温 + 该值">
              <InputNumber style={{ width: '100%' }} step={1} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="daily_ops" label="日动作次数" tooltip="继电器/开关/连接器的磨损按动作次数算">
              <InputNumber style={{ width: '100%' }} step={1} />
            </Form.Item>
          </Col>
        </Row>

        <Divider style={{ margin: '4px 0 10px' }}>额定值（降额检查 / 磨损计算用）</Divider>
        <Row gutter={12}>
          <Col span={8}>
            <Form.Item name="voltage_rated" label="额定电压 V">
              <InputNumber style={{ width: '100%' }} step={1} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="power_rated" label="额定功率 W">
              <InputNumber style={{ width: '100%' }} step={0.01} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="current_rated" label="额定电流 A">
              <InputNumber style={{ width: '100%' }} step={0.01} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="temp_max_c" label="额定最高温度 °C">
              <InputNumber style={{ width: '100%' }} step={1} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="life_h" label="额定寿命 h" tooltip="电解电容的 L0（如 2000h@105℃）">
              <InputNumber style={{ width: '100%' }} step={100} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="cycles" label="额定动作次数" tooltip="继电器电气寿命、连接器插拔寿命">
              <InputNumber style={{ width: '100%' }} step={1000} />
            </Form.Item>
          </Col>
        </Row>

        <Form.Item
          name="redundancy_group"
          label="冗余组"
          tooltip="填相同字符串的零件在可靠性框图中按并联处理（任一存活即系统存活）。留空=串联。"
        >
          <Input placeholder="如 PWR-A（同一组的零件填一样的值）" />
        </Form.Item>
      </Form>
    </Modal>
  )
}
