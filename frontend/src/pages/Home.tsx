/**
 * pages/Home.tsx — 总览与项目列表
 *
 * 【这一页要回答的问题】
 * "我现在有哪些项目、每个走到哪一步、上一个结论是什么"。
 * 所以卡片上放的是状态徽标 + 最近一次评估的 MTBF / R(t) / 判定，
 * 而不是项目描述这类静态信息——后者点进去再看就行。
 *
 * 【新手引导】
 * 首次进入用 Tour 走三步：看项目卡 → 打开演示项目 → 说明工作台按 Tab 串行。
 * 引导只帮人找到入口，不阻塞操作（可随时关闭）。
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import {
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
  Statistic,
  Tag,
  Tooltip,
  Tour,
  Typography,
  message,
} from 'antd'
import {
  DeleteOutlined,
  PlusOutlined,
  ProjectOutlined,
  ReloadOutlined,
  RightOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { createProject, deleteProject, getDashboard, listProjects } from '../api'
import { Term } from '../components/Term'
import { VERDICT_META, num, pct } from '../utils/format'

const STATUS_META: Record<string, { text: string; color: string }> = {
  draft: { text: '草稿', color: 'default' },
  bom_ready: { text: 'BOM 已导入', color: 'blue' },
  classified: { text: '分类已完成', color: 'cyan' },
  assessed: { text: '已评估', color: 'purple' },
  reported: { text: '已出报告', color: 'green' },
  archived: { text: '已归档', color: 'default' },
}

export default function Home() {
  const [projects, setProjects] = useState<any[]>([])
  const [dash, setDash] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()
  const [tourOpen, setTourOpen] = useState(false)
  const nav = useNavigate()
  const refCards = useRef<HTMLDivElement>(null)
  const refNew = useRef<HTMLDivElement>(null)

  const load = async () => {
    setLoading(true)
    try {
      const [ps, d] = await Promise.all([listProjects(), getDashboard()])
      setProjects(ps)
      setDash(d)
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    if (!localStorage.getItem('relsys_tour_done')) {
      setTimeout(() => setTourOpen(true), 700)
    }
  }, [])

  const onCreate = async () => {
    const v = await form.validateFields()
    try {
      // 表单上按百分数填（95），后端与计算核心一律用小数（0.95）。
      // 这一步以前漏了，结果存进去是 95，卡片显示「存活率 ≥ 9500%」，判定永远不通过。
      const p = await createProject({ ...v, target_survival: v.target_survival / 100 })
      message.success('项目已创建')
      setOpen(false)
      form.resetFields()
      nav(`/projects/${p.id}`)
    } catch (e: any) {
      message.error(e.message)
    }
  }

  const stats = useMemo(
    () => [
      { title: '项目数', value: dash?.project_count ?? projects.length, suffix: '个' },
      { title: '评估次数', value: dash?.assessment_count ?? 0, suffix: '次' },
      { title: '判定通过', value: dash?.pass_count ?? 0, suffix: '次', color: '#1B7F3B' },
      { title: '判定不通过', value: dash?.fail_count ?? 0, suffix: '次', color: '#C0392B' },
    ],
    [dash, projects.length],
  )

  return (
    <div>
      <Row gutter={[14, 14]}>
        {stats.map((s) => (
          <Col xs={12} md={6} key={s.title}>
            <Card size="small" variant="borderless" style={{ boxShadow: '0 1px 3px rgba(16,24,40,.06)' }}>
              <Statistic title={s.title} value={s.value} suffix={<span style={{ fontSize: 12 }}>{s.suffix}</span>} valueStyle={{ color: s.color, fontSize: 24 }} />
            </Card>
          </Col>
        ))}
      </Row>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', margin: '20px 0 12px' }}>
        <div>
          <Typography.Title level={5} style={{ margin: 0 }}>
            我的项目
          </Typography.Title>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            一个项目 = 一份 BOM + 一次分类 + 多轮评估 + 多份报告
          </Typography.Text>
        </div>
        <div ref={refNew} style={{ display: 'flex', gap: 8 }}>
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
            新建项目
          </Button>
        </div>
      </div>

      <div ref={refCards}>
        {projects.length === 0 ? (
          <Card variant="borderless">
            <Empty description="还没有项目。新建一个，或用演示项目直接体验完整流程。" />
          </Card>
        ) : (
          <Row gutter={[14, 14]}>
            {projects.map((p) => {
              const la = p.latest_assessment
              const vm = la ? VERDICT_META[la.verdict] || VERDICT_META.NA : null
              const sm = STATUS_META[p.status] || STATUS_META.draft
              return (
                <Col xs={24} md={12} xl={8} key={p.id}>
                  <Card
                    hoverable
                    variant="borderless"
                    style={{ boxShadow: '0 1px 3px rgba(16,24,40,.06)', height: '100%' }}
                    onClick={() => nav(`/projects/${p.id}`)}
                    actions={[
                      <span key="open" style={{ color: '#3A6EA5' }}>
                        打开工作台 <RightOutlined />
                      </span>,
                      <Popconfirm
                        key="del"
                        title="删除该项目及其全部 BOM / 评估 / 报告？"
                        okText="删除"
                        cancelText="取消"
                        okButtonProps={{ danger: true }}
                        onConfirm={async (e) => {
                          e?.stopPropagation()
                          try {
                            await deleteProject(p.id)
                            message.success('已删除')
                            load()
                          } catch (err: any) {
                            message.error(err.message)
                          }
                        }}
                        onCancel={(e) => e?.stopPropagation()}
                      >
                        <span onClick={(e) => e.stopPropagation()} style={{ color: '#C0392B' }}>
                          <DeleteOutlined /> 删除
                        </span>
                      </Popconfirm>,
                    ]}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                      <div>
                        <div style={{ fontWeight: 600, fontSize: 15, color: '#1F3864' }}>{p.name}</div>
                        <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>
                          {p.code} · {p.bom_version_count} 个 BOM 版本
                        </div>
                      </div>
                      <Tag color={sm.color}>{sm.text}</Tag>
                    </div>

                    <div style={{ marginTop: 14, display: 'flex', gap: 18 }}>
                      <div>
                        <div className="muted" style={{ fontSize: 11 }}>
                          <Term k="mtbf">MTBF</Term>
                        </div>
                        <div style={{ fontSize: 17, fontWeight: 600 }}>
                          {la ? num(la.mtbf_hours, 0) : '—'}
                          <span style={{ fontSize: 11, fontWeight: 400, marginLeft: 3 }}>h</span>
                        </div>
                      </div>
                      <div>
                        <div className="muted" style={{ fontSize: 11 }}>
                          目标存活率
                        </div>
                        <div style={{ fontSize: 17, fontWeight: 600 }}>{la ? pct(la.r_at_target) : '—'}</div>
                      </div>
                      <div>
                        <div className="muted" style={{ fontSize: 11 }}>
                          最近判定
                        </div>
                        <div style={{ fontSize: 17, fontWeight: 600, color: vm?.color }}>
                          {la ? vm?.text : '未评估'}
                        </div>
                      </div>
                    </div>

                    <div style={{ marginTop: 12, fontSize: 12 }} className="muted">
                      目标：{p.target_years} 年存活率 ≥ {pct(p.target_survival, 0)}
                      {p.mtbf_threshold_hours ? ` ；MTBF ≥ ${num(p.mtbf_threshold_hours, 0)} h` : ''}
                    </div>
                  </Card>
                </Col>
              )
            })}
          </Row>
        )}
      </div>

      <Modal
        title="新建项目"
        open={open}
        onOk={onCreate}
        onCancel={() => setOpen(false)}
        okText="创建并进入"
        cancelText="取消"
        destroyOnHidden
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ target_years: 5, target_survival: 95, mtbf_threshold: 430000 }}
        >
          <Form.Item name="name" label="项目名称" rules={[{ required: true, message: '请输入项目名称' }]}>
            <Input placeholder="如：智能网关 GW-200" />
          </Form.Item>
          <Form.Item name="code" label="项目编号" tooltip="留空则自动生成 P-日期-序号">
            <Input placeholder="选填" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} placeholder="选填：产品用途、使用环境等" />
          </Form.Item>
          <Row gutter={12}>
            <Col span={8}>
              <Form.Item name="target_years" label="目标年限（年）" rules={[{ required: true }]}>
                <InputNumber min={0.5} max={50} step={0.5} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="target_survival" label="目标存活率（%）" rules={[{ required: true }]}>
                <InputNumber min={1} max={99.99} step={1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="mtbf_threshold" label="MTBF 门槛（h）" tooltip="留空则不作为判定条件">
                <InputNumber min={0} step={10000} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            存活率在提交时按百分比转成 0~1 的小数；门槛可留空。
          </Typography.Text>
        </Form>
      </Modal>

      <Tour
        open={tourOpen}
        onClose={() => {
          setTourOpen(false)
          localStorage.setItem('relsys_tour_done', '1')
        }}
        steps={[
          {
            title: '这里是你的项目',
            description: '每个卡片显示最近一次评估的 MTBF、存活率与判定。演示项目已经预置了 200 行模拟 BOM。',
            target: () => refCards.current as HTMLElement,
          },
          {
            title: '新建/重新导入',
            description: '可以新建项目并上传自己的 BOM（支持 Excel/CSV，模板可下载），也可以一键生成模拟 BOM。',
            target: () => refNew.current as HTMLElement,
          },
          {
            title: '工作台按流程分 Tab',
            description:
              '打开项目后依次是：BOM → 分类确认 → 假设与评估 → 结果 → 磨损 → 降额 → 敏感性 → 报告。必须按顺序走完才能出结论。',
            target: () => document.body,
          },
        ]}
      />
    </div>
  )
}
