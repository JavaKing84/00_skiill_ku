// CDP 层拟人化原语：贝塞尔鼠标轨迹、阅读停留滚动、逐字输入、点击前抖动
// 说明：本模块不使用 Playwright（会触发反爬空白页），全部通过原生 CDP Input 域实现

const sleep = ms => new Promise(r => setTimeout(r, ms));
const rand = (a, b) => a + Math.random() * (b - a);
const randInt = (a, b) => Math.floor(rand(a, b + 1));

// 三次贝塞尔取点
function bezier(p0, p1, p2, p3, t) {
  const u = 1 - t;
  return {
    x: u*u*u*p0.x + 3*u*u*t*p1.x + 3*u*t*t*p2.x + t*t*t*p3.x,
    y: u*u*u*p0.y + 3*u*u*t*p1.y + 3*u*t*t*p2.y + t*t*t*p3.y
  };
}

// 生成一条带随机控制点的贝塞尔轨迹
function buildPath(from, to, steps) {
  const dx = to.x - from.x, dy = to.y - from.y;
  const dist = Math.hypot(dx, dy);
  // 控制点沿垂直方向随机偏移，模拟手部弧线
  const off1 = rand(-0.35, 0.35) * Math.max(dist * 0.5, 30);
  const off2 = rand(-0.35, 0.35) * Math.max(dist * 0.5, 30);
  const nx = -dy / (dist || 1), ny = dx / (dist || 1);
  const c1 = {x: from.x + dx * 0.3 + nx * off1, y: from.y + dy * 0.3 + ny * off1};
  const c2 = {x: from.x + dx * 0.7 + nx * off2, y: from.y + dy * 0.7 + ny * off2};
  const pts = [];
  for (let i = 1; i <= steps; i++) {
    const t = i / steps;
    // 缓入缓出：中段速度快，起止慢
    const te = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
    pts.push(bezier(from, c1, c2, to, te));
  }
  return pts;
}

class Human {
  constructor(c) {
    this.c = c;
    this.pos = {x: rand(300, 700), y: rand(200, 500)};
  }

  async _move(x, y) {
    await this.c.send('Input.dispatchMouseEvent', {type: 'mouseMoved', x, y});
    this.pos = {x, y};
  }

  // 沿贝塞尔曲线移动到目标，带随机步间停顿
  async moveTo(target, opts = {}) {
    const steps = opts.steps || randInt(14, 26);
    const path = buildPath(this.pos, target, steps);
    for (const p of path) {
      await this._move(p.x, p.y);
      await sleep(rand(6, 22));
    }
    // 到位后轻微过冲回弹
    if (Math.random() < 0.5) {
      const jx = target.x + rand(-2.5, 2.5), jy = target.y + rand(-2.5, 2.5);
      await this._move(jx, jy);
      await sleep(rand(40, 120));
      await this._move(target.x, target.y);
      await sleep(rand(30, 90));
    }
  }

  // 阅读停留后点击：移动 -> 抖动 -> 停顿 -> 按下 -> 随机按住时长 -> 松开
  async click(target, opts = {}) {
    await this.moveTo(target, opts);
    // 点击前的随机微调抖动（用户要求 ≥200ms）
    const jitterTimes = randInt(2, 4);
    for (let i = 0; i < jitterTimes; i++) {
      await this._move(target.x + rand(-3, 3), target.y + rand(-3, 3));
      await sleep(rand(60, 110));
    }
    await this._move(target.x, target.y);
    await sleep(rand(200, 480));
    await this.c.send('Input.dispatchMouseEvent', {
      type: 'mousePressed', x: target.x, y: target.y, button: 'left', clickCount: 1
    });
    await sleep(rand(65, 145));
    await this.c.send('Input.dispatchMouseEvent', {
      type: 'mouseReleased', x: target.x, y: target.y, button: 'left', clickCount: 1
    });
    await sleep(rand(180, 420));
  }

  // 按 CSS 选择器点击：先把元素滚入视野，再取中心点
  async clickSelector(selector, opts = {}) {
    const box = await this.c.evaluate(`(() => {
      const el = document.querySelector(${JSON.stringify(selector)});
      if (!el) return null;
      el.scrollIntoView({block: 'center', behavior: 'instant'});
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) return null;
      return {x: r.x + r.width / 2, y: r.y + r.height / 2, w: r.width, h: r.height};
    })()`);
    if (!box) return false;
    // 点击点做少量随机偏移，避免每次都命中正中心
    const target = {
      x: box.x + rand(-box.w * 0.18, box.w * 0.18),
      y: box.y + rand(-box.h * 0.18, box.h * 0.18)
    };
    await this.click(target, opts);
    return true;
  }

  // 模拟阅读：随机停留 + 若干次上下滚动
  async readDwell(minMs = 5000, maxMs = 15000) {
    const total = rand(minMs, maxMs);
    const start = Date.now();
    let dir = 1;
    while (Date.now() - start < total) {
      const delta = dir * randInt(120, 420);
      await this.scroll(delta);
      await sleep(rand(900, 2600));
      if (Math.random() < 0.35) dir = -dir;  // 偶尔回看
    }
  }

  async scroll(deltaY, x, y) {
    const px = x != null ? x : rand(520, 900);
    const py = y != null ? y : rand(260, 520);
    await this._move(px, py);
    await this.c.send('Input.dispatchMouseEvent', {
      type: 'mouseWheel', x: px, y: py, deltaX: 0, deltaY: Math.round(deltaY)
    });
  }

  // 逐字输入：单字 150-400ms，偶尔长停顿模拟思考
  async typeText(text, opts = {}) {
    const minDelay = opts.minDelay || 150;
    const maxDelay = opts.maxDelay || 400;
    for (const ch of String(text)) {
      await this.c.send('Input.insertText', {text: ch});
      let d = rand(minDelay, maxDelay);
      if (Math.random() < 0.08) d += rand(400, 1100);  // 偶发思考停顿
      await sleep(d);
    }
  }

  // 人类式随机停手（用于动作之间）
  async pause(minMs = 800, maxMs = 2500) {
    await sleep(rand(minMs, maxMs));
  }
}

module.exports = {Human, sleep, rand, randInt};
