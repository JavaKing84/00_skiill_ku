---
name: video-pipeline-canonical
description: 自动视频生产标准流程与质量体系（素材验证→参考分析→基础渲染→QC→发布 dry-run）。当用户要求剪辑视频、把素材做成成片、合并视频、复刻参考视频节奏、加字幕花字配音BGM转场、做不同画幅、批量剪辑、压缩导出、检查成片黑屏无声损坏、或生成发布预览时使用。纯视频内容分析、只下载素材、研究视频生成技术不触发。
version: 1.2.0
language: zh-CN
triggers: [剪辑, 成片, 合并视频, 参考视频, 字幕, 配音, BGM, 转场, 画幅, 竖屏, 导出, 压缩, 成片质检, 黑屏, 无声, 发布预览]
not_triggers: [只分析视频内容, 只下载视频, 视频生成技术研究, 纯图片编辑, 只讨论剪辑理论]
executor: D:/00_skiill_ku/03_video/aitoearn（库内副本）+ ~/.trae-cn/skills/aitoearn（安装壳，真实剪辑执行 + aitoearn-cn MCP）
standard_flow: D:/00_skiill_ku/03_video (素材校验 / 参考分析 / 基础渲染 / QC / 发布预览)
tool_deps: [ffmpeg 9.0.2, ffprobe, python 3.14.7, numpy, opencv-python 5.1.0, onnxruntime 1.32.0, scenedetect 0.7.3, Pillow, 字体 C:/Windows/Fonts/msyhbd.ttc]
acceptance: [成片文件真实存在, ffprobe 元信息可解析, video_qc verdict 记录, 产物路径与参数留档, quality_check_all verdict 记录]
---

# 自动视频生产流水线（Canonical · 跨客户端）

> 与 `~\.trae-cn\skills\aitoearn\SKILL.md` 的关系：aitoearn 是 Trae 内的满血执行版（14 子技能 + MCP），
> 本文件是**不依赖插件市场的可迁移版**。已验证的 ffmpeg 滤镜链、crop 参数、混音铁律仍以 aitoearn 原文为准，
> 本文件只沉淀流程契约、可执行脚本与验收门禁，不复制、不改写那些参数。
> aitoearn 的库内副本在 `03_video\aitoearn`（源），`~\.trae-cn\skills\aitoearn` 是安装壳；改库后同步壳。

## 0. 全流程与状态门禁

```
主题/参考视频
  → ① 需求拆解（镜头清单 + 中英双语搜索词）
  → ② 素材发现 verify_asset.py（落盘 + 验证 + assets_manifest.json）
  → ③ 参考分析 reference_analyze.py（timeline + reference_style.json）
  → ④ 创意与镜头规划（人工/模型，输出镜头清单）
  → ⑤ 生成/渲染
       ├ Trae 内：aitoearn 技能 + aitoearn-cn MCP（真实剪辑、字幕、配音、生成式视频、发布）
       └ 跨客户端 / 轻量拼接：03_video/scripts/render.py（基础拼接 + 画幅 + 字幕 + 可选授权 BGM + 导出）
  → ⑥ 质检 video_qc.py（不只看退出码）
  → ⑦ 用户审核（默认停在这里）
  → ⑧ 发布准备 publish_preview.py（dry-run，永不自动公开发布）
  → ⑨ 效果归档
```

每个环节的状态只能取：`discovered / downloaded / verified / failed / skipped / blocked`。

### 0.1 时长守卫（2026-11-21 新增，三道门禁 + QC 兜底）

剪辑最忌两类怪片：几秒桥段被拉长、只剪了前几秒就收工。现在由确定性门禁拦截，不再靠模型自觉：

| 门禁 | 位置 | 规则 |
|---|---|---|
| 守卫1 | `montage_edit.py` 渲染前 | 每段 `start+dur ≤ 源素材实际时长`，超出直接 BLOCKED 并提示最多可用多少秒；禁止慢放/补帧硬凑 |
| 守卫2 | `montage_edit.py` 每段渲染后 | 段实得时长 vs 计划 dur 偏差 > 0.35s 即报错中止 |
| 守卫3 | `montage_edit.py` 成片后 | 成片时长 vs EDL 计划总时长偏差 > 1.0s → 退出码 2，禁止交付 |
| QC 兜底 | `video_qc.py --plan-json <montage 报告.json>` | 复核时长守卫 + 冻结检测（freezedetect，整段静止 > 3s 即 FAIL）+ 静音段 + 黑屏 + 音量 |

EDL 字段与守卫说明见 `03_video/examples/edl_example.json`。规则：**多段带裁剪的剪辑一律走 `montage_edit.py` + EDL**，
`render.py` 只用于整段原样拼接；任何渲染必须带 `--qc` 或事后补跑 `video_qc.py --plan-json`。

**音轨守卫（2026-11-22 新增）**：`montage_edit.py` 输出 `audio_source ∈ source|bgm|silence`。
若为 `silence`（所有素材无音轨且未配 BGM），脚本会告警，且**禁止直接发布**——先补登记过的 BGM
（`03_video/assets/BGM_LICENSES.json`）或换带原声素材。`video_qc.py` 的静音段走 `-af` 检测，
"有声但长时间静音"的片子会被判 WARN/FAIL，不会被当成成品放行。

### 0.2 职责分工（避免重复实现）

| 能力 | 归属 | 说明 |
|---|---|---|
| 真实剪辑、字幕生成、配音、生成式视频、多平台发布 | **aitoearn**（Trae 内） | 已装 14 子技能 + aitoearn-cn MCP，能力最全 |
| 素材验证、参考视频分析、成片 QC、发布预览 | **03 脚本** | 跨客户端可复用的质量体系 |
| 基础拼接/画幅/字幕/可选 BGM/导出 | **03/scripts/render.py** | 最小可复现渲染，非 Trae 客户端的兜底路径 |
| 复杂电影混剪（多镜叙事、混音铁律、crop 参数） | **aitoearn 原文** | 参数以 aitoearn SKILL 为准，本文件不复制 |
| 镜头边界检测（切点对齐真实剪辑点） | **03/scripts/shot_detect.py** | 基于 PySceneDetect，见 §0.3 |

### 0.3 画幅转制与镜头对齐（2026-11-22 实战缺陷复盘，硬约束）

一次竖屏电影混剪交付后被打回，三条投诉全部可复现，根因都是流水线参数而不是"AI 理解不够"：

| 投诉现象 | 真实根因 | 现行规则 |
|---|---|---|
| "镜头像被放大过，人都到画面外" | `scale=1080:1920:force_original_aspect_ratio=increase` + `crop` 把 1920×1080 放大 **1.78 倍**，横向只保留 **31.6%** | 横屏素材转竖屏**默认 `fit=blur_pad`**：等比缩放完整放入画幅 + 同画面模糊放大做背景填充。只有源比例与目标比例相差 <15% 才允许 `fit=cover` |
| "半个镜头都是黑的，看着难受" | 裁切丢掉了亮部信息；再叠加 `dark_cool` 的 `vignette` 与背景 `brightness=-0.18`，上下两端叠成死黑 | `blur_pad` 模式自动去掉 `vignette`，背景只压 `brightness=-0.04`；逆光/夜景镜头用段级 `extra_grade` 单独补 `eq=brightness=0.07:gamma=1.18`，不全局拉亮 |
| "剪辑很 AI、随便乱配音频" | 切点凭感觉（落在半句/半个动作上）；一段用了**另一个文件的声音**配本段画面，且音画错位 5s | 任何对白段必须 **A/V 同源同起点**；切点先跑 `shot_detect.py` 拿真实镜头边界，再结合词级时间戳落在句间停顿；跨源配音仅允许明确的 V.O.（画外音）且必须在 EDL `note` 里标注出来 |

```json
// EDL 相关字段（montage_edit.py）
{
  "fit": "blur_pad",            // cover | blur_pad，横屏转竖屏默认 blur_pad
  "segments": [
    {"label": "S6", "src": "a.mp4", "start": 465.95, "dur": 15.8,
     "extra_grade": "eq=brightness=0.07:gamma=1.18"}   // 可选，段级补光
  ]
}
```

镜头边界检测（确定性，不依赖模型判断）：

```powershell
python 03_video/scripts/shot_detect.py --video a.mp4 --start 428 --end 620 `
  --json shots.json --frames shots_dir
```

- 输出每镜 `start/end/dur`；`--frames` 落每个镜头首帧，便于判断"这一镜里有没有人、是不是空镜、亮不亮"。
- 电影长镜头多，**区间内只返回 1 个镜头是正常结果**（说明这段是一镜到底），不视为检测失败。
- 交付前必须抽帧自查三件事：人物是否完整在画（未被裁）、上下补边区是否是"可辨识的环境色"而非死黑、每一句台词开口时画面里是否有对应人物/场景。

## 1. 素材发现（可验证，禁止编造）

- 主题 → 镜头需求 → 每个镜头生成中文+英文搜索词、同义词、场景词，先写查询记录再下载。
- 依次检查：官方/授权素材库 API → 用户提供链接/文件 → 合规网页。找不到就记录查询式与失败原因，**不许编造下载链接、不许把缩略图当原视频**。
- 下载与验证统一走：
  `python 03_video/scripts/verify_asset.py --url <URL> --project-dir <项目目录> --title <标题>`
  - 自动执行：同域限速 1.5s、30s 超时、3 次指数退避、MIME 检查、PIL/ffprobe 解码验证、SHA256、去重。
  - 产出 `<项目目录>/assets_manifest.json`（collection-manifest-v1，契约见 `01_crawler/skills/web-scraping/08`）。
- `license_status` 默认 `unknown`；unknown 素材可进清单，**禁止进正式作品**。

## 2. 参考视频逆向分析

仅分析用户有权处理的本地文件，不上传外部服务：

`python 03_video/scripts/reference_analyze.py --video <参考视频> --out <分析目录>`

- 机器产出：ffprobe 元信息、scene cut 切换点、首/中/尾+切换点抽帧、`reference_timeline.csv`、`reference_style.json`。
- 脚本**不编造画面内容**：timeline 的 visual/shot_motion 留空，由模型看 `frames/` 后补，并区分事实与推断（JSON 内 `inferred_fields`）。
- 学习规律但不照搬：不复用原文案、商标、水印、受版权保护画面。

## 3. 生成架构（工具评估结论，2026-11）

| 层 | 工具 | 结论 | 理由 |
|---|---|---|---|
| 确定性渲染地基 | FFmpeg 9.0.2 | **主链路，保留全部已验证参数** | 可控、可复现、零积分 |
| 程序化模板/批量数据视频 | Remotion | 评估通过后作为第二渲染器接入，先隔离 demo | React 模板擅长榜单/卡片/数据视频 |
| 表达层（花字/卡点/模板） | 剪映自动化 | **可选降级通道，不进主链路** | UI 自动化随版本易碎；必须有版本检测、截图状态检查、失败退出、人工接管 |
| AI 文生/图生视频 | Seedance（aitoearn）/内置 GenerateVideo | 维持现状，不新增 Hyperframes 类重复服务 | 生成层多接一家只增加密钥与成本 |
| TTS | byted-mediakit-audiogen | 维持；克隆自有声音才考虑 ElevenLabs | 避免重复能力 |
| ASR/字幕 | byted-mediakit-asr；平替 faster-whisper | 跨客户端时用平替 | — |
| 镜头边界检测 | **PySceneDetect 0.7.3（GitHub 5.6k★，2026-11-22 仍在更新）** | **已采纳**，封装为 `scripts/shot_detect.py` | 纯 CPU、确定性、毫秒级切点；直接解决"切点落在半句/半个动作上" |
| 学习型切分（备选，未采纳） | TransNetV2（1.08k★）、OmniShotCut（357★）、AutoShot（267★） | 观察 | 依赖模型权重与 GPU，收益相对 PySceneDetect 有限；仅在转场/闪光/淡入淡出误判严重时再评估 |
| 语义级镜头理解（未采纳） | Qwen2.5-Omni（4.1k★）、InternVideo（2.4k★）、VideoLLaMA3（1.2k★） | 观察，不接入主链路 | 可回答"这一镜拍的是谁/什么景别"，但需 GPU 与长推理；本项目的缺陷根因是裁切参数与音画不同源，不是看不懂画面 |
| 智能重构图（未采纳） | pyautoflip / OpenClipper（均 <30★） | 不采纳 | 星数与维护度不足，且其"自动跟随主体裁切"正是竖屏毁构图的来源；改用 blur_pad 保守方案 |

新工具接入三问：是否提供现有栈做不到的表达/数据？挂了有无降级？维护成本是否低于收益？

## 4. 视频质检（退出码 0 ≠ 合格）

`python 03_video/scripts/video_qc.py --video <成片> --out <QC目录>`

检查项（阈值见脚本 DEFAULTS，可按项目覆盖）：
- 容器/编码/时长/画幅/帧率/音轨存在性；高度 <480、时长越界直接 FAIL。
- 黑屏累计 >1.5s 告警；无音轨告警；峰值 <-45dB 判无声 FAIL；峰值 >-0.5dB 判爆音风险；均值 <-35dB 偏小。
- 首/中/尾抽帧落盘，供人工核对字幕越界、拉伸、水印、黑帧。
- 产出 `video_qc.json` + `video_qc_report.md`，verdict ∈ PASS/WARN/FAIL（退出码 0/1/2）。
- 上线前另跑一次全片解码：`ffmpeg -v error -f null - <视频>`，有任何 error 输出不得交付。

## 5. 发布边界（硬约束）

- 默认且唯一的自动化产物：`publish_preview.py` 生成的 dry-run 预览（账号脱敏，无网络发布动作）。
- 禁止真实公开发布、禁止浏览器兜底点击发布；真实发布必须用户逐次明确批准后走正式 channel-publish。
- 预览 JSON 保留全部字段，便于获批后一键转为正式发布参数。

## 6. 已知环境缺口（2026-11-17 审计）

- `E:\Trae_Video_Workspace\bgm.mp3` 与 `bgm\` 目录不存在 → 无声视频自动垫乐当前会走到"停止并说明"。
  人工待办：放入 Mixkit 免费许可 BGM 并在 manifest 登记授权。
- aitoearn MCP 报 `-32001` 时按其 SKILL 的 onboarding 流程处理，不猜密钥。

## 7. 与共享底座的依赖

- 契约/清单/去重/断点：`_shared/skillkit/manifest.py`、`policy.py`
- 媒体探测：`_shared/skillkit/media.py`
- 抓取协议：`01_crawler/SKILL.md`（P0–P5）+ WS-08

## 8. 镜头语义 / 情绪 / 叙事 / 混音（2026-11-22 吸纳）

外部调研结论（GitHub 实查 star，非记忆）：镜头景别分类与电影情绪标注**没有**可直接本地落地的万星级项目；TransNetV2(1083★)/OmniShotCut(357★) 需 GPU 权重、收益不如确定性规则；PySceneDetect(5616★) 仅做镜头边界。故采用"确定性算法 + FFmpeg"组合，不引入重型模型：

- 镜头边界：`shot_detect.py`（PySceneDetect），切点对齐真实镜头边界，禁止凭感觉下刀。
- 段落台词补录：`win_asr.py`（本地 faster-whisper，指定时间窗转写，带词级时间戳），替代付费 ASR。
- 景别/情绪：按人脸占比与画面亮度判定（特写>18% / 中景6–18% / 远景<6%），情绪标签固定为 压抑/对峙/放空/挣扎，同情绪编组，禁止随机硬切。
- 三查：`validate_45s.py` ①人物白名单区间 ②原声轨 vs 单独渲染 BGM 轨的分离测量（人声≥BGM+8dB、压侧中位数≤-2dB）③段落顺序/时长/主线不并行。任一 FAIL 必须重排重混，禁止直接输出。

混音硬规则（本轮实测得出）：
- BGM 必须第 0 秒淡入垫底（-16dB 量级），不许"后段才进"；侧链用**轻压**（ratio 3、threshold 0.08），重度压侧会把 BGM 打到 -70dB 反而消失。
- 每段人声先做段内增益归一（安静对白 +8~14dB 并 `alimiter`），再做整体 `loudnorm I=-15`；否则小声对白会被 BGM 盖住。
- 素材自带 tiled 水印/烧录字幕时，用 `crop=iw:ih-180:0:108` 同时去掉顶部水印与底部字幕条，再做模糊补边，不要叠加二次字幕。
- 台词与画面不同源属 J-cut：先确认说话者本人无干净镜头，再以画外音处理，并在 manifest 注明。

## 9. 能力补齐章节（2026-11-22，7 个新模块）

> 背景：旧链路只能"听音频转写"，不能"看画面是谁"；镜头语义、叙事分级、混音封装、多条件检索、
> EDL 互操作、统一质检全部缺失。本节对应新增脚本均可被后续剪辑任务直接 `import`，**不修改**
> `win_asr.py` / `validate_45s.py`。全程只产出分析数据，不渲染 mp4。
> 全部 7 个模块的最小 demo 已用《大象席地而坐》导剪素材实跑通过（见 `03_video/demo_out/`）。
> 技术选型与 GitHub 调研明细见 `03_video/tech_radar.md`；依赖见 `03_video/requirements.txt`。

### 9.0 模块总览

| 缺陷 | 脚本 | demo | 主要产物 |
|---|---|---|---|
| 1 画面人物检索 | `scripts/person_scan.py` | `person_scan_demo.py` | `person_scan_result.csv` + detail JSON |
| 2 镜头语义解析 | `scripts/shot_analyze.py` | `shot_analyze_demo.py` | `shot_analyze_result.json` |
| 3 叙事/J-cut 分级 | `scripts/validate_narrative.py` | `validate_narrative_demo.py` | `validate_narrative_report.json` |
| 4 混音函数封装 | `scripts/audio_skill.py` | `audio_skill_demo.py` | filter 字符串 + `audio_diagnose.json` |
| 5 多模态素材检索 | `scripts/material_retrieve.py` | `material_retrieve_demo.py` | `material_retrieve_result.csv` |
| 6 EDL 互操作 | `scripts/edl_io.py` | `edl_io_demo.py` | `.edl` / 内部时间轴 JSON |
| 7 综合质量巡检 | `scripts/quality_check_all.py` | `quality_check_demo.py` | `quality_report.md` + `.json` |

### 9.1 依赖与模型权重（必须放对位置）

- 必装：`numpy`、`opencv-python`、`onnxruntime`、`scenedetect`、`Pillow`；系统需 `ffmpeg` / `ffprobe`。
- 可选 GPU（默认关闭不启用）：`onnxruntime-gpu`、`torch`、`tensorflow`（TransNetV2）、`insightface`，见 `requirements.txt` 注释。
- 权重目录：`D:\00_skiill_ku\03_video\models\`
  - `face_detection_yunet_2023mar.onnx`（232,589 字节）
    `https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx`
  - `face_recognition_sface_2021dec.onnx`（38,696,353 字节）
    `https://huggingface.co/opencv/face_recognition_sface/resolve/main/face_recognition_sface_2021dec.onnx`
- **踩坑**：opencv_zoo 用 Git LFS，`raw.githubusercontent.com` 只能下到 130 字节指针文件；`media` 地址对大文件限速严重，
  断点续传会叠加出 45MB 损坏文件。SFace 请走上面的 HuggingFace 地址并用 PowerShell
  `Invoke-WebRequest -OutFile` 下载，下完核对字节数。
- **踩坑**：本机 OpenCV 5.1.0 新 graph engine 下 `cv2.FaceDetectorYN.detect()` 返回 retval=1 但人脸矩阵为空，
  因此 `person_scan.py` 改为 **onnxruntime 直接跑 YuNet + 自行解码 + NMS**；SFace 仍用 `cv2.FaceRecognizerSF`（128 维）。

### 9.2 person_scan.py — 画面人物检索（缺陷1）

```powershell
# 1) 建参考库：从已知镜头自动裁脸，人工只需给脸贴名字
python scripts/person_scan.py --build-gallery `
  --spec assets/elephant/faces_seed.json `
  --video-dir assets/elephant/raw --gallery assets/elephant/faces

# 2) 扫描某区间
python scripts/person_scan.py --video assets/elephant/raw/导剪002.mp4 --start 1620 --end 1700 `
  --gallery assets/elephant/faces --window 4 --fps 1 `
  --out demo_out/person_scan_result.csv --detail-json demo_out/person_scan_detail.json
```

- 头像目录约定：`assets/elephant/faces/target/<角色>.jpg`、`assets/elephant/faces/blacklist/<角色>.jpg`；
  `faces/index.json` 缓存建库时从**原始帧**提取的 embedding（优先读取，避免对裁剪小图二次检测失败）。
- 输出 CSV 固定六列：`start,end,target_person_hit,blacklist_person_hit,face_count,confidence`。
  - `start/end`：源视频时间（秒）；`*_hit`：0/1；`face_count`：该窗口最大人脸数；
    `confidence`：窗口内最高余弦相似度。详细命中姓名在 `--detail-json` 的 `targets/blacklist` 里。
- 关键参数：`--window` 聚合窗（默认 4s）、`--fps` 抽帧率（默认 1）、`--min-score` 检测分（0.7）、
  `--min-face` 最小人脸像素（48）、`--sim-threshold` 余弦阈值（0.363，SFace 官方 LFW 阈值）。
- 与本片相关的配置事实：**王金 = 老人，是同一角色**，黑名单合并为一个头像文件，避免重复计数。
- 局限性（如实记录）：背光、强侧脸、口罩/手遮挡、远景 <48px 小脸会漏检；同一演员不同年龄/妆造掉相似度；
  阈值是经验值，换片必须用 20–30 个样本重标；**无法做到 100% 可靠**，黑名单命中仍需人工复核。

### 9.3 shot_analyze.py — 镜头语义（缺陷2）

```powershell
python scripts/shot_analyze.py --video assets/elephant/raw/短片64.mp4 --start 0 --end 64 `
  --out demo_out/shot_analyze_result.json [--frames demo_out/shot_frames]
```

- 输出 JSON 字段：`shot_id,start_time,end_time,shot_scale,face_area_ratio,motion_score,is_long_shot`，
  另附只读辅助字段 `source,duration,frames_sampled,no_face`。
- 实现：PySceneDetect 切边界（复用 `shot_detect.py`）→ 每镜抽帧 → YuNet 求最大人脸面积占比 → 帧差 MAE 求运动量。
- **景别阈值（本片标定，换片需重标）**：`≥0.22 特写`、`0.12–0.22 近景`、`0.05–0.12 中景`、`<0.05 远景`；
  时长 `≥6s` 记长镜头；`motion_score >0.25` 视为明显运动/手持，`<0.05` 视为静态。
- 局限：完全背身、全黑/极暗、纯空镜无法判景别（记远景且 `face_area_ratio=0`）；快速摇镜会让 motion 虚高。

### 9.4 validate_narrative.py — 叙事 / J-cut 分级（缺陷3）

```powershell
python scripts/validate_narrative.py --timeline assets/elephant/build45/timeline_45s.json `
  --shots demo_out/shot_analyze_result.json --forbidden forbidden.json `
  --emotion-script 压抑,挣扎,对峙,放空,压抑 --allow-jcut `
  --out demo_out/validate_narrative_report.json --md demo_out/validate_narrative_report.md
```

- 输出 JSON：`verdict`（PASS/WARN/FAIL）、`counts`、`issues[{error_level,message,time_range}]`、节奏统计。
- **block（必须重剪）**：黑名单人物入画、禁止支线（枪/养老院）命中、情绪顺序断裂、素材越界、总时长越界。
- **warn（可人工放行）**：J-cut 画外音、碎镜头比例过高、单镜过长、景别标注与实测不一致。
- 开关：`--allow-jcut`（默认，J-cut 记 warn）/ `--no-allow-jcut`（J-cut 升级为 block）。
  文艺片大量 VO 属正常创作，**默认只警告不阻断**。
- 局限：情绪顺序校验的是"标注一致性"，依赖上游写好的 `emotion` 字段，不是"理解电影"；无该字段时跳过并给 warn。

### 9.5 audio_skill.py — 混音函数封装（缺陷4）

```python
from audio_skill import audio_ducking, audio_segment_normalize, audio_fade_in_out, audio_diagnose

fc = (f"[1:a]{audio_segment_normalize('dynaudnorm')}[bgm];"
      f"{audio_ducking('0:a', 'bgm', threshold=0.03, ratio=9, attack=6, release=380)};"
      f"[0:a][bgmduck]amix=inputs=2:duration=first:dropout_transition=0,"
      f"{audio_fade_in_out(2.5, 2.8, 45.0)}[aout]")
```

- `audio_ducking(voice_label, bgm_label, threshold, ratio, attack, release, makeup, sc_level, bgm_gain_db, out_label)`
  → 返回 `[bgm]…sidechaincompress…[bgmduck]` 片段。默认 `threshold=0.05, ratio=6, attack=8, release=420`。
- `audio_segment_normalize(mode="dynaudnorm"|"loudnorm", ...)` → 单轨 filter 链（loudnorm 单遍为动态，精确达标需两遍）。
- `audio_fade_in_out(fade_in, fade_out, total, curve, start_at)` → `afade` 链，`out` 起点 = `start_at+total-fade_out`。
- `audio_diagnose(voice_path, bgm_path=None, speech_windows=None, is_mix=False)` → dict：
  `bgm_entry_sec`（BGM 首次可闻）、`voice_db`、`voice_bgm_diff`（>6dB 才不易被盖）、`ducking_db`（仅成片混音有意义）、
  `speech_drops`（台词窗口能量空档）、`flags`。**只解码分析，不生成任何视频**。
- 局限：能量法判"丢台词"不等价语义，气声/耳语会误报；独立 BGM 分轨不要看 `ducking_db`（传 `is_mix=False`）。

### 9.6 material_retrieve.py — 多模态条件检索（缺陷5）

```powershell
python scripts/material_retrieve.py --shots demo_out/shot_analyze_result.json `
  --person "导剪002.mp4=demo_out/person_scan_result.csv" `
  --person-detail "导剪002.mp4=demo_out/person_scan_detail.json" `
  --whisper whisper_002.json `
  --need 于城 --exclude 王金 --scale 近景 --long-shot --dialogue 满洲里 `
  --out demo_out/material_retrieve_result.csv
```

- 输出 CSV：`source,start,end,shot_scale,character_list,dialogue_text,confidence`。
- 三个来源按 `(source, start, end)` 区间交叠 join：person CSV + shot JSON + whisper JSON；**不解码视频、不建向量库**。
- 检索条件（AND）：`--need` 必须出现的人物、`--exclude` 排除人物、`--scale` 景别（可多次）、
  `--long-shot/--short-shot`、`--dialogue` 台词关键词（逗号=OR）、`--min-dur/--max-dur`。
- 局限：精度完全取决于上游 person/shot/whisper 的精度；同义词需自己列关键词（如"满洲里|大象"）。

### 9.7 edl_io.py — EDL / 时间轴互操作（缺陷6）

```powershell
python scripts/edl_io.py --timeline assets/elephant/build45/timeline_45s.json --fps 25 --out demo_out/demo.edl
python scripts/edl_io.py --read demo_out/demo.edl --fps 25 --out demo_out/timeline_from_edl.json
```

- `timeline_to_edl(tl, fps, title, reel)` → CMX3600 文本（TITLE/FCM/EVENT 最小子集）；
  `edl_to_timeline(text, fps)` → 内部 JSON（含 `segments` 与 `duration`）。
- 输入时间轴兼容 `sections`（`video` / `video_sequence`）和扁平 `segments` 两种结构。
- 局限：只支持 `C`（cut）事件与 V 轨，A 轨跳过；不支持 dissolve/wipe、变速、59.94 丢帧时间码
  （遇到 `DROP FRAME` 或复杂事件直接报错，不静默丢数据）。

### 9.8 quality_check_all.py — 综合巡检总入口（缺陷7）

```powershell
python scripts/quality_check_all.py `
  --timeline assets/elephant/build45/timeline_45s.json `
  --video-dir assets/elephant/raw --gallery assets/elephant/faces `
  --forbidden forbidden.json --bgm assets/elephant/bgm/志铭.m4a `
  --allow-jcut --blacklist-level block --outdir demo_out
```

- 一次跑完：人物黑名单命中、镜头节奏、叙事顺序、J-cut、禁止支线、音频指标、素材边界；
  输出 `quality_report.md`（人读）+ `quality_report.json`（机器可读），退出码 0/1/2 = PASS/WARN/FAIL。
- 参数：`--blacklist-level block|warn` 控制黑名单命中的级别；`--skip-person` / `--skip-shot` 可跳过耗时项；
  `--bgm` 存在时会做「原声实测 dB vs BGM 原始 dB + 计划增益」的遮盖风险估算。
- 排序约定：先跑 `person_scan` / `shot_analyze` 产出中间文件，再跑本入口最省时间（也可直接全量跑）。
- 局限：规则体检，不替代人眼审片；音频估算不代表真实混音，最终仍需 `video_qc.py` 与试听。

### 9.9 与旧脚本的关系（兼容约束）

- `win_asr.py`、`validate_45s.py` **未改动**；新模块是独立文件，可按需 `import`：
  `from person_scan import scan, load_gallery` / `from shot_analyze import analyze` /
  `from validate_narrative import validate` / `from audio_skill import audio_ducking` 等。
- 旧链路继续可用；推荐新链路：`person_scan` + `shot_analyze` → `material_retrieve` 选素材 →
  `validate_narrative` / `quality_check_all` 门禁 → `montage_edit.py` 渲染 → `video_qc.py` 复核。
- 所有新脚本默认**只读素材、只写分析文件**，不得在分析阶段渲染 mp4。

---

## 10. 脚本参数参考（2026-11-24 同步）

完整参数以 [CLI_REFERENCE.md](./CLI_REFERENCE.md) 为准（由 `scripts\*.py` 的 argparse 自动提取）。
高频参数速查：

| 脚本 | 关键参数 |
|---|---|
| `montage_edit.py` | `--edl`、`--out`、`--work` |
| `video_qc.py` | `--video`、`--out`、`--plan-json`、`--plan-duration`、`--tolerance`、`--max-freeze` |
| `render.py` | `--inputs`、`--out`、`--aspect {9:16,16:9,1:1,4:5}`、`--subtitle`、`--bgm`、`--bgm-gain-db`、`--fps`、`--qc` |
| `verify_asset.py` | `--url`、`--project-dir`、`--title`、`--source-name`、`--manifest-name` |
| `reference_analyze.py` | `--video`、`--out`、`--scene-threshold` |
| `shot_detect.py` | `--video`、`--start`、`--end`、`--json`、`--frames`、`--threshold`、`--min-len` |
| `shot_analyze.py` | `--video`、`--start`、`--end`、`--out`、`--frames`、`--threshold`、`--min-len`、`--sample-fps`、`--long-shot-sec` |
| `person_scan.py` | `--video`、`--start`、`--end`、`--gallery`、`--window`、`--fps`、`--min-score`、`--min-face`、`--sim-threshold`、`--frame-width`、`--out`、`--detail-json`、`--build-gallery`、`--spec`、`--video-dir` |
| `material_retrieve.py` | `--shots`、`--person`、`--person-csv`、`--person-detail`、`--whisper`、`--source`、`--need`、`--exclude`、`--scale`、`--long-shot`、`--short-shot`、`--dialogue`、`--min-dur`、`--max-dur`、`--avoid-json`、`--avoid-buffer`、`--no-fallback`、`--out` |
| `validate_narrative.py` | `--timeline`、`--shots`、`--forbidden`、`--emotion-script`、`--allow-jcut`、`--blacklist-level`、`--out`、`--md` |
| `quality_check_all.py` | `--timeline`、`--video-dir`、`--gallery`、`--forbidden`、`--bgm`、`--allow-jcut`、`--blacklist-level`、`--blacklist-buffer`、`--skip-person`、`--skip-shot`、`--outdir` |
| `edl_io.py` | `--timeline`、`--fps`、`--out`、`--read` |
| `publish_preview.py` | `--video`、`--platform`、`--account`、`--title`、`--description`、`--tags`、`--cover`、`--scheduled-at`、`--out` |
| `validate_45s.py` | `--timeline`、`--video`、`--voice`、`--forbidden`、`--report` |
| `win_asr.py` | `--video`、`--start`、`--end`、`--model`、`--out` |

> `render.py` 的 `--qc` 会在渲染后自动调用 `video_qc.py`；多段裁剪仍必须走 `montage_edit.py` + EDL。
> `video_qc.py` 的 `--plan-json` 接收 `montage_edit.py` 报告，`--plan-duration` 用于没有报告时直接给计划时长。
