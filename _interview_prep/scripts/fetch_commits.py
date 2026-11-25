"""Fetch commit history for the four studio repos from the public GitHub API.

Only public metadata is read (no auth). Output: cache/commits_<repo>.json
"""
import json
import os
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "cache")
REPOS = ["Fast-Https", "sqlalchemy-codegen", "Python_RESTfulAPI_Codegen", ".ncepu_ideal-skills"]
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/vnd.github+json"}


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    for repo in REPOS:
        out = os.path.join(CACHE, "commits_%s.json" % repo.replace(".", "_"))
        allc = []
        for page in (1, 2, 3):
            url = ("https://api.github.com/repos/ncepu-iDealStudio/%s/commits?per_page=100&page=%d"
                   % (urllib.parse.quote(repo), page))
            try:
                data = get(url)
            except Exception as e:  # rate limit / network
                print("%s page%d FAIL %s" % (repo, page, e))
                break
            if not data:
                break
            allc.extend(data)
            if len(data) < 100:
                break
            time.sleep(0.5)
        slim = [{
            "sha": c["sha"][:8],
            "date": c["commit"]["author"]["date"],
            "author": c["commit"]["author"]["name"],
            "msg": c["commit"]["message"].split("\n")[0],
        } for c in allc]
        with open(out, "w", encoding="utf-8") as f:
            json.dump(slim, f, ensure_ascii=False, indent=1)
        print("%s -> %d commits" % (repo, len(slim)))


if __name__ == "__main__":
    import urllib.parse
    main()
