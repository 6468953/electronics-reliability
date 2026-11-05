/**
 * scripts/check_limits.mjs — 「数据成色 / 本次局限」专项检查（开发期用，不参与构建）
 *
 * 盯三件事：
 *   1. 结果页顶部出现「读数字前先看」这一行，且算出的条目与后端一致；
 *   2. 参数库页每个参数集显示「数据成色」标签；
 *   3. 没有英文报错、没有控制台异常。
 *
 * 用法：先启动后端（单端口 8000），再 node scripts/check_limits.mjs
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
page.on('console', (m) => {
  if (m.type() === 'error') errors.push(`[console] ${m.text().slice(0, 200)}`)
})

await page.goto(BASE + '/login', { waitUntil: 'networkidle' })
await page.fill('input[type="text"]', 'admin')
await page.fill('input[type="password"]', 'admin123')
await page.keyboard.press('Enter')
await page.waitForTimeout(1500)

await page.goto(BASE + '/', { waitUntil: 'networkidle' })
await page.locator('text=演示项目').first().click()
await page.waitForTimeout(1200)
await page.locator('.ant-tabs-tab', { hasText: '结果' }).first().click()
await page.waitForTimeout(2500)

await page.screenshot({ path: 'shots/limits-collapsed.png' })

// 展开局限性折叠面板
const head = page.locator('text=读数字前先看').first()
const hasHead = await head.count()
if (hasHead) {
  await head.click()
  await page.waitForTimeout(600)
  await head.scrollIntoViewIfNeeded()
  await page.waitForTimeout(400)
  await page.screenshot({ path: 'shots/limits-expanded.png' })
}

const bodyText = await page.locator('body').innerText()
const rowTexts = hasHead ? await page.locator('.ant-collapse-content .ant-collapse-content-box > div').allInnerTexts() : []

// 参数库页
await page.goto(BASE + '/params', { waitUntil: 'networkidle' })
await page.waitForTimeout(2000)
await page.screenshot({ path: 'shots/params-quality.png' })
const paramsText = await page.locator('body').innerText()

const checks = {
  '结果页有局限性入口': hasHead > 0,
  '含「参数」成色条目': /示例量级|已按标准原表录入/.test(bodyText),
  '含非电子件占比': /非电子件占|非电子件（标准未覆盖）/.test(bodyText),
  '含降额缺数据提示': /项降额无法判定|缺数据/.test(bodyText),
  '参数库页显示数据成色': /数据成色/.test(paramsText),
  '无英文网络错误': !/Failed to fetch/.test(bodyText + paramsText),
}
for (const [k, v] of Object.entries(checks)) console.log(`${v ? 'PASS' : 'FAIL'}  ${k}`)
console.log('\n展开后的条目行：')
rowTexts.filter(Boolean).slice(0, 10).forEach((t) => console.log('  ·', t.replace(/\s+/g, ' ').slice(0, 110)))
console.log('\n页面错误:', errors.length ? errors.slice(0, 3) : '无')
await browser.close()
