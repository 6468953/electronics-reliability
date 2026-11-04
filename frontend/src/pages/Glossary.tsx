/**
 * pages/Glossary.tsx — 模块八：术语表（新手辅助）
 *
 * 【为什么要单独做一页术语表，而不是只在 Hover 里给提示】
 * 这个系统的用户不都是可靠性工程师：可能是硬件工程师、项目经理、采购。
 * Hover 提示解决"看到不认识的词"，但解决不了"我根本不知道该关心哪些词"。
 * 所以这里按主题分组，把每个词讲三层：
 *     严谨定义（能写进报告的措辞）
 *     大白话（一句话说人话）
 *     例子 + 常见误用（这才是最容易踩的坑）
 *
 * 【为什么每条都要写"常见误用"】
 * 可靠性领域最容易出错的地方不是公式，而是口径：
 * 把 MTBF 当寿命、把 FIT 当百分比、把随机失效的结论套到磨损件上。
 * 这些错误在报告里看起来毫无破绽，但会让整个结论方向反掉。
 */

import { useMemo, useState } from 'react'
import { Alert, Card, Col, Empty, Input, Row, Space, Tag, Typography } from 'antd'
import { BookOutlined, BulbOutlined, SearchOutlined, WarningOutlined } from '@ant-design/icons'
import { useGlossary } from '../components/Term'

const GROUP_COLOR: Record<string, string> = {
  basic: 'blue',
  metric: 'green',
  factor: 'geekblue',
  design: 'purple',
  wear: 'volcano',
}

export default function Glossary() {
  const { list, loading } = useGlossary()
  const [kw, setKw] = useState('')
  const [group, setGroup] = useState<string>('all')

  const groups = useMemo(() => {
    const m: Record<string, string> = {}
    list.forEach((t) => {
      if (!m[t.group]) m[t.group] = t.group
    })
    return Object.keys(m)
  }, [list])

  const GROUP_NAME: Record<string, string> = {
    basic: '基本概念',
    metric: '指标与统计',
    factor: '因子与模型',
    design: '设计与验证',
    wear: '磨损与寿命',
  }

  const rows = useMemo(() => {
    let r = list
    if (group !== 'all') r = r.filter((t) => t.group === group)
    if (kw.trim()) {
      const q = kw.trim().toLowerCase()
      r = r.filter((t) =>
        [t.term, t.abbr, t.definition, t.plain, t.example, t.misuse]
          .filter(Boolean)
          .join(' ')
          .toLowerCase()
          .includes(q),
      )
    }
    return r
  }, [list, group, kw])

  return (
    <div>
      <Card
        size="small"
        variant="borderless"
        style={{ marginBottom: 12, border: '1px solid #EEE' }}
        title={
          <Space>
            <BookOutlined />
            <span>可靠性工程术语表</span>
            <Tag>{list.length} 条</Tag>
          </Space>
        }
        extra={
          <Space wrap>
            <Tag
              color={group === 'all' ? 'blue' : undefined}
              style={{ cursor: 'pointer' }}
              onClick={() => setGroup('all')}
            >
              全部
            </Tag>
            {groups.map((g) => (
              <Tag
                key={g}
                color={group === g ? GROUP_COLOR[g] || 'blue' : undefined}
                style={{ cursor: 'pointer' }}
                onClick={() => setGroup(g)}
              >
                {GROUP_NAME[g] || g}
              </Tag>
            ))}
            <Input
              allowClear
              size="small"
              prefix={<SearchOutlined />}
              placeholder="搜术语 / 解释"
              style={{ width: 170 }}
              onChange={(e) => setKw(e.target.value)}
            />
          </Space>
        }
      >
        <Alert
          type="info"
          showIcon
          icon={<BulbOutlined />}
          style={{ fontSize: 12.5 }}
          message="三条最容易踩的坑（先看这个，再看下面）"
          description={
            <ol style={{ paddingLeft: 18, margin: '4px 0 0', lineHeight: 1.9 }}>
              <li>
                <b>MTBF 不是寿命。</b>MTBF = 40 万小时不等于"能用 45 年"。它只描述随机失效的平均间隔，
                不含电解电容干涸、风扇轴承磨损这类耗损机理。
              </li>
              <li>
                <b>FIT 不是百分比。</b>1000 FIT = 每 10⁹ 小时 1000 次失效 = MTBF 100 万小时。
                把 FIT 当"0.1% 失效率"会差好几个数量级。
              </li>
              <li>
                <b>预计是数量级参考。</b>没有实测校准时，预计结果与实际可能差 2~5 倍。
                它的用途是"比较方案、找短板"，不是"承诺寿命"。
              </li>
            </ol>
          }
        />
      </Card>

      {loading && !list.length ? (
        <Empty description="加载中…" />
      ) : !rows.length ? (
        <Empty description="没有匹配的术语" />
      ) : (
        <Row gutter={[12, 12]}>
          {rows.map((t) => (
            <Col xs={24} lg={12} xxl={8} key={t.key}>
              <Card
                size="small"
                variant="borderless"
                style={{
                  border: '1px solid #EEE',
                  borderLeft: `3px solid ${
                    t.group === 'wear' ? '#E8684A' : t.group === 'metric' ? '#1B7F3B' : '#3A6EA5'
                  }`,
                  height: '100%',
                }}
                title={
                  <Space wrap size={6}>
                    <span style={{ fontSize: 13.5, fontWeight: 600 }}>{t.term}</span>
                    {t.abbr && t.abbr !== t.term && (
                      <code style={{ fontSize: 11.5, color: '#3A6EA5' }}>{t.abbr}</code>
                    )}
                    <Tag color={GROUP_COLOR[t.group] || 'default'} style={{ fontSize: 10.5 }}>
                      {GROUP_NAME[t.group] || t.group}
                    </Tag>
                  </Space>
                }
              >
                <Typography.Paragraph style={{ fontSize: 12.5, marginBottom: 8 }}>
                  {t.definition}
                </Typography.Paragraph>
                <div
                  style={{
                    fontSize: 12.5,
                    background: '#F7F9FC',
                    borderRadius: 6,
                    padding: '8px 10px',
                    marginBottom: 8,
                    lineHeight: 1.75,
                  }}
                >
                  <b style={{ color: '#3A6EA5' }}>说人话：</b>
                  {t.plain}
                </div>
                {t.example && (
                  <div style={{ fontSize: 12, marginBottom: 6, lineHeight: 1.75 }}>
                    <b>例子：</b>
                    <span className="muted">{t.example}</span>
                  </div>
                )}
                {t.misuse && (
                  <div style={{ fontSize: 12, color: '#D46B08', lineHeight: 1.75 }}>
                    <WarningOutlined style={{ marginRight: 4 }} />
                    <b>常见误用：</b>
                    {t.misuse}
                  </div>
                )}
              </Card>
            </Col>
          ))}
        </Row>
      )}
    </div>
  )
}
