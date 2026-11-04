/**
 * pages/Login.tsx — 登录页
 *
 * 【设计考虑】
 * 这是内部工具，**不提供注册**：账号由管理员开设。所以页面上直接给出演示账号，
 * 让人打开就能用——这比让人先去找文档要高效得多。
 * 生产部署时把提示去掉（或用环境变量控制）即可。
 */

import { useState } from 'react'
import { Button, Card, Form, Input, Typography, Alert, message } from 'antd'
import { LockOutlined, UserOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { login, setSession } from '../api'

export default function Login() {
  const [loading, setLoading] = useState(false)
  const nav = useNavigate()

  const onFinish = async (v: { username: string; password: string }) => {
    setLoading(true)
    try {
      const res = await login(v.username, v.password)
      setSession(res.access_token, res.user)
      message.success(`欢迎，${res.user.display_name || res.user.username}`)
      nav('/')
    } catch (e: any) {
      message.error(e.message || '登录失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg,#eef3fb 0%,#f7f9fc 55%,#eaf1f8 100%)',
      }}
    >
      <Card variant="borderless" style={{ width: 400, boxShadow: '0 8px 30px rgba(31,56,100,.10)' }}>
        <div style={{ textAlign: 'center', marginBottom: 20 }}>
          <div style={{ fontSize: 20, fontWeight: 700, color: '#1F3864' }}>电子零件可靠性评估系统</div>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            BOM 导入 · 自动分类 · 预计与磨损 · 降额 · 报告
          </Typography.Text>
        </div>

        <Form layout="vertical" onFinish={onFinish} initialValues={{ username: 'admin', password: 'admin123' }}>
          <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="admin" autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="admin123" autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={loading} size="large">
            登录
          </Button>
        </Form>

        <Alert
          style={{ marginTop: 16 }}
          type="info"
          showIcon
          message="演示账号"
          description={
            <div style={{ fontSize: 12, lineHeight: 1.8 }}>
              管理员：<b>admin / admin123</b>（可维护知识库、查看日志）
              <br />
              工程师：<b>engineer / engineer123</b>（只能看自己的项目）
            </div>
          }
        />
      </Card>
    </div>
  )
}
