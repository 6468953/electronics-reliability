/**
 * scripts/check_classify.mjs — 分类页专项检查（开发期用，不参与构建）
 *
 * 盯两件事：
 *   1. 结构件、螺丝、线缆这些非电子件，落到了类目而不是"未识别"；
 *   2. 真正未识别的行，类目下拉框必须是空的 —— 不能把 7% 的瞎猜预填成"建议"。
 *
 * 用法：先启动后端（单端口 8000），再 node scripts/check_classify.mjs
 */
import { chromium } from 'playwright-core'
import fs from 'node:fs'

const BASE = process.env.BASE || 'http://127.0.0.1:8000'
fs.mkdirSync('shots', { recursive: true })
const errors = []

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1560, height: 1100 } })
await ctx.addInitScript(() => localStorage.setItem('relsys_tour_done', '1'))
const page = await ctx.newPage()
page.on('pageerror', (e) => errors.push(`[pageerror] ${String(e).slice(0, 200)}`))
page.on('console', (m) => { if (m.type() === 'error') errors.push(`[console] ${m.text().slice(0, 200)}`) })

await page.goto(BASE + '/login', { waitUntil: 'networkidle' })
await page.fill('input[type="text"]', 'admin')
await page.fill('input[type="password"]', 'admin123')
await page.keyboard.press('Enter')
await page.waitForTimeout(1500)

await page.goto(BASE + '/', { waitUntil: 'networkidle' })
await page.locator('text=演示项目').first().click()
await page.waitForTimeout(1200)
await page.locator('.ant-tabs-tab', { hasText: '分类' }).first().click()
await page.waitForTimeout(2000)

const rerun = page.locator('button', { hasText: '重新分类全部行' }).first()
if (await rerun.count()) { await rerun.click(); await page.waitForTimeout(3000) }

const queue = page.locator('text=待确认队列').first()
await queue.scrollIntoViewIfNeeded()
await page.waitForTimeout(800)
await page.screenshot({ path: 'shots/classify-queue.png' })

const rows = page.locator('.ant-table-tbody .ant-table-row')
const n = await rows.count()
let emptySelects = 0
const detail = []
for (let i = 0; i < n; i++) {
  const txt = (await rows.nth(i).innerText()).replace(/\s+/g, ' ').trim()
  const sel = rows.nth(i).locator('.ant-select-selection-item, .ant-select-selection-placeholder')
  const selTxt = (await sel.count()) ? (await sel.first().innerText()).trim() : ''
  if (!selTxt || selTxt === '选择类目') emptySelects++
  detail.push(`${txt.slice(0, 40)} ⇒ [${selTxt || '空'}]`)
}

console.log('队列行数:', n)
detail.forEach((d) => console.log('  ', d))
console.log(`空下拉框: ${emptySelects} / ${n}`)
console.log('页面错误:', errors.length ? errors.slice(0, 3) : '无')
await browser.close()
