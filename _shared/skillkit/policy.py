"""采集策略：超时、重试退避、速率限制、断点状态。纯标准库。"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from pathlib import Path
import json


@dataclass(frozen=True)
class CrawlPolicy:
    timeout_seconds: int = 30
    max_retries: int = 3            # 不含首次
    backoff_base_seconds: float = 2.0
    backoff_cap_seconds: float = 30.0
    min_interval_seconds: float = 1.5   # 同域请求最小间隔（拟人节奏）
    jitter_seconds: float = 0.8
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )

    def backoff(self, attempt: int) -> float:
        """attempt 从 1 开始（第 1 次失败后的等待）。"""
        delay = min(self.backoff_cap_seconds, self.backoff_base_seconds * 2 ** (attempt - 1))
        return delay + random.uniform(0, self.jitter_seconds)


class RateLimiter:
    """同域最小间隔限速，线程内使用足够。"""

    def __init__(self, policy: CrawlPolicy):
        self.policy = policy
        self._last: dict[str, float] = {}

    def wait(self, domain: str) -> None:
        now = time.monotonic()
        prev = self._last.get(domain)
        if prev is not None:
            gap = now - prev
            if gap < self.policy.min_interval_seconds:
                time.sleep(self.policy.min_interval_seconds - gap)
        self._last[domain] = time.monotonic()


class Checkpoint:
    """断点恢复：把已完成 URL 持久化到 JSON。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.done: set[str] = set()
        if self.path.exists():
            self.done = set(json.loads(self.path.read_text(encoding="utf-8")).get("done", []))

    def has(self, url: str) -> bool:
        return url in self.done

    def mark(self, url: str) -> None:
        self.done.add(url)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"done": sorted(self.done)}, ensure_ascii=False), encoding="utf-8")
