"""_shared/security.py — 凭据脱敏与安全读取工具。

用途：任何需要打印/记录凭据相关数据的地方，统一调用这里的方法，
避免 Key / Token / Cookie 以明文进入日志、报告或终端输出。

用法：
    from _shared.security import mask_secret, mask_mapping, redact_text
    print(mask_secret(os.environ.get("SILICONFLOW_API_KEY")))   # sk-****abcd
    print(mask_mapping({"api_key": key, "model": "seedance2.5"}))
"""
from __future__ import annotations

import os
import re

SENSITIVE_KEYS = ("api_key", "apikey", "token", "secret", "password", "passwd",
                  "authorization", "cookie", "session", "access_key", "private_key")

# 常见凭据形态：sk-xxx / ghp_xxx / Bearer xxx / 长 hex
_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9_\-]{8,})"),
    re.compile(r"(ghp_[A-Za-z0-9]{20,})"),
    re.compile(r"(github_pat_[A-Za-z0-9_]{20,})"),
    re.compile(r"(AIza[0-9A-Za-z_\-]{30,})"),
    re.compile(r"(Bearer\s+)([A-Za-z0-9_\-\.]{12,})"),
]


def mask_secret(value: str | None, keep: int = 4) -> str:
    """把密钥变成 `sk-****abcd` 形式；太短则全部掩码。"""
    if not value:
        return ""
    v = str(value)
    if len(v) <= keep * 2:
        return "****"
    return f"{v[:keep]}****{v[-keep:]}"


def mask_mapping(data: dict, keep: int = 4) -> dict:
    """递归脱敏字典中键名含敏感词的字段。"""
    out: dict = {}
    for k, v in data.items():
        if isinstance(v, dict):
            out[k] = mask_mapping(v, keep)
        elif isinstance(v, list):
            out[k] = [mask_mapping(i, keep) if isinstance(i, dict) else i for i in v]
        elif any(s in str(k).lower() for s in SENSITIVE_KEYS) and isinstance(v, str) and v:
            out[k] = mask_secret(v, keep)
        else:
            out[k] = v
    return out


def redact_text(text: str) -> str:
    """对任意文本做正则脱敏，用于日志行/异常信息。"""
    if not text:
        return text
    result = text
    for p in _PATTERNS:
        result = p.sub(lambda m: (m.group(1) + mask_secret(m.group(2))) if p.groups == 2 else mask_secret(m.group(1)), result)
    return result


def get_secret(name: str, default: str = "") -> str:
    """从环境变量读取凭据（禁止在源码里写死）。"""
    return os.environ.get(name, default).strip()
