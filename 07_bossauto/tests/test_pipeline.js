// 07_bossauto 最小链路测试（不连 Chrome、不投递）
// 覆盖：额度分配 → 搜索计划 → 搜索 URL → 资产闸门 → deliveryLimit → 额度用尽挂起
// 运行：node --test tests/test_pipeline.js
const test = require('node:test');
const assert = require('node:assert');
const path = require('path');

const b = require(path.join(__dirname, '..', 'bossctl.js'));
const TIERS = require(path.join(__dirname, '..', 'tiers.json'));

const GREETING = '您好，我是华北电力大学(211)28届毕业生。熟悉python和go语言开发，希望能长期实习。';

test('allocate: 配额按权重分配且总数守恒', () => {
  const out = b.allocate({mid: 75, small: 65}, 14);
  const sum = out.reduce((s, x) => s + x.n, 0);
  assert.strictEqual(sum, 14);
  assert.ok(out.every(x => x.n >= 0));
});

test('planDaily: 只产出 mid/small，且配额总数等于目标', () => {
  const plan = b.planDaily(TIERS, 12);
  assert.ok(plan.length > 0);
  assert.ok(plan.every(p => p.tier === 'mid' || p.tier === 'small'));
  assert.ok(plan.every(p => p.q && p.quota > 0));
  assert.strictEqual(plan.reduce((s, p) => s + p.quota, 0), 12);
});

test('dayQuota: 星期额度与周末 0 生效', () => {
  assert.strictEqual(b.dayQuota(new Date(2026, 10, 23)), 100); // 周一
  assert.strictEqual(b.dayQuota(new Date(2026, 10, 25)), 140); // 周三
  assert.strictEqual(b.dayQuota(new Date(2026, 10, 27)), 70);  // 周五
  assert.strictEqual(b.dayQuota(new Date(2026, 10, 28)), 0);   // 周六
});

test('computeTotalToday: 受星期额度、dailyTotal、批次 cap 三重约束', () => {
  const wed = new Date(2026, 10, 25); // 140
  assert.strictEqual(b.computeTotalToday(wed, 10, 20), 20);
  assert.strictEqual(b.computeTotalToday(wed, 135, null), 5);
  assert.strictEqual(b.computeTotalToday(wed, 200, null), 0);
  const fri = new Date(2026, 10, 27); // 70
  assert.strictEqual(b.computeTotalToday(fri, 10, null), 60);
});

test('buildSearchUrl: 搜索词编码、城市与页码正确', () => {
  const url = b.buildSearchUrl('python 实习', 2);
  assert.ok(url.startsWith('https://www.zhipin.com/web/geek/jobs?query='));
  assert.ok(url.includes('python%E5%AE%9E%E4%B9%A0'));
  assert.ok(!url.includes('python 实习'));
  assert.ok(url.includes('city=101010100'));
  assert.ok(url.endsWith('page=2'));
});

test('validateAssets: 只要求简历图存在（招呼语由扩展设置，wrapper 校验）', () => {
  assert.deepStrictEqual(b.validateAssets({greeting: '旧java文案', imgOk: true}),
    {ok: true, greetingOk: true, imgOk: true});
  assert.strictEqual(b.validateAssets({imgOk: false}).ok, false);
  assert.strictEqual(b.validateAssets(null).ok, false);
});

test('computeDeliveryLimit: 以扩展今日已投为 base，不按本批 cap 重置', () => {
  assert.strictEqual(b.computeDeliveryLimit(8, 5, 1, 3), 11);
  assert.strictEqual(b.computeDeliveryLimit(null, 5, 1, 3), 9);
});

test('summarizeStop: 额度用尽时输出安全挂起语义', () => {
  const msg = b.summarizeStop('LIMIT_EXHAUSTED', 1, 20);
  assert.ok(msg.includes('今日沟通额度已达上限'));
  assert.ok(msg.includes('已成功投递 1 份'));
  assert.ok(msg.includes('安全挂起'));
  assert.ok(msg.includes('等待明日重置'));
  assert.ok(msg.includes('LIMIT_EXHAUSTED'));
});

test('markSuspended: 状态文件记录挂起原因与恢复提示', () => {
  const state = {};
  b.markSuspended(state, '2026-11-24', 'LIMIT_EXHAUSTED', 3, 18);
  const s = state['2026-11-24'].suspended;
  assert.strictEqual(s.reason, 'LIMIT_EXHAUSTED');
  assert.strictEqual(s.applied, 3);
  assert.strictEqual(s.left, 18);
  assert.strictEqual(s.resume, '等待明日重置');
  assert.ok(s.at);
});

test('端到端（离线）：计划 → 搜索 URL → 额度用尽不崩溃', () => {
  const plan = b.planDaily(TIERS, 5);
  const first = plan[0];
  const url = b.buildSearchUrl(first.q, 1);
  assert.ok(url.includes('zhipin.com/web/geek/jobs'));
  assert.ok(first.q.includes('实习'));

  const assets = b.validateAssets({greeting: GREETING, imgOk: true});
  assert.ok(assets.ok);
  const limit = b.computeDeliveryLimit(8, 5, 0, first.quota);
  assert.ok(limit > 8);

  const state = {};
  b.markSuspended(state, '2026-11-24', 'LIMIT_EXHAUSTED', 1, 4);
  assert.strictEqual(state['2026-11-24'].suspended.applied, 1);
  assert.strictEqual(state['2026-11-24'].suspended.left, 4);
});
