"""_shared/secret_scan.py — 提交前敏感信息扫描。

用法：
    python _shared/secret_scan.py            # 扫描 Git 暂存区（pre-commit 钩子调用）
    python _shared/secret_scan.py --all      # 扫描工作区全部已跟踪文件

命中疑似真实凭据时返回码 1，阻断提交；仅提示不阻断的弱口令返回 0。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 高置信度：命中即阻断
BLOCK_PATTERNS = [
    ("OpenAI/聚合平台 Key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}")),
    ("GitHub PAT", re.compile(r"\b(ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})")),
    ("Google API Key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}")),
    ("AWS Access Key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Slack Token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{20,}")),
    ("私钥文件内容", re.compile(r"-----BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY-----")),
    ("硬编码 Bearer", re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{40,}")),
]

# 允许出现的占位符/示例值
ALLOW_HINTS = ("your_", "xxx", "****", "<", "example", "placeholder", "test-", "dummy", "demo",
               "changeme", "sk-****")

TEXT_SUFFIXES = {".py", ".md", ".json", ".yaml", ".yml", ".js", ".ts", ".ps1", ".bat", ".sh",
                 ".txt", ".ini", ".cfg", ".toml", ".env", ".example"}
SKIP_PARTS = {".venv", "node_modules", "__pycache__", ".git", "runtime", "_backup", "_browser_profile"}
MAX_BYTES = 2 * 1024 * 1024


def _staged_files() -> list[Path]:
    out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
                         cwd=ROOT, capture_output=True, text=True)
    return [ROOT / line.strip() for line in out.stdout.splitlines() if line.strip()]


def _tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    return [ROOT / line.strip() for line in out.stdout.splitlines() if line.strip()]


def _skipped(path: Path) -> bool:
    rel = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    return any(part in SKIP_PARTS for part in rel.parts)


def scan(files: list[Path]) -> list[tuple[str, Path, int, str]]:
    findings: list[tuple[str, Path, int, str]] = []
    for path in files:
        if not path.is_file() or _skipped(path):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES and path.name != ".env":
            continue
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            low = line.lower()
            if any(h in low for h in ALLOW_HINTS):
                continue
            for label, pattern in BLOCK_PATTERNS:
                if pattern.search(line):
                    masked = re.sub(r"[A-Za-z0-9_\-]{8,}", lambda m: m.group(0)[:4] + "****", line.strip())
                    findings.append((label, path, lineno, masked[:160]))
                    break
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description="提交前敏感信息扫描")
    ap.add_argument("--all", action="store_true", help="扫描全部已跟踪文件而非暂存区")
    args = ap.parse_args()

    files = _tracked_files() if args.all else _staged_files()
    if not files:
        print("[secret-scan] 没有待检查的文件，跳过。")
        return 0

    findings = scan(files)
    if not findings:
        print(f"[secret-scan] 通过：检查 {len(files)} 个文件，未发现疑似凭据。")
        return 0

    print(f"[secret-scan] 拦截：发现 {len(findings)} 处疑似凭据（已脱敏）：")
    for label, path, lineno, snippet in findings:
        rel = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
        print(f"  - [{label}] {rel}:{lineno}  {snippet}")
    print("\n处理方式：改为 os.environ.get(\"XXX_API_KEY\") 读取，并把真实值写入本地 .env。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
