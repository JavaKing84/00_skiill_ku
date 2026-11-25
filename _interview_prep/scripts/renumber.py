"""Renumber `## X.Y` headings inside each content file so they run 1..N."""
import os
import re
import sys

CONTENT = r"D:\00_skiill_ku\_interview_prep\content"


def renumber(path):
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    n = 0
    changed = 0
    major = None
    for i, line in enumerate(lines):
        m = re.match(r"^## (\d+)\.(\d+)\s+(.*)$", line)
        if not m:
            continue
        major = m.group(1)
        n += 1
        new = "## %s.%d %s" % (major, n, m.group(3))
        if new != line:
            lines[i] = new
            changed += 1
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return n, changed


if __name__ == "__main__":
    for name in sorted(os.listdir(CONTENT)):
        if not name.endswith(".md"):
            continue
        n, c = renumber(os.path.join(CONTENT, name))
        print("%-22s headings=%d changed=%d" % (name, n, c))
