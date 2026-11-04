/**
 * workspace/AssessTab.tsx — 模块四：评估假设与发起计算
 *
 * 【为什么"假设"要放在计算的必经路径上，而且必须显式确认】
 * 可靠性预计的误差 90% 来自假设，不是来自公式。同一块板：
 *     40°C + 商用级  → MTBF 40 万小时
 *     25°C + 汽车级  → MTBF 300 万小时
 * 差 7 倍。如果系统"默认帮你填好"然后一键出数，用户会把那个数当客观事实。
 * 所以这一屏把四个参数（环境类别 / 环境温度 / 质量等级 / 日通电占比）摆到最前面，
 * 并配三个预设场景——预设的作用是"给出可解释的起点"，不是"替用户决定"。
 *
 * 【计数法 vs 应力法怎么选】
 *   计数法：只看"用了多少个什么器件 + 环境 + 质量"。适合方案早期，BOM 还不完整时。
 *   应力法：还看每个件实际承受的电压/电流/功率/温升。更准，但要求 BOM 里有应力数据。
 * 本系统默认计数法，应力法在缺数据时会用类别默认值兜底并在结果里标注提醒。
 *
 * 【双标准要不要都跑】
 * 本屏只选一个作为"主口径"落库，但结果页提供"双标准对比"（基于同一次假设重算），
 * 保证除标准外其他条件完全一致，对比才有意义。
 */

import { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Divider,
  Form,
  Input,
  InputNumber,
  Radio,
  Row,
  Segmented,
  Select,
  Slider,
  Space,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import { ExperimentOutlined, InfoCircleOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { Term, TermIcon } from '../../components/Term'
import { classifyStats, getParamSet, runAssess } from '../../api'
import { pct } from '../../utils/format'

/** 三个预设场景：数值取工程上常见的"室内消费电子 / 工业柜内 / 户外"设定。 */
const PRESETS = [
  {
    key: 'consumer',
    label: '室内消费电子',
    desc: '室内常温、商用级器件、每天通电 8 小时。最常见也最宽松的假设。',
    env: 'GB',
    temp: 35,
    quality: 'commercial',
    duty: 8,
  },
  {
    key: 'industrial',
    label: '工业控制柜',
    desc: '柜内温升明显、工业级器件、常年不间断运行。温度是主导因素。',
    env: 'GB',
    temp: 55,
    quality: 'industrial',
    duty: 24,
  },
  {
    key: 'outdoor',
    label: '户外/车载',
    desc: '日夜温差与振动、汽车级器件、每天 12 小时。环境倍率显著变差。',
    env: 'GM',
    temp: 65,
    quality: 'automotive',
    duty: 12,
  },
]

export default function AssessTab({
  project,
  version,
  onAssessed,
}: {
  project: any
  version: any
  onAssessed: (assessmentId: number) => void
}) {
  const [form] = Form.useForm()
  const [params, setParams] = useState<any>(null)
  const [running, setRunning] = useState(false)
  const [stats, setStats] = useState<any>(null)
  const [advanced, setAdvanced] = useState(false)
  const standard = Form.useWatch('standard', form) || 'MIL-217F'
  const mode = Form.useWatch('mode', form) || 'parts_count'
  const duty = Form.useWatch('duty_hours_per_day', form) ?? 8

  useEffect(() => {
    form.setFieldsValue({
      environment: 'GB',
      ambient_temp_c: 40,
      quality_level: 'commercial',
      duty_hours_per_day: 8,
      target_years: project?.target_years ?? 5,
      target_survival: project?.target_survival ?? 0.95,
      mtbf_threshold_hours: project?.mtbf_threshold_hours ?? undefined,
      standard: 'MIL-217F',
      mode: 'parts_count',
      note: '',
    })
  }, [form, project])

  useEffect(() => {
    getParamSet(standard)
      .then(setParams)
      .catch(() => setParams(null))
  }, [standard])

  useEffect(() => {
    if (version?.id) classifyStats(version.id).then(setStats).catch(() => setStats(null))
  }, [version?.id])

  const envOptions = useMemo(
    () =>
      (params?.environments || []).map((e: any) => ({
        value: e.code,
        label: `${e.label}（${e.code}，×${e.mult}）`,
      })),
    [params],
  )
  const qualityOptions = useMemo(
    () =>
      (params?.quality_levels || []).map((q: any) => ({
        value: q.code,
        label: `${q.label}（π_Q = ${q.pi_q}）`,
      })),
    [params],
  )

  const applyPreset = (p: (typeof PRESETS)[number]) => {
    form.setFieldsValue({
      environment: p.env,
      ambient_temp_c: p.temp,
      quality_level: p.quality,
      duty_hours_per_day: p.duty,
    })
    message.success(`已套用「${p.label}」预设，可继续微调`)
  }

  const submit = async () => {
    const v = await form.validateFields()
    setRunning(true)
    try {
      const r = await runAssess(project.id, {
        bom_version_id: version.id,
        assumption: {
          environment: v.environment,
          ambient_temp_c: v.ambient_temp_c,
          quality_level: v.quality_level,
          duty_hours_per_day: v.duty_hours_per_day,
          target_years: v.target_years,
          target_survival: v.target_survival,
          mtbf_threshold_hours: v.mtbf_threshold_hours || null,
          standard: v.standard,
          mode: v.mode,
        },
        with_sensitivity: true,
        note: v.note || '',
      })
      const a = r.result?.assessment || {}
      message.success(
        `评估完成：MTBF ${Math.round(a.mtbf_hours || 0).toLocaleString('zh-CN')} h，` +
          `目标 ${v.target_years} 年存活率 ${pct(a.r_at_target, 2)} → ${a.verdict === 'PASS' ? '通过' : '不通过'}`,
      )
      onAssessed(r.assessment.id)
    } catch (e: any) {
      message.error(e.message)
    } finally {
      setRunning(false)
    }
  }

  const pending = stats?.pending_total ?? 0

  return (
    <Row gutter={16}>
      <Col xs={24} xl={15}>
        <Card size="small" variant="borderless" style={{ border: '1px solid #EEE' }}>
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontSize: 12, color: '#8c8c8c', marginBottom: 6 }}>快速预设（给出可解释的起点）</div>
            <Space wrap>
              {PRESETS.map((p) => (
                <Tooltip key={p.key} title={p.desc}>
                  <Button size="small" onClick={() => applyPreset(p)}>
                    {p.label}
                  </Button>
                </Tooltip>
              ))}
            </Space>
          </div>

          <Divider style={{ margin: '10px 0' }} />

          <Form form={form} layout="vertical" size="middle" requiredMark={false}>
            <Row gutter={14}>
              <Col xs={24} md={12}>
                <Form.Item
                  name="environment"
                  label={
                    <span>
                      环境类别 <TermIcon k="pie" />
                    </span>
                  }
                  rules={[{ required: true }]}
                  extra="器件装在什么环境里。这是四项假设里影响最大的一项（GB→GM 差 4 倍）"
                >
                  <Select options={envOptions} showSearch optionFilterProp="label" />
                </Form.Item>
              </Col>
              <Col xs={24} md={12}>
                <Form.Item
                  name="ambient_temp_c"
                  label={
                    <span>
                      环境温度（°C） <TermIcon k="arrhenius" />
                    </span>
                  }
                  rules={[{ required: true }]}
                  extra="机箱内的空气温度，不是室温。一般比室温高 10~20°C"
                >
                  <InputNumber min={-40} max={125} step={5} style={{ width: '100%' }} suffix="°C" />
                </Form.Item>
              </Col>
              <Col xs={24} md={12}>
                <Form.Item
                  name="quality_level"
                  label={
                    <span>
                      质量等级 <TermIcon k="piq" />
                    </span>
                  }
                  rules={[{ required: true }]}
                  extra="器件本身的筛选等级。商用级最便宜但 π_Q 最大"
                >
                  <Select options={qualityOptions} />
                </Form.Item>
              </Col>
              <Col xs={24} md={12}>
                <Form.Item
                  name="duty_hours_per_day"
                  label={
                    <span>
                      日通电小时 <TermIcon k="duty" />
                    </span>
                  }
                  rules={[{ required: true }]}
                  extra={`当前 ≈ ${((duty / 24) * 100).toFixed(0)}% 占空比，影响存活率的时间轴折算`}
                >
                  <Slider min={0.5} max={24} step={0.5} marks={{ 8: '8h', 12: '12h', 24: '24h' }} />
                </Form.Item>
              </Col>
            </Row>

            <Divider style={{ margin: '4px 0 14px' }}>判定目标</Divider>

            <Row gutter={14}>
              <Col xs={24} md={8}>
                <Form.Item name="target_years" label={<Term k="rt">目标年限</Term>} rules={[{ required: true }]}>
                  <InputNumber min={0.5} max={30} step={0.5} style={{ width: '100%' }} suffix="年" />
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item
                  name="target_survival"
                  label="目标存活率"
                  rules={[{ required: true }]}
                  extra="例：0.95 表示 5 年后至少 95% 的设备仍正常"
                >
                  <InputNumber min={0.5} max={0.9999} step={0.01} style={{ width: '100%' }} />
                </Form.Item>
              </Col>
              <Col xs={24} md={8}>
                <Form.Item
                  name="mtbf_threshold_hours"
                  label={<Term k="mtbf">MTBF 门槛</Term>}
                  extra="可选。填了才做 MTBF 硬性判定"
                >
                  <InputNumber min={0} step={10000} style={{ width: '100%' }} suffix="h" placeholder="如 430000" />
                </Form.Item>
              </Col>
            </Row>

            <Divider style={{ margin: '4px 0 14px' }}>计算口径</Divider>

            <Row gutter={14}>
              <Col xs={24} md={12}>
                <Form.Item name="standard" label="预计标准" rules={[{ required: true }]}>
                  <Radio.Group optionType="button" buttonStyle="solid">
                    <Radio.Button value="MIL-217F">
                      <Term k="parts_count">MIL-HDBK-217F</Term>
                    </Radio.Button>
                    <Radio.Button value="TELCORDIA_SR332">Telcordia SR-332</Radio.Button>
                  </Radio.Group>
                </Form.Item>
              </Col>
              <Col xs={24} md={12}>
                <Form.Item name="mode" label="预计方法" rules={[{ required: true }]}>
                  <Radio.Group optionType="button" buttonStyle="solid">
                    <Radio.Button value="parts_count">零件计数法</Radio.Button>
                    <Radio.Button value="parts_stress">零件应力法</Radio.Button>
                  </Radio.Group>
                </Form.Item>
              </Col>
            </Row>

            {params && (
              <Alert
                type="info"
                showIcon
                icon={<InfoCircleOutlined />}
                style={{ marginBottom: 12, fontSize: 12.5 }}
                message={`${params.display_name} · 参数库 ${params.version_tag}`}
                description={
                  <span className="muted">
                    来源：{params.source_ref}
                    <br />
                    {params.disclaimer}
                  </span>
                }
              />
            )}

            <Space wrap>
              <Button type="primary" size="large" icon={<ExperimentOutlined />} loading={running} onClick={submit}>
                开始评估
              </Button>
              <Button onClick={() => setAdvanced((v) => !v)}>{advanced ? '收起备注' : '添加备注'}</Button>
              <span className="muted" style={{ fontSize: 12 }}>
                基于 BOM 版本 v{version?.version_no} · {version?.row_count} 行
              </span>
            </Space>

            {advanced && (
              <Form.Item name="note" label="本次评估备注" style={{ marginTop: 12, marginBottom: 0 }}>
                <Input.TextArea rows={2} placeholder="例：改用 105°C 电解电容后的第二版方案" maxLength={200} showCount />
              </Form.Item>
            )}
          </Form>
        </Card>
      </Col>

      <Col xs={24} xl={9}>
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          {pending > 0 && (
            <Alert
              type="error"
              showIcon
              message={`还有 ${pending} 行未确认分类`}
              description="未确认的行无法参与计算。请先回到「② 分类确认」处理完队列，否则评估会直接报错。"
            />
          )}

          <Card size="small" title="这两项口径差在哪" variant="borderless" style={{ border: '1px solid #EEE' }}>
            <Typography.Paragraph style={{ fontSize: 12.5, marginBottom: 8 }}>
              <b>计数法</b>：λ = Σ(类别基础失效率 × 环境 × 质量 × 数量)。
              只看"用了多少个什么件"，不看实际加了多少电压电流。方案早期 BOM 不全时用它。
            </Typography.Paragraph>
            <Typography.Paragraph style={{ fontSize: 12.5, marginBottom: 8 }}>
              <b>应力法</b>：在计数法基础上再乘温度项 π_T 与电应力项 π_V / π_S。
              更接近真实，但要求每行都有应力数据（缺了会用类别默认值兜底并在结果里标注）。
            </Typography.Paragraph>
            <Typography.Paragraph style={{ fontSize: 12.5, marginBottom: 0 }} type="secondary">
              当前选择：<Tag color="blue">{mode === 'parts_stress' ? '零件应力法' : '零件计数法'}</Tag>
              {mode === 'parts_stress' &&
                '应力法在 MIL-217F 下不含温度修正项，温度影响需要靠应力数据体现；Telcordia 下才带 Arrhenius π_T。'}
            </Typography.Paragraph>
          </Card>

          <Card size="small" title="两个标准怎么选" variant="borderless" style={{ border: '1px solid #EEE' }}>
            <Typography.Paragraph style={{ fontSize: 12.5, marginBottom: 8 }}>
              <b>MIL-HDBK-217F</b>：航空航天出身，参数保守，结果偏悲观。客户/军工项目常被要求用它。
            </Typography.Paragraph>
            <Typography.Paragraph style={{ fontSize: 12.5, marginBottom: 8 }}>
              <b>Telcordia SR-332</b>：基于电信设备现场失效数据，结果通常比 MIL 乐观 2 倍左右，
              更接近实际使用寿命。
            </Typography.Paragraph>
            <Typography.Paragraph style={{ fontSize: 12.5, marginBottom: 0 }} type="secondary">
              结论别只看一个数。评估完成后到「④ 预计结果」页做双标准对比，
              把两个数并排写进报告并说明取用理由，才经得起评审。
            </Typography.Paragraph>
          </Card>

          <Card size="small" title="四项假设的物理含义" variant="borderless" style={{ border: '1px solid #EEE' }}>
            <ul style={{ paddingLeft: 18, margin: 0, fontSize: 12.5, lineHeight: 1.9 }}>
              <li>
                <Term k="pie">环境类别</Term>：装在室内还是户外、有没有空调，用一个倍率概括
              </li>
              <li>
                <Term k="arrhenius">环境温度</Term>：温度每升 10°C，多数器件失效率约翻倍
              </li>
              <li>
                <Term k="piq">质量等级</Term>：器件出厂筛选水平，商用级 π_Q 可达军品的 3 倍
              </li>
              <li>
                <Term k="duty">日通电小时</Term>：决定"5 年"到底是 4.4 万小时还是 1.3 万小时
              </li>
            </ul>
          </Card>

          <Alert
            type="warning"
            showIcon
            icon={<ThunderboltOutlined />}
            message="演示数据提醒"
            description="参数库中的基础失效率为公开标准的典型值整理，用于演示与教学。真实认证项目请以正版标准文本与厂家数据为准。"
          />
        </Space>
      </Col>
    </Row>
  )
}
