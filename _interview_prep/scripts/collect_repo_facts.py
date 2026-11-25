"""Collect structural facts from the four cloned studio repos into one fact sheet."""
import os
import re
from collections import Counter

ROOT = r"D:\00_skiill_ku\_interview_prep\repos"
OUT = r"D:\00_skiill_ku\_interview_prep\cache\repo_facts.txt"

lines = []


def w(s=""):
    lines.append(s)


def head(t):
    w("")
    w("=" * 78)
    w(t)
    w("=" * 78)


def tree(base, maxdepth=2):
    base = os.path.abspath(base)
    for root, dirs, files in os.walk(base):
        rel = os.path.relpath(root, base)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        if depth > maxdepth:
            dirs[:] = []
            continue
        keep = [d for d in dirs if d not in {".git", "__pycache__", "node_modules", ".idea"}]
        dirs[:] = keep
        pad = "  " * depth
        w("%s%s/ (%d files)" % (pad, os.path.basename(root) if rel != "." else ".", len(files)))
        for f in sorted(files)[:14]:
            w("%s  %s" % (pad, f))


def count_ext(base, exts):
    c = Counter()
    loc = Counter()
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "node_modules", "dist", "build"}]
        for f in files:
            e = os.path.splitext(f)[1].lower()
            if e in exts:
                c[e] += 1
                try:
                    with open(os.path.join(root, f), encoding="utf-8", errors="ignore") as fh:
                        loc[e] += sum(1 for _ in fh)
                except OSError:
                    pass
    return c, loc


# ---------- Fast-Https ----------
fh = os.path.join(ROOT, "Fast-Https")
head("Fast-Https / line counts")
c, loc = count_ext(fh, {".go", ".md", ".json", ".html", ".js", ".vue", ".css", ".ts", ".ps1"})
for e in c:
    w("%-6s files=%-4d loc=%d" % (e, c[e], loc[e]))

head("Fast-Https / package line counts (non-test)")
for pkg in ["cmd", "config", "core", "init", "runtime", "modules", "infra", "monitor", "management"]:
    p = os.path.join(fh, pkg)
    if not os.path.isdir(p):
        continue
    n = 0
    tst = 0
    for root, dirs, files in os.walk(p):
        for f in files:
            if f.endswith(".go"):
                with open(os.path.join(root, f), encoding="utf-8", errors="ignore") as fh2:
                    k = sum(1 for _ in fh2)
                if f.endswith("_test.go"):
                    tst += k
                else:
                    n += k
    w("%-14s code=%-6d test=%d" % (pkg, n, tst))

head("Fast-Https / request parse.go signatures")
p = os.path.join(fh, "runtime", "request", "parse.go")
if os.path.exists(p):
    with open(p, encoding="utf-8", errors="ignore") as f:
        src = f.read()
    for m in re.finditer(r"^func .*$", src, re.M):
        w(m.group(0)[:120])
    w("-- total lines: %d" % src.count("\n"))

head("Fast-Https / server.go signatures")
p = os.path.join(fh, "runtime", "server", "server.go")
if os.path.exists(p):
    with open(p, encoding="utf-8", errors="ignore") as f:
        src = f.read()
    for m in re.finditer(r"^(type|func) .*$", src, re.M):
        w(m.group(0)[:120])
    w("-- total lines: %d" % src.count("\n"))

head("Fast-Https / proxy pool.go signatures")
p = os.path.join(fh, "modules", "proxy", "pool.go")
if os.path.exists(p):
    with open(p, encoding="utf-8", errors="ignore") as f:
        src = f.read()
    for m in re.finditer(r"^(type|func) .*$", src, re.M):
        w(m.group(0)[:120])
    w("-- total lines: %d" % src.count("\n"))

head("Fast-Https / listener reload.go")
p = os.path.join(fh, "runtime", "listener", "reload.go")
if os.path.exists(p):
    with open(p, encoding="utf-8", errors="ignore") as f:
        src = f.read()
    for m in re.finditer(r"^(type|func) .*$", src, re.M):
        w(m.group(0)[:120])
    w("-- total lines: %d" % src.count("\n"))

head("Fast-Https / cache.go signatures")
p = os.path.join(fh, "modules", "cache", "cache.go")
if os.path.exists(p):
    with open(p, encoding="utf-8", errors="ignore") as f:
        src = f.read()
    for m in re.finditer(r"^(type|func) .*$", src, re.M):
        w(m.group(0)[:120])
    w("-- total lines: %d" % src.count("\n"))

head("Fast-Https / go test files count")
c, _ = count_ext(fh, {".go"})
tests = 0
for root, dirs, files in os.walk(fh):
    tests += sum(1 for f in files if f.endswith("_test.go"))
w("go files=%d, _test.go=%d" % (c[".go"], tests))

# ---------- sqlalchemy-codegen ----------
sc = os.path.join(ROOT, "sqlalchemy-codegen")
head("sqlalchemy-codegen / tree")
tree(sc, 3)
head("sqlalchemy-codegen / loc")
c, loc = count_ext(sc, {".py", ".md", ".txt", ".cfg"})
for e in c:
    w("%-6s files=%-4d loc=%d" % (e, c[e], loc[e]))
head("sqlalchemy-codegen / main.py")
p = os.path.join(sc, "codegen", "main.py")
if os.path.exists(p):
    with open(p, encoding="utf-8", errors="ignore") as f:
        src = f.read()
    w("lines=%d" % src.count("\n"))
    for m in re.finditer(r"^(def |class |\s*parser\.add_argument)\(?.*$", src, re.M):
        w(m.group(0).strip()[:130])
head("sqlalchemy-codegen / requirements")
p = os.path.join(sc, "requirements.txt")
if os.path.exists(p):
    w(open(p, encoding="utf-8", errors="ignore").read())

# ---------- Python_RESTfulAPI_Codegen ----------
pc = os.path.join(ROOT, "Python_RESTfulAPI_Codegen")
head("Python_RESTfulAPI_Codegen / tree")
tree(pc, 2)
head("Python_RESTfulAPI_Codegen / loc")
c, loc = count_ext(pc, {".py", ".html", ".js", ".css", ".md", ".txt", ".yml"})
for e in c:
    w("%-6s files=%-4d loc=%d" % (e, c[e], loc[e]))
head("Python_RESTfulAPI_Codegen / codegenerate subdirs")
p = os.path.join(pc, "codegenerate")
if os.path.isdir(p):
    for d in sorted(os.listdir(p)):
        dp = os.path.join(p, d)
        if os.path.isdir(dp):
            fs = os.listdir(dp)
            w("%-22s %d files: %s" % (d, len(fs), ", ".join(sorted(fs)[:8])))
    for f in sorted(os.listdir(p)):
        if f.endswith(".py"):
            w("file %s" % f)
head("Python_RESTfulAPI_Codegen / requirements")
p = os.path.join(pc, "requirements.txt")
if os.path.exists(p):
    w(open(p, encoding="utf-8", errors="ignore").read())
head("Python_RESTfulAPI_Codegen / LICENSE head")
p = os.path.join(pc, "LICENSE")
if os.path.exists(p):
    w(open(p, encoding="utf-8", errors="ignore").read()[:400])
head("Python_RESTfulAPI_Codegen / tests")
p = os.path.join(pc, "tests")
if os.path.isdir(p):
    for f in os.listdir(p):
        w(f)

# ---------- skills ----------
sk = os.path.join(ROOT, ".ncepu_ideal-skills")
head("skills / top dirs")
for d in sorted(os.listdir(sk)):
    dp = os.path.join(sk, d)
    if os.path.isdir(dp) and d != ".git":
        subs = [x for x in os.listdir(dp) if os.path.isdir(os.path.join(dp, x))]
        w("%-42s subdirs=%d" % (d, len(subs)))
        for s in sorted(subs)[:12]:
            w("    - %s" % s)
head("skills / SKILL.md count")
n = 0
cats = Counter()
for root, dirs, files in os.walk(sk):
    if "SKILL.md" in files:
        n += 1
        rel = os.path.relpath(root, sk).split(os.sep)
        cats[rel[0]] += 1
w("total SKILL.md = %d" % n)
for k, v in cats.most_common():
    w("%-42s %d" % (k, v))

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("written", OUT, len(lines), "lines")
