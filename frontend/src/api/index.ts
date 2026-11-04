/**
 * api/index.ts — 接口函数清单
 *
 * 【为什么不手写一整套 TS interface】
 * 后端已经用 Pydantic 定义了请求体，并由 OpenAPI 暴露。
 * 这里的类型只覆盖"页面真正会读的字段"，其余用 Record<string, any> 兜住。
 * 好处是接口新增字段时前端不需要同步改类型；代价是失去部分编译期检查——
 * 对这个规模的项目，收益大于代价（真正需要严格类型的场景是 SDK，不是内部应用）。
 */

import { api, download } from './client'

// 把 client 的会话/错误类型统一从这里再导出：页面只需要 import 一处，
// 不用记"哪个函数在 client、哪个在 index"。
export * from './client'

// ---------- 认证 ----------
export const login = (username: string, password: string) =>
  api<{ access_token: string; user: any }>('/auth/login', { method: 'POST', body: { username, password } })

export const me = () => api<any>('/auth/me')

// ---------- 项目 ----------
export const listProjects = () => api<any[]>('/projects')
export const createProject = (body: any) => api<any>('/projects', { method: 'POST', body })
export const getProject = (id: number) => api<any>(`/projects/${id}`)
export const updateProject = (id: number, body: any) => api<any>(`/projects/${id}`, { method: 'PATCH', body })
export const deleteProject = (id: number) => api<void>(`/projects/${id}`, { method: 'DELETE' })
export const projectTimeline = (id: number) => api<any>(`/projects/${id}/timeline`)

// ---------- BOM ----------
export const bomTemplate = () => download('/bom/template.xlsx', 'BOM模板.xlsx')
export const getVersion = (vid: number) => api<any>(`/bom/versions/${vid}`)
export const listItems = (vid: number, params: Record<string, any> = {}) => {
  const qs = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') qs.append(k, String(v))
  })
  return api<any>(`/bom/versions/${vid}/items?${qs.toString()}`)
}
export const getItem = (id: number) => api<any>(`/bom/items/${id}`)
export const updateItem = (id: number, body: any) => api<any>(`/bom/items/${id}`, { method: 'PATCH', body })

export const uploadBom = async (pid: number, file: File, label = '上传 BOM') => {
  const fd = new FormData()
  fd.append('file', file)
  return api<any>(`/projects/${pid}/bom/upload?label=${encodeURIComponent(label)}`, {
    method: 'POST',
    body: fd,
  })
}

export const simulateBom = (pid: number, body: any) =>
  api<any>(`/projects/${pid}/bom/simulate`, { method: 'POST', body })

// ---------- 分类 ----------
export const runClassify = (vid: number, onlyUnclassified = false) =>
  api<any>(`/bom/versions/${vid}/classify?only_unclassified=${onlyUnclassified}`, { method: 'POST' })
export const classifyQueue = (vid: number, params: Record<string, any> = {}) => {
  const qs = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') qs.append(k, String(v))
  })
  return api<any>(`/bom/versions/${vid}/queue?${qs.toString()}`)
}
export const classifyStats = (vid: number) => api<any>(`/bom/versions/${vid}/stats`)
export const confirmItem = (id: number, body: any) =>
  api<any>(`/bom/items/${id}/confirm`, { method: 'POST', body })
export const confirmBatch = (vid: number, body: any) =>
  api<any>(`/bom/versions/${vid}/confirm-batch`, { method: 'POST', body })
export const classifyFeedback = () => api<any>('/classify/feedback')

// ---------- 知识库 ----------
export const listCategories = () => api<any>('/categories')
export const getCategory = (code: string) => api<any>(`/categories/${code}`)
export const createCategory = (body: any) => api<any>('/categories', { method: 'POST', body })
export const updateCategory = (code: string, body: any) =>
  api<any>(`/categories/${code}`, { method: 'PATCH', body })
export const addKeyword = (code: string, body: any) =>
  api<any>(`/categories/${code}/keywords`, { method: 'POST', body })
export const updateKeyword = (id: number, body: any) =>
  api<any>(`/keywords/${id}`, { method: 'PATCH', body })
export const deleteKeyword = (id: number) => api<void>(`/keywords/${id}`, { method: 'DELETE' })

// ---------- 评估 ----------
export const runAssess = (pid: number, body: any) =>
  api<any>(`/projects/${pid}/assess`, { method: 'POST', body })
export const getAssessment = (aid: number) => api<any>(`/assessments/${aid}`)
export const listAssessments = (projectId?: number) =>
  api<any[]>(`/assessments${projectId ? `?project_id=${projectId}` : ''}`)
export const listAssessmentItems = (aid: number, page = 1, pageSize = 50) =>
  api<any>(`/assessments/${aid}/items?page=${page}&page_size=${pageSize}`)
export const getTrace = (aid: number, itemId: number) => api<any>(`/assessments/${aid}/trace/${itemId}`)
export const getWear = (aid: number) => api<any>(`/assessments/${aid}/wear`)
export const getDerating = (aid: number) => api<any>(`/assessments/${aid}/derating`)
export const runSensitivity = (aid: number, body: any) =>
  api<any>(`/assessments/${aid}/sensitivity`, { method: 'POST', body })
export const compareStandards = (aid: number) => api<any>(`/assessments/${aid}/compare-standards`)
export const compareAssessments = (a: number, b: number) => api<any>(`/assessments/compare?ids=${a},${b}`)

// ---------- 报告 ----------
export const createReport = (aid: number, kind: 'pdf' | 'xlsx') =>
  api<any>(`/assessments/${aid}/report`, { method: 'POST', body: { kind } })
export const listReports = (projectId?: number) =>
  api<any[]>(`/reports${projectId ? `?project_id=${projectId}` : ''}`)
export const downloadReport = (id: number, filename: string) =>
  download(`/reports/${id}/download`, filename)

// ---------- 系统 ----------
export const getGlossary = () => api<any>('/glossary')
export const listParamVersions = () => api<any[]>('/param-versions')
export const getParamSet = (standard: string) => api<any>(`/params/${standard}`)
export const getDashboard = () => api<any>('/dashboard')
export const listLogs = (limit = 100) => api<any[]>(`/logs?limit=${limit}`)
