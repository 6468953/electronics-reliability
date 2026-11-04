/**
 * scripts/flow.mjs — 完整流程冒烟（含确认队列 → 评估 → 结果 → 报告）
 *
 * 与 smoke.mjs 的区别：smoke 只逛页面（会遇到"还没有评估记录"的空状态），
 * 这个脚本会把 7 行待确认逐条确认掉、跑一次评估，然后逐页截图。
 * 目的是让"图表 + 表格 + 追溯抽屉"这些重页面真的被渲染一次。
 *
 * 用法（需先启动后端 8000 与前端 5173）：
 *   node scripts/flow.mjs
 */

import { chromium } from 'playwright-core'
import fs from 'node:fs'

const BASE = process.env.BASE || 'http://127.0.0.1:5173'
const OUT = 'shots'
fs.mkdirSync(OUT, { recursive: true })

const errors = []
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } })
page.on('console', (m) => {
  if (m.type() === 'error') errors.push(`[console] ${m.text().slice(0, 300)}`)
})
page.on('pageerror', (e) => errors.push(`[pageerror] ${String(e).slice(0, 400)}`))

const shot = async (name) => {
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true })
  console.log('shot:', name)
}

// ---- 登录 ----
await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
await page.fill('input#username, input[placeholder="admin"]', 'admin')
await page.fill('input[type="password"]', 'admin123')
await page.click('button[type="submit"]')
await page.waitForURL(`${BASE}/`, { timeout: 15000 })
await page.click('text=演示项目 · 智能网关 GW-200')
await page.waitForURL(/\/projects\/\d+/, { timeout: 15000 })
await page.waitForTimeout(1200)

// ---- ② 分类确认：逐条确认待确认行 ----
await page.locator('.ant-tabs-tab:has-text("② 分类确认")').first().click()
await page.waitForTimeout(1500)
await shot('10-classify-queue')

for (let i = 0; i < 12; i++) {
  const btn = page.locator('.ant-tabs-tabpane-active .ant-table-tbody button:has-text("确认")').first()
  if (!(await btn.count())) break
  const disabled = await btn.isDisabled().catch(() => false)
  if (disabled) break
  await btn.click()
  await page.waitForTimeout(500)
  const ok = page.locator('.ant-modal-footer button:has-text("确认归类")').first()
  if (await ok.count()) {
    await ok.click()
    await page.waitForTimeout(1200)
  } else {
    break
  }
}
await shot('11-classify-after')

// ---- ③ 假设与评估 ----
await page.locator('.ant-tabs-tab:has-text("③ 假设与评估")').first().click()
await page.waitForTimeout(1500)
await shot('12-assess-form')
await page.locator('.ant-tabs-tabpane-active button:has-text("开始评估")').first().click()
await page.waitForTimeout(4000)
await shot('13-result')

// ---- ④ 追溯抽屉 ----
const row = page.locator('.ant-tabs-tabpane-active .ant-table-tbody tr.ant-table-row').first()
if (await row.count()) {
  await row.click()
  await page.waitForTimeout(1500)
  await shot('14-trace-drawer')
  await page.keyboard.press('Escape')
  await page.waitForTimeout(600)
}

// ---- 双标准对比 ----
const cmp = page.locator('.ant-tabs-tabpane-active button:has-text("计算另一套标准")').first()
if (await cmp.count()) {
  await cmp.click()
  await page.waitForTimeout(2500)
  await shot('15-standards-compare')
}

// ---- 其余 Tab ----
for (const t of ['⑤ 磨损寿命', '⑥ 降额检查', '⑦ 敏感性', '⑧ 报告']) {
  await page.locator(`.ant-tabs-tab:has-text("${t}")`).first().click()
  await page.waitForTimeout(2200)
  await shot(`16-${t.replace(/[^\u4e00-\u9fa5A-Za-z0-9]/g, '')}`)
}

// ---- 生成一份 PDF（顺带验证报告接口在真实浏览器里能触发下载） ----
const gen = page.locator('.ant-tabs-tabpane-active button:has-text("生成 PDF")').first()
if (await gen.count()) {
  await gen.click()
  await page.waitForTimeout(5000)
  await shot('17-report-generated')
}

await browser.close()
console.log('\n=== console / page errors ===')
if (!errors.length) console.log('(none)')
else errors.forEach((e) => console.log(e))
process.exit(errors.length ? 1 : 0)
