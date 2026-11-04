/**
 * scripts/smoke.mjs — 端到端冒烟脚本（开发期用，不参与构建）
 *
 * 目的：用真实浏览器把关键页面走一遍，抓 React 运行时错误与控制台报错。
 * 类型检查与构建能发现"写错了"，但发现不了"渲染时炸了"（例如图表 option 非法、
 * 某个字段 undefined 导致 .map 报错、antd 属性组合冲突）。
 *
 * 用法（需先启动后端 8000 与前端 5173）：
 *   node scripts/smoke.mjs
 * 依赖：playwright-core + 本机已安装的 Chrome/Edge（不额外下载浏览器）。
 */

import { chromium } from 'playwright-core'
import fs from 'node:fs'

const BASE = process.env.BASE || 'http://127.0.0.1:5173'
const OUT = 'shots'
fs.mkdirSync(OUT, { recursive: true })

const errors = []

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })

page.on('console', (m) => {
  if (m.type() === 'error') errors.push(`[console] ${m.text().slice(0, 300)}`)
})
page.on('pageerror', (e) => errors.push(`[pageerror] ${String(e).slice(0, 300)}`))

const shot = async (name) => {
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true })
  console.log('shot:', name)
}

// ---- 登录 ----
await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
await shot('01-login')
await page.fill('input#username, input[placeholder="admin"]', 'admin')
await page.fill('input[type="password"]', 'admin123')
await page.click('button[type="submit"]')
await page.waitForURL(`${BASE}/`, { timeout: 15000 })
await page.waitForTimeout(1200)
await shot('02-home')

// ---- 工作台 ----
await page.click('text=演示项目 · 智能网关 GW-200')
await page.waitForURL(/\/projects\/\d+/, { timeout: 15000 })
await page.waitForTimeout(1500)
await shot('03-workspace-bom')

const tabs = ['② 分类确认', '③ 假设与评估', '④ 预计结果', '⑤ 磨损寿命', '⑥ 降额检查', '⑦ 敏感性', '⑧ 报告']
for (const t of tabs) {
  const tab = page.locator(`.ant-tabs-tab:has-text("${t}")`).first()
  if (!(await tab.count())) {
    errors.push(`[tab] 找不到 Tab: ${t}`)
    continue
  }
  await tab.click()
  await page.waitForTimeout(1600)
  await shot(`04-${t.replace(/[^\u4e00-\u9fa5A-Za-z0-9]/g, '')}`)
}

// ---- 独立页面 ----
for (const [path, name] of [['/knowledge', '05-knowledge'], ['/glossary', '06-glossary'], ['/params', '07-params']]) {
  await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1200)
  await shot(name)
}

await browser.close()

console.log('\n=== console / page errors ===')
if (!errors.length) console.log('(none)')
else errors.forEach((e) => console.log(e))
process.exit(errors.length ? 1 : 0)
