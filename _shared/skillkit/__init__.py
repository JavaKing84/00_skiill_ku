"""skillkit — 个人 AI 技能库共享服务包。

模块：
  hashing   文件哈希与去重
  manifest  采集结果统一清单（assets_manifest / entries）
  inteldb   TechRadar SQLite 情报库
  media     ffprobe/ffmpeg 封装与 QC
  loggingx 脱敏日志
所有模块仅依赖标准库；requests/PIL 为可选增强，缺失时降级。
"""

__version__ = "1.0.0"
