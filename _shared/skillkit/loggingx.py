"""脱敏日志：密钥/token/cookie/key 一律打码。"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|cookie|password|session[_-]?token)([\"'\s:=]+)([^\s\"',;]{6,})"),
    re.compile(r"(?i)(Bearer\s+)([A-Za-z0-9._\-]{8,})"),
    re.compile(r"(?i)(cn_[A-Za-z0-9]{12,}|sk-[A-Za-z0-9]{12,})"),
]


def mask(text: str) -> str:
    def _sub(m: re.Match) -> str:
        if len(m.groups()) == 3:
            return f"{m.group(1)}{m.group(2)}***MASKED***"
        return f"{m.group(1)}***MASKED***"

    out = str(text)
    for pat in _SECRET_PATTERNS:
        out = pat.sub(_sub, out)
    return out


class MaskedLogger:
    def __init__(self, log_path: str | Path | None = None, echo: bool = True):
        self.path = Path(log_path) if log_path else None
        self.echo = echo
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, level: str, msg: str) -> None:
        line = f"[{datetime.now().isoformat(timespec='seconds')}] {level} {mask(msg)}"
        if self.echo:
            print(line, file=sys.stderr)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def info(self, msg: str) -> None:
        self.log("INFO", msg)

    def warn(self, msg: str) -> None:
        self.log("WARN", msg)

    def error(self, msg: str) -> None:
        self.log("ERROR", msg)
