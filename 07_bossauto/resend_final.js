// 正式批量补发：只给"已发招呼语但无简历图片"的今日会话补发压缩简历图
const {connect} = require('./cdp_lib');
const fs = require('fs');
const path = require('path');
const sleep = ms => new Promise(r => setTimeout(r, ms));

const IMG = path.join(__dirname, 'assets', 'resume_small.jpg');
const LOG = path.join(__dirname, 'resend.log');
const REPORT = 'D:\\00_skiill_ku\\_logs\\bossauto\\resend_final.json';

function log(...a) {
  const line = '[' + new Date().toLocaleString('zh-CN', {hour12: false}) + '] ' + a.join(' ');
  console.log(line); fs.appendFileSync(LOG, line + '\n');
}

const READ = `(() => {
  const host = document.querySelector('.chat-message');
  if (!host) return {err: 'NO_HOST'};
  const mine = Array.from(host.querySelectorAll('.item-myself'));
  let imgs = host.querySelectorAll('img.message-image').length;
  let text = '';
  for (const m of mine) {
    const t = (m.innerText || '').replace(/\\s+/g, ' ').trim();
    if (t && !text) text = t;
  }
  return {mineCount: mine.length, imgs, text};
})()`;

(async () => {
  const c = await connect('zhipin.com/web/geek/chat');
  await c.send('Page.bringToFront');
  await c.send('DOM.enable');

  // 采集今日会话名单（行首 HH:MM）
  const convs = await c.evaluate(`(() => {
    return Array.from(document.querySelectorAll('.user-list-content li')).map((li, i) => {
      const t = (li.innerText || '').replace(/\\s+/g, ' ').trim();
      const m = t.match(/^(\\d{1,2}:\\d{2})/);
      return {i, time: m ? m[1] : '', key: t.replace(/^\\d{1,2}:\\d{2}\\s*/, '').replace(/\\s*(送达|已读|\\[图片\\])\\s*/g, '').trim().slice(0, 26)};
    }).filter(x => x.time);
  })()`);
  log('=== FINAL RESEND START candidates=' + convs.length);

  const results = [];
  for (const cv of convs) {
    // 重新定位（列表会因新消息重排）
    const found = await c.evaluate(`(() => {
      const key = ${JSON.stringify(cv.key)};
      const items = Array.from(document.querySelectorAll('.user-list-content li'));
      const pick = li => (li.innerText||'').replace(/\\s+/g,' ').trim().replace(/^\\d{1,2}:\\d{2}\\s*/,'').replace(/\\s*(送达|已读|\\[图片\\])\\s*/g,'').trim();
      const li = items.find(x => pick(x).includes(key));
      if (!li) return 'NOT_FOUND';
      (li.querySelector('.friend-content') || li).click();
      return 'OK';
    })()`);
    if (found !== 'OK') { log('MISS', cv.key); results.push({...cv, state: 'NOT_FOUND'}); continue; }
    await sleep(3200);

    const st = await c.evaluate(READ);
    const greetingOk = /华北电力大学|熟悉python和go/i.test(st.text || '');
    if (st.imgs > 0) { log('SKIP_HAS_IMG', cv.key, 'imgs=' + st.imgs); results.push({...cv, state: 'HAS_IMG'}); continue; }
    if (!greetingOk) { log('SKIP_NO_GREETING', cv.key, '|', (st.text||'').slice(0, 20)); results.push({...cv, state: 'NO_GREETING'}); continue; }

    const doc = await c.send('DOM.getDocument', {depth: -1});
    const q = await c.send('DOM.querySelector', {nodeId: doc.root.nodeId, selector: '.btn-sendimg input[type="file"]'});
    if (!q.nodeId) { log('FAIL_NO_INPUT', cv.key); results.push({...cv, state: 'NO_INPUT'}); continue; }
    await c.send('DOM.setFileInputFiles', {files: [IMG], nodeId: q.nodeId});
    await sleep(2500);

    const rect = await c.evaluate(`(() => {
      const b = document.querySelector('.btn-v2.btn-sure-v2.btn-send');
      if (!b || b.offsetParent === null) return null;
      const r = b.getBoundingClientRect();
      return {x: r.x + r.width/2, y: r.y + r.height/2};
    })()`);
    if (!rect) { log('FAIL_NO_BTN', cv.key); results.push({...cv, state: 'NO_SEND_BTN'}); continue; }

    await c.send('Input.dispatchMouseEvent', {type: 'mousePressed', x: rect.x, y: rect.y, button: 'left', clickCount: 1});
    await sleep(90);
    await c.send('Input.dispatchMouseEvent', {type: 'mouseReleased', x: rect.x, y: rect.y, button: 'left', clickCount: 1});

    // 等上传完成
    let ok = false, last = null;
    for (let k = 0; k < 10; k++) {
      await sleep(2500);
      last = await c.evaluate(`(() => {
        const h = document.querySelector('.chat-message');
        return {
          imgs: h ? h.querySelectorAll('img.message-image').length : 0,
          loading: h ? h.querySelectorAll('.loading, [class*=loading]').length : 0
        };
      })()`);
      if (last.imgs > st.imgs && last.loading === 0) { ok = true; break; }
    }
    log(ok ? 'SENT_OK' : 'SENT_FAIL', cv.key, 'imgs', st.imgs, '->', last ? last.imgs : '?', 'loading=' + (last ? last.loading : '?'));
    results.push({...cv, state: ok ? 'SENT_OK' : 'FAILED', imgs: last ? last.imgs : null});
    await sleep(2200 + Math.floor(Math.random() * 1500));
  }

  const okN = results.filter(r => r.state === 'SENT_OK').length;
  const failN = results.filter(r => r.state === 'FAILED').length;
  log('=== FINAL DONE sent=' + okN, 'failed=' + failN, 'total=' + results.length);
  fs.writeFileSync(REPORT, JSON.stringify(results, null, 2));
  c.close();
})().catch(e => { log('ERR', e.message); process.exit(1); });
