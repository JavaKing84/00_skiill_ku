// 封禁冷却闸门 + 急停守卫：所有 bossauto 脚本启动第一件事必须调用 assertNotBanned()
const fs = require('fs');
const path = require('path');

const STATE_FILE = path.join(__dirname, 'state.json');
const EMERGENCY_DIR = 'D:\\00_skiill_ku\\_logs\\bossauto';

function loadState() {
  try { return JSON.parse(fs.readFileSync(STATE_FILE, 'utf8')); } catch { return {}; }
}

// 解析本地时间字符串（不带时区按本机时区理解）
function parseLocal(s) {
  if (!s) return null;
  const d = new Date(s);
  return isNaN(d.getTime()) ? null : d;
}

// 返回 {banned:boolean, until:Date|null, remainMin:number}
function banStatus(now = new Date()) {
  const st = loadState();
  const until = parseLocal(st.banned_until);
  if (!until) return {banned: false, until: null, remainMin: 0};
  const remainMs = until.getTime() - now.getTime();
  return {banned: remainMs > 0, until, remainMin: Math.ceil(remainMs / 60000)};
}

// 封禁中直接安全退出（退出码 8），不发起任何网络请求
function assertNotBanned(tag = '') {
  const s = banStatus();
  if (s.banned) {
    const msg = '账号处于封禁冷却期，禁止运行';
    const detail = `banned_until=${s.until.toLocaleString('zh-CN', {hour12: false})} 剩余${s.remainMin}分钟${tag ? ' [' + tag + ']' : ''}`;
    console.log(msg);
    console.log(detail);
    try {
      fs.mkdirSync(EMERGENCY_DIR, {recursive: true});
      const line = '[' + new Date().toLocaleString('zh-CN', {hour12: false}) + '] COOLDOWN_BLOCK ' + detail + '\n';
      fs.appendFileSync(path.join(EMERGENCY_DIR, 'cooldown.log'), line);
    } catch (e) { /* 日志失败不阻塞退出 */ }
    process.exit(8);
  }
  return s;
}

// 判定页面是否触发风控（验证码 / 异常行为 / 封禁页）
function detectRiskPage(url, bodyText) {
  const u = String(url || '');
  const t = String(bodyText || '');
  const urlHit = /passport\/zp\/verify|security-check|exception|captcha|verify\.html/i.test(u);
  const textHit = /异常行为|操作过于频繁|账号存在风险|访问受限|请完成验证|拖动滑块|安全验证|封禁|限制访问/.test(t);
  return urlHit || textHit;
}

// 急停：截图落盘 + 写日志 + 立即退出（不刷新、不重试）
async function emergencyStop(c, reason, extra = {}) {
  try {
    fs.mkdirSync(EMERGENCY_DIR, {recursive: true});
    const ts = Date.now();
    let shotPath = null;
    if (c && c.send) {
      try {
        const shot = await c.send('Page.captureScreenshot', {format: 'jpeg', quality: 85}, 20000);
        shotPath = path.join(EMERGENCY_DIR, 'EMERGENCY_' + ts + '.jpg');
        fs.writeFileSync(shotPath, Buffer.from(shot.data, 'base64'));
      } catch (e) { /* 截图失败也要退出 */ }
    }
    const payload = {
      at: new Date().toISOString(),
      reason,
      screenshot: shotPath,
      ...extra
    };
    fs.writeFileSync(path.join(EMERGENCY_DIR, 'EMERGENCY_' + ts + '.json'), JSON.stringify(payload, null, 2));
    fs.appendFileSync(path.join(EMERGENCY_DIR, 'emergency.log'),
      '[' + new Date().toLocaleString('zh-CN', {hour12: false}) + '] EMERGENCY_STOP ' + reason + ' shot=' + (shotPath || 'none') + '\n');
    console.error('EMERGENCY_STOP ' + reason + (shotPath ? ' screenshot=' + shotPath : ''));
  } catch (e) {
    console.error('EMERGENCY_STOP(日志失败) ' + reason);
  }
  process.exit(9);
}

module.exports = {assertNotBanned, banStatus, detectRiskPage, emergencyStop, loadState, STATE_FILE};
