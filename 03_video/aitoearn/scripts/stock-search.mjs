#!/usr/bin/env node
/**
 * stock-search.mjs — 免费商用素材检索（图片 / 视频）
 *
 * 用法:
 *   node stock-search.mjs --type all --q "city night" --n 8 --json
 *   node stock-search.mjs --type image --q "咖啡" --orientation portrait --n 6
 *   node stock-search.mjs --type video --q "night city" --n 4
 *
 * 输出: JSON { ok, query, results: [...], notes: [...] }
 * 依赖: Node 18+ 内置 fetch，无第三方包。
 */

const UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36';

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 1) {
    const k = argv[i];
    if (!k.startsWith('--')) continue;
    const key = k.slice(2);
    const next = argv[i + 1];
    if (!next || next.startsWith('--')) out[key] = true;
    else {
      out[key] = next;
      i += 1;
    }
  }
  return out;
}

async function get(url, as = 'text') {
  const res = await fetch(url, {
    headers: { 'User-Agent': UA, Accept: as === 'json' ? 'application/json' : '*/*' },
    signal: AbortSignal.timeout(25000),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status} ${url}`);
  return as === 'json' ? res.json() : res.text();
}

/** Openverse 返回的 URL 会带 <>、%5F 等转义，需还原成可访问直链 */
function normalizeUrl(raw) {
  if (!raw) return '';
  return raw
    .replace(/^</, '')
    .replace(/>$/, '')
    .replace(/%5F/gi, '_')
    .replace(/%28/gi, '(')
    .replace(/%29/gi, ')')
    .replace(/%2C/gi, ',');
}

async function searchImages({ q, n, orientation, notes, allowWikimedia, sources }) {
  const params = new URLSearchParams({
    q,
    page_size: '20',
    license: 'cc0,by',
    size: 'large',
  });
  if (orientation === 'portrait') params.set('aspect_ratio', 'tall');
  if (orientation === 'landscape') params.set('aspect_ratio', 'wide');
  if (sources) params.set('source', sources);

  const url = `https://api.openverse.org/v1/images/?${params.toString()}`;
  let data;
  try {
    data = await get(url, 'json');
  } catch (err) {
    notes.push(`图片检索失败：${err.message}（Openverse 匿名限流 20 次/分钟）`);
    return [];
  }

  const results = [];
  let skipped = 0;
  const blockedProviders = new Set(['wikimedia', 'stocksnap']);
  for (const item of data.results || []) {
    if (blockedProviders.has(item.provider) && !allowWikimedia) {
      skipped += 1;
      continue;
    }
    const direct = normalizeUrl(item.url);
    if (!direct) continue;
    results.push({
      type: 'image',
      title: item.title || '未命名图片',
      url: direct,
      thumb: direct,
      width: item.width || 0,
      height: item.height || 0,
      duration_s: null,
      license: (item.license || '').toUpperCase(),
      license_url: item.license_url || '',
      attribution: item.attribution || '',
      creator: item.creator || '',
      page_url: item.foreign_landing_url || '',
      provider: item.provider || item.source || 'openverse',
    });
    if (results.length >= n) break;
  }
  if (skipped) {
    notes.push(
      `已跳过 ${skipped} 条防盗链图库（Wikimedia / StockSnap），MediaKit 探测会失败。需要时加 --allow-wikimedia，并先转存到媒体库再入库。`,
    );
  }
  if (!results.length) notes.push('图片没有匹配结果，可换同义词或去掉风格词重试。');
  return results;
}

function slugify(text) {
  return String(text)
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

async function mapLimit(items, limit, fn) {
  const out = [];
  let cursor = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (cursor < items.length) {
      const index = cursor;
      cursor += 1;
      try {
        out[index] = await fn(items[index], index);
      } catch {
        out[index] = null;
      }
    }
  });
  await Promise.all(workers);
  return out;
}

function videoSlugCandidates(q) {
  const base = slugify(q);
  if (!base) return [];
  const words = base.split('-').filter((word) => word.length >= 3);
  const candidates = [base, [...words].reverse().join('-'), ...words];
  return [...new Set(candidates.filter(Boolean))];
}

async function searchVideos({ q, n, notes }) {
  const candidates = videoSlugCandidates(q);
  if (!candidates.length) {
    notes.push('视频检索需要英文关键词，已跳过。');
    return [];
  }

  let html = '';
  let slug = '';
  let pages = [];
  const linkRe = /href="(\/free-stock-video\/[a-z0-9%-]+-(\d+)\/)"/g;

  for (const candidate of candidates) {
    try {
      html = await get(`https://mixkit.co/free-stock-video/${candidate}/`);
    } catch {
      continue;
    }
    const seen = new Set();
    pages = [];
    for (const match of html.matchAll(linkRe)) {
      const [, path, id] = match;
      if (seen.has(id)) continue;
      seen.add(id);
      pages.push({ pageUrl: `https://mixkit.co${path}`, id });
      if (pages.length >= n * 3) break;
    }
    if (pages.length) {
      slug = candidate;
      break;
    }
  }
  if (!pages.length) {
    notes.push(
      `Mixkit 没有匹配分类（已尝试 ${candidates.join(' / ')}）。改用 WebSearch 找 https://mixkit.co/free-stock-video/ 下的相近分类，或换英文同义词。`,
    );
    return [];
  }

  const details = await mapLimit(pages, 4, async ({ pageUrl }) => {
    const page = await get(pageUrl);
    const mp4 = page.match(/https:\/\/assets\.mixkit\.co\/videos\/[^"\s<>]+\.mp4/);
    if (!mp4) return null;

    const og = page.match(/property="og:title" content="([^"]+)"/);
    const title = (og ? og[1] : '').replace(/\s*-\s*Free Stock Video\s*$/i, '') || '未命名视频';
    const poster = page.match(/poster="([^"]+)"/);
    const dur = page.match(/(?:Duration|duration)[^0-9]{0,120}(\d{1,2}:\d{2})/);
    let duration_s = null;
    if (dur) {
      const [m, s] = dur[1].split(':').map(Number);
      duration_s = m * 60 + s;
    }
    let best = { width: 0, height: 0 };
    for (const m of page.matchAll(/(\d{3,4})x(\d{3,4})/g)) {
      const width = Number(m[1]);
      const height = Number(m[2]);
      if (width * height > best.width * best.height) best = { width, height };
    }

    return {
      type: 'video',
      title,
      url: mp4[0],
      thumb: poster ? poster[1] : '',
      width: best.width,
      height: best.height,
      duration_s,
      license: 'Mixkit Free License',
      license_url: 'https://mixkit.co/license/#videoFree',
      attribution: '',
      creator: 'Mixkit',
      page_url: pageUrl,
      provider: 'mixkit',
    };
  });

  const results = details.filter(Boolean);
  if (!results.length) notes.push('视频详情页没有解析到 mp4 直链，换个分类或关键词。');
  return results.slice(0, n);
}

function printHuman(result) {
  const rows = result.results.map((item, index) => {
    const spec =
      item.type === 'video'
        ? `${item.width || '?'}x${item.height || '?'} ${item.duration_s ? `${item.duration_s}s` : ''}`.trim()
        : `${item.width || '?'}x${item.height || '?'}`;
    return `${index + 1}. [${item.type === 'video' ? '视频' : '图片'}] ${item.title} | ${spec} | ${item.license} | ${item.url}`;
  });
  if (!rows.length) {
    console.log('没有搜到可用素材。');
  } else {
    console.log(rows.join('\n'));
  }
  if (result.notes.length) console.log(`\n备注: ${result.notes.join('；')}`);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.q) {
    console.error('缺少 --q 关键词。示例: node stock-search.mjs --type video --q "city night" --n 6');
    process.exit(1);
  }

  const type = ['image', 'video', 'all'].includes(args.type) ? args.type : 'all';
  const n = Math.min(Math.max(Number(args.n) || 8, 1), 20);
  const orientation = ['portrait', 'landscape', 'any'].includes(args.orientation)
    ? args.orientation
    : 'any';
  const notes = [];

  let results = [];
  const allowWikimedia = Boolean(args['allow-wikimedia']);
  const sources = args.sources || 'flickr,rawpixel';
  if (type === 'image') {
    results = await searchImages({ q: args.q, n, orientation, notes, allowWikimedia, sources });
    if (!results.length && sources) {
      notes.push(`指定图库（${sources}）没有结果，已放宽到全部图库再试一次。`);
      results = await searchImages({
        q: args.q,
        n,
        orientation,
        notes,
        allowWikimedia,
        sources: '',
      });
    }
  } else if (type === 'video') {
    results = await searchVideos({ q: args.q, n, notes });
  } else {
    const half = Math.ceil(n / 2);
    const [images, videos] = await Promise.all([
      searchImages({ q: args.q, n: half, orientation, notes, allowWikimedia, sources }),
      searchVideos({ q: args.q, n: half, notes }),
    ]);
    results = [...images, ...videos];
  }

  const payload = { ok: true, query: args.q, type, count: results.length, results, notes };
  if (args.json) console.log(JSON.stringify(payload, null, 2));
  else printHuman(payload);
}

main().catch((err) => {
  console.log(JSON.stringify({ ok: false, error: err.message, results: [], notes: [] }, null, 2));
  process.exit(1);
});
