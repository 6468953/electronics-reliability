/**
 * main.tsx — 应用入口
 *
 * ConfigProvider 里统一设置中文语言包与主题色，避免每个组件单独调样式。
 */
import React from 'react'
import ReactDOM from 'react-dom/client'
import { ConfigProvider, App as AntApp } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import 'antd/dist/reset.css'
import 'dayjs/locale/zh-cn'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#3A6EA5',
          borderRadius: 6,
          fontSize: 13.5,
          fontFamily:
            "-apple-system, 'Segoe UI', 'Microsoft YaHei', 'PingFang SC', 'Hiragino Sans GB', sans-serif",
        },
        components: {
          Layout: { bodyBg: '#f5f7fb', headerBg: '#fff' },
          Card: { boxShadowTertiary: '0 1px 2px rgba(16,24,40,.05)' },
        },
      }}
    >
      <AntApp>
        <App />
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>,
)
