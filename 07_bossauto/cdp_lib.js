const http = require('http');

function getJson(path) {
  return new Promise((res, rej) => {
    http.get({host: '127.0.0.1', port: 9222, path}, r => {
      let d = ''; r.on('data', c => d += c); r.on('end', () => { try { res(JSON.parse(d)); } catch (e) { res(d); } });
    }).on('error', rej);
  });
}

async function connect(urlSubstr) {
  const list = await getJson('/json/list');
  const tab = list.find(t => t.type === 'page' && t.url.includes(urlSubstr));
  if (!tab) throw new Error('NO_TAB_FOR ' + urlSubstr + ' ; tabs=' + list.filter(t => t.type === 'page').map(t => t.url).join(', '));
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  let id = 0; const pending = new Map();
  const send = (method, params = {}, timeoutMs = 30000) => new Promise((resolve, reject) => {
    const i = ++id; pending.set(i, {resolve, reject});
    ws.send(JSON.stringify({id: i, method, params}));
    setTimeout(() => { if (pending.has(i)) { pending.delete(i); reject(new Error('TIMEOUT ' + method)); } }, timeoutMs);
  });
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const {resolve, reject} = pending.get(m.id); pending.delete(m.id);
      if (m.error) reject(new Error(JSON.stringify(m.error))); else resolve(m.result);
    }
  };
  await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  const evaluate = async (expr) => {
    const r = await send('Runtime.evaluate', {expression: expr, returnByValue: true, awaitPromise: true, userGesture: true});
    if (r.exceptionDetails) throw new Error('JS_ERR: ' + JSON.stringify(r.exceptionDetails).slice(0, 400));
    return r.result.value;
  };
  return {send, evaluate, close: () => ws.close(), tab};
}

module.exports = {connect, getJson};
