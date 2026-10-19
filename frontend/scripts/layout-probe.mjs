#!/usr/bin/env node
// Зонд вёрстки Plume (волна 25, 2026-10-19): открывает НАСТОЯЩИЙ фронт в невидимом
// Chrome и меряет вёрстку числами — формы × ширина окна × ширина списка режима × табы ×
// просмотр/правка. Рецепт «мерить, а не считать по CSS» ([[css-measure-recipe]]) в виде
// инструмента: им сделана разведка волны 25, им же — приёмка её Ф4 (`--strict`).
//
// Нужно: локально запущены Django (:8000) и Vite (:5173), в dev-БД есть данные (снимок
// прода — `deploy/pull_prod.sh --load`). Вход — локальная сессия, которую скрипт сам
// выписывает через `manage.py shell` (пароль не нужен и не меняется, ключ сессии нигде не
// сохраняется). Профиль Chrome и снимки — во временной папке системы, не в репозитории.
//
// Режимы:
//   matrix  — переполнения: рабочая область, шапка, наезд полей шапки на команды, вылет
//             таблицы таба вбок, обрезанные строки списка режима, ряды табов (по умолчанию)
//   cols    — опись колонок каждого таба: подпись[класс]ширина
//   ghost   — число колонок заголовка против строки-призрака (`tr.ghost`) в правке
//   hover   — навести курсор на элемент (по умолчанию сумма над колонкой «Потребности»)
//             и прочитать текст его строки рядом с числами панели бюджета
//
// Примеры (из корня репозитория):
//   node frontend/scripts/layout-probe.mjs matrix --forms project/4,purchase/13 --vw 1440,1280,980 --side 240,400
//   node frontend/scripts/layout-probe.mjs matrix --forms purchase/13 --edit --strict
//   node frontend/scripts/layout-probe.mjs cols --forms project/4 --vw 1920
//   node frontend/scripts/layout-probe.mjs ghost --forms purchase/13,receipt/1
//   node frontend/scripts/layout-probe.mjs hover --forms project/4 --tab 1 --shots /tmp/probe
//
// Опции:
//   --forms a,b      формы по адресу `вид/id` (`/purchase/13`); обязательна
//   --vw 1440,...    ширины окна (по умолчанию 1440); высота 900
//   --side 240,...   ширины списка режима, подменой колонки сетки `.app` (по умолчанию —
//                    как есть в приложении)
//   --edit           нажать «Редактировать» перед замером (замок формы клиентский)
//   --tab N          только таб N (с нуля); по умолчанию — все табы
//   --hover SEL      селектор для режима hover (по умолчанию `.prow--sums .sumtip-host`)
//   --shots DIR      сохранять снимки экрана в DIR
//   --strict         код выхода 1, если хоть где-то переполнение / наезд / вылет вбок
//   --user NAME      пользователь сессии (по умолчанию — первый активный суперпользователь)
//   --base URL       адрес фронта (по умолчанию http://localhost:5173)
//   CHROME=путь      бинарь Chrome (по умолчанию — macOS-путь Google Chrome)
import { spawn, execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const BACKEND = resolve(HERE, '../../backend')

// ── аргументы ──
const argv = process.argv.slice(2)
const MODE = argv[0] && !argv[0].startsWith('--') ? argv.shift() : 'matrix'
const opt = {}
for (let i = 0; i < argv.length; i++) {
  const k = argv[i].replace(/^--/, '')
  const flag = ['edit', 'strict'].includes(k)
  opt[k] = flag ? true : argv[++i]
}
if (!['matrix', 'cols', 'ghost', 'hover'].includes(MODE) || !opt.forms) {
  console.error('использование: layout-probe.mjs [matrix|cols|ghost|hover] --forms вид/id,... ' +
    '[--vw ..] [--side ..] [--edit] [--tab N] [--hover SEL] [--shots DIR] [--strict] [--user NAME]')
  process.exit(2)
}
const FORMS = opt.forms.split(',')
const VWS = (opt.vw || '1440').split(',').map(Number)
const SIDES = opt.side ? opt.side.split(',').map(Number) : [null]
const BASE = opt.base || 'http://localhost:5173'
const EDIT = MODE === 'ghost' || !!opt.edit          // призрак живёт только в правке
const HOVER = opt.hover || '.prow--sums .sumtip-host'
const CHROME = process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
if (opt.shots) mkdirSync(opt.shots, { recursive: true })

// ── локальная сессия входа (ключ живёт только в памяти процесса) ──
const PY = `
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.auth import SESSION_KEY, BACKEND_SESSION_KEY, HASH_SESSION_KEY
from django.contrib.auth.models import User
import sys
name = ${JSON.stringify(opt.user || '')}
u = User.objects.get(username=name) if name else User.objects.filter(is_superuser=True, is_active=True).order_by('id').first()
s = SessionStore()
s[SESSION_KEY] = str(u.pk)
s[BACKEND_SESSION_KEY] = 'django.contrib.auth.backends.ModelBackend'
s[HASH_SESSION_KEY] = u.get_session_auth_hash()
s.create()
sys.stdout.write('SID=' + s.session_key)
`
const shellOut = execFileSync(join(BACKEND, '.venv/bin/python'), ['manage.py', 'shell', '-c', PY],
  { cwd: BACKEND, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] })
const SID = shellOut.match(/SID=(\w+)/)?.[1]
if (!SID) { console.error('не удалось выписать сессию через manage.py shell'); process.exit(2) }

// ── Chrome + CDP (голый WebSocket Node ≥ 22, без пакетов) ──
const PROFILE = mkdtempSync(join(tmpdir(), 'plume-probe-'))
const PORT = 9300 + Math.floor(Math.random() * 500)
const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', `--remote-debugging-port=${PORT}`,
  `--user-data-dir=${PROFILE}`, 'about:blank'], { stdio: 'ignore' })
const sleep = ms => new Promise(r => setTimeout(r, ms))
let targets
for (let i = 0; i < 75 && !targets; i++) {
  try { targets = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json() } catch { await sleep(200) }
}
const ws = new WebSocket(targets.find(t => t.type === 'page').webSocketDebuggerUrl)
await new Promise(r => { ws.onopen = r })
let seq = 0
const pend = new Map()
ws.onmessage = m => {
  const d = JSON.parse(m.data)
  if (d.id && pend.has(d.id)) { pend.get(d.id)(d); pend.delete(d.id) }
}
const send = (method, params = {}) => new Promise(r => {
  const id = ++seq; pend.set(id, r); ws.send(JSON.stringify({ id, method, params }))
})
const ev = async expr => (await send('Runtime.evaluate',
  { expression: expr, awaitPromise: true, returnByValue: true })).result?.result?.value
const host = new URL(BASE).hostname
await send('Network.setCookie', { name: 'sessionid', value: SID, domain: host, path: '/' })

// ── выражения замера (исполняются в странице) ──
const MEASURE = `(() => {
  const r = el => el.getBoundingClientRect()
  const work = document.querySelector('.work'); if (!work) return { err: 'нет .work' }
  const W = r(work)
  const out = { workW: work.clientWidth, workX: work.scrollWidth - work.clientWidth }
  const head = document.querySelector('.fs-head')
  if (head) {
    const props = head.querySelector('.props'), cmds = head.querySelector('.fh-right')
    out.headX = head.scrollWidth - head.clientWidth
    out.fieldsW = Math.round(r(props).width)
    out.cmdW = cmds ? Math.round(r(cmds).width) : 0
    const cmdL = cmds ? r(cmds).left : Infinity
    out.overlap = [...props.querySelectorAll('dd *')]
      .filter(e => r(e).width && r(e).right > cmdL + 0.5)
      .map(e => '.' + String(e.className).split(' ')[0] + '@+' + Math.round(r(e).right - cmdL)).slice(0, 4)
  }
  const list = document.querySelector('.fs-list')
  if (list) out.listX = list.scrollWidth - list.clientWidth
  // торчит за правый край .work и НЕ внутри собственной прокрутки — вылет рамки
  const edge = W.right - (work.offsetWidth - work.clientWidth) + 0.5
  const stick = new Set()
  for (const el of work.querySelectorAll('*')) {
    const b = r(el); if (!b.width || b.right <= edge) continue
    let p = el.parentElement, scrolls = false
    while (p && p !== work) { if (/auto|scroll|hidden/.test(getComputedStyle(p).overflowX)) { scrolls = true; break } p = p.parentElement }
    if (!scrolls) stick.add((typeof el.className === 'string' && el.className ? '.' + el.className.split(' ')[0] : el.tagName) + '@+' + Math.round(b.right - W.right))
  }
  out.stickOut = [...stick].slice(0, 6)
  const rows = [...document.querySelectorAll('.sidebar .tree-item:not(.new)')]
  out.sideClipped = rows.filter(i => i.scrollWidth > i.clientWidth + 0.5).length
  out.sideRows = rows.length
  const tabs = document.querySelector('.fs-tabs')
  out.tabsH = tabs ? Math.round(r(tabs).height) : 0
  return out
})()`

const COLS = `(() => {
  const L = document.querySelector('.fs-list'); if (!L) return 'нет списка'
  const w = e => Math.round(e.getBoundingClientRect().width)
  const cell = c => ((c.textContent || '').trim() || '·') + '[' + c.className + ']' + w(c)
  const t = L.querySelector('table.grid')
  if (t) return 'grid ' + [...t.querySelector('tr').children].map(cell).join(' | ')
  const p = L.querySelector('.prow--head') || L.querySelector('.prow')
  if (p) return 'prow(' + p.closest('.pgrid')?.className + ') ' + [...p.children].map(cell).join(' | ')
  return 'иное: ' + (L.firstElementChild?.className || '')
})()`

const GHOST = `(() => {
  const t = document.querySelector('.fs-list table.grid'); if (!t) return null
  const g = t.querySelector('tr.ghost'); if (!g) return null
  const n = r => [...r.children].reduce((s, c) => s + (c.colSpan || 1), 0)
  return { head: n(t.querySelector('thead tr') || t.querySelector('tr')), ghost: n(g) }
})()`

const BUDGET = `[...document.querySelectorAll('.stat')].map(s => s.innerText.replace(/\\n/g, ': ')).join(' | ')`

// ── обход ──
let bad = 0
const shot = async name => {
  if (!opt.shots) return
  const s = await send('Page.captureScreenshot', { format: 'png' })
  writeFileSync(join(opt.shots, name + '.png'), Buffer.from(s.result.data, 'base64'))
}
try {
  for (const form of FORMS) {
    for (const vw of VWS) {
      await send('Emulation.setDeviceMetricsOverride',
        { width: vw, height: 900, deviceScaleFactor: 1, mobile: false })
      for (const side of SIDES) {
        await send('Page.navigate', { url: `${BASE}/${form}` })
        await sleep(2500)
        if (side != null)
          await ev(`(() => { const s = document.createElement('style'); s.textContent =
            '.app{grid-template-columns:48px ${side}px minmax(0,1fr) !important}'; document.head.appendChild(s) })()`)
        if (EDIT) {
          await ev(`[...document.querySelectorAll('.fh-ctl')].find(b => b.textContent.includes('Редактировать'))?.click()`)
          await sleep(800)
        }
        const labels = (await ev(`[...document.querySelectorAll('.fs-tab .lbl')].map(x => x.textContent)`)) || []
        const idx = opt.tab != null ? [Number(opt.tab)] : labels.length ? labels.map((_, i) => i) : [0]
        for (const t of idx) {
          await ev(`document.querySelectorAll('.fs-tab')[${t}]?.click()`)
          await sleep(900)
          const tag = [form, vw, side ?? 'app', EDIT ? 'правка' : 'просмотр', labels[t] ?? '-']
          const name = tag.join('_').replace(/[/ ]/g, '-')
          if (MODE === 'matrix') {
            const m = await ev(MEASURE)
            const fail = m.workX > 0 || m.headX > 0 || m.listX > 0 || m.overlap?.length || m.stickOut?.length
            if (fail) bad++
            console.log([...tag.slice(0, 4), String(tag[4]).padEnd(12), fail ? '✗' : '✓',
              `work ${m.workW}`, `workX ${m.workX}`, `поля ${m.fieldsW}/команды ${m.cmdW}`,
              `headX ${m.headX}`, `listX ${m.listX ?? '-'}`, `список✂ ${m.sideClipped}/${m.sideRows}`,
              `табы ${m.tabsH}px`, m.overlap?.length ? 'наезд ' + m.overlap.join(' ') : '',
              m.stickOut?.length ? 'вылет ' + m.stickOut.join(' ') : ''].join('  '))
          } else if (MODE === 'cols') {
            console.log(tag.join(' '), '::', await ev(COLS))
          } else if (MODE === 'ghost') {
            const g = await ev(GHOST)
            if (g) {
              const ok = g.head === g.ghost
              if (!ok) bad++
              console.log(tag.join(' '), ok ? '✓' : '✗', `заголовок ${g.head} · призрак ${g.ghost}`)
            }
          } else {
            const box = await ev(`(() => { const h = document.querySelector(${JSON.stringify(HOVER)});
              if (!h) return null; h.scrollIntoView({ block: 'center' }); const b = h.getBoundingClientRect();
              return [b.x + b.width / 2, b.y + b.height / 2] })()`)
            if (!box) { console.log(tag.join(' '), ':: нет элемента', HOVER); continue }
            await sleep(300)
            await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x: box[0], y: box[1] })
            await sleep(400)
            console.log(tag.join(' '))
            console.log('  панель:', await ev(BUDGET))
            console.log('  строка:', await ev(`(() => { const h = document.querySelector(${JSON.stringify(HOVER)});
              return (h.closest('.prow') || h.parentElement).innerText.replace(/\\n/g, ' · ') })()`))
          }
          await shot(name)
        }
      }
    }
  }
} finally {
  ws.close()
  chrome.kill()
  await sleep(300)
  rmSync(PROFILE, { recursive: true, force: true })
}
if (opt.strict && bad) { console.error(`✗ нарушений: ${bad}`); process.exit(1) }
