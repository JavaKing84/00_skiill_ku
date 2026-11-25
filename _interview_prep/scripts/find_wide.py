import os
from playwright.sync_api import sync_playwright

url = 'file:///' + os.path.abspath('build/t1.html').replace('\\', '/')
with sync_playwright() as pw:
    b = pw.chromium.launch()
    p = b.new_page(viewport={"width": 1280, "height": 900})
    p.goto(url)
    p.emulate_media(media="print")
    info = p.evaluate("""() => {
      const out = {bodyScroll: document.body.scrollWidth, docScroll: document.documentElement.scrollWidth,
                   bodyClient: document.body.clientWidth, wide: []};
      const all = document.querySelectorAll('*');
      for (const el of all) {
        if (el.scrollWidth > 820 || el.offsetWidth > 820) {
          out.wide.push({tag: el.tagName, cls: el.className && el.className.toString().slice(0,30),
                         ow: el.offsetWidth, sw: el.scrollWidth, txt: (el.textContent||'').trim().slice(0,40)});
        }
        if (out.wide.length > 14) break;
      }
      return out;
    }""")
    print(info)
    b.close()
