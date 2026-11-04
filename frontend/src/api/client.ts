/**
 * api/client.ts — 与后端通信的唯一出口
 *
 * 【为什么所有请求都走这里】
 * 1. 令牌注入、401 处理、错误消息提取只写一次，页面里不需要重复；
 * 2. 后端返回的错误统一是 {detail: string}，这里把它转成人类可读的 Error，
 *    页面只要 try/catch + message.error(e.message) 就够了。
 *
 * 【错误处理原则】
 * 后端的 400/403 消息是写给用户看的（例如"还有 7 行未完成分类"），必须原样展示；
 * 500 则由后端兜底处理器返回"服务器内部错误：XxxError"，不应把堆栈暴露给用户。
 */

const TOKEN_KEY = 'relsys_token'
const USER_KEY = 'relsys_user'
const BASE = '/api/v1'

export interface AuthUser {
  id: number
  username: string
  display_name: string
  role: 'admin' | 'engineer'
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function getStoredUser(): AuthUser | null {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as AuthUser
  } catch {
    return null
  }
}

export function setSession(token: string, user: AuthUser) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

/** 网络层失败（请求根本没到后端）统一用这个状态码，便于调用方区分“业务错误”与“连不上”。 */
export const NETWORK_ERROR = 0

/**
 * 把浏览器原生的 "Failed to fetch" 翻译成人能照着做的说明。
 *
 * 【为什么必须包这一层】
 * fetch 只在“请求根本没发出去”时抛异常，浏览器给的文案永远是同一句英文
 * "Failed to fetch"，不告诉你原因。实际能踩到的只有四种，而它们对使用者的
 * 处置动作完全不同：
 *   1. 后端进程没了（最常见）：start.bat 的黑窗口被关掉、或电脑重启过。
 *      浏览器标签还开着，页面能点，但点任何按钮都失败。
 *   2. 页面是用 file:// 直接双击 index.html 打开的，同源策略下请求发不出去。
 *   3. 端口不对：服务顺延到了 8001，而地址栏还停留在 8000。
 *   4. 断网/安全软件拦截。
 * 把这四种可能写进错误消息，用户对着看一遍就能自己解决，不必来找我。
 */
function networkError(): ApiError {
  const viaFile = location.protocol === 'file:'
  // 这里是 toast，一行就能读完的量级；详细的三种排查步骤交给页面顶部的
  // 连接状态横幅（components/BackendStatus.tsx），那里空间够、而且常驻。
  const msg = viaFile
    ? '页面是以文件方式打开的，无法访问后端。请改为双击 start.bat 启动。'
    : `连不上后端服务（${location.origin}）。启动窗口（start.bat）可能已被关闭，重新启动后再试。`
  return new ApiError(msg, NETWORK_ERROR)
}

/** 所有请求的唯一出口。网络层异常在这里统一转成中文 ApiError。 */
async function send(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(input, init)
  } catch {
    throw networkError()
  }
}

type Init = Omit<RequestInit, 'body'> & { body?: unknown }

export async function api<T = any>(path: string, init: Init = {}): Promise<T> {
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string> | undefined),
  }
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`

  let body = init.body as BodyInit | undefined
  if (body !== undefined && !(body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(body)
  }

  const res = await send(`${BASE}${path}`, { ...init, headers, body })

  if (res.status === 401) {
    clearSession()
    if (!location.pathname.startsWith('/login')) location.href = '/login'
    throw new ApiError('登录已过期，请重新登录', 401)
  }

  if (!res.ok) {
    let msg = `请求失败（${res.status}）`
    try {
      const data = await res.json()
      if (typeof data?.detail === 'string') msg = data.detail
      else if (Array.isArray(data?.detail)) msg = data.detail.map((d: any) => d.msg).join('；')
    } catch {
      /* 非 JSON 响应，用默认消息 */
    }
    throw new ApiError(msg, res.status)
  }

  if (res.status === 204) return undefined as T
  const ct = res.headers.get('content-type') || ''
  if (ct.includes('application/json')) return (await res.json()) as T
  return (await res.blob()) as unknown as T
}

/** 下载类接口：拿 blob 后触发浏览器保存。 */
export async function download(path: string, filename: string) {
  const token = getToken()
  const res = await send(`${BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!res.ok) {
    let msg = '下载失败'
    try {
      msg = (await res.json())?.detail || msg
    } catch {
      /* ignore */
    }
    throw new ApiError(msg, res.status)
  }
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
