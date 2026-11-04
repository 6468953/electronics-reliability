/**
 * scripts/diag.mjs — 诊断三条"用户会走到"的路径
 *
 * 1) file:// 双击 index.html       → 应看到中文说明页，而不是白屏/英文报错
 * 2) http://127.0.0.1:8000 正常使用 → 登录 + 首页应可用
 * 3) 页面已加载但后端失联           → 应看到中文错误 + 顶部红色横幅，而不是 "Failed to fetch"
 *
 * 用法：node scripts/diag.mjs   （需要后端已在 8000 端口运行）
 */

import { chromium } from 'playwright-core'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const BASE = 'http://127.0.0.1:8000'
const __dirname = path.dirname(fileURLToPath(import.meta.url))
const DIST_INDEX = path.resolve(__dirname, '../dist/index.html')
const SHOTS = path.resolve(__dirname, '../shots')

const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
await ctx.addInitScript(() => {
  // 首页首次进入会弹新手引导（Tour），半透明遮罩会挡住整个页面。
  // 测试关心的不是它，直接标记为已看过。
  try {
    localStorage.setItem('relsys_tour_done', '1')
  } catch {
    /* file:// 下 localStorage 不可用，忽略 */
  }
})
const page = await ctx.newPage()

const errors = []
page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`))

/* ---------- 1) file:// 直接双击 ---------- */
await page.goto(`file:///${DIST_INDEX.replace(/\\/g, '/')}`, { waitUntil: 'load' })
await page.waitForTimeout(600)
const fileBody = (await page.locator('body').innerText()).replace(/\s+/g, ' ')
console.log('[1] file:// 标题:', await page.title())
console.log('[1] file:// 文案:', fileBody.slice(0, 90))
console.log('[1] 判定:', fileBody.includes('不能直接双击打开') ? 'OK 显示了中文说明' : 'FAIL 仍是白屏')
await page.screenshot({ path: `${SHOTS}/diag-1-file.png`, fullPage: true })

/* ---------- 2) 正常访问 ---------- */
await page.goto(BASE, { waitUntil: 'networkidle' })
console.log('[2] 首页 title:', await page.title())
await page.fill('input[placeholder="admin"]', 'admin')
await page.fill('input[placeholder="admin123"]', 'admin123')
await page.click('button[type="submit"]')
await page.waitForURL(`${BASE}/`, { timeout: 15000 })
await page.waitForTimeout(1500)
const homeText = await page.locator('body').innerText()
console.log('[2] 登录后出现项目:', homeText.includes('智能网关 GW-200') ? 'OK' : 'FAIL')
console.log('[2] 是否有红色横幅:', homeText.includes('与后端服务的连接已断开') ? '有(异常)' : '无(正常)')
await page.screenshot({ path: `${SHOTS}/diag-2-home.png`, fullPage: true })

/* ---------- 3) 页面已加载，后端失联 ---------- */
// 用 route.abort 精确模拟"请求根本发不出去"，这正是服务被关掉时浏览器的行为
await page.route('**/api/**', (r) => r.abort('connectionrefused'))
await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')))
await page.waitForTimeout(1200)
const bannerText = await page.locator('body').innerText()

// 再点一个会真正发请求的入口，看用户拿到的是哪句话
await page.click('.ant-menu-item:has-text("分类知识库")')
await page.waitForTimeout(1500)
const afterClick = await page.locator('body').innerText()

const hasBanner = afterClick.includes('与后端服务的连接已断开')
const hasCN = afterClick.includes('连不上后端服务')
const hasEnglish = afterClick.includes('Failed to fetch')
console.log('[3] 横幅出现:', hasBanner ? 'OK' : 'FAIL')
console.log('[3] 中文错误提示:', hasCN ? 'OK' : 'FAIL 没弹提示')
console.log('[3] 是否泄漏英文 Failed to fetch:', hasEnglish ? 'FAIL 仍然暴露英文' : 'OK 已翻译')

// toast 会盖在横幅上，先清掉它，单独验证横幅本身的排版（按钮是否可见）
await page.evaluate(() => {
  document.querySelectorAll('.ant-message, .ant-notification').forEach((n) => n.remove())
})
await page.waitForTimeout(400)
const banner = page.locator('.ant-alert').first()
const box = await banner.boundingBox()
const btnVisible = await page.locator('.ant-alert button:has-text("重新检测")').isVisible().catch(() => false)
console.log('[3] 横幅高度:', box ? Math.round(box.height) + 'px' : '未渲染')
console.log('[3] 重新检测按钮可见:', btnVisible ? 'OK' : 'FAIL')
await page.screenshot({ path: `${SHOTS}/diag-3-offline.png`, fullPage: true })
await banner.screenshot({ path: `${SHOTS}/diag-4-banner.png` })

console.log('[!] pageerror 数量:', errors.length, errors.slice(0, 3))

await browser.close()
