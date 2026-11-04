/**
 * components/Chart.tsx — ECharts 轻封装
 *
 * 【为什么不用 echarts-for-react】
 * 那个包对 React 18 的 StrictMode 双挂载处理不干净，会出现图表重复初始化/空白。
 * 直接用 echarts 的 init + setOption + resize 监听，代码不到 60 行，行为可预期。
 *
 * 【主题与中文】
 * 图表颜色统一走这里，避免每个页面各调一套色；坐标轴文字用默认字体（浏览器有中文字体）。
 */

import { useEffect, useRef } from 'react'
import * as echarts from 'echarts'

export const CHART_COLORS = [
  '#3A6EA5', '#5B8FF9', '#61DDAA', '#F6BD16', '#F6903D', '#E8684A', '#9270CA', '#6DC8EC',
]

interface Props {
  option: echarts.EChartsOption
  height?: number | string
  onEvents?: Record<string, (params: any) => void>
}

export default function Chart({ option, height = 320, onEvents }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!ref.current) return
    const chart = echarts.init(ref.current)
    chartRef.current = chart
    const onResize = () => chart.resize()
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chart.dispose()
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    chart.setOption({ color: CHART_COLORS, ...option }, true)
    // 容器尺寸变化（比如切 Tab）后需要手动 resize，否则图表会挤在左上角
    const t = window.setTimeout(() => chart.resize(), 60)
    return () => window.clearTimeout(t)
  }, [option])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart || !onEvents) return
    Object.entries(onEvents).forEach(([evt, handler]) => chart.on(evt, handler))
    return () => {
      Object.keys(onEvents).forEach((evt) => chart.off(evt))
    }
  }, [onEvents])

  return <div ref={ref} style={{ width: '100%', height }} />
}
