import os
from playwright.sync_api import sync_playwright

url = 'file:///' + os.path.abspath('build/t2.html').replace('\\', '/')
with sync_playwright() as pw:
    b = pw.chromium.launch()
    p = b.new_page(viewport={"width": 794, "height": 1123})
    p.goto(url)
    p.emulate_media(media="print")
    info = p.evaluate("""() => {
      const res = {docScroll: document.documentElement.scrollWidth, wide: []};
      for (const el of document.querySelectorAll('body *')) {
        const r = el.getBoundingClientRect();
        if (r.width > 760 || el.scrollWidth > 780) {
          res.wide.push({tag: el.tagName, cls: (el.className||'').toString().slice(0,24),
                         w: Math.round(r.width), sw: el.scrollWidth,
                         txt: (el.textContent||'').trim().replace(/\\s+/g,' ').slice(0,48)});
        }
      }
      res.wide = res.wide.slice(0, 18);
      return res;
    }""")
    print(info['docScroll'])
    for w in info['wide']:
        print(w)
    b.close()
