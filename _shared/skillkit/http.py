"""共享 HTTP 采集层：统一 UA/超时/退避重试/限速/脱敏错误。

所有通道（A 公开、B 认证）都走这里，保证：单一信任边界、单一重试策略、错误不外泄凭据。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import requests

from .policy import CrawlPolicy
from .loggingx import mask

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


class FetchError(RuntimeError):
    """采集失败（错误信息已脱敏）。"""

    def __init__(self, message: str, status: int | None = None, kind: str = "error"):
        super().__init__(mask(message))
        self.status = status
        self.kind = kind          # auth | approval | network | http | parse | rate_limit


class HttpClient:
    """带策略的 HTTP 客户端；会话级复用。

    trust_env=False 让采集不隐式走系统代理（保证同一份代码在不同机器结果一致）。
    需要代理的来源（被 TLS 指纹/地域拦截的站点）显式传 proxy，例如
    HttpClient(policy=p, proxy="http://127.0.0.1:3067")。
    """

    def __init__(self, policy: CrawlPolicy | None = None, user_agent: str = DEFAULT_UA,
                 headers: dict[str, str] | None = None, proxy: str | None = None):
        self.policy = policy or CrawlPolicy(timeout_seconds=25, max_retries=3,
                                            backoff_base_seconds=2.0, min_interval_seconds=1.0)
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({"User-Agent": user_agent, "Accept": "*/*"})
        if headers:
            self.session.headers.update(headers)
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        self.proxy = proxy
        self._last_call = 0.0
        self.request_count = 0

    def _throttle(self) -> None:
        gap = time.monotonic() - self._last_call
        if gap < self.policy.min_interval_seconds:
            time.sleep(self.policy.min_interval_seconds - gap)
        self._last_call = time.monotonic()

    def get(self, url: str, *, params: dict | None = None, headers: dict | None = None,
            timeout: int | None = None) -> requests.Response:
        return self._request("GET", url, params=params, headers=headers, timeout=timeout)

    def post(self, url: str, *, data: Any = None, json_body: Any = None,
             headers: dict | None = None, auth: tuple | None = None,
             timeout: int | None = None) -> requests.Response:
        kw: dict[str, Any] = {}
        if data is not None:
            kw["data"] = data
        if json_body is not None:
            kw["json"] = json_body
        return self._request("POST", url, headers=headers, auth=auth, timeout=timeout, **kw)

    def _request(self, method: str, url: str, **kw) -> requests.Response:
        last_exc: Exception | None = None
        for attempt in range(self.policy.max_retries + 1):
            self._throttle()
            try:
                self.request_count += 1
                r = self.session.request(method, url, timeout=kw.pop("timeout", None) or self.policy.timeout_seconds, **kw)
                if r.status_code == 401:
                    raise FetchError(f"401 未授权: {url}", 401, "auth")
                if r.status_code == 403:
                    low = (r.text or "")[:200].lower()
                    kind = "approval" if ("api" in low or "blocked" in low or "forbidden" in low) else "auth"
                    raise FetchError(f"403 拒绝访问: {url}", 403, kind)
                if r.status_code == 429:
                    if attempt < self.policy.max_retries:
                        time.sleep(self.policy.backoff(attempt + 1))
                        continue
                    raise FetchError(f"429 触发限流: {url}", 429, "rate_limit")
                if r.status_code >= 500:
                    if attempt < self.policy.max_retries:
                        time.sleep(self.policy.backoff(attempt + 1))
                        continue
                    raise FetchError(f"HTTP {r.status_code}: {url}", r.status_code, "http")
                return r
            except FetchError:
                raise
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < self.policy.max_retries:
                    time.sleep(self.policy.backoff(attempt + 1))
                    continue
                raise FetchError(f"{type(exc).__name__}: {url}", None, "network") from None
        raise FetchError(f"请求失败: {url}", None, "network") from last_exc

    def get_json(self, url: str, **kw) -> Any:
        r = self.get(url, **kw)
        try:
            return r.json()
        except ValueError:
            raise FetchError(f"响应不是 JSON: {url} ({r.text[:80]})", r.status_code, "parse") from None

    def get_text(self, url: str, **kw) -> str:
        return self.get(url, **kw).text


def load_dotenv(path: str | Path = ".env") -> dict[str, str]:
    """极简 .env 读取（不覆盖已存在的环境变量）；返回解析到的键值（值不打印）。"""
    p = Path(path)
    out: dict[str, str] = {}
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        out[k] = v
        os.environ.setdefault(k, v)
    return out


def env_present(name: str) -> bool:
    return bool((os.environ.get(name) or "").strip())


def safe_json(obj: Any) -> str:
    return mask(json.dumps(obj, ensure_ascii=False)[:500])
