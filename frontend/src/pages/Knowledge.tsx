/**
 * pages/Knowledge.tsx — 模块二：零件分类知识库维护
 *
 * 【知识库为什么必须"可维护"】
 * 分类准确率不是一次性做出来的。真实项目里总会出现库里没有的写法和新器件
 * （"固态高分子电容""氮化镓 MOS""保险管 Φ5×20"）。如果只能改代码，
 * 现场就会退化成"人工一条条选"，系统也就废了。
 * 所以这一页把类目、关键词、权重、负向词全部放开给工程师维护。
 *
 * 【关键词的 source 为什么要显示】
 *   seed     种子词（建库时按标准类目写入，权重高）
 *   learned  自动学习（人工改判时沉淀下来的，权重 2.0 起步，上限 4.0）
 *   manual   人工添加
 * 出现误判时，第一件事就是看"是哪一类词在起作用"。自动学习的词默认权重低，
 * 就是为了不让人工维护的知识被机器悄悄覆盖。
 *
 * 【权重怎么调（一线经验）】
 * 命中一个关键词的贡献 ≈ 权重 × 6 分（KW_SCALE）。所以：
 *   2.0 → 明显倾向这一类；  4.0 → 几乎等于拍板；
 *   想让一个词"只是提示、不决定"，用 1.0 以下。
 * 负向词（is_negative）的作用是"看到它就扣分"，用来区分共享规格的近似件，
 * 例如陶瓷电容与铝电解都可能写 0.1uF 50V，靠"ALU/电解"这类负向词分开。
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Segmented,
  Space,
  Spin,
  Switch,
  Table,
  Tag,
  Tooltip,
  Tree,
  Typography,
  message,
} from 'antd'
import {
  ApartmentOutlined,
  DeleteOutlined,
  PlusOutlined,
  SaveOutlined,
  SearchOutlined,
} from '@ant-design/icons'
import {
  addKeyword,
  deleteKeyword,
  getCategory,
  getStoredUser,
  listCategories,
  updateCategory,
  updateKeyword,
} from '../api'

const SOURCE_META: Record<string, { color: string; text: string }> = {
  seed: { color: 'blue', text: '种子词' },
  learned: { color: 'purple', text: '自动学习' },
  manual: { color: 'green', text: '人工添加' },
}

export default function Knowledge() {
  const user = getStoredUser()
  const isAdmin = user?.role === 'admin'

  const [tree, setTree] = useState<any[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  const [detail, setDetail] = useState<any>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [kw, setKw] = useState('')
  const [onlyNeg, setOnlyNeg] = useState<string>('all')
  const [addOpen, setAddOpen] = useState(false)
  const [addForm] = Form.useForm()
  const [editOpen, setEditOpen] = useState(false)
  const [editForm] = Form.useForm()

  const loadTree = useCallback(async () => {
    setLoading(true)
    try {
      const d = await listCategories()
      setTree(d.tree || [])
      setTotal(d.total || 0)
      if (!selected && d.tree?.length) {
        const first = d.tree.find((m: any) => m.children?.length) || d.tree[0]
        const code = first.children?.[0]?.code || first.code
        setSelected(code)
      }
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }, [selected])

  const loadDetail = useCallback(async (code: string) => {
    setDetailLoading(true)
    try {
      setDetail(await getCategory(code))
    } catch (e: any) {
      message.error(e.message)
      setDetail(null)
    } finally {
      setDetailLoading(false)
    }
  }, [])

  useEffect(() => {
    loadTree()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (selected) loadDetail(selected)
  }, [selected, loadDetail])

  const treeData = useMemo(() => {
    const filterNodes = (nodes: any[]): any[] =>
      nodes
        .map((n) => {
          const children = n.children ? filterNodes(n.children) : undefined
          const hit = !kw || (n.name + n.code).toLowerCase().includes(kw.toLowerCase()) || (children?.length ?? 0) > 0
          if (!hit) return null
          return {
            key: n.code,
            title: (
              <span style={{ fontSize: 13 }}>
                {n.name}
                <span className="muted" style={{ fontSize: 11, marginLeft: 4 }}>
                  {n.code}
                </span>
                {n.children ? (
                  <Tag style={{ marginLeft: 6, fontSize: 10 }}>{n.children.length}</Tag>
                ) : (
                  <Tag style={{ marginLeft: 6, fontSize: 10 }} color="blue">
                    {n.keyword_count}
                  </Tag>
                )}
              </span>
            ),
            children,
          }
        })
        .filter(Boolean) as any[]
    return filterNodes(tree)
  }, [tree, kw])

  const keywords = useMemo(() => {
    let ks = detail?.keywords || []
    if (onlyNeg === 'pos') ks = ks.filter((k: any) => !k.is_negative)
    else if (onlyNeg === 'neg') ks = ks.filter((k: any) => k.is_negative)
    return ks
  }, [detail, onlyNeg])

  const doAdd = async () => {
    const v = await addForm.validateFields()
    try {
      await addKeyword(selected as string, v)
      message.success('关键词已添加')
      setAddOpen(false)
      addForm.resetFields()
      await Promise.all([loadDetail(selected as string), loadTree()])
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const toggleKeyword = async (k: any, active: boolean) => {
    try {
      await updateKeyword(k.id, { is_active: active })
      await loadDetail(selected as string)
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const changeWeight = async (k: any, weight: number) => {
    try {
      await updateKeyword(k.id, { weight })
      message.success(`「${k.keyword}」权重改为 ${weight}`)
      await loadDetail(selected as string)
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const removeKeyword = async (k: any) => {
    try {
      await deleteKeyword(k.id)
      message.success('已删除')
      await Promise.all([loadDetail(selected as string), loadTree()])
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const saveCategory = async () => {
    const v = await editForm.validateFields()
    try {
      await updateCategory(detail.code, {
        name: v.name,
        description: v.description,
        aliases: v.aliases ? v.aliases.split(/[，,;；\s]+/).filter(Boolean) : [],
        samples: v.samples ? v.samples.split(/\n+/).filter(Boolean) : [],
      })
      message.success('已保存')
      setEditOpen(false)
      await Promise.all([loadDetail(detail.code), loadTree()])
    } catch (e: any) {
      message.error(e.message)
    }
  }

  return (
    <div>
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12, fontSize: 12.5 }}
        message="知识库驱动分类引擎：类目 → 关键词（含权重与负向词）→ 匹配分数"
        description="改这里会立刻影响下一次「重新分类」的结果，但不会改变历史评估（评估是快照）。调完建议回项目页重跑分类，并观察自动归类率的变化。"
      />

      <Row gutter={14}>
        {/* ---- 左：类目树 ---- */}
        <Col xs={24} xl={8}>
          <Card
            size="small"
            variant="borderless"
            style={{ border: '1px solid #EEE' }}
            title={
              <Space>
                <ApartmentOutlined />
                <span>类目树</span>
                <Tag>{total}</Tag>
              </Space>
            }
            extra={
              <Input
                size="small"
                allowClear
                prefix={<SearchOutlined />}
                placeholder="搜类目"
                style={{ width: 130 }}
                onChange={(e) => setKw(e.target.value)}
              />
            }
            styles={{ body: { padding: 8, maxHeight: 620, overflow: 'auto' } }}
          >
            {loading ? (
              <div style={{ padding: 40, textAlign: 'center' }}>
                <Spin />
              </div>
            ) : (
              <Tree
                treeData={treeData}
                selectedKeys={selected ? [selected] : []}
                defaultExpandAll
                blockNode
                onSelect={(keys) => keys[0] && setSelected(String(keys[0]))}
              />
            )}
          </Card>
        </Col>

        {/* ---- 右：类目详情 + 关键词 ---- */}
        <Col xs={24} xl={16}>
          {!detail ? (
            <Card size="small" variant="borderless" style={{ border: '1px solid #EEE' }}>
              {detailLoading ? (
                <div style={{ padding: 60, textAlign: 'center' }}>
                  <Spin />
                </div>
              ) : (
                <Empty description="请选择左侧类目" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              )}
            </Card>
          ) : (
            <>
              <Card
                size="small"
                variant="borderless"
                style={{ border: '1px solid #EEE', marginBottom: 12 }}
                title={
                  <Space wrap>
                    <span style={{ fontSize: 14, fontWeight: 600 }}>{detail.name}</span>
                    <Tag>{detail.code}</Tag>
                    <Tag color={detail.level === 1 ? 'geekblue' : 'default'}>
                      {detail.level === 1 ? '大类' : `小类 · 父级 ${detail.parent_code}`}
                    </Tag>
                    {!detail.is_active && <Tag color="red">已停用</Tag>}
                  </Space>
                }
                extra={
                  isAdmin && (
                    <Button
                      size="small"
                      icon={<SaveOutlined />}
                      onClick={() => {
                        editForm.setFieldsValue({
                          name: detail.name,
                          description: detail.description,
                          aliases: (detail.aliases || []).join('，'),
                          samples: (detail.samples || []).join('\n'),
                        })
                        setEditOpen(true)
                      }}
                    >
                      编辑
                    </Button>
                  )
                }
              >
                <Typography.Paragraph style={{ fontSize: 12.5, marginBottom: 8 }}>
                  {detail.description || <span className="muted">（暂无描述）</span>}
                </Typography.Paragraph>
                <div style={{ fontSize: 12.5 }}>
                  <b>别名：</b>
                  {(detail.aliases || []).length ? (
                    <Space size={4} wrap>
                      {detail.aliases.map((a: string) => (
                        <Tag key={a}>{a}</Tag>
                      ))}
                    </Space>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </div>
                {(detail.samples || []).length > 0 && (
                  <div style={{ fontSize: 12.5, marginTop: 6 }}>
                    <b>典型描述样例：</b>
                    <ul style={{ paddingLeft: 18, margin: '4px 0 0', lineHeight: 1.8 }}>
                      {detail.samples.map((s: string, i: number) => (
                        <li key={i} className="muted">
                          {s}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </Card>

              <Card
                size="small"
                variant="borderless"
                style={{ border: '1px solid #EEE' }}
                title={
                  <Space>
                    <span>关键词</span>
                    <Tag color="blue">{detail.keyword_count} 正向</Tag>
                    <Tag color="red">{detail.negative_count} 负向</Tag>
                  </Space>
                }
                extra={
                  <Space>
                    <Segmented
                      size="small"
                      value={onlyNeg}
                      onChange={(v) => setOnlyNeg(v as string)}
                      options={[
                        { label: '全部', value: 'all' },
                        { label: '正向', value: 'pos' },
                        { label: '负向', value: 'neg' },
                      ]}
                    />
                    <Tooltip title={isAdmin ? '' : '需要管理员权限'}>
                      <Button
                        size="small"
                        type="primary"
                        icon={<PlusOutlined />}
                        disabled={!isAdmin}
                        onClick={() => setAddOpen(true)}
                      >
                        添加
                      </Button>
                    </Tooltip>
                  </Space>
                }
                styles={{ body: { padding: 0 } }}
              >
                <Table
                  size="small"
                  rowKey="id"
                  dataSource={keywords}
                  pagination={keywords.length > 15 ? { pageSize: 15, size: 'small' } : false}
                  locale={{ emptyText: '该类目还没有关键词——没有关键词就只能靠描述相似度硬猜' }}
                  columns={[
                    {
                      title: '关键词',
                      dataIndex: 'keyword',
                      render: (v: string, r: any) => (
                        <span>
                          {r.is_negative && (
                            <Tag color="red" style={{ marginRight: 4 }}>
                              负向
                            </Tag>
                          )}
                          <code style={{ fontSize: 12.5 }}>{v}</code>
                        </span>
                      ),
                    },
                    {
                      title: '权重',
                      dataIndex: 'weight',
                      width: 130,
                      render: (v: number, r: any) =>
                        isAdmin ? (
                          <InputNumber
                            size="small"
                            min={0.1}
                            max={10}
                            step={0.5}
                            defaultValue={v}
                            style={{ width: 82 }}
                            onBlur={(e) => {
                              const nv = Number((e.target as HTMLInputElement).value)
                              if (nv && nv !== v) changeWeight(r, nv)
                            }}
                          />
                        ) : (
                          v
                        ),
                    },
                    {
                      title: '来源',
                      dataIndex: 'source',
                      width: 100,
                      render: (v: string) => {
                        const m = SOURCE_META[v] || { color: 'default', text: v }
                        return <Tag color={m.color}>{m.text}</Tag>
                      },
                    },
                    {
                      title: '命中次数',
                      dataIndex: 'hit_count',
                      width: 92,
                      align: 'right' as const,
                      render: (v: number) => (v ? <b>{v}</b> : <span className="muted">0</span>),
                    },
                    {
                      title: '启用',
                      dataIndex: 'is_active',
                      width: 76,
                      render: (v: boolean, r: any) => (
                        <Switch
                          size="small"
                          checked={v}
                          disabled={!isAdmin}
                          onChange={(nv) => toggleKeyword(r, nv)}
                        />
                      ),
                    },
                    {
                      title: '',
                      width: 56,
                      render: (_: any, r: any) =>
                        isAdmin ? (
                          <Popconfirm
                            title="删除这个关键词？"
                            description="删除后无法恢复。若只是想停用，请关掉右边的开关。"
                            onConfirm={() => removeKeyword(r)}
                          >
                            <Button size="small" type="text" danger icon={<DeleteOutlined />} />
                          </Popconfirm>
                        ) : null,
                    },
                  ]}
                />
                <div className="muted" style={{ fontSize: 11.5, padding: '8px 12px', lineHeight: 1.8 }}>
                  命中一个关键词约贡献「权重 × 6 分」。权重 2.0 是明显倾向，4.0 接近拍板；
                  负向词会在同类候选上扣分，用来区分"共享规格但不同材质"的近似件。
                  自动学习的词上限 4.0，避免一次改判就把知识库带偏。
                </div>
              </Card>
            </>
          )}
        </Col>
      </Row>

      {/* ---- 添加关键词 ---- */}
      <Modal
        open={addOpen}
        title={`为「${detail?.name || ''}」添加关键词`}
        onCancel={() => setAddOpen(false)}
        onOk={doAdd}
        okText="添加"
        destroyOnHidden
      >
        <Form form={addForm} layout="vertical" initialValues={{ weight: 2.0, is_negative: false }}>
          <Form.Item
            name="keyword"
            label="关键词"
            rules={[{ required: true, message: '请输入关键词' }]}
            extra="引擎会做归一化（去空格、统一单位符号），所以「105℃」「105 °C」写一种即可"
          >
            <Input placeholder="如：铝电解 / ALU / 固态高分子" />
          </Form.Item>
          <Form.Item
            name="weight"
            label="权重"
            extra="2.0 = 明显倾向；4.0 = 接近拍板；0.5 = 仅作提示"
          >
            <InputNumber min={0.1} max={10} step={0.5} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="is_negative"
            label="负向词"
            valuePropName="checked"
            extra="打开表示「看到它就该扣分」，用于排除近似件"
          >
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      {/* ---- 编辑类目 ---- */}
      <Modal
        open={editOpen}
        title="编辑类目"
        onCancel={() => setEditOpen(false)}
        onOk={saveCategory}
        okText="保存"
        destroyOnHidden
        width={620}
      >
        <Form form={editForm} layout="vertical">
          <Form.Item name="name" label="类目名称" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="说明（给工程师看的一句话定义）">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name="aliases" label="别名" extra="用逗号分隔，如：电解电容，铝电解，ALU">
            <Input />
          </Form.Item>
          <Form.Item name="samples" label="典型描述样例" extra="每行一条。这些样例不参与打分，只作为维护时的参照">
            <Input.TextArea rows={4} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
