/**
 * BackendStatus.tsx — 后端连接状态灯
 *
 * 【解决的问题】
 * 这个系统是"一个本地进程 + 一个浏览器页面"。使用者最常见的困惑不是功能不会用，
 * 而是：页面还开着，但那个黑色启动窗口被关掉了（或者电脑睡眠后进程没了），
 * 于是点任何按钮都只弹一句英文 "Failed to fetch" —— 看不出是什么坏了。
 *
 * 【做法】
 * 定时 ping 一次 /api/health。断开时在页面最顶部挂一条红色横幅，直接写清
 * "服务已断开 + 怎么恢复"；恢复后自动消失并提示一次。
 *
 * 【为什么用 15 秒而不是更短】
 * 本地服务的健康检查开销很小，但没必要更频繁：真断开时用户通常是在"点了一下
 * 没反应"之后才会注意到，15 秒足够在下次点击前把提示挂出来；
 * 同时点任何一个按钮都会立刻触发真实请求，错误消息本身也会提示原因，两者互补。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, Button, Tooltip } from 'antd'
import { ApiOutlined, ReloadOutlined } from '@ant-design/icons'

const HEALTH_URL = '/api/health'
const INTERVAL_MS = 15000

export default function BackendStatus() {
  const [down, setDown] = useState(false)
  const [checking, setChecking] = useState(false)
  // 记录"上一次是否断开"，用于判断该不该弹"已恢复"的提示，避免每次轮询都提示
  const wasDown = useRef(false)

  const check = useCallback(async () => {
    setChecking(true)
    try {
      const r = await fetch(HEALTH_URL, { cache: 'no-store' })
      setDown(!r.ok)
      if (r.ok && wasDown.current) wasDown.current = false
      if (!r.ok) wasDown.current = true
      return r.ok
    } catch {
      setDown(true)
      wasDown.current = true
      return false
    } finally {
      setChecking(false)
    }
  }, [])

  useEffect(() => {
    check()
    const timer = window.setInterval(check, INTERVAL_MS)
    // 切回标签页时立刻复查一次：用户很可能刚在另一个窗口里把服务重新启动了
    const onVisible = () => {
      if (document.visibilityState === 'visible') check()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [check])

  if (!down) return null

  const viaFile = location.protocol === 'file:'

  return (
    <div style={{ position: 'sticky', top: 0, zIndex: 1200 }}>
      <Alert
        type="error"
        showIcon
        icon={<ApiOutlined />}
        banner
        /* 文案刻意压到一句半：这是要在一行里和右侧按钮共存的横幅，
           写成长段落会换行三四行、把按钮挤没（实测过）。细节放进 Tooltip。 */
        message={
          <span style={{ fontSize: 13 }}>
            <b>与后端服务的连接已断开</b>
            <span style={{ marginLeft: 8, color: '#a8071a' }}>
              {viaFile
                ? '页面是以 file:// 打开的，无法访问后端。请改为双击 start.bat 启动。'
                : '启动服务的黑色窗口可能被关掉了。双击 start.bat 重新启动，再点右侧“重新检测”。'}
            </span>
          </span>
        }
        action={
          <Tooltip
            title={
              <span style={{ fontSize: 12 }}>
                当前地址：{location.origin}
                <br />
                ① 确认显示 “Uvicorn running on...” 的黑窗口还开着 —— 关掉窗口就等于关掉服务；
                <br />
                ② 地址栏端口要与窗口里显示的一致（8000 被占用时脚本会顺延到 8001~8010）；
                <br />
                ③ 服务恢复前，页面展示的是上一次加载的数据，任何保存/计算都会失败。
              </span>
            }
          >
            <Button size="small" icon={<ReloadOutlined />} loading={checking} onClick={check}>
              重新检测
            </Button>
          </Tooltip>
        }
      />
    </div>
  )
}
