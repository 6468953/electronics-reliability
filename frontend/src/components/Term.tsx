/**
 * components/Term.tsx — 全站术语 Hover 提示
 *
 * 【为什么要做成组件而不是各页面自己写 Tooltip】
 * 需求要求"所有专业指标悬停即弹出通俗解释"。如果每页各写一份文案，
 * 三个月后必然出现同一术语在不同页面解释不一致的情况。
 * 这里从后端 /glossary 拉一次、全站共用，改文案只改 JSON。
 *
 * 用法：<Term k="mtbf">MTBF</Term>
 * 若 glossary 里没有该 key，组件降级为普通文本（不会崩、也不会显示空气泡）。
 */

import { createContext, ReactNode, useContext, useEffect, useMemo, useState } from 'react'
import { Tooltip } from 'antd'
import { QuestionCircleOutlined } from '@ant-design/icons'
import { getGlossary, getToken } from '../api'

export interface GlossaryTerm {
  key: string
  term: string
  abbr: string
  group: string
  definition: string
  plain: string
  example: string
  misuse: string
}

interface Ctx {
  terms: Record<string, GlossaryTerm>
  list: GlossaryTerm[]
  loading: boolean
}

const GlossaryCtx = createContext<Ctx>({ terms: {}, list: [], loading: true })

export function GlossaryProvider({ children }: { children: ReactNode }) {
  const [list, setList] = useState<GlossaryTerm[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // 未登录时不要拉术语表：否则登录页会先打两个 401，控制台一片红，
    // 真实问题（比如接口 500）就被淹没了。
    if (!getToken()) {
      setLoading(false)
      return
    }
    getGlossary()
      .then((d) => setList(d.terms || []))
      .catch(() => setList([]))
      .finally(() => setLoading(false))
  }, [])

  const terms = useMemo(() => {
    const map: Record<string, GlossaryTerm> = {}
    list.forEach((t) => {
      map[t.key] = t
    })
    return map
  }, [list])

  return <GlossaryCtx.Provider value={{ terms, list, loading }}>{children}</GlossaryCtx.Provider>
}

export function useGlossary() {
  return useContext(GlossaryCtx)
}

const overlayStyle: React.CSSProperties = { maxWidth: 360, fontSize: 12.5, lineHeight: 1.65 }

function Bubble({ t }: { t: GlossaryTerm }) {
  return (
    <div style={overlayStyle}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>
        {t.term}
        {t.abbr && t.abbr !== t.term ? `（${t.abbr}）` : ''}
      </div>
      <div style={{ opacity: 0.92 }}>{t.plain}</div>
      {t.example && (
        <div style={{ marginTop: 6, paddingTop: 6, borderTop: '1px dashed rgba(140,140,140,.45)' }}>
          <b>例子：</b>
          {t.example}
        </div>
      )}
      {t.misuse && (
        <div style={{ marginTop: 4, color: '#d46b08' }}>
          <b>常见误用：</b>
          {t.misuse}
        </div>
      )}
    </div>
  )
}

export function Term({ k, children }: { k: string; children?: ReactNode }) {
  const { terms } = useGlossary()
  const t = terms[k]
  const label = children ?? t?.term ?? k
  if (!t) return <span>{label}</span>
  return (
    <Tooltip title={<Bubble t={t} />} placement="top" color="#fff" styles={{ root: {} }}>
      <span
        style={{
          borderBottom: '1px dotted #8c8c8c',
          cursor: 'help',
          whiteSpace: 'nowrap',
        }}
      >
        {label}
      </span>
    </Tooltip>
  )
}

/** 带问号图标的术语，用于表单 label / 指标卡标题这类不方便加下划线的地方。 */
export function TermIcon({ k }: { k: string }) {
  const { terms } = useGlossary()
  const t = terms[k]
  if (!t) return null
  return (
    <Tooltip title={<Bubble t={t} />} placement="top" color="#fff">
      <QuestionCircleOutlined style={{ color: '#8c8c8c', marginLeft: 4, cursor: 'help' }} />
    </Tooltip>
  )
}
