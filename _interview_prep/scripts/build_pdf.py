# -*- coding: utf-8 -*-
"""Interview-prep PDF builder.

Markdown-ish source in content/*.md  ->  one HTML  ->  A4 PDF via Chromium (Playwright).

Supported markup
----------------
# PART :: 标题            -> part divider page (dark)
## 1.2 标题               -> chapter heading
### 小标题                -> sub heading
- item / 1. item          -> lists
> text                    -> callout box
| a | b |                 -> table (first row = header)
```lang ... ```           -> code block
{{text}}                  -> red bold (memorisation line)
[Q] text / [A] text       -> question / answer row
[S] 来源 | 置信度          -> source line (confidence: 高/中/低/待核实)
[T] 标签文字               -> small caps label above a block
[[PAGEBREAK]]             -> hard page break
[[COLS]] ... [[/COLS]]    -> two-column block
"""
import argparse
import html
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT = os.path.join(ROOT, "content")
BUILD = os.path.join(ROOT, "build")

CONF_CLASS = {"高": "c-hi", "中": "c-mid", "低": "c-low", "待核实": "c-tbd"}

CSS = r"""
@page {
  size: A4;
  margin: 19mm 20mm 16mm 20mm;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
  font-size: %(body)spt;
  line-height: %(lh)s;
  color: #1a1c1e;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}
p { margin: 0 0 %(pgap)smm 0; text-align: justify; }
strong { font-weight: 700; }
.r { color: #D32F2F; font-weight: 700; }
.mono, code {
  font-family: Consolas, "Cascadia Mono", monospace;
  font-size: %(mono)spt;
}
code { background: #F1F2F3; padding: 0 .8mm; border-radius: .4mm; }

.cover {
  page-break-after: always;
  background: #fff;
  height: 240mm;
  padding: 24mm 0 0 0;
  position: relative;
  overflow: hidden;
}
.cover .kicker {
  font-family: Consolas, monospace; font-size: 8.4pt; letter-spacing: .3em;
  color: #D32F2F; text-transform: uppercase;
}
.cover h1 { font-size: 40pt; line-height: 1.08; margin: 6mm 0 0; letter-spacing: -.02em; font-weight: 700; }
.cover .sub { font-size: 13pt; color: #40454A; margin-top: 5mm; line-height: 1.6; }
.cover .band { margin-top: 14mm; height: 1.6pt; background: #1a1c1e; }
.cover .meta { margin-top: 7mm; font-family: Consolas, monospace; font-size: 8.2pt; line-height: 2.0; color: #40454A; }
.cover .meta b { font-family: "Microsoft YaHei"; font-weight: 700; color:#1a1c1e; display:inline-block; width: 22mm; }
.cover .note {
  position:absolute; left:0; right:0; bottom: 8mm;
  border-top: .5pt solid #C9CDD2; padding-top: 3mm;
  font-size: 7.6pt; color:#6B7075; line-height:1.7;
}
.cover .rnum {
  position:absolute; right:0; top: 0;
  font-family: Consolas, monospace; font-size: 7.6pt; color:#9AA0A6; text-align:right; line-height:1.9;
}

/* ---------- part divider ---------- */
.part {
  page-break-before: always;
  page-break-after: always;
  background: #14161A;
  color: #fff;
  height: 250mm;
  padding: 44mm 16mm 0 16mm;
  position: relative;
  overflow: hidden;
}
.part .pnum {
  font-family: Consolas, monospace;
  font-size: 9pt; letter-spacing: .34em; color: #D32F2F;
  text-transform: uppercase;
}
.part h1 {
  font-size: 27pt; line-height: 1.24; font-weight: 700;
  margin: 7mm 0 0 0; letter-spacing: -.01em; max-width: 150mm;
}
.part .pdesc {
  margin-top: 9mm; font-size: 10.5pt; line-height: 1.75;
  color: #B9BEC4; max-width: 132mm; border: none;
}
.part .prule { position:absolute; left:16mm; right:16mm; bottom:30mm; height:.3pt; background:#3A3F45; }
.part .pfoot {
  position:absolute; left:16mm; right:16mm; bottom:20mm;
  font-family: Consolas, monospace; font-size: 7.6pt; color:#6E757D;
  display:flex; justify-content:space-between;
}

/* ---------- headings ---------- */
h2 {
  font-size: 14.2pt; line-height: 1.35; font-weight: 700;
  margin: %(h2top)smm 0 %(h2bot)smm 0;
  padding-bottom: 2.1mm;
  border-bottom: .9pt solid #1a1c1e;
  page-break-after: avoid;
  letter-spacing: -.005em;
}
h2 .num { color: #D32F2F; font-family: Consolas, monospace; font-size: 10.5pt; margin-right: 2.4mm; }
h3 {
  font-size: 10.4pt; font-weight: 700; margin: %(h3top)smm 0 1.6mm 0;
  page-break-after: avoid; color: #111315;
}
h3::before { content: ""; display:block; width: 5mm; height: 1.4pt; background:#D32F2F; margin-bottom: 1.4mm; }
h4 { font-size: 9.4pt; font-weight: 700; margin: 3mm 0 1mm; page-break-after: avoid; }

/* ---------- lists ---------- */
ul, ol { margin: 0 0 %(pgap)smm 0; padding-left: 4.6mm; }
li { margin-bottom: .7mm; text-align: justify; }
ul li::marker { color: #9AA0A6; }
ol li::marker { color: #D32F2F; font-family: Consolas, monospace; font-size: 8pt; }

/* ---------- callout ---------- */
.callout {
  border: .5pt solid #C9CDD2; border-left: 2.2pt solid #1a1c1e;
  background: #FAFAFA; padding: 2.4mm 3mm; margin: 0 0 %(pgap)smm 0;
  font-size: %(calls)spt; line-height: 1.6; page-break-inside: avoid;
}
.callout p:last-child { margin-bottom: 0; }

/* ---------- q&a ---------- */
.qa { margin: 0 0 2.4mm 0; page-break-inside: avoid; }
.qa .q {
  font-weight: 700; color: #111315; margin: 0 0 .9mm 0;
  padding-left: 6.6mm; text-indent: -6.6mm;
}
.qa .q::before {
  content: "问"; font-family: "Microsoft YaHei"; font-size: 7pt; font-weight: 700;
  color: #fff; background: #1a1c1e; padding: .35mm 1.1mm; margin-right: 1.8mm;
  border-radius: .4mm;
}
.qa .a { margin: 0 0 1.1mm 0; padding-left: 0; text-align: justify; }
.qa .a::before {
  content: "答"; font-family: "Microsoft YaHei"; font-size: 7pt; font-weight: 700;
  color: #D32F2F; border: .5pt solid #D32F2F; padding: .3mm 1mm; margin-right: 1.8mm;
  border-radius: .4mm;
}

/* ---------- source line ---------- */
.src {
  font-family: Consolas, monospace; font-size: %(srcs)spt; color: #6B7075;
  margin: 1.2mm 0 3mm 0; line-height: 1.45; word-break: break-all;
}
.src .conf {
  font-family: "Microsoft YaHei"; font-weight: 700; padding: .25mm 1.2mm;
  border-radius: .5mm; margin-left: 1.6mm; white-space: nowrap;
}
.c-hi { background: #1a1c1e; color: #fff; }
.c-mid { background: #DDE0E3; color: #1a1c1e; }
.c-low { border: .5pt solid #8A9096; color: #40454A; }
.c-tbd { border: .5pt dashed #D32F2F; color: #D32F2F; }

/* ---------- table ---------- */
table {
  width: 100%%; border-collapse: collapse; margin: 1mm 0 %(pgap)smm 0;
  font-size: %(tbl)spt; line-height: 1.5;
}
thead { display: table-header-group; }
tr { page-break-inside: avoid; }
thead th {
  text-align: left; font-weight: 700; padding: 1.4mm 1.6mm;
  border-top: .9pt solid #1a1c1e; border-bottom: .5pt solid #1a1c1e;
  background: #fff;
}
tbody td { padding: 1.25mm 1.6mm; border-bottom: .3pt solid #D6D9DC; vertical-align: top; }
td, th { overflow-wrap: anywhere; }
td:first-child, th:first-child { overflow-wrap: normal; min-width: 15mm; }
tbody td:first-child { font-weight: 400; }
tbody tr:last-child td { border-bottom: .9pt solid #1a1c1e; }

/* ---------- code ---------- */
pre {
  background: #F4F5F6; border: .4pt solid #E2E4E6;
  padding: 2.2mm 2.6mm; margin: 1mm 0 %(pgap)smm 0;
  font-family: Consolas, "Cascadia Mono", monospace;
  font-size: %(codes)spt; line-height: 1.5; white-space: pre-wrap;
  overflow-wrap: anywhere; page-break-inside: auto; color: #22262A;
}

/* ---------- misc ---------- */
.tag {
  font-family: Consolas, monospace; font-size: 7.2pt; letter-spacing: .12em;
  color: #6B7075; text-transform: uppercase; margin: 3mm 0 1mm 0;
}
.cols { column-count: 2; column-gap: 7mm; column-rule: .3pt solid #E2E4E6; }
.cols p, .cols li { font-size: %(colbody)spt; }
.pb { page-break-after: always; }
.kv { font-family: Consolas, monospace; font-size: 7.6pt; color:#40454A; }
.hr { height:.3pt; background:#D6D9DC; margin: 3mm 0; }
.small { font-size: %(srcs)spt; color:#5A6067; }
.redline { border-top: .5pt solid #D32F2F; margin: 2mm 0 2.6mm; }
.card {
  border: .5pt solid #C9CDD2; padding: 2.6mm 3mm; margin: 0 0 2.6mm 0;
  page-break-inside: avoid;
}
.card .ct { font-weight: 700; margin-bottom: 1.2mm; }
.card .cn { font-family: Consolas, monospace; color:#D32F2F; font-size: 8pt; margin-right:1.6mm; }
"""


def inline(text):
    """Inline formatting: {{red}}, `code`, **bold** (bold may wrap code spans)."""
    out = []
    text = re.sub(r"\*\*(.+?)\*\*", "\x01\\1\x02", text)
    parts = re.split(r"(`[^`]+`)", text)
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) > 2:
            out.append("<code>%s</code>" % html.escape(part[1:-1]))
            continue
        esc = html.escape(part)
        esc = re.sub(r"\{\{(.+?)\}\}", r'<span class="r">\1</span>', esc)
        esc = esc.replace("\x01", "<strong>").replace("\x02", "</strong>")
        esc = esc.replace("&quot;", '"')
        out.append(esc)
    return "".join(out)


def render_table(rows):
    head = rows[0]
    body = rows[1:]
    h = ["<table><thead><tr>"]
    for c in head:
        h.append("<th>%s</th>" % inline(c))
    h.append("</tr></thead><tbody>")
    for r in body:
        h.append("<tr>")
        for c in r:
            h.append("<td>%s</td>" % inline(c))
        h.append("</tr>")
    h.append("</tbody></table>")
    return "".join(h)


def parse_blocks(lines):
    """Turn the markup into a list of (kind, payload) blocks."""
    blocks = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].rstrip("\n")
        s = line.strip()
        if not s:
            i += 1
            continue
        if s == "[[COVER]]":
            buf = []
            i += 1
            while i < n and lines[i].strip() != "[[/COVER]]":
                buf.append(lines[i].strip()); i += 1
            i += 1
            blocks.append(("cover", buf)); continue
        if s == "[[PAGEBREAK]]":
            blocks.append(("pb", None)); i += 1; continue
        if s == "[[COLS]]":
            buf = []
            i += 1
            while i < n and lines[i].strip() != "[[/COLS]]":
                buf.append(lines[i]); i += 1
            i += 1
            blocks.append(("cols", buf)); continue
        if s.startswith("```"):
            lang = s[3:].strip()
            buf = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                buf.append(lines[i].rstrip("\n")); i += 1
            i += 1
            blocks.append(("code", (lang, buf))); continue
        if s.startswith("|") and s.endswith("|"):
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                raw = lines[i].strip().strip("|")
                cells = [c.strip() for c in raw.split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            if rows:
                blocks.append(("table", rows))
            continue
        if s.startswith("[Q] "):
            blocks.append(("q", s[4:].strip())); i += 1; continue
        if s.startswith("[A] "):
            blocks.append(("a", s[4:].strip())); i += 1; continue
        if s.startswith("[S] "):
            blocks.append(("src", s[4:].strip())); i += 1; continue
        if s.startswith("[T] "):
            blocks.append(("tag", s[4:].strip())); i += 1; continue
        if s == "[HR]":
            blocks.append(("hr", None)); i += 1; continue
        if s.startswith("# "):
            blocks.append(("part", s[2:].strip())); i += 1; continue
        if s.startswith("## "):
            blocks.append(("h2", s[3:].strip())); i += 1; continue
        if s.startswith("### "):
            blocks.append(("h3", s[4:].strip())); i += 1; continue
        if s.startswith("#### "):
            blocks.append(("h4", s[5:].strip())); i += 1; continue
        if s.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip()); i += 1
            blocks.append(("callout", buf)); continue
        if re.match(r"^[-*] ", s):
            buf = []
            while i < n and re.match(r"^[-*] ", lines[i].strip()):
                buf.append(lines[i].strip()[2:]); i += 1
            blocks.append(("ul", buf)); continue
        if re.match(r"^\d+\. ", s):
            buf = []
            while i < n and re.match(r"^\d+\. ", lines[i].strip()):
                buf.append(re.sub(r"^\d+\. ", "", lines[i].strip())); i += 1
            blocks.append(("ol", buf)); continue
        # paragraph: consume until blank / block start
        buf = [s]
        i += 1
        while i < n:
            t = lines[i].strip()
            if (not t or t.startswith(("#", ">", "|", "```", "[Q] ", "[A] ", "[S] ",
                                       "[T] ", "[[", "[HR]")) or re.match(r"^[-*] ", t)
                    or re.match(r"^\d+\. ", t)):
                break
            buf.append(t)
            i += 1
        blocks.append(("p", " ".join(buf)))
    return blocks


def render(blocks, counters):
    out = []
    for kind, payload in blocks:
        if kind == "cover":
            kicker = payload[0] if len(payload) > 0 else ""
            title = payload[1] if len(payload) > 1 else ""
            sub = payload[2] if len(payload) > 2 else ""
            meta = payload[3:]
            out.append('<section class="cover"><div class="kicker">%s</div><h1>%s</h1>'
                       '<div class="sub">%s</div><div class="band"></div>'
                       '<div class="meta">%s</div>'
                       '<div class="note">%s</div></section>' % (
                           inline(kicker), inline(title), inline(sub),
                           "".join(inline(m) + "<br>" for m in meta if "::" not in m),
                           inline(" ".join(m.split("::", 1)[1].strip() for m in meta if "::" in m))))
        elif kind == "part":
            segs = [x.strip() for x in payload.split("::")]
            num = segs[0] if len(segs) > 0 else ""
            title = segs[1] if len(segs) > 1 else ""
            desc = segs[2] if len(segs) > 2 else ""
            counters["part"] += 1
            out.append('<section class="part"><div class="pnum">%s</div><h1>%s</h1>'
                       '<div class="pdesc">%s</div>'
                       '<div class="prule"></div><div class="pfoot"><span>马曦晨 · 面试准备 · 内部材料</span>'
                       '<span>%s</span></div></section>' % (
                           html.escape(num), inline(title), inline(desc), html.escape(num)))
        elif kind == "h2":
            m = re.match(r"^([\d.]+)\s+(.*)$", payload)
            if m:
                counters["h2n"] += 1
                out.append('<h2><span class="num">%s</span>%s</h2>' % (m.group(1), inline(m.group(2))))
            else:
                out.append("<h2>%s</h2>" % inline(payload))
        elif kind == "h3":
            out.append("<h3>%s</h3>" % inline(payload))
        elif kind == "h4":
            out.append("<h4>%s</h4>" % inline(payload))
        elif kind == "p":
            out.append("<p>%s</p>" % inline(payload))
        elif kind == "ul":
            out.append("<ul>%s</ul>" % "".join("<li>%s</li>" % inline(x) for x in payload))
        elif kind == "ol":
            out.append("<ol>%s</ol>" % "".join("<li>%s</li>" % inline(x) for x in payload))
        elif kind == "callout":
            out.append('<div class="callout">%s</div>'
                       % "".join("<p>%s</p>" % inline(x) for x in payload if x))
        elif kind == "table":
            out.append(render_table(payload))
        elif kind == "code":
            lang, buf = payload
            out.append('<pre data-lang="%s">%s</pre>' % (html.escape(lang), html.escape("\n".join(buf))))
        elif kind == "q":
            out.append('<div class="qa"><div class="q">%s</div>' % inline(payload))
        elif kind == "a":
            out.append('<div class="a">%s</div></div>' % inline(payload))
        elif kind == "src":
            segs = [x.strip() for x in payload.split("|")]
            url = segs[0] if segs else ""
            conf = segs[1] if len(segs) > 1 else "中"
            extra = (" · ".join(segs[2:])) if len(segs) > 2 else ""
            cls = CONF_CLASS.get(conf, "c-mid")
            out.append('<div class="src">来源 %s%s%s</div>' % (
                inline(url),
                ' · <span class="small">%s</span>' % html.escape(extra) if extra else "",
                ' <span class="conf %s">%s</span>' % (cls, html.escape(conf))))
        elif kind == "tag":
            out.append('<div class="tag">%s</div>' % inline(payload))
        elif kind == "hr":
            out.append('<div class="hr"></div>')
        elif kind == "pb":
            out.append('<div class="pb"></div>')
        elif kind == "cols":
            inner = render(parse_blocks(payload), {"part": 0, "h2n": 0})
            out.append('<div class="cols">%s</div>' % inner)
    return "".join(out)


def build(files, scale, out_html):
    body = []
    counters = {"part": 0, "h2n": 0}
    for f in files:
        with open(f, encoding="utf-8") as fh:
            body.append(render(parse_blocks(fh.read().split("\n")), counters))
    css = CSS % {
        "body": round(10.4 * scale, 2),
        "lh": round(1.82, 2),
        "mono": round(9.2 * scale, 2),
        "codes": round(8.5 * scale, 2),
        "tbl": round(9.0 * scale, 2),
        "srcs": 7.0,
        "calls": round(9.5 * scale, 2),
        "colbody": round(9.4 * scale, 2),
        "pgap": round(2.6 * scale, 2),
        "h2top": 6.4,
        "h2bot": 3.0,
        "h3top": 4.4,
    }
    doc = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>面试准备 · 马曦晨</title><style>%s</style></head><body>%s</body></html>""" % (css, "".join(body))
    with open(out_html, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return doc


def stamp(path, doc_title="马曦晨 · 面试准备 · 内部材料", date_str="2026-11-25"):
    """Draw running head (chapter name) and footer (page no + owner) on every body page."""
    import pymupdf as fitz
    d = fitz.open(path)
    W, H = d[0].rect.width, d[0].rect.height
    font = "C:/Windows/Fonts/simhei.ttf"
    ink = (0.10, 0.11, 0.12)
    grey = (0.42, 0.44, 0.46)
    red = (0.827, 0.184, 0.184)
    chapter = ""
    total = d.page_count
    for idx, page in enumerate(d):
        pix = page.get_pixmap(clip=fitz.Rect(150, 300, 172, 322))
        dark = bool(pix.samples) and sum(pix.samples[:3]) < 240
        if dark or idx == 0:
            continue
        # chapter title = first line containing a span >= 13pt on this page
        found = None
        for blk in page.get_text("dict")["blocks"]:
            for line in blk.get("lines", []):
                spans = [s["text"].strip() for s in line.get("spans", []) if s["text"].strip()]
                if any(s["size"] >= 13 for s in line.get("spans", [])) and spans:
                    found = " ".join(spans)
                    break
            if found:
                break
        if found:
            chapter = found
        head = chapter if chapter else "面试准备"
        if len(head) > 34:
            head = head[:33] + "…"
        page.insert_font(fontname="cjk", fontfile=font)
        L, R = 56.7, W - 56.7
        page.insert_text((L, 38), head, fontname="cjk", fontsize=7.4, color=grey)
        page.insert_text((R - len(doc_title) * 7.4 * 0.52, 38), "马曦晨 · 面试准备",
                         fontname="cjk", fontsize=7.4, color=grey)
        page.draw_line(fitz.Point(L, 43), fitz.Point(R, 43), color=(0.82, 0.84, 0.85), width=0.4)
        # footer
        page.insert_text((L, H - 30), doc_title, fontname="cjk", fontsize=7.2, color=grey)
        num = "%d / %d" % (idx + 1, total)
        page.insert_text((R - len(num) * 7.2 * 0.5, H - 30), num, fontname="cjk", fontsize=7.2, color=ink)
        page.draw_line(fitz.Point(L, H - 37), fitz.Point(R, H - 37), color=(0.82, 0.84, 0.85), width=0.4)
        page.draw_rect(fitz.Rect(L, H - 37, L + 10, H - 36.4), color=None, fill=red)
    d.saveIncr()
    d.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--out", default=os.path.join(BUILD, "interview_prep.html"))
    ap.add_argument("--pdf", default="")
    ap.add_argument("--only", default="")
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    files = sorted(os.path.join(CONTENT, f) for f in os.listdir(CONTENT)
                   if f.endswith(".md") and not f.startswith("_"))
    if args.only:
        keys = args.only.split(",")
        files = [f for f in files if any(k in os.path.basename(f) for k in keys)]
    os.makedirs(BUILD, exist_ok=True)
    doc = build(files, args.scale, args.out)
    print("html chars=%d -> %s" % (len(doc), args.out))

    if args.stats:
        red = len(re.findall(r'class="r"', doc))
        print("red marks=%d" % red)
        print("files=%s" % [os.path.basename(f) for f in files])

    if args.pdf:
        from playwright.sync_api import sync_playwright
        url = "file:///" + os.path.abspath(args.out).replace("\\", "/")
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            page = b.new_page()
            page.goto(url, wait_until="load")
            page.emulate_media(media="print")
            page.pdf(path=args.pdf, print_background=True,
                     display_header_footer=False, prefer_css_page_size=True)
            b.close()
        print("pdf ->", args.pdf)
        stamp(args.pdf)
        try:
            import pymupdf
            d = pymupdf.open(args.pdf)
            print("pages=%d" % d.page_count)
        except Exception as e:
            print("page count failed:", e)


if __name__ == "__main__":
    main()
