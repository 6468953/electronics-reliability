/**
 * App.tsx — 路由与整体布局
 *
 * 【页面结构】
 *   /login          登录
 *   /               首页（总览 + 项目列表 + 新建项目）
 *   /projects/:id   项目工作台（BOM → 分类 → 假设 → 结果 → 磨损 → 降额 → 敏感性 → 报告）
 *   /knowledge      分类知识库维护
 *   /glossary       术语表
 *   /params         参数库（标准来源、环境/质量档位、各类别基础失效率）
 *
 * 【为什么把 8 个模块收进一个"工作台 + Tab"】
 * 这些步骤是严格串行的（没分类就没法评估，没评估就没报告）。做成 8 个独立路由，
 * 用户每次都要回到列表点下一步；做成 Tab，则上下文（当前 BOM 版本、当前评估）天然连续。
 * 路由仍然是 /projects/:id，刷新后可恢复。
 */

import { useEffect, useState } from 'react'
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { Avatar, Button, Dropdown, Layout, Menu, Tag, Typography, message } from 'antd'
import {
  ApartmentOutlined,
  BookOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  LogoutOutlined,
  HomeOutlined,
  UserOutlined,
} from '@ant-design/icons'

import { clearSession, getStoredUser, getToken, me } from './api'
import { GlossaryProvider } from './components/Term'
import BackendStatus from './components/BackendStatus'
import Login from './pages/Login'
import Home from './pages/Home'
import Workspace from './pages/Workspace'
import Knowledge from './pages/Knowledge'
import Glossary from './pages/Glossary'
import Params from './pages/Params'

const { Header, Sider, Content } = Layout

function Shell({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState(getStoredUser())
  const nav = useNavigate()
  const loc = useLocation()

  useEffect(() => {
    // 用后端校验一次身份：本地存的只是"上次登录的人"，令牌过期后必须回到登录页
    if (!getToken()) return
    me()
      .then((u) => setUser({ ...u, display_name: u.display_name || u.username }))
      .catch(() => {})
  }, [])

  const selected = loc.pathname.startsWith('/knowledge')
    ? 'knowledge'
    : loc.pathname.startsWith('/glossary')
      ? 'glossary'
      : loc.pathname.startsWith('/params')
        ? 'params'
        : loc.pathname.startsWith('/projects')
          ? 'projects'
          : 'home'

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider theme="light" width={208} style={{ borderRight: '1px solid #e8edf5' }}>
        <div style={{ padding: '18px 16px 10px' }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#1F3864', lineHeight: 1.35 }}>
            电子零件可靠性
            <br />
            评估系统
          </div>
          <div style={{ fontSize: 11, color: '#8c8c8c', marginTop: 4 }}>MIL-217F · SR-332 · 示例数据</div>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[selected]}
          style={{ borderInlineEnd: 'none' }}
          onClick={(e) => {
            const map: Record<string, string> = {
              home: '/',
              knowledge: '/knowledge',
              glossary: '/glossary',
              params: '/params',
            }
            if (e.key === 'projects') nav('/')
            else nav(map[e.key] || '/')
          }}
          items={[
            { key: 'home', icon: <HomeOutlined />, label: '总览与项目' },
            { key: 'knowledge', icon: <ApartmentOutlined />, label: '分类知识库' },
            { key: 'glossary', icon: <BookOutlined />, label: '术语表' },
            { key: 'params', icon: <DatabaseOutlined />, label: '参数库与来源' },
          ]}
        />
        <div style={{ position: 'absolute', bottom: 12, left: 0, width: '100%', padding: '0 16px' }}>
          <Typography.Text type="secondary" style={{ fontSize: 11, lineHeight: 1.5 }}>
            参数为公开标准示例值，
            <br />
            仅供演示/学习，不作认证依据。
          </Typography.Text>
        </div>
      </Sider>

      <Layout>
        <Header
          style={{
            background: '#fff',
            borderBottom: '1px solid #e8edf5',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            paddingInline: 20,
            height: 56,
          }}
        >
          <Link to="/" style={{ color: '#1F3864', fontWeight: 600 }}>
            <ExperimentOutlined style={{ marginRight: 6 }} />
            可靠性评估工作台
          </Link>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <Tag color={user?.role === 'admin' ? 'geekblue' : 'default'}>
              {user?.role === 'admin' ? '管理员' : '工程师'}
            </Tag>
            <Dropdown
              menu={{
                items: [{ key: 'logout', icon: <LogoutOutlined />, label: '退出登录' }],
                onClick: () => {
                  clearSession()
                  message.success('已退出')
                  nav('/login')
                },
              }}
            >
              <span style={{ cursor: 'pointer' }}>
                <Avatar size={26} icon={<UserOutlined />} style={{ marginRight: 6 }} />
                {user?.display_name || user?.username || '未登录'}
              </span>
            </Dropdown>
          </div>
        </Header>
        <Content style={{ padding: 20, background: '#f5f7fb' }}>{children}</Content>
      </Layout>
    </Layout>
  )
}

function Guard({ children }: { children: React.ReactNode }) {
  if (!getToken()) return <Navigate to="/login" replace />
  return <Shell>{children}</Shell>
}

export default function App() {
  return (
    <BrowserRouter>
      <GlossaryProvider>
        {/* 连接状态横幅放在路由之外：登录页同样可能出现"服务已断开"，那一页更需要提示 */}
        <BackendStatus />
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route
            path="/"
            element={
              <Guard>
                <Home />
              </Guard>
            }
          />
          <Route
            path="/projects/:id"
            element={
              <Guard>
                <Workspace />
              </Guard>
            }
          />
          <Route
            path="/knowledge"
            element={
              <Guard>
                <Knowledge />
              </Guard>
            }
          />
          <Route
            path="/glossary"
            element={
              <Guard>
                <Glossary />
              </Guard>
            }
          />
          <Route
            path="/params"
            element={
              <Guard>
                <Params />
              </Guard>
            }
          />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </GlossaryProvider>
    </BrowserRouter>
  )
}
