const fs = require('fs');
const path = require('path');
const http = require('http');
const {connect, getJson} = require('./cdp_lib');
const {assertNotBanned, banStatus, detectRiskPage, emergencyStop} = require('./guard');
const {Human, rand, randInt} = require('./humanize');

const EXT = 'fpfjpeicdgddkojpldehpfnbnlojmbcb';
const STATE_FILE = path.join(__dirname, 'state.json');
const LOG_FILE = path.join(__dirname, 'daily.log');
const TIERS = require('./tiers.json');
const COMPANIES = require('./companies.json');
const SHOT_DIR = 'C:\\Users\\26808\\Documents\\Trae-CN\\temp_20261121_07';
const sleep = ms => new Promise(r => setTimeout(r, ms));

function log(...args) {
  const line = '[' + new Date().toLocaleString('zh-CN', {hour12: false}) + '] ' + args.join(' ');
  console.log(line);
  fs.appendFileSync(LOG_FILE, line + '\n');
}
function loadState() {
  try { return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8')); } catch { return {}; }
}
function saveState(s) { fs.writeFileSync(STATE_FILE, JSON.stringify(s, null, 2)); }
function ymd(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
function q2u(q) { return encodeURIComponent(String(q).replace(/\s+/g, '')); }
// 按权重比例分配整数配额：先取整，余数按小数部分从大到小依次补 1
function allocate(weights, total) {
  const entries = Object.entries(weights);
  const sum = entries.reduce((s, [, w]) => s + (Number(w) || 0), 0);
  if (!entries.length || sum <= 0 || total <= 0) return entries.map(([k]) => ({key: k, n: 0}));
  const raw = entries.map(([k, w]) => ({key: k, n: total * (Number(w) || 0) / sum}));
  const out = raw.map(x => ({key: x.key, n: Math.floor(x.n)}));
  let rest = total - out.reduce((s, x) => s + x.n, 0);
  const order = raw.map((x, i) => ({i, frac: x.n - Math.floor(x.n)}))
    .sort((a, b) => b.frac - a.frac || a.i - b.i);
  for (let i = 0; rest > 0; i++, rest--) out[order[i % order.length].i].n += 1;
  return out;
}
// 先分厂规模总量，再在每个厂规模内按搜索词权重分配
function planDaily(cfg, totalToday) {
  const tiers = allocate(cfg.companyQuota, totalToday);
  const plan = [];
  for (const t of tiers) {
    for (const q of allocate(cfg.queryWeights, t.n)) {
      if (q.n > 0) plan.push({q: q.key, tier: t.key, quota: q.n});
    }
  }
  return plan;
}
// 当日可投总量：星期额度 - 已投，且不超过 dailyTotal 与本批 cap
function computeTotalToday(now, used, capArg) {
  const dq = dayQuota(now);
  const cap = (capArg == null || Number.isNaN(Number(capArg))) ? Infinity : Number(capArg);
  return Math.max(0, Math.min(dq - used, TIERS.dailyTotal, cap));
}
// 搜索页 URL（纯函数，测试与 runPage 共用）
// experience=108：在校生；jobType=1902：实习（2026-11-25 在 BOSS 页面实测确认）
function buildSearchUrl(query, page, city = '101010100') {
  return `https://www.zhipin.com/web/geek/jobs?query=${q2u(query)}&city=${city}&experience=108&jobType=1902&page=${page}`;
}
// 资产闸门：招呼语文案/开关完全以插件里用户自己的设置为准（脚本不校验、不覆盖），仅要求简历图存在
function validateAssets(sync) {
  const imgOk = !!(sync && sync.imgOk);
  return {ok: imgOk, greetingOk: true, imgOk};
}
// 扩展 deliveryLimit 以“今日已投”为 base，而不是本批 cap
function computeDeliveryLimit(extBefore, used, appliedTotal, capNow) {
  const base = extBefore != null ? extBefore : (used + appliedTotal);
  return base + capNow;
}
const STOP_HEAD = {
  LIMIT_EXHAUSTED: '今日沟通额度已达上限',
  EXT_LIMIT_REACHED: '扩展今日投递额度已达上限',
  DAILY_QUOTA_REACHED: '今日计划额度已用尽',
};
function summarizeStop(reason, appliedTotal, left) {
  const head = STOP_HEAD[reason] || '任务已安全挂起';
  return `${head}，已成功投递 ${appliedTotal} 份，任务安全挂起，等待明日重置（${reason}）`;
}
function markSuspended(state, today, reason, appliedTotal, left) {
  state[today] = state[today] || {};
  state[today].suspended = {
    reason,
    applied: appliedTotal,
    left,
    at: new Date().toISOString(),
    message: summarizeStop(reason, appliedTotal, left),
    resume: '等待明日重置',
  };
  return state;
}

async function closeTab(id) {
  await new Promise(res => http.get({host: '127.0.0.1', port: 9222, path: '/json/close/' + id}, r => { r.resume(); r.on('end', res); }));
}
async function findTab(sub) {
  const list = await getJson('/json/list');
  return list.find(t => t.type === 'page' && t.url.includes(sub));
}
async function ensureZhipinTab(sub, url) {
  if (await findTab(sub)) return;
  let c;
  try { c = await connect('zhipin.com'); } catch { throw new Error('NO_ZHIPIN_TAB'); }
  await c.send('Target.createTarget', {url});
  c.close();
  // Boss 打开 chat 页可能先落主页再跳转，固定 5s 不够；轮询最多 15s 等 tab 出现
  for (let i = 0; i < 15; i++) {
    await sleep(1000);
    if (await findTab(sub)) return;
  }
  throw new Error('TAB_TIMEOUT ' + sub);
}
async function extSession() {
  let list = await getJson('/json/list');
  for (const t of list.filter(t => t.url.includes('chrome-extension://' + EXT))) await closeTab(t.id);
  await sleep(800);
  const jobs = await findTab('zhipin.com');
  if (!jobs) throw new Error('NO_ZHIPIN_TAB');
  const jc = await connect('zhipin.com');
  await jc.send('Target.createTarget', {url: `chrome-extension://${EXT}/options.html`});
  jc.close();
  await sleep(4500);
  const tab = await findTab(EXT + '/options.html');
  if (!tab) throw new Error('EXT_TAB_FAIL');
  return await connect(EXT + '/options.html');
}
async function readExt() {
  const c = await extSession();
  const r = await c.evaluate(`(async () => {
    const all = await chrome.storage.local.get(null);
    const cfg = all['web-geek-job-FormData'] || {};
    let imgOk = false, imgSize = 0;
    const g = cfg.customGreeting && cfg.customGreeting.value || [];
    const img = g.find(p => p.type === 'image');
    if (img) {
      try {
        const db = await new Promise((res, rej) => { const q = indexedDB.open('ExtensionGlobalDB', 1); q.onsuccess = () => res(q.result); q.onerror = () => rej(q.error); });
        const f = await new Promise(res => { const tx = db.transaction('images', 'readonly'); const get = tx.objectStore('images').get(img.image); get.onsuccess = () => res(get.result); get.onerror = () => res(null); });
        imgOk = !!f; imgSize = f ? f.size : 0;
      } catch (e) {}
    }
    return {
      greeting: g.filter(p => p.type === 'text').map(p => p.content).join(''),
      greetingEnable: !!(cfg.customGreeting && cfg.customGreeting.enable),
      imageKey: img ? img.image : null, imgOk, imgSize,
      limit: cfg.deliveryLimit ? cfg.deliveryLimit.value : null,
      company: cfg.company, jobTitle: cfg.jobTitle,
      today: all['web-geek-job-Today'] || null
    };
  })()`);
  c.close();
  return r;
}
async function setExt(patch) {
  const c = await extSession();
  const r = await c.evaluate(`(async () => {
    const k = 'web-geek-job-FormData';
    const cur = (await chrome.storage.local.get(k))[k];
    const patch = ${JSON.stringify(patch)};
    Object.assign(cur, patch);
    await chrome.storage.local.set({[k]: cur});
    return {limit: cur.deliveryLimit, company: cur.company, jobTitle: cur.jobTitle, greeting: cur.customGreeting};
  })()`);
  c.close();
  return r;
}
// 只读校验扩展资产：招呼语文案/开关/图片全部以插件选项里用户自己的设置为准，脚本一律不写入覆盖
async function syncExtAssets() {
  const c = await extSession();
  const r = await c.evaluate(`(async () => {
    const all = await chrome.storage.local.get(null);
    const cfg = all['web-geek-job-FormData'] || {};
    let imgOk = false, imgSize = 0;
    const g = cfg.customGreeting && cfg.customGreeting.value || [];
    const img = g.find(p => p.type === 'image');
    if (img) {
      try {
        const db = await new Promise((res, rej) => { const q = indexedDB.open('ExtensionGlobalDB', 1); q.onsuccess = () => res(q.result); q.onerror = () => rej(q.error); });
        const f = await new Promise(res => { const tx = db.transaction('images', 'readonly'); const get = tx.objectStore('images').get(img.image); get.onsuccess = () => res(get.result); get.onerror = () => res(null); });
        imgOk = !!f; imgSize = f ? f.size : 0;
      } catch (e) {}
    }
    return {
      greeting: g.filter(p => p.type === 'text').map(p => p.content).join(''),
      greetingEnable: !!(cfg.customGreeting && cfg.customGreeting.enable),
      imageKey: img ? img.image : null, imgOk, imgSize,
      limit: cfg.deliveryLimit ? cfg.deliveryLimit.value : null,
      jobTitle: cfg.jobTitle
    };
  })()`);
  c.close();
  return r;
}
// 重载扩展，迫使后台/注入脚本丢弃旧配置缓存（否则仍按旧招呼语发送）
async function reloadExt() {
  const c = await extSession();
  try {
    await c.evaluate(`(() => { setTimeout(() => { try { chrome.runtime.reload(); } catch (e) {} }, 200); return true; })()`);
  } catch (e) { /* reload 会销毁上下文 */ }
  c.close();
  await sleep(6000);
}
async function countToday() {
  await ensureZhipinTab('/web/geek/chat', 'https://www.zhipin.com/web/geek/chat');
  const c = await connect('zhipin.com/web/geek/chat');
  let r = null;
  for (let i = 0; i < 12; i++) {
    r = await c.evaluate(`(() => {
      const box = document.querySelector('.user-list-content') || document.querySelector('.user-list');
      const rows = box ? Array.from(box.querySelectorAll('li')) : [];
      let n = 0; const heads = [];
      for (const row of rows) {
        const t = (row.innerText || '').trim();
        const m = t.match(/^(\\d{2}:\\d{2})/);
        if (m) { n++; heads.push(m[1]); }
      }
      return {todayCount: n, rows: rows.length, firstTime: heads[0] || null, lastTime: heads[heads.length-1] || null};
    })()`);
    if (r.rows > 0) break;
    await sleep(1500);
  }
  c.close();
  return r;
}
async function countSince(hhmm) {
  await ensureZhipinTab('/web/geek/chat', 'https://www.zhipin.com/web/geek/chat');
  const c = await connect('zhipin.com/web/geek/chat');
  await sleep(2500);
  const r = await c.evaluate(`(() => {
    const box = document.querySelector('.user-list-content') || document.querySelector('.user-list');
    const rows = box ? Array.from(box.querySelectorAll('li')) : [];
    const since = ${JSON.stringify(hhmm)};
    let n = 0; const heads = [];
    let seen = false;
    for (const row of rows) {
      const t = (row.innerText || '').trim();
      const m = t.match(/^(\\d{2}:\\d{2})/);
      if (!m) { if (!seen) { n++; heads.push('now'); } continue; }
      seen = true;
      if (m[1] >= since) { n++; heads.push(m[1]); } else break;
    }
    return {since, count: n, heads: heads.slice(0, 20)};
  })()`);
  c.close();
  return r;
}
function hhmmNow() {
  const d = new Date();
  return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
}
async function panelState() {
  let c;
  try { c = await connect('zhipin.com/web/geek/jobs'); }
  catch (e) {
    c = await connect('zhipin.com');
    await c.send('Page.navigate', {url: 'https://www.zhipin.com/web/geek/jobs?query=python%E5%AE%9E%E4%B9%A0&city=101010100&experience=108&jobType=1902'});
    await sleep(6000);
  }
  const r = await c.evaluate(`(() => {
    const host = document.querySelector('boss-helper-job');
    const sr = host && host.shadowRoot;
    if (!sr) return {ok: false};
    const t = (sr.textContent || '').replace(/\\s+/g, ' ');
    const m = t.match(/当前页面处理:\\s*(\\d+)\\/(\\d+)/);
    const btns = Array.from(sr.querySelectorAll('button')).map(b => (b.innerText || '').trim()).filter(Boolean);
    return {ok: true, progress: m ? m[1] : null, total: m ? m[2] : null, running: btns.includes('暂停')};
  })()`);
  c.close();
  return r;
}
async function isCaptcha(c) {
  try {
    const u = await c.evaluate(`location.href`);
    return String(u).includes('/passport/zp/verify');
  } catch (e) { return false; }
}
// 风控页判定：URL 或正文命中验证码/异常行为/封禁文案
async function riskHit(c) {
  try {
    const info = await c.evaluate(`(() => ({url: location.href, text: (document.body && document.body.innerText || '').slice(0, 3000)}))()`);
    return detectRiskPage(info.url, info.text) ? info : null;
  } catch (e) { return null; }
}
async function waitPanel(c, secs = 25) {
  for (let i = 0; i < secs; i++) {
    const ok = await c.evaluate(`!!(document.querySelector('boss-helper-job') && document.querySelector('boss-helper-job').shadowRoot)`);
    if (ok) return true;
    await sleep(1000);
  }
  return false;
}
// 取扩展面板内按钮的屏幕坐标（shadowRoot 内元素无法用 document.querySelector 定位）
async function shadowBtnRect(c, label) {
  return await c.evaluate(`(() => {
    const h = document.querySelector('boss-helper-job');
    const sr = h && h.shadowRoot;
    if (!sr) return null;
    const b = Array.from(sr.querySelectorAll('button')).find(x => (x.innerText || '').trim() === ${JSON.stringify(label)});
    if (!b) return null;
    const r = b.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return null;
    return {x: r.x + r.width / 2, y: r.y + r.height / 2, w: r.width, h: r.height};
  })()`);
}
// 拟人化点击扩展面板按钮：贝塞尔移动 + 抖动 + 真实按下/松开
async function humanClickShadowBtn(c, human, label) {
  const r = await shadowBtnRect(c, label);
  if (!r) return false;
  await human.click({
    x: r.x + rand(-r.w * 0.16, r.w * 0.16),
    y: r.y + rand(-r.h * 0.16, r.h * 0.16)
  });
  return true;
}
// 读扩展面板「今日投递 N/150」计数：扩展不遵守 deliveryLimit，必须以该计数做硬上限
async function panelToday(c, tries = 6) {
  for (let i = 0; i < tries; i++) {
    const n = await c.evaluate(`(() => {
      const h = document.querySelector('boss-helper-job'); const sr = h && h.shadowRoot;
      if (!sr) return null;
      const t = (sr.textContent || '').replace(/\\s+/g, ' ');
      const m = t.match(/今日投递:\\s*(\\d+)\\s*\\//);
      return m ? Number(m[1]) : null;
    })()`);
    if (n != null) return n;
    await sleep(1000);
  }
  return null;
}
async function runPage(query, page, cap, maxMinutes) {
  let c;
  try { c = await connect('zhipin.com/web/geek/jobs'); }
  catch (e) {
    c = await connect('zhipin.com');
  }
  const human = new Human(c);
  const url = buildSearchUrl(query, page);
  await c.send('Target.activateTarget', {targetId: c.tab.id}).catch(() => {});
  await c.send('Page.bringToFront').catch(() => {});
  await c.send('Page.navigate', {url});
  await sleep(randInt(4500, 8500));   // 页面加载后先随机停顿，不立刻动作
  const risk0 = await riskHit(c);
  if (risk0) await emergencyStop(c, 'RISK_PAGE_ON_LOAD', {url: risk0.url});
  let cards = 0;
  for (let i = 0; i < 10; i++) {
    cards = await c.evaluate(`document.querySelectorAll('li.job-card-box').length`);
    if (cards > 0) break;
    await sleep(2000);
  }
  if (!cards) { c.close(); return {applied: 'NO_CARDS', cards: 0}; }
  if (!(await waitPanel(c))) { c.close(); return {applied: 'NO_PANEL', cards}; }
  // 拟人化阅读：滚动浏览 JD 列表 5-15 秒后才操作面板
  await human.readDwell(5000, 15000);
  const risk1 = await riskHit(c);
  if (risk1) await emergencyStop(c, 'RISK_PAGE_BEFORE_APPLY', {url: risk1.url});
  const base = await panelToday(c, 6);
  if (base == null) { c.close(); return {applied: 'NO_COUNTER', cards}; }
  const clicked = await humanClickShadowBtn(c, human, '开始投递');
  if (!clicked) { c.close(); return {applied: 'NO_BTN', cards}; }
  const click = 'CLICKED';
  // 确认扩展真正进入运行态：navigate 后首次点击可能落在未重绑事件的死按钮上（SPA 重渲染）
  let started = false;
  for (let k = 0; k < 3 && !started; k++) {
    await sleep(4000);
    const chk = await c.evaluate(`(() => {
      const h = document.querySelector('boss-helper-job'); const sr = h && h.shadowRoot;
      if (!sr) return {running: false, gone: true};
      const btns = Array.from(sr.querySelectorAll('button')).map(b => (b.innerText || '').trim()).filter(Boolean);
      return {running: btns.includes('暂停'), gone: false};
    })()`);
    if (chk.running) { started = true; break; }
    if (chk.gone) continue;
    await humanClickShadowBtn(c, human, '开始投递');
  }
  if (!started) { c.close(); return {applied: 'NOT_STARTED', cards}; }
  const deadline = Date.now() + maxMinutes * 60000;
  let last = null, still = 0, goneRuns = 0, tick = 0;
  while (Date.now() < deadline) {
    await sleep(2500);
    tick++;
    // 每 15 秒抽检一次风控页：命中立即截图并急停，绝不刷新重试
    if (tick % 3 === 0) {
      const rk = await riskHit(c);
      if (rk) await emergencyStop(c, 'RISK_PAGE_DURING_RUN', {url: rk.url, query, page});
    }
    const st = await c.evaluate(`(() => {
      const host = document.querySelector('boss-helper-job');
      const sr = host && host.shadowRoot;
      if (!sr) return {progress: null, total: null, running: false, gone: true};
      const t = (sr.textContent || '').replace(/\\s+/g, ' ');
      const m = t.match(/当前页面处理:\\s*(\\d+)\\/(\\d+)/);
      const tm = t.match(/今日投递:\\s*(\\d+)\\s*\\//);
      const btns = Array.from(sr.querySelectorAll('button')).map(b => (b.innerText || '').trim()).filter(Boolean);
      return {progress: m ? m[1] : null, total: m ? m[2] : null, today: tm ? Number(tm[1]) : null, running: btns.includes('暂停'), gone: false};
    })()`);
    if (st.gone) { goneRuns++; if (goneRuns >= 3) { log('PANEL_GONE x3'); break; } } else goneRuns = 0;
    // 硬上限：扩展自己不会按 deliveryLimit 停，必须由面板今日计数兜底，超 cap 立即暂停
    if (st.today != null && base != null && st.today - base >= cap) {
      log('CAP_STOP', 'today=' + st.today, 'base=' + base, 'cap=' + cap);
      await humanClickShadowBtn(c, human, '暂停');
      last = st.progress;
      c.close();
      return {applied: 'CAP_STOP', cards, progress: last, cap};
    }
    if (last && st.progress === last && !st.gone) still++; else still = 0;
    last = st.progress;
    if (!st.running) break;
    if (still >= 6) { // stalled ~30s -> 拟人化点击暂停后结束本页
      await humanClickShadowBtn(c, human, '暂停');
      break;
    }
  }
  c.close();
  return {applied: 'RUN_DONE', cards, progress: last, cap};
}
// 冒烟专用：只发 1 份，投出第 1 份后 0.4 秒内点击暂停
async function runOne(query, page) {
  let c;
  try { c = await connect('zhipin.com/web/geek/jobs'); }
  catch (e) { c = await connect('zhipin.com'); }
  const human = new Human(c);
  const url = buildSearchUrl(query, page);
  await c.send('Target.activateTarget', {targetId: c.tab.id}).catch(() => {});
  await c.send('Page.bringToFront').catch(() => {});
  await c.send('Page.navigate', {url});
  await sleep(randInt(4500, 8500));
  const rk0 = await riskHit(c);
  if (rk0) await emergencyStop(c, 'RISK_PAGE_SMOKE', {url: rk0.url});
  if (await isCaptcha(c)) { c.close(); return {applied: 'CAPTCHA', cards: 0}; }
  let cards = 0;
  for (let i = 0; i < 10; i++) {
    cards = await c.evaluate(`document.querySelectorAll('li.job-card-box').length`);
    if (cards > 0) break;
    await sleep(2000);
  }
  if (!cards) { c.close(); return {applied: 'NO_CARDS', cards: 0}; }
  if (!(await waitPanel(c))) { c.close(); return {applied: 'NO_PANEL', cards}; }
  // 拟人化阅读后再操作
  await human.readDwell(5000, 15000);
  const rk1 = await riskHit(c);
  if (rk1) await emergencyStop(c, 'RISK_PAGE_SMOKE_BEFORE_APPLY', {url: rk1.url});
  const statOf = async () => {
    const st = await c.evaluate(`(() => {
      const host = document.querySelector('boss-helper-job');
      const sr = host && host.shadowRoot;
      if (!sr) return {success: null, progress: null, running: false, gone: true};
      const t = (sr.textContent || '').replace(/\\s+/g, ' ');
      const m = t.match(/今日投递:\\s*(\\d+)\\//);
      const pm = t.match(/当前页面处理:\\s*(\\d+)\\/(\\d+)/);
      const btns = Array.from(sr.querySelectorAll('button')).map(b => (b.innerText || '').trim()).filter(Boolean);
      return {success: m ? Number(m[1]) : null, progress: pm ? Number(pm[1]) : null, running: btns.includes('暂停'), gone: false};
    })()`);
    return st;
  };
  const before = {success: await panelToday(c, 6)};
  if (before.success == null) { c.close(); return {applied: 'NO_COUNTER', cards}; }
  const clicked = await humanClickShadowBtn(c, human, '开始投递');
  const click = clicked ? 'CLICKED' : 'NO_BTN';
  if (click !== 'CLICKED') { c.close(); return {applied: click, cards}; }
  let progress = 0, started = false, success = before.success;
  const startDeadline = Date.now() + 40000;
  const deadline = Date.now() + 180000;
  while (Date.now() < deadline) {
    await sleep(500);
    const st = await statOf();
    if (st.running) started = true;
    if (st.progress != null) progress = st.progress;
    if (st.success != null) success = st.success;
    if (before.success != null && success > before.success) {
      for (let k = 0; k < 3; k++) {
        await c.evaluate(`(() => { const h=document.querySelector('boss-helper-job'); const sr=h&&h.shadowRoot; if(!sr) return false; const b=Array.from(sr.querySelectorAll('button')).find(x=>(x.innerText||'').trim()==='暂停'); if(b) b.click(); return true; })()`);
        await sleep(250);
      }
      break;
    }
    if (started && !st.running) break;
    if (!started && Date.now() > startDeadline) break;
  }
  c.close();
  return {applied: 'SMOKE_DONE', cards, progress, started, successBefore: before.success, successAfter: success};
}
async function captureChatScreenshot() {
  await ensureZhipinTab('/web/geek/chat', 'https://www.zhipin.com/web/geek/chat');
  const c = await connect('zhipin.com/web/geek/chat');
  await c.send('Target.activateTarget', {targetId: c.tab.id}).catch(() => {});
  await c.send('Page.bringToFront');
  // 重新加载会话页，避免截到旧会话/旧缓存
  await c.send('Page.navigate', {url: 'https://www.zhipin.com/web/geek/chat'});
  await sleep(7000);
  let clicked = 'NO_FC';
  for (let i = 0; i < 12; i++) {
    clicked = await c.evaluate(`(() => {
      const fc = document.querySelector('.user-list-content li .friend-content');
      if (!fc) return 'NO_FC';
      fc.click();
      return 'OK';
    })()`);
    if (clicked === 'OK') break;
    await sleep(1500);
  }
  await sleep(5000);
  await c.evaluate(`(() => { const m = document.querySelector('.chat-message'); if (m) m.scrollTop = 0; return true; })()`);
  await sleep(1500);
  const info = await c.evaluate(`(() => {
    const host = document.querySelector('.chat-message') || document.querySelector('.chat-conversation');
    const text = host ? (host.innerText || '').replace(/\\s+/g, ' ').slice(0, 800) : '';
    const imgs = host ? host.querySelectorAll('img').length : 0;
    return {clicked: ${JSON.stringify(clicked)}, text, imgs};
  })()`);
  const shot = await c.send('Page.captureScreenshot', {format: 'jpeg', quality: 85}, 60000);
  const p = path.join(SHOT_DIR, 'boss_smoke_' + Date.now() + '.jpg');
  fs.writeFileSync(p, Buffer.from(shot.data, 'base64'));
  c.close();
  return {path: p, text: info.text, images: info.imgs, clicked: info.clicked};
}

async function cmdExtRead() {
  const r = await readExt();
  log('EXT', JSON.stringify(r).slice(0, 800));
}
async function cmdCountToday() {
  const r = await countToday();
  log('COUNT', JSON.stringify(r));
}
async function cmdTier(mode) {
  let company;
  if (mode === 'big4') company = {enable: true, include: true, options: [], value: COMPANIES.big4};
  else if (mode === 'big') company = {enable: true, include: true, options: [], value: COMPANIES.big};
  // mid/small 统一用「排除大厂」：白名单模式在搜索页命中率过低（18:46 实测 15 张卡全拦，公司警告×6+岗位警告×9）
  else if (mode === 'mid' || mode === 'small') company = {enable: true, include: false, options: [], value: COMPANIES.big};
  else company = {enable: false, include: true, options: [], value: []};
  // 岗位名/工作内容筛选由扩展配置维护（算法、Java、C/C++ 排除），tier 切换不再重置
  const r = await setExt({company});
  log('TIER', mode, JSON.stringify(r.company).slice(0, 200));
}
// 把桌面筛选配置 JSON 合并写入扩展（jobTitle/jobContent/额度/延迟），不改招呼语
async function cmdApplyConfig(file) {
  const cfg = JSON.parse(fs.readFileSync(file, 'utf8'));
  const c = await extSession();
  const r = await c.evaluate(`(async () => {
    const k = 'web-geek-job-FormData';
    const cur = (await chrome.storage.local.get(k))[k] || {};
    Object.assign(cur, ${JSON.stringify(cfg)});
    await chrome.storage.local.set({[k]: cur});
    return {
      jobTitle: cur.jobTitle, jobContent: cur.jobContent, deliveryLimit: cur.deliveryLimit,
      delayDeliveryStarts: cur.delayDeliveryStarts, delayDeliveryInterval: cur.delayDeliveryInterval,
      delayDeliveryPageNext: cur.delayDeliveryPageNext
    };
  })()`);
  c.close();
  log('APPLYCFG', JSON.stringify(r).slice(0, 1200));
  return r;
}
// 单条定向投递（用于指定岗位：投 1 份即停）
async function cmdOne(query, pageArg, tier) {
  const page = Number(pageArg) || 1;
  await cmdTier(tier || 'big4');
  await reloadExt();
  const extBefore = await extSuccessCount();
  const limitValue = computeDeliveryLimit(extBefore, 0, 0, 1);
  await setExt({deliveryLimit: {value: limitValue}});
  log('ONE', tier || 'big4', query, 'page=' + page, 'extBefore=' + extBefore, 'limit=' + limitValue);
  const res = await runOne(query, page);
  const extAfter = await extSuccessCount();
  const delta = (extBefore != null && extAfter != null) ? Math.max(0, extAfter - extBefore) : 0;
  log('ONE_RESULT', 'delta=' + delta, 'extAfter=' + extAfter, JSON.stringify(res));
  await setExt({deliveryLimit: {value: limitValue + 9}}).catch(() => {});
  return {delta, res};
}
// 扩展今日真实投出数（today.success）：聊天列表有延迟且部分会话无时间头，以扩展计数为统计真源
async function extSuccessCount() {
  try {
    const r = await readExt();
    return (r.today && typeof r.today.success === 'number') ? r.today.success : null;
  } catch (e) { log('WARN extSuccess failed:', e.message); return null; }
}
async function usedToday() {
  const today = ymd(new Date());
  const state = loadState();
  let chatCount = 0;
  try { const c = await countToday(); chatCount = c.todayCount || 0; }
  catch (e) { log('WARN chat count failed:', e.message); }
  const extS = await extSuccessCount();
  const st = (state[today] && state[today].applied) || 0;
  return {today, used: Math.max(chatCount, st, extS || 0), chatCount, st, extS};
}
// 按星期取当日总额度（weekdayQuota），缺省回退 dailyTotal
function dayQuota(now) {
  const q = TIERS.weekdayQuota || {};
  const v = q[String(now.getDay())];
  return (typeof v === 'number') ? v : TIERS.dailyTotal;
}
async function cmdPlan() {
  const {today, used, chatCount, st} = await usedToday();
  const dq = dayQuota(new Date());
  const totalToday = Math.max(0, Math.min(dq - used, TIERS.dailyTotal));
  const plan = planDaily(TIERS, totalToday);
  const byTier = {big: 0, mid: 0, small: 0};
  const byQuery = {};
  for (const p of plan) {
    byTier[p.tier] = (byTier[p.tier] || 0) + p.quota;
    byQuery[p.q] = (byQuery[p.q] || 0) + p.quota;
  }
  const out = {date: today, chatCount, stateApplied: st, used, totalToday, byTier, byQuery, plan};
  console.log(JSON.stringify(out, null, 2));
  log('PLAN', JSON.stringify({date: today, used, totalToday, byTier, byQuery}));
}
async function cmdDaily(capArg) {
  const now = new Date();
  const today = ymd(now);
  const state = loadState();
  log('=== DAILY START', today, 'cap=' + (capArg == null ? 'none' : capArg));

  const sync = await syncExtAssets();
  log('ASSETS', JSON.stringify(sync));
  const assets = validateAssets(sync);
  if (!assets.ok) { log('ABORT', 'greeting image missing in plugin', JSON.stringify(assets)); return; }
  // 首次 sync 后强制 reload：扩展后台可能缓存旧招呼语（曾把旧java文案发给HR）
  await reloadExt();

  const {used} = await usedToday();
  const dq = dayQuota(now);
  const totalToday = computeTotalToday(now, used, capArg);
  log('QUOTA used=' + used, 'dayQuota=' + dq, 'totalToday=' + totalToday);
  if (totalToday <= 0) {
    const msg = summarizeStop('DAILY_QUOTA_REACHED', 0, 0);
    log(msg);
    markSuspended(state, today, 'DAILY_QUOTA_REACHED', 0, 0);
    saveState(state);
    return;
  }

  const plan = planDaily(TIERS, totalToday);
  log('PLAN', JSON.stringify(plan));

  // 逐份模式：每次只投 1 份，投完强制间隔 5-10 分钟（保号优先，严禁连续点击）
  const units = [];
  for (const it of plan) for (let i = 0; i < it.quota; i++) units.push({tier: it.tier, q: it.q});
  const hcfg = TIERS.humanize || {};
  const gapMin = hcfg.perApplyGapMinSec || 300;
  const gapMax = hcfg.perApplyGapMaxSec || 600;

  let appliedTotal = 0, left = totalToday, curTier = null, captcha = false, zeroRuns = 0, limitHit = false;
  let limitReason = null;
  const pageUse = {};

  for (let ui = 0; ui < units.length; ui++) {
    if (left <= 0 || captcha || limitHit) break;
    const item = units[ui];
    if (item.tier !== curTier) { await cmdTier(item.tier); await reloadExt(); curTier = item.tier; }

    // 同一搜索词分摊到前几页，避免反复刷同一页
    const page = Math.min(5, 1 + Math.floor((pageUse[item.q] || 0) / 3));
    pageUse[item.q] = (pageUse[item.q] || 0) + 1;

    const unitNo = ui + 1;
    const capNow = 1;
    const extBefore = await extSuccessCount();
    // limit 必须以扩展自身计数为 base：扩展按「今日已投 >= limit」判停
    const limitValue = computeDeliveryLimit(extBefore, used, appliedTotal, capNow);
    await setExt({deliveryLimit: {value: limitValue}});
    log('RUN', unitNo + '/' + units.length, item.tier, item.q, 'page=' + page, 'cap=1', 'extBefore=' + extBefore, 'limit=' + limitValue);
    const runStart = hhmmNow();
    const res = await runPage(item.q, page, capNow, 10);
    // 产出统计真源：扩展 today.success 增量；聊天列表仅作回退
    const extAfter = await extSuccessCount();
    let delta = 0, deltaSrc = 'ext';
    if (extBefore != null && extAfter != null) {
      delta = Math.max(0, extAfter - extBefore);
    } else {
      deltaSrc = 'chat';
      let cntRes = null;
      try { cntRes = await countSince(runStart); }
      catch (e) { log('WARN countSince failed:', e.message); }
      delta = cntRes ? Math.min(capNow, cntRes.count || 0) : 0;
    }
    appliedTotal += delta; left -= delta;
    log('RESULT', item.tier, item.q, 'p' + page, 'delta=' + delta, 'src=' + deltaSrc, 'extAfter=' + extAfter, JSON.stringify(res));

    // 落盘当前进度，便于长间隔中断后对账
    state[today] = state[today] || {};
    state[today].applied = (state[today].applied || 0) + delta;
    state[today].usedAtStart = used;
    state[today].lastRunAt = new Date().toISOString();
    saveState(state);

    if (res.applied === 'CAPTCHA') { captcha = true; log('STOP CAPTCHA'); break; }
    if (res.applied === 'NO_CARDS' && unitNo === 1) { log('WARN NO_CARDS_FIRST'); }
    // 启动失败且扩展计数已达 limit：额度到点正常结束，不算空转
    if (res.applied === 'NOT_STARTED' && extAfter != null && extAfter >= limitValue) {
      limitHit = true; limitReason = 'EXT_LIMIT_REACHED';
      log('STOP EXT_LIMIT_REACHED', 'extAfter=' + extAfter, 'limit=' + limitValue);
      break;
    }
    if (delta === 0) {
      zeroRuns++;
      if (zeroRuns >= 2) {
        limitHit = true; limitReason = 'LIMIT_EXHAUSTED';
        log('STOP LIMIT_EXHAUSTED', 'zero delta x' + zeroRuns);
        log(summarizeStop(limitReason, appliedTotal, left));
        break;
      }
    } else zeroRuns = 0;

    // 每份之间强制长间隔；分段睡眠，期间若被封禁立即退出
    if (ui < units.length - 1 && left > 0) {
      const waitS = randInt(gapMin, gapMax);
      log('HUMAN_GAP', 'wait ' + Math.round(waitS / 60) + 'min before next unit');
      const end = Date.now() + waitS * 1000;
      while (Date.now() < end) {
        await sleep(Math.min(60000, end - Date.now()));
        const bs = banStatus();
        if (bs.banned) { log('COOLDOWN_DETECTED', '剩余' + bs.remainMin + '分钟，立即停止'); process.exit(8); }
      }
    }
  }

  await setExt({deliveryLimit: {value: TIERS.dailyTotal}}).catch(() => {});
  // applied 已在逐份循环内落盘，此处不再累加，避免重复计数
  state[today] = state[today] || {};
  state[today].usedAtStart = used;
  state[today].lastRunAt = now.toISOString();
  if (limitReason) {
    markSuspended(state, today, limitReason, appliedTotal, left);
    log(summarizeStop(limitReason, appliedTotal, left));
  }
  saveState(state);
  log('=== DAILY DONE applied=' + appliedTotal, 'left=' + left,
      limitReason ? 'suspended=' + limitReason : 'completed');
}
async function cmdSmoke() {
  const sync = await syncExtAssets();
  log('SMOKE_ASSETS', JSON.stringify(sync));
  const assets = validateAssets(sync);
  if (!assets.ok) { log('SMOKE_ABORT', 'asset sync failed', JSON.stringify(assets)); return; }
  await cmdTier('off');
  await setExt({deliveryLimit: {value: TIERS.dailyTotal}});
  await reloadExt();
  const runStart = hhmmNow();
  const res = await runOne('python 实习', 1);
  await sleep(3000);
  let delta = 0, cntRes = null;
  try { cntRes = await countSince(runStart); delta = cntRes.count || 0; } catch (e) { log('WARN count failed', e.message); }
  log('SMOKE_RUN', JSON.stringify(res), 'delta=' + delta, JSON.stringify(cntRes));
  if (res.applied === 'CAPTCHA') {
    await setExt({deliveryLimit: {value: TIERS.dailyTotal}}).catch(() => {});
    log('SMOKE_STOP', 'CAPTCHA');
    return;
  }
  const shot = await captureChatScreenshot();
  log('SMOKE_SHOT', shot.path, 'imgs=' + shot.images, 'text=' + JSON.stringify(shot.text).slice(0, 600));
  await setExt({deliveryLimit: {value: TIERS.dailyTotal}});
  log('SMOKE_DONE', JSON.stringify({delta, progress: res.progress, screenshot: shot.path}));
}

if (require.main === module) {
  (async () => {
    const cmd = process.argv[2];
    // 唯一入口闸门：封禁冷却期内任何子命令都不得执行，也不得发起任何网络请求
    assertNotBanned(cmd || 'main');
    if (cmd === 'extread') await cmdExtRead();
    else if (cmd === 'counttoday') await cmdCountToday();
    else if (cmd === 'tier') await cmdTier(process.argv[3] || 'off');
    else if (cmd === 'plan') await cmdPlan();
    else if (cmd === 'sync') log('SYNC', JSON.stringify(await syncExtAssets()));
    else if (cmd === 'smoke') await cmdSmoke();
    else if (cmd === 'applyconfig') await cmdApplyConfig(process.argv[3]);
    else if (cmd === 'one') await cmdOne(process.argv[3], process.argv[4], process.argv[5]);
    else if (cmd === 'daily') await cmdDaily(process.argv[3] == null ? null : Number(process.argv[3]));
    else if (cmd === 'panel') log('PANEL', JSON.stringify(await panelState()));
    else if (cmd === 'chatshot') { const s = await captureChatScreenshot(); log('CHATSHOT', JSON.stringify(s)); }
    else { console.log('usage: node bossctl.js extread|counttoday|tier big4|big|mid|small|off|plan|sync|smoke|daily|panel|chatshot|applyconfig <json>|one <query> <page> <tier>'); }
  })().catch(e => { log('FATAL', e.message); process.exit(1); });
}

module.exports = {
  allocate, planDaily, computeTotalToday, buildSearchUrl, validateAssets,
  computeDeliveryLimit, summarizeStop, markSuspended, dayQuota,
};
