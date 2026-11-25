import os
import pymupdf
from playwright.sync_api import sync_playwright

base = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
@page part { size: A4; margin: 0; }
@page { size: A4; margin: 17mm 15mm 14mm 15mm; }
html,body{margin:0;padding:0}
%(extra)s
</style></head><body>
<section class="a">PART TEST</section>
<div class="b">body page</div>
</body></html>"""

variants = {
    "no_pad": "*{box-sizing:border-box}.a{page:part;width:210mm;height:297mm;background:#14161A;page-break-after:always;overflow:hidden}.b{background:#eee;height:40mm}",
    "pad_bb": "*{box-sizing:border-box}.a{page:part;width:210mm;height:297mm;padding:58mm 24mm 0;background:#14161A;page-break-after:always;overflow:hidden}.b{background:#eee;height:40mm}",
    "pad_cb": ".a{page:part;width:210mm;height:297mm;padding:58mm 24mm 0;background:#14161A;page-break-after:always;overflow:hidden}.b{background:#eee;height:40mm}",
    "width_px": "*{box-sizing:border-box}.a{page:part;width:794px;height:1123px;background:#14161A;page-break-after:always;overflow:hidden}.b{background:#eee;height:40mm}",
}

with sync_playwright() as pw:
    b = pw.chromium.launch()
    for name, extra in variants.items():
        html = base % {"extra": extra}
        p = 'build/c_%s.html' % name
        open(p, 'w', encoding='utf-8').write(html)
        pg = b.new_page()
        pg.goto('file:///' + os.path.abspath(p).replace('\\', '/'))
        pg.emulate_media(media='print')
        pdf = 'build/c_%s.pdf' % name
        pg.pdf(path=pdf, print_background=True, prefer_css_page_size=True)
        pg.close()
        d = pymupdf.open(pdf)
        pix = d[0].get_pixmap(dpi=72)
        w, h = pix.width, pix.height
        xs = []
        for y in range(0, h, 3):
            for x in range(0, w, 3):
                i = (y * w + x) * 3
                if pix.samples[i] < 40:
                    xs.append(x)
        print('%-9s page=%s dark_x=%s' % (name, (round(d[0].rect.width), round(d[0].rect.height)),
                                          (min(xs), max(xs)) if xs else None))
        d.close()
    b.close()
