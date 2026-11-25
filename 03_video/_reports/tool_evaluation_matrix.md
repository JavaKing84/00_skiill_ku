# 03_video 工具选型对比矩阵（Phase 1 调研产物）

> **生成时间**：2026-11-25
> **调研方式**：GitHub MCP `search_repositories`（实时星数）+ WebSearch/WebFetch（云端 API 定价）+ 本地 TechRadar DB 检索（无相关条目，故以联网为准）
> **环境基线**：Windows + Python 3.14 + **纯 CPU（无独立显卡）** → 本地大模型推理不现实，AI 生视频/短剧首选云端 API
> **可信度**：星数 / archived 标记来自 GitHub 实时查询（2026-11-25）；定价来自官方文档；未凭记忆编造

---

## 一、AI 视频生成（业务能力 A）

| 仓库 / 服务 | 星数 | 维护频率(最近更新) | License | CPU 兼容 | API / 成本 | 结论 |
|---|---|---|---|---|---|---|
| **ComfyUI** (Comfy-Org/ComfyUI) | 148,554⭐ | 2026-11-25 活跃 | GPL-3.0 | ❌ 需 GPU（本地无独显跑不动） | 本地免费但需显卡 | **不选**：本机无 GPU，弃用 |
| **CogVideoX** (zai-org/CogVideo) | 13,230⭐ | 2026-11-25 | Apache-2.0 | ⚠️ CPU 可跑但极慢（分钟级/秒） | 无官方 API | 备选：仅作离线研究，不作为生产路径 |
| **HunyuanVideo-1.5** (Tencent-Hunyuan) | 4,618⭐ | 2026-11-25（2025-11 创建，很新） | 腾讯开源协议 | ⚠️ 同上 | 无 | 备选 |
| **Seedance 2.0/2.5**（火山引擎·云端 API） | — | 官方持续迭代 | 商用 | ✅ 纯 CPU 调 API 即可 | 见下表 | ✅ **首选**：已有 aitoearn 集成路径 + 官方 API |
| **可灵 Kling 4.0**（快手·云端 API） | — | 官方持续 | 商用 | ✅ CPU 调 API | 聚合价 ~$0.38/s | ✅ 备选：画质强，成本较高 |
| **硅基流动 SiliconFlow**（聚合云端 API） | — | 活跃 | 商用 | ✅ CPU 调 API | MiniMax-H3 $0.08/s；Seedance $0.12/s | ✅ **首选聚合**：一个 Key 调多家，成本最低 |
| **Runway Gen-4 / Pika 3.0 / Luma** | — | 活跃 | 商用 | ✅ CPU 调 API | $28–39/mo 订阅 | 备选：海外，需科学上网 |

**Seedance 官方定价（火山引擎，CNY，2026-11 核实）**：
| 模型 | 480P | 720P | 1080P | 4K |
|---|---|---|---|---|
| Seedance 2.0 | 0.580 元/s | 1.220 元/s | 3.040 元/s | 5.075 元/s |
| Seedance 2.5 | 0.808 元/s | — | 3.040 元/s | — |
| Seedance 2.5 flash | 0.66 元/s | 1.49 元/s | — | — |

> 成本估算：一条 5s 1080P Seedance 2.5 ≈ 15 元；走 SiliconFlow 聚合 Seedance ≈ $0.6/条。**需用户充值，非免费。**

---

## 二、AI 短剧编排（业务能力 B）—— 调研架构，不自建全栈

> 目标：借鉴「工作流 JSON 化 + 状态机与门禁分离」，自研轻量编排器（后端调 API），不直接部署这些重型 TS/Java 平台。

| 仓库 | 星数 | 语言 | 架构亮点（借鉴点） | CPU/API | 结论 |
|---|---|---|---|---|---|
| **huobao-drama** (chatfire-AI) | 17,987⭐ | TypeScript | 一句话→剧本→分镜→成片全自动化；工作流节点化 | 后端调 API | ✅ **重点借鉴**：其「剧本→分镜→生图→生视频→拼接」状态机 |
| **Toonflow-app** (HBAI-Ltd) | 22,789⭐ | TypeScript | 无限画布 + AI Agent + 可视化工作流；MCP/插件扩展；自部署 | 可本地但重 | 借鉴其「工作流 JSON 化」与「角色资产库」设计 |
| **Jellyfish** (Forget-C) | 7,320⭐ | **Python** | 剧本拆解 / 分镜 / 角色一致性管理 | Python 友好 | ✅ **最贴近我们技术栈**：可直接读其分镜拆分逻辑 |
| **LocalMiniDrama** (xuanyustudio) | 2,544⭐ | JS | seedance2 接入；本地离线；纳米流水线 | seedance API | 借鉴其「数据不出本机 + seedance 接入」封装 |
| **drama-skills** (zenstory-ai) | 4,996⭐ | Python | Agent 技能包：小说改剧本→视觉设定→分镜→提示词→成片 | 纯 skill/提示词 | ✅ 借鉴其提示词模板分层 |
| **shuohao-skills** (eternityspring) | 7,121⭐ | JS | 拆角色/排大纲/出场景/写剧本/切分镜 | skill 集合 | 借鉴角色一致性门禁 |

> 用户点名的 `shortdrama-pipeline`：GitHub 未检索到同名高星仓库（短剧生态关键词为 short-drama / mini-drama）。上述仓库覆盖了同类能力，以它们为准。

---

## 三、视频语义理解（业务能力 C·首选路径）

| 仓库 / 工具 | 星数 | 能力 | CPU 兼容 | 结论 |
|---|---|---|---|---|
| **Qwen3-Omni** (QwenLM) | 4,123⭐ | 端到端理解 文本/音频/图像/视频 + 生成语音 | ⚠️ 本地需大显存；推荐走**云端 API**（火山方舟 / 硅基流动均已上线） | ✅ **首选**：调 API 做镜头描述+台词理解，做语义级切点匹配 |
| **Awesome-LLMs-for-Video-Understanding** (yoloytang) | 3,312⭐ | Vid-LLM 论文/代码/数据集汇总（IEEE TCSVT） | — | 📚 索引清单，用于跟踪 Video-LLaVA / LLaMA-Video / VideoChat 等 |
| `media-engine`（用户提及） | 0 结果 | — | — | ❌ **GitHub 无此公开仓库**，如实标注；不编造。以 Qwen3-Omni / Video-LLaVA 系替代 |

---

## 四、底层基建（业务能力 C·备选缝合 + 全流程性能底座）

| 工具 | 星数 | 用途 | CPU 兼容 | 选型 |
|---|---|---|---|---|
| **PySceneDetect** (Breakthrough) | 5,652⭐ | 镜头边界检测 | ✅ CPU | 已有（慢）；**用 ffmpeg `select='gt(scene,0.3)'` 替代**其 Python 逐帧循环，速度数倍 |
| **videohash** (akamhy) | 388⭐ | 感知视频哈希 / 近重复检测 | ✅ 基于 ffmpeg | ✅ 用于跨素材去重；另有 ffmpeg `mpdecimate` 做片内去重 |
| **IOPaint** (Sanster，原 lama-cleaner) | 23,281⭐ ⚠️**已 archived** | AI 去水印/画面修补（lama/latent-diffusion） | ⚠️ CPU 可跑但慢；模型需下载 | 🔧 作可选内核；**首选 ffmpeg `delogo`**（零依赖、快），顽固水印才降级调 IOPaint |
| **ultralytics YOLO** (ultralytics) | 63,741⭐ | 人物检测（替代 YuNet） | ✅ 导出 YOLOv8n ONNX(~6MB) 后 CPU 推理可用 | ✅ 用 YOLOv8n/v10n ONNX + onnxruntime CPU，替换迟滞的 OpenCV YuNet |

---

## 五、选型决策汇总（封装落点）

| 能力 | 选定方案 | 封装位置 | 理由 |
|---|---|---|---|
| AI 视频生成 | 云端 API：Seedance（主）/ SiliconFlow 聚合（备） | `generative/ai_video_api.py` | 纯 CPU 无显卡，本地 ComfyUI/CogVideo 不可行；已有 aitoearn MCP 路径 |
| AI 短剧编排 | 自研状态机编排器（借鉴 huobao/Jellyfish），后端调 Seedance | `generative/drama_orchestrator.py` + `templates/` | 不部署重型 TS 平台；取其架构思想，保持 Python 可控 |
| 电影混剪·语义理解 | Qwen3-Omni 云端 API 做镜头描述+台词 | `adapters/semantic_adapter.py` | media-engine 无公开仓库；Qwen3-Omni 已验证且有 API |
| 电影混剪·缝合模式 | 按语义/情绪标签切割已有爆款视频重组 | `adapters/stitcher.py` | 长视频语义理解失败时的降级路径 |
| 镜头检测 | ffmpeg `select='gt(scene,0.3)'` 替代 PySceneDetect 循环 | `adapters/shot_detector.py`（替换 scripts/shot_analyze.py） | CPU 上 ffmpeg 原生滤镜比 Python 逐帧快数倍 |
| 去重 | ffmpeg `mpdecimate`（片内）+ `videohash`（跨素材） | `adapters/dup_finder.py`（替换 scripts/dedup） | 抛弃逐帧全量哈希；稀疏采样已够快 |
| 去水印 | ffmpeg `delogo`（首选）→ IOPaint/ONNX（降级） | `adapters/watermark_remover.py` | 抛弃粗糙 crop；delogo 零依赖快 |
| 人物检测 | YOLOv8n/v10n ONNX + onnxruntime CPU | `adapters/person_scan.py`（替换 scripts/person_scan.py） | 替代 YuNet，精度速度双升 |
| 并发渲染 | 多进程切片渲染 + concat | `adapters/concurrent_render.py` 接入 montage_edit | 压榨 CPU 多核 |
| 自迭代沉淀 | 执行后写耗时/失败到 tech_radar.md | `scripts/reflect.py` | 闭环优化 |

---

## 六、局限性声明（前置，写入最终报告）

1. **无 GPU**：所有本地大模型推理（ComfyUI / CogVideo / HunyuanVideo / 本地 Qwen3-Omni）在本机不可行或极慢，AI 视频/语义理解**必须走云端 API，需用户充值**。
2. **云端 API 非免费**：Seedance 1080P ≈ 3 元/s，一条 5s 视频 ≈ 15 元；SiliconFlow 聚合更便宜但仍付费。
3. **IOPaint 已 archived**：作为可选降级内核，不保证持续维护；首选 ffmpeg delogo。
4. **`media-engine` 无公开仓库**：业务 C 首选改用 Qwen3-Omni API。
5. 短剧编排为**自研轻量状态机**（借鉴架构，非部署 huobao/Toonflow 全栈），功能覆盖剧本→分镜→生成→拼接，不含其无限画布 UI。

*数据复核：所有星数与 archived 标记均来自 GitHub MCP 实时查询（2026-11-25），定价来自火山引擎/SiliconFlow 官方文档。*
