/**
 * pages/Workspace.tsx — 项目工作台
 *
 * 【职责】
 * 只做三件事：加载项目上下文（项目 / BOM 版本 / 最近一次评估）、维护 Tab 状态、
 * 把上下文传给各 Tab。具体业务都在各自 Tab 里，这个文件不写业务逻辑。
 *
 * 【为什么用一个 "assessmentId" 贯穿全程】
 * 评估结果是快照。用户可能对同一份 BOM 跑多轮（换标准、换假设、改冗余）。
 * 结果类 Tab 必须知道自己展示的是哪一份快照，否则切 Tab 时会看到"上一轮的数"。
 */

import { useCallback, useEffect, useState } from 'react'
import { Breadcrumb, Button, Card, Empty, Select, Space, Spin, Tabs, Tag, Typography, message } from 'antd'
import { ArrowLeftOutlined, ExperimentOutlined, ReloadOutlined } from '@ant-design/icons'
import { Link, useParams } from 'react-router-dom'
import { getProject, listAssessments } from '../api'
import { num, pct, VERDICT_META } from '../utils/format'

import BomTab from './workspace/BomTab'
import ClassifyTab from './workspace/ClassifyTab'
import AssessTab from './workspace/AssessTab'
import ResultTab from './workspace/ResultTab'
import WearTab from './workspace/WearTab'
import DeratingTab from './workspace/DeratingTab'
import SensTab from './workspace/SensTab'
import ReportTab from './workspace/ReportTab'

export default function Workspace() {
  const { id } = useParams()
  const projectId = Number(id)
  const [project, setProject] = useState<any>(null)
  const [version, setVersion] = useState<any>(null)
  const [assessments, setAssessments] = useState<any[]>([])
  const [assessmentId, setAssessmentId] = useState<number | null>(null)
  const [tab, setTab] = useState('bom')
  const [loading, setLoading] = useState(true)
  const [versionId, setVersionId] = useState<number | null>(null)

  const reload = useCallback(
    async (keepTab = true) => {
      setLoading(true)
      try {
        const p = await getProject(projectId)
        setProject(p)
        const vid = versionId || p.current_bom_version_id || p.bom_versions?.[0]?.id
        setVersionId(vid)
        if (vid) {
          const v = p.bom_versions?.find((x: any) => x.id === vid) || p.bom_versions?.[0]
          setVersion({ ...v, project_id: p.id })
        }
        const as = await listAssessments(projectId)
        setAssessments(as)
        if (as.length && (assessmentId === null || !as.some((a) => a.id === assessmentId))) {
          setAssessmentId(as[0].id)
        }
        if (!keepTab) setTab('bom')
      } catch (e: any) {
        message.error(e.message)
      } finally {
        setLoading(false)
      }
    },
    [projectId, versionId, assessmentId],
  )

  useEffect(() => {
    reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  const latest = assessments.find((a) => a.id === assessmentId)

  if (loading && !project) {
    return (
      <div style={{ padding: 80, textAlign: 'center' }}>
        <Spin size="large" />
      </div>
    )
  }

  if (!project) {
    return <Empty description="项目不存在或无权访问" />
  }

  const tabs = [
    {
      key: 'bom',
      label: '① BOM 导入',
      children: <BomTab project={project} version={version} onChanged={() => reload()} />,
    },
    {
      key: 'classify',
      label: '② 分类确认',
      children: version ? (
        <ClassifyTab version={version} onChanged={() => reload()} />
      ) : (
        <Empty description="请先导入 BOM" />
      ),
    },
    {
      key: 'assess',
      label: '③ 假设与评估',
      children: version ? (
        <AssessTab
          project={project}
          version={version}
          onAssessed={(aid) => {
            setAssessmentId(aid)
            reload()
            setTab('result')
          }}
        />
      ) : (
        <Empty description="请先导入 BOM" />
      ),
    },
    {
      key: 'result',
      label: '④ 预计结果',
      children: <ResultTab project={project} assessmentId={assessmentId} assessments={assessments} onChangeAssessment={setAssessmentId} />,
    },
    {
      key: 'wear',
      label: '⑤ 磨损寿命',
      children: <WearTab assessmentId={assessmentId} />,
    },
    {
      key: 'derating',
      label: '⑥ 降额检查',
      children: <DeratingTab assessmentId={assessmentId} onNeedReassess={() => setTab('assess')} />,
    },
    {
      key: 'sens',
      label: '⑦ 敏感性',
      children: <SensTab assessmentId={assessmentId} />,
    },
    {
      key: 'report',
      label: '⑧ 报告',
      children: <ReportTab project={project} assessmentId={assessmentId} onReported={() => reload()} />,
    },
  ]

  return (
    <div>
      <Breadcrumb
        style={{ marginBottom: 10 }}
        items={[
          { title: <Link to="/">总览</Link> },
          { title: project.name },
        ]}
      />

      <Card variant="borderless" style={{ marginBottom: 14, boxShadow: '0 1px 3px rgba(16,24,40,.06)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16, flexWrap: 'wrap' }}>
          <div>
            <Space align="center" size={10}>
              <Typography.Title level={5} style={{ margin: 0 }}>
                {project.name}
              </Typography.Title>
              <Tag>{project.code}</Tag>
              {latest && (
                <Tag color={VERDICT_META[latest.verdict]?.tag === 'success' ? 'success' : latest.verdict === 'FAIL' ? 'error' : 'default'}>
                  最近判定：{VERDICT_META[latest.verdict]?.text || latest.verdict}
                </Tag>
              )}
            </Space>
            <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
              目标：{project.target_years} 年存活率 ≥ {pct(project.target_survival, 0)}
              {project.mtbf_threshold_hours ? ` ；MTBF 门槛 ${num(project.mtbf_threshold_hours, 0)} h` : ''}
              {latest ? ` ；最近 MTBF ${num(latest.mtbf_hours, 0)} h` : ''}
            </div>
          </div>

          <Space wrap>
            {(project.bom_versions?.length ?? 0) > 1 && (
              <Select
                size="small"
                style={{ minWidth: 190 }}
                value={versionId || undefined}
                onChange={(v) => {
                  setVersionId(v)
                  const ver = project.bom_versions.find((x: any) => x.id === v)
                  setVersion({ ...ver, project_id: project.id })
                }}
                options={project.bom_versions.map((v: any) => ({
                  value: v.id,
                  label: `v${v.version_no} · ${v.label}（${v.row_count} 行）`,
                }))}
              />
            )}
            {assessments.length > 0 && (
              <Select
                size="small"
                style={{ minWidth: 240 }}
                value={assessmentId || undefined}
                onChange={setAssessmentId}
                options={assessments.map((a) => ({
                  value: a.id,
                  label: `#${a.id} ${a.standard} / ${a.mode === 'parts_count' ? '计数法' : '应力法'} · ${a.verdict} · ${a.created_at.slice(5, 16)}`,
                }))}
              />
            )}
            <Button size="small" icon={<ReloadOutlined />} onClick={() => reload()}>
              刷新
            </Button>
            <Link to="/">
              <Button size="small" icon={<ArrowLeftOutlined />}>
                返回
              </Button>
            </Link>
          </Space>
        </div>
      </Card>

      <Card variant="borderless" style={{ boxShadow: '0 1px 3px rgba(16,24,40,.06)' }} styles={{ body: { paddingTop: 6 } }}>
        <Tabs activeKey={tab} onChange={setTab} items={tabs} destroyOnHidden={false} />
      </Card>
    </div>
  )
}
