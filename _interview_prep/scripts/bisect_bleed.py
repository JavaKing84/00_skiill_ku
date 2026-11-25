import os
import pymupdf
from playwright.sync_api import sync_playwright

src = open('build/t1.html', encoding='utf-8').read()
variants = {
    'as_is': '',
    'padding0': '.part{padding:0 !important}',
    'boxborder': '.part{box-sizing:border-box !important}',
    'wauto': '.part{width:auto !important;height:auto !important}',
    'norelat': '.part{position:static !important}',
    'nopage': '.part{page:auto !important}',
}
with sync_playwright() as pw:
    b = pw.chromium.launch()
    for name, extra in variants.items():
        h = src.replace('</style>', extra + '</style>')
        p = 'build/v_%s.html' % name
        open(p, 'w', encoding='utf-8').write(h)
        pg = b.new_page()
        pg.goto('file:///' + os.path.abspath(p).replace('\\', '/'))
        pg.emulate_media(media='print')
        pdf = 'build/v_%s.pdf' % name
        pg.pdf(path=pdf, print_background=True, prefer_css_page_size=True)
        pg.close()
        d = pymupdf.open(pdf)
        page = d[3]
        pix = page.get_pixmap(dpi=72)
        w, h2 = pix.width, pix.height
        xs = []
        ys = []
        for y in range(0, h2, 3):
            for x in range(0, w, 3):
                i = (y * w + x) * 3
                if pix.samples[i] < 40:
                    xs.append(x)
                    ys.append(y)
        print('%-10s page=%s bbox=%s' % (name, page.rect, (min(xs), min(ys), max(xs), max(ys)) if xs else None))
        d.close()
    b.close()
