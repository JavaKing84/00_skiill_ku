# CHANGELOG — 03-video-pipeline

## 1.0.0 — 2026-11-25

- 新建标准聚合入口，遵循 SKILL.md frontmatter 规范（name / description / version / triggers / not_triggers）。
- 通过相对路径映射到 `03_video/`：canonical 规则、aitoearn 执行器、scripts 渲染与 QC 脚本。
- 补充常用命令：`video_qc.py`、`verify_asset.py`、`publish_preview.py`。
- 明确硬约束：必须真实调用执行器、ffprobe 校验、发布默认 dry-run、BGM 许可台账。
